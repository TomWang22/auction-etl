"""Migration contracts for new-auction intake."""

from pathlib import Path


UP = Path(
    "alembic/versions/"
    "c8b4d7e2a619_new_auction_intake_queue_and_alerts_up.sql"
)

DOWN = Path(
    "alembic/versions/"
    "c8b4d7e2a619_new_auction_intake_queue_and_alerts_down.sql"
)


def test_upgrade_installs_required_objects() -> None:
    """The migration installs queue, audit, and alert contracts."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required = (
        "auction_pressing_assignment_audit_event",
        "new_auction_assignment_queue",
        "listing_completeness_alert",
        "current_listing_completeness_alert",
        "completeness_cohort_summary",
        "capture_auction_pressing_assignment_audit",
        "reject_assignment_audit_mutation",
    )

    for fragment in required:
        assert fragment in source


def test_queue_is_derived_and_deduplicated() -> None:
    """The queue is based on missing composite assignments."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert "NOT EXISTS" in source
    assert "assignment.marketplace" in source
    assert "assignment.listing_id" in source
    assert "CREATE TABLE system.new_auction_assignment_queue" not in source


def test_alerts_are_derived_from_immutable_snapshots() -> None:
    """Alerts do not create a second mutable status source."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert "FROM system.listing_completeness_snapshot" in source
    assert "BECAME_COMPLETE" in source
    assert "BECAME_INCOMPLETE" in source
    assert "REFERENCE_UNRESOLVED" in source
    assert "MISSING_COMPONENTS_CHANGED" in source
    assert "ASSIGNMENT_CHANGED" in source


def test_downgrade_removes_every_object() -> None:
    """The downgrade removes all newly installed objects."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    required = (
        "completeness_cohort_summary",
        "current_listing_completeness_alert",
        "listing_completeness_alert",
        "new_auction_assignment_queue",
        "auction_pressing_assignment_audit_event",
    )

    for fragment in required:
        assert fragment in source
