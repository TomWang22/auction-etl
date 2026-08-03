"""Administration service for pressing completeness references."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine


REFERENCE_STATES = (
    "REQUIRED",
    "NOT_INCLUDED",
    "UNKNOWN",
)


def _is_missing(value: Any) -> bool:
    """Return whether a UI value should be treated as absent."""
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


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize one required text value."""
    if _is_missing(value):
        raise ValueError(
            f"{field_name} is required."
        )

    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    """Normalize one optional text value."""
    if _is_missing(value):
        return None

    return str(value).strip()


def _integer(
    value: Any,
    *,
    field_name: str,
    minimum: int | None = None,
    required: bool = False,
) -> int | None:
    """Normalize an optional integer."""
    if _is_missing(value):
        if required:
            raise ValueError(
                f"{field_name} is required."
            )

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

    return normalized


def _decimal(
    value: Any,
    *,
    field_name: str,
    default: Decimal | None = None,
) -> Decimal:
    """Normalize a decimal confidence value."""
    if _is_missing(value):
        if default is not None:
            return default

        raise ValueError(
            f"{field_name} is required."
        )

    try:
        normalized = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error

    if not Decimal("0") <= normalized <= Decimal("1"):
        raise ValueError(
            f"{field_name} must be between 0 and 1."
        )

    return normalized.quantize(
        Decimal("0.0001")
    )


def list_component_types(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return active collector component types."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    code,
                    display_name,
                    description,
                    applicable_media,
                    sort_order
                FROM system.component_type
                WHERE active
                ORDER BY
                    sort_order,
                    code
                """
            )
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_media_types(
    engine: Engine,
) -> list[str]:
    """Return media types currently present in the system."""
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                WITH available_media AS (
                    SELECT media_type
                    FROM warehouse.auction
                    WHERE media_type IS NOT NULL

                    UNION

                    SELECT unnest(applicable_media)
                    FROM system.component_type
                    WHERE active
                )
                SELECT media_type
                FROM available_media
                WHERE NULLIF(BTRIM(media_type), '') IS NOT NULL
                ORDER BY media_type
                """
            )
        ).scalars().all()

    return [
        str(value)
        for value in values
    ]


def list_generation_values(
    engine: Engine,
) -> list[str]:
    """Return known pressing-generation labels."""
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT DISTINCT generation
                FROM warehouse.pressing_identity
                WHERE NULLIF(
                    BTRIM(generation),
                    ''
                ) IS NOT NULL
                ORDER BY generation
                """
            )
        ).scalars().all()

    result = {
        "UNKNOWN",
        *(
            str(value)
            for value in values
        ),
    }

    return sorted(result)


def list_pressings(
    engine: Engine,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return searchable pressing-reference records."""
    normalized_search = _optional_text(search)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing.id,
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
                        DISTINCT expectation.component_code
                    ) AS configured_component_count
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
                WHERE (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        family.display_artist,
                        family.display_title,
                        pressing.catalog_number,
                        pressing.matrix_number,
                        pressing.pressing_variant_label
                    ) ILIKE '%' || CAST(:search AS text) || '%'
                )
                GROUP BY
                    pressing.id,
                    family.id
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

    return [
        dict(row)
        for row in rows
    ]


def create_pressing(
    engine: Engine,
    payload: Mapping[str, Any],
) -> int:
    """Create one release family and exact pressing atomically."""
    artist = _required_text(
        payload.get("display_artist"),
        "Display artist",
    )

    title = _required_text(
        payload.get("display_title"),
        "Display title",
    )

    catalog_number = _required_text(
        payload.get("catalog_number"),
        "Catalog number",
    )

    media_type = _required_text(
        payload.get("media_type"),
        "Media type",
    )

    original_release_year = _integer(
        payload.get("original_release_year"),
        field_name="Original release year",
        minimum=1800,
    )

    release_year = _integer(
        payload.get("release_year"),
        field_name="Pressing release year",
        minimum=1800,
    )

    disc_count = _integer(
        payload.get("disc_count"),
        field_name="Disc count",
        minimum=1,
    )

    generation = (
        _optional_text(
            payload.get("generation")
        )
        or "UNKNOWN"
    )

    is_first_press = bool(
        payload.get("is_first_press")
    )

    is_modern_repress = bool(
        payload.get("is_modern_repress")
    )

    if is_first_press and is_modern_repress:
        raise ValueError(
            "A pressing cannot be both first press "
            "and modern repress."
        )

    family_notes = _optional_text(
        payload.get("family_notes")
    )

    pressing_notes = _optional_text(
        payload.get("pressing_notes")
    )

    pressing_variant_key = (
        _optional_text(
            payload.get("pressing_variant_key")
        )
        or ""
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )

        family_id = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.release_family
                WHERE lower(display_artist) =
                        lower(:display_artist)
                  AND lower(display_title) =
                        lower(:display_title)
                  AND original_release_year
                        IS NOT DISTINCT FROM
                        :original_release_year
                ORDER BY id
                LIMIT 1
                FOR UPDATE
                """
            ),
            {
                "display_artist": artist,
                "display_title": title,
                "original_release_year":
                    original_release_year,
            },
        ).scalar_one_or_none()

        if family_id is None:
            family_id = connection.execute(
                text(
                    """
                    INSERT INTO warehouse.release_family (
                        display_artist,
                        display_title,
                        original_release_year,
                        notes
                    )
                    VALUES (
                        :display_artist,
                        :display_title,
                        :original_release_year,
                        :notes
                    )
                    RETURNING id
                    """
                ),
                {
                    "display_artist": artist,
                    "display_title": title,
                    "original_release_year":
                        original_release_year,
                    "notes": family_notes,
                },
            ).scalar_one()

        duplicate = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.pressing_identity
                WHERE release_family_id =
                        :release_family_id
                  AND upper(
                        regexp_replace(
                            catalog_number,
                            '[^A-Z0-9]',
                            '',
                            'g'
                        )
                    ) =
                    upper(
                        regexp_replace(
                            :catalog_number,
                            '[^A-Z0-9]',
                            '',
                            'g'
                        )
                    )
                  AND media_type = :media_type
                  AND pressing_variant_key =
                        :pressing_variant_key
                ORDER BY id
                LIMIT 1
                """
            ),
            {
                "release_family_id": family_id,
                "catalog_number": catalog_number,
                "media_type": media_type,
                "pressing_variant_key":
                    pressing_variant_key,
            },
        ).scalar_one_or_none()

        if duplicate is not None:
            raise ValueError(
                "An equivalent pressing already exists "
                f"as pressing #{duplicate}."
            )

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
                    notes
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
                    :notes
                )
                RETURNING id
                """
            ),
            {
                "release_family_id": family_id,
                "catalog_number": catalog_number,
                "matrix_number": _optional_text(
                    payload.get("matrix_number")
                ),
                "label_name": _optional_text(
                    payload.get("label_name")
                ),
                "region": _optional_text(
                    payload.get("region")
                ),
                "country": _optional_text(
                    payload.get("country")
                ),
                "media_type": media_type,
                "format_detail": _optional_text(
                    payload.get("format_detail")
                ),
                "disc_count": disc_count,
                "release_year": release_year,
                "generation": generation,
                "pressing_variant_key":
                    pressing_variant_key,
                "pressing_variant_label":
                    _optional_text(
                        payload.get(
                            "pressing_variant_label"
                        )
                    ),
                "is_first_press": is_first_press,
                "is_modern_repress":
                    is_modern_repress,
                "parent_first_press_id":
                    _integer(
                        payload.get(
                            "parent_first_press_id"
                        ),
                        field_name=(
                            "Parent first-press ID"
                        ),
                        minimum=1,
                    ),
                "notes": pressing_notes,
            },
        ).scalar_one()

    return int(pressing_id)


def normalize_reference_rows(
    rows: Iterable[Mapping[str, Any]],
    active_component_codes: Sequence[str],
) -> list[dict[str, Any]]:
    """Validate and normalize a full pressing reference."""
    active_codes = {
        str(code)
        for code in active_component_codes
    }

    normalized_rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    configured_codes: set[str] = set()

    for position, row in enumerate(
        rows,
        start=1,
    ):
        component_code = _required_text(
            row.get("component_code"),
            f"Row {position} component code",
        ).upper()

        if component_code not in active_codes:
            raise ValueError(
                f"Row {position} uses inactive or unknown "
                f"component {component_code}."
            )

        state = _required_text(
            row.get("expectation_state"),
            f"Row {position} expectation state",
        ).upper()

        if state not in REFERENCE_STATES:
            raise ValueError(
                f"Row {position} has unsupported state "
                f"{state}."
            )

        variant_key = (
            _optional_text(
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
                "Duplicate component/variant reference: "
                f"{component_code}/{variant_key or '(default)'}."
            )

        identities.add(identity)
        configured_codes.add(component_code)

        quantity = _integer(
            row.get("expected_quantity"),
            field_name=(
                f"Row {position} expected quantity"
            ),
            minimum=0,
        )

        if state == "REQUIRED":
            quantity = quantity or 1

            if quantity < 1:
                raise ValueError(
                    f"Row {position} REQUIRED quantity "
                    "must be at least 1."
                )
        elif state == "NOT_INCLUDED":
            quantity = 0
        else:
            quantity = quantity or 1

        evidence_source = _optional_text(
            row.get("evidence_source")
        )

        if (
            state != "UNKNOWN"
            and evidence_source is None
        ):
            raise ValueError(
                f"Row {position} requires an evidence source."
            )

        normalized_rows.append(
            {
                "component_code": component_code,
                "variant_key": variant_key,
                "variant_label": _optional_text(
                    row.get("variant_label")
                ),
                "expectation_state": state,
                "expected_quantity": quantity,
                "evidence_source":
                    evidence_source,
                "confidence": _decimal(
                    row.get("confidence"),
                    field_name=(
                        f"Row {position} confidence"
                    ),
                    default=Decimal("0.9000"),
                ),
                "notes": _optional_text(
                    row.get("notes")
                ),
            }
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
        row["expectation_state"] == "REQUIRED"
        for row in normalized_rows
    ):
        raise ValueError(
            "At least one component must be REQUIRED."
        )

    return normalized_rows


def load_reference_rows(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return editable component-reference rows."""
    with engine.connect() as connection:
        components = connection.execute(
            text(
                """
                SELECT
                    code,
                    display_name,
                    description,
                    applicable_media,
                    sort_order
                FROM system.component_type
                WHERE active
                ORDER BY
                    sort_order,
                    code
                """
            )
        ).mappings().all()

        expectations = connection.execute(
            text(
                """
                SELECT
                    id,
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
                "pressing_id": pressing_id,
            },
        ).mappings().all()

    components_by_code = {
        str(row["code"]): dict(row)
        for row in components
    }

    expectations_by_code: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for expectation in expectations:
        expectations_by_code.setdefault(
            str(
                expectation["component_code"]
            ),
            [],
        ).append(
            dict(expectation)
        )

    result: list[dict[str, Any]] = []

    for component in components:
        code = str(component["code"])
        existing_rows = expectations_by_code.get(
            code,
            [],
        )

        if not existing_rows:
            existing_rows = [
                {
                    "id": None,
                    "component_code": code,
                    "variant_key": "",
                    "variant_label": None,
                    "expectation_state": "UNKNOWN",
                    "expected_quantity": 1,
                    "evidence_source": None,
                    "confidence": Decimal("0.9000"),
                    "notes": None,
                }
            ]

        for expectation in existing_rows:
            metadata = components_by_code[code]

            result.append(
                {
                    "component_code": code,
                    "display_name":
                        metadata["display_name"],
                    "applicable_media": ", ".join(
                        metadata[
                            "applicable_media"
                        ]
                        or []
                    ),
                    "variant_key":
                        expectation["variant_key"]
                        or "",
                    "variant_label":
                        expectation["variant_label"],
                    "expectation_state":
                        expectation[
                            "expectation_state"
                        ],
                    "expected_quantity":
                        expectation[
                            "expected_quantity"
                        ],
                    "evidence_source":
                        expectation[
                            "evidence_source"
                        ],
                    "confidence":
                        expectation["confidence"],
                    "notes":
                        expectation["notes"],
                    "sort_order":
                        metadata["sort_order"],
                }
            )

    return sorted(
        result,
        key=lambda row: (
            int(row["sort_order"]),
            str(row["component_code"]),
            str(row["variant_key"]),
        ),
    )


def save_reference_rows(
    engine: Engine,
    pressing_id: int,
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replace one pressing's complete component reference."""
    component_rows = list_component_types(
        engine
    )

    active_codes = [
        str(row["code"])
        for row in component_rows
    ]

    normalized_rows = normalize_reference_rows(
        rows,
        active_codes,
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
                    "pressing_id": pressing_id,
                    **row,
                }
                for row in normalized_rows
            ],
        )

    return reference_summary(
        engine,
        pressing_id,
    )


def reference_summary(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Return reference coverage and pressing metadata."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                WITH active_components AS (
                    SELECT COUNT(*) AS rows
                    FROM system.component_type
                    WHERE active
                ),
                expectation_summary AS (
                    SELECT
                        COUNT(
                            DISTINCT component_code
                        ) AS configured_components,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'REQUIRED'
                        ) AS required_rows,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'NOT_INCLUDED'
                        ) AS not_included_rows,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'UNKNOWN'
                        ) AS unknown_rows
                    FROM
                        warehouse.pressing_component_expectation
                    WHERE pressing_id = :pressing_id
                )
                SELECT
                    pressing.id AS pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.media_type,
                    active.rows AS active_components,
                    summary.configured_components,
                    summary.required_rows,
                    summary.not_included_rows,
                    summary.unknown_rows,
                    (
                        summary.configured_components =
                            active.rows
                        AND summary.required_rows > 0
                        AND summary.unknown_rows = 0
                    ) AS verified_reference
                FROM warehouse.pressing_identity
                    AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                CROSS JOIN active_components AS active
                CROSS JOIN expectation_summary AS summary
                WHERE pressing.id = :pressing_id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Pressing #{pressing_id} does not exist."
        )

    return dict(row)


def assigned_listing_preview(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Return assigned listings and derived completeness."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    auction.marketplace,
                    auction.listing_id,
                    auction.title,
                    auction.seller,
                    auction.currency,
                    auction.final_price,
                    auction.gross_price_usd,
                    auction.landed_price_usd,
                    auction.ended_at,
                    assignment.match_basis,
                    assignment.match_confidence,
                    completeness.required_component_count,
                    completeness.present_required_component_count,
                    completeness.missing_components,
                    completeness.unverified_components,
                    completeness.unexpected_components,
                    completeness.completeness_ratio,
                    completeness.completeness_status,
                    completeness.complete
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
                WHERE assignment.pressing_id =
                        :pressing_id
                ORDER BY
                    auction.ended_at DESC NULLS LAST,
                    auction.marketplace,
                    auction.listing_id
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
