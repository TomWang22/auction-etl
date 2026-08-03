"""Reference audit migration contracts."""

from __future__ import annotations

from pathlib import Path


UP = Path(
    "alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments_up.sql"
)

DOWN = Path(
    "alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments_down.sql"
)

REVISION = Path(
    "alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments.py"
)


def test_revision_chain() -> None:
    """The migration extends the evidence registry."""
    source = REVISION.read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "9e4b7c2a6d15"' in source
    assert (
        'down_revision: str | None = '
        '"7c3e8a1d5f42"'
        in source
    )


def test_audit_and_attachment_objects() -> None:
    """Audit, attachments, and batch history are installed."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "CREATE TABLE system.reference_audit_event",
        "CREATE TABLE system.evidence_attachment",
        "CREATE TABLE system.bulk_observation_batch",
        "CREATE TABLE system.bulk_observation_batch_row",
        "reference_audit_event_immutable",
        "capture_reference_audit",
        "pressing_component_expectation_audit",
        "auction_component_observation_audit",
        "evidence_source_registry_audit",
        "evidence_attachment_audit",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_audit_is_immutable() -> None:
    """Audit events cannot be edited or deleted."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert (
        "reject_reference_audit_mutation"
        in source
    )
    assert (
        "BEFORE UPDATE OR DELETE"
        in source
    )


def test_downgrade_preserves_collector_rows() -> None:
    """Downgrade removes only new history objects."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    assert (
        "DROP TABLE IF EXISTS"
        in source
    )
    assert (
        "DROP TABLE IF EXISTS\n"
        "    warehouse.pressing_component_expectation"
        not in source
    )
    assert (
        "DROP TABLE IF EXISTS\n"
        "    warehouse.auction_component_observation"
        not in source
    )


# psycopg-percent-regression:start
def test_plpgsql_raise_placeholders_are_driver_escaped() -> None:
    """Psycopg must receive doubled literal percent signs."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert (
        "'Unsupported audited table %%.%%'"
        in source
    )
    assert (
        "'Unsupported audited table %.%'"
        not in source
    )
# psycopg-percent-regression:end


# evidence-source-key-repair-regression:start
def test_upgrade_repairs_malformed_evidence_source_key() -> None:
    """The pending migration canonicalizes the bootstrapped key."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "-- evidence-source-key-repair:start",
        "'AUCTION_TITLE_STATES_'",
        "'AUCTION_TITLE_STATES'",
        "UPDATE warehouse.pressing_component_expectation",
        "UPDATE warehouse.auction_component_observation",
        "DELETE FROM system.evidence_source_registry",
    )

    for fragment in required_fragments:
        assert fragment in source
# evidence-source-key-repair-regression:end
