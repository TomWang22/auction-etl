"""Daily refresh lookback cutoffs from warehouse ending timestamps."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from auction_etl.services.refresh_lookback import (
    coerce_sale_date,
    normalize_lookback_days,
    page_is_at_or_before_cutoff,
)


def test_normalize_lookback_days_defaults_and_clamps() -> None:
    assert normalize_lookback_days(None) == 3
    assert normalize_lookback_days(0) == 1
    assert normalize_lookback_days(2) == 2


def test_page_lookback_requires_dated_evidence() -> None:
    cutoff = date(2026, 11, 16)
    assert page_is_at_or_before_cutoff([], cutoff) is False
    assert page_is_at_or_before_cutoff([None, None], cutoff) is False
    assert (
        page_is_at_or_before_cutoff(
            ["2026-11-19", "2026-11-18"],
            cutoff,
        )
        is False
    )
    assert (
        page_is_at_or_before_cutoff(
            ["2026-11-16", "2026-11-10"],
            cutoff,
        )
        is True
    )


def test_coerce_sale_date_accepts_datetime_and_iso() -> None:
    assert coerce_sale_date("2026-11-19") == date(2026, 11, 19)
    assert coerce_sale_date(
        datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    ) == date(2026, 11, 19)
    assert coerce_sale_date("not-a-date") is None


def test_cutoff_math_matches_three_day_floor() -> None:
    newest = date(2026, 12, 3)
    assert newest - timedelta(days=3) == date(2026, 11, 30)
