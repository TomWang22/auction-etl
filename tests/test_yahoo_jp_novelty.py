"""Unit tests for Yahoo JP novelty stop helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from auction_etl.services.yahoo_jp_ingest import (
    page_is_all_older_or_equal,
    page_is_fully_known,
)


def test_page_is_fully_known_requires_nonempty_subset() -> None:
    assert page_is_fully_known([], {"a"}) is False
    assert page_is_fully_known(["a", "b"], {"a", "b", "c"}) is True
    assert page_is_fully_known(["a", "x"], {"a", "b"}) is False


def test_page_is_all_older_or_equal_uses_watermark() -> None:
    watermark = datetime(2026, 11, 1, tzinfo=timezone.utc)
    older = [
        {"closing_at": "2026-10-31T12:00:00+00:00"},
        {"closing_at": "2026-11-01T00:00:00+00:00"},
    ]
    newer = [
        {"closing_at": "2026-11-02T00:00:00+00:00"},
        {"closing_at": "2026-10-01T00:00:00+00:00"},
    ]
    assert page_is_all_older_or_equal(older, watermark) is True
    assert page_is_all_older_or_equal(newer, watermark) is False
    assert page_is_all_older_or_equal(older, None) is False
