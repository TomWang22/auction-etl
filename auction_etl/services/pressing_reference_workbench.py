"""General pressing-reference worksheets and deterministic verdicts."""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.pressing_reference_admin import (
    list_component_types,
    load_reference_rows,
    reference_summary,
    save_reference_rows,
)


REFERENCE_CSV_COLUMNS = (
    "component_code",
    "display_name",
    "applicable_media",
    "variant_key",
    "variant_label",
    "expectation_state",
    "expected_quantity",
    "evidence_source",
    "confidence",
    "notes",
)

IMPORT_MODES = (
    "DRAFT",
    "VERIFIED",
)

CLONE_MODES = (
    "DRAFT",
    "VERIFIED_COPY",
)

CANONICAL_CONDITION_FACTORS: dict[str, Decimal] = {
    "M": Decimal("1.0000"),
    "MINT": Decimal("1.0000"),
    "NM": Decimal("0.9700"),
    "NEAR_MINT": Decimal("0.9700"),
    "EX": Decimal("0.9000"),
    "EXCELLENT": Decimal("0.9000"),
    "E": Decimal("0.8500"),
    "E-": Decimal("0.8000"),
    "VG+": Decimal("0.7200"),
    "VG": Decimal("0.6200"),
    "G": Decimal("0.4500"),
    "GOOD": Decimal("0.4500"),
    "FAIR": Decimal("0.3000"),
    "DAMAGED": Decimal("0.2500"),
    "PARTIAL": Decimal("0.2000"),
    "TORN": Decimal("0.2000"),
    "TAPED": Decimal("0.6500"),
    "POOR": Decimal("0.1500"),
}

ANALYTICS_RELATIONS = {
    "auction_scores",
    "emotional_damage",
    "auction_alerts",
    "midfication_detection",
    "completeness_premium",
    "obi_premium",
    "obi_variant_price_summary",
}


def _is_missing(value: Any) -> bool:
    """Return whether a value should be treated as absent."""
    if value is None:
        return True

    rendered = str(value).strip()

    return rendered in {
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
    """Normalize a non-negative integer."""
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


def _decimal(
    value: Any,
    *,
    field_name: str,
    default: Decimal | None = None,
) -> Decimal:
    """Normalize a decimal."""
    if _is_missing(value):
        if default is None:
            raise ValueError(
                f"{field_name} is required."
            )

        return default

    try:
        normalized = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error

    return normalized


def _percent(
    numerator: Decimal,
    denominator: Decimal,
) -> Decimal | None:
    """Calculate a percentage safely."""
    if denominator <= 0:
        return None

    return (
        numerator
        / denominator
        * Decimal("100")
    ).quantize(
        Decimal("0.01")
    )


def _condition_token(value: Any) -> str | None:
    """Normalize an exact canonical component-condition token."""
    normalized = _optional_text(value)

    if normalized is None:
        return None

    return (
        normalized.upper()
        .replace(" ", "_")
    )


def list_reference_library(
    engine: Engine,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return all pressings and their shared-reference status."""
    normalized_search = _optional_text(search)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                WITH active_components AS (
                    SELECT COUNT(*) AS active_component_count
                    FROM system.component_type
                    WHERE active
                )
                SELECT
                    pressing.id AS pressing_id,
                    family.display_artist,
                    family.display_title,
                    family.original_release_year,
                    pressing.catalog_number,
                    pressing.matrix_number,
                    pressing.label_name,
                    pressing.country,
                    pressing.region,
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
                        DISTINCT expectation.component_code
                    ) AS configured_component_count,
                    COUNT(*) FILTER (
                        WHERE expectation.expectation_state =
                            'REQUIRED'
                    ) AS required_reference_rows,
                    COUNT(*) FILTER (
                        WHERE expectation.expectation_state =
                            'NOT_INCLUDED'
                    ) AS not_included_reference_rows,
                    COUNT(*) FILTER (
                        WHERE expectation.expectation_state =
                            'UNKNOWN'
                    ) AS unknown_reference_rows,
                    active.active_component_count,
                    (
                        COUNT(
                            DISTINCT expectation.component_code
                        ) = active.active_component_count
                        AND COUNT(*) FILTER (
                            WHERE expectation.expectation_state =
                                'REQUIRED'
                        ) > 0
                        AND COUNT(*) FILTER (
                            WHERE expectation.expectation_state =
                                'UNKNOWN'
                        ) = 0
                    ) AS verified_reference
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id = pressing.release_family_id
                LEFT JOIN warehouse.auction_pressing_assignment
                    AS assignment
                  ON assignment.pressing_id = pressing.id
                LEFT JOIN warehouse.pressing_component_expectation
                    AS expectation
                  ON expectation.pressing_id = pressing.id
                CROSS JOIN active_components AS active
                WHERE (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        family.display_artist,
                        family.display_title,
                        pressing.catalog_number,
                        pressing.matrix_number,
                        pressing.label_name,
                        pressing.pressing_variant_key,
                        pressing.pressing_variant_label
                    ) ILIKE
                        '%' || CAST(:search AS text) || '%'
                )
                GROUP BY
                    pressing.id,
                    family.id,
                    active.active_component_count
                ORDER BY
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.id
                """
            ),
            {
                "search": normalized_search,
            },
        ).mappings().all()

    result: list[dict[str, Any]] = []

    for row in rows:
        item = dict(row)
        active_count = int(
            item["active_component_count"]
            or 0
        )
        configured_count = int(
            item["configured_component_count"]
            or 0
        )

        item["reference_coverage_percent"] = (
            round(
                configured_count
                / active_count
                * 100,
                2,
            )
            if active_count
            else None
        )

        item["reference_status"] = (
            "VERIFIED"
            if item["verified_reference"]
            else "DRAFT"
        )

        result.append(item)

    return result


def reference_csv_bytes(
    engine: Engine,
    pressing_id: int,
) -> bytes:
    """Export a complete editable worksheet for one pressing."""
    rows = load_reference_rows(
        engine,
        pressing_id,
    )

    buffer = io.StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        buffer,
        fieldnames=REFERENCE_CSV_COLUMNS,
        extrasaction="ignore",
    )

    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                column: (
                    ""
                    if row.get(column) is None
                    else row.get(column)
                )
                for column in REFERENCE_CSV_COLUMNS
            }
        )

    return buffer.getvalue().encode(
        "utf-8-sig"
    )


def parse_reference_csv(
    payload: bytes | str,
) -> list[dict[str, Any]]:
    """Parse one pressing-reference worksheet."""
    if isinstance(payload, bytes):
        source = payload.decode(
            "utf-8-sig"
        )
    else:
        source = payload

    reader = csv.DictReader(
        io.StringIO(source)
    )

    if reader.fieldnames is None:
        raise ValueError(
            "The CSV file has no header."
        )

    required_columns = {
        "component_code",
        "expectation_state",
        "expected_quantity",
        "confidence",
    }

    missing_columns = sorted(
        required_columns
        - set(reader.fieldnames)
    )

    if missing_columns:
        raise ValueError(
            "The CSV file is missing columns: "
            + ", ".join(missing_columns)
        )

    rows: list[dict[str, Any]] = []

    for row_number, source_row in enumerate(
        reader,
        start=2,
    ):
        if not any(
            not _is_missing(value)
            for value in source_row.values()
        ):
            continue

        component_code = _required_text(
            source_row.get(
                "component_code"
            ),
            f"Row {row_number} component code",
        ).upper()

        state = _required_text(
            source_row.get(
                "expectation_state"
            ),
            f"Row {row_number} expectation state",
        ).upper()

        if state not in {
            "REQUIRED",
            "NOT_INCLUDED",
            "UNKNOWN",
        }:
            raise ValueError(
                f"Row {row_number} has unsupported "
                f"expectation state {state}."
            )

        quantity = _integer(
            source_row.get(
                "expected_quantity"
            ),
            field_name=(
                f"Row {row_number} expected quantity"
            ),
            minimum=0,
            default=(
                0
                if state == "NOT_INCLUDED"
                else 1
            ),
        )

        if state == "REQUIRED" and quantity < 1:
            raise ValueError(
                f"Row {row_number} REQUIRED quantity "
                "must be at least 1."
            )

        if state == "NOT_INCLUDED":
            quantity = 0

        confidence = _decimal(
            source_row.get("confidence"),
            field_name=(
                f"Row {row_number} confidence"
            ),
            default=Decimal("0.9000"),
        )

        if not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError(
                f"Row {row_number} confidence must "
                "be between 0 and 1."
            )

        rows.append(
            {
                "component_code":
                    component_code,
                "display_name":
                    _optional_text(
                        source_row.get(
                            "display_name"
                        )
                    ),
                "applicable_media":
                    _optional_text(
                        source_row.get(
                            "applicable_media"
                        )
                    ),
                "variant_key":
                    _optional_text(
                        source_row.get(
                            "variant_key"
                        )
                    )
                    or "",
                "variant_label":
                    _optional_text(
                        source_row.get(
                            "variant_label"
                        )
                    ),
                "expectation_state":
                    state,
                "expected_quantity":
                    quantity,
                "evidence_source":
                    _optional_text(
                        source_row.get(
                            "evidence_source"
                        )
                    ),
                "confidence":
                    confidence.quantize(
                        Decimal("0.0001")
                    ),
                "notes":
                    _optional_text(
                        source_row.get(
                            "notes"
                        )
                    ),
            }
        )

    if not rows:
        raise ValueError(
            "The CSV file contains no reference rows."
        )

    identities: set[
        tuple[str, str]
    ] = set()

    for row in rows:
        identity = (
            str(row["component_code"]),
            str(row["variant_key"]),
        )

        if identity in identities:
            raise ValueError(
                "Duplicate component/variant row: "
                f"{identity[0]}/"
                f"{identity[1] or '(default)'}."
            )

        identities.add(identity)

    return rows


def _draft_rows(
    rows: Iterable[Mapping[str, Any]],
    active_components: Sequence[
        Mapping[str, Any]
    ],
    source_note: str,
) -> list[dict[str, Any]]:
    """Convert imported or cloned rows into a review-required draft."""
    active_by_code = {
        str(component["code"]):
            component
        for component in active_components
    }

    output: list[dict[str, Any]] = []
    represented_codes: set[str] = set()

    for source_row in rows:
        component_code = _required_text(
            source_row.get(
                "component_code"
            ),
            "Component code",
        ).upper()

        if component_code not in active_by_code:
            raise ValueError(
                "Unknown or inactive component: "
                f"{component_code}"
            )

        represented_codes.add(
            component_code
        )

        original_state = (
            _optional_text(
                source_row.get(
                    "expectation_state"
                )
            )
            or "UNKNOWN"
        )

        original_notes = _optional_text(
            source_row.get("notes")
        )

        output.append(
            {
                "component_code":
                    component_code,
                "variant_key":
                    _optional_text(
                        source_row.get(
                            "variant_key"
                        )
                    )
                    or "",
                "variant_label":
                    _optional_text(
                        source_row.get(
                            "variant_label"
                        )
                    ),
                "expectation_state":
                    "UNKNOWN",
                "expected_quantity":
                    _integer(
                        source_row.get(
                            "expected_quantity"
                        ),
                        field_name=(
                            "Expected quantity"
                        ),
                        minimum=0,
                        default=1,
                    ),
                "evidence_source":
                    "DRAFT_TRANSFER",
                "confidence":
                    Decimal("0.5000"),
                "notes":
                    (
                        f"{source_note} "
                        f"Source state was {original_state}. "
                        f"{original_notes or ''}"
                    ).strip(),
            }
        )

    for component_code in sorted(
        set(active_by_code)
        - represented_codes
    ):
        output.append(
            {
                "component_code":
                    component_code,
                "variant_key":
                    "",
                "variant_label":
                    None,
                "expectation_state":
                    "UNKNOWN",
                "expected_quantity":
                    1,
                "evidence_source":
                    "DRAFT_TRANSFER",
                "confidence":
                    Decimal("0.5000"),
                "notes":
                    (
                        f"{source_note} Component was not "
                        "included in the source worksheet."
                    ),
            }
        )

    return output


def _replace_reference_rows_directly(
    engine: Engine,
    pressing_id: int,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Replace one pressing reference without marking it verified."""
    normalized_rows = list(rows)

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
                "pressing_id": pressing_id,
            },
        ).scalar_one_or_none()

        if pressing_exists is None:
            raise ValueError(
                f"Pressing #{pressing_id} does not exist."
            )

        connection.execute(
            text(
                """
                DELETE FROM
                    warehouse.pressing_component_expectation
                WHERE pressing_id = :pressing_id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        )

        if not normalized_rows:
            return

        connection.execute(
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
                """
            ),
            [
                {
                    "pressing_id":
                        pressing_id,
                    **row,
                }
                for row in normalized_rows
            ],
        )


def import_reference_csv(
    engine: Engine,
    pressing_id: int,
    payload: bytes | str,
    mode: str,
) -> dict[str, Any]:
    """Import a worksheet as a draft or verified reference."""
    normalized_mode = _required_text(
        mode,
        "Import mode",
    ).upper()

    if normalized_mode not in IMPORT_MODES:
        raise ValueError(
            f"Unsupported import mode: {normalized_mode}"
        )

    rows = parse_reference_csv(
        payload
    )

    if normalized_mode == "VERIFIED":
        return save_reference_rows(
            engine,
            pressing_id,
            rows,
        )

    active_components = list_component_types(
        engine
    )

    draft_rows = _draft_rows(
        rows,
        active_components,
        "Imported as a draft worksheet.",
    )

    _replace_reference_rows_directly(
        engine,
        pressing_id,
        draft_rows,
    )

    return reference_summary(
        engine,
        pressing_id,
    )


def clone_reference(
    engine: Engine,
    source_pressing_id: int,
    target_pressing_id: int,
    mode: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Clone one shared reference safely between exact pressings."""
    if source_pressing_id == target_pressing_id:
        raise ValueError(
            "Source and target pressings must differ."
        )

    normalized_mode = _required_text(
        mode,
        "Clone mode",
    ).upper()

    if normalized_mode not in CLONE_MODES:
        raise ValueError(
            f"Unsupported clone mode: {normalized_mode}"
        )

    with engine.connect() as connection:
        source_rows = connection.execute(
            text(
                """
                SELECT
                    component_code,
                    variant_key,
                    variant_label,
                    expectation_state,
                    expected_quantity,
                    evidence_source,
                    confidence,
                    notes
                FROM warehouse.pressing_component_expectation
                WHERE pressing_id = :pressing_id
                ORDER BY
                    component_code,
                    variant_key,
                    id
                """
            ),
            {
                "pressing_id":
                    source_pressing_id,
            },
        ).mappings().all()

        target_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM warehouse.pressing_component_expectation
                WHERE pressing_id = :pressing_id
                """
            ),
            {
                "pressing_id":
                    target_pressing_id,
            },
        ).scalar_one()

    if not source_rows:
        raise ValueError(
            "The source pressing has no reference rows."
        )

    if target_count and not overwrite:
        raise ValueError(
            "The target pressing already has a reference. "
            "Enable overwrite explicitly."
        )

    source_payload = [
        dict(row)
        for row in source_rows
    ]

    if normalized_mode == "VERIFIED_COPY":
        return save_reference_rows(
            engine,
            target_pressing_id,
            source_payload,
        )

    if normalized_mode != "DRAFT":
        raise AssertionError(
            "Validated clone mode reached an impossible branch."
        )

    active_components = list_component_types(
        engine
    )

    draft_rows = _draft_rows(
        source_payload,
        active_components,
        (
            "Cloned as a review-required draft from "
            f"pressing #{source_pressing_id}."
        ),
    )

    _replace_reference_rows_directly(
        engine,
        target_pressing_id,
        draft_rows,
    )

    return reference_summary(
        engine,
        target_pressing_id,
    )


def _load_required_component_rows(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> list[dict[str, Any]]:
    """Return required expectations joined to exact observations."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    assignment.pressing_id,
                    expectation.component_code,
                    expectation.variant_key,
                    expectation.variant_label,
                    expectation.expected_quantity,
                    observation.observation_state,
                    observation.observed_quantity,
                    observation.normalized_condition,
                    observation.source_condition_text,
                    observation.evidence_source,
                    observation.confidence,
                    observation.notes
                FROM warehouse.auction_pressing_assignment
                    AS assignment
                JOIN warehouse.pressing_component_expectation
                    AS expectation
                  ON expectation.pressing_id =
                        assignment.pressing_id
                 AND expectation.expectation_state =
                        'REQUIRED'
                LEFT JOIN warehouse.auction_component_observation
                    AS observation
                  ON observation.marketplace =
                        assignment.marketplace
                 AND observation.listing_id =
                        assignment.listing_id
                 AND observation.component_code =
                        expectation.component_code
                 AND observation.variant_key =
                        expectation.variant_key
                WHERE assignment.marketplace =
                        :marketplace
                  AND assignment.listing_id =
                        :listing_id
                ORDER BY
                    expectation.component_code,
                    expectation.variant_key
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def calculate_component_score(
    rows: Iterable[Mapping[str, Any]],
    completeness_status: str | None = None,
) -> dict[str, Any]:
    """Calculate deterministic completeness and damage percentages."""
    normalized_rows = list(rows)

    required_units = Decimal("0")
    present_units = Decimal("0")
    absent_units = Decimal("0")
    unverified_units = Decimal("0")
    graded_units = Decimal("0")
    weighted_condition_units = Decimal("0")

    component_details: list[
        dict[str, Any]
    ] = []

    for row in normalized_rows:
        expected_quantity = Decimal(
            str(
                row.get(
                    "expected_quantity"
                )
                or 1
            )
        )

        required_units += expected_quantity

        state = (
            _optional_text(
                row.get(
                    "observation_state"
                )
            )
            or "UNOBSERVED"
        ).upper()

        observed_quantity = Decimal(
            str(
                row.get(
                    "observed_quantity"
                )
                if row.get(
                    "observed_quantity"
                ) is not None
                else (
                    1
                    if state == "PRESENT"
                    else 0
                )
            )
        )

        confirmed_present = Decimal("0")
        confirmed_absent = Decimal("0")
        unresolved = Decimal("0")

        if state == "PRESENT":
            confirmed_present = min(
                max(
                    observed_quantity,
                    Decimal("0"),
                ),
                expected_quantity,
            )

            if confirmed_present < expected_quantity:
                unresolved = (
                    expected_quantity
                    - confirmed_present
                )
        elif state == "ABSENT":
            confirmed_absent = expected_quantity
        else:
            unresolved = expected_quantity

        present_units += confirmed_present
        absent_units += confirmed_absent
        unverified_units += unresolved

        condition_token = _condition_token(
            row.get(
                "normalized_condition"
            )
        )

        condition_factor = (
            CANONICAL_CONDITION_FACTORS.get(
                condition_token
            )
            if condition_token is not None
            else None
        )

        if (
            confirmed_present > 0
            and condition_factor is not None
        ):
            graded_units += confirmed_present
            weighted_condition_units += (
                confirmed_present
                * condition_factor
            )

        component_details.append(
            {
                "component_code":
                    row.get(
                        "component_code"
                    ),
                "variant_key":
                    row.get(
                        "variant_key"
                    ),
                "variant_label":
                    row.get(
                        "variant_label"
                    ),
                "expected_quantity":
                    float(expected_quantity),
                "observation_state":
                    state,
                "observed_quantity":
                    float(observed_quantity),
                "confirmed_present_units":
                    float(confirmed_present),
                "confirmed_absent_units":
                    float(confirmed_absent),
                "unverified_units":
                    float(unresolved),
                "normalized_condition":
                    condition_token,
                "condition_factor":
                    (
                        float(condition_factor)
                        if condition_factor
                        is not None
                        else None
                    ),
            }
        )

    structural_percent = _percent(
        present_units,
        required_units,
    )

    verification_percent = _percent(
        present_units + absent_units,
        required_units,
    )

    condition_coverage_percent = _percent(
        graded_units,
        present_units,
    )

    condition_percent = (
        (
            weighted_condition_units
            / graded_units
            * Decimal("100")
        ).quantize(
            Decimal("0.01")
        )
        if graded_units > 0
        else None
    )

    damage_adjusted_percent = (
        (
            structural_percent
            * condition_percent
            / Decimal("100")
        ).quantize(
            Decimal("0.01")
        )
        if (
            structural_percent is not None
            and condition_percent is not None
            and condition_coverage_percent
                == Decimal("100.00")
        )
        else None
    )

    damage_penalty_percent = (
        (
            structural_percent
            - damage_adjusted_percent
        ).quantize(
            Decimal("0.01")
        )
        if (
            structural_percent is not None
            and damage_adjusted_percent
                is not None
        )
        else None
    )

    status = (
        completeness_status
        or ""
    ).upper()

    if required_units <= 0:
        verdict = "NO_REFERENCE"
    elif status == "FACTORY_SEALED_EXCEPTION":
        verdict = "FACTORY_SEALED_EXCEPTION"
    elif absent_units > 0 or status == "INCOMPLETE":
        verdict = "INCOMPLETE"
    elif unverified_units > 0 or status == "UNVERIFIED":
        verdict = "UNVERIFIED"
    elif condition_coverage_percent != Decimal("100.00"):
        verdict = "COMPLETE_UNGRADED"
    elif condition_percent is None:
        verdict = "COMPLETE_UNGRADED"
    elif condition_percent < Decimal("70"):
        verdict = "COMPLETE_DAMAGED"
    elif condition_percent < Decimal("85"):
        verdict = "COMPLETE_WORN"
    else:
        verdict = "COMPLETE_STRONG"

    return {
        "required_units":
            float(required_units),
        "present_units":
            float(present_units),
        "absent_units":
            float(absent_units),
        "unverified_units":
            float(unverified_units),
        "graded_present_units":
            float(graded_units),
        "structural_completeness_percent":
            (
                float(structural_percent)
                if structural_percent
                is not None
                else None
            ),
        "verification_percent":
            (
                float(verification_percent)
                if verification_percent
                is not None
                else None
            ),
        "condition_coverage_percent":
            (
                float(condition_coverage_percent)
                if condition_coverage_percent
                is not None
                else None
            ),
        "condition_percent":
            (
                float(condition_percent)
                if condition_percent
                is not None
                else None
            ),
        "damage_adjusted_percent":
            (
                float(damage_adjusted_percent)
                if damage_adjusted_percent
                is not None
                else None
            ),
        "damage_penalty_percent":
            (
                float(damage_penalty_percent)
                if damage_penalty_percent
                is not None
                else None
            ),
        "verdict":
            verdict,
        "components":
            component_details,
    }


def listing_component_score(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any]:
    """Calculate one listing's deterministic component score."""
    with engine.connect() as connection:
        listing = connection.execute(
            text(
                """
                SELECT
                    auction.id,
                    auction.marketplace,
                    auction.listing_id,
                    auction.title,
                    auction.seller,
                    auction.catalog_number,
                    auction.media_type,
                    auction.currency,
                    auction.final_price,
                    auction.gross_price_usd,
                    auction.landed_price_usd,
                    auction.ended_at,
                    assignment.pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.pressing_variant_label
                FROM warehouse.auction AS auction
                LEFT JOIN warehouse.auction_pressing_assignment
                    AS assignment
                  ON assignment.marketplace =
                        auction.marketplace
                 AND assignment.listing_id =
                        auction.listing_id
                LEFT JOIN warehouse.pressing_identity
                    AS pressing
                  ON pressing.id =
                        assignment.pressing_id
                LEFT JOIN warehouse.release_family
                    AS family
                  ON family.id =
                        pressing.release_family_id
                WHERE auction.marketplace =
                        :marketplace
                  AND auction.listing_id =
                        :listing_id
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).mappings().one_or_none()

        completeness = connection.execute(
            text(
                """
                SELECT to_jsonb(completeness_row)
                FROM warehouse.auction_completeness
                    AS completeness_row
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one_or_none()

    if listing is None:
        raise ValueError(
            f"Listing {marketplace}/{listing_id} "
            "does not exist."
        )

    component_rows = _load_required_component_rows(
        engine,
        marketplace,
        listing_id,
    )

    completeness_payload = (
        dict(completeness)
        if completeness is not None
        else {}
    )

    score = calculate_component_score(
        component_rows,
        completeness_payload.get(
            "completeness_status"
        ),
    )

    score["listing"] = dict(listing)
    score["database_completeness"] = (
        completeness_payload
    )

    return score


def pressing_listing_scores(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Calculate deterministic component scores for a pressing cohort."""
    with engine.connect() as connection:
        listings = connection.execute(
            text(
                """
                SELECT
                    assignment.marketplace,
                    assignment.listing_id
                FROM warehouse.auction_pressing_assignment
                    AS assignment
                WHERE assignment.pressing_id =
                        :pressing_id
                ORDER BY
                    assignment.marketplace,
                    assignment.listing_id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        ).mappings().all()

    result: list[dict[str, Any]] = []

    for listing in listings:
        score = listing_component_score(
            engine,
            str(listing["marketplace"]),
            str(listing["listing_id"]),
        )

        listing_payload = score["listing"]

        result.append(
            {
                "marketplace":
                    listing_payload[
                        "marketplace"
                    ],
                "listing_id":
                    listing_payload[
                        "listing_id"
                    ],
                "title":
                    listing_payload[
                        "title"
                    ],
                "seller":
                    listing_payload[
                        "seller"
                    ],
                "structural_completeness_percent":
                    score[
                        "structural_completeness_percent"
                    ],
                "verification_percent":
                    score[
                        "verification_percent"
                    ],
                "condition_coverage_percent":
                    score[
                        "condition_coverage_percent"
                    ],
                "condition_percent":
                    score[
                        "condition_percent"
                    ],
                "damage_adjusted_percent":
                    score[
                        "damage_adjusted_percent"
                    ],
                "damage_penalty_percent":
                    score[
                        "damage_penalty_percent"
                    ],
                "verdict":
                    score["verdict"],
            }
        )

    return result


def _relation_columns(
    engine: Engine,
    relation: str,
) -> set[str]:
    """Return columns for one approved analytics relation."""
    if relation not in ANALYTICS_RELATIONS:
        raise ValueError(
            f"Unsupported analytics relation: {relation}"
        )

    with engine.connect() as connection:
        columns = connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'analytics'
                  AND table_name = :relation
                """
            ),
            {
                "relation": relation,
            },
        ).scalars().all()

    return {
        str(column)
        for column in columns
    }


def load_analytics_rows(
    engine: Engine,
    relation: str,
    filters: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Load existing analytics rows without assuming their columns."""
    columns = _relation_columns(
        engine,
        relation,
    )

    if not columns:
        return []

    usable_filters = {
        key: value
        for key, value in filters.items()
        if key in columns
        and value is not None
    }

    where_clause = ""

    if usable_filters:
        predicates = [
            f"{column} = :{column}"
            for column in usable_filters
        ]

        where_clause = (
            "WHERE "
            + " AND ".join(predicates)
        )

    statement = text(
        f"""
        SELECT to_jsonb(analytics_row)
        FROM analytics.{relation}
            AS analytics_row
        {where_clause}
        LIMIT 200
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            usable_filters,
        ).scalars().all()

    return [
        dict(row)
        for row in rows
    ]


def listing_verdict_bundle(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any]:
    """Return deterministic and existing analytics verdicts."""
    component_score = listing_component_score(
        engine,
        marketplace,
        listing_id,
    )

    pressing_id = component_score[
        "listing"
    ].get(
        "pressing_id"
    )

    listing_filters = {
        "marketplace": marketplace,
        "listing_id": listing_id,
        "pressing_id": pressing_id,
    }

    pressing_filters = {
        "pressing_id": pressing_id,
    }

    return {
        "component_score":
            component_score,
        "auction_scores":
            load_analytics_rows(
                engine,
                "auction_scores",
                listing_filters,
            ),
        "emotional_damage":
            load_analytics_rows(
                engine,
                "emotional_damage",
                listing_filters,
            ),
        "auction_alerts":
            load_analytics_rows(
                engine,
                "auction_alerts",
                listing_filters,
            ),
        "midfication_detection":
            load_analytics_rows(
                engine,
                "midfication_detection",
                listing_filters,
            ),
        "completeness_premium":
            load_analytics_rows(
                engine,
                "completeness_premium",
                pressing_filters,
            ),
        "obi_premium":
            load_analytics_rows(
                engine,
                "obi_premium",
                pressing_filters,
            ),
        "obi_variant_price_summary":
            load_analytics_rows(
                engine,
                "obi_variant_price_summary",
                pressing_filters,
            ),
    }
