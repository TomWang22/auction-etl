"""Production contract for new-only Buyee detail enrichment."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

CRAWLER = (
    ROOT
    / "scripts"
    / "crawl_buyee_live_details.py"
)


def function_source(
    path: Path,
    function_name: str,
) -> str:
    """Return one top-level function's source."""

    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == function_name
    ]

    assert len(matches) == 1

    segment = ast.get_source_segment(
        source,
        matches[0],
    )

    assert segment is not None

    return segment


def test_latest_refresh_snapshots_buyee_ids_before_sync() -> None:
    """Production remembers identities present before discovery."""

    main = function_source(
        RUNNER,
        "main",
    )

    assert (
        "buyee_listing_ids_before"
        in main
    )
    assert (
        'WHERE marketplace = %s'
        in main
    )
    assert (
        '("buyee",)'
        in main
    )


def test_latest_refresh_details_only_new_buyee_ids() -> None:
    """Existing Buyee identities never enter normal detail navigation."""

    main = function_source(
        RUNNER,
        "main",
    )

    assert (
        "buyee_listing_ids_after"
        in main
    )
    assert (
        "buyee_listing_ids_after\n"
        "                - buyee_listing_ids_before"
        in main
    )
    assert (
        "if buyee_new_listing_ids:"
        in main
    )
    assert (
        "buyee_detail_command.extend"
        in main
    )
    assert (
        '"--listing-id"'
        in main
    )
    assert (
        "detail-page crawl skipped"
        in main
    )


def test_latest_refresh_does_not_force_historical_refresh() -> None:
    """Normal refresh limits forced detail refresh to WAF fallback IDs."""

    main = function_source(
        RUNNER,
        "main",
    )

    production_start = main.index(
        "if buyee_new_listing_ids:"
    )

    production_end = main.index(
        "if buyee_available:",
        production_start,
    )

    production_detail = main[
        production_start:
        production_end
    ]

    https_index = production_detail.index(
        '"scripts/crawl_buyee_http_details.py"'
    )

    waf_index = production_detail.index(
        '"AWS_WAF_CHALLENGE"',
        https_index,
    )

    owner_index = production_detail.index(
        '"scripts/run_buyee_owner_job.py"',
        waf_index,
    )

    crawl_index = production_detail.index(
        '"crawl_live_details"',
        owner_index,
    )

    refresh_index = production_detail.index(
        '"--refresh"',
        crawl_index,
    )

    https_primary_block = production_detail[
        https_index:
        waf_index
    ]

    waf_fallback_block = production_detail[
        waf_index:
    ]

    assert (
        "buyee_new_listing_ids"
        in production_detail
    )

    assert (
        "buyee_waf_listing_ids"
        in production_detail
    )

    assert (
        '"--refresh"'
        not in https_primary_block
    )

    assert (
        '"--refresh"'
        in waf_fallback_block
    )

    assert (
        production_detail.count(
            '"--refresh"'
        )
        == 1
    )

    assert (
        '"--listing-id"'
        in waf_fallback_block
    )

    assert (
        '"--apply"'
        in waf_fallback_block
    )

    assert (
        https_index
        < waf_index
        < owner_index
        < crawl_index
        < refresh_index
    )


def test_detail_crawler_supports_explicit_identity_filter() -> None:
    """The downstream crawler honors the production identity allow-list."""

    source = CRAWLER.read_text(
        encoding="utf-8",
    )

    assert '"--listing-id"' in source
    assert (
        "a.listing_id = ANY(:listing_ids)"
        in source
    )


def test_detail_crawler_preserves_completeness_guard() -> None:
    """Manual/backfill crawling still avoids complete rows by default."""

    source = CRAWLER.read_text(
        encoding="utf-8",
    )

    assert (
        "d.detail_status <> 'complete'"
        in source
    )
    assert '"--refresh"' in source
