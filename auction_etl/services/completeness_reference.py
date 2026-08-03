"""Separate pressing references from listing observations."""

from __future__ import annotations

import re

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.collector_curation import (
    OBSERVATION_STATES,
)


REFERENCE_STATES = (
    "REQUIRED",
    "OPTIONAL",
    "NOT_INCLUDED",
)

REFERENCE_EDITOR_STATES = (
    "UNKNOWN",
    *REFERENCE_STATES,
)


def _text(value: Any) -> str | None:
    """Normalize nullable text."""
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = _text(value)

    if normalized is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def _integer(
    value: Any,
    *,
    minimum: int,
    field_name: str,
) -> int:
    """Validate one required integer."""
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


def _optional_integer(
    value: Any,
    *,
    minimum: int,
    field_name: str,
) -> int | None:
    """Validate one optional integer."""
    if value in {
        None,
        "",
    }:
        return None

    return _integer(
        value,
        minimum=minimum,
        field_name=field_name,
    )


def _decimal(
    value: Any,
    *,
    required: bool,
    field_name: str,
) -> Decimal | None:
    """Validate confidence values."""
    if value in {
        None,
        "",
    }:
        if required:
            raise ValueError(
                f"{field_name} is required."
            )

        return None

    try:
        normalized = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error

    if not Decimal("0") <= normalized <= Decimal("1"):
        raise ValueError(
            f"{field_name} must be between 0 and 1."
        )

    return normalized


def _pressing_id(value: Any) -> int:
    """Validate a pressing identifier."""
    return _integer(
        value,
        minimum=1,
        field_name="Pressing ID",
    )


def load_pressing_reference_rows(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return all reference rows for an exact pressing."""
    normalized_pressing_id = _pressing_id(
        pressing_id
    )

    statement = text(
        """
        WITH selected_pressing AS (
            SELECT
                id,
                media_type
            FROM warehouse.pressing_identity
            WHERE id = :pressing_id
        )
        SELECT
            component.code AS component_code,
            component.display_name,
            component.description,
            component.applicable_media,
            (
                CARDINALITY(
                    component.applicable_media
                ) = 0
                OR pressing.media_type = ANY(
                    component.applicable_media
                )
            ) AS applies_to_pressing,
            COALESCE(
                expectation.variant_key,
                ''
            ) AS variant_key,
            expectation.variant_label,
            COALESCE(
                expectation.expectation_state,
                'UNKNOWN'
            ) AS expectation_state,
            COALESCE(
                expectation.expected_quantity,
                1
            ) AS expected_quantity,
            expectation.evidence_source,
            expectation.confidence,
            expectation.notes
        FROM system.component_type AS component
        CROSS JOIN selected_pressing AS pressing
        LEFT JOIN warehouse
            .pressing_component_expectation
            AS expectation
          ON expectation.pressing_id =
                pressing.id
         AND expectation.component_code =
                component.code
        WHERE component.active
        ORDER BY
            component.sort_order,
            component.code,
            expectation.variant_key
        """
    )

    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                statement,
                {
                    "pressing_id":
                        normalized_pressing_id,
                },
            ).mappings()
        ]

    if not rows:
        raise ValueError(
            "The pressing does not exist."
        )

    return rows


def load_pressing_reference_summary(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Return reference coverage and affected listings."""
    normalized_pressing_id = _pressing_id(
        pressing_id
    )

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                WITH component_counts AS (
                    SELECT
                        COUNT(*) AS active_components
                    FROM system.component_type
                    WHERE active
                ),
                expectation_counts AS (
                    SELECT
                        COUNT(
                            DISTINCT component_code
                        ) AS configured_components,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'REQUIRED'
                        ) AS required_components,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'OPTIONAL'
                        ) AS optional_components,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'NOT_INCLUDED'
                        ) AS excluded_components,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'UNKNOWN'
                        ) AS unknown_components
                    FROM warehouse
                        .pressing_component_expectation
                    WHERE pressing_id = :pressing_id
                ),
                assignment_counts AS (
                    SELECT
                        COUNT(*) AS assigned_listings
                    FROM warehouse
                        .auction_pressing_assignment
                    WHERE pressing_id = :pressing_id
                )
                SELECT
                    component.active_components,
                    expectation.configured_components,
                    expectation.required_components,
                    expectation.optional_components,
                    expectation.excluded_components,
                    expectation.unknown_components,
                    assignment.assigned_listings,
                    (
                        component.active_components > 0
                        AND expectation.configured_components =
                            component.active_components
                        AND expectation.required_components > 0
                        AND expectation.unknown_components = 0
                    ) AS reference_complete
                FROM component_counts AS component
                CROSS JOIN expectation_counts
                    AS expectation
                CROSS JOIN assignment_counts
                    AS assignment
                """
            ),
            {
                "pressing_id":
                    normalized_pressing_id,
            },
        ).mappings().one()

    return dict(row)


def normalize_pressing_reference_rows(
    rows: Iterable[Mapping[str, Any]],
    active_component_codes: Iterable[str],
) -> list[dict[str, Any]]:
    """Validate one complete pressing reference."""
    active_codes = {
        str(code).strip().upper()
        for code in active_component_codes
    }

    normalized_rows: list[
        dict[str, Any]
    ] = []

    identities: set[
        tuple[str, str]
    ] = set()

    configured_codes: set[str] = set()

    for index, row in enumerate(
        rows,
        start=1,
    ):
        component_code = _required_text(
            row.get("component_code"),
            f"Row {index} component",
        ).upper()

        if component_code not in active_codes:
            raise ValueError(
                f"Row {index} uses inactive component "
                f"{component_code}."
            )

        state = _required_text(
            row.get("expectation_state"),
            f"Row {index} expectation",
        ).upper()

        if state not in REFERENCE_STATES:
            raise ValueError(
                f"Row {index} expectation must be "
                "REQUIRED, OPTIONAL, or NOT_INCLUDED."
            )

        variant_key = (
            _text(
                row.get("variant_key")
            )
            or ""
        )

        identity = (
            component_code,
            variant_key,
        )

        if identity in identities:
            raise ValueError(
                "Duplicate reference identity: "
                f"{component_code}/"
                f"{variant_key or 'default'}."
            )

        evidence_source = _required_text(
            row.get("evidence_source"),
            f"Row {index} evidence source",
        )

        confidence = _decimal(
            row.get("confidence"),
            required=True,
            field_name=(
                f"Row {index} confidence"
            ),
        )

        normalized_rows.append(
            {
                "component_code":
                    component_code,
                "variant_key":
                    variant_key,
                "variant_label":
                    _text(
                        row.get(
                            "variant_label"
                        )
                    ),
                "expectation_state":
                    state,
                "expected_quantity":
                    _integer(
                        row.get(
                            "expected_quantity",
                            1,
                        ),
                        minimum=1,
                        field_name=(
                            f"Row {index} "
                            "expected quantity"
                        ),
                    ),
                "evidence_source":
                    evidence_source,
                "confidence":
                    confidence,
                "notes":
                    _text(
                        row.get("notes")
                    ),
            }
        )

        identities.add(identity)
        configured_codes.add(
            component_code
        )

    missing_codes = sorted(
        active_codes - configured_codes
    )

    if missing_codes:
        raise ValueError(
            "Every active component must be classified. "
            "Missing: "
            + ", ".join(missing_codes)
        )

    if not any(
        row["expectation_state"]
        == "REQUIRED"
        for row in normalized_rows
    ):
        raise ValueError(
            "A verified reference must contain at least "
            "one REQUIRED component."
        )

    return normalized_rows


def save_pressing_reference_rows(
    engine: Engine,
    pressing_id: int,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Atomically replace only the pressing reference."""
    normalized_pressing_id = _pressing_id(
        pressing_id
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )

        pressing_exists = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.pressing_identity
                WHERE id = :pressing_id
                FOR UPDATE
                """
            ),
            {
                "pressing_id":
                    normalized_pressing_id,
            },
        ).scalar_one_or_none()

        if pressing_exists is None:
            raise ValueError(
                "The pressing does not exist."
            )

        active_codes = [
            str(value)
            for value in connection.execute(
                text(
                    """
                    SELECT code
                    FROM system.component_type
                    WHERE active
                    ORDER BY sort_order, code
                    """
                )
            ).scalars()
        ]

        normalized_rows = (
            normalize_pressing_reference_rows(
                rows,
                active_codes,
            )
        )

        connection.execute(
            text(
                """
                DELETE FROM warehouse
                    .pressing_component_expectation
                WHERE pressing_id = :pressing_id
                """
            ),
            {
                "pressing_id":
                    normalized_pressing_id,
            },
        )

        for row in normalized_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO warehouse
                        .pressing_component_expectation (
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
                    """
                ),
                {
                    "pressing_id":
                        normalized_pressing_id,
                    **row,
                },
            )


def load_listing_observation_rows(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> list[dict[str, Any]]:
    """Return observations without pressing expectations."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    statement = text(
        """
        SELECT
            component.code AS component_code,
            component.display_name,
            component.description,
            component.applicable_media,
            COALESCE(
                observation.variant_key,
                ''
            ) AS variant_key,
            observation.variant_label,
            COALESCE(
                observation.observation_state,
                'UNKNOWN'
            ) AS observation_state,
            observation.observed_quantity,
            observation.normalized_condition,
            observation.source_condition_text,
            observation.evidence_source,
            observation.confidence,
            observation.evidence_url,
            observation.notes
        FROM system.component_type AS component
        LEFT JOIN warehouse
            .auction_component_observation
            AS observation
          ON observation.component_code =
                component.code
         AND observation.marketplace =
                :marketplace
         AND observation.listing_id =
                :listing_id
        WHERE component.active
        ORDER BY
            component.sort_order,
            component.code,
            observation.variant_key
        """
    )

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement,
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                },
            ).mappings()
        ]


def normalize_listing_observation_rows(
    rows: Iterable[Mapping[str, Any]],
    active_component_codes: Iterable[str],
) -> list[dict[str, Any]]:
    """Validate meaningful listing observations."""
    active_codes = {
        str(code).strip().upper()
        for code in active_component_codes
    }

    normalized_rows: list[
        dict[str, Any]
    ] = []

    identities: set[
        tuple[str, str]
    ] = set()

    for index, row in enumerate(
        rows,
        start=1,
    ):
        component_code = _required_text(
            row.get("component_code"),
            f"Row {index} component",
        ).upper()

        state = (
            _text(
                row.get(
                    "observation_state"
                )
            )
            or "UNKNOWN"
        ).upper()

        meaningful = any(
            (
                state != "UNKNOWN",
                _text(
                    row.get("variant_key")
                )
                is not None,
                _text(
                    row.get("variant_label")
                )
                is not None,
                row.get(
                    "observed_quantity"
                )
                not in {
                    None,
                    "",
                },
                _text(
                    row.get(
                        "normalized_condition"
                    )
                )
                is not None,
                _text(
                    row.get(
                        "source_condition_text"
                    )
                )
                is not None,
                _text(
                    row.get("evidence_source")
                )
                is not None,
                row.get("confidence")
                not in {
                    None,
                    "",
                },
                _text(
                    row.get("evidence_url")
                )
                is not None,
                _text(
                    row.get("notes")
                )
                is not None,
            )
        )

        if not meaningful:
            continue

        if component_code not in active_codes:
            raise ValueError(
                f"Row {index} uses inactive component "
                f"{component_code}."
            )

        if state not in OBSERVATION_STATES:
            raise ValueError(
                f"Row {index} has invalid observation "
                f"state {state}."
            )

        variant_key = (
            _text(
                row.get("variant_key")
            )
            or ""
        )

        identity = (
            component_code,
            variant_key,
        )

        if identity in identities:
            raise ValueError(
                "Duplicate observation identity: "
                f"{component_code}/"
                f"{variant_key or 'default'}."
            )

        observed_quantity = (
            _optional_integer(
                row.get(
                    "observed_quantity"
                ),
                minimum=0,
                field_name=(
                    f"Row {index} "
                    "observed quantity"
                ),
            )
        )

        if (
            state == "PRESENT"
            and observed_quantity is None
        ):
            observed_quantity = 1

        if (
            state == "ABSENT"
            and observed_quantity is None
        ):
            observed_quantity = 0

        evidence_source = _text(
            row.get("evidence_source")
        )

        confidence_required = state in {
            "PRESENT",
            "ABSENT",
        }

        if (
            confidence_required
            and evidence_source is None
        ):
            raise ValueError(
                f"Row {index} evidence source is required "
                f"when state is {state}."
            )

        normalized_rows.append(
            {
                "component_code":
                    component_code,
                "variant_key":
                    variant_key,
                "variant_label":
                    _text(
                        row.get(
                            "variant_label"
                        )
                    ),
                "observation_state":
                    state,
                "observed_quantity":
                    observed_quantity,
                "normalized_condition":
                    _text(
                        row.get(
                            "normalized_condition"
                        )
                    ),
                "source_condition_text":
                    _text(
                        row.get(
                            "source_condition_text"
                        )
                    ),
                "evidence_source":
                    evidence_source,
                "confidence":
                    _decimal(
                        row.get("confidence"),
                        required=confidence_required,
                        field_name=(
                            f"Row {index} confidence"
                        ),
                    ),
                "evidence_url":
                    _text(
                        row.get("evidence_url")
                    ),
                "notes":
                    _text(
                        row.get("notes")
                    ),
            }
        )

        identities.add(identity)

    return normalized_rows


def save_listing_observation_rows(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Atomically replace only one listing's observations."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    normalized_pressing_id = _pressing_id(
        pressing_id
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )

        assigned_pressing = connection.execute(
            text(
                """
                SELECT pressing_id
                FROM warehouse
                    .auction_pressing_assignment
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                FOR UPDATE
                """
            ),
            {
                "marketplace":
                    marketplace_value,
                "listing_id":
                    listing_id_value,
            },
        ).scalar_one_or_none()

        if assigned_pressing is None:
            raise ValueError(
                "The listing has no pressing assignment."
            )

        if int(
            assigned_pressing
        ) != normalized_pressing_id:
            raise ValueError(
                "The listing pressing changed before save."
            )

        active_codes = [
            str(value)
            for value in connection.execute(
                text(
                    """
                    SELECT code
                    FROM system.component_type
                    WHERE active
                    ORDER BY sort_order, code
                    """
                )
            ).scalars()
        ]

        normalized_rows = (
            normalize_listing_observation_rows(
                rows,
                active_codes,
            )
        )

        connection.execute(
            text(
                """
                DELETE FROM warehouse
                    .auction_component_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    marketplace_value,
                "listing_id":
                    listing_id_value,
            },
        )

        for row in normalized_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO warehouse
                        .auction_component_observation (
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
                            notes,
                            updated_at
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
                        :notes,
                        now()
                    )
                    """
                ),
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                    **row,
                },
            )

# factory-sealed-evidence:start
FACTORY_SEALED_COMPONENT_CODE = "SHRINK_WRAP"
FACTORY_SEALED_VARIANT_KEY = "FACTORY_SEALED"
FACTORY_SEALED_VARIANT_LABEL = "Factory sealed"
FACTORY_SEALED_MINIMUM_CONFIDENCE = Decimal("0.9000")


FACTORY_SEALED_TITLE_PATTERNS = (
    re.compile(
        r"(?i)(?<![A-Z])FACTORY[\s-]+SEALED(?![A-Z])"
    ),
    re.compile(
        r"(?i)(?<![A-Z])STILL[\s-]+SEALED(?![A-Z])"
    ),
    re.compile(
        r"(?i)(?<![A-Z])NEW[\s-]+SEALED(?![A-Z])"
    ),
    re.compile(
        r"(?i)(?<![A-Z])SEALED(?![A-Z])"
    ),
    re.compile(r"新品未開封"),
    re.compile(r"シュリンク未開封"),
    re.compile(r"未開封"),
)

FACTORY_SEALED_CONTRADICTION_PATTERNS = (
    re.compile(
        r"(?i)(?<![A-Z])UNSEALED(?![A-Z])"
    ),
    re.compile(
        r"(?i)(?<![A-Z])RESEALED(?![A-Z])"
    ),
    re.compile(
        r"(?i)SHRINK[\s-]+REMOVED"
    ),
    re.compile(
        r"(?i)OPENED[\s-]+COPY"
    ),
    re.compile(r"開封済"),
    re.compile(r"開封品"),
    re.compile(r"シュリンクなし"),
    re.compile(r"シュリンク無し"),
    re.compile(r"シュリンク欠"),
)


def infer_factory_sealed_title_evidence(
    title: Any,
    evidence_url: Any,
) -> dict[str, Any]:
    """Build safe form defaults from explicit title evidence."""
    normalized_title = _text(title)
    normalized_url = _text(evidence_url)

    if normalized_title is None:
        return {
            "eligible": False,
            "evidence_source": "",
            "evidence_url": normalized_url or "",
            "confidence": Decimal("0.9000"),
            "notes": "",
            "matched_text": None,
            "blocker": "The listing title is empty.",
        }

    contradiction = next(
        (
            pattern.search(normalized_title)
            for pattern
            in FACTORY_SEALED_CONTRADICTION_PATTERNS
            if pattern.search(normalized_title)
        ),
        None,
    )

    if contradiction is not None:
        return {
            "eligible": False,
            "evidence_source": "",
            "evidence_url": normalized_url or "",
            "confidence": Decimal("0.9000"),
            "notes": "",
            "matched_text": None,
            "blocker": (
                "The title contains contradictory opened, "
                "unsealed, resealed, or shrink-removed evidence: "
                f"{contradiction.group(0)}"
            ),
        }

    positive_match = next(
        (
            pattern.search(normalized_title)
            for pattern in FACTORY_SEALED_TITLE_PATTERNS
            if pattern.search(normalized_title)
        ),
        None,
    )

    if positive_match is None:
        return {
            "eligible": False,
            "evidence_source": "",
            "evidence_url": normalized_url or "",
            "confidence": Decimal("0.9000"),
            "notes": "",
            "matched_text": None,
            "blocker": (
                "No explicit factory-sealed token was found "
                "in the listing title."
            ),
        }

    matched_text = positive_match.group(0)

    return {
        "eligible": True,
        "evidence_source": "LISTING_TITLE",
        "evidence_url": normalized_url or "",
        "confidence": Decimal("0.9900"),
        "notes": (
            "Listing title explicitly indicates factory-sealed "
            f"condition using '{matched_text}'. "
            f"Reviewed title: {normalized_title}"
        ),
        "matched_text": matched_text,
        "blocker": None,
    }


def build_factory_sealed_prefill(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any]:
    """Load a listing and build reviewed form defaults."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    with engine.connect() as connection:
        listing = connection.execute(
            text(
                """
                SELECT
                    title,
                    auction_url
                FROM warehouse.auction
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
        ).mappings().one_or_none()

    if listing is None:
        raise ValueError(
            "The auction listing does not exist."
        )

    return infer_factory_sealed_title_evidence(
        listing["title"],
        listing["auction_url"],
    )


def validate_factory_sealed_evidence(
    evidence_source: Any,
    evidence_url: Any,
    confidence: Any,
    notes: Any = None,
) -> dict[str, Any]:
    """Validate explicit factory-sealed evidence."""
    normalized_source = _required_text(
        evidence_source,
        "Factory-sealed evidence source",
    )

    normalized_url = _required_text(
        evidence_url,
        "Factory-sealed evidence URL",
    )

    normalized_confidence = _decimal(
        confidence,
        required=True,
        field_name="Factory-sealed confidence",
    )

    if normalized_confidence is None:
        raise ValueError(
            "Factory-sealed confidence is required."
        )

    if (
        normalized_confidence
        < FACTORY_SEALED_MINIMUM_CONFIDENCE
    ):
        raise ValueError(
            "Factory-sealed confidence must be at least 0.90."
        )

    return {
        "component_code":
            FACTORY_SEALED_COMPONENT_CODE,
        "variant_key":
            FACTORY_SEALED_VARIANT_KEY,
        "variant_label":
            FACTORY_SEALED_VARIANT_LABEL,
        "observation_state":
            "PRESENT",
        "observed_quantity":
            1,
        "evidence_source":
            normalized_source,
        "confidence":
            normalized_confidence,
        "evidence_url":
            normalized_url,
        "notes":
            _text(notes),
    }


def load_factory_sealed_observation(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Load reviewed factory-sealed evidence for one listing."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    marketplace,
                    listing_id,
                    component_code,
                    variant_key,
                    variant_label,
                    observation_state,
                    observed_quantity,
                    evidence_source,
                    confidence,
                    evidence_url,
                    notes
                FROM warehouse.auction_component_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                  AND component_code = 'SHRINK_WRAP'
                  AND variant_key = 'FACTORY_SEALED'
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def save_factory_sealed_observation(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    evidence_source: Any,
    evidence_url: Any,
    confidence: Any,
    notes: Any = None,
) -> None:
    """Save one explicit factory-sealed observation only."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    evidence = validate_factory_sealed_evidence(
        evidence_source,
        evidence_url,
        confidence,
        notes,
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )

        assignment_exists = connection.execute(
            text(
                """
                SELECT 1
                FROM warehouse.auction_pressing_assignment
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                FOR UPDATE
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
        ).scalar_one_or_none()

        if assignment_exists is None:
            raise ValueError(
                "An exact pressing assignment is required "
                "before factory-sealed evidence can be saved."
            )

        seal_contradiction = connection.execute(
            text(
                """
                SELECT 1
                FROM warehouse.auction_component_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                  AND component_code = 'SHRINK_WRAP'
                  AND observation_state = 'ABSENT'
                LIMIT 1
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
        ).scalar_one_or_none()

        if seal_contradiction is not None:
            raise ValueError(
                "Factory-sealed evidence conflicts with an "
                "existing SHRINK_WRAP=ABSENT observation."
            )

        connection.execute(
            text(
                """
                DELETE FROM warehouse.auction_component_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                  AND component_code = 'SHRINK_WRAP'
                  AND variant_key = 'FACTORY_SEALED'
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
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
                    evidence_source,
                    confidence,
                    evidence_url,
                    notes,
                    updated_at
                )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :component_code,
                    :variant_key,
                    :variant_label,
                    :observation_state,
                    :observed_quantity,
                    :evidence_source,
                    :confidence,
                    :evidence_url,
                    :notes,
                    now()
                )
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
                **evidence,
            },
        )


def delete_factory_sealed_observation(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> None:
    """Delete only the reviewed factory-sealed evidence row."""
    marketplace_value = _required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = _required_text(
        listing_id,
        "Listing ID",
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM warehouse.auction_component_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                  AND component_code = 'SHRINK_WRAP'
                  AND variant_key = 'FACTORY_SEALED'
                """
            ),
            {
                "marketplace": marketplace_value,
                "listing_id": listing_id_value,
            },
        )
# factory-sealed-evidence:end
