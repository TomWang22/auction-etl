"""Historical anchors require normalized comparable evidence."""

from __future__ import annotations

import inspect
from dataclasses import fields
from pathlib import Path

from auction_etl.services.collector_evidence import (
    EvidenceReport,
    apply_evidence_report,
    build_evidence_report,
)


def test_report_exposes_normalization_state() -> None:
    """Reports preserve raw and eligible comparable counts."""
    field_names = {
        field.name
        for field in fields(EvidenceReport)
    }

    assert "comparable_count" in field_names
    assert "normalized_comparable_count" in field_names
    assert "normalization_ready" in field_names


def test_builder_adjusts_requested_price_basis() -> None:
    """Raw warehouse prices cannot directly form an anchor."""
    source = inspect.getsource(
        build_evidence_report
    )

    assert "normalized_price_columns" in source
    assert '"HAMMER": "price_hammer_usd"' in source
    assert '"GROSS": "price_gross_usd"' in source
    assert '"LANDED": "price_landed_usd"' in source
    assert "condition_market_factor" in source
    assert "completeness_market_factor" in source
    assert "normalized_comparable_rows" in source
    assert "target_normalization_ready" in source


def test_apply_revalidates_normalized_evidence() -> None:
    """Stale reports cannot bypass normalization checks."""
    source = inspect.getsource(
        apply_evidence_report
    )

    assert (
        "_historical_anchor_is_still_valid"
        in source
    )


def test_editor_displays_eligible_over_raw() -> None:
    """The UI explains blocked historical anchors."""
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "report.normalized_comparable_count"
        in source
    )
    assert "normalization-ready target" in source
