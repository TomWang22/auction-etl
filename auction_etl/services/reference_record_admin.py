"""Real reference-record administration with immutable audit history."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.collector_observation_bulk import (
    preview_bulk_observations,
)


REFERENCE_STATES = (
    "REQUIRED",
    "NOT_INCLUDED",
    "UNKNOWN",
)

ATTACHMENT_KINDS = (
    "URL",
    "IMAGE",
    "PDF",
    "CATALOG_SCAN",
    "LISTING_CAPTURE",
    "PHYSICAL_COPY",
    "ARCHIVE_FILE",
    "OTHER",
)


def _is_missing(value: Any) -> bool:
    """Return whether one value is empty."""
    if value is None:
        return True

    return str(value).strip() in {
        "",
        "<NA>",
        "nan",
        "NaN",
        "NaT",
        "None",
    }


def _optional_text(value: Any) -> str | None:
    """Normalize optional text."""
    if _is_missing(value):
        return None

    return str(value).strip()


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = _optional_text(value)

    if normalized is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def _integer(
    value: Any,
    *,
    field_name: str,
    minimum: int = 0,
    default: int | None = None,
) -> int:
    """Normalize an integer."""
    if _is_missing(value):
        if default is None:
            raise ValueError(
                f"{field_name} is required."
            )

        return default

    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be an integer."
        ) from error

    if normalized < minimum:
        raise ValueError(
            f"{field_name} must be at least {minimum}."
        )

    return normalized


def _confidence(value: Any) -> Decimal:
    """Normalize confidence to four decimal places."""
    if _is_missing(value):
        raise ValueError(
            "Confidence is required."
        )

    try:
        normalized = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(
            "Confidence must be numeric."
        ) from error

    if not Decimal("0") <= normalized <= Decimal("1"):
        raise ValueError(
            "Confidence must be between 0 and 1."
        )

    return normalized.quantize(
        Decimal("0.0001")
    )


def _optional_datetime(value: Any) -> datetime | None:
    """Normalize an optional ISO-8601 timestamp."""
    if _is_missing(value):
        return None

    if isinstance(value, datetime):
        return value

    normalized = str(value).strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(
            "Captured timestamp must be valid ISO 8601, "
            "for example 2026-08-03T15:55:17-04:00."
        ) from error


def _sha256(value: Any) -> str:
    """Validate one SHA-256 checksum."""
    normalized = _required_text(
        value,
        "SHA-256 checksum",
    ).lower()

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        normalized,
    ):
        raise ValueError(
            "SHA-256 must contain exactly 64 hexadecimal characters."
        )

    return normalized


def _set_audit_context(
    connection: Connection,
    *,
    actor: str,
    reason: str,
    batch_id: UUID | str | None = None,
    action: str | None = None,
) -> None:
    """Set transaction-local audit metadata."""
    normalized_actor = _required_text(
        actor,
        "Actor",
    )

    normalized_reason = _required_text(
        reason,
        "Reason",
    )

    connection.execute(
        text(
            """
            SELECT
                set_config(
                    'auction_etl.actor',
                    :actor,
                    true
                ),
                set_config(
                    'auction_etl.reason',
                    :reason,
                    true
                ),
                set_config(
                    'auction_etl.batch_id',
                    :batch_id,
                    true
                ),
                set_config(
                    'auction_etl.audit_action',
                    :action,
                    true
                )
            """
        ),
        {
            "actor": normalized_actor,
            "reason": normalized_reason,
            "batch_id": (
                str(batch_id)
                if batch_id is not None
                else ""
            ),
            "action": action or "",
        },
    )


def list_reference_records(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return persisted component-reference records."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    expectation.id,
                    expectation.pressing_id,
                    expectation.component_code,
                    component.display_name,
                    component.applicable_media,
                    expectation.variant_key,
                    expectation.variant_label,
                    expectation.expectation_state,
                    expectation.expected_quantity,
                    expectation.evidence_source,
                    source.display_name
                        AS evidence_source_name,
                    expectation.confidence,
                    expectation.notes,
                    expectation.created_at,
                    expectation.updated_at
                FROM warehouse.pressing_component_expectation
                    AS expectation
                JOIN system.component_type AS component
                  ON component.code =
                        expectation.component_code
                LEFT JOIN system.evidence_source_registry
                    AS source
                  ON source.source_key =
                        expectation.evidence_source
                WHERE expectation.pressing_id =
                        :pressing_id
                ORDER BY
                    component.sort_order,
                    expectation.component_code,
                    expectation.variant_key,
                    expectation.id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_active_components(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return active component types."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    code,
                    display_name,
                    applicable_media,
                    sort_order
                FROM system.component_type
                WHERE active
                ORDER BY
                    sort_order,
                    display_name,
                    code
                """
            )
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_active_sources(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return active evidence-source registry entries."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    source_key,
                    display_name,
                    source_type,
                    base_url,
                    default_confidence,
                    notes
                FROM system.evidence_source_registry
                WHERE active
                ORDER BY
                    display_name,
                    source_key
                """
            )
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def _normalize_reference_payload(
    engine: Engine,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one real reference record."""
    pressing_id = _integer(
        payload.get("pressing_id"),
        field_name="Pressing ID",
        minimum=1,
    )

    component_code = _required_text(
        payload.get("component_code"),
        "Component code",
    ).upper()

    variant_key = (
        _optional_text(
            payload.get("variant_key")
        )
        or ""
    )

    expectation_state = _required_text(
        payload.get("expectation_state"),
        "Expectation state",
    ).upper()

    if expectation_state not in REFERENCE_STATES:
        raise ValueError(
            "Expectation state must be REQUIRED, "
            "NOT_INCLUDED, or UNKNOWN."
        )

    expected_quantity = _integer(
        payload.get("expected_quantity"),
        field_name="Expected quantity",
        minimum=0,
        default=(
            0
            if expectation_state ==
                "NOT_INCLUDED"
            else 1
        ),
    )

    if expectation_state == "REQUIRED":
        if expected_quantity < 1:
            raise ValueError(
                "A REQUIRED component must have quantity 1 or greater."
            )

    if expectation_state == "NOT_INCLUDED":
        expected_quantity = 0

    evidence_source = _required_text(
        payload.get("evidence_source"),
        "Evidence source",
    ).upper()

    confidence = _confidence(
        payload.get("confidence")
    )

    with engine.connect() as connection:
        pressing_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM warehouse.pressing_identity
                WHERE id = :pressing_id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        ).scalar_one()

        component_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM system.component_type
                WHERE code = :component_code
                  AND active
                """
            ),
            {
                "component_code":
                    component_code,
            },
        ).scalar_one()

        source_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM system.evidence_source_registry
                WHERE source_key =
                        :evidence_source
                  AND active
                """
            ),
            {
                "evidence_source":
                    evidence_source,
            },
        ).scalar_one()

    if pressing_exists != 1:
        raise ValueError(
            f"Pressing #{pressing_id} does not exist."
        )

    if component_exists != 1:
        raise ValueError(
            f"Component {component_code} is unknown or inactive."
        )

    if source_exists != 1:
        raise ValueError(
            f"Evidence source {evidence_source} "
            "is unknown or inactive."
        )

    return {
        "pressing_id":
            pressing_id,
        "component_code":
            component_code,
        "variant_key":
            variant_key,
        "variant_label":
            _optional_text(
                payload.get("variant_label")
            ),
        "expectation_state":
            expectation_state,
        "expected_quantity":
            expected_quantity,
        "evidence_source":
            evidence_source,
        "confidence":
            confidence,
        "notes":
            _optional_text(
                payload.get("notes")
            ),
    }


def create_reference_record(
    engine: Engine,
    payload: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Create one persisted pressing-reference record."""
    normalized = _normalize_reference_payload(
        engine,
        payload,
    )

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        duplicate = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.pressing_component_expectation
                WHERE pressing_id =
                        :pressing_id
                  AND component_code =
                        :component_code
                  AND variant_key =
                        :variant_key
                """
            ),
            normalized,
        ).scalar_one_or_none()

        if duplicate is not None:
            raise ValueError(
                "A reference record already exists for "
                f"{normalized['component_code']}/"
                f"{normalized['variant_key'] or '(default)'}."
            )

        row = connection.execute(
            text(
                """
                INSERT INTO
                    warehouse.pressing_component_expectation (
                        pressing_id,
                        component_code,
                        variant_key,
                        variant_label,
                        expectation_state,
                        expected_quantity,
                        evidence_source,
                        confidence,
                        notes,
                        updated_at
                    )
                VALUES (
                    :pressing_id,
                    :component_code,
                    :variant_key,
                    :variant_label,
                    :expectation_state,
                    :expected_quantity,
                    :evidence_source,
                    :confidence,
                    :notes,
                    now()
                )
                RETURNING *
                """
            ),
            normalized,
        ).mappings().one()

    return dict(row)


def update_reference_record(
    engine: Engine,
    record_id: int,
    payload: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Update one persisted pressing-reference record."""
    normalized_record_id = _integer(
        record_id,
        field_name="Reference record ID",
        minimum=1,
    )

    normalized = _normalize_reference_payload(
        engine,
        payload,
    )

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        duplicate = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.pressing_component_expectation
                WHERE pressing_id =
                        :pressing_id
                  AND component_code =
                        :component_code
                  AND variant_key =
                        :variant_key
                  AND id <> :record_id
                """
            ),
            {
                **normalized,
                "record_id":
                    normalized_record_id,
            },
        ).scalar_one_or_none()

        if duplicate is not None:
            raise ValueError(
                "Another reference record already uses "
                "that component and variant."
            )

        row = connection.execute(
            text(
                """
                UPDATE warehouse.pressing_component_expectation
                SET
                    pressing_id =
                        :pressing_id,
                    component_code =
                        :component_code,
                    variant_key =
                        :variant_key,
                    variant_label =
                        :variant_label,
                    expectation_state =
                        :expectation_state,
                    expected_quantity =
                        :expected_quantity,
                    evidence_source =
                        :evidence_source,
                    confidence =
                        :confidence,
                    notes =
                        :notes,
                    updated_at = now()
                WHERE id = :record_id
                RETURNING *
                """
            ),
            {
                **normalized,
                "record_id":
                    normalized_record_id,
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Reference record #{normalized_record_id} does not exist."
        )

    return dict(row)


def delete_reference_record(
    engine: Engine,
    record_id: int,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Delete one record while retaining immutable history."""
    normalized_record_id = _integer(
        record_id,
        field_name="Reference record ID",
        minimum=1,
    )

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                DELETE FROM
                    warehouse.pressing_component_expectation
                WHERE id = :record_id
                RETURNING *
                """
            ),
            {
                "record_id":
                    normalized_record_id,
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Reference record #{normalized_record_id} does not exist."
        )

    return dict(row)


def register_attachment(
    engine: Engine,
    payload: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Register evidence attachment metadata."""
    entity_type = _required_text(
        payload.get("entity_type"),
        "Entity type",
    ).upper()

    entity_key = payload.get(
        "entity_key"
    )

    if not isinstance(
        entity_key,
        Mapping,
    ) or not entity_key:
        raise ValueError(
            "Entity key must be a non-empty mapping."
        )

    source_key = _optional_text(
        payload.get("source_key")
    )

    if source_key is not None:
        source_key = source_key.upper()

    attachment_kind = _required_text(
        payload.get("attachment_kind"),
        "Attachment kind",
    ).upper()

    if attachment_kind not in ATTACHMENT_KINDS:
        raise ValueError(
            "Unsupported attachment kind."
        )

    uri = _required_text(
        payload.get("uri"),
        "Attachment URI",
    )

    checksum = _sha256(
        payload.get("sha256")
    )

    if source_key is not None:
        with engine.connect() as connection:
            source_exists = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM system.evidence_source_registry
                    WHERE source_key = :source_key
                    """
                ),
                {
                    "source_key": source_key,
                },
            ).scalar_one()

        if source_exists != 1:
            raise ValueError(
                f"Evidence source {source_key} does not exist."
            )

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                INSERT INTO system.evidence_attachment (
                    entity_type,
                    entity_key,
                    source_key,
                    attachment_kind,
                    uri,
                    sha256,
                    mime_type,
                    captured_at,
                    page_reference,
                    notes,
                    active,
                    created_by,
                    updated_at
                )
                VALUES (
                    :entity_type,
                    CAST(:entity_key AS jsonb),
                    :source_key,
                    :attachment_kind,
                    :uri,
                    :sha256,
                    :mime_type,
                    :captured_at,
                    :page_reference,
                    :notes,
                    true,
                    :created_by,
                    now()
                )
                RETURNING *
                """
            ),
            {
                "entity_type":
                    entity_type,
                "entity_key":
                    json.dumps(
                        dict(entity_key)
                    ),
                "source_key":
                    source_key,
                "attachment_kind":
                    attachment_kind,
                "uri":
                    uri,
                "sha256":
                    checksum,
                "mime_type":
                    _optional_text(
                        payload.get(
                            "mime_type"
                        )
                    ),
                "captured_at":
                    _optional_datetime(
                        payload.get(
                            "captured_at"
                        )
                    ),
                "page_reference":
                    _optional_text(
                        payload.get(
                            "page_reference"
                        )
                    ),
                "notes":
                    _optional_text(
                        payload.get("notes")
                    ),
                "created_by":
                    _required_text(
                        actor,
                        "Actor",
                    ),
            },
        ).mappings().one()

    return dict(row)


def list_attachments(
    engine: Engine,
    *,
    entity_type: str | None = None,
    pressing_id: int | None = None,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    """Return attachment metadata."""
    normalized_entity_type = (
        _optional_text(entity_type)
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    attachment.*,
                    source.display_name
                        AS source_display_name
                FROM system.evidence_attachment
                    AS attachment
                LEFT JOIN system.evidence_source_registry
                    AS source
                  ON source.source_key =
                        attachment.source_key
                WHERE (
                    CAST(:entity_type AS text) IS NULL
                    OR attachment.entity_type =
                        CAST(:entity_type AS text)
                )
                  AND (
                    CAST(:pressing_id AS bigint) IS NULL
                    OR attachment.entity_key @>
                        jsonb_build_object(
                            'pressing_id',
                            CAST(:pressing_id AS bigint)
                        )
                  )
                  AND (
                    :include_inactive
                    OR attachment.active
                  )
                ORDER BY
                    attachment.created_at DESC,
                    attachment.id DESC
                """
            ),
            {
                "entity_type":
                    (
                        normalized_entity_type.upper()
                        if normalized_entity_type
                        else None
                    ),
                "pressing_id":
                    pressing_id,
                "include_inactive":
                    include_inactive,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def deactivate_attachment(
    engine: Engine,
    attachment_id: int,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Deactivate attachment metadata without deleting history."""
    normalized_id = _integer(
        attachment_id,
        field_name="Attachment ID",
        minimum=1,
    )

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                UPDATE system.evidence_attachment
                SET
                    active = false,
                    updated_at = now()
                WHERE id = :attachment_id
                RETURNING *
                """
            ),
            {
                "attachment_id":
                    normalized_id,
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Attachment #{normalized_id} does not exist."
        )

    return dict(row)


def list_audit_events(
    engine: Engine,
    *,
    entity_type: str | None = None,
    pressing_id: int | None = None,
    source_key: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return immutable audit events."""
    normalized_limit = _integer(
        limit,
        field_name="Limit",
        minimum=1,
    )

    normalized_type = (
        _optional_text(entity_type)
    )

    normalized_source = (
        _optional_text(source_key)
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    entity_type,
                    entity_key,
                    action,
                    before_state,
                    after_state,
                    reason,
                    actor,
                    batch_id,
                    created_at
                FROM system.reference_audit_event
                WHERE (
                    CAST(:entity_type AS text) IS NULL
                    OR entity_type =
                        CAST(:entity_type AS text)
                )
                  AND (
                    CAST(:pressing_id AS bigint) IS NULL
                    OR entity_key @>
                        jsonb_build_object(
                            'pressing_id',
                            CAST(:pressing_id AS bigint)
                        )
                  )
                  AND (
                    CAST(:source_key AS text) IS NULL
                    OR entity_key @>
                        jsonb_build_object(
                            'source_key',
                            CAST(:source_key AS text)
                        )
                  )
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "entity_type":
                    (
                        normalized_type.upper()
                        if normalized_type
                        else None
                    ),
                "pressing_id":
                    pressing_id,
                "source_key":
                    (
                        normalized_source.upper()
                        if normalized_source
                        else None
                    ),
                "limit":
                    normalized_limit,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def restore_reference_event(
    engine: Engine,
    audit_event_id: int,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Restore the after-state of a prior reference event."""
    normalized_event_id = _integer(
        audit_event_id,
        field_name="Audit event ID",
        minimum=1,
    )

    with engine.begin() as connection:
        event = connection.execute(
            text(
                """
                SELECT
                    id,
                    entity_type,
                    after_state
                FROM system.reference_audit_event
                WHERE id = :event_id
                """
            ),
            {
                "event_id":
                    normalized_event_id,
            },
        ).mappings().one_or_none()

        if event is None:
            raise ValueError(
                f"Audit event #{normalized_event_id} does not exist."
            )

        if (
            event["entity_type"] !=
            "PRESSING_COMPONENT_EXPECTATION"
        ):
            raise ValueError(
                "Only pressing component reference events "
                "can be restored here."
            )

        snapshot = event[
            "after_state"
        ]

        if snapshot is None:
            raise ValueError(
                "The selected event has no after-state to restore."
            )

        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
            action="RESTORE",
        )

        current_id = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.pressing_component_expectation
                WHERE id = :snapshot_id
                   OR (
                        pressing_id =
                            :pressing_id
                        AND component_code =
                            :component_code
                        AND variant_key =
                            :variant_key
                   )
                ORDER BY
                    CASE
                        WHEN id = :snapshot_id
                        THEN 0
                        ELSE 1
                    END
                LIMIT 1
                """
            ),
            {
                "snapshot_id":
                    snapshot.get("id"),
                "pressing_id":
                    snapshot["pressing_id"],
                "component_code":
                    snapshot["component_code"],
                "variant_key":
                    snapshot.get(
                        "variant_key"
                    )
                    or "",
            },
        ).scalar_one_or_none()

        parameters = {
            "pressing_id":
                snapshot["pressing_id"],
            "component_code":
                snapshot["component_code"],
            "variant_key":
                snapshot.get(
                    "variant_key"
                )
                or "",
            "variant_label":
                snapshot.get(
                    "variant_label"
                ),
            "expectation_state":
                snapshot[
                    "expectation_state"
                ],
            "expected_quantity":
                snapshot[
                    "expected_quantity"
                ],
            "evidence_source":
                snapshot.get(
                    "evidence_source"
                ),
            "confidence":
                snapshot.get(
                    "confidence"
                ),
            "notes":
                snapshot.get("notes"),
        }

        if current_id is None:
            row = connection.execute(
                text(
                    """
                    INSERT INTO
                        warehouse.pressing_component_expectation (
                            pressing_id,
                            component_code,
                            variant_key,
                            variant_label,
                            expectation_state,
                            expected_quantity,
                            evidence_source,
                            confidence,
                            notes,
                            updated_at
                        )
                    VALUES (
                        :pressing_id,
                        :component_code,
                        :variant_key,
                        :variant_label,
                        :expectation_state,
                        :expected_quantity,
                        :evidence_source,
                        :confidence,
                        :notes,
                        now()
                    )
                    RETURNING *
                    """
                ),
                parameters,
            ).mappings().one()
        else:
            row = connection.execute(
                text(
                    """
                    UPDATE warehouse.pressing_component_expectation
                    SET
                        pressing_id =
                            :pressing_id,
                        component_code =
                            :component_code,
                        variant_key =
                            :variant_key,
                        variant_label =
                            :variant_label,
                        expectation_state =
                            :expectation_state,
                        expected_quantity =
                            :expected_quantity,
                        evidence_source =
                            :evidence_source,
                        confidence =
                            :confidence,
                        notes =
                            :notes,
                        updated_at = now()
                    WHERE id = :current_id
                    RETURNING *
                    """
                ),
                {
                    **parameters,
                    "current_id":
                        current_id,
                },
            ).mappings().one()

    return dict(row)


def list_bulk_batches(
    engine: Engine,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return audited bulk-import batches."""
    normalized_limit = _integer(
        limit,
        field_name="Limit",
        minimum=1,
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    batch.*,
                    (
                        SELECT COUNT(*)
                        FROM system.bulk_observation_batch_row
                            AS batch_row
                        WHERE batch_row.batch_id =
                                batch.id
                    ) AS recorded_row_outcomes
                FROM system.bulk_observation_batch
                    AS batch
                ORDER BY
                    batch.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "limit": normalized_limit,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_bulk_batch_rows(
    engine: Engine,
    batch_id: UUID | str,
) -> list[dict[str, Any]]:
    """Return row outcomes for one batch."""
    normalized_id = UUID(
        str(batch_id)
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.bulk_observation_batch_row
                WHERE batch_id = :batch_id
                ORDER BY
                    row_number,
                    id
                """
            ),
            {
                "batch_id":
                    normalized_id,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def apply_audited_bulk_observations(
    engine: Engine,
    payload: bytes | str,
    *,
    overwrite_existing: bool = False,
    actor: str = "STREAMLIT_BULK_PAGE",
    reason: str = (
        "Reviewed bulk component-observation import"
    ),
    filename: str | None = None,
) -> dict[str, Any]:
    """Apply bulk observations with batch and row history."""
    preview = preview_bulk_observations(
        engine,
        payload,
    )

    if not preview.ready:
        raise ValueError(
            "Bulk observation worksheet is invalid:\n"
            + "\n".join(
                preview.errors
            )
        )

    if (
        preview.existing_conflicts
        and not overwrite_existing
    ):
        raise ValueError(
            "Existing observation conflicts were found. "
            "Enable overwrite explicitly."
        )

    normalized_actor = _required_text(
        actor,
        "Actor",
    )

    normalized_reason = _required_text(
        reason,
        "Reason",
    )

    payload_bytes = (
        payload
        if isinstance(payload, bytes)
        else payload.encode("utf-8")
    )

    uploaded_sha256 = hashlib.sha256(
        payload_bytes
    ).hexdigest()

    batch_id = uuid4()
    rows = list(preview.rows)

    conflict_identities = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
            str(row["component_code"]),
            str(row["variant_key"]),
        )
        for row in preview.existing_conflicts
    }

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
            )

            _set_audit_context(
                connection,
                actor=normalized_actor,
                reason=normalized_reason,
                batch_id=batch_id,
            )

            connection.execute(
                text(
                    """
                    INSERT INTO system.bulk_observation_batch (
                        id,
                        filename,
                        uploaded_sha256,
                        overwrite_existing,
                        actor,
                        reason,
                        status,
                        requested_row_count,
                        touched_listing_count,
                        validation_summary
                    )
                    VALUES (
                        :batch_id,
                        :filename,
                        :uploaded_sha256,
                        :overwrite_existing,
                        :actor,
                        :reason,
                        'RUNNING',
                        :requested_row_count,
                        :touched_listing_count,
                        CAST(:validation_summary AS jsonb)
                    )
                    """
                ),
                {
                    "batch_id":
                        batch_id,
                    "filename":
                        _optional_text(filename),
                    "uploaded_sha256":
                        uploaded_sha256,
                    "overwrite_existing":
                        overwrite_existing,
                    "actor":
                        normalized_actor,
                    "reason":
                        normalized_reason,
                    "requested_row_count":
                        len(rows),
                    "touched_listing_count":
                        preview.touched_listing_count,
                    "validation_summary":
                        json.dumps(
                            preview.as_dict()
                        ),
                },
            )

            overwritten_count = 0

            for row_number, row in enumerate(
                rows,
                start=2,
            ):
                identity = (
                    str(row["marketplace"]),
                    str(row["listing_id"]),
                    str(row["component_code"]),
                    str(row["variant_key"]),
                )

                existing = connection.execute(
                    text(
                        """
                        SELECT to_jsonb(observation)
                        FROM warehouse.auction_component_observation
                            AS observation
                        WHERE marketplace =
                                :marketplace
                          AND listing_id =
                                :listing_id
                          AND component_code =
                                :component_code
                          AND variant_key =
                                :variant_key
                        """
                    ),
                    row,
                ).scalar_one_or_none()

                if existing is not None:
                    if not overwrite_existing:
                        raise ValueError(
                            "A conflict appeared after preview. "
                            "No rows were written."
                        )

                    connection.execute(
                        text(
                            """
                            DELETE FROM
                                warehouse.auction_component_observation
                            WHERE marketplace =
                                    :marketplace
                              AND listing_id =
                                    :listing_id
                              AND component_code =
                                    :component_code
                              AND variant_key =
                                    :variant_key
                            """
                        ),
                        row,
                    )

                    overwritten_count += 1

                inserted = connection.execute(
                    text(
                        """
                        INSERT INTO
                            warehouse.auction_component_observation (
                                marketplace,
                                listing_id,
                                component_code,
                                variant_key,
                                variant_label,
                                observation_state,
                                observed_quantity,
                                normalized_condition,
                                source_condition_text,
                                evidence_source,
                                confidence,
                                evidence_url,
                                notes
                            )
                        VALUES (
                            :marketplace,
                            :listing_id,
                            :component_code,
                            :variant_key,
                            :variant_label,
                            :observation_state,
                            :observed_quantity,
                            :normalized_condition,
                            :source_condition_text,
                            :evidence_source,
                            :confidence,
                            :evidence_url,
                            :notes
                        )
                        RETURNING to_jsonb(
                            auction_component_observation
                        )
                        """
                    ),
                    row,
                ).scalar_one()

                outcome = (
                    "OVERWRITTEN"
                    if identity in
                        conflict_identities
                    else "INSERTED"
                )

                connection.execute(
                    text(
                        """
                        INSERT INTO
                            system.bulk_observation_batch_row (
                                batch_id,
                                row_number,
                                marketplace,
                                listing_id,
                                component_code,
                                variant_key,
                                outcome,
                                before_state,
                                after_state
                            )
                        VALUES (
                            :batch_id,
                            :row_number,
                            :marketplace,
                            :listing_id,
                            :component_code,
                            :variant_key,
                            :outcome,
                            CAST(:before_state AS jsonb),
                            CAST(:after_state AS jsonb)
                        )
                        """
                    ),
                    {
                        "batch_id":
                            batch_id,
                        "row_number":
                            row_number,
                        "marketplace":
                            row["marketplace"],
                        "listing_id":
                            row["listing_id"],
                        "component_code":
                            row["component_code"],
                        "variant_key":
                            row["variant_key"],
                        "outcome":
                            outcome,
                        "before_state":
                            (
                                json.dumps(
                                    existing,
                                    default=str,
                                )
                                if existing is not None
                                else None
                            ),
                        "after_state":
                            json.dumps(
                                inserted,
                                default=str,
                            ),
                    },
                )

            connection.execute(
                text(
                    """
                    UPDATE system.bulk_observation_batch
                    SET
                        status = 'COMPLETED',
                        inserted_row_count =
                            :inserted_row_count,
                        overwritten_row_count =
                            :overwritten_row_count,
                        completed_at = now()
                    WHERE id = :batch_id
                    """
                ),
                {
                    "batch_id":
                        batch_id,
                    "inserted_row_count":
                        len(rows),
                    "overwritten_row_count":
                        overwritten_count,
                },
            )

    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO system.bulk_observation_batch (
                        id,
                        filename,
                        uploaded_sha256,
                        overwrite_existing,
                        actor,
                        reason,
                        status,
                        requested_row_count,
                        rejected_row_count,
                        touched_listing_count,
                        validation_summary,
                        error_message,
                        completed_at
                    )
                    VALUES (
                        :batch_id,
                        :filename,
                        :uploaded_sha256,
                        :overwrite_existing,
                        :actor,
                        :reason,
                        'FAILED',
                        :requested_row_count,
                        :rejected_row_count,
                        :touched_listing_count,
                        CAST(:validation_summary AS jsonb),
                        :error_message,
                        now()
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "batch_id":
                        batch_id,
                    "filename":
                        _optional_text(filename),
                    "uploaded_sha256":
                        uploaded_sha256,
                    "overwrite_existing":
                        overwrite_existing,
                    "actor":
                        normalized_actor,
                    "reason":
                        normalized_reason,
                    "requested_row_count":
                        len(rows),
                    "rejected_row_count":
                        len(rows),
                    "touched_listing_count":
                        preview.touched_listing_count,
                    "validation_summary":
                        json.dumps(
                            preview.as_dict()
                        ),
                    "error_message":
                        str(error),
                },
            )

        raise

    return {
        "batch_id":
            str(batch_id),
        "inserted_rows":
            len(rows),
        "overwritten_rows":
            len(
                preview.existing_conflicts
            ),
        "touched_listings":
            preview.touched_listing_count,
        "warnings":
            list(preview.warnings),
    }
