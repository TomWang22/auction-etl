"""State-safe exact-pressing completeness evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import math
from typing import Any, Mapping

from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.engine import Connection, Engine


PRESENT_STATES = frozenset(
    {
        "PRESENT",
        "VERIFIED_PRESENT",
        "OBSERVED_PRESENT",
        "INCLUDED",
        "YES",
    }
)

ABSENT_STATES = frozenset(
    {
        "ABSENT",
        "VERIFIED_ABSENT",
        "OBSERVED_ABSENT",
        "MISSING",
        "NOT_PRESENT",
        "NO",
    }
)

DAMAGE_TOKENS = frozenset(
    {
        "DAMAGED",
        "BROKEN",
        "TORN",
        "STAINED",
        "WARPED",
        "CRACKED",
        "INCOMPLETE",
    }
)

VALID_STATUSES = frozenset(
    {
        "COMPLETE",
        "INCOMPLETE",
        "INSUFFICIENT_OBSERVATION",
        "NO_VERIFIED_REFERENCE",
        "NO_PRESSING_ASSIGNMENT",
        "FACTORY_SEALED_EXCEPTION",
    }
)


@dataclass(frozen=True)
class ListingCompletenessResult:
    """One deterministic listing-versus-master evaluation."""

    marketplace: str
    listing_id: str
    pressing_id: int | None
    catalog_number: str | None
    media_type: str | None
    status: str
    structural_complete: bool
    required_component_count: int
    required_unit_count: int
    satisfied_unit_count: int
    completeness_ratio: str | None
    missing_components: tuple[dict[str, Any], ...]
    quantity_shortfalls: tuple[dict[str, Any], ...]
    unverified_components: tuple[dict[str, Any], ...]
    contradictory_components: tuple[dict[str, Any], ...]
    damaged_components: tuple[dict[str, Any], ...]
    ignored_reference_rows: int
    observation_count: int
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe mapping."""
        return asdict(
            self
        )


def _upper(value: object) -> str:
    """Normalize a state-like value."""
    return str(
        value
        or ""
    ).strip().upper()


def _text(value: object) -> str:
    """Normalize optional text."""
    return str(
        value
        or ""
    ).strip()


def _integer(
    value: object,
    *,
    default: int = 0,
) -> int:
    """Normalize one integral value."""
    if value is None:
        return default

    if isinstance(
        value,
        float,
    ) and math.isnan(
        value
    ):
        return default

    try:
        return int(
            Decimal(
                str(
                    value
                )
            )
        )
    except Exception:
        return default


def _table(
    connection: Connection,
    schema: str,
    name: str,
) -> Table:
    """Reflect one live table."""
    return Table(
        name,
        MetaData(),
        schema=schema,
        autoload_with=connection,
    )


def _assignment(
    connection: Connection,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Load the exact pressing assigned to one listing."""
    row = connection.execute(
        text(
            """
            SELECT
                assignment.marketplace,
                assignment.listing_id,
                assignment.pressing_id,
                pressing.catalog_number,
                pressing.media_type,
                family.display_artist,
                family.display_title,
                auction.title
            FROM warehouse.auction_pressing_assignment
                AS assignment
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id =
                    assignment.pressing_id
            JOIN warehouse.release_family AS family
              ON family.id =
                    pressing.release_family_id
            JOIN warehouse.auction
              ON auction.marketplace =
                    assignment.marketplace
             AND auction.listing_id =
                    assignment.listing_id
            WHERE assignment.marketplace =
                    :marketplace
              AND assignment.listing_id =
                    :listing_id
            """
        ),
        {
            "marketplace":
                marketplace,
            "listing_id":
                listing_id,
        },
    ).mappings().one_or_none()

    return (
        dict(
            row
        )
        if row is not None
        else None
    )


def _active_profile_codes(
    connection: Connection,
    media_type: str,
) -> set[str]:
    """Return authoritative applicable component codes."""
    if connection.execute(
        text(
            """
            SELECT to_regclass(
                'system.media_profile_component'
            )
            """
        )
    ).scalar_one() is None:
        rows = connection.execute(
            text(
                """
                SELECT code
                FROM system.component_type
                WHERE active
                  AND :media_type =
                        ANY(applicable_media)
                """
            ),
            {
                "media_type":
                    media_type,
            },
        ).scalars().all()
    else:
        rows = connection.execute(
            text(
                """
                SELECT component_code
                FROM system.media_profile_component
                WHERE media_type =
                        :media_type
                  AND active
                """
            ),
            {
                "media_type":
                    media_type,
            },
        ).scalars().all()

    return {
        str(
            value
        )
        for value in rows
    }


def _existing_factory_status(
    connection: Connection,
    marketplace: str,
    listing_id: str,
) -> str | None:
    """Discover an existing factory-sealed status when available."""
    inspector = inspect(
        connection
    )

    candidate_views = [
        name
        for name in inspector.get_view_names(
            schema="analytics"
        )
        + inspector.get_view_names(
            schema="warehouse"
        )
        if (
            "complete"
            in name.casefold()
            or "sealed"
            in name.casefold()
        )
    ]

    for schema in (
        "analytics",
        "warehouse",
    ):
        for view_name in candidate_views:
            try:
                columns = {
                    column[
                        "name"
                    ]
                    for column in inspector.get_columns(
                        view_name,
                        schema=schema,
                    )
                }
            except Exception:
                continue

            if not {
                "marketplace",
                "listing_id",
            } <= columns:
                continue

            status_column = next(
                (
                    candidate
                    for candidate in (
                        "completeness_status",
                        "status",
                        "result_status",
                    )
                    if candidate in columns
                ),
                None,
            )

            if status_column is None:
                continue

            statement = text(
                f"""
                SELECT CAST(
                    "{status_column}"
                    AS text
                )
                FROM "{schema}"."{view_name}"
                WHERE marketplace =
                        :marketplace
                  AND listing_id =
                        :listing_id
                LIMIT 1
                """
            )

            try:
                status = connection.execute(
                    statement,
                    {
                        "marketplace":
                            marketplace,
                        "listing_id":
                            listing_id,
                    },
                ).scalar_one_or_none()
            except Exception:
                continue

            if _upper(
                status
            ) == "FACTORY_SEALED_EXCEPTION":
                return "FACTORY_SEALED_EXCEPTION"

    return None


def _damage_values(
    observation: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return explicit structured damage values."""
    damage_columns = (
        "damage_state",
        "condition_state",
        "component_condition",
        "damage_code",
    )

    values: list[str] = []

    for column in damage_columns:
        if column not in observation:
            continue

        normalized = _upper(
            observation.get(
                column
            )
        )

        if normalized:
            values.append(
                normalized
            )

    return tuple(
        values
    )


def list_assigned_listings(
    engine: Engine,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """List auction listings with exact-pressing assignments."""
    normalized_search = (
        str(
            search
        ).strip()
        if search is not None
        else None
    )

    if normalized_search == "":
        normalized_search = None

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    assignment.marketplace,
                    assignment.listing_id,
                    assignment.pressing_id,
                    auction.title,
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    pressing.media_type
                FROM warehouse.auction_pressing_assignment
                    AS assignment
                JOIN warehouse.auction
                  ON auction.marketplace =
                        assignment.marketplace
                 AND auction.listing_id =
                        assignment.listing_id
                JOIN warehouse.pressing_identity AS pressing
                  ON pressing.id =
                        assignment.pressing_id
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                WHERE (
                    CAST(
                        :search
                        AS text
                    ) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        assignment.marketplace,
                        assignment.listing_id,
                        auction.title,
                        family.display_artist,
                        family.display_title,
                        pressing.catalog_number,
                        pressing.media_type
                    ) ILIKE (
                        '%'
                        || CAST(
                            :search
                            AS text
                        )
                        || '%'
                    )
                )
                ORDER BY
                    family.display_artist,
                    family.display_title,
                    pressing.catalog_number,
                    assignment.marketplace,
                    assignment.listing_id
                """
            ),
            {
                "search":
                    normalized_search,
            },
        ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]


def evaluate_listing(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> ListingCompletenessResult:
    """Evaluate one copy against its exact-pressing master."""
    normalized_marketplace = _text(
        marketplace
    )

    normalized_listing_id = _text(
        listing_id
    )

    with engine.connect() as connection:
        assignment = _assignment(
            connection,
            normalized_marketplace,
            normalized_listing_id,
        )

        if assignment is None:
            return ListingCompletenessResult(
                marketplace=normalized_marketplace,
                listing_id=normalized_listing_id,
                pressing_id=None,
                catalog_number=None,
                media_type=None,
                status="NO_PRESSING_ASSIGNMENT",
                structural_complete=False,
                required_component_count=0,
                required_unit_count=0,
                satisfied_unit_count=0,
                completeness_ratio=None,
                missing_components=(),
                quantity_shortfalls=(),
                unverified_components=(),
                contradictory_components=(),
                damaged_components=(),
                ignored_reference_rows=0,
                observation_count=0,
                explanation=(
                    "The listing has not been assigned to an exact pressing."
                ),
            )

        pressing_id = int(
            assignment[
                "pressing_id"
            ]
        )

        media_type = str(
            assignment[
                "media_type"
            ]
        )

        profile_codes = _active_profile_codes(
            connection,
            media_type,
        )

        expectation_table = _table(
            connection,
            "warehouse",
            "pressing_component_expectation",
        )

        observation_table = _table(
            connection,
            "warehouse",
            "auction_component_observation",
        )

        expectation_rows = [
            dict(
                row
            )
            for row in connection.execute(
                expectation_table.select().where(
                    expectation_table.c.pressing_id
                    == pressing_id
                )
            ).mappings().all()
        ]

        observation_rows = [
            dict(
                row
            )
            for row in connection.execute(
                observation_table.select().where(
                    (
                        observation_table.c.marketplace
                        == normalized_marketplace
                    )
                    & (
                        observation_table.c.listing_id
                        == normalized_listing_id
                    )
                )
            ).mappings().all()
        ]

        active_reference_rows = [
            row
            for row in expectation_rows
            if (
                str(
                    row.get(
                        "component_code"
                    )
                )
                in profile_codes
            )
        ]

        asserted_reference_rows = [
            row
            for row in active_reference_rows
            if _upper(
                row.get(
                    "expectation_state"
                )
            )
            in {
                "REQUIRED",
                "NOT_INCLUDED",
            }
        ]

        required_rows = [
            row
            for row in active_reference_rows
            if _upper(
                row.get(
                    "expectation_state"
                )
            )
            == "REQUIRED"
        ]

        ignored_reference_rows = (
            len(
                expectation_rows
            )
            - len(
                required_rows
            )
        )

        factory_status = _existing_factory_status(
            connection,
            normalized_marketplace,
            normalized_listing_id,
        )

        if factory_status is not None:
            return ListingCompletenessResult(
                marketplace=normalized_marketplace,
                listing_id=normalized_listing_id,
                pressing_id=pressing_id,
                catalog_number=_text(
                    assignment.get(
                        "catalog_number"
                    )
                )
                or None,
                media_type=media_type,
                status="FACTORY_SEALED_EXCEPTION",
                structural_complete=False,
                required_component_count=len(
                    required_rows
                ),
                required_unit_count=sum(
                    max(
                        1,
                        _integer(
                            row.get(
                                "expected_quantity"
                            ),
                            default=1,
                        ),
                    )
                    for row in required_rows
                ),
                satisfied_unit_count=0,
                completeness_ratio=None,
                missing_components=(),
                quantity_shortfalls=(),
                unverified_components=(),
                contradictory_components=(),
                damaged_components=(),
                ignored_reference_rows=ignored_reference_rows,
                observation_count=len(
                    observation_rows
                ),
                explanation=(
                    "An existing verified factory-sealed exception applies. "
                    "Hidden components remain unverified and complete=true "
                    "is not inferred."
                ),
            )

        if not asserted_reference_rows:
            return ListingCompletenessResult(
                marketplace=normalized_marketplace,
                listing_id=normalized_listing_id,
                pressing_id=pressing_id,
                catalog_number=_text(
                    assignment.get(
                        "catalog_number"
                    )
                )
                or None,
                media_type=media_type,
                status="NO_VERIFIED_REFERENCE",
                structural_complete=False,
                required_component_count=0,
                required_unit_count=0,
                satisfied_unit_count=0,
                completeness_ratio=None,
                missing_components=(),
                quantity_shortfalls=(),
                unverified_components=(),
                contradictory_components=(),
                damaged_components=(),
                ignored_reference_rows=ignored_reference_rows,
                observation_count=len(
                    observation_rows
                ),
                explanation=(
                    "The exact pressing has no asserted REQUIRED or "
                    "NOT_INCLUDED master-reference rows."
                ),
            )

        observations_by_identity: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = {}

        for observation in observation_rows:
            identity = (
                _text(
                    observation.get(
                        "component_code"
                    )
                ),
                _text(
                    observation.get(
                        "variant_key"
                    )
                ),
            )

            observations_by_identity.setdefault(
                identity,
                [],
            ).append(
                observation
            )

        missing: list[
            dict[str, Any]
        ] = []

        shortfalls: list[
            dict[str, Any]
        ] = []

        unverified: list[
            dict[str, Any]
        ] = []

        contradictory: list[
            dict[str, Any]
        ] = []

        damaged: list[
            dict[str, Any]
        ] = []

        required_units = 0
        satisfied_units = 0

        for reference in required_rows:
            component_code = _text(
                reference.get(
                    "component_code"
                )
            )

            variant_key = _text(
                reference.get(
                    "variant_key"
                )
            )

            required_quantity = max(
                1,
                _integer(
                    reference.get(
                        "expected_quantity"
                    ),
                    default=1,
                ),
            )

            required_units += required_quantity

            matching = observations_by_identity.get(
                (
                    component_code,
                    variant_key,
                ),
                [],
            )

            present_rows = [
                row
                for row in matching
                if _upper(
                    row.get(
                        "observation_state"
                    )
                )
                in PRESENT_STATES
            ]

            absent_rows = [
                row
                for row in matching
                if _upper(
                    row.get(
                        "observation_state"
                    )
                )
                in ABSENT_STATES
            ]

            for observation in matching:
                explicit_damage = [
                    value
                    for value in _damage_values(
                        observation
                    )
                    if (
                        value in DAMAGE_TOKENS
                        or any(
                            token in value
                            for token in DAMAGE_TOKENS
                        )
                    )
                ]

                if explicit_damage:
                    damaged.append(
                        {
                            "component_code":
                                component_code,
                            "variant_key":
                                variant_key,
                            "damage_states":
                                explicit_damage,
                        }
                    )

            present_quantity = max(
                (
                    max(
                        1,
                        _integer(
                            row.get(
                                "observed_quantity"
                            ),
                            default=1,
                        ),
                    )
                    for row in present_rows
                ),
                default=0,
            )

            identity_payload = {
                "component_code":
                    component_code,
                "variant_key":
                    variant_key,
                "required_quantity":
                    required_quantity,
                "observed_quantity":
                    present_quantity,
            }

            if present_rows and absent_rows:
                contradictory.append(
                    identity_payload
                )
                satisfied_units += min(
                    present_quantity,
                    required_quantity,
                )
                continue

            if absent_rows:
                missing.append(
                    identity_payload
                )
                continue

            if not present_rows:
                unverified.append(
                    identity_payload
                )
                continue

            satisfied_units += min(
                present_quantity,
                required_quantity,
            )

            if present_quantity < required_quantity:
                shortfalls.append(
                    identity_payload
                )

        if required_units == 0:
            ratio = Decimal("1")
        else:
            ratio = (
                Decimal(
                    satisfied_units
                )
                / Decimal(
                    required_units
                )
            )

        if (
            missing
            or shortfalls
            or contradictory
        ):
            status = "INCOMPLETE"
        elif unverified:
            status = "INSUFFICIENT_OBSERVATION"
        else:
            status = "COMPLETE"

        explanation_map = {
            "COMPLETE": (
                "Every REQUIRED master component has sufficient verified "
                "listing-specific presence evidence."
            ),
            "INCOMPLETE": (
                "At least one REQUIRED master component is explicitly "
                "absent, contradictory, or below its required quantity."
            ),
            "INSUFFICIENT_OBSERVATION": (
                "No required absence was established, but one or more "
                "REQUIRED components remain unverified."
            ),
        }

        return ListingCompletenessResult(
            marketplace=normalized_marketplace,
            listing_id=normalized_listing_id,
            pressing_id=pressing_id,
            catalog_number=_text(
                assignment.get(
                    "catalog_number"
                )
            )
            or None,
            media_type=media_type,
            status=status,
            structural_complete=(
                status == "COMPLETE"
            ),
            required_component_count=len(
                required_rows
            ),
            required_unit_count=required_units,
            satisfied_unit_count=satisfied_units,
            completeness_ratio=format(
                ratio.quantize(
                    Decimal("0.0001")
                ),
                "f",
            ),
            missing_components=tuple(
                missing
            ),
            quantity_shortfalls=tuple(
                shortfalls
            ),
            unverified_components=tuple(
                unverified
            ),
            contradictory_components=tuple(
                contradictory
            ),
            damaged_components=tuple(
                damaged
            ),
            ignored_reference_rows=ignored_reference_rows,
            observation_count=len(
                observation_rows
            ),
            explanation=explanation_map[
                status
            ],
        )
