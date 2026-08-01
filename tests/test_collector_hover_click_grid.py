"""Source contracts for the hover/click Collector Review grid."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


APP_PATH = Path("app/collector_review.py")
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
    assert ".ag-row-hover" in table_source
    assert ".ag-row-selected" in table_source
    assert '"Review": [' not in table_source


def test_stable_identity_is_returned_by_grid() -> None:
    """The grid must return marketplace/listing identity."""
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    helper_source = function_source(
        source,
        "_aggrid_selected_identity",
    )

    table_source = function_source(
        source,
        "render_listing_table",
    )

    assert "__identity" in helper_source
    assert "__identity" in table_source
    assert "_set_listing_identity(" in table_source
