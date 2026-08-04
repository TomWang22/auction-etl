"""Structural tests for the canonical reference page."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/2_Completeness_Reference.py"
)


def _tree() -> ast.Module:
    """Parse the current page."""
    return ast.parse(
        PAGE.read_text(
            encoding="utf-8"
        )
    )


def test_page_is_the_canonical_master_reference() -> None:
    """Page 2 renders the exact-pressing master before legacy tools."""
    tree = _tree()

    renderer = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_render_canonical_media_reference"
        ),
        None,
    )

    assert renderer is not None

    strings = {
        node.value
        for node in ast.walk(
            renderer
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    required_fragments = (
        "Pressing Completeness Reference",
        "Master reference",
        "Create exact pressing",
        "Assigned listings",
        "Audit history",
        "Preview reviewed changes",
        "Apply reviewed master reference",
        "PROFILE_CONTRACT ",
    )

    for fragment in required_fragments:
        assert any(
            fragment in value
            for value in strings
        )


def test_main_stops_after_rendering_canonical_page() -> None:
    """Legacy functions remain installed but are not rendered first."""
    tree = _tree()

    main_function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "main"
        ),
        None,
    )

    assert main_function is not None

    calls = [
        node
        for node in ast.walk(
            main_function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
        and node.func.id
        == "_render_canonical_media_reference"
    ]

    assert len(
        calls
    ) == 1

    returns = [
        node
        for node in ast.walk(
            main_function
        )
        if isinstance(
            node,
            ast.Return,
        )
    ]

    assert returns
    assert calls[0].lineno < min(
        node.lineno
        for node in returns
    )


def test_create_pressing_remains_available() -> None:
    """The master page still supports new exact-pressing records."""
    tree = _tree()

    renderer = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_canonical_render_create_pressing"
        ),
        None,
    )

    assert renderer is not None

    strings = {
        node.value
        for node in ast.walk(
            renderer
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    assert "_render_create_pressing" in strings
    assert "_create_pressing_panel" in strings


def test_listing_observations_are_not_master_reference_writes() -> None:
    """The canonical renderer calls only reference apply functions."""
    tree = _tree()

    renderer = next(
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name
        == "_render_canonical_media_reference"
    )

    call_names = set()

    for node in ast.walk(
        renderer
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if isinstance(
            node.func,
            ast.Name,
        ):
            call_names.add(
                node.func.id
            )
        elif isinstance(
            node.func,
            ast.Attribute,
        ):
            call_names.add(
                node.func.attr
            )

    assert (
        "_canonical_apply_reference_changes"
        in call_names
    )

    assert (
        "save_listing_observation_rows"
        not in call_names
    )

    assert (
        "replace_component_rows"
        not in call_names
    )
