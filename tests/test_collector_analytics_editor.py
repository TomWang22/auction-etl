"""Tests for the Collector Analytics Streamlit editor."""

from __future__ import annotations

import ast

from pathlib import Path

import pandas as pd

from app.collector_analytics_editor import (
    _select_index,
    select_listing_record,
)
from app.collector_review_support import (
    listing_identity,
)


def test_select_listing_record_uses_stable_identity() -> None:
    records = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "111",
                "title": "First",
            },
            {
                "marketplace": "buyee",
                "listing_id": "q222",
                "title": "Second",
            },
        ]
    )

    selected = select_listing_record(
        records,
        listing_identity(
            "buyee",
            "q222",
        ),
    )

    assert selected is not None
    assert selected["title"] == "Second"


def test_select_listing_record_returns_none_without_selection() -> None:
    records = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "111",
            }
        ]
    )

    assert select_listing_record(
        records,
        None,
    ) is None


def test_select_index_falls_back_to_first_option() -> None:
    assert _select_index(
        ["A", "B"],
        "missing",
    ) == 0


def test_editor_preserves_buyee_bidder_uncertainty() -> None:
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert '"NOT_EXPOSED"' in source
    assert "Buyee/Yahoo Japan" in source
    assert "distinct-human bidder count" in source


def test_editor_wires_all_curation_services() -> None:
    """The editor wires each independent persistence scope."""
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    required_calls = (
        "create_and_assign_pressing(",
        "assign_existing_pressing(",
        "load_pressing_reference_rows(",
        "save_pressing_reference_rows(",
        "load_listing_observation_rows(",
        "save_listing_observation_rows(",
        "save_condition(",
        "save_behavior(",
        "save_analysis_input(",
        "load_score_snapshot(",
    )

    for required_call in required_calls:
        assert required_call in source

    assert "replace_component_rows(" not in source


def test_collector_review_has_analytics_tab() -> None:
    source = Path(
        "app/collector_review.py"
    ).read_text(
        encoding="utf-8"
    )

    assert '"Insights"' in source
    assert '"Collection insights"' in source
    assert "with tabs[3]:" in source
    assert "render_collector_analytics_editor(" in source
    assert (
        "render_collector_analytics_editor("
        in source
    )
    assert (
        "# collector-analytics-editor:start"
        in source
    )
    assert (
        "# collector-analytics-editor:end"
        in source
    )


def test_component_editor_separates_pressing_and_listing_scope() -> None:
    """The component editor keeps persistence scopes independent."""
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    editor_function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_component_editor"
        ),
        None,
    )

    assert editor_function is not None

    string_literals = {
        node.value
        for node in ast.walk(editor_function)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }

    call_names: set[str] = set()

    for node in ast.walk(editor_function):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name):
            call_names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            call_names.add(node.func.attr)

    assert "Pressing completeness reference" in string_literals
    assert "This listing's observations" in string_literals
    assert "Save verified pressing reference" in string_literals
    assert "Save this listing's observations" in string_literals

    assert "save_pressing_reference_rows" in call_names
    assert "save_listing_observation_rows" in call_names
    assert "replace_component_rows" not in call_names
