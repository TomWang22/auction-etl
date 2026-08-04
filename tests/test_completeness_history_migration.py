"""Tests for completeness-history migration sources."""

from pathlib import Path


UP = Path(
    "alembic/versions/"
    "d4e8b1c7a903_completeness_snapshots_and_timeline_up.sql"
)

DOWN = Path(
    "alembic/versions/"
    "d4e8b1c7a903_completeness_snapshots_and_timeline_down.sql"
)


def test_snapshot_migration_contract() -> None:
    """The migration installs immutable automatic history."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required = (
        "system.listing_completeness_snapshot",
        "system.listing_completeness_payload",
        "system.capture_listing_completeness_snapshot",
        "system.capture_automatic_completeness_snapshot",
        "system.listing_completeness_timeline",
        "listing_completeness_snapshot_immutable",
        "PRESSING_ASSIGNMENT_CHANGED",
        "MASTER_REFERENCE_CHANGED",
        "LISTING_OBSERVATION_CHANGED",
        "MEDIA_PROFILE_CHANGED",
        "snapshot_fingerprint",
        "source_changed_fields",
        "completeness_changed_fields",
        "expectation_state = 'REQUIRED'",
    )

    for fragment in required:
        assert fragment in source


def test_migration_backfills_assigned_listings() -> None:
    """Every current assignment receives a baseline snapshot."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert (
        "'BASELINE'"
        in source
    )

    assert (
        "FROM warehouse.auction_pressing_assignment"
        in source
    )


def test_downgrade_removes_all_snapshot_objects() -> None:
    """Downgrade removes triggers, functions, view, and table."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    required = (
        "DROP VIEW IF EXISTS",
        "listing_completeness_timeline",
        "capture_automatic_completeness_snapshot",
        "capture_listing_completeness_snapshot",
        "listing_completeness_snapshot",
    )

    for fragment in required:
        assert fragment in source


def test_upgrade_sql_avoids_psycopg_percent_rowtype() -> None:
    """PL/pgSQL declarations cannot expose percent tokens to psycopg."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert "%ROWTYPE" not in source
    assert "latest_snapshot record;" in source
