"""Source contracts for the hover/click Collector Review grid."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


APP_PATH = Path("app/collector_review.py")
SUPPORT_PATH = Path("app/collector_review_support.py")
PROJECT_PATH = Path("pyproject.toml")


def function_source(
    source: str,
    name: str,
) -> str:
    """Return one top-level function's exact source."""
    tree = ast.parse(source)

    node = next(
        item
        for item in tree.body
        if isinstance(
            item,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and item.name == name
    )

    result = ast.get_source_segment(
        source,
        node,
    )

    assert result is not None
    return result


def test_aggrid_dependency_is_pinned() -> None:
    """The production dependency must be reproducible."""
    project = tomllib.loads(
        PROJECT_PATH.read_text(
            encoding="utf-8"
        )
    )

    dependencies = project["project"][
        "dependencies"
    ]

    assert (
        "streamlit-aggrid==1.2.1.post2"
        in dependencies
    )


def test_listing_grid_uses_click_selection() -> None:
    """Rows must be clickable without checkbox selection UI."""
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    table_source = function_source(
        source,
        "render_listing_table",
    )

    assert (
        "from st_aggrid import AgGrid, JsCode"
        in source
    )
    assert "AgGrid(" in table_source
    assert "st.dataframe(" not in table_source
    assert '"mode": "singleRow"' in table_source
    assert '"checkboxes": False' in table_source
    assert '"headerCheckbox": False' in table_source
    assert '"enableClickSelection": True' in table_source
    assert '"selectionChanged"' in table_source
    assert '"server_wins"' in table_source
    assert "should_grid_return" in table_source
    assert "rowDataChanged" in table_source
    assert "_grid_click_identity(" in table_source
    assert ".ag-row-hover" in table_source
    assert ".ag-row-selected" in table_source
    assert '"Review": [' not in table_source


def test_stable_identity_is_returned_by_grid() -> None:
    """The grid must return marketplace/listing identity."""
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    helper_source = function_source(
        SUPPORT_PATH.read_text(encoding="utf-8"),
        "_aggrid_selected_identity",
    )

    table_source = function_source(
        source,
        "render_listing_table",
    )

    assert "__identity" in table_source
    assert "grid_row_identity" in helper_source
    assert "_aggrid_selection_ids" in helper_source
    assert "_set_listing_identity(" in table_source
    assert '"rowClicked"' in table_source
    assert "__current_listing" in table_source
    assert "params.data.__selected" not in table_source
    assert '"field": "__selected"' not in table_source


def test_grid_row_identity_uses_visible_listing_columns() -> None:
    """Unmatched clicks still open the editor when AG Grid omits hidden fields."""
    from app.collector_review_support import grid_row_identity

    assert (
        grid_row_identity(
            {
                "Marketplace": "ebay",
                "Listing ID": 14665373254,
                "Title": "1991 Teresa Teng",
            }
        )
        == "ebay:14665373254"
    )
    assert (
        grid_row_identity(
            {"__identity": "buyee:n1245996680", "Listing ID": "ignored"}
        )
        == "buyee:n1245996680"
    )
    assert grid_row_identity({}) is None


class _GridResponse:
    """Minimal stand-in for an AG Grid return value."""

    def __init__(self, event_data):
        self.event_data = event_data
        self.selected_rows_id = None
        self.selected_rows = None


def test_row_data_refresh_does_not_count_as_a_click() -> None:
    """server_wins row replacement must not open or replace a listing."""
    from app.collector_review_support import _grid_click_identity

    assert (
        _grid_click_identity(
            _GridResponse(
                {
                    "source": "rowDataChanged",
                    "type": "selectionChanged",
                    "data": {"__identity": "ebay:800138386816"},
                }
            )
        )
        is None
    )


def test_row_click_opens_the_listing_identity() -> None:
    """A row click carries the listing identity even without selected rows."""
    from app.collector_review_support import _grid_click_identity

    assert (
        _grid_click_identity(
            _GridResponse(
                {
                    "streamlitRerunEventTriggerName": "rowClicked",
                    "data": {
                        "Marketplace": "ebay",
                        "Listing ID": "800138386816",
                        "__identity": "ebay:800138386816",
                    },
                }
            )
        )
        == "ebay:800138386816"
    )
    assert (
        _grid_click_identity(
            _GridResponse(
                {
                    "streamlitRerunEventTriggerName": "rowClicked",
                    "node": {"id": "buyee:n1245996680"},
                }
            )
        )
        == "buyee:n1245996680"
    )
