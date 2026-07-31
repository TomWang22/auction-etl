"""Tests for main Collector Review activity and Gripsweat integration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from auction_etl.reporting.main_review_integration import (
    gripsweat_original_listing_id,
    integrate_recent_activity,
    parse_gripsweat_sold_at,
    parse_gripsweat_title,
)


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_APP = ROOT / "app/collector_review.py"


def test_added_date_does_not_fabricate_closed_date() -> None:
    """A new row uses activity metadata while its real close stays missing."""
    dataframe = pd.DataFrame(
        [
            {
                "marketplace": "buyee",
                "listing_id": "new-1",
                "closing_display": pd.NaT,
                "ended_at": pd.NaT,
            },
            {
                "marketplace": "buyee",
                "listing_id": "old-1",
                "closing_display":
                    "2026-07-22T12:00:00+00:00",
                "ended_at":
                    "2026-07-22T12:00:00+00:00",
            },
        ]
    )

    metadata = [
        {
            "marketplace": "buyee",
            "listing_id": "new-1",
            "first_seen_at":
                datetime(
                    2026,
                    7,
                    30,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
            "last_seen_at":
                datetime(
                    2026,
                    7,
                    30,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
            "first_seen_source":
                "new-only-export",
            "last_seen_source":
                "new-only-export",
        },
        {
            "marketplace": "buyee",
            "listing_id": "old-1",
            "first_seen_at":
                datetime(
                    2026,
                    7,
                    1,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            "last_seen_at":
                datetime(
                    2026,
                    7,
                    30,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
            "first_seen_source":
                "historical-backfill",
            "last_seen_source":
                "refresh",
        },
    ]

    integrated = integrate_recent_activity(
        dataframe,
        metadata_rows=metadata,
    )

    new_row = integrated.loc[
        integrated["listing_id"] == "new-1"
    ].iloc[0]

    old_row = integrated.loc[
        integrated["listing_id"] == "old-1"
    ].iloc[0]

    assert pd.isna(
        new_row["closing_display"]
    )
    assert pd.isna(
        new_row["ended_at"]
    )
    assert (
        new_row["_activity_date_basis"]
        == "ADDED"
    )
    assert new_row["_ingestion_status"] == "NEW"
    assert pd.notna(
        new_row["_activity_sort"]
    )

    assert (
        old_row["_activity_date_basis"]
        == "CLOSED"
    )
    assert pd.notna(
        old_row["closing_display"]
    )


def test_activity_sort_places_new_unclosed_rows_first() -> None:
    """Recent additions participate in activity sorting."""
    dataframe = pd.DataFrame(
        [
            {
                "marketplace": "buyee",
                "listing_id": "closed",
                "closing_display":
                    "2026-07-22T12:00:00+00:00",
            },
            {
                "marketplace": "buyee",
                "listing_id": "added",
                "closing_display": pd.NaT,
            },
        ]
    )

    metadata = [
        {
            "marketplace": "buyee",
            "listing_id": "closed",
            "first_seen_at":
                "2026-07-22T12:00:00+00:00",
            "last_seen_at":
                "2026-07-22T12:00:00+00:00",
            "first_seen_source":
                "historical-backfill",
            "last_seen_source":
                "historical-backfill",
        },
        {
            "marketplace": "buyee",
            "listing_id": "added",
            "first_seen_at":
                "2026-07-30T18:00:00+00:00",
            "last_seen_at":
                "2026-07-30T18:00:00+00:00",
            "first_seen_source":
                "new-only-export",
            "last_seen_source":
                "new-only-export",
        },
    ]

    integrated = integrate_recent_activity(
        dataframe,
        metadata_rows=metadata,
    )

    assert integrated.iloc[0][
        "listing_id"
    ] == "added"


def test_gripsweat_archive_parsing() -> None:
    """Archived Gripsweat card text yields stable sale fields."""
    raw_text = (
        "Anita Mui 梅艷芳 LP "
        "$74.99 $42.00 (USD) May 23, 2026"
    )
    url = (
        "https://gripsweat.com/item/287290308220/"
        "anita-mui-self-titled"
    )

    assert (
        gripsweat_original_listing_id(url)
        == "287290308220"
    )
    assert (
        parse_gripsweat_title(
            None,
            raw_text,
        )
        == "Anita Mui 梅艷芳 LP"
    )

    sold_at = parse_gripsweat_sold_at(
        raw_text
    )

    assert sold_at.isoformat().startswith(
        "2026-05-23"
    )


def test_main_page_has_reactive_filter_contract() -> None:
    """Marketplace changes must invalidate dependent UI state."""
    source = COLLECTOR_APP.read_text(
        encoding="utf-8"
    )

    required = (
        "load_gripsweat_records",
        "Recent additions only",
        "_marketplace_changed",
        "on_change=_marketplace_changed",
        "_filter_revision",
        "_activity_sort",
        '"Added"',
        '"Date basis"',
    )

    for value in required:
        assert value in source

    assert (
        'filtered["closing_display"]'
        ".dt.date"
        not in source
    )


def test_update_status_coalesces_duplicate_labels() -> None:
    """Update-status datetime selection must return one Series."""
    source = COLLECTOR_APP.read_text(
        encoding="utf-8"
    )

    assert (
        "def "
        "_coalesce_duplicate_named_column("
        in source
    )
    assert (
        "_coalesce_duplicate_named_column("
        "recent, updated_column"
        ")"
        in source
    )
