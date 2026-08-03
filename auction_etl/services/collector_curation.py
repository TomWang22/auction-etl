"""Persistence services for manual collector analytics curation."""

from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine


PRESSING_GENERATIONS = (
    "FIRST_PRESS",
    "EARLY_PRESS",
    "STANDARD",
    "PROMO",
    "REISSUE",
    "MODERN_REPRESS",
    "UNKNOWN",
)

MATCH_BASES = (
    "MANUAL",
    "CATALOG_EXACT",
    "MATRIX_EXACT",
    "TITLE_RULE",
    "MODEL",
    "IMPORT",
    "UNKNOWN",
)

EXPECTATION_STATES = (
    "REQUIRED",
    "OPTIONAL",
    "NOT_INCLUDED",
    "UNKNOWN",
)

OBSERVATION_STATES = (
    "PRESENT",
    "ABSENT",
    "UNKNOWN",
    "NOT_VISIBLE",
    "NOT_APPLICABLE",
)

BIDDER_STATES = (
    "OBSERVED",
    "MANUAL",
    "NOT_EXPOSED",
    "UNAVAILABLE",
    "ESTIMATED",
)

BIDDER_COUNT_REQUIRED_STATES = frozenset(
    {
        "OBSERVED",
        "MANUAL",
        "ESTIMATED",
    }
)

BIDDER_COUNT_NULL_STATES = frozenset(
    {
        "NOT_EXPOSED",
        "UNAVAILABLE",
    }
)

PRICE_BASES = (
    "HAMMER",
    "GROSS",
    "LANDED",
)


def is_missing(value: Any) -> bool:
    """Return whether a scalar represents missing input."""
    if value is None:
        return True

    if isinstance(value, float):
        return math.isnan(value)

    return False


def nullable_text(value: Any) -> str | None:
    """Normalize optional text without fabricating a value."""
    if is_missing(value):
        return None

    normalized = str(value).strip()
    return normalized or None


def required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = nullable_text(value)

    if normalized is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def normalize_identity_key(value: Any) -> str:
    """Create a stable Unicode-aware release identity key."""
    normalized = unicodedata.normalize(
        "NFKC",
        required_text(
            value,
            "Identity value",
        ),
    )

    return re.sub(
        r"\s+",
        " ",
        normalized.casefold(),
    ).strip()


def optional_integer(
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    field_name: str = "Value",
) -> int | None:
    """Validate an optional integer."""
    if is_missing(value) or value == "":
        return None

    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be an integer."
        ) from error

    if (
        minimum is not None
        and normalized < minimum
    ):
        raise ValueError(
            f"{field_name} must be at least {minimum}."
        )

    if (
        maximum is not None
        and normalized > maximum
    ):
        raise ValueError(
            f"{field_name} must be at most {maximum}."
        )

    return normalized


def optional_decimal(
    value: Any,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    minimum_exclusive: bool = False,
    field_name: str = "Value",
) -> Decimal | None:
    """Validate an optional decimal."""
    if is_missing(value) or value == "":
        return None

    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error

    if not normalized.is_finite():
        raise ValueError(
            f"{field_name} must be finite."
        )

    if minimum is not None:
        invalid_minimum = (
            normalized <= minimum
            if minimum_exclusive
            else normalized < minimum
        )

        if invalid_minimum:
            comparison = (
                "greater than"
                if minimum_exclusive
                else "at least"
            )

            raise ValueError(
                f"{field_name} must be "
                f"{comparison} {minimum}."
            )

    if (
        maximum is not None
        and normalized > maximum
    ):
        raise ValueError(
            f"{field_name} must be at most {maximum}."
        )

    return normalized


def validated_choice(
    value: Any,
    choices: tuple[str, ...],
    field_name: str,
    default: str,
) -> str:
    """Validate one constrained text state."""
    normalized = str(
        value or default
    ).strip().upper()

    if normalized not in choices:
        raise ValueError(
            f"{field_name} must be one of: "
            f"{', '.join(choices)}."
        )

    return normalized


def normalize_bidder_count(
    state: Any,
    count: Any,
) -> tuple[str, int | None]:
    """Enforce nullable distinct-bidder semantics."""
    normalized_state = validated_choice(
        state,
        BIDDER_STATES,
        "Distinct bidder state",
        "UNAVAILABLE",
    )

    if normalized_state in BIDDER_COUNT_NULL_STATES:
        return normalized_state, None

    normalized_count = optional_integer(
        count,
        minimum=0,
        field_name="Distinct bidder count",
    )

    if normalized_count is None:
        raise ValueError(
            "Distinct bidder count is required "
            f"when state is {normalized_state}."
        )

    return normalized_state, normalized_count


def normalize_component_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate a complete component-editor snapshot."""
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
        component_code = required_text(
            row.get("component_code"),
            f"Row {index} component code",
        ).upper()

        variant_key = (
            nullable_text(
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
                "Duplicate component identity: "
                f"{component_code} / "
                f"{variant_key or 'default'}."
            )

        identities.add(identity)

        expectation_state = validated_choice(
            row.get("expectation_state"),
            EXPECTATION_STATES,
            f"Row {index} expectation state",
            "UNKNOWN",
        )

        observation_state = validated_choice(
            row.get("observation_state"),
            OBSERVATION_STATES,
            f"Row {index} observation state",
            "UNKNOWN",
        )

        normalized_rows.append(
            {
                "component_code":
                    component_code,
                "variant_key":
                    variant_key,
                "variant_label":
                    nullable_text(
                        row.get("variant_label")
                    ),
                "expectation_state":
                    expectation_state,
                "expected_quantity":
                    optional_integer(
                        row.get(
                            "expected_quantity"
                        ),
                        minimum=1,
                        field_name=(
                            f"Row {index} "
                            "expected quantity"
                        ),
                    )
                    or 1,
                "expectation_evidence_source":
                    nullable_text(
                        row.get(
                            "expectation_evidence_source"
                        )
                    ),
                "expectation_confidence":
                    optional_decimal(
                        row.get(
                            "expectation_confidence"
                        ),
                        minimum=Decimal("0"),
                        maximum=Decimal("1"),
                        field_name=(
                            f"Row {index} "
                            "expectation confidence"
                        ),
                    ),
                "expectation_notes":
                    nullable_text(
                        row.get(
                            "expectation_notes"
                        )
                    ),
                "observation_state":
                    observation_state,
                "observed_quantity":
                    optional_integer(
                        row.get(
                            "observed_quantity"
                        ),
                        minimum=0,
                        field_name=(
                            f"Row {index} "
                            "observed quantity"
                        ),
                    ),
                "normalized_condition":
                    nullable_text(
                        row.get(
                            "normalized_condition"
                        )
                    ),
                "source_condition_text":
                    nullable_text(
                        row.get(
                            "source_condition_text"
                        )
                    ),
                "observation_evidence_source":
                    nullable_text(
                        row.get(
                            "observation_evidence_source"
                        )
                    ),
                "observation_confidence":
                    optional_decimal(
                        row.get(
                            "observation_confidence"
                        ),
                        minimum=Decimal("0"),
                        maximum=Decimal("1"),
                        field_name=(
                            f"Row {index} "
                            "observation confidence"
                        ),
                    ),
                "evidence_url":
                    nullable_text(
                        row.get("evidence_url")
                    ),
                "observation_notes":
                    nullable_text(
                        row.get(
                            "observation_notes"
                        )
                    ),
            }
        )

    return normalized_rows


def list_component_types(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return active component dictionary entries."""
    statement = text(
        """
        SELECT
            code,
            display_name,
            description,
            applicable_media,
            sort_order
        FROM system.component_type
        WHERE active
        ORDER BY sort_order, code
        """
    )

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement
            ).mappings()
        ]


def list_condition_grades(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return canonical condition grades."""
    statement = text(
        """
        SELECT
            code,
            display_name,
            sort_rank,
            score_20,
            market_value_factor,
            description
        FROM system.condition_grade
        ORDER BY sort_rank, code
        """
    )

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement
            ).mappings()
        ]


def list_pressings(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return reusable exact pressing identities."""
    statement = text(
        """
        SELECT
            pressing.id,
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
            pressing.parent_first_press_id
        FROM warehouse.pressing_identity AS pressing
        JOIN warehouse.release_family AS family
          ON family.id =
                pressing.release_family_id
        ORDER BY
            family.display_artist,
            family.display_title,
            pressing.catalog_number,
            pressing.region,
            pressing.id
        """
    )

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement
            ).mappings()
        ]


def load_assignment(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return the exact pressing assigned to one listing."""
    statement = text(
        """
        SELECT
            assignment.id AS assignment_id,
            assignment.pressing_id,
            assignment.match_basis,
            assignment.match_confidence,
            assignment.is_manual_override,
            assignment.notes AS assignment_notes,
            family.id AS release_family_id,
            family.artist_key,
            family.title_key,
            family.display_artist,
            family.display_title,
            family.original_release_year,
            family.notes AS family_notes,
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
            pressing.parent_first_press_id,
            pressing.notes AS pressing_notes
        FROM warehouse.auction_pressing_assignment
            AS assignment
        JOIN warehouse.pressing_identity
            AS pressing
          ON pressing.id =
                assignment.pressing_id
        JOIN warehouse.release_family
            AS family
          ON family.id =
                pressing.release_family_id
        WHERE assignment.marketplace =
                :marketplace
          AND assignment.listing_id =
                :listing_id
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            statement,
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def create_and_assign_pressing(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    payload: Mapping[str, Any],
) -> int:
    """Create or reuse a release and pressing, then assign it."""
    marketplace_value = required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = required_text(
        listing_id,
        "Listing ID",
    )

    display_artist = required_text(
        payload.get("display_artist"),
        "Canonical artist",
    )

    display_title = required_text(
        payload.get("display_title"),
        "Canonical release title",
    )

    media_type = required_text(
        payload.get("media_type"),
        "Media type",
    )

    generation = validated_choice(
        payload.get("generation"),
        PRESSING_GENERATIONS,
        "Pressing generation",
        "UNKNOWN",
    )

    match_basis = validated_choice(
        payload.get("match_basis"),
        MATCH_BASES,
        "Match basis",
        "MANUAL",
    )

    match_confidence = optional_decimal(
        payload.get(
            "match_confidence",
            1,
        ),
        minimum=Decimal("0"),
        maximum=Decimal("1"),
        field_name="Match confidence",
    )

    original_release_year = optional_integer(
        payload.get(
            "original_release_year"
        ),
        minimum=1800,
        maximum=2200,
        field_name="Original release year",
    )

    release_year = optional_integer(
        payload.get("release_year"),
        minimum=1800,
        maximum=2200,
        field_name="Pressing year",
    )

    disc_count = optional_integer(
        payload.get("disc_count"),
        minimum=1,
        field_name="Disc count",
    )

    parent_first_press_id = optional_integer(
        payload.get(
            "parent_first_press_id"
        ),
        minimum=1,
        field_name="Parent first-press ID",
    )

    parameters = {
        "marketplace":
            marketplace_value,
        "listing_id":
            listing_id_value,
        "artist_key":
            normalize_identity_key(
                display_artist
            ),
        "title_key":
            normalize_identity_key(
                display_title
            ),
        "display_artist":
            display_artist,
        "display_title":
            display_title,
        "original_release_year":
            original_release_year,
        "family_notes":
            nullable_text(
                payload.get("family_notes")
            ),
        "catalog_number":
            nullable_text(
                payload.get(
                    "catalog_number"
                )
            )
            or "",
        "matrix_number":
            nullable_text(
                payload.get(
                    "matrix_number"
                )
            )
            or "",
        "label_name":
            nullable_text(
                payload.get("label_name")
            )
            or "",
        "region":
            nullable_text(
                payload.get("region")
            )
            or "",
        "country":
            nullable_text(
                payload.get("country")
            )
            or "",
        "media_type":
            media_type,
        "format_detail":
            nullable_text(
                payload.get(
                    "format_detail"
                )
            )
            or "",
        "disc_count":
            disc_count,
        "release_year":
            release_year,
        "generation":
            generation,
        "pressing_variant_key":
            nullable_text(
                payload.get(
                    "pressing_variant_key"
                )
            )
            or "",
        "pressing_variant_label":
            nullable_text(
                payload.get(
                    "pressing_variant_label"
                )
            ),
        "is_first_press":
            generation == "FIRST_PRESS",
        "is_modern_repress":
            generation in {
                "REISSUE",
                "MODERN_REPRESS",
            },
        "parent_first_press_id":
            parent_first_press_id,
        "pressing_notes":
            nullable_text(
                payload.get(
                    "pressing_notes"
                )
            ),
        "match_basis":
            match_basis,
        "match_confidence":
            match_confidence,
        "assignment_notes":
            nullable_text(
                payload.get(
                    "assignment_notes"
                )
            ),
    }

    with engine.begin() as connection:
        release_family_id = (
            connection.execute(
                text(
                    """
                    INSERT INTO warehouse.release_family (
                        artist_key,
                        title_key,
                        display_artist,
                        display_title,
                        original_release_year,
                        notes,
                        updated_at
                    )
                    VALUES (
                        :artist_key,
                        :title_key,
                        :display_artist,
                        :display_title,
                        :original_release_year,
                        :family_notes,
                        now()
                    )
                    ON CONFLICT (
                        artist_key,
                        title_key
                    )
                    DO UPDATE SET
                        display_artist =
                            EXCLUDED.display_artist,
                        display_title =
                            EXCLUDED.display_title,
                        original_release_year =
                            COALESCE(
                                EXCLUDED
                                    .original_release_year,
                                warehouse.release_family
                                    .original_release_year
                            ),
                        notes =
                            COALESCE(
                                EXCLUDED.notes,
                                warehouse.release_family
                                    .notes
                            ),
                        updated_at = now()
                    RETURNING id
                    """
                ),
                parameters,
            ).scalar_one()
        )

        pressing_parameters = {
            **parameters,
            "release_family_id":
                release_family_id,
        }

        pressing_id = connection.execute(
            text(
                """
                INSERT INTO warehouse.pressing_identity (
                    release_family_id,
                    catalog_number,
                    matrix_number,
                    label_name,
                    region,
                    country,
                    media_type,
                    format_detail,
                    disc_count,
                    release_year,
                    generation,
                    pressing_variant_key,
                    pressing_variant_label,
                    is_first_press,
                    is_modern_repress,
                    parent_first_press_id,
                    notes,
                    updated_at
                )
                VALUES (
                    :release_family_id,
                    :catalog_number,
                    :matrix_number,
                    :label_name,
                    :region,
                    :country,
                    :media_type,
                    :format_detail,
                    :disc_count,
                    :release_year,
                    :generation,
                    :pressing_variant_key,
                    :pressing_variant_label,
                    :is_first_press,
                    :is_modern_repress,
                    :parent_first_press_id,
                    :pressing_notes,
                    now()
                )
                ON CONFLICT (
                    release_family_id,
                    catalog_number,
                    matrix_number,
                    region,
                    media_type,
                    pressing_variant_key
                )
                DO UPDATE SET
                    label_name =
                        EXCLUDED.label_name,
                    country =
                        EXCLUDED.country,
                    format_detail =
                        EXCLUDED.format_detail,
                    disc_count =
                        EXCLUDED.disc_count,
                    release_year =
                        EXCLUDED.release_year,
                    generation =
                        EXCLUDED.generation,
                    pressing_variant_label =
                        EXCLUDED
                            .pressing_variant_label,
                    is_first_press =
                        EXCLUDED.is_first_press,
                    is_modern_repress =
                        EXCLUDED.is_modern_repress,
                    parent_first_press_id =
                        EXCLUDED
                            .parent_first_press_id,
                    notes =
                        COALESCE(
                            EXCLUDED.notes,
                            warehouse.pressing_identity
                                .notes
                        ),
                    updated_at = now()
                RETURNING id
                """
            ),
            pressing_parameters,
        ).scalar_one()

        connection.execute(
            text(
                """
                INSERT INTO
                    warehouse.auction_pressing_assignment (
                        marketplace,
                        listing_id,
                        pressing_id,
                        match_basis,
                        match_confidence,
                        is_manual_override,
                        notes,
                        updated_at
                    )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :pressing_id,
                    :match_basis,
                    :match_confidence,
                    true,
                    :assignment_notes,
                    now()
                )
                ON CONFLICT (
                    marketplace,
                    listing_id
                )
                DO UPDATE SET
                    pressing_id =
                        EXCLUDED.pressing_id,
                    match_basis =
                        EXCLUDED.match_basis,
                    match_confidence =
                        EXCLUDED.match_confidence,
                    is_manual_override = true,
                    notes =
                        EXCLUDED.notes,
                    updated_at = now()
                """
            ),
            {
                **parameters,
                "pressing_id":
                    pressing_id,
            },
        )

    return int(pressing_id)


def assign_existing_pressing(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    *,
    notes: str | None = None,
) -> None:
    """Assign a known pressing to a listing manually."""
    normalized_pressing_id = (
        optional_integer(
            pressing_id,
            minimum=1,
            field_name="Pressing ID",
        )
    )

    if normalized_pressing_id is None:
        raise ValueError(
            "Pressing ID is required."
        )

    statement = text(
        """
        INSERT INTO warehouse.auction_pressing_assignment (
            marketplace,
            listing_id,
            pressing_id,
            match_basis,
            match_confidence,
            is_manual_override,
            notes,
            updated_at
        )
        VALUES (
            :marketplace,
            :listing_id,
            :pressing_id,
            'MANUAL',
            1,
            true,
            :notes,
            now()
        )
        ON CONFLICT (
            marketplace,
            listing_id
        )
        DO UPDATE SET
            pressing_id =
                EXCLUDED.pressing_id,
            match_basis = 'MANUAL',
            match_confidence = 1,
            is_manual_override = true,
            notes = EXCLUDED.notes,
            updated_at = now()
        """
    )

    with engine.begin() as connection:
        connection.execute(
            statement,
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
                "pressing_id":
                    normalized_pressing_id,
                "notes":
                    nullable_text(notes),
            },
        )


def load_component_rows(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return expected and observed component rows."""
    statement = text(
        """
        WITH expectations AS (
            SELECT *
            FROM warehouse
                .pressing_component_expectation
            WHERE pressing_id = :pressing_id
        ),
        observations AS (
            SELECT *
            FROM warehouse
                .auction_component_observation
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
        ),
        combined AS (
            SELECT
                COALESCE(
                    expectations.component_code,
                    observations.component_code
                ) AS component_code,
                COALESCE(
                    expectations.variant_key,
                    observations.variant_key,
                    ''
                ) AS variant_key,
                COALESCE(
                    observations.variant_label,
                    expectations.variant_label
                ) AS variant_label,
                expectations.expectation_state,
                expectations.expected_quantity,
                expectations.evidence_source
                    AS expectation_evidence_source,
                expectations.confidence
                    AS expectation_confidence,
                expectations.notes
                    AS expectation_notes,
                observations.observation_state,
                observations.observed_quantity,
                observations.normalized_condition,
                observations.source_condition_text,
                observations.evidence_source
                    AS observation_evidence_source,
                observations.confidence
                    AS observation_confidence,
                observations.evidence_url,
                observations.notes
                    AS observation_notes
            FROM expectations
            FULL OUTER JOIN observations
              ON observations.component_code =
                    expectations.component_code
             AND observations.variant_key =
                    expectations.variant_key
        )
        SELECT
            component.code AS component_code,
            component.display_name,
            component.sort_order,
            COALESCE(
                combined.variant_key,
                ''
            ) AS variant_key,
            combined.variant_label,
            COALESCE(
                combined.expectation_state,
                'UNKNOWN'
            ) AS expectation_state,
            COALESCE(
                combined.expected_quantity,
                1
            ) AS expected_quantity,
            combined.expectation_evidence_source,
            combined.expectation_confidence,
            combined.expectation_notes,
            COALESCE(
                combined.observation_state,
                'UNKNOWN'
            ) AS observation_state,
            combined.observed_quantity,
            combined.normalized_condition,
            combined.source_condition_text,
            combined.observation_evidence_source,
            combined.observation_confidence,
            combined.evidence_url,
            combined.observation_notes
        FROM system.component_type AS component
        LEFT JOIN combined
          ON combined.component_code =
                component.code
        WHERE component.active
        ORDER BY
            component.sort_order,
            component.code,
            combined.variant_key
        """
    )

    normalized_pressing_id = optional_integer(
        pressing_id,
        minimum=1,
        field_name="Pressing ID",
    )

    if normalized_pressing_id is None:
        raise ValueError(
            "Pressing ID is required."
        )

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement,
                {
                    "marketplace":
                        required_text(
                            marketplace,
                            "Marketplace",
                        ),
                    "listing_id":
                        required_text(
                            listing_id,
                            "Listing ID",
                        ),
                    "pressing_id":
                        normalized_pressing_id,
                },
            ).mappings()
        ]


def replace_component_rows(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Replace the complete expected/observed component snapshot."""
    marketplace_value = required_text(
        marketplace,
        "Marketplace",
    )

    listing_id_value = required_text(
        listing_id,
        "Listing ID",
    )

    pressing_id_value = optional_integer(
        pressing_id,
        minimum=1,
        field_name="Pressing ID",
    )

    if pressing_id_value is None:
        raise ValueError(
            "Pressing ID is required."
        )

    normalized_rows = normalize_component_rows(
        rows
    )

    with engine.begin() as connection:
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
                    pressing_id_value,
            },
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
            expectation_meaningful = any(
                (
                    row["expectation_state"]
                    != "UNKNOWN",
                    row["variant_key"] != "",
                    row["variant_label"]
                    is not None,
                    row[
                        "expectation_evidence_source"
                    ]
                    is not None,
                    row[
                        "expectation_confidence"
                    ]
                    is not None,
                    row["expectation_notes"]
                    is not None,
                )
            )

            if expectation_meaningful:
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
                            pressing_id_value,
                        "component_code":
                            row["component_code"],
                        "variant_key":
                            row["variant_key"],
                        "variant_label":
                            row["variant_label"],
                        "expectation_state":
                            row["expectation_state"],
                        "expected_quantity":
                            row["expected_quantity"],
                        "evidence_source":
                            row[
                                "expectation_evidence_source"
                            ],
                        "confidence":
                            row[
                                "expectation_confidence"
                            ],
                        "notes":
                            row["expectation_notes"],
                    },
                )

            observation_meaningful = any(
                (
                    row["observation_state"]
                    != "UNKNOWN",
                    row["observed_quantity"]
                    is not None,
                    row["normalized_condition"]
                    is not None,
                    row["source_condition_text"]
                    is not None,
                    row[
                        "observation_evidence_source"
                    ]
                    is not None,
                    row[
                        "observation_confidence"
                    ]
                    is not None,
                    row["evidence_url"]
                    is not None,
                    row["observation_notes"]
                    is not None,
                )
            )

            if observation_meaningful:
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
                        "component_code":
                            row["component_code"],
                        "variant_key":
                            row["variant_key"],
                        "variant_label":
                            row["variant_label"],
                        "observation_state":
                            row["observation_state"],
                        "observed_quantity":
                            row["observed_quantity"],
                        "normalized_condition":
                            row[
                                "normalized_condition"
                            ],
                        "source_condition_text":
                            row[
                                "source_condition_text"
                            ],
                        "evidence_source":
                            row[
                                "observation_evidence_source"
                            ],
                        "confidence":
                            row[
                                "observation_confidence"
                            ],
                        "evidence_url":
                            row["evidence_url"],
                        "notes":
                            row["observation_notes"],
                    },
                )


def load_completeness(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return derived completeness for one listing."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM warehouse.auction_completeness
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def load_condition(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return normalized condition data."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM warehouse
                    .auction_condition_normalization
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def save_condition(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Upsert normalized media and cover condition."""
    values = {
        "marketplace":
            required_text(
                marketplace,
                "Marketplace",
            ),
        "listing_id":
            required_text(
                listing_id,
                "Listing ID",
            ),
        "media_grade_code":
            nullable_text(
                payload.get(
                    "media_grade_code"
                )
            ),
        "cover_grade_code":
            nullable_text(
                payload.get(
                    "cover_grade_code"
                )
            ),
        "source_media_condition":
            nullable_text(
                payload.get(
                    "source_media_condition"
                )
            ),
        "source_cover_condition":
            nullable_text(
                payload.get(
                    "source_cover_condition"
                )
            ),
        "condition_factor_override":
            optional_decimal(
                payload.get(
                    "condition_factor_override"
                ),
                minimum=Decimal("0"),
                minimum_exclusive=True,
                field_name=(
                    "Condition factor override"
                ),
            ),
        "confidence":
            optional_decimal(
                payload.get("confidence"),
                minimum=Decimal("0"),
                maximum=Decimal("1"),
                field_name="Condition confidence",
            ),
        "notes":
            nullable_text(
                payload.get("notes")
            ),
    }

    meaningful = any(
        value is not None
        for key, value in values.items()
        if key not in {
            "marketplace",
            "listing_id",
        }
    )

    with engine.begin() as connection:
        if not meaningful:
            connection.execute(
                text(
                    """
                    DELETE FROM warehouse
                        .auction_condition_normalization
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                values,
            )
            return

        connection.execute(
            text(
                """
                INSERT INTO warehouse
                    .auction_condition_normalization (
                        marketplace,
                        listing_id,
                        media_grade_code,
                        cover_grade_code,
                        source_media_condition,
                        source_cover_condition,
                        condition_factor_override,
                        confidence,
                        is_manual_override,
                        notes,
                        updated_at
                    )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :media_grade_code,
                    :cover_grade_code,
                    :source_media_condition,
                    :source_cover_condition,
                    :condition_factor_override,
                    :confidence,
                    true,
                    :notes,
                    now()
                )
                ON CONFLICT (
                    marketplace,
                    listing_id
                )
                DO UPDATE SET
                    media_grade_code =
                        EXCLUDED.media_grade_code,
                    cover_grade_code =
                        EXCLUDED.cover_grade_code,
                    source_media_condition =
                        EXCLUDED.source_media_condition,
                    source_cover_condition =
                        EXCLUDED.source_cover_condition,
                    condition_factor_override =
                        EXCLUDED
                            .condition_factor_override,
                    confidence =
                        EXCLUDED.confidence,
                    is_manual_override = true,
                    notes =
                        EXCLUDED.notes,
                    updated_at = now()
                """
            ),
            values,
        )


def load_behavior(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return bidder and closing-window observations."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM warehouse
                    .auction_behavior_observation
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def save_behavior(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Upsert bidder visibility and closing-window evidence."""
    bidder_state, bidder_count = (
        normalize_bidder_count(
            payload.get(
                "distinct_bidder_state"
            ),
            payload.get(
                "distinct_bidder_count"
            ),
        )
    )

    values = {
        "marketplace":
            required_text(
                marketplace,
                "Marketplace",
            ),
        "listing_id":
            required_text(
                listing_id,
                "Listing ID",
            ),
        "distinct_bidder_count":
            bidder_count,
        "distinct_bidder_state":
            bidder_state,
        "distinct_bidder_source":
            nullable_text(
                payload.get(
                    "distinct_bidder_source"
                )
            ),
        "closing_window_minutes":
            optional_integer(
                payload.get(
                    "closing_window_minutes"
                ),
                minimum=0,
                field_name=(
                    "Closing-window minutes"
                ),
            ),
        "closing_window_start_price":
            optional_decimal(
                payload.get(
                    "closing_window_start_price"
                ),
                minimum=Decimal("0"),
                field_name=(
                    "Closing-window start price"
                ),
            ),
        "closing_window_final_price":
            optional_decimal(
                payload.get(
                    "closing_window_final_price"
                ),
                minimum=Decimal("0"),
                field_name=(
                    "Closing-window final price"
                ),
            ),
        "closing_window_currency":
            nullable_text(
                payload.get(
                    "closing_window_currency"
                )
            ),
        "closing_window_escalation_ratio":
            optional_decimal(
                payload.get(
                    "closing_window_escalation_ratio"
                ),
                field_name=(
                    "Closing-window escalation ratio"
                ),
            ),
        "reserve_status":
            nullable_text(
                payload.get(
                    "reserve_status"
                )
            ),
        "notes":
            nullable_text(
                payload.get("notes")
            ),
    }

    with engine.begin() as connection:
        connection.execute(
            text(
                (
                    '\n'
                    '                INSERT INTO warehouse\n'
                    '                    .auction_behavior_observation (\n'
                    '                        marketplace,\n'
                    '                        listing_id,\n'
                    '                        distinct_bidder_count,\n'
                    '                        distinct_bidder_state,\n'
                    '                        distinct_bidder_source,\n'
                    '                        closing_window_minutes,\n'
                    '                        closing_window_start_price,\n'
                    '                        closing_window_final_price,\n'
                    '                        closing_window_currency,\n'
                    '                        reserve_status,\n'
                    '                        notes,\n'
                    '                        updated_at\n'
                    '                    )\n'
                    '                VALUES (\n'
                    '                    :marketplace,\n'
                    '                    :listing_id,\n'
                    '                    :distinct_bidder_count,\n'
                    '                    :distinct_bidder_state,\n'
                    '                    :distinct_bidder_source,\n'
                    '                    :closing_window_minutes,\n'
                    '                    :closing_window_start_price,\n'
                    '                    :closing_window_final_price,\n'
                    '                    :closing_window_currency,\n'
                    '                    :reserve_status,\n'
                    '                    :notes,\n'
                    '                    now()\n'
                    '                )\n'
                    '                ON CONFLICT (\n'
                    '                    marketplace,\n'
                    '                    listing_id\n'
                    '                )\n'
                    '                DO UPDATE SET\n'
                    '                    distinct_bidder_count =\n'
                    '                        EXCLUDED\n'
                    '                            .distinct_bidder_count,\n'
                    '                    distinct_bidder_state =\n'
                    '                        EXCLUDED\n'
                    '                            .distinct_bidder_state,\n'
                    '                    distinct_bidder_source =\n'
                    '                        EXCLUDED\n'
                    '                            .distinct_bidder_source,\n'
                    '                    closing_window_minutes =\n'
                    '                        EXCLUDED\n'
                    '                            .closing_window_minutes,\n'
                    '                    closing_window_start_price =\n'
                    '                        EXCLUDED\n'
                    '                            .closing_window_start_price,\n'
                    '                    closing_window_final_price =\n'
                    '                        EXCLUDED\n'
                    '                            .closing_window_final_price,\n'
                    '                    closing_window_currency =\n'
                    '                        EXCLUDED\n'
                    '                            .closing_window_currency,\n'
                    '                    reserve_status =\n'
                    '                        EXCLUDED.reserve_status,\n'
                    '                    notes =\n'
                    '                        EXCLUDED.notes,\n'
                    '                    updated_at = now()\n'
                    '                '
                )
            ),
            values,
        )


def load_analysis_input(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return manual price and score inputs."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM warehouse.auction_analysis_input
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )


def save_analysis_input(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Upsert manual normalization and score inputs."""
    values = {
        "marketplace":
            required_text(
                marketplace,
                "Marketplace",
            ),
        "listing_id":
            required_text(
                listing_id,
                "Listing ID",
            ),
        "price_basis":
            validated_choice(
                payload.get("price_basis"),
                PRICE_BASES,
                "Price basis",
                "GROSS",
            ),
        "completeness_market_factor":
            optional_decimal(
                payload.get(
                    "completeness_market_factor"
                ),
                minimum=Decimal("0"),
                minimum_exclusive=True,
                field_name=(
                    "Completeness market factor"
                ),
            ),
        "condition_factor_override":
            optional_decimal(
                payload.get(
                    "condition_factor_override"
                ),
                minimum=Decimal("0"),
                minimum_exclusive=True,
                field_name=(
                    "Condition factor override"
                ),
            ),
        "title_strength_score":
            optional_decimal(
                payload.get(
                    "title_strength_score"
                ),
                minimum=Decimal("0"),
                maximum=Decimal("20"),
                field_name=(
                    "Title strength score"
                ),
            ),
        "market_context_score":
            optional_decimal(
                payload.get(
                    "market_context_score"
                ),
                minimum=Decimal("0"),
                maximum=Decimal("20"),
                field_name=(
                    "Market context score"
                ),
            ),
        "manual_auction_behavior_score":
            optional_decimal(
                payload.get(
                    "manual_auction_behavior_score"
                ),
                minimum=Decimal("0"),
                maximum=Decimal("20"),
                field_name=(
                    "Manual auction behavior score"
                ),
            ),
        "expectation_price_usd":
            optional_decimal(
                payload.get(
                    "expectation_price_usd"
                ),
                minimum=Decimal("0"),
                field_name=(
                    "Expectation price USD"
                ),
            ),
        "historical_anchor_usd":
            optional_decimal(
                payload.get(
                    "historical_anchor_usd"
                ),
                minimum=Decimal("0"),
                field_name=(
                    "Historical anchor USD"
                ),
            ),
        "notes":
            nullable_text(
                payload.get("notes")
            ),
    }

    meaningful = any(
        value is not None
        for key, value in values.items()
        if key not in {
            "marketplace",
            "listing_id",
            "price_basis",
        }
    )

    with engine.begin() as connection:
        if (
            not meaningful
            and values["price_basis"]
            == "GROSS"
        ):
            connection.execute(
                text(
                    """
                    DELETE FROM warehouse
                        .auction_analysis_input
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                values,
            )
            return

        connection.execute(
            text(
                """
                INSERT INTO warehouse
                    .auction_analysis_input (
                        marketplace,
                        listing_id,
                        price_basis,
                        completeness_market_factor,
                        condition_factor_override,
                        title_strength_score,
                        market_context_score,
                        manual_auction_behavior_score,
                        expectation_price_usd,
                        historical_anchor_usd,
                        notes,
                        updated_at
                    )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :price_basis,
                    :completeness_market_factor,
                    :condition_factor_override,
                    :title_strength_score,
                    :market_context_score,
                    :manual_auction_behavior_score,
                    :expectation_price_usd,
                    :historical_anchor_usd,
                    :notes,
                    now()
                )
                ON CONFLICT (
                    marketplace,
                    listing_id
                )
                DO UPDATE SET
                    price_basis =
                        EXCLUDED.price_basis,
                    completeness_market_factor =
                        EXCLUDED
                            .completeness_market_factor,
                    condition_factor_override =
                        EXCLUDED
                            .condition_factor_override,
                    title_strength_score =
                        EXCLUDED.title_strength_score,
                    market_context_score =
                        EXCLUDED.market_context_score,
                    manual_auction_behavior_score =
                        EXCLUDED
                            .manual_auction_behavior_score,
                    expectation_price_usd =
                        EXCLUDED.expectation_price_usd,
                    historical_anchor_usd =
                        EXCLUDED.historical_anchor_usd,
                    notes =
                        EXCLUDED.notes,
                    updated_at = now()
                """
            ),
            values,
        )


def load_score_snapshot(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return calculated scoring and emotional-damage output."""
    statement = text(
        """
        SELECT
            scores.title_strength_score,
            scores.completeness_score,
            scores.condition_score,
            scores.auction_behavior_score,
            scores.auction_behavior_coverage,
            scores.market_context_score,
            scores.plushie_index,
            scores.plushie_partial_score,
            scores.plushie_coverage,
            damage.expectation_deviation,
            damage.late_spike,
            damage.historical_anchor_deviation,
            damage.completeness_contradiction,
            damage.first_press_distortion,
            damage.bidder_war_intensity,
            damage.emotional_damage_score,
            damage.emotional_damage_coverage,
            damage.incident_class
        FROM analytics.auction_scores AS scores
        LEFT JOIN analytics.emotional_damage
            AS damage
          ON damage.marketplace =
                scores.marketplace
         AND damage.listing_id =
                scores.listing_id
        WHERE scores.marketplace =
                :marketplace
          AND scores.listing_id =
                :listing_id
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            statement,
            {
                "marketplace":
                    required_text(
                        marketplace,
                        "Marketplace",
                    ),
                "listing_id":
                    required_text(
                        listing_id,
                        "Listing ID",
                    ),
            },
        ).mappings().one_or_none()

    return (
        dict(row)
        if row is not None
        else None
    )
