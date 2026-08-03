"""Evidence-source registry and bulk component-observation imports."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine


OBSERVATION_STATES = (
    "PRESENT",
    "ABSENT",
)

CSV_COLUMNS = (
    "marketplace",
    "listing_id",
    "title",
    "component_code",
    "variant_key",
    "variant_label",
    "observation_state",
    "observed_quantity",
    "normalized_condition",
    "source_condition_text",
    "evidence_source",
    "confidence",
    "evidence_url",
    "notes",
)


@dataclass(frozen=True)
class BulkObservationPreview:
    """Validated preview of one bulk observation worksheet."""

    rows: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    existing_conflicts: tuple[dict[str, Any], ...]
    touched_listing_count: int

    @property
    def ready(self) -> bool:
        """Return whether the worksheet can be applied."""
        return bool(self.rows) and not self.errors

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe preview summary."""
        return {
            "row_count": len(self.rows),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "existing_conflict_count": len(
                self.existing_conflicts
            ),
            "touched_listing_count":
                self.touched_listing_count,
            "ready": self.ready,
        }


def _is_missing(value: Any) -> bool:
    """Return whether a value should be treated as absent."""
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
    result = _optional_text(value)

    if result is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return result


def _integer(
    value: Any,
    *,
    field_name: str,
    default: int,
    minimum: int = 0,
) -> int:
    """Normalize one integer."""
    if _is_missing(value):
        return default

    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be an integer."
        ) from error

    if result < minimum:
        raise ValueError(
            f"{field_name} must be at least {minimum}."
        )

    return result


def _confidence(
    value: Any,
    *,
    field_name: str,
) -> Decimal:
    """Normalize confidence to four decimal places."""
    if _is_missing(value):
        raise ValueError(
            f"{field_name} is required."
        )

    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error

    if not Decimal("0") <= result <= Decimal("1"):
        raise ValueError(
            f"{field_name} must be between 0 and 1."
        )

    return result.quantize(
        Decimal("0.0001")
    )


def normalize_source_key(value: Any) -> str:
    """Normalize one reusable evidence-source key."""
    source = _required_text(
        value,
        "Source key",
    ).upper()

    source = re.sub(
        r"[^A-Z0-9_:-]+",
        "_",
        source,
    ).strip("_")

    if not source:
        raise ValueError(
            "Source key contains no usable characters."
        )

    if len(source) > 80:
        raise ValueError(
            "Source key cannot exceed 80 characters."
        )

    return source


def list_evidence_sources(
    engine: Engine,
    *,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    """Return reusable evidence sources."""
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
                    active,
                    notes,
                    created_at,
                    updated_at
                FROM system.evidence_source_registry
                WHERE (
                    :include_inactive
                    OR active
                )
                ORDER BY
                    active DESC,
                    display_name,
                    source_key
                """
            ),
            {
                "include_inactive":
                    include_inactive,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def save_evidence_source(
    engine: Engine,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Create or update one evidence-source registry row."""
    source_key = normalize_source_key(
        payload.get("source_key")
    )

    display_name = _required_text(
        payload.get("display_name"),
        "Display name",
    )

    source_type = (
        _optional_text(
            payload.get("source_type")
        )
        or "OTHER"
    ).upper()

    default_confidence_value = payload.get(
        "default_confidence"
    )

    default_confidence: Decimal | None

    if _is_missing(
        default_confidence_value
    ):
        default_confidence = None
    else:
        default_confidence = _confidence(
            default_confidence_value,
            field_name="Default confidence",
        )

    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                INSERT INTO system.evidence_source_registry (
                    source_key,
                    display_name,
                    source_type,
                    base_url,
                    default_confidence,
                    active,
                    notes,
                    updated_at
                )
                VALUES (
                    :source_key,
                    :display_name,
                    :source_type,
                    :base_url,
                    :default_confidence,
                    :active,
                    :notes,
                    now()
                )
                ON CONFLICT (source_key)
                DO UPDATE SET
                    display_name =
                        EXCLUDED.display_name,
                    source_type =
                        EXCLUDED.source_type,
                    base_url =
                        EXCLUDED.base_url,
                    default_confidence =
                        EXCLUDED.default_confidence,
                    active =
                        EXCLUDED.active,
                    notes =
                        EXCLUDED.notes,
                    updated_at = now()
                RETURNING
                    source_key,
                    display_name,
                    source_type,
                    base_url,
                    default_confidence,
                    active,
                    notes,
                    created_at,
                    updated_at
                """
            ),
            {
                "source_key": source_key,
                "display_name": display_name,
                "source_type": source_type,
                "base_url": _optional_text(
                    payload.get("base_url")
                ),
                "default_confidence":
                    default_confidence,
                "active": bool(
                    payload.get(
                        "active",
                        True,
                    )
                ),
                "notes": _optional_text(
                    payload.get("notes")
                ),
            },
        ).mappings().one()

    return dict(row)


def set_evidence_source_active(
    engine: Engine,
    source_key: str,
    active: bool,
) -> dict[str, Any]:
    """Enable or disable one evidence source."""
    normalized_key = normalize_source_key(
        source_key
    )

    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                UPDATE system.evidence_source_registry
                SET
                    active = :active,
                    updated_at = now()
                WHERE source_key = :source_key
                RETURNING
                    source_key,
                    display_name,
                    source_type,
                    base_url,
                    default_confidence,
                    active,
                    notes,
                    created_at,
                    updated_at
                """
            ),
            {
                "source_key": normalized_key,
                "active": active,
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Evidence source {normalized_key} does not exist."
        )

    return dict(row)


def export_observation_worksheet(
    engine: Engine,
    pressing_id: int,
) -> bytes:
    """Export assigned listings and component observation slots."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                WITH assigned AS (
                    SELECT
                        assignment.marketplace,
                        assignment.listing_id,
                        auction.title
                    FROM warehouse.auction_pressing_assignment
                        AS assignment
                    JOIN warehouse.auction AS auction
                      ON auction.marketplace =
                            assignment.marketplace
                     AND auction.listing_id =
                            assignment.listing_id
                    WHERE assignment.pressing_id =
                            :pressing_id
                ),
                existing_rows AS (
                    SELECT
                        assigned.marketplace,
                        assigned.listing_id,
                        assigned.title,
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
                    FROM assigned
                    JOIN warehouse.auction_component_observation
                        AS observation
                      ON observation.marketplace =
                            assigned.marketplace
                     AND observation.listing_id =
                            assigned.listing_id
                ),
                empty_slots AS (
                    SELECT
                        assigned.marketplace,
                        assigned.listing_id,
                        assigned.title,
                        component.code AS component_code,
                        ''::varchar AS variant_key,
                        NULL::varchar AS variant_label,
                        NULL::varchar AS observation_state,
                        NULL::integer AS observed_quantity,
                        NULL::varchar AS normalized_condition,
                        NULL::text AS source_condition_text,
                        NULL::text AS evidence_source,
                        NULL::numeric AS confidence,
                        NULL::text AS evidence_url,
                        NULL::text AS notes
                    FROM assigned
                    CROSS JOIN system.component_type
                        AS component
                    WHERE component.active
                      AND NOT EXISTS (
                          SELECT 1
                          FROM warehouse.auction_component_observation
                              AS observation
                          WHERE observation.marketplace =
                                    assigned.marketplace
                            AND observation.listing_id =
                                    assigned.listing_id
                            AND observation.component_code =
                                    component.code
                      )
                )
                SELECT *
                FROM existing_rows

                UNION ALL

                SELECT *
                FROM empty_slots

                ORDER BY
                    marketplace,
                    listing_id,
                    component_code,
                    variant_key
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        ).mappings().all()

    buffer = io.StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_COLUMNS,
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
                for column in CSV_COLUMNS
            }
        )

    return buffer.getvalue().encode(
        "utf-8-sig"
    )


def parse_observation_csv(
    payload: bytes | str,
) -> list[dict[str, Any]]:
    """Parse actionable rows from one observation CSV."""
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
        "marketplace",
        "listing_id",
        "component_code",
        "observation_state",
        "observed_quantity",
        "evidence_source",
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
    identities: set[
        tuple[str, str, str, str]
    ] = set()

    for row_number, source_row in enumerate(
        reader,
        start=2,
    ):
        state_value = _optional_text(
            source_row.get(
                "observation_state"
            )
        )

        non_state_values = (
            source_row.get(
                "observed_quantity"
            ),
            source_row.get(
                "normalized_condition"
            ),
            source_row.get(
                "source_condition_text"
            ),
            source_row.get(
                "evidence_source"
            ),
            source_row.get(
                "confidence"
            ),
            source_row.get(
                "evidence_url"
            ),
            source_row.get(
                "notes"
            ),
        )

        if state_value is None:
            if any(
                not _is_missing(value)
                for value in non_state_values
            ):
                raise ValueError(
                    f"Row {row_number} contains evidence "
                    "but has no observation_state."
                )

            continue

        state = state_value.upper()

        if state not in OBSERVATION_STATES:
            raise ValueError(
                f"Row {row_number} has unsupported "
                f"observation state {state}."
            )

        marketplace = _required_text(
            source_row.get(
                "marketplace"
            ),
            f"Row {row_number} marketplace",
        ).lower()

        listing_id = _required_text(
            source_row.get(
                "listing_id"
            ),
            f"Row {row_number} listing ID",
        )

        component_code = _required_text(
            source_row.get(
                "component_code"
            ),
            f"Row {row_number} component code",
        ).upper()

        variant_key = (
            _optional_text(
                source_row.get(
                    "variant_key"
                )
            )
            or ""
        )

        identity = (
            marketplace,
            listing_id,
            component_code,
            variant_key,
        )

        if identity in identities:
            raise ValueError(
                "Duplicate observation row: "
                + "/".join(
                    (
                        marketplace,
                        listing_id,
                        component_code,
                        variant_key
                        or "(default)",
                    )
                )
            )

        identities.add(identity)

        quantity = _integer(
            source_row.get(
                "observed_quantity"
            ),
            field_name=(
                f"Row {row_number} observed quantity"
            ),
            default=(
                1
                if state == "PRESENT"
                else 0
            ),
            minimum=0,
        )

        if state == "PRESENT" and quantity < 1:
            raise ValueError(
                f"Row {row_number} PRESENT quantity "
                "must be at least 1."
            )

        if state == "ABSENT":
            quantity = 0

        rows.append(
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
                "component_code":
                    component_code,
                "variant_key":
                    variant_key,
                "variant_label":
                    _optional_text(
                        source_row.get(
                            "variant_label"
                        )
                    ),
                "observation_state":
                    state,
                "observed_quantity":
                    quantity,
                "normalized_condition":
                    _optional_text(
                        source_row.get(
                            "normalized_condition"
                        )
                    ),
                "source_condition_text":
                    _optional_text(
                        source_row.get(
                            "source_condition_text"
                        )
                    ),
                "evidence_source":
                    normalize_source_key(
                        source_row.get(
                            "evidence_source"
                        )
                    ),
                "confidence":
                    _confidence(
                        source_row.get(
                            "confidence"
                        ),
                        field_name=(
                            f"Row {row_number} confidence"
                        ),
                    ),
                "evidence_url":
                    _optional_text(
                        source_row.get(
                            "evidence_url"
                        )
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
            "The CSV file contains no actionable observations."
        )

    return rows


def _values_relation(
    rows: Iterable[
        tuple[str, str, str, str]
    ],
) -> tuple[str, dict[str, Any]]:
    """Build a bound PostgreSQL VALUES relation."""
    fragments: list[str] = []
    parameters: dict[str, Any] = {}

    for index, row in enumerate(rows):
        fragments.append(
            (
                f"(:marketplace_{index}, "
                f":listing_id_{index}, "
                f":component_code_{index}, "
                f":variant_key_{index})"
            )
        )

        parameters[
            f"marketplace_{index}"
        ] = row[0]

        parameters[
            f"listing_id_{index}"
        ] = row[1]

        parameters[
            f"component_code_{index}"
        ] = row[2]

        parameters[
            f"variant_key_{index}"
        ] = row[3]

    return (
        ", ".join(fragments),
        parameters,
    )


def preview_bulk_observations(
    engine: Engine,
    payload: bytes | str,
) -> BulkObservationPreview:
    """Validate a worksheet without writing database rows."""
    try:
        rows = parse_observation_csv(
            payload
        )
    except ValueError as error:
        return BulkObservationPreview(
            rows=(),
            errors=(str(error),),
            warnings=(),
            existing_conflicts=(),
            touched_listing_count=0,
        )

    errors: list[str] = []
    warnings: list[str] = []

    listing_keys = sorted(
        {
            (
                str(row["marketplace"]),
                str(row["listing_id"]),
            )
            for row in rows
        }
    )

    component_codes = sorted(
        {
            str(row["component_code"])
            for row in rows
        }
    )

    source_keys = sorted(
        {
            str(row["evidence_source"])
            for row in rows
        }
    )

    with engine.connect() as connection:
        listing_values = ", ".join(
            (
                f"(:listing_marketplace_{index}, "
                f":listing_id_{index})"
            )
            for index, _ in enumerate(
                listing_keys
            )
        )

        listing_parameters: dict[
            str,
            Any,
        ] = {}

        for index, (
            marketplace,
            listing_id,
        ) in enumerate(listing_keys):
            listing_parameters[
                f"listing_marketplace_{index}"
            ] = marketplace

            listing_parameters[
                f"listing_id_{index}"
            ] = listing_id

        listing_rows = connection.execute(
            text(
                f"""
                SELECT
                    requested.marketplace,
                    requested.listing_id,
                    auction.id,
                    auction.media_type
                FROM (
                    VALUES {listing_values}
                ) AS requested(
                    marketplace,
                    listing_id
                )
                LEFT JOIN warehouse.auction AS auction
                  ON auction.marketplace =
                        requested.marketplace
                 AND auction.listing_id =
                        requested.listing_id
                """
            ),
            listing_parameters,
        ).mappings().all()

        component_rows = connection.execute(
            text(
                """
                SELECT
                    code,
                    applicable_media
                FROM system.component_type
                WHERE active
                  AND code = ANY(
                      CAST(:component_codes AS text[])
                  )
                """
            ),
            {
                "component_codes":
                    component_codes,
            },
        ).mappings().all()

        source_rows = connection.execute(
            text(
                """
                SELECT
                    source_key,
                    active
                FROM system.evidence_source_registry
                WHERE source_key = ANY(
                    CAST(:source_keys AS text[])
                )
                """
            ),
            {
                "source_keys": source_keys,
            },
        ).mappings().all()

        identities = [
            (
                str(row["marketplace"]),
                str(row["listing_id"]),
                str(row["component_code"]),
                str(row["variant_key"]),
            )
            for row in rows
        ]

        values_sql, values_parameters = (
            _values_relation(
                identities
            )
        )

        conflict_rows = connection.execute(
            text(
                f"""
                SELECT
                    requested.marketplace,
                    requested.listing_id,
                    requested.component_code,
                    requested.variant_key,
                    existing.observation_state,
                    existing.observed_quantity,
                    existing.evidence_source,
                    existing.confidence
                FROM (
                    VALUES {values_sql}
                ) AS requested(
                    marketplace,
                    listing_id,
                    component_code,
                    variant_key
                )
                JOIN warehouse.auction_component_observation
                    AS existing
                  ON existing.marketplace =
                        requested.marketplace
                 AND existing.listing_id =
                        requested.listing_id
                 AND existing.component_code =
                        requested.component_code
                 AND existing.variant_key =
                        requested.variant_key
                ORDER BY
                    requested.marketplace,
                    requested.listing_id,
                    requested.component_code,
                    requested.variant_key
                """
            ),
            values_parameters,
        ).mappings().all()

    listing_map = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        ): dict(row)
        for row in listing_rows
    }

    missing_listings = [
        (
            marketplace,
            listing_id,
        )
        for marketplace, listing_id
        in listing_keys
        if listing_map[
            (
                marketplace,
                listing_id,
            )
        ]["id"] is None
    ]

    for marketplace, listing_id in (
        missing_listings
    ):
        errors.append(
            "Listing does not exist: "
            f"{marketplace}/{listing_id}"
        )

    component_map = {
        str(row["code"]): dict(row)
        for row in component_rows
    }

    for code in component_codes:
        if code not in component_map:
            errors.append(
                "Inactive or unknown component: "
                f"{code}"
            )

    source_map = {
        str(row["source_key"]): dict(row)
        for row in source_rows
    }

    for source_key in source_keys:
        source = source_map.get(
            source_key
        )

        if source is None:
            errors.append(
                "Evidence source is not registered: "
                f"{source_key}"
            )
        elif not source["active"]:
            errors.append(
                "Evidence source is inactive: "
                f"{source_key}"
            )

    for row in rows:
        listing = listing_map.get(
            (
                str(row["marketplace"]),
                str(row["listing_id"]),
            )
        )

        component = component_map.get(
            str(row["component_code"])
        )

        if (
            listing is None
            or listing["id"] is None
            or component is None
        ):
            continue

        applicable_media = (
            component[
                "applicable_media"
            ]
            or []
        )

        media_type = listing[
            "media_type"
        ]

        if (
            applicable_media
            and media_type is not None
            and media_type
                not in applicable_media
        ):
            warnings.append(
                (
                    f"{row['marketplace']}/"
                    f"{row['listing_id']} uses "
                    f"{row['component_code']} for media "
                    f"{media_type}, outside its configured "
                    "applicable-media list."
                )
            )

    return BulkObservationPreview(
        rows=tuple(rows),
        errors=tuple(
            sorted(set(errors))
        ),
        warnings=tuple(
            sorted(set(warnings))
        ),
        existing_conflicts=tuple(
            dict(row)
            for row in conflict_rows
        ),
        touched_listing_count=len(
            listing_keys
        ),
    )


def apply_bulk_observations(
    engine: Engine,
    payload: bytes | str,
    *,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    """Apply one validated worksheet atomically."""
    preview = preview_bulk_observations(
        engine,
        payload,
    )

    if not preview.ready:
        raise ValueError(
            "Bulk observation worksheet is invalid:\n"
            + "\n".join(preview.errors)
        )

    if (
        preview.existing_conflicts
        and not overwrite_existing
    ):
        raise ValueError(
            "Existing observation conflicts were found. "
            "Enable overwrite explicitly or remove those rows."
        )

    rows = list(preview.rows)

    identities = [
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
            str(row["component_code"]),
            str(row["variant_key"]),
        )
        for row in rows
    ]

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )

        values_sql, parameters = (
            _values_relation(
                identities
            )
        )

        live_conflicts = connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM (
                    VALUES {values_sql}
                ) AS requested(
                    marketplace,
                    listing_id,
                    component_code,
                    variant_key
                )
                JOIN warehouse.auction_component_observation
                    AS existing
                  ON existing.marketplace =
                        requested.marketplace
                 AND existing.listing_id =
                        requested.listing_id
                 AND existing.component_code =
                        requested.component_code
                 AND existing.variant_key =
                        requested.variant_key
                """
            ),
            parameters,
        ).scalar_one()

        if (
            live_conflicts
            and not overwrite_existing
        ):
            raise ValueError(
                "An observation conflict appeared after preview. "
                "No rows were written."
            )

        if overwrite_existing:
            connection.execute(
                text(
                    f"""
                    DELETE FROM
                        warehouse.auction_component_observation
                    WHERE (
                        marketplace,
                        listing_id,
                        component_code,
                        variant_key
                    ) IN (
                        SELECT
                            requested.marketplace,
                            requested.listing_id,
                            requested.component_code,
                            requested.variant_key
                        FROM (
                            VALUES {values_sql}
                        ) AS requested(
                            marketplace,
                            listing_id,
                            component_code,
                            variant_key
                        )
                    )
                    """
                ),
                parameters,
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
                """
            ),
            rows,
        )

    return {
        "inserted_rows": len(rows),
        "overwritten_rows": (
            len(
                preview.existing_conflicts
            )
            if overwrite_existing
            else 0
        ),
        "touched_listings":
            preview.touched_listing_count,
        "warnings": list(
            preview.warnings
        ),
    }
