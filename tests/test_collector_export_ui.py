"""Focused tests for Collector Review exports."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from app.collector_export import (
    ALL_COMBINED,
    build_export_payload,
    dataframe_to_export_rows,
    deduplicate_export_frame,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "188586715117",
                "_activity_source": "native-ebay",
                "title": "Native eBay LP",
                "seller": "facerecords",
                "artist_display": "Teresa Teng",
                "media_display": "LP",
                "catalog_display": "28TR-2057",
                "currency_display": "USD",
                "hammer_local": 37,
                "total_local": 37,
                "total_usd": 37,
                "bid_count_display": 7,
            },
            {
                "marketplace": "gripsweat",
                "listing_id": "188586715117",
                "_activity_source": "gripsweat",
                "title": "Duplicate archive LP",
                "seller": "facerecords",
                "artist_display": "Teresa Teng",
                "media_display": "LP",
                "catalog_display": "28TR-2057",
                "currency_display": "USD",
                "hammer_local": 37,
                "total_local": 37,
                "total_usd": 37,
                "bid_count_display": 7,
            },
            {
                "marketplace": "buyee",
                "listing_id": "buyee-123",
                "_activity_source": "buyee-watchlist",
                "title": "Teresa Teng CD",
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
            },
        ]
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
    assert ebay["title"] == "Native eBay LP"


def test_dataframe_adapter_maps_collector_fields() -> None:
    rows = dataframe_to_export_rows(
        deduplicate_export_frame(
            sample_frame()
        )
    )

    assert rows[0]["media_type"] == "LP"
    assert rows[0]["catalog_number"] == "28TR-2057"
    assert rows[0]["hammer_price_local"] == Decimal("37")
    assert rows[1]["media_type"] == "CD"


def test_combined_csv_payload_contains_filtered_rows() -> None:
    payload, filename, mime_type, count = (
        build_export_payload(
            deduplicate_export_frame(
                sample_frame()
            ),
            "CSV",
            ALL_COMBINED,
        )
    )

    decoded = payload.decode("utf-8-sig")

    assert count == 2
    assert filename.endswith(".csv")
    assert mime_type == "text/csv"
    assert "188586715117" in decoded
    assert "buyee-123" in decoded
    assert "Duplicate archive LP" not in decoded
