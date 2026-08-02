"""Tests for the Collector Analytics Streamlit editor."""

from __future__ import annotations

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
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    required_calls = (
        "create_and_assign_pressing(",
        "assign_existing_pressing(",
        "replace_component_rows(",
        "save_condition(",
        "save_behavior(",
        "save_analysis_input(",
        "load_score_snapshot(",
    )

    for required_call in required_calls:
        assert required_call in source


def test_collector_review_has_analytics_tab() -> None:
    source = Path(
        "app/collector_review.py"
    ).read_text(
        encoding="utf-8"
    )

    assert '"Collector analytics"' in source
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


def test_component_editor_warns_about_pressing_scope() -> None:
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "Expected components belong to pressing"
        in source
    )
    assert (
        "apply to every listing"
        in source
    )
