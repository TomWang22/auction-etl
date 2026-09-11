"""Phase-D contracts for legacy/global collector runtime paths."""

from __future__ import annotations

import inspect
import re

from auction_etl.database import collector_views
from scripts import collector_features
from scripts import reclassify_collector
from scripts import run_latest_auction_refresh


def compact(value: str) -> str:
    """Normalize source and SQL whitespace for semantic assertions."""
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def test_managed_effective_view_reads_only_legacy_collector_rows() -> None:
    """Global effective state must not consume account-private metadata."""
    source = compact(
        collector_views.EFFECTIVE_VIEW_SELECT_SQL
    )

    assert (
        "LEFT JOIN warehouse.auction_collector c "
        "ON c.marketplace::text = a.marketplace::text "
        "AND c.listing_id::text = a.listing_id::text "
        "AND c.account_id IS NULL"
        in source
    )


def test_managed_review_view_reads_only_legacy_collector_rows() -> None:
    """Global review state must not consume account-private metadata."""
    source = compact(
        collector_views.REVIEW_VIEW_SELECT_SQL
    )

    assert (
        "LEFT JOIN warehouse.auction_collector collector "
        "ON collector.marketplace::text = effective.marketplace::text "
        "AND collector.listing_id::text = effective.listing_id::text "
        "AND collector.account_id IS NULL"
        in source
    )


def test_collector_view_verifier_uses_legacy_identity() -> None:
    """View parity must compare warehouse rows with legacy collector rows."""
    required = collector_views._REQUIRED_COLUMNS[
        (
            "warehouse",
            "auction_collector",
        )
    ]

    assert "account_id" in required

    source = inspect.getsource(
        collector_views.verify_collector_views
    )

    assert source.count(
        "WHERE account_id IS NULL"
    ) >= 2


def test_reclassifier_reads_and_updates_only_legacy_rows() -> None:
    """Reclassification must never mutate account-private collector rows."""
    source = compact(
        inspect.getsource(
            reclassify_collector.main
        )
    )

    assert (
        "LEFT JOIN warehouse.auction_collector AS c "
        "ON c.marketplace = a.marketplace "
        "AND c.listing_id = a.listing_id "
        "AND c.account_id IS NULL"
        in source
    )

    assert (
        "WHERE marketplace = :marketplace "
        "AND listing_id = :listing_id "
        "AND account_id IS NULL"
        in source
    )

    assert '"account_id"' in inspect.getsource(
        reclassify_collector.main
    )


def test_global_review_import_updates_only_legacy_rows() -> None:
    """Legacy review imports must not cross into account-private rows."""
    source = compact(
        inspect.getsource(
            collector_features.import_review
        )
    )

    assert (
        "WHERE marketplace = :marketplace "
        "AND listing_id = :listing_id "
        "AND account_id IS NULL"
        in source
    )


def test_global_status_duplicate_check_uses_legacy_identity() -> None:
    """Account-private siblings are not legacy duplicate rows."""
    source = compact(
        inspect.getsource(
            collector_features.print_status
        )
    )

    assert (
        "FROM warehouse.auction_collector "
        "WHERE account_id IS NULL "
        "GROUP BY marketplace, listing_id"
        in source
    )


def test_refresh_parity_counts_only_legacy_collector_rows() -> None:
    """Full refresh parity must ignore additional account-owned rows."""
    source = compact(
        inspect.getsource(
            run_latest_auction_refresh.database_state
        )
    )

    assert (
        "SELECT COUNT(*) "
        "FROM warehouse.auction_collector "
        "WHERE account_id IS NULL"
        in source
    )


def test_feature_builder_keeps_phase_d_legacy_identity() -> None:
    """The previously released builder fix must remain intact."""
    load_source = compact(
        inspect.getsource(
            collector_features.load_auctions
        )
    )

    build_source = compact(
        inspect.getsource(
            collector_features.build_features
        )
    )

    assert (
        "AND c.account_id IS NULL"
        in load_source
    )

    assert (
        "ON CONFLICT (marketplace, listing_id) "
        "WHERE account_id IS NULL "
        "DO UPDATE SET"
        in build_source
    )
