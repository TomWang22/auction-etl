"""Focused tests for complete and recent Collector Review exports."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pandas as pd

from app.collector_export import (
    ALL_COMBINED,
    ALL_SPLIT,
    build_export_payload,
    deduplicate_export_frame,
    full_export_frame,
    recent_ingestion_frame,
)


def sample_frame() -> pd.DataFrame:
    """Return historical, recent, native eBay, and Gripsweat rows."""
    return pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "188586715117",
                "_activity_source": "native-ebay",
                "_is_recent_addition": False,
                "title": "Native historical eBay LP",
                "seller": "facerecords",
                "artist_display": "Teresa Teng",
                "media_display": "LP",
                "catalog_display": "28TR-2057",
                "currency_display": "USD",
                "hammer_local": 37,
                "total_local": 37,
                "total_usd": 37,
                "bid_count_display": 7,
                "manual_collector_notes": "Complete with obi",
                "custom_ingestion_column": "historical-value",
            },
            {
                "marketplace": "gripsweat",
                "listing_id": "188586715117",
                "_activity_source": "gripsweat",
                "_is_recent_addition": False,
                "title": "Duplicate Gripsweat archive LP",
                "seller": "facerecords",
                "artist_display": "Teresa Teng",
                "media_display": "LP",
                "catalog_display": "28TR-2057",
                "currency_display": "USD",
                "hammer_local": 37,
                "total_local": 37,
                "total_usd": 37,
                "bid_count_display": 7,
                "manual_collector_notes": "Archive duplicate",
                "custom_ingestion_column": "duplicate-value",
            },
            {
                "marketplace": "buyee",
                "listing_id": "buyee-recent-123",
                "_activity_source": "buyee-watchlist",
                "_is_recent_addition": True,
                "title": "Recent Teresa Teng CD",
                "seller": "diskunion",
                "artist_display": "Teresa Teng",
                "media_display": "CD",
                "catalog_display": "TACL-2301",
                "currency_display": "JPY",
                "hammer_local": 7800,
                "tax_local": 0,
                "total_local": 7800,
                "total_usd": 52,
                "bid_count_display": 1,
                "manual_collector_notes": "Recent ingestion row",
                "custom_ingestion_column": "recent-value",
            },
        ]
    )


def test_recent_ingestion_uses_recent_flag() -> None:
    recent = recent_ingestion_frame(
        sample_frame()
    )

    assert len(recent) == 1
    assert (
        recent.iloc[0]["listing_id"]
        == "buyee-recent-123"
    )


def test_deduplication_prefers_native_ebay() -> None:
    result = deduplicate_export_frame(
        sample_frame()
    )

    assert len(result) == 2

    ebay = result[
        result["listing_id"]
        == "188586715117"
    ].iloc[0]

    assert ebay["marketplace"] == "ebay"
    assert (
        ebay["title"]
        == "Native historical eBay LP"
    )


def test_full_export_preserves_every_column() -> None:
    frame = full_export_frame(
        sample_frame()
    )

    assert (
        "manual_collector_notes"
        in frame.columns
    )

    assert (
        "custom_ingestion_column"
        in frame.columns
    )

    assert (
        "_is_recent_addition"
        in frame.columns
    )


def test_csv_contains_all_columns_and_recent_metadata() -> None:
    recent = recent_ingestion_frame(
        sample_frame()
    )

    (
        payload,
        filename,
        mime_type,
        count,
    ) = build_export_payload(
        recent,
        "CSV",
        ALL_COMBINED,
        "All recent ingestion",
    )

    decoded = payload.decode(
        "utf-8-sig"
    )

    assert count == 1
    assert filename.endswith(".csv")
    assert mime_type == "text/csv"
    assert "manual_collector_notes" in decoded
    assert "custom_ingestion_column" in decoded
    assert "_is_recent_addition" in decoded
    assert "recent-value" in decoded
    assert "historical-value" not in decoded


def test_media_split_zip_contains_lp_and_cd_files() -> None:
    frame = deduplicate_export_frame(
        sample_frame()
    )

    (
        payload,
        filename,
        mime_type,
        count,
    ) = build_export_payload(
        frame,
        "CSV",
        ALL_SPLIT,
        "Current filtered results",
    )

    with ZipFile(
        BytesIO(payload)
    ) as archive:
        names = archive.namelist()

    assert count == 2
    assert filename.endswith(".zip")
    assert mime_type == "application/zip"
    assert any(
        "-lp-" in name
        for name in names
    )
    assert any(
        "-cd-" in name
        for name in names
    )
