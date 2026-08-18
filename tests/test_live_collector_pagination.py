"""Regression tests for Collector Review navigation and row selection."""

from __future__ import annotations

import ast
from pathlib import Path

from app.collector_review_support import (
    listing_identity,
    listing_option_label,
)


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_APP = ROOT / "app/collector_review.py"


def source_text() -> str:
    """Return the Collector Review source."""
    return COLLECTOR_APP.read_text(
        encoding="utf-8"
    )


def parse_collector_app() -> ast.Module:
    """Parse the Collector Review application."""
    return ast.parse(
        source_text()
    )


def named_function(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef:
    """Return one named function."""
    return next(
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        )
    )


def test_pagination_accepts_a_key_prefix() -> None:
    """Pagination must expose a widget-key namespace."""
    function = named_function(
        parse_collector_app(),
        "render_pagination",
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
    function = named_function(
        parse_collector_app(),
        "render_pagination",
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


def test_results_use_one_pagination_bar() -> None:
    """The redesigned results should not duplicate pagination."""
    source = source_text()

    assert (
        source.count(
            "render_pagination("
        )
        == 2
    )
    assert (
        "collector_pagination_bottom:"
        not in source
    )




def test_listing_table_uses_single_row_selection() -> None:
    """The complete AG Grid row must drive review selection."""
    source = source_text()

    required_fragments = (
        "from st_aggrid import AgGrid, JsCode",
        "def _aggrid_selected_identity(",
        "AgGrid(",
        '"mode": "singleRow"',
        '"checkboxes": False',
        '"headerCheckbox": False',
        '"enableClickSelection": True',
        '"selectionChanged"',
        ".ag-row-hover",
        ".ag-row-selected",
        "_set_listing_identity(",
    )

    for fragment in required_fragments:
        assert fragment in source

    assert 'on_select="rerun"' not in source
    assert 'selection_mode="single-row"' not in source




def test_sidebar_jump_is_searchable_and_stable() -> None:
    """A sidebar jump control must share stable identity state."""
    source = source_text()

    required = (
        "Find a listing",
        "JUMP_LISTING_KEY",
        "SELECTED_LISTING_KEY",
        "PENDING_JUMP_LISTING_KEY",
        "listing_option_label",
        "render_listing_jump(",
    )

    for value in required:
        assert value in source




def test_table_pins_identity_columns() -> None:
    """Horizontal scrolling must preserve listing identity."""
    source = source_text()

    for column in (
        "Marketplace",
        "Listing ID",
        "Title",
    ):
        marker = (
            f'"field": "{column}"'
        )

        assert marker in source

        start = source.index(
            marker
        )

        column_definition = source[
            start : start + 600
        ]

        assert (
            '"pinned": "left"'
            in column_definition
        )
        assert (
            '"lockPinned": True'
            in column_definition
        )




def test_detached_listing_dropdown_is_removed() -> None:
    """The old below-table selector must not remain."""
    source = source_text()

    assert (
        "Select a listing to review"
        not in source
    )
    assert (
        "Choose a listing above"
        not in source
    )
    assert (
        "PLACEHOLDER_LISTING"
        not in source
    )


def test_table_key_contains_selection_revision() -> None:
    """External jumps must reset stale native row selections."""
    source = source_text()

    assert (
        "table_selection_revision"
        in source
    )
    assert (
        "TABLE_SELECTION_REVISION_KEY"
        in source
    )
    assert "row_signature" in source
    assert "filter_revision" in source


def test_listing_identity_is_stable() -> None:
    """Marketplace and listing ID form the stable review key."""
    assert (
        listing_identity(
            "Buyee",
            "abc123",
        )
        == "buyee:abc123"
    )


def test_listing_option_label_is_searchable() -> None:
    """Jump labels include the searchable business identity."""
    label = listing_option_label(
        marketplace="buyee",
        listing_id="abc123",
        seller="records-jp",
        title="Teresa Teng LP",
    )

    assert label == (
        "BUYEE · abc123 · records-jp · Teresa Teng LP"
    )
