"""Regression tests for Collector Review widget identity."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_APP = ROOT / "app/collector_review.py"


def parse_collector_app() -> ast.Module:
    """Parse the Collector Review application."""
    return ast.parse(
        COLLECTOR_APP.read_text(
            encoding="utf-8"
        )
    )


def pagination_function(
    tree: ast.Module,
) -> ast.FunctionDef:
    """Return render_pagination from the parsed source."""
    return next(
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "render_pagination"
        )
    )


def test_pagination_accepts_a_key_prefix() -> None:
    """Pagination must expose a widget-key namespace."""
    function = pagination_function(
        parse_collector_app()
    )

    parameter_names = {
        argument.arg
        for argument in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
        )
    }

    assert "key_prefix" in parameter_names


def test_every_pagination_button_key_uses_the_prefix() -> None:
    """Every pagination button key must include its namespace."""
    function = pagination_function(
        parse_collector_app()
    )

    buttons = [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "button"
        )
    ]

    assert buttons

    for button in buttons:
        key_keyword = next(
            (
                keyword
                for keyword in button.keywords
                if keyword.arg == "key"
            ),
            None,
        )

        assert key_keyword is not None
        assert "key_prefix" in ast.unparse(
            key_keyword.value
        )


def test_top_and_bottom_pagers_use_distinct_prefixes() -> None:
    """The two pager renderings must use distinct names."""
    source = COLLECTOR_APP.read_text(
        encoding="utf-8"
    )

    assert (
        "collector_pagination_top:"
        in source
    )
    assert (
        "collector_pagination_bottom:"
        in source
    )


def test_table_key_contains_filter_revision_and_row_signature() -> None:
    """Changing filters must create a fresh table element identity."""
    source = COLLECTOR_APP.read_text(
        encoding="utf-8"
    )

    assert "filter_revision" in source
    assert "row_signature" in source
    assert "hash_pandas_object" in source


def test_filter_widgets_have_explicit_state_keys() -> None:
    """Primary filters must not rely on auto-generated widget IDs."""
    source = COLLECTOR_APP.read_text(
        encoding="utf-8"
    )

    assert "FILTER_WIDGET_KEYS" in source
    assert (
        '"collector_filter_marketplace"'
        in source
    )
    assert (
        '"collector_filter_recent_only"'
        in source
    )
