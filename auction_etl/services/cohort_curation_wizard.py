"""Eleven-stage audited cohort curation orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.deterministic_verdicts import (
    evaluate_listing,
    list_rules,
)
from auction_etl.services.normalization_readiness import (
    get_readiness,
)
from auction_etl.services.normalization_workbench import (
    apply_workbook,
    export_workbook_csv,
    list_comparable_candidates,
    preview_workbook,
    save_comparable_review,
)


WIZARD_STEPS = (
    "Exact pressing identity",
    "Assigned listings",
    "Evidence and attachments",
    "Completeness reference",
    "Listing observations",
    "Condition normalization",
    "Analysis and market factors",
    "Comparable review",
    "Normalization readiness",
    "Eleven deterministic verdicts",
    "Audit and final report",
)

BASELINE_RULE_CODES = (
    "MARKET_EVIDENCE_INSUFFICIENT",
    "MARKET_NOISE_INSUFFICIENT_SAMPLE",
    "REISSUE_MARKET_VISIBILITY",
    "REISSUE_PRICE_CONVERGENCE",
    "FIRST_PRESS_PRICE_PARITY",
    "REISSUE_PRICE_CROSSOVER",
    "PERSISTENT_REISSUE_DISPLACEMENT",
    "HISTORICAL_PRICE_OUTLIER",
    "CLOSING_WINDOW_ESCALATION",
    "HIGH_AUCTION_IMPACT",
    "HIGH_COLLECTOR_SIGNIFICANCE",
)

REFERENCE_ACTIONS = (
    "NO_CHANGE",
    "UPSERT",
    "DELETE",
)

REFERENCE_STATES = (
    "REQUIRED",
    "NOT_INCLUDED",
    "UNKNOWN",
)

OBSERVATION_ACTIONS = (
    "NO_CHANGE",
    "UPSERT",
    "DELETE",
)

OBSERVATION_STATES = (
    "PRESENT",
    "ABSENT",
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

SHA256_PATTERN = re.compile(
    r"^[0-9a-fA-F]{64}$"
)


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = (
        str(value).strip()
        if value is not None
        else ""
    )

    if not normalized:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def _optional_text(
    value: Any,
) -> str | None:
    """Normalize optional text."""
    if value is None:
        return None

    normalized = str(value).strip()

    return normalized or None


def _decimal(
    value: Any,
    field_name: str,
) -> Decimal:
    """Normalize one required decimal."""
    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error


def _integer(
    value: Any,
    field_name: str,
) -> int:
    """Normalize one required integer."""
    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{field_name} must be an integer."
        ) from error


def _optional_datetime(
    value: Any,
) -> datetime | None:
    """Normalize an optional ISO-8601 timestamp."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    normalized = str(value).strip()

    if not normalized:
        return None

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        return datetime.fromisoformat(
            normalized
        )
    except ValueError as error:
        raise ValueError(
            "Captured timestamp must use ISO 8601."
        ) from error


def _set_audit_context(
    connection: Connection,
    *,
    actor: str,
    reason: str,
) -> None:
    """Set transaction-local audit metadata."""
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
                )
            """
        ),
        {
            "actor":
                _required_text(
                    actor,
                    "Actor",
                ),
            "reason":
                _required_text(
                    reason,
                    "Reason",
                ),
        },
    )


def list_cohorts(
    engine: Engine,
    *,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return every exact pressing cohort."""
    normalized_search = _optional_text(
        search
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing.id AS pressing_id,
                    pressing.release_family_id,
                    family.display_artist,
                    family.display_title,
                    family.original_release_year,
                    pressing.catalog_number,
                    pressing.matrix_number,
                    pressing.label_name,
                    pressing.region,
                    pressing.country,
                    pressing.media_type,
                    pressing.format_detail,
                    pressing.disc_count,
                    pressing.release_year,
                    pressing.generation,
                    pressing.pressing_variant_key,
                    pressing.pressing_variant_label,
                    pressing.is_first_press,
                    pressing.is_modern_repress,
                    COUNT(
                        DISTINCT assignment.id
                    ) AS assigned_listing_count,
                    COUNT(
                        DISTINCT expectation.id
                    ) AS reference_row_count,
                    COUNT(
                        DISTINCT observation.id
                    ) AS observation_row_count,
                    COUNT(
                        DISTINCT condition.marketplace
                        || '/'
                        || condition.listing_id
                    ) AS condition_row_count,
                    COUNT(
                        DISTINCT analysis.marketplace
                        || '/'
                        || analysis.listing_id
                    ) AS analysis_row_count
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                LEFT JOIN warehouse.auction_pressing_assignment
                    AS assignment
                  ON assignment.pressing_id =
                        pressing.id
                LEFT JOIN warehouse.pressing_component_expectation
                    AS expectation
                  ON expectation.pressing_id =
                        pressing.id
                LEFT JOIN warehouse.auction_component_observation
                    AS observation
                  ON observation.marketplace =
                        assignment.marketplace
                 AND observation.listing_id =
                        assignment.listing_id
                LEFT JOIN warehouse.auction_condition_normalization
                    AS condition
                  ON condition.marketplace =
                        assignment.marketplace
                 AND condition.listing_id =
                        assignment.listing_id
                LEFT JOIN warehouse.auction_analysis_input
                    AS analysis
                  ON analysis.marketplace =
                        assignment.marketplace
                 AND analysis.listing_id =
                        assignment.listing_id
                WHERE (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        family.display_artist,
                        family.display_title,
                        pressing.catalog_number,
                        pressing.matrix_number,
                        pressing.label_name,
                        pressing.pressing_variant_label
                    ) ILIKE
                        '%' ||
                        CAST(:search AS text) ||
                        '%'
                )
                GROUP BY
                    pressing.id,
                    family.id
                ORDER BY
                    COUNT(
                        DISTINCT assignment.id
                    ) DESC,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.id
                """
            ),
            {
                "search":
                    normalized_search,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def load_cohort(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Load one exact pressing and all assigned listings."""
    with engine.connect() as connection:
        pressing = connection.execute(
            text(
                """
                SELECT
                    pressing.*,
                    family.display_artist,
                    family.display_title,
                    family.original_release_year
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                WHERE pressing.id = :pressing_id
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).mappings().one_or_none()

        if pressing is None:
            raise ValueError(
                f"Pressing #{pressing_id} does not exist."
            )

        listings = connection.execute(
            text(
                """
                SELECT
                    assignment.marketplace,
                    assignment.listing_id,
                    assignment.match_basis,
                    assignment.match_confidence,
                    assignment.is_manual_override,
                    assignment.notes AS assignment_notes,
                    auction.title,
                    auction.artist,
                    auction.seller,
                    auction.catalog_number,
                    auction.media_type,
                    auction.currency,
                    auction.final_price,
                    auction.gross_price_usd,
                    auction.landed_price_usd,
                    auction.ended_at,
                    completeness.required_component_count,
                    completeness.present_required_component_count,
                    completeness.missing_components,
                    completeness.unverified_components,
                    completeness.unexpected_components,
                    completeness.completeness_ratio,
                    completeness.completeness_status,
                    completeness.complete,
                    collector.selected_price_usd,
                    collector.condition_market_factor,
                    collector.completeness_market_factor,
                    collector.normalization_ready
                FROM warehouse.auction_pressing_assignment
                    AS assignment
                JOIN warehouse.auction AS auction
                  ON auction.marketplace =
                        assignment.marketplace
                 AND auction.listing_id =
                        assignment.listing_id
                LEFT JOIN warehouse.auction_completeness
                    AS completeness
                  ON completeness.marketplace =
                        assignment.marketplace
                 AND completeness.listing_id =
                        assignment.listing_id
                LEFT JOIN analytics.auction_collector_base
                    AS collector
                  ON collector.marketplace =
                        assignment.marketplace
                 AND collector.listing_id =
                        assignment.listing_id
                WHERE assignment.pressing_id =
                        :pressing_id
                ORDER BY
                    auction.ended_at,
                    assignment.marketplace,
                    assignment.listing_id
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).mappings().all()

    return {
        "pressing":
            dict(pressing),
        "listings":
            [
                dict(row)
                for row in listings
            ],
    }


def list_component_types(
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
                    active
                FROM system.component_type
                WHERE active
                ORDER BY
                    display_name,
                    code
                """
            )
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_evidence_sources(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return active reusable evidence sources."""
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


def list_attachments(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return active attachment metadata for one pressing."""
    entity_key = json.dumps(
        {
            "pressing_id":
                pressing_id,
        }
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.evidence_attachment
                WHERE entity_type =
                        'PRESSING_IDENTITY'
                  AND entity_key @>
                        CAST(:entity_key AS jsonb)
                  AND active
                ORDER BY
                    created_at DESC,
                    id DESC
                """
            ),
            {
                "entity_key":
                    entity_key,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def save_attachment(
    engine: Engine,
    pressing_id: int,
    *,
    source_key: str | None,
    attachment_kind: str,
    uri: str,
    sha256: str,
    mime_type: str | None,
    captured_at: Any,
    page_reference: str | None,
    notes: str | None,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Register checksummed evidence metadata."""
    normalized_kind = _required_text(
        attachment_kind,
        "Attachment kind",
    ).upper()

    if normalized_kind not in ATTACHMENT_KINDS:
        raise ValueError(
            "Unsupported attachment kind."
        )

    normalized_sha256 = _required_text(
        sha256,
        "SHA-256",
    )

    if not SHA256_PATTERN.fullmatch(
        normalized_sha256
    ):
        raise ValueError(
            "SHA-256 must contain exactly 64 hexadecimal characters."
        )

    with engine.begin() as connection:
        exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM warehouse.pressing_identity
                WHERE id = :pressing_id
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).scalar_one()

        if int(exists) != 1:
            raise ValueError(
                f"Pressing #{pressing_id} does not exist."
            )

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
                    created_by
                )
                VALUES (
                    'PRESSING_IDENTITY',
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
                    :actor
                )
                RETURNING *
                """
            ),
            {
                "entity_key":
                    json.dumps(
                        {
                            "pressing_id":
                                pressing_id,
                        }
                    ),
                "source_key":
                    _optional_text(
                        source_key
                    ),
                "attachment_kind":
                    normalized_kind,
                "uri":
                    _required_text(
                        uri,
                        "URI",
                    ),
                "sha256":
                    normalized_sha256.lower(),
                "mime_type":
                    _optional_text(
                        mime_type
                    ),
                "captured_at":
                    _optional_datetime(
                        captured_at
                    ),
                "page_reference":
                    _optional_text(
                        page_reference
                    ),
                "notes":
                    _optional_text(
                        notes
                    ),
                "actor":
                    _required_text(
                        actor,
                        "Actor",
                    ),
            },
        ).mappings().one()

    return dict(row)


def load_reference_rows(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return existing reference rows plus active component choices."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    expectation.id,
                    component.code AS component_code,
                    component.display_name,
                    COALESCE(
                        expectation.variant_key,
                        ''
                    ) AS variant_key,
                    expectation.variant_label,
                    expectation.expectation_state,
                    expectation.expected_quantity,
                    expectation.evidence_source,
                    expectation.confidence,
                    expectation.notes
                FROM system.component_type AS component
                LEFT JOIN warehouse.pressing_component_expectation
                    AS expectation
                  ON expectation.pressing_id =
                        :pressing_id
                 AND expectation.component_code =
                        component.code
                WHERE component.active
                ORDER BY
                    component.display_name,
                    component.code,
                    expectation.variant_key
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).mappings().all()

    results: list[dict[str, Any]] = []

    for row in rows:
        item = dict(row)

        item["action"] = "NO_CHANGE"
        item["expectation_state"] = (
            item["expectation_state"]
            or "UNKNOWN"
        )
        item["expected_quantity"] = (
            item["expected_quantity"]
            if item["expected_quantity"] is not None
            else 1
        )
        item["confidence"] = (
            item["confidence"]
            if item["confidence"] is not None
            else Decimal("0.9000")
        )

        results.append(item)

    return results


def _active_source_keys(
    connection: Connection,
) -> set[str]:
    """Return active evidence-source keys."""
    return {
        str(value)
        for value in connection.execute(
            text(
                """
                SELECT source_key
                FROM system.evidence_source_registry
                WHERE active
                """
            )
        ).scalars()
    }


def _active_component_codes(
    connection: Connection,
) -> set[str]:
    """Return active component codes."""
    return {
        str(value)
        for value in connection.execute(
            text(
                """
                SELECT code
                FROM system.component_type
                WHERE active
                """
            )
        ).scalars()
    }


def apply_reference_changes(
    engine: Engine,
    pressing_id: int,
    changes: Iterable[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
) -> dict[str, int]:
    """Apply reviewed pressing-reference changes atomically."""
    normalized_changes = [
        dict(change)
        for change in changes
        if str(
            change.get(
                "action",
                "NO_CHANGE",
            )
        ).upper() != "NO_CHANGE"
    ]

    inserted_or_updated = 0
    deleted = 0

    with (
        engine.connect()
        .execution_options(
            isolation_level="SERIALIZABLE"
        )
    ) as connection:
        with connection.begin():
            _set_audit_context(
                connection,
                actor=actor,
                reason=reason,
            )

            source_keys = _active_source_keys(
                connection
            )
            component_codes = (
                _active_component_codes(
                    connection
                )
            )

            for change in normalized_changes:
                action = _required_text(
                    change.get("action"),
                    "Action",
                ).upper()

                if action not in REFERENCE_ACTIONS:
                    raise ValueError(
                        f"Unsupported reference action: {action}"
                    )

                component_code = (
                    _required_text(
                        change.get(
                            "component_code"
                        ),
                        "Component code",
                    ).upper()
                )

                if component_code not in component_codes:
                    raise ValueError(
                        "Inactive or unknown component: "
                        f"{component_code}"
                    )

                variant_key = (
                    _optional_text(
                        change.get(
                            "variant_key"
                        )
                    )
                    or ""
                )

                if action == "DELETE":
                    result = connection.execute(
                        text(
                            """
                            DELETE FROM warehouse.pressing_component_expectation
                            WHERE pressing_id =
                                    :pressing_id
                              AND component_code =
                                    :component_code
                              AND variant_key =
                                    :variant_key
                            """
                        ),
                        {
                            "pressing_id":
                                pressing_id,
                            "component_code":
                                component_code,
                            "variant_key":
                                variant_key,
                        },
                    )

                    deleted += int(
                        result.rowcount or 0
                    )
                    continue

                state = _required_text(
                    change.get(
                        "expectation_state"
                    ),
                    "Expectation state",
                ).upper()

                if state not in REFERENCE_STATES:
                    raise ValueError(
                        "Unsupported expectation state."
                    )

                expected_quantity = _integer(
                    change.get(
                        "expected_quantity"
                    ),
                    "Expected quantity",
                )

                if expected_quantity < 0:
                    raise ValueError(
                        "Expected quantity cannot be negative."
                    )

                if (
                    state == "REQUIRED"
                    and expected_quantity < 1
                ):
                    raise ValueError(
                        "REQUIRED components need quantity one or greater."
                    )

                evidence_source = (
                    _required_text(
                        change.get(
                            "evidence_source"
                        ),
                        "Evidence source",
                    )
                )

                if evidence_source not in source_keys:
                    raise ValueError(
                        "Evidence source is not active: "
                        f"{evidence_source}"
                    )

                confidence = _decimal(
                    change.get("confidence"),
                    "Confidence",
                )

                if not (
                    Decimal("0")
                    <= confidence
                    <= Decimal("1")
                ):
                    raise ValueError(
                        "Confidence must be between zero and one."
                    )

                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse.pressing_component_expectation (
                            pressing_id,
                            component_code,
                            variant_key,
                            variant_label,
                            expectation_state,
                            expected_quantity,
                            evidence_source,
                            confidence,
                            notes
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
                            :notes
                        )
                        ON CONFLICT (
                            pressing_id,
                            component_code,
                            variant_key
                        )
                        DO UPDATE SET
                            variant_label =
                                EXCLUDED.variant_label,
                            expectation_state =
                                EXCLUDED.expectation_state,
                            expected_quantity =
                                EXCLUDED.expected_quantity,
                            evidence_source =
                                EXCLUDED.evidence_source,
                            confidence =
                                EXCLUDED.confidence,
                            notes =
                                EXCLUDED.notes,
                            updated_at = now()
                        """
                    ),
                    {
                        "pressing_id":
                            pressing_id,
                        "component_code":
                            component_code,
                        "variant_key":
                            variant_key,
                        "variant_label":
                            _optional_text(
                                change.get(
                                    "variant_label"
                                )
                            ),
                        "expectation_state":
                            state,
                        "expected_quantity":
                            expected_quantity,
                        "evidence_source":
                            evidence_source,
                        "confidence":
                            confidence,
                        "notes":
                            _optional_text(
                                change.get("notes")
                            ),
                    },
                )

                inserted_or_updated += 1

    return {
        "upserted":
            inserted_or_updated,
        "deleted":
            deleted,
    }


def load_observation_rows(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return existing listing observations for one cohort."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    observation.id,
                    observation.marketplace,
                    observation.listing_id,
                    auction.title,
                    observation.component_code,
                    observation.variant_key,
                    observation.variant_label,
                    observation.observation_state,
                    observation.observed_quantity,
                    observation.normalized_condition,
                    observation.source_condition_text,
                    observation.evidence_source,
                    observation.confidence,
                    observation.evidence_url,
                    observation.notes
                FROM warehouse.auction_component_observation
                    AS observation
                JOIN warehouse.auction_pressing_assignment
                    AS assignment
                  ON assignment.marketplace =
                        observation.marketplace
                 AND assignment.listing_id =
                        observation.listing_id
                JOIN warehouse.auction AS auction
                  ON auction.marketplace =
                        observation.marketplace
                 AND auction.listing_id =
                        observation.listing_id
                WHERE assignment.pressing_id =
                        :pressing_id
                ORDER BY
                    observation.marketplace,
                    observation.listing_id,
                    observation.component_code,
                    observation.variant_key
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).mappings().all()

    results = []

    for row in rows:
        item = dict(row)
        item["action"] = "NO_CHANGE"
        results.append(item)

    return results


def _cohort_identities(
    connection: Connection,
    pressing_id: int,
) -> set[tuple[str, str]]:
    """Return all listing identities assigned to a pressing."""
    return {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT
                    marketplace,
                    listing_id
                FROM warehouse.auction_pressing_assignment
                WHERE pressing_id = :pressing_id
                """
            ),
            {
                "pressing_id":
                    pressing_id,
            },
        ).mappings()
    }


def apply_observation_changes(
    engine: Engine,
    pressing_id: int,
    changes: Iterable[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
) -> dict[str, int]:
    """Apply reviewed listing-observation changes atomically."""
    normalized_changes = [
        dict(change)
        for change in changes
        if str(
            change.get(
                "action",
                "NO_CHANGE",
            )
        ).upper() != "NO_CHANGE"
    ]

    inserted_or_updated = 0
    deleted = 0

    with (
        engine.connect()
        .execution_options(
            isolation_level="SERIALIZABLE"
        )
    ) as connection:
        with connection.begin():
            _set_audit_context(
                connection,
                actor=actor,
                reason=reason,
            )

            identities = _cohort_identities(
                connection,
                pressing_id,
            )

            source_keys = _active_source_keys(
                connection
            )

            component_codes = (
                _active_component_codes(
                    connection
                )
            )

            for change in normalized_changes:
                action = _required_text(
                    change.get("action"),
                    "Action",
                ).upper()

                if action not in OBSERVATION_ACTIONS:
                    raise ValueError(
                        f"Unsupported observation action: {action}"
                    )

                marketplace = _required_text(
                    change.get(
                        "marketplace"
                    ),
                    "Marketplace",
                )

                listing_id = _required_text(
                    change.get(
                        "listing_id"
                    ),
                    "Listing ID",
                )

                if (
                    marketplace,
                    listing_id,
                ) not in identities:
                    raise ValueError(
                        "Observation listing is not assigned "
                        f"to pressing #{pressing_id}: "
                        f"{marketplace}/{listing_id}"
                    )

                component_code = (
                    _required_text(
                        change.get(
                            "component_code"
                        ),
                        "Component code",
                    ).upper()
                )

                if component_code not in component_codes:
                    raise ValueError(
                        "Inactive or unknown component: "
                        f"{component_code}"
                    )

                variant_key = (
                    _optional_text(
                        change.get(
                            "variant_key"
                        )
                    )
                    or ""
                )

                if action == "DELETE":
                    result = connection.execute(
                        text(
                            """
                            DELETE FROM warehouse.auction_component_observation
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
                        {
                            "marketplace":
                                marketplace,
                            "listing_id":
                                listing_id,
                            "component_code":
                                component_code,
                            "variant_key":
                                variant_key,
                        },
                    )

                    deleted += int(
                        result.rowcount or 0
                    )
                    continue

                state = _required_text(
                    change.get(
                        "observation_state"
                    ),
                    "Observation state",
                ).upper()

                if state not in OBSERVATION_STATES:
                    raise ValueError(
                        "Unsupported observation state."
                    )

                observed_quantity = _integer(
                    change.get(
                        "observed_quantity"
                    ),
                    "Observed quantity",
                )

                if observed_quantity < 0:
                    raise ValueError(
                        "Observed quantity cannot be negative."
                    )

                if (
                    state == "PRESENT"
                    and observed_quantity < 1
                ):
                    raise ValueError(
                        "PRESENT observations need quantity one or greater."
                    )

                if (
                    state == "ABSENT"
                    and observed_quantity != 0
                ):
                    raise ValueError(
                        "ABSENT observations must use quantity zero."
                    )

                evidence_source = _required_text(
                    change.get(
                        "evidence_source"
                    ),
                    "Evidence source",
                )

                if evidence_source not in source_keys:
                    raise ValueError(
                        "Evidence source is not active: "
                        f"{evidence_source}"
                    )

                confidence = _decimal(
                    change.get("confidence"),
                    "Confidence",
                )

                if not (
                    Decimal("0")
                    <= confidence
                    <= Decimal("1")
                ):
                    raise ValueError(
                        "Confidence must be between zero and one."
                    )

                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse.auction_component_observation (
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
                        ON CONFLICT (
                            marketplace,
                            listing_id,
                            component_code,
                            variant_key
                        )
                        DO UPDATE SET
                            variant_label =
                                EXCLUDED.variant_label,
                            observation_state =
                                EXCLUDED.observation_state,
                            observed_quantity =
                                EXCLUDED.observed_quantity,
                            normalized_condition =
                                EXCLUDED.normalized_condition,
                            source_condition_text =
                                EXCLUDED.source_condition_text,
                            evidence_source =
                                EXCLUDED.evidence_source,
                            confidence =
                                EXCLUDED.confidence,
                            evidence_url =
                                EXCLUDED.evidence_url,
                            notes =
                                EXCLUDED.notes,
                            updated_at = now()
                        """
                    ),
                    {
                        "marketplace":
                            marketplace,
                        "listing_id":
                            listing_id,
                        "component_code":
                            component_code,
                        "variant_key":
                            variant_key,
                        "variant_label":
                            _optional_text(
                                change.get(
                                    "variant_label"
                                )
                            ),
                        "observation_state":
                            state,
                        "observed_quantity":
                            observed_quantity,
                        "normalized_condition":
                            _optional_text(
                                change.get(
                                    "normalized_condition"
                                )
                            ),
                        "source_condition_text":
                            _optional_text(
                                change.get(
                                    "source_condition_text"
                                )
                            ),
                        "evidence_source":
                            evidence_source,
                        "confidence":
                            confidence,
                        "evidence_url":
                            _optional_text(
                                change.get(
                                    "evidence_url"
                                )
                            ),
                        "notes":
                            _optional_text(
                                change.get("notes")
                            ),
                    },
                )

                inserted_or_updated += 1

    return {
        "upserted":
            inserted_or_updated,
        "deleted":
            deleted,
    }


def export_cohort_workbook(
    engine: Engine,
    pressing_id: int,
    work_type: str,
) -> bytes:
    """Export a condition or factor worksheet for a cohort."""
    cohort = load_cohort(
        engine,
        pressing_id,
    )

    identities = [
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in cohort["listings"]
    ]

    return export_workbook_csv(
        engine,
        work_type,
        identities,
    )


def preview_cohort_workbook(
    engine: Engine,
    work_type: str,
    payload: bytes | str,
) -> dict[str, Any]:
    """Preview one cohort worksheet without persistence."""
    return preview_workbook(
        engine,
        work_type,
        payload,
    )


def apply_cohort_workbook(
    engine: Engine,
    work_type: str,
    payload: bytes | str,
    *,
    actor: str,
    reason: str,
    filename: str | None,
) -> dict[str, Any]:
    """Apply one approved cohort worksheet."""
    return apply_workbook(
        engine,
        work_type,
        payload,
        actor=actor,
        reason=reason,
        filename=filename,
    )


def cohort_progress(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Calculate explicit completion state for all eleven stages."""
    cohort = load_cohort(
        engine,
        pressing_id,
    )

    listings = cohort["listings"]
    listing_count = len(listings)

    attachments = list_attachments(
        engine,
        pressing_id,
    )

    reference_rows = [
        row
        for row in load_reference_rows(
            engine,
            pressing_id,
        )
        if row["id"] is not None
    ]

    observation_rows = (
        load_observation_rows(
            engine,
            pressing_id,
        )
    )

    condition_count = sum(
        row[
            "condition_market_factor"
        ] is not None
        for row in listings
    )

    analysis_count = sum(
        row[
            "completeness_market_factor"
        ] is not None
        for row in listings
    )

    readiness_rows = [
        get_readiness(
            engine,
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in listings
    ]

    ready_count = sum(
        row["readiness_status"] == "READY"
        for row in readiness_rows
    )

    reviewed_comparables = 0
    pending_comparables = 0

    with engine.connect() as connection:
        comparable_summary = (
            connection.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE review.decision
                                IN (
                                    'INCLUDE',
                                    'EXCLUDE'
                                )
                        ) AS reviewed_count,
                        COUNT(*) FILTER (
                            WHERE review.decision =
                                'NEEDS_REVIEW'
                        ) AS pending_count
                    FROM warehouse.auction_comparable_review
                        AS review
                    JOIN warehouse.auction_pressing_assignment
                        AS assignment
                      ON assignment.marketplace =
                            review.marketplace
                     AND assignment.listing_id =
                            review.listing_id
                    WHERE assignment.pressing_id =
                            :pressing_id
                    """
                ),
                {
                    "pressing_id":
                        pressing_id,
                },
            ).mappings().one()
        )

        reviewed_comparables = int(
            comparable_summary[
                "reviewed_count"
            ]
            or 0
        )

        pending_comparables = int(
            comparable_summary[
                "pending_count"
            ]
            or 0
        )

    baseline_rules = {
        str(rule["rule_code"])
        for rule in list_rules(
            engine,
            include_inactive=True,
        )
        if str(
            rule["rule_code"]
        ) in BASELINE_RULE_CODES
    }

    evaluated_rule_sets = []

    for listing in listings:
        evaluation = evaluate_listing(
            engine,
            str(listing["marketplace"]),
            str(listing["listing_id"]),
        )

        evaluated_rule_sets.append(
            {
                str(item["rule_code"])
                for item in evaluation[
                    "evaluations"
                ]
            }
        )

    all_baseline_rules_available = (
        baseline_rules
        == set(
            BASELINE_RULE_CODES
        )
    )

    all_listings_evaluated = bool(
        listings
    ) and all(
        set(BASELINE_RULE_CODES)
        <= evaluated_rules
        for evaluated_rules in evaluated_rule_sets
    )

    stage_rows = [
        {
            "stage":
                1,
            "name":
                WIZARD_STEPS[0],
            "complete":
                True,
            "detail":
                f"Pressing #{pressing_id} selected.",
        },
        {
            "stage":
                2,
            "name":
                WIZARD_STEPS[1],
            "complete":
                listing_count > 0,
            "detail":
                f"{listing_count} assigned listings.",
        },
        {
            "stage":
                3,
            "name":
                WIZARD_STEPS[2],
            "complete":
                len(attachments) > 0,
            "detail":
                f"{len(attachments)} active attachments.",
        },
        {
            "stage":
                4,
            "name":
                WIZARD_STEPS[3],
            "complete":
                len(reference_rows) > 0
                and all(
                    row[
                        "expectation_state"
                    ] != "UNKNOWN"
                    for row in reference_rows
                ),
            "detail":
                f"{len(reference_rows)} persisted reference rows.",
        },
        {
            "stage":
                5,
            "name":
                WIZARD_STEPS[4],
            "complete":
                len(observation_rows) > 0,
            "detail":
                f"{len(observation_rows)} listing observations.",
        },
        {
            "stage":
                6,
            "name":
                WIZARD_STEPS[5],
            "complete":
                listing_count > 0
                and condition_count
                == listing_count,
            "detail":
                f"{condition_count}/{listing_count} listings normalized.",
        },
        {
            "stage":
                7,
            "name":
                WIZARD_STEPS[6],
            "complete":
                listing_count > 0
                and analysis_count
                == listing_count,
            "detail":
                f"{analysis_count}/{listing_count} listings have factors.",
        },
        {
            "stage":
                8,
            "name":
                WIZARD_STEPS[7],
            "complete":
                reviewed_comparables > 0
                and pending_comparables == 0,
            "detail":
                (
                    f"{reviewed_comparables} reviewed, "
                    f"{pending_comparables} pending."
                ),
        },
        {
            "stage":
                9,
            "name":
                WIZARD_STEPS[8],
            "complete":
                listing_count > 0
                and ready_count
                == listing_count,
            "detail":
                f"{ready_count}/{listing_count} listings ready.",
        },
        {
            "stage":
                10,
            "name":
                WIZARD_STEPS[9],
            "complete":
                all_baseline_rules_available
                and all_listings_evaluated,
            "detail":
                (
                    f"{len(baseline_rules)}/11 baseline rules "
                    "available and evaluated."
                ),
        },
        {
            "stage":
                11,
            "name":
                WIZARD_STEPS[10],
            "complete":
                True,
            "detail":
                "Audited final report is available.",
        },
    ]

    return {
        "pressing_id":
            pressing_id,
        "listing_count":
            listing_count,
        "attachments":
            len(attachments),
        "reference_rows":
            len(reference_rows),
        "observation_rows":
            len(observation_rows),
        "condition_rows":
            condition_count,
        "analysis_rows":
            analysis_count,
        "reviewed_comparables":
            reviewed_comparables,
        "pending_comparables":
            pending_comparables,
        "ready_listings":
            ready_count,
        "baseline_rules":
            len(baseline_rules),
        "completed_stages":
            sum(
                row["complete"]
                for row in stage_rows
            ),
        "stages":
            stage_rows,
    }


def list_cohort_audit(
    engine: Engine,
    pressing_id: int,
    *,
    limit: int = 2000,
) -> dict[str, list[dict[str, Any]]]:
    """Return audit events relevant to one exact pressing cohort."""
    cohort = load_cohort(
        engine,
        pressing_id,
    )

    identities = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in cohort["listings"]
    }

    with engine.connect() as connection:
        reference_events = connection.execute(
            text(
                """
                SELECT *
                FROM system.reference_audit_event
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "limit":
                    limit,
            },
        ).mappings().all()

        normalization_events = connection.execute(
            text(
                """
                SELECT *
                FROM system.normalization_work_audit_event
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "limit":
                    limit,
            },
        ).mappings().all()

    filtered_reference = []

    for raw_event in reference_events:
        event = dict(raw_event)
        key = dict(
            event.get("entity_key")
            or {}
        )

        event_pressing_id = key.get(
            "pressing_id"
        )

        event_identity = (
            str(
                key.get(
                    "marketplace",
                    "",
                )
            ),
            str(
                key.get(
                    "listing_id",
                    "",
                )
            ),
        )

        if (
            str(event_pressing_id)
            == str(pressing_id)
            or event_identity in identities
        ):
            filtered_reference.append(
                event
            )

    filtered_normalization = []

    for raw_event in normalization_events:
        event = dict(raw_event)
        key = dict(
            event.get("entity_key")
            or {}
        )

        event_identity = (
            str(
                key.get(
                    "marketplace",
                    "",
                )
            ),
            str(
                key.get(
                    "listing_id",
                    "",
                )
            ),
        )

        if event_identity in identities:
            filtered_normalization.append(
                event
            )

    return {
        "reference_events":
            filtered_reference,
        "normalization_events":
            filtered_normalization,
    }


def build_cohort_report(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Build one complete, read-only cohort report."""
    cohort = load_cohort(
        engine,
        pressing_id,
    )

    progress = cohort_progress(
        engine,
        pressing_id,
    )

    reference_rows = [
        row
        for row in load_reference_rows(
            engine,
            pressing_id,
        )
        if row["id"] is not None
    ]

    observations = load_observation_rows(
        engine,
        pressing_id,
    )

    attachments = list_attachments(
        engine,
        pressing_id,
    )

    readiness: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []

    for listing in cohort["listings"]:
        marketplace = str(
            listing["marketplace"]
        )

        listing_id = str(
            listing["listing_id"]
        )

        readiness.append(
            get_readiness(
                engine,
                marketplace,
                listing_id,
            )
        )

        verdicts.append(
            evaluate_listing(
                engine,
                marketplace,
                listing_id,
            )
        )

    rules = list_rules(
        engine,
        include_inactive=True,
    )

    audit = list_cohort_audit(
        engine,
        pressing_id,
    )

    return {
        "generated_at":
            datetime.now().astimezone().isoformat(),
        "wizard_stage_count":
            len(WIZARD_STEPS),
        "baseline_rule_count":
            len(BASELINE_RULE_CODES),
        "pressing":
            cohort["pressing"],
        "listings":
            cohort["listings"],
        "progress":
            progress,
        "attachments":
            attachments,
        "reference_rows":
            reference_rows,
        "observations":
            observations,
        "readiness":
            readiness,
        "baseline_rules":
            [
                rule
                for rule in rules
                if str(
                    rule["rule_code"]
                ) in BASELINE_RULE_CODES
            ],
        "verdicts":
            verdicts,
        "audit":
            audit,
    }


def uploaded_file_sha256(
    payload: bytes,
) -> str:
    """Return a lowercase SHA-256 checksum."""
    return hashlib.sha256(
        payload
    ).hexdigest()


__all__ = [
    "ATTACHMENT_KINDS",
    "BASELINE_RULE_CODES",
    "OBSERVATION_ACTIONS",
    "OBSERVATION_STATES",
    "REFERENCE_ACTIONS",
    "REFERENCE_STATES",
    "WIZARD_STEPS",
    "apply_cohort_workbook",
    "apply_observation_changes",
    "apply_reference_changes",
    "build_cohort_report",
    "cohort_progress",
    "export_cohort_workbook",
    "list_attachments",
    "list_cohort_audit",
    "list_cohorts",
    "list_component_types",
    "list_evidence_sources",
    "load_cohort",
    "load_observation_rows",
    "load_reference_rows",
    "preview_cohort_workbook",
    "save_attachment",
    "save_comparable_review",
    "uploaded_file_sha256",
]
