"""Regression tests for external structured-eBay raw-page handoff."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)


def runner_source() -> str:
    """Return syntactically valid latest-refresh source."""
    source = RUNNER.read_text(
        encoding="utf-8",
    )
    ast.parse(
        source,
        filename=str(RUNNER),
    )
    return source


def test_runner_counts_only_external_unparsed_ebay_raw_pages() -> None:
    """Select only pending pages produced by the structured importer."""
    source = runner_source()

    assert (
        "def unparsed_external_ebay_raw_page_count("
        in source
    )
    assert "FROM raw.page" in source
    assert "WHERE source = 'ebay'" in source
    assert "AND parsed_at IS NULL" in source
    assert (
        "AND url LIKE 'collector://ebay/%%'"
        in source
    )
    assert (
        'unparsed_external_ebay_raw_page_count(\n'
        '                    connection\n'
        '                )'
        in source
    )


def test_generic_unparsed_ebay_page_does_not_define_external_handoff() -> None:
    """Do not mistake abandoned browser-crawl pages for external input."""
    source = runner_source()

    assert "def unparsed_raw_page_count(" not in source
    assert (
        "url LIKE 'collector://ebay/%%'"
        in source
    )


def test_external_raw_pages_precede_browser_crawl() -> None:
    """Consume imported eBay pages before attempting Railway browsing."""
    source = runner_source()

    pending = source.index(
        "if pending_ebay_raw_pages > 0:"
    )
    crawler = source.index(
        '"scripts/crawl_ebay_sources.py"',
        pending,
    )

    assert pending < crawler
    assert (
        "browser crawl skipped."
        in source[pending:crawler]
    )


def test_external_raw_pages_use_existing_ingestion_pipeline() -> None:
    """Feed external records through parser, normalizer, and safe sync."""
    source = runner_source()

    assert "def process_ebay_raw_pages(" in source
    assert '"parse",' in source
    assert '"source",' in source
    assert '"ebay",' in source
    assert '"normalize",' in source
    assert '"staging",' in source
    assert '"sync",' in source
    assert '"warehouse",' in source
    assert '"--marketplace",' in source
    assert '"--no-prune",' in source


def test_ebay_parser_is_marketplace_scoped() -> None:
    """Never consume unrelated pending raw pages from the eBay branch."""
    source = runner_source()

    helper_start = source.index(
        "def process_ebay_raw_pages("
    )
    helper_end = source.index(
        "\n\ndef ",
        helper_start + 1,
    )
    helper = source[
        helper_start:helper_end
    ]

    assert (
        '"parse",\n'
        '            "source",\n'
        '            "ebay",'
        in helper
    )

    assert (
        '"parse",\n'
        '            "latest",'
        not in helper
    )


def test_browser_crawler_remains_fallback() -> None:
    """Preserve current Railway crawler when no imported page is waiting."""
    source = runner_source()

    assert (
        "else:\n"
        "            for source_name in enabled_ebay_sources("
        in source
    )
    assert '"scripts/crawl_ebay_sources.py"' in source
    assert '"--incremental-newest-first"' in source
    assert '"--known-stop-threshold"' in source


def test_existing_access_block_semantics_remain() -> None:
    """Keep degraded and strict crawler-failure contracts intact."""
    source = runner_source()

    assert "ebay_access_blocked(" in source
    assert (
        "EBAY_SOURCE_UNAVAILABLE_ACCESS_BLOCKED"
        in source
    )
    assert (
        "Required source eBay is unavailable"
        in source
    )
    assert (
        "Continuing Gripsweat refresh."
        in source
    )


def test_external_handoff_can_mark_ebay_available() -> None:
    """Successful imported pages flow into the normal available state."""
    source = runner_source()

    handoff = source.index(
        "if pending_ebay_raw_pages > 0:"
    )
    available = source.index(
        'status["ebay_source_state"] = "available"',
        handoff,
    )

    assert handoff < available
    assert (
        "EBAY_SOURCE_AVAILABLE"
        in source[handoff:available + 300]
    )
