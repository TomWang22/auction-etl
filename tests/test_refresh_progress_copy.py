"""Marketplace refresh cards show processed progress, not discovery noise."""

from __future__ import annotations

from pathlib import Path

from auction_etl.services.refresh_progress_copy import (
    marketplace_card_captions,
    show_processed_metric,
    show_record_processing_bar,
)


INGEST_PAGE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)


def test_zero_new_complete_has_no_processed_or_complete_captions() -> None:
    """Incremental complete cards keep the checkmark, not 0/0 or Complete."""
    assert marketplace_card_captions(
        state="done",
        processed=0,
        new_records=0,
    ) == []


def test_new_discovery_shows_processed_progression() -> None:
    """New records get a processed-of-new line instead of discovered counts."""
    assert marketplace_card_captions(
        state="running",
        processed=1,
        new_records=74,
    ) == ["Processed 1 of 74"]

    assert marketplace_card_captions(
        state="done",
        processed=38,
        new_records=38,
    ) == ["Processed 38 of 38"]


def test_running_with_no_new_records_does_not_show_discovery() -> None:
    """While searching, do not advertise already-known discovery totals."""
    captions = marketplace_card_captions(
        state="running",
        processed=0,
        new_records=0,
    )
    assert captions == ["Looking for new sales…"]
    joined = " ".join(captions).casefold()
    assert "discovered" not in joined
    assert "already known" not in joined
    assert "complete" not in joined


def test_failure_reason_still_surfaces() -> None:
    """Blocked or failed marketplaces keep the reason, not Complete."""
    captions = marketplace_card_captions(
        state="unavailable",
        processed=0,
        new_records=0,
        reason="eBay programmatic access is blocked; continuing Gripsweat refresh.",
    )
    assert captions == [
        "eBay programmatic access is blocked; continuing Gripsweat refresh."
    ]


def test_processed_metric_and_bar_only_for_new_records_or_live_search() -> None:
    """Hide Processed 0/0 after an incremental refresh finds nothing new."""
    assert show_processed_metric(new_records=0) is False
    assert show_processed_metric(new_records=74) is True
    assert show_record_processing_bar(
        state="completed",
        new_records=0,
    ) is False
    assert show_record_processing_bar(
        state="running",
        new_records=0,
    ) is True
    assert show_record_processing_bar(
        state="completed",
        new_records=38,
    ) is True


def test_ingest_page_does_not_render_discovery_or_complete_captions() -> None:
    """The Streamlit cards must not print discovered/already known/Complete."""
    source = INGEST_PAGE.read_text(encoding="utf-8")
    assert "already known" not in source
    assert 'f"Discovered {discovered:,}' not in source
    assert "marketplace_card_captions(" in source
    render = source[
        source.index("def render_source_progress(") : source.index(
            "def failed_sources("
        )
    ]
    assert "source_state_label(" not in render
    assert "Complete" not in render
