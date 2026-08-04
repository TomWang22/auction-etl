"""Canonical media-aware exact-pressing completeness references."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import MetaData, Table, and_, select, text
from sqlalchemy.engine import Connection, Engine


REFERENCE_ACTIONS = (
    "NO_CHANGE",
    "UPSERT",
    "DELETE",
)

REFERENCE_STATES = (
    "UNKNOWN",
    "REQUIRED",
    "NOT_INCLUDED",
)

ASSERTED_STATES = frozenset(
    {
        "REQUIRED",
        "NOT_INCLUDED",
    }
)

MEDIA_GROUPS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "LP": (
        (
            "Identity and packaging",
            (
                "OBI",
                "BOX",
                "SHRINK_WRAP",
                "STICKER",
            ),
        ),
        (
            "Printed matter",
            (
                "INSERT",
                "LYRIC_SHEET",
                "POSTER",
                "PINUP",
            ),
        ),
        (
            "Sleeves and additional media",
            (
                "INNER_SLEEVE",
                "BONUS_MEDIA",
            ),
        ),
    ),
    "CASSETTE": (
        (
            "Primary packaging",
            (
                "J_CARD",
                "BOX",
                "SHRINK_WRAP",
                "STICKER",
            ),
        ),
        (
            "Printed matter",
            (
                "BOOKLET",
                "INSERT",
                "LYRIC_SHEET",
            ),
        ),
    ),
    "CD": (
        (
            "Identity and packaging",
            (
                "OBI",
                "SHRINK_WRAP",
                "STICKER",
            ),
        ),
        (
            "Printed matter",
            (
                "BOOKLET",
                "INSERT",
                "LYRIC_SHEET",
            ),
        ),
        (
            "Additional media",
            (
                "BONUS_MEDIA",
            ),
        ),
    ),
    "CD_BOX_SET": (
        (
            "Box-set packaging",
            (
                "BOX",
                "OBI",
            ),
        ),
        (
            "Printed matter",
            (
                "BOOKLET",
                "POSTER",
            ),
        ),
        (
            "Additional media",
            (
                "BONUS_MEDIA",
            ),
        ),
    ),
    "EP_7_INCH": (
        (
            "Identity and sleeves",
            (
                "OBI",
                "INNER_SLEEVE",
            ),
        ),
        (
            "Printed matter",
            (
                "INSERT",
                "LYRIC_SHEET",
                "PINUP",
            ),
        ),
    ),
    "SINGLE_12_INCH": (
        (
            "Identity and sleeves",
            (
                "OBI",
                "INNER_SLEEVE",
            ),
        ),
    ),
    "LD": (
        (
            "Packaging",
            (
                "BOX",
                "SHRINK_WRAP",
                "STICKER",
            ),
        ),
        (
            "Printed matter",
            (
                "BOOKLET",
                "INSERT",
                "POSTER",
            ),
        ),
    ),
    "DVD": (
        (
            "Packaging",
            (
                "SHRINK_WRAP",
            ),
        ),
        (
            "Printed matter and media",
            (
                "BOOKLET",
                "BONUS_MEDIA",
            ),
        ),
    ),
}


@dataclass(frozen=True)
class ReferencePreview:
    """Deterministic preview for one exact-pressing master change."""

    pressing_id: int
    catalog_number: str
    media_type: str
    applicable_component_count: int
    digest: str
    confirmation_token: str
    status: str
    ready: bool
    operations: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return asdict(
            self
        )


def _is_missing(value: object) -> bool:
    """Return whether a worksheet value is blank."""
    if value is None:
        return True

    if isinstance(
        value,
        float,
    ) and math.isnan(
        value
    ):
        return True

    normalized = str(
        value
    ).strip()

    return normalized.casefold() in {
        "",
        "nan",
        "nat",
        "none",
        "<na>",
    }


def _optional_text(value: object) -> str | None:
    """Normalize optional text."""
    if _is_missing(
        value
    ):
        return None

    normalized = str(
        value
    ).strip()

    return normalized or None


def _required_text(
    value: object,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = _optional_text(
        value
    )

    if normalized is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def _upper_text(value: object) -> str:
    """Normalize one identifier-like value."""
    return (
        _optional_text(
            value
        )
        or ""
    ).upper()


def _optional_integer(
    value: object,
) -> int | None:
    """Normalize an optional integer."""
    if _is_missing(
        value
    ):
        return None

    try:
        decimal_value = Decimal(
            str(
                value
            )
        )
    except InvalidOperation as error:
        raise ValueError(
            f"Expected an integer; received {value!r}."
        ) from error

    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(
            f"Expected an integer; received {value!r}."
        )

    return int(
        decimal_value
    )


def _optional_decimal(
    value: object,
) -> Decimal | None:
    """Normalize an optional decimal."""
    if _is_missing(
        value
    ):
        return None

    try:
        return Decimal(
            str(
                value
            )
        )
    except InvalidOperation as error:
        raise ValueError(
            f"Expected a decimal; received {value!r}."
        ) from error


def _json_safe(value: object) -> object:
    """Convert database values into deterministic JSON values."""
    if isinstance(
        value,
        Decimal,
    ):
        return format(
            value,
            "f",
        )

    if isinstance(
        value,
        (
            datetime,
            date,
        ),
    ):
        return value.isoformat()

    if isinstance(
        value,
        Mapping,
    ):
        return {
            str(key):
                _json_safe(
                    nested_value
                )
            for key, nested_value in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            _json_safe(
                nested_value
            )
            for nested_value in value
        ]

    return value


def _expectation_table(
    connection: Connection,
) -> Table:
    """Reflect the current expectation table contract."""
    return Table(
        "pressing_component_expectation",
        MetaData(),
        schema="warehouse",
        autoload_with=connection,
    )


def _pressing_identity(
    connection: Connection,
    pressing_id: int,
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    """Load one exact pressing."""
    suffix = (
        " FOR UPDATE"
        if for_update
        else ""
    )

    row = connection.execute(
        text(
            """
            SELECT
                pressing.id AS pressing_id,
                pressing.catalog_number,
                pressing.matrix_number,
                pressing.label_name,
                pressing.country,
                pressing.region,
                pressing.media_type,
                pressing.disc_count,
                pressing.generation,
                pressing.pressing_variant_key,
                pressing.pressing_variant_label,
                family.display_artist,
                family.display_title,
                family.original_release_year
            FROM warehouse.pressing_identity AS pressing
            JOIN warehouse.release_family AS family
              ON family.id =
                    pressing.release_family_id
            WHERE pressing.id = :pressing_id
            """
            + suffix
        ),
        {
            "pressing_id":
                int(
                    pressing_id
                ),
        },
    ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Exact pressing #{pressing_id} does not exist."
        )

    return dict(
        row
    )


def list_pressings(
    engine: Engine,
) -> list[dict[str, Any]]:
    """List every exact pressing available to the master page."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing.id AS pressing_id,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.matrix_number,
                    pressing.label_name,
                    pressing.country,
                    pressing.region,
                    pressing.media_type,
                    pressing.disc_count,
                    pressing.generation,
                    pressing.pressing_variant_key,
                    pressing.pressing_variant_label,
                    COUNT(
                        DISTINCT assignment.id
                    ) AS assigned_listing_count,
                    COUNT(
                        DISTINCT expectation.id
                    ) AS reference_row_count
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
                GROUP BY
                    pressing.id,
                    family.id
                ORDER BY
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.id
                """
            )
        ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]


def list_evidence_sources(
    engine: Engine,
) -> list[dict[str, Any]]:
    """List active reusable evidence sources."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    source_key,
                    display_name,
                    source_type,
                    base_url,
                    default_confidence
                FROM system.evidence_source_registry
                WHERE active
                ORDER BY
                    display_name,
                    source_key
                """
            )
        ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]


def _profile_components(
    connection: Connection,
    pressing_id: int,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Load applicable and non-applicable component definitions."""
    pressing = _pressing_identity(
        connection,
        pressing_id,
    )

    all_rows = connection.execute(
        text(
            """
            SELECT
                code,
                display_name,
                applicable_media,
                active
            FROM system.component_type
            WHERE active
            ORDER BY code
            """
        )
    ).mappings().all()

    media_type = str(
        pressing["media_type"]
    )

    applicable: list[
        dict[str, Any]
    ] = []

    non_applicable: list[
        dict[str, Any]
    ] = []

    for row in all_rows:
        payload = dict(
            row
        )

        media_values = {
            str(
                value
            )
            for value in (
                row["applicable_media"]
                or []
            )
        }

        payload[
            "applicable"
        ] = (
            media_type
            in media_values
        )

        payload[
            "group"
        ] = group_for_component(
            media_type,
            str(
                row["code"]
            ),
        )

        if payload[
            "applicable"
        ]:
            applicable.append(
                payload
            )
        else:
            non_applicable.append(
                payload
            )

    return (
        pressing,
        applicable,
        non_applicable,
    )


def load_media_profile(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Return the selected exact pressing's media profile."""
    with engine.connect() as connection:
        (
            pressing,
            applicable,
            non_applicable,
        ) = _profile_components(
            connection,
            pressing_id,
        )

    return {
        "pressing":
            pressing,
        "applicable_components":
            applicable,
        "non_applicable_components":
            non_applicable,
        "applicable_component_count":
            len(
                applicable
            ),
    }


def group_for_component(
    media_type: str,
    component_code: str,
) -> str:
    """Return a professional media-specific editor group."""
    normalized_media = str(
        media_type
    ).upper()

    normalized_code = str(
        component_code
    ).upper()

    for (
        group_name,
        component_codes,
    ) in MEDIA_GROUPS.get(
        normalized_media,
        (),
    ):
        if normalized_code in component_codes:
            return group_name

    return "Applicable components"


def _current_expectations(
    connection: Connection,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Load persisted exact-pressing reference rows."""
    table = _expectation_table(
        connection
    )

    rows = connection.execute(
        select(
            table
        ).where(
            table.c.pressing_id
            == int(
                pressing_id
            )
        )
    ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]


def _editor_row_from_current(
    current: Mapping[str, Any],
    *,
    display_name: str,
    applicable: bool,
    group: str,
) -> dict[str, Any]:
    """Convert one persisted row into an editable row."""
    return {
        "action":
            "NO_CHANGE",
        "id":
            current.get(
                "id"
            ),
        "persisted":
            True,
        "applicable":
            applicable,
        "group":
            group,
        "component_code":
            current.get(
                "component_code"
            ),
        "display_name":
            display_name,
        "variant_key":
            current.get(
                "variant_key"
            )
            or "",
        "variant_label":
            current.get(
                "variant_label"
            ),
        "expectation_state":
            current.get(
                "expectation_state"
            )
            or "UNKNOWN",
        "expected_quantity":
            _semantic_expected_quantity(
                current
            ),
        "evidence_source":
            current.get(
                "evidence_source"
            ),
        "confidence":
            current.get(
                "confidence"
            ),
        "notes":
            current.get(
                "notes"
            ),
    }


def load_reference_editor_rows(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """Build a media-aware worksheet for one exact pressing."""
    with engine.connect() as connection:
        (
            pressing,
            applicable,
            _,
        ) = _profile_components(
            connection,
            pressing_id,
        )

        current_rows = _current_expectations(
            connection,
            pressing_id,
        )

    media_type = str(
        pressing["media_type"]
    )

    component_map = {
        str(
            row["code"]
        ):
            dict(
                row
            )
        for row in applicable
    }

    grouped_current: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    out_of_profile: list[
        dict[str, Any]
    ] = []

    for row in current_rows:
        component_code = str(
            row.get(
                "component_code"
            )
            or ""
        )

        if component_code in component_map:
            grouped_current.setdefault(
                component_code,
                [],
            ).append(
                row
            )
        else:
            out_of_profile.append(
                row
            )

    editor_rows: list[
        dict[str, Any]
    ] = []

    for component in applicable:
        component_code = str(
            component["code"]
        )

        persisted_rows = grouped_current.get(
            component_code,
            [],
        )

        if persisted_rows:
            for persisted_row in persisted_rows:
                editor_rows.append(
                    _editor_row_from_current(
                        persisted_row,
                        display_name=str(
                            component[
                                "display_name"
                            ]
                        ),
                        applicable=True,
                        group=group_for_component(
                            media_type,
                            component_code,
                        ),
                    )
                )
        else:
            editor_rows.append(
                {
                    "action":
                        "NO_CHANGE",
                    "id":
                        None,
                    "persisted":
                        False,
                    "applicable":
                        True,
                    "group":
                        group_for_component(
                            media_type,
                            component_code,
                        ),
                    "component_code":
                        component_code,
                    "display_name":
                        component[
                            "display_name"
                        ],
                    "variant_key":
                        "",
                    "variant_label":
                        None,
                    "expectation_state":
                        "UNKNOWN",
                    "expected_quantity":
                        None,
                    "evidence_source":
                        None,
                    "confidence":
                        None,
                    "notes":
                        None,
                }
            )

    for persisted_row in out_of_profile:
        component_code = str(
            persisted_row.get(
                "component_code"
            )
            or ""
        )

        editor_rows.append(
            _editor_row_from_current(
                persisted_row,
                display_name=component_code,
                applicable=False,
                group=(
                    "Out-of-profile persisted rows"
                ),
            )
        )

    group_order = {
        group_name:
            index
        for index, (
            group_name,
            _,
        ) in enumerate(
            MEDIA_GROUPS.get(
                media_type,
                (),
            )
        )
    }

    editor_rows.sort(
        key=lambda row: (
            group_order.get(
                str(
                    row["group"]
                ),
                999,
            ),
            str(
                row["component_code"]
            ),
            str(
                row["variant_key"]
                or ""
            ),
        )
    )

    return editor_rows


def list_assigned_listings(
    engine: Engine,
    pressing_id: int,
) -> list[dict[str, Any]]:
    """List auction copies assigned to one exact pressing."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    assignment.marketplace,
                    assignment.listing_id,
                    auction.title,
                    COUNT(
                        DISTINCT observation.id
                    ) AS observation_count
                FROM warehouse.auction_pressing_assignment
                    AS assignment
                JOIN warehouse.auction
                  ON auction.marketplace =
                        assignment.marketplace
                 AND auction.listing_id =
                        assignment.listing_id
                LEFT JOIN warehouse.auction_component_observation
                    AS observation
                  ON observation.marketplace =
                        assignment.marketplace
                 AND observation.listing_id =
                        assignment.listing_id
                WHERE assignment.pressing_id =
                    :pressing_id
                GROUP BY
                    assignment.marketplace,
                    assignment.listing_id,
                    auction.title
                ORDER BY
                    assignment.marketplace,
                    assignment.listing_id
                """
            ),
            {
                "pressing_id":
                    int(
                        pressing_id
                    ),
            },
        ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]


def list_reference_audit(
    engine: Engine,
    pressing_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List immutable audit events for one master reference."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    action,
                    actor,
                    reason,
                    entity_key,
                    before_state,
                    after_state,
                    batch_id,
                    created_at
                FROM system.reference_audit_event
                WHERE entity_type =
                    'PRESSING_COMPONENT_EXPECTATION'
                  AND entity_key ->> 'pressing_id' =
                        CAST(
                            :pressing_id
                            AS text
                        )
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "pressing_id":
                    int(
                        pressing_id
                    ),
                "limit":
                    int(
                        limit
                    ),
            },
        ).mappings().all()

    return [
        {
            key:
                _json_safe(
                    value
                )
            for key, value in dict(
                row
            ).items()
        }
        for row in rows
    ]


def _semantic_expected_quantity(
    row: Mapping[str, Any],
) -> int | None:
    """Return quantity only when it has reference meaning."""
    state = _upper_text(
        row.get(
            "expectation_state"
        )
    )

    if state != "REQUIRED":
        return None

    return _optional_integer(
        row.get(
            "expected_quantity"
        )
    )


def _current_projection(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the semantic portion of one persisted row."""
    confidence = _optional_decimal(
        row.get(
            "confidence"
        )
    )

    return {
        "id":
            row.get(
                "id"
            ),
        "component_code":
            _upper_text(
                row.get(
                    "component_code"
                )
            ),
        "variant_key":
            _optional_text(
                row.get(
                    "variant_key"
                )
            )
            or "",
        "variant_label":
            _optional_text(
                row.get(
                    "variant_label"
                )
            ),
        "expectation_state":
            _upper_text(
                row.get(
                    "expectation_state"
                )
            ),
        "expected_quantity":
            _semantic_expected_quantity(
                row
            ),
        "evidence_source":
            _optional_text(
                row.get(
                    "evidence_source"
                )
            ),
        "confidence":
            (
                format(
                    confidence,
                    "f",
                )
                if confidence is not None
                else None
            ),
        "notes":
            _optional_text(
                row.get(
                    "notes"
                )
            ),
    }


def _normalized_after_row(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one proposed reference row."""
    state = _upper_text(
        row.get(
            "expectation_state"
        )
    )

    quantity = _optional_integer(
        row.get(
            "expected_quantity"
        )
    )

    if state != "REQUIRED":
        quantity = None

    confidence = _optional_decimal(
        row.get(
            "confidence"
        )
    )

    return {
        "component_code":
            _upper_text(
                row.get(
                    "component_code"
                )
            ),
        "variant_key":
            _optional_text(
                row.get(
                    "variant_key"
                )
            )
            or "",
        "variant_label":
            _optional_text(
                row.get(
                    "variant_label"
                )
            ),
        "expectation_state":
            state,
        "expected_quantity":
            quantity,
        "evidence_source":
            _optional_text(
                row.get(
                    "evidence_source"
                )
            ),
        "confidence":
            (
                format(
                    confidence,
                    "f",
                )
                if confidence is not None
                else None
            ),
        "notes":
            _optional_text(
                row.get(
                    "notes"
                )
            ),
    }


def _storage_expected_quantity(
    after: Mapping[str, Any],
) -> int:
    """Return a value compatible with the legacy non-null schema."""
    state = _upper_text(
        after.get(
            "expectation_state"
        )
    )

    if state == "REQUIRED":
        quantity = _optional_integer(
            after.get(
                "expected_quantity"
            )
        )

        if (
            quantity is None
            or quantity < 1
        ):
            raise ValueError(
                "REQUIRED references need a positive quantity."
            )

        return quantity

    # The existing table requires a positive non-null value.
    # This storage sentinel is ignored by the editor, previews,
    # completeness arithmetic, and all non-REQUIRED semantics.
    return 1


def _insert_payload(
    pressing_id: int,
    after: Mapping[str, Any],
) -> dict[str, Any]:
    """Return database values for one UPSERT."""
    confidence_value = after.get(
        "confidence"
    )

    return {
        "pressing_id":
            int(
                pressing_id
            ),
        "component_code":
            after[
                "component_code"
            ],
        "variant_key":
            after[
                "variant_key"
            ],
        "variant_label":
            after.get(
                "variant_label"
            ),
        "expectation_state":
            after[
                "expectation_state"
            ],
        "expected_quantity":
            _storage_expected_quantity(
                after
            ),
        "evidence_source":
            after.get(
                "evidence_source"
            ),
        "confidence":
            (
                Decimal(
                    str(
                        confidence_value
                    )
                )
                if confidence_value is not None
                else None
            ),
        "notes":
            after.get(
                "notes"
            ),
    }


def _required_insert_columns(
    table: Table,
    payload: Mapping[str, Any],
) -> list[str]:
    """Return unsupported required columns for a new row."""
    missing: list[
        str
    ] = []

    for column in table.columns:
        if column.name in payload:
            continue

        if column.primary_key:
            continue

        if column.nullable:
            continue

        if column.default is not None:
            continue

        if column.server_default is not None:
            continue

        if column.autoincrement is True:
            continue

        missing.append(
            column.name
        )

    return missing


def _preview_with_connection(
    connection: Connection,
    pressing_id: int,
    rows: Sequence[Mapping[str, Any]],
) -> ReferencePreview:
    """Build a preview using one database snapshot."""
    (
        pressing,
        applicable_components,
        _,
    ) = _profile_components(
        connection,
        pressing_id,
    )

    applicable_codes = {
        str(
            row["code"]
        )
        for row in applicable_components
    }

    source_rows = connection.execute(
        text(
            """
            SELECT
                source_key,
                active
            FROM system.evidence_source_registry
            """
        )
    ).mappings().all()

    active_sources = {
        str(
            row["source_key"]
        )
        for row in source_rows
        if bool(
            row["active"]
        )
    }

    current_rows = _current_expectations(
        connection,
        pressing_id,
    )

    current_map = {
        (
            _upper_text(
                row.get(
                    "component_code"
                )
            ),
            _optional_text(
                row.get(
                    "variant_key"
                )
            )
            or "",
        ):
            dict(
                row
            )
        for row in current_rows
    }

    blockers: list[
        str
    ] = []

    warnings: list[
        str
    ] = []

    operations: list[
        dict[str, Any]
    ] = []

    seen_identities: set[
        tuple[str, str]
    ] = set()

    expectation_table = _expectation_table(
        connection
    )

    for row_number, raw_row in enumerate(
        rows,
        start=1,
    ):
        action = _upper_text(
            raw_row.get(
                "action"
            )
        ) or "NO_CHANGE"

        if action not in REFERENCE_ACTIONS:
            blockers.append(
                f"Row {row_number}: invalid action {action!r}."
            )
            continue

        if action == "NO_CHANGE":
            continue

        component_code = _upper_text(
            raw_row.get(
                "component_code"
            )
        )

        variant_key = (
            _optional_text(
                raw_row.get(
                    "variant_key"
                )
            )
            or ""
        )

        if not component_code:
            blockers.append(
                f"Row {row_number}: component_code is required."
            )
            continue

        identity = (
            component_code,
            variant_key,
        )

        if identity in seen_identities:
            blockers.append(
                "Duplicate reviewed identity: "
                f"{component_code}/{variant_key or '<default>'}."
            )
            continue

        seen_identities.add(
            identity
        )

        current = current_map.get(
            identity
        )

        if action == "DELETE":
            if current is None:
                blockers.append(
                    f"Row {row_number}: DELETE requires a persisted row."
                )
                continue

            operations.append(
                {
                    "operation":
                        "DELETE",
                    "identity": {
                        "component_code":
                            component_code,
                        "variant_key":
                            variant_key,
                    },
                    "before":
                        _current_projection(
                            current
                        ),
                    "after":
                        None,
                }
            )

            continue

        if component_code not in applicable_codes:
            blockers.append(
                f"Row {row_number}: {component_code} is not applicable "
                f"to media type {pressing['media_type']}."
            )
            continue

        try:
            after = _normalized_after_row(
                raw_row
            )
        except ValueError as error:
            blockers.append(
                f"Row {row_number}: {error}"
            )
            continue

        state = str(
            after[
                "expectation_state"
            ]
        )

        if state not in REFERENCE_STATES:
            blockers.append(
                f"Row {row_number}: invalid expectation state {state!r}."
            )
            continue

        quantity = after.get(
            "expected_quantity"
        )

        if (
            state == "REQUIRED"
            and (
                quantity is None
                or int(
                    quantity
                ) < 1
            )
        ):
            blockers.append(
                f"Row {row_number}: REQUIRED needs a positive quantity."
            )

        evidence_source = after.get(
            "evidence_source"
        )

        confidence = after.get(
            "confidence"
        )

        if state in ASSERTED_STATES:
            if not evidence_source:
                blockers.append(
                    f"Row {row_number}: {state} requires an evidence source."
                )
            elif evidence_source not in active_sources:
                blockers.append(
                    f"Row {row_number}: evidence source "
                    f"{evidence_source!r} is not active."
                )

            if confidence is None:
                blockers.append(
                    f"Row {row_number}: {state} requires confidence."
                )
            else:
                confidence_value = Decimal(
                    str(
                        confidence
                    )
                )

                if not (
                    Decimal("0")
                    <= confidence_value
                    <= Decimal("1")
                ):
                    blockers.append(
                        f"Row {row_number}: confidence must be between 0 and 1."
                    )

        if (
            state == "UNKNOWN"
            and evidence_source
            and evidence_source not in active_sources
        ):
            blockers.append(
                f"Row {row_number}: evidence source "
                f"{evidence_source!r} is not active."
            )

        before = (
            _current_projection(
                current
            )
            if current is not None
            else None
        )

        comparable_before = (
            {
                key:
                    value
                for key, value in before.items()
                if key != "id"
            }
            if before is not None
            else None
        )

        if comparable_before == after:
            warnings.append(
                f"Row {row_number}: reviewed UPSERT produces no change."
            )
            continue

        operation_name = (
            "UPDATE"
            if current is not None
            else "INSERT"
        )

        if operation_name == "INSERT":
            payload = _insert_payload(
                pressing_id,
                after,
            )

            missing_columns = _required_insert_columns(
                expectation_table,
                payload,
            )

            if missing_columns:
                blockers.append(
                    "The live expectation table requires unsupported "
                    "insert fields: "
                    + ", ".join(
                        missing_columns
                    )
                )
                continue

        operations.append(
            {
                "operation":
                    operation_name,
                "identity": {
                    "component_code":
                        component_code,
                    "variant_key":
                        variant_key,
                },
                "before":
                    before,
                "after":
                    after,
            }
        )

    current_fingerprint = [
        _current_projection(
            row
        )
        for row in current_rows
    ]

    current_fingerprint.sort(
        key=lambda row: (
            str(
                row[
                    "component_code"
                ]
            ),
            str(
                row[
                    "variant_key"
                ]
            ),
        )
    )

    digest_payload = {
        "pressing_id":
            int(
                pressing_id
            ),
        "media_type":
            pressing[
                "media_type"
            ],
        "current":
            current_fingerprint,
        "operations":
            operations,
    }

    digest = sha256(
        json.dumps(
            _json_safe(
                digest_payload
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()

    ready = (
        not blockers
        and bool(
            operations
        )
    )

    if blockers:
        status = "BLOCKED"
    elif operations:
        status = "READY"
    else:
        status = "NO_CHANGES"

    confirmation_token = (
        f"REFERENCE:{pressing_id}:"
        f"{digest[:12].upper()}"
    )

    return ReferencePreview(
        pressing_id=int(
            pressing_id
        ),
        catalog_number=str(
            pressing.get(
                "catalog_number"
            )
            or ""
        ),
        media_type=str(
            pressing[
                "media_type"
            ]
        ),
        applicable_component_count=len(
            applicable_components
        ),
        digest=digest,
        confirmation_token=confirmation_token,
        status=status,
        ready=ready,
        operations=tuple(
            operations
        ),
        blockers=tuple(
            blockers
        ),
        warnings=tuple(
            warnings
        ),
    )


def preview_reference_changes(
    engine: Engine,
    pressing_id: int,
    rows: Sequence[Mapping[str, Any]],
) -> ReferencePreview:
    """Preview exact master-reference mutations without writing."""
    with engine.connect() as connection:
        return _preview_with_connection(
            connection,
            pressing_id,
            rows,
        )


def apply_reference_changes(
    engine: Engine,
    pressing_id: int,
    rows: Sequence[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
    confirmation_token: str,
    confirmed_catalog: str,
    scope_confirmed: bool,
) -> dict[str, Any]:
    """Revalidate and atomically apply one reviewed master change."""
    normalized_actor = _required_text(
        actor,
        "Reviewer",
    )

    normalized_reason = _required_text(
        reason,
        "Review reason",
    )

    normalized_token = _required_text(
        confirmation_token,
        "Confirmation token",
    )

    normalized_catalog = _required_text(
        confirmed_catalog,
        "Confirmed catalog",
    )

    if not scope_confirmed:
        raise ValueError(
            "Exact-pressing scope must be confirmed."
        )

    applied_operations: list[
        dict[str, Any]
    ] = []

    connection = engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    )

    try:
        with connection.begin():
            pressing = _pressing_identity(
                connection,
                pressing_id,
                for_update=True,
            )

            catalog_number = str(
                pressing.get(
                    "catalog_number"
                )
                or ""
            )

            if (
                normalized_catalog.casefold()
                != catalog_number.casefold()
            ):
                raise ValueError(
                    "Confirmed catalog does not match the selected "
                    "exact pressing."
                )

            preview = _preview_with_connection(
                connection,
                pressing_id,
                rows,
            )

            if not preview.ready:
                raise ValueError(
                    "Reference preview is not ready to apply: "
                    + "; ".join(
                        preview.blockers
                        or (
                            "No mutations were requested.",
                        )
                    )
                )

            if (
                normalized_token
                != preview.confirmation_token
            ):
                raise ValueError(
                    "Confirmation token is stale or incorrect. "
                    "Run Preview again."
                )

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'auction_etl.actor',
                        :actor,
                        true
                    )
                    """
                ),
                {
                    "actor":
                        normalized_actor,
                },
            )

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'auction_etl.reason',
                        :reason,
                        true
                    )
                    """
                ),
                {
                    "reason":
                        normalized_reason,
                },
            )

            table = _expectation_table(
                connection
            )

            for operation in preview.operations:
                identity = operation[
                    "identity"
                ]

                where_clause = and_(
                    table.c.pressing_id
                    == int(
                        pressing_id
                    ),
                    table.c.component_code
                    == identity[
                        "component_code"
                    ],
                    table.c.variant_key
                    == identity[
                        "variant_key"
                    ],
                )

                operation_name = str(
                    operation[
                        "operation"
                    ]
                )

                if operation_name == "DELETE":
                    result = connection.execute(
                        table.delete().where(
                            where_clause
                        )
                    )

                    if result.rowcount != 1:
                        raise ValueError(
                            "A reviewed DELETE no longer matches exactly "
                            "one persisted reference row."
                        )

                elif operation_name == "UPDATE":
                    before = operation.get(
                        "before"
                    )

                    after = operation.get(
                        "after"
                    )

                    if not isinstance(
                        after,
                        Mapping,
                    ):
                        raise ValueError(
                            "Reviewed UPDATE is missing its after state."
                        )

                    payload = _insert_payload(
                        pressing_id,
                        after,
                    )

                    if (
                        isinstance(
                            before,
                            Mapping,
                        )
                        and before.get(
                            "id"
                        )
                        is not None
                        and "id" in table.c
                    ):
                        update_clause = (
                            table.c.id
                            == int(
                                before[
                                    "id"
                                ]
                            )
                        )
                    else:
                        update_clause = where_clause

                    result = connection.execute(
                        table.update().where(
                            update_clause
                        ).values(
                            **{
                                key:
                                    value
                                for key, value in payload.items()
                                if key in table.c
                                and key != "pressing_id"
                            }
                        )
                    )

                    if result.rowcount != 1:
                        raise ValueError(
                            "A reviewed UPDATE no longer matches exactly "
                            "one persisted reference row."
                        )

                elif operation_name == "INSERT":
                    after = operation.get(
                        "after"
                    )

                    if not isinstance(
                        after,
                        Mapping,
                    ):
                        raise ValueError(
                            "Reviewed INSERT is missing its after state."
                        )

                    payload = _insert_payload(
                        pressing_id,
                        after,
                    )

                    connection.execute(
                        table.insert().values(
                            **{
                                key:
                                    value
                                for key, value in payload.items()
                                if key in table.c
                            }
                        )
                    )

                else:
                    raise AssertionError(
                        f"Unsupported operation {operation_name!r}."
                    )

                applied_operations.append(
                    dict(
                        operation
                    )
                )

        audit_rows = list_reference_audit(
            engine,
            pressing_id,
            limit=500,
        )

        current_rows = load_reference_editor_rows(
            engine,
            pressing_id,
        )

        return {
            "status":
                "COMPLETED",
            "pressing_id":
                int(
                    pressing_id
                ),
            "catalog_number":
                normalized_catalog,
            "applied_operation_count":
                len(
                    applied_operations
                ),
            "operations":
                applied_operations,
            "persisted_reference_row_count":
                len(
                    [
                        row
                        for row in current_rows
                        if bool(
                            row[
                                "persisted"
                            ]
                        )
                    ]
                ),
            "audit_event_count":
                len(
                    audit_rows
                ),
        }
    finally:
        connection.close()
