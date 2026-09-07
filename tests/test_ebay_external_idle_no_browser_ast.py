"""Structural regression proof for external-only eBay browser isolation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

CRAWLER = "scripts/crawl_ebay_sources.py"


def string_constants(
    nodes: Iterable[ast.AST],
) -> set[str]:
    """Return all string literals beneath a node collection."""

    values: set[str] = set()

    for node in nodes:
        for descendant in ast.walk(
            node
        ):
            if (
                isinstance(
                    descendant,
                    ast.Constant,
                )
                and isinstance(
                    descendant.value,
                    str,
                )
            ):
                values.add(
                    descendant.value
                )

    return values


def function_named(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef:
    """Return one top-level function by name."""

    for node in tree.body:
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == name
        ):
            return node

    raise AssertionError(
        f"Function not found: {name}"
    )


def pending_handoff_if(
    main_function: ast.FunctionDef,
    source: str,
) -> ast.If:
    """Return the pending-raw-page decision chain."""

    for node in ast.walk(
        main_function
    ):
        if not isinstance(
            node,
            ast.If,
        ):
            continue

        expression = ast.get_source_segment(
            source,
            node.test,
        )

        if (
            expression is not None
            and "pending_ebay_raw_pages > 0"
            in expression
        ):
            return node

    raise AssertionError(
        "Pending eBay raw-page decision was not found."
    )


def test_external_idle_structurally_cannot_execute_browser_crawler() -> None:
    """Crawler must exist only in the browser-policy fallback branch."""

    source = RUNNER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(
            RUNNER
        ),
    )

    main_function = function_named(
        tree,
        "main",
    )

    handoff_if = pending_handoff_if(
        main_function,
        source,
    )

    assert len(
        handoff_if.orelse
    ) == 1

    external_if = handoff_if.orelse[
        0
    ]

    assert isinstance(
        external_if,
        ast.If,
    )

    external_test = ast.get_source_segment(
        source,
        external_if.test,
    )

    assert external_test is not None

    assert (
        "ebay_external_handoff_only"
        in external_test
    )

    pending_branch_strings = string_constants(
        handoff_if.body
    )

    external_idle_strings = string_constants(
        external_if.body
    )

    browser_fallback_strings = string_constants(
        external_if.orelse
    )

    assert (
        CRAWLER
        not in pending_branch_strings
    )

    assert (
        CRAWLER
        not in external_idle_strings
    )

    assert (
        CRAWLER
        in browser_fallback_strings
    )

    assert (
        "EBAY_EXTERNAL_HANDOFF_IDLE"
        in external_idle_strings
    )

    assert (
        "Existing eBay warehouse rows are preserved."
        in external_idle_strings
    )


def test_structured_handoff_precedes_external_idle_and_browser_fallback() -> None:
    """The decision chain must remain handoff -> idle -> browser fallback."""

    source = RUNNER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(
            RUNNER
        ),
    )

    main_function = function_named(
        tree,
        "main",
    )

    handoff_if = pending_handoff_if(
        main_function,
        source,
    )

    external_if = handoff_if.orelse[
        0
    ]

    assert isinstance(
        external_if,
        ast.If,
    )

    pending_strings = string_constants(
        handoff_if.body
    )

    external_strings = string_constants(
        external_if.body
    )

    fallback_strings = string_constants(
        external_if.orelse
    )

    assert any(
        "browser crawl skipped."
        in value
        for value in pending_strings
    )

    assert (
        "EBAY_EXTERNAL_HANDOFF_IDLE"
        in external_strings
    )

    assert (
        CRAWLER
        in fallback_strings
    )
