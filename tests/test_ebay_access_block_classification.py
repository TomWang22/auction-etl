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


def test_crawl_source_uses_nonfatal_page_evidence() -> None:
    """Access-block and empty-result diagnostics must not raise on screenshot."""
    source = CRAWLER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CRAWLER))
    crawl_source = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "crawl_source"
    )
    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_save_ebay_page_evidence"
    )
    crawl_segment = ast.get_source_segment(source, crawl_source) or ""
    helper_segment = ast.get_source_segment(source, helper) or ""

    assert "page.screenshot(" not in crawl_segment
    assert crawl_segment.count("_save_ebay_page_evidence(") >= 2
    assert "timeout=4_000" in helper_segment
    assert "full_page=False" in helper_segment
    assert "EBAY_CRAWL_PHASE=evidence_skip" in helper_segment


def test_ebay_page_evidence_survives_screenshot_timeout(
    tmp_path: Path,
) -> None:
    """HTML is kept even when Playwright hangs waiting for fonts on a 403 page."""
    from scripts import crawl_ebay_sources as crawler

    class BoomPage:
        def screenshot(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            raise TimeoutError("Timeout 8000ms exceeded.")

    html_path = tmp_path / "ebay_block.html"
    screenshot_path = tmp_path / "ebay_block.png"
    page = BoomPage()

    crawler._save_ebay_page_evidence(
        page,  # type: ignore[arg-type]
        "<html>403</html>",
        screenshot_path=screenshot_path,
        html_path=html_path,
    )

    assert html_path.read_text(encoding="utf-8") == "<html>403</html>"
    assert screenshot_path.exists() is False
    assert page.kwargs["timeout"] == 4_000
    assert page.kwargs["full_page"] is False
