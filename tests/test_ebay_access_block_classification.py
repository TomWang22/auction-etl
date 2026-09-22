"""Regression tests for deployed-worker eBay HTTP blocking."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.run_latest_auction_refresh import ebay_access_blocked


ROOT = Path(__file__).resolve().parents[1]
CRAWLER = ROOT / "scripts" / "crawl_ebay_sources.py"


def test_ebay_access_blocked_recognizes_deployed_worker_http_403() -> None:
    """Canonical deployed-worker HTTP failures are access blocks."""
    output = (
        "ERROR facerecords: "
        "eBay rejected the deployed worker's request with HTTP 403."
    )

    assert ebay_access_blocked(1, output) is True


def test_ebay_access_blocked_requires_nonzero_exit() -> None:
    """Successful crawler execution is not classified as blocked."""
    output = (
        "eBay rejected the deployed worker's request with HTTP 403."
    )

    assert ebay_access_blocked(0, output) is False


def test_ebay_result_wait_precedes_access_classification() -> None:
    """Commit HTTP status is not fatal until listing cards can render."""
    source = CRAWLER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(CRAWLER),
    )

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "crawl_source"
    ]

    assert len(functions) == 1

    segment = (
        ast.get_source_segment(
            source,
            functions[0],
        )
        or ""
    )

    wait_position = segment.index(
        "load_ebay_results_page("
    )
    classify_position = segment.index(
        "classify_ebay_page("
    )

    assert "if status in {401, 403, 429}:" not in segment
    assert wait_position < classify_position


def test_later_page_access_block_keeps_first_page_results() -> None:
    """Pagination 403 must stop the crawl without discarding page 1."""
    source = CRAWLER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(CRAWLER),
    )

    crawl_source = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "crawl_source"
    )
    main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "main"
    )

    crawl_segment = (
        ast.get_source_segment(
            source,
            crawl_source,
        )
        or ""
    )
    main_segment = (
        ast.get_source_segment(
            source,
            main,
        )
        or ""
    )

    blocked_at = crawl_segment.index(
        "MarketplaceAccessState.ACCESS_BLOCKED"
    )
    first_page_raise_at = crawl_segment.index(
        "if page_number == 1:",
        blocked_at,
    )
    later_stop_at = crawl_segment.index(
        "Stopping: later eBay page was not usable",
        first_page_raise_at,
    )
    later_break_at = crawl_segment.index(
        "break",
        later_stop_at,
    )

    assert first_page_raise_at < later_stop_at < later_break_at
    assert "Keeping already captured pages." in crawl_segment

    fail_at = main_segment.index(
        "Crawl failed; reports will"
    )
    condition = main_segment[
        main_segment.rindex(
            "if (",
            0,
            fail_at,
        ):fail_at
    ]

    assert "stats.pages_processed == 0" in condition
    assert "stats.failed_sources" in condition
    assert "stats.blocked_sources" not in condition
