"""Reviewed new-auction assignment and completeness-alert services."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.account_scope import set_transaction_account_context


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


def queue_count(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
) -> int:
    """Return the number of visible auctions awaiting account assignment."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM system.new_auction_assignment_queue AS queue
                    WHERE EXISTS (
                        SELECT 1
                        FROM account.auction_listing AS account_listing
                        WHERE account_listing.account_id = :account_id
                          AND account_listing.marketplace = queue.marketplace
                          AND account_listing.listing_id = queue.listing_id
                    )
                    """
                ),
                {"account_id": str(account_id)},
            ).scalar_one()
        )



def list_unassigned_auctions(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    limit: int = 500,
    marketplace: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return the prioritized assignment queue visible to one account."""
    bounded_limit = max(1, min(int(limit), 5000))
    marketplace_value = _clean_text(marketplace)
    search_value = _clean_text(search)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    queue.marketplace,
                    queue.listing_id,
                    queue.display_title,
                    queue.catalog_hint,
                    queue.source_url,
                    queue.source_changed_at,
                    queue.queue_status,
                    queue.identity_fingerprint,
                    queue.auction_payload
                FROM system.new_auction_assignment_queue AS queue
                WHERE EXISTS (
                    SELECT 1
                    FROM account.auction_listing AS account_listing
                    WHERE account_listing.account_id = :account_id
                      AND account_listing.marketplace = queue.marketplace
                      AND account_listing.listing_id = queue.listing_id
                )
                  AND (
                    :marketplace = ''
                    OR queue.marketplace = :marketplace
                )
                  AND (
                    :search = ''
                    OR queue.display_title ILIKE '%' || :search || '%'
                    OR COALESCE(queue.catalog_hint, '') ILIKE
                        '%' || :search || '%'
                    OR queue.listing_id ILIKE '%' || :search || '%'
                )
                ORDER BY
                    queue.source_changed_at DESC NULLS LAST,
                    queue.marketplace,
                    queue.listing_id
                LIMIT :limit
                """
            ),
            {
                "account_id": str(account_id),
                "marketplace": marketplace_value,
                "search": search_value,
                "limit": bounded_limit,
            },
        ).mappings().all()

    return [_dictionary(row) for row in rows]



def list_queue_marketplaces(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
) -> list[str]:
    """Return queue marketplaces visible to one account."""
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT DISTINCT queue.marketplace
                FROM system.new_auction_assignment_queue AS queue
                WHERE EXISTS (
                    SELECT 1
                    FROM account.auction_listing AS account_listing
                    WHERE account_listing.account_id = :account_id
                      AND account_listing.marketplace = queue.marketplace
                      AND account_listing.listing_id = queue.listing_id
                )
                ORDER BY queue.marketplace
                """
            ),
            {"account_id": str(account_id)},
        ).scalars().all()

    return [str(value) for value in values]



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
    account_id: uuid.UUID | str,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    match_basis: str,
    match_confidence: Any,
    reviewer: str,
    reason: str,
    scope_confirmed: bool,
) -> dict[str, Any]:
    """Build one deterministic assignment preview for one account."""
    account_value = uuid.UUID(str(account_id))
    marketplace_value = _clean_text(marketplace)
    listing_value = _clean_text(listing_id)
    reviewer_value = _clean_text(reviewer)
    reason_value = _clean_text(reason)
    basis_value = _clean_text(match_basis)

    if not marketplace_value:
        raise ValueError("Marketplace is required.")
    if not listing_value:
        raise ValueError("Listing ID is required.")
    if not reviewer_value:
        raise ValueError("Reviewer is required.")
    if len(reason_value) < 12:
        raise ValueError("Reason must contain at least 12 characters.")
    if not scope_confirmed:
        raise ValueError("Exact-pressing scope confirmation is required.")

    confidence_value = _confidence(match_confidence)
    permitted_basis = _match_basis_options_with_connection(connection)

    if basis_value not in permitted_basis:
        raise ValueError(
            "Match basis is not permitted by the live schema."
        )

    auction = connection.execute(
        text(
            """
            SELECT
                queue.marketplace,
                queue.listing_id,
                queue.display_title,
                queue.catalog_hint,
                queue.source_url,
                queue.source_changed_at,
                queue.auction_payload
            FROM system.new_auction_assignment_queue AS queue
            WHERE queue.marketplace = :marketplace
              AND queue.listing_id = :listing_id
              AND EXISTS (
                  SELECT 1
                  FROM account.auction_listing AS account_listing
                  WHERE account_listing.account_id = :account_id
                    AND account_listing.marketplace = queue.marketplace
                    AND account_listing.listing_id = queue.listing_id
              )
            """
        ),
        {
            "account_id": account_value,
            "marketplace": marketplace_value,
            "listing_id": listing_value,
        },
    ).mappings().one_or_none()

    if auction is None:
        existing_assignment = connection.execute(
            text(
                """
                SELECT pressing_id
                FROM warehouse.auction_pressing_assignment
                WHERE account_id = :account_id
                  AND marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_value,
                "marketplace": marketplace_value,
                "listing_id": listing_value,
            },
        ).scalar_one_or_none()

        if existing_assignment is not None:
            raise ValueError(
                "This account already has a reviewed pressing assignment."
            )

        raise ValueError(
            "The auction is not visible in this account's unassigned queue."
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
              ON family.id = pressing.release_family_id
            WHERE pressing.id = :pressing_id
            """
        ),
        {"pressing_id": int(pressing_id)},
    ).mappings().one_or_none()

    if pressing is None:
        raise ValueError(
            "The selected exact pressing does not exist."
        )

    mutation = {
        "account_id": account_value,
        "marketplace": marketplace_value,
        "listing_id": listing_value,
        "pressing_id": int(pressing_id),
        "match_basis": basis_value,
        "match_confidence": str(confidence_value),
        "is_manual_override": True,
        "reviewer": reviewer_value,
        "reason": reason_value,
    }

    token_payload = {
        "auction": _dictionary(auction),
        "pressing": _dictionary(pressing),
        "mutation": mutation,
    }

    digest = hashlib.sha256(
        json.dumps(
            token_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16].upper()

    confirmation_token = (
        f"ASSIGN:{account_value}:{marketplace_value}:"
        f"{listing_value}:{pressing_id}:{digest}"
    )

    return {
        "status": "READY",
        "auction": _dictionary(auction),
        "pressing": _dictionary(pressing),
        "mutation": mutation,
        "confirmation_token": confirmation_token,
        "expected_effects": [
            "Insert one account-owned reviewed exact-pressing assignment.",
            "Generate one account-owned immutable assignment audit event.",
            "Generate the first account-owned completeness snapshot.",
            "Remove the auction from this account's unassigned queue.",
        ],
        "database_writes": 0,
    }



def preview_assignment(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    **values: Any,
) -> dict[str, Any]:
    """Preview one account-owned assignment without writing PostgreSQL."""
    with engine.connect() as connection:
        return _preview_with_connection(
            connection,
            account_id=account_id,
            **values,
        )



def apply_assignment(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    confirmation_token: str,
    **values: Any,
) -> dict[str, Any]:
    """Apply one account-owned reviewed assignment atomically."""
    validated_account_id = uuid.UUID(str(account_id))
    validated_user_id = uuid.UUID(str(user_id))
    supplied_token = _clean_text(confirmation_token)

    with engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    ) as connection:
        with connection.begin():
            set_transaction_account_context(
                connection,
                account_id=validated_account_id,
                user_id=validated_user_id,
            )

            marketplace = _clean_text(values.get("marketplace"))
            listing_id = _clean_text(values.get("listing_id"))

            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:lock_key, 0)
                    )
                    """
                ),
                {
                    "lock_key": (
                        "auction-assignment:"
                        f"{validated_account_id}:"
                        f"{marketplace}:{listing_id}"
                    ),
                },
            )

            preview = _preview_with_connection(
                connection,
                account_id=validated_account_id,
                **values,
            )

            expected_token = str(preview["confirmation_token"])

            if not hmac.compare_digest(supplied_token, expected_token):
                raise PermissionError(
                    "Confirmation token does not match the recomputed preview."
                )

            mutation = preview["mutation"]

            connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.actor', :actor, true),
                        set_config('app.reason', :reason, true)
                    """
                ),
                {
                    "actor": mutation["reviewer"],
                    "reason": mutation["reason"],
                },
            )

            snapshot_count_before = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM system.listing_completeness_snapshot
                        WHERE account_id = :account_id
                          AND marketplace = :marketplace
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
                        account_id,
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
                        :account_id,
                        :marketplace,
                        :listing_id,
                        :pressing_id,
                        :match_basis,
                        CAST(:match_confidence AS numeric),
                        TRUE,
                        :reason,
                        now(),
                        now()
                    )
                    RETURNING
                        id,
                        account_id,
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
                        WHERE account_id = :account_id
                          AND marketplace = :marketplace
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
                        account_id,
                        action,
                        actor,
                        reason,
                        occurred_at
                    FROM system.auction_pressing_assignment_audit_event
                    WHERE account_id = :account_id
                      AND marketplace = :marketplace
                      AND listing_id = :listing_id
                    ORDER BY occurred_at DESC, id DESC
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
                        account_id,
                        status,
                        pressing_id,
                        trigger_event,
                        blocking_reasons,
                        created_at
                    FROM system.listing_completeness_snapshot
                    WHERE account_id = :account_id
                      AND marketplace = :marketplace
                      AND listing_id = :listing_id
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                mutation,
            ).mappings().one_or_none()

    return {
        "status": "COMPLETED",
        "assignment": _dictionary(inserted),
        "audit_event": _dictionary(audit_event),
        "latest_snapshot": (
            _dictionary(latest_snapshot)
            if latest_snapshot is not None
            else None
        ),
        "snapshot_created": snapshot_count_after > snapshot_count_before,
        "database_writes": 1,
    }



def list_assignment_audit(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return immutable reviewed-assignment history for one account."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    account_id,
                    marketplace,
                    listing_id,
                    pressing_id,
                    action,
                    actor,
                    reason,
                    occurred_at
                FROM system.auction_pressing_assignment_audit_event
                WHERE account_id = :account_id
                ORDER BY occurred_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {
                "account_id": str(account_id),
                "limit": max(1, min(int(limit), 5000)),
            },
        ).mappings().all()

    return [_dictionary(row) for row in rows]



def list_current_alerts(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return current derived completeness alerts visible to one account."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT alert.*
                FROM system.current_listing_completeness_alert AS alert
                WHERE EXISTS (
                    SELECT 1
                    FROM account.auction_listing AS account_listing
                    WHERE account_listing.account_id = :account_id
                      AND account_listing.marketplace = alert.marketplace
                      AND account_listing.listing_id = alert.listing_id
                )
                ORDER BY
                    CASE alert.severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING' THEN 2
                        ELSE 3
                    END,
                    alert.created_at DESC,
                    alert.snapshot_id DESC
                LIMIT :limit
                """
            ),
            {
                "account_id": str(account_id),
                "limit": max(1, min(int(limit), 5000)),
            },
        ).mappings().all()

    return [_dictionary(row) for row in rows]



def list_alert_history(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return snapshot-derived alert history visible to one account."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT alert.*
                FROM system.listing_completeness_alert AS alert
                WHERE EXISTS (
                    SELECT 1
                    FROM account.auction_listing AS account_listing
                    WHERE account_listing.account_id = :account_id
                      AND account_listing.marketplace = alert.marketplace
                      AND account_listing.listing_id = alert.listing_id
                )
                ORDER BY alert.created_at DESC, alert.snapshot_id DESC
                LIMIT :limit
                """
            ),
            {
                "account_id": str(account_id),
                "limit": max(1, min(int(limit), 10000)),
            },
        ).mappings().all()

    return [_dictionary(row) for row in rows]



def list_cohort_summary(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
) -> list[dict[str, Any]]:
    """Return current completeness totals for listings visible to one account."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                WITH latest_snapshots AS (
                    SELECT DISTINCT ON (
                        snapshot.marketplace,
                        snapshot.listing_id
                    )
                        snapshot.*
                    FROM system.listing_completeness_snapshot AS snapshot
                    JOIN account.auction_listing AS account_listing
                      ON account_listing.marketplace = snapshot.marketplace
                     AND account_listing.listing_id = snapshot.listing_id
                     AND account_listing.account_id = :account_id
                    ORDER BY
                        snapshot.marketplace,
                        snapshot.listing_id,
                        snapshot.created_at DESC,
                        snapshot.id DESC
                )
                SELECT
                    latest_snapshots.pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    latest_snapshots.media_type,
                    latest_snapshots.status,
                    COUNT(*)::integer AS listing_count,
                    SUM(latest_snapshots.required_unit_count)::integer
                        AS required_unit_count,
                    SUM(latest_snapshots.verified_present_unit_count)::integer
                        AS verified_present_unit_count,
                    SUM(latest_snapshots.missing_required_unit_count)::integer
                        AS missing_required_unit_count,
                    SUM(latest_snapshots.unknown_observation_count)::integer
                        AS unknown_observation_count
                FROM latest_snapshots
                LEFT JOIN warehouse.pressing_identity AS pressing
                  ON pressing.id = latest_snapshots.pressing_id
                LEFT JOIN warehouse.release_family AS family
                  ON family.id = pressing.release_family_id
                GROUP BY
                    latest_snapshots.pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    latest_snapshots.media_type,
                    latest_snapshots.status
                ORDER BY
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    latest_snapshots.media_type,
                    latest_snapshots.status
                """
            ),
            {"account_id": str(account_id)},
        ).mappings().all()

    return [_dictionary(row) for row in rows]
