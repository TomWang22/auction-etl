"""Reference-record administration contracts."""

from __future__ import annotations

import inspect

from auction_etl.services.reference_record_admin import (
    apply_audited_bulk_observations,
    create_reference_record,
    register_attachment,
    restore_reference_event,
)


def test_create_reference_record_is_a_real_insert() -> None:
    """The admin service persists an expectation row."""
    source = inspect.getsource(
        create_reference_record
    )

    assert (
        "INSERT INTO"
        in source
    )
    assert (
        "warehouse.pressing_component_expectation"
        in source
    )
    assert "_set_audit_context" in source
    assert "RETURNING *" in source


def test_attachments_require_checksums() -> None:
    """Attachment metadata requires a SHA-256 checksum."""
    source = inspect.getsource(
        register_attachment
    )

    assert "_sha256(" in source
    assert (
        "system.evidence_attachment"
        in source
    )
    assert "_set_audit_context" in source


def test_restoration_is_an_audited_new_action() -> None:
    """Revision restoration does not rewrite audit history."""
    source = inspect.getsource(
        restore_reference_event
    )

    assert 'action="RESTORE"' in source
    assert (
        "system.reference_audit_event"
        in source
    )
    assert (
        "DELETE FROM system.reference_audit_event"
        not in source
    )


def test_bulk_import_creates_batch_and_row_history() -> None:
    """Existing bulk imports receive batch-level history."""
    source = inspect.getsource(
        apply_audited_bulk_observations
    )

    required_fragments = (
        "system.bulk_observation_batch",
        "system.bulk_observation_batch_row",
        "SERIALIZABLE",
        "_set_audit_context",
        "uploaded_sha256",
        "OVERWRITTEN",
        "INSERTED",
        "COMPLETED",
        "FAILED",
    )

    for fragment in required_fragments:
        assert fragment in source


# reference-runtime-regression:start
def test_attachment_timestamp_is_validated() -> None:
    """Attachment timestamps use explicit ISO-8601 validation."""
    source = inspect.getsource(
        register_attachment
    )

    assert "_optional_datetime(" in source


def test_bulk_returning_uses_valid_whole_row_reference() -> None:
    """The INSERT RETURNING expression uses the table row."""
    source = inspect.getsource(
        apply_audited_bulk_observations
    )

    compact_source = "".join(
        source.split()
    )

    assert (
        "to_jsonb(auction_component_observation)"
        in compact_source
    )

    assert (
        "to_jsonb("
        "warehouse.auction_component_observation"
        ")"
        not in compact_source
    )
# reference-runtime-regression:end
