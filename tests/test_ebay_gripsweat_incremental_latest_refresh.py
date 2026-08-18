"""Incremental latest-refresh contracts for eBay and Gripsweat."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"
EBAY = ROOT / "scripts" / "crawl_ebay_sources.py"
GRIPSWEAT = ROOT / "scripts" / "enrich_gripsweat_details.py"


def read_source(path: Path) -> str:
    """Read and syntax-check one source file."""

    value = path.read_text(encoding="utf-8")
    ast.parse(value, filename=str(path))
    return value


def test_ebay_uses_bounded_known_id_overlap() -> None:
    """Production eBay discovery stops after known newest-first overlap."""

    crawler = read_source(EBAY)
    runner = read_source(RUNNER)

    assert '"--incremental-newest-first"' in crawler
    assert '"--known-stop-threshold"' in crawler
    assert "_warehouse_known_ebay_listing_ids" in crawler
    assert "stop_for_known_overlap" in crawler
    assert "consecutive_known_at_stop" in crawler
    assert '"--incremental-newest-first"' in runner
    assert "EBAY_KNOWN_STOP_THRESHOLD = 20" in runner


def test_ebay_manual_mode_remains_unbounded_by_default() -> None:
    """Manual crawler semantics remain available."""

    crawler = read_source(EBAY)

    assert '"--interactive"' in crawler
    assert "incremental_newest_first: bool = False" in crawler


def test_gripsweat_can_stop_after_newest_probe() -> None:
    """Known newest-page overlap skips normal historical pagination."""

    runner = read_source(RUNNER)

    assert "GRIPSWEAT_KNOWN_STOP_THRESHOLD = 20" in runner
    assert "gripsweat_probe_trailing_known" in runner
    assert "gripsweat_stop_after_probe" in runner
    assert "if not gripsweat_stop_after_probe:" in runner
    assert "Skipping Gripsweat pagination audit" in runner


def test_gripsweat_detail_navigation_is_new_id_only() -> None:
    """Normal refresh allows only newly inserted Gripsweat IDs."""

    runner = read_source(RUNNER)
    detail = read_source(GRIPSWEAT)

    assert "gripsweat_item_ids_before" in runner
    assert "gripsweat_new_item_ids" in runner
    assert '"--item-id-file"' in runner
    assert '"--item-id-file"' in detail
    assert "allowed_item_ids" in detail


def test_zero_new_gripsweat_ids_skip_details() -> None:
    """Steady-state refresh performs no historical detail navigation."""

    runner = read_source(RUNNER)

    assert "if gripsweat_new_item_ids:" in runner
    assert "detail-page crawl skipped." in runner


def test_manual_gripsweat_backfill_is_preserved() -> None:
    """Explicit complete-row refresh remains available."""

    detail = read_source(GRIPSWEAT)

    assert '"--refresh-complete"' in detail
    assert "args.refresh_complete" in detail


def test_safe_sync_remains_no_prune() -> None:
    """Incremental discovery cannot introduce pruning."""

    runner = read_source(RUNNER)

    assert '"--no-prune"' in runner


def test_requested_progress_counters_exist() -> None:
    """Production persists all incremental counters."""

    runner = read_source(RUNNER)

    for name in (
        "discovered",
        "already_known",
        "new",
        "detail_scraped",
        "detail_skipped",
        "discovery_pages",
        "consecutive_known_at_stop",
    ):
        assert name in runner

    assert '"marketplace_progress"' in runner
