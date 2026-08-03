"""Tests for evidence-backed collector proposals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from auction_etl.services.collector_evidence import (
    extract_exact_condition_grade,
    median_decimal,
    select_closing_window,
)


def test_exact_condition_code_is_detected() -> None:
    """An explicit canonical token is safe."""
    assert extract_exact_condition_grade(
        "Media: VG+ / Sleeve: VG",
        ("M", "NM", "EX", "VG+", "VG", "G"),
    ) == "VG+"


def test_near_mint_alias_is_detected() -> None:
    """A complete standard phrase maps conservatively."""
    assert extract_exact_condition_grade(
        "Record is Near Mint",
        ("M", "NM", "EX", "VG"),
    ) == "NM"


def test_vague_condition_is_not_inferred() -> None:
    """Vague seller language must remain unnormalized."""
    assert extract_exact_condition_grade(
        "ほぼ美盤・年代物として良好",
        ("M", "NM", "EX", "VG+", "VG"),
    ) is None


def test_grade_letter_is_not_taken_from_word() -> None:
    """Single-letter grades need token boundaries."""
    assert extract_exact_condition_grade(
        "Complete cassette collection",
        ("M", "E", "G"),
    ) is None


def test_decimal_median_odd_sample() -> None:
    assert median_decimal(
        (
            Decimal("10"),
            Decimal("30"),
            Decimal("20"),
        )
    ) == Decimal("20.0000")


def test_decimal_median_even_sample() -> None:
    assert median_decimal(
        (
            Decimal("10"),
            Decimal("20"),
            Decimal("30"),
            Decimal("40"),
        )
    ) == Decimal("25.0000")


def test_closing_window_uses_latest_valid_snapshot() -> None:
    closing_at = datetime(
        2026,
        8,
        2,
        20,
        0,
        tzinfo=timezone.utc,
    )

    proposal = select_closing_window(
        (
            {
                "id": 1,
                "captured_at":
                    closing_at
                    - timedelta(minutes=120),
                "price_local": Decimal("4000"),
                "currency": "JPY",
                "source": "crawler",
            },
            {
                "id": 2,
                "captured_at":
                    closing_at
                    - timedelta(minutes=30),
                "price_local": Decimal("5000"),
                "currency": "JPY",
                "source": "crawler",
            },
        ),
        closing_at=closing_at,
        final_price=Decimal("8750"),
        currency="JPY",
        maximum_minutes=180,
    )

    assert proposal is not None
    assert proposal.snapshot_id == 2
    assert (
        proposal.minutes_before_close
        == 30
    )
    assert (
        proposal.escalation_ratio
        == Decimal("0.75000000")
    )


def test_stale_snapshot_is_rejected() -> None:
    closing_at = datetime(
        2026,
        8,
        2,
        20,
        0,
        tzinfo=timezone.utc,
    )

    assert select_closing_window(
        (
            {
                "id": 1,
                "captured_at":
                    closing_at
                    - timedelta(hours=12),
                "price_local": Decimal("5000"),
                "currency": "JPY",
                "source": "crawler",
            },
        ),
        closing_at=closing_at,
        final_price=Decimal("8750"),
        currency="JPY",
        maximum_minutes=180,
    ) is None


def test_currency_mismatch_is_rejected() -> None:
    closing_at = datetime(
        2026,
        8,
        2,
        20,
        0,
        tzinfo=timezone.utc,
    )

    assert select_closing_window(
        (
            {
                "id": 1,
                "captured_at":
                    closing_at
                    - timedelta(minutes=30),
                "price_local": Decimal("50"),
                "currency": "USD",
                "source": "crawler",
            },
        ),
        closing_at=closing_at,
        final_price=Decimal("8750"),
        currency="JPY",
        maximum_minutes=180,
    ) is None


def test_streamlit_wires_evidence_assistant() -> None:
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "build_evidence_report(",
        "apply_evidence_report(",
        "Evidence-backed suggestions",
        "Exact condition tokens only",
        "Nothing will be fabricated",
    )

    for fragment in required:
        assert fragment in source
