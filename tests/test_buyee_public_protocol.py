"""Regression tests for the public Buyee producer/consumer protocol."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

CRAWLER = (
    ROOT
    / "scripts"
    / "crawl_buyee_public_sources.py"
)

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

MARKER_NAME = (
    "BUYEE_PUBLIC_AUTHENTICATION_REDIRECT_MARKER"
)

MARKER_VALUE = (
    "BUYEE_PUBLIC_RESULT=AUTHENTICATION_REDIRECT"
)


def _parse(
    path: Path,
) -> ast.Module:
    """Parse one production module."""

    return ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(
            path
        ),
    )


def _assignment_name(
    node: ast.Assign | ast.AnnAssign,
) -> str | None:
    """Return a simple assignment target."""

    if isinstance(
        node,
        ast.AnnAssign,
    ):
        target = node.target
    else:
        if len(
            node.targets
        ) != 1:
            return None

        target = node.targets[0]

    if isinstance(
        target,
        ast.Name,
    ):
        return target.id

    return None


def _main(
    tree: ast.Module,
) -> ast.FunctionDef:
    """Return one top-level main function."""

    matches = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "main"
        )
    ]

    assert len(
        matches
    ) == 1

    return matches[0]


def test_public_buyee_crawler_emits_authentication_redirect_marker() -> None:
    """Authentication redirects expose the canonical machine result."""

    tree = _parse(
        CRAWLER
    )

    matching_prints = []

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not (
            isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "print"
        ):
            continue

        strings = {
            child.value
            for child in ast.walk(
                node
            )
            if (
                isinstance(
                    child,
                    ast.Constant,
                )
                and isinstance(
                    child.value,
                    str,
                )
            )
        }

        if MARKER_VALUE in strings:
            matching_prints.append(
                node
            )

    assert len(
        matching_prints
    ) == 1


def test_runner_marker_matches_crawler_protocol() -> None:
    """The production consumer uses the crawler's exact result marker."""

    tree = _parse(
        RUNNER
    )

    assignments = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                (
                    ast.Assign,
                    ast.AnnAssign,
                ),
            )
            and _assignment_name(
                node
            )
            == MARKER_NAME
        )
    ]

    assert len(
        assignments
    ) == 1

    assignment = assignments[0]

    strings = {
        child.value
        for child in ast.walk(
            assignment
        )
        if (
            isinstance(
                child,
                ast.Constant,
            )
            and isinstance(
                child.value,
                str,
            )
        )
    }

    assert strings == {
        MARKER_VALUE,
    }


def test_runner_classifies_authentication_redirect_using_canonical_marker() -> None:
    """Buyee auth classification consumes normalized crawler output."""

    tree = _parse(
        RUNNER
    )

    main = _main(
        tree
    )

    assignments = [
        node
        for node in ast.walk(
            main
        )
        if (
            isinstance(
                node,
                (
                    ast.Assign,
                    ast.AnnAssign,
                ),
            )
            and _assignment_name(
                node
            )
            == "buyee_authentication_required"
        )
    ]

    assert len(
        assignments
    ) == 1

    assignment = assignments[0]

    assert assignment.value is not None

    names = {
        child.id
        for child in ast.walk(
            assignment.value
        )
        if isinstance(
            child,
            ast.Name,
        )
    }

    strings = {
        child.value
        for child in ast.walk(
            assignment.value
        )
        if (
            isinstance(
                child,
                ast.Constant,
            )
            and isinstance(
                child.value,
                str,
            )
        )
    }

    assert MARKER_NAME in names
    assert "normalized_buyee_output" in names
    assert "AUTHENTICATION_REQUIRED" not in strings
