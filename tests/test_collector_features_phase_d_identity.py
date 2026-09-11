"""Regression contracts for Phase-D collector feature identity."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FEATURE_FILE = (
    ROOT
    / "scripts"
    / "collector_features.py"
)

MIGRATION_FILE = (
    ROOT
    / "alembic"
    / "versions"
    / "c7f6b1d9e204_account_runtime_scoping_up.sql"
)


def function_source(
    path: Path,
    function_name: str,
) -> str:
    """Return one top-level function body from a Python source file."""
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
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == function_name
        )
    ]

    assert len(matches) == 1

    segment = ast.get_source_segment(
        source,
        matches[0],
    )

    assert segment is not None

    return segment


def normalize_whitespace(
    value: str,
) -> str:
    """Collapse formatting so SQL assertions test semantics."""
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def test_load_auctions_reads_only_legacy_collector_features() -> None:
    """Global feature rebuilds must not consume account-private rows."""
    source = normalize_whitespace(
        function_source(
            FEATURE_FILE,
            "load_auctions",
        )
    )

    assert (
        "LEFT JOIN warehouse.auction_collector AS c "
        "ON c.marketplace = a.marketplace "
        "AND c.listing_id = a.listing_id "
        "AND c.account_id IS NULL"
        in source
    )


def test_build_features_targets_legacy_partial_unique_index() -> None:
    """Legacy writes must infer the Phase-D NULL-account index."""
    source = normalize_whitespace(
        function_source(
            FEATURE_FILE,
            "build_features",
        )
    )

    assert (
        "ON CONFLICT (marketplace, listing_id) "
        "WHERE account_id IS NULL "
        "DO UPDATE SET"
        in source
    )

    assert (
        "ON CONFLICT (marketplace, listing_id) "
        "DO UPDATE SET"
        not in source
    )


def test_phase_d_migration_declares_both_collector_identities() -> None:
    """Runtime conflict inference must match the authoritative schema."""
    migration = MIGRATION_FILE.read_text(
        encoding="utf-8",
    )

    legacy_index = re.compile(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"auction_collector_legacy_listing_uidx\s+"
        r"ON\s+warehouse\.auction_collector\s*"
        r"\(\s*marketplace\s*,\s*listing_id\s*\)\s*"
        r"WHERE\s+account_id\s+IS\s+NULL\s*;",
        flags=re.IGNORECASE | re.DOTALL,
    )

    account_index = re.compile(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"auction_collector_account_listing_uidx\s+"
        r"ON\s+warehouse\.auction_collector\s*"
        r"\(\s*account_id\s*,\s*marketplace\s*,\s*listing_id\s*\)\s*"
        r"WHERE\s+account_id\s+IS\s+NOT\s+NULL\s*;",
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert legacy_index.search(
        migration
    )

    assert account_index.search(
        migration
    )


def test_legacy_builder_does_not_target_account_private_identity() -> None:
    """The global rebuild must not overwrite an account-owned row."""
    source = normalize_whitespace(
        function_source(
            FEATURE_FILE,
            "build_features",
        )
    )

    assert (
        "ON CONFLICT "
        "(account_id, marketplace, listing_id)"
        not in source
    )

    assert (
        "WHERE account_id IS NULL"
        in source
    )
