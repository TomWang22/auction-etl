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


def test_ebay_http_block_precedes_result_wait() -> None:
    """Blocked HTTP responses cannot enter eBay result waiting."""
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

    block_position = segment.index(
        "if status in {401, 403, 429}:"
    )
    signal_position = segment.index(
        "eBay rejected the deployed worker's request "
    )
    wait_position = segment.index(
        "wait_for_results("
    )

    assert (
        block_position
        < signal_position
        < wait_position
    )
