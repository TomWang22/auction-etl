"""Tests for the completeness-history service."""

from __future__ import annotations

import ast
from pathlib import Path


SERVICE = Path(
    "auction_etl/services/completeness_history.py"
)


def test_history_service_is_read_only() -> None:
    """The service exposes no mutation command."""
    source = SERVICE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    function_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    required = {
        "list_assigned_listings",
        "snapshot_coverage",
        "current_snapshot",
        "list_snapshots",
        "list_timeline",
    }

    assert required <= function_names

    forbidden = (
        "INSERT INTO",
        "UPDATE system.listing_completeness_snapshot",
        "DELETE FROM system.listing_completeness_snapshot",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_history_queries_are_identity_scoped() -> None:
    """Snapshot and timeline queries use both identity columns."""
    source = SERVICE.read_text(
        encoding="utf-8"
    )

    assert (
        "marketplace = :marketplace"
        in source
    )

    assert (
        "listing_id = :listing_id"
        in source
    )


def test_assignment_query_uses_release_family_identity() -> None:
    """Assignment labels do not require display fields on pressings."""
    source = SERVICE.read_text(
        encoding="utf-8"
    )

    assert "pressing.display_artist" not in source
    assert "pressing.display_title" not in source
    assert "warehouse.release_family" in source
    assert "to_jsonb(" in source
    assert "family_payload" in source
    assert "display_artist" in source
    assert "display_title" in source
    assert "Unknown artist" in source
    assert "Unknown title" in source
