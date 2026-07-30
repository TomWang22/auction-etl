"""Tests for recent-ingestion classification and export formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from auction_etl.reporting.recent_ingestion import (
    CSVExportOptions,
    REPORT_PRESETS,
    classify_identities,
    partition_export_identities,
    write_formatted_csv,
)


def test_identity_classification_uses_the_baseline() -> None:
    """New and refreshed rows must remain mutually meaningful."""
    baseline = {
        ("buyee", "old-1"),
        ("buyee", "old-2"),
        ("ebay", "ebay-1"),
    }
    warehouse = baseline | {
        ("buyee", "new-1"),
        ("buyee", "new-2"),
    }
    staging = {
        ("buyee", "old-1"),
        ("buyee", "new-1"),
        ("buyee", "pending-1"),
        ("ebay", "ebay-1"),
    }

    result = classify_identities(
        baseline,
        warehouse,
        staging,
    )

    assert result.newly_ingested == {
        ("buyee", "new-1"),
        ("buyee", "new-2"),
    }
    assert result.refreshed_existing == {
        ("buyee", "old-1"),
        ("ebay", "ebay-1"),
    }
    assert result.pending == {
        ("buyee", "pending-1"),
    }
    assert not result.missing_from_warehouse


def test_formatted_csv_supports_excel_bom_and_dates() -> None:
    """CSV rendering should preserve Unicode and requested formats."""
    payload = write_formatted_csv(
        [
            {
                "title": "テレサ・テン",
                "amount": Decimal("12.345"),
                "seen": datetime(
                    2026,
                    7,
                    30,
                    15,
                    0,
                    tzinfo=timezone.utc,
                ),
            }
        ],
        columns=(
            "title",
            "amount",
            "seen",
        ),
        options=CSVExportOptions(
            delimiter=";",
            quote_style="all",
            include_bom=True,
            date_format="date",
            decimal_places=2,
        ),
    )

    assert payload.startswith(
        b"\xef\xbb\xbf"
    )

    decoded = payload.decode(
        "utf-8-sig"
    )

    assert '"テレサ・テン"' in decoded
    assert '"12.34"' in decoded
    assert '"2026-07-30"' in decoded


def test_report_presets_contain_identity_fields() -> None:
    """Every standard preset must retain stable identity fields."""
    for fields in REPORT_PRESETS.values():
        assert "marketplace" in fields
        assert "listing_id" in fields

def test_export_identity_partition_removes_overlap() -> None:
    """New identities must not also be counted as refreshed."""
    newly_ingested, refreshed = partition_export_identities(
        {
            ("buyee", "new-1"),
            ("buyee", "new-2"),
        },
        {
            ("buyee", "old-1"),
            ("buyee", "new-1"),
            ("ebay", "old-2"),
        },
    )

    assert newly_ingested == (
        ("buyee", "new-1"),
        ("buyee", "new-2"),
    )
    assert refreshed == (
        ("buyee", "old-1"),
        ("ebay", "old-2"),
    )
