"""Reviewed new-auction assignment and completeness-alert services."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


def engine_from_environment() -> Engine:
    """Create an engine from the required application database URL."""
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")

    return create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
    )


def _dictionary(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached dictionary."""
    return dict(row)


def _clean_text(value: Any) -> str:
    """Normalize user-supplied text."""
    return str(value or "").strip()


def _confidence(value: Any) -> Decimal:
    """Return a reviewed confidence value between zero and one."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            "Match confidence must be a decimal between 0 and 1."
        ) from error

    if result < Decimal("0") or result > Decimal("1"):
        raise ValueError(
            "Match confidence must be between 0 and 1."
        )

    return result.quantize(Decimal("0.0001"))


def queue_count(engine: Engine) -> int:
    """Return the number of auctions awaiting assignment."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM system.new_auction_assignment_queue
                    """
                )
            ).scalar_one()
        )


def list_unassigned_auctions(
    engine: Engine,
    *,
    limit: int = 500,
    marketplace: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return the prioritized derived assignment queue."""
    bounded_limit = max(
        1,
        min(
            int(limit),
            5000,
        ),
    )

    marketplace_value = _clean_text(
        marketplace
    )

    search_value = _clean_text(
        search
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    marketplace,
                    listing_id,
                    display_title,
                    catalog_hint,
                    source_url,
                    source_changed_at,
                    queue_status,
                    identity_fingerprint,
                    auction_payload
                FROM system.new_auction_assignment_queue
                WHERE (
                    :marketplace = ''
                    OR marketplace = :marketplace
                )
                  AND (
                    :search = ''
                    OR display_title ILIKE
                        '%' || :search || '%'
                    OR COALESCE(
                        catalog_hint,
                        ''
                    ) ILIKE
                        '%' || :search || '%'
                    OR listing_id ILIKE
                        '%' || :search || '%'
                )
                ORDER BY
                    source_changed_at DESC NULLS LAST,
                    marketplace,
                    listing_id
                LIMIT :limit
                """
            ),
            {
                "marketplace":
                    marketplace_value,
                "search":
                    search_value,
                "limit":
                    bounded_limit,
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def list_queue_marketplaces(
    engine: Engine,
) -> list[str]:
    """Return marketplaces represented in the queue."""
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT DISTINCT marketplace
                FROM system.new_auction_assignment_queue
                ORDER BY marketplace
                """
            )
        ).scalars().all()

    return [
        str(value)
        for value in values
    ]


def list_exact_pressings(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return every reviewed exact pressing available for assignment."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing.id AS pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.media_type,
                    pressing.generation,
                    (
                        SELECT COUNT(*)
                        FROM warehouse.auction_pressing_assignment
                            AS assignment
                        WHERE assignment.pressing_id =
                                pressing.id
                    )::integer AS assigned_listing_count,
                    (
                        SELECT COUNT(*)
                        FROM warehouse.pressing_component_expectation
                            AS reference_record
                        WHERE reference_record.pressing_id =
                                pressing.id
                          AND reference_record.expectation_state =
                                'REQUIRED'
                    )::integer AS required_reference_count
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                ORDER BY
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.id
                """
            )
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def _match_basis_options_with_connection(
    connection: Connection,
) -> list[str]:
    """Return values permitted by the live assignment contract."""
    existing_values = {
        str(value).strip()
        for value in connection.execute(
            text(
                """
                SELECT DISTINCT match_basis
                FROM warehouse.auction_pressing_assignment
                WHERE match_basis IS NOT NULL
                  AND btrim(
                      match_basis
                  ) <> ''
                """
            )
        ).scalars().all()
        if str(value).strip()
    }

    definitions = connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(
                constraint_record.oid,
                true
            )
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid =
                    'warehouse.auction_pressing_assignment'
                        ::regclass
              AND position(
                    'match_basis'
                    IN lower(
                        pg_get_constraintdef(
                            constraint_record.oid,
                            true
                        )
                    )
                  ) > 0
            """
        )
    ).scalars().all()

    discovered_values: set[str] = set()

    for definition in definitions:
        discovered_values.update(
            value
            for value in re.findall(
                r"'([^']+)'",
                str(definition),
            )
            if value
        )

    options = sorted(
        existing_values
        | discovered_values
    )

    if not options:
        raise RuntimeError(
            "No permitted assignment match-basis value was discovered."
        )

    return options


def list_match_basis_options(
    engine: Engine,
) -> list[str]:
    """Return permitted assignment match-basis values."""
    with engine.connect() as connection:
        return _match_basis_options_with_connection(
            connection
        )


def _preview_with_connection(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    match_basis: str,
    match_confidence: Any,
    reviewer: str,
    reason: str,
    scope_confirmed: bool,
) -> dict[str, Any]:
    """Build one deterministic assignment preview."""
    marketplace_value = _clean_text(
        marketplace
    )

    listing_value = _clean_text(
        listing_id
    )

    reviewer_value = _clean_text(
        reviewer
    )

    reason_value = _clean_text(
        reason
    )

    basis_value = _clean_text(
        match_basis
    )

    if not marketplace_value:
        raise ValueError("Marketplace is required.")

    if not listing_value:
        raise ValueError("Listing ID is required.")

    if not reviewer_value:
        raise ValueError("Reviewer is required.")

    if len(reason_value) < 12:
        raise ValueError(
            "Reason must contain at least 12 characters."
        )

    if not scope_confirmed:
        raise ValueError(
            "Exact-pressing scope confirmation is required."
        )

    confidence_value = _confidence(
        match_confidence
    )

    permitted_basis = _match_basis_options_with_connection(
        connection
    )

    if basis_value not in permitted_basis:
        raise ValueError(
            "Match basis is not permitted by the live schema."
        )

    auction = connection.execute(
        text(
            """
            SELECT
                marketplace,
                listing_id,
                display_title,
                catalog_hint,
                source_url,
                source_changed_at,
                auction_payload
            FROM system.new_auction_assignment_queue
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """
        ),
        {
            "marketplace":
                marketplace_value,
            "listing_id":
                listing_value,
        },
    ).mappings().one_or_none()

    if auction is None:
        existing_assignment = connection.execute(
            text(
                """
                SELECT pressing_id
                FROM warehouse.auction_pressing_assignment
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    marketplace_value,
                "listing_id":
                    listing_value,
            },
        ).scalar_one_or_none()

        if existing_assignment is not None:
            raise ValueError(
                "This auction already has a reviewed pressing assignment."
            )

        raise ValueError(
            "The auction is not present in the unassigned queue."
        )

    pressing = connection.execute(
        text(
            """
            SELECT
                pressing.id AS pressing_id,
                family.display_artist,
                family.display_title,
                pressing.catalog_number,
                pressing.media_type,
                pressing.generation
            FROM warehouse.pressing_identity AS pressing
            JOIN warehouse.release_family AS family
              ON family.id =
                    pressing.release_family_id
            WHERE pressing.id = :pressing_id
            """
        ),
        {
            "pressing_id":
                int(
                    pressing_id
                ),
        },
    ).mappings().one_or_none()

    if pressing is None:
        raise ValueError(
            "The selected exact pressing does not exist."
        )

    mutation = {
        "marketplace":
            marketplace_value,
        "listing_id":
            listing_value,
        "pressing_id":
            int(
                pressing_id
            ),
        "match_basis":
            basis_value,
        "match_confidence":
            str(
                confidence_value
            ),
        "is_manual_override":
            True,
        "reviewer":
            reviewer_value,
        "reason":
            reason_value,
    }

    token_payload = {
        "auction":
            _dictionary(
                auction
            ),
        "pressing":
            _dictionary(
                pressing
            ),
        "mutation":
            mutation,
    }

    digest = hashlib.sha256(
        json.dumps(
            token_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()[
        :16
    ].upper()

    confirmation_token = (
        f"ASSIGN:{marketplace_value}:"
        f"{listing_value}:{pressing_id}:{digest}"
    )

    return {
        "status":
            "READY",
        "auction":
            _dictionary(
                auction
            ),
        "pressing":
            _dictionary(
                pressing
            ),
        "mutation":
            mutation,
        "confirmation_token":
            confirmation_token,
        "expected_effects": [
            "Insert one reviewed exact-pressing assignment.",
            "Generate one immutable assignment audit event.",
            "Generate the first completeness snapshot through the existing trigger.",
            "Remove the auction from the unassigned queue.",
        ],
        "database_writes":
            0,
    }


def preview_assignment(
    engine: Engine,
    **values: Any,
) -> dict[str, Any]:
    """Preview one assignment without writing PostgreSQL."""
    with engine.connect() as connection:
        return _preview_with_connection(
            connection,
            **values,
        )


def apply_assignment(
    engine: Engine,
    *,
    confirmation_token: str,
    **values: Any,
) -> dict[str, Any]:
    """Apply one reviewed assignment atomically."""
    supplied_token = _clean_text(
        confirmation_token
    )

    with engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    ) as connection:
        with connection.begin():
            marketplace = _clean_text(
                values.get(
                    "marketplace"
                )
            )

            listing_id = _clean_text(
                values.get(
                    "listing_id"
                )
            )

            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(
                            :lock_key,
                            0
                        )
                    )
                    """
                ),
                {
                    "lock_key":
                        (
                            "auction-assignment:"
                            f"{marketplace}:"
                            f"{listing_id}"
                        ),
                },
            )

            preview = _preview_with_connection(
                connection,
                **values,
            )

            expected_token = str(
                preview[
                    "confirmation_token"
                ]
            )

            if not hmac.compare_digest(
                supplied_token,
                expected_token,
            ):
                raise PermissionError(
                    "Confirmation token does not match the recomputed preview."
                )

            mutation = preview[
                "mutation"
            ]

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'app.actor',
                        :actor,
                        true
                    )
                    """
                ),
                {
                    "actor":
                        mutation[
                            "reviewer"
                        ],
                },
            )

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'app.reason',
                        :reason,
                        true
                    )
                    """
                ),
                {
                    "reason":
                        mutation[
                            "reason"
                        ],
                },
            )

            snapshot_count_before = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM system.listing_completeness_snapshot
                        WHERE marketplace = :marketplace
                          AND listing_id = :listing_id
                        """
                    ),
                    mutation,
                ).scalar_one()
            )

            inserted = connection.execute(
                text(
                    """
                    INSERT INTO warehouse.auction_pressing_assignment (
                        marketplace,
                        listing_id,
                        pressing_id,
                        match_basis,
                        match_confidence,
                        is_manual_override,
                        notes,
                        assigned_at,
                        updated_at
                    )
                    VALUES (
                        :marketplace,
                        :listing_id,
                        :pressing_id,
                        :match_basis,
                        CAST(
                            :match_confidence
                            AS numeric
                        ),
                        TRUE,
                        :reason,
                        now(),
                        now()
                    )
                    RETURNING
                        id,
                        marketplace,
                        listing_id,
                        pressing_id,
                        match_basis,
                        match_confidence,
                        is_manual_override,
                        notes,
                        assigned_at,
                        updated_at
                    """
                ),
                mutation,
            ).mappings().one()

            snapshot_count_after = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM system.listing_completeness_snapshot
                        WHERE marketplace = :marketplace
                          AND listing_id = :listing_id
                        """
                    ),
                    mutation,
                ).scalar_one()
            )

            audit_event = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        action,
                        actor,
                        reason,
                        occurred_at
                    FROM system.auction_pressing_assignment_audit_event
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    ORDER BY
                        occurred_at DESC,
                        id DESC
                    LIMIT 1
                    """
                ),
                mutation,
            ).mappings().one()

            latest_snapshot = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        status,
                        pressing_id,
                        trigger_event,
                        blocking_reasons,
                        created_at
                    FROM system.listing_completeness_snapshot
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    ORDER BY
                        created_at DESC,
                        id DESC
                    LIMIT 1
                    """
                ),
                mutation,
            ).mappings().one_or_none()

    return {
        "status":
            "COMPLETED",
        "assignment":
            _dictionary(
                inserted
            ),
        "audit_event":
            _dictionary(
                audit_event
            ),
        "latest_snapshot":
            (
                _dictionary(
                    latest_snapshot
                )
                if latest_snapshot is not None
                else None
            ),
        "snapshot_created":
            (
                snapshot_count_after
                > snapshot_count_before
            ),
        "database_writes":
            1,
    }


def list_assignment_audit(
    engine: Engine,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return immutable reviewed-assignment history."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    marketplace,
                    listing_id,
                    pressing_id,
                    action,
                    actor,
                    reason,
                    occurred_at
                FROM system.auction_pressing_assignment_audit_event
                ORDER BY
                    occurred_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "limit":
                    max(
                        1,
                        min(
                            int(limit),
                            5000,
                        ),
                    ),
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def list_current_alerts(
    engine: Engine,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return each listing's current derived completeness alert."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    snapshot_id,
                    marketplace,
                    listing_id,
                    pressing_id,
                    media_type,
                    status,
                    previous_status,
                    alert_type,
                    severity,
                    missing_required_unit_count,
                    missing_components,
                    blocking_reasons,
                    trigger_event,
                    created_at
                FROM system.current_listing_completeness_alert
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING' THEN 2
                        ELSE 3
                    END,
                    created_at DESC,
                    snapshot_id DESC
                LIMIT :limit
                """
            ),
            {
                "limit":
                    max(
                        1,
                        min(
                            int(limit),
                            5000,
                        ),
                    ),
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def list_alert_history(
    engine: Engine,
    *,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return chronological snapshot-derived alert history."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    snapshot_id,
                    marketplace,
                    listing_id,
                    pressing_id,
                    media_type,
                    status,
                    previous_status,
                    alert_type,
                    severity,
                    trigger_event,
                    actor,
                    reason,
                    created_at
                FROM system.listing_completeness_alert
                ORDER BY
                    created_at DESC,
                    snapshot_id DESC
                LIMIT :limit
                """
            ),
            {
                "limit":
                    max(
                        1,
                        min(
                            int(limit),
                            10000,
                        ),
                    ),
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def list_cohort_summary(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return current completeness totals by exact pressing."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing_id,
                    display_artist,
                    display_title,
                    catalog_number,
                    media_type,
                    status,
                    listing_count,
                    required_unit_count,
                    verified_present_unit_count,
                    missing_required_unit_count,
                    unknown_observation_count
                FROM system.completeness_cohort_summary
                ORDER BY
                    display_artist,
                    display_title,
                    catalog_number,
                    media_type,
                    status
                """
            )
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]
