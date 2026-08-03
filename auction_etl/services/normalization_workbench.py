"""Normalization work queues and audited bulk curation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


WORK_TABLES = {
    "CONDITION":
        "warehouse.auction_condition_normalization",
    "ANALYSIS_FACTOR":
        "warehouse.auction_analysis_input",
}

COMPARABLE_DECISIONS = (
    "INCLUDE",
    "EXCLUDE",
    "NEEDS_REVIEW",
)

IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


@dataclass(frozen=True)
class ColumnContract:
    """One writable PostgreSQL column."""

    name: str
    sql_type: str
    nullable: bool
    has_default: bool


@dataclass(frozen=True)
class TableContract:
    """The discovered write contract for one table."""

    work_type: str
    schema_name: str
    table_name: str
    conflict_columns: tuple[str, ...]
    editable_columns: tuple[ColumnContract, ...]
    has_created_at: bool
    has_updated_at: bool


def _quote_identifier(value: str) -> str:
    """Quote one trusted PostgreSQL identifier."""
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"Unsafe SQL identifier: {value}"
        )

    return f'"{value}"'


def _qualified_table(
    contract: TableContract,
) -> str:
    """Return one safely quoted relation name."""
    return (
        f"{_quote_identifier(contract.schema_name)}."
        f"{_quote_identifier(contract.table_name)}"
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


def _truthy(value: Any) -> bool:
    """Parse an explicit worksheet apply flag."""
    normalized = (
        str(value).strip().upper()
        if value is not None
        else ""
    )

    return normalized in {
        "1",
        "TRUE",
        "T",
        "YES",
        "Y",
    }


def _json_text(value: Any) -> str | None:
    """Serialize optional JSON values."""
    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )


def _serialize_cell(value: Any) -> str:
    """Serialize one PostgreSQL value into CSV."""
    if value is None:
        return ""

    if isinstance(
        value,
        (
            list,
            tuple,
            dict,
        ),
    ):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    return str(value)


def _set_audit_context(
    connection: Connection,
    *,
    actor: str,
    reason: str,
    batch_id: UUID | None = None,
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
                ),
                set_config(
                    'auction_etl.batch_id',
                    :batch_id,
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
            "batch_id":
                (
                    str(batch_id)
                    if batch_id is not None
                    else ""
                ),
        },
    )


def list_queue(
    engine: Engine,
    *,
    search: str | None = None,
    work_status: str | None = None,
    blocker_code: str | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Return prioritized normalization work."""
    normalized_search = _optional_text(
        search
    )

    normalized_status = _optional_text(
        work_status
    )

    normalized_blocker = _optional_text(
        blocker_code
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM analytics.normalization_work_queue
                WHERE (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        title,
                        artist,
                        catalog_number,
                        media_type,
                        marketplace,
                        listing_id,
                        display_artist,
                        display_title
                    ) ILIKE
                        '%' ||
                        CAST(:search AS text) ||
                        '%'
                )
                  AND (
                    CAST(:work_status AS text) IS NULL
                    OR work_status =
                        CAST(:work_status AS text)
                )
                  AND (
                    CAST(:blocker_code AS text) IS NULL
                    OR CAST(:blocker_code AS text) =
                        ANY(blocker_codes)
                )
                ORDER BY
                    priority_score DESC,
                    pressing_id NULLS LAST,
                    marketplace,
                    listing_id
                LIMIT :limit
                """
            ),
            {
                "search":
                    normalized_search,
                "work_status":
                    normalized_status,
                "blocker_code":
                    normalized_blocker,
                "limit":
                    limit,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def queue_summary(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """Summarize explicit normalization work states."""
    materialized = list(rows)

    statuses = {
        str(row["work_status"])
        for row in materialized
    }

    summary = {
        "total":
            len(materialized),
        "ready":
            sum(
                row["work_status"] == "READY"
                for row in materialized
            ),
        "blocked":
            sum(
                row["work_status"] != "READY"
                for row in materialized
            ),
    }

    for status in sorted(statuses):
        summary[status] = sum(
            row["work_status"] == status
            for row in materialized
        )

    return summary


def list_reference_candidates(
    engine: Engine,
    *,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return general pressing-reference candidates."""
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
                    pressing.media_type,
                    pressing.release_year,
                    pressing.generation,
                    pressing.pressing_variant_label,
                    COUNT(
                        DISTINCT assignment.id
                    ) AS assigned_listing_count,
                    COUNT(
                        DISTINCT expectation.id
                    ) AS expectation_count,
                    COUNT(
                        DISTINCT observation.id
                    ) AS observation_count,
                    array_remove(
                        array_agg(
                            DISTINCT observation.component_code
                        ),
                        NULL
                    ) AS observed_component_codes
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
                WHERE (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        family.display_artist,
                        family.display_title,
                        pressing.catalog_number,
                        pressing.matrix_number,
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
                    (
                        COUNT(DISTINCT expectation.id) = 0
                    ) DESC,
                    COUNT(DISTINCT assignment.id) DESC,
                    COUNT(DISTINCT observation.id) DESC,
                    pressing.id
                """
            ),
            {
                "search":
                    _optional_text(search),
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def load_table_contract(
    engine: Engine,
    work_type: str,
) -> TableContract:
    """Discover the real writable table contract."""
    normalized_type = _required_text(
        work_type,
        "Work type",
    ).upper()

    relation = WORK_TABLES.get(
        normalized_type
    )

    if relation is None:
        raise ValueError(
            f"Unsupported work type: {normalized_type}"
        )

    schema_name, table_name = relation.split(
        ".",
        1,
    )

    with engine.connect() as connection:
        column_rows = connection.execute(
            text(
                """
                SELECT
                    attribute.attname AS column_name,
                    pg_catalog.format_type(
                        attribute.atttypid,
                        attribute.atttypmod
                    ) AS sql_type,
                    NOT attribute.attnotnull AS nullable,
                    attribute.attidentity <> '' AS is_identity,
                    attribute.attgenerated <> '' AS is_generated,
                    default_value.adbin IS NOT NULL AS has_default
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid =
                        attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid =
                        relation.relnamespace
                LEFT JOIN pg_catalog.pg_attrdef AS default_value
                  ON default_value.adrelid =
                        attribute.attrelid
                 AND default_value.adnum =
                        attribute.attnum
                WHERE namespace.nspname =
                        :schema_name
                  AND relation.relname =
                        :table_name
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY attribute.attnum
                """
            ),
            {
                "schema_name":
                    schema_name,
                "table_name":
                    table_name,
            },
        ).mappings().all()

        constraint_rows = connection.execute(
            text(
                """
                SELECT
                    constraint_definition.conname,
                    array_agg(
                        attribute.attname
                        ORDER BY key_column.ordinality
                    ) AS columns
                FROM pg_catalog.pg_constraint
                    AS constraint_definition
                JOIN LATERAL unnest(
                    constraint_definition.conkey
                ) WITH ORDINALITY
                    AS key_column(attnum, ordinality)
                  ON true
                JOIN pg_catalog.pg_attribute AS attribute
                  ON attribute.attrelid =
                        constraint_definition.conrelid
                 AND attribute.attnum =
                        key_column.attnum
                WHERE constraint_definition.conrelid =
                        CAST(:relation AS regclass)
                  AND constraint_definition.contype
                        IN ('p', 'u')
                GROUP BY
                    constraint_definition.conname
                """
            ),
            {
                "relation":
                    relation,
            },
        ).mappings().all()

    if not column_rows:
        raise ValueError(
            f"Relation does not exist: {relation}"
        )

    conflict_columns: tuple[str, ...] | None = None

    for constraint in constraint_rows:
        columns = tuple(
            constraint["columns"]
        )

        if set(columns) == {
            "marketplace",
            "listing_id",
        }:
            conflict_columns = columns
            break

    if conflict_columns is None:
        raise ValueError(
            f"{relation} does not have a unique "
            "(marketplace, listing_id) contract."
        )

    column_names = {
        row["column_name"]
        for row in column_rows
    }

    excluded_columns = {
        "id",
        "marketplace",
        "listing_id",
        "created_at",
        "updated_at",
    }

    editable_columns = tuple(
        ColumnContract(
            name=str(row["column_name"]),
            sql_type=str(row["sql_type"]),
            nullable=bool(row["nullable"]),
            has_default=bool(row["has_default"]),
        )
        for row in column_rows
        if row["column_name"]
            not in excluded_columns
        and not bool(row["is_identity"])
        and not bool(row["is_generated"])
    )

    if not editable_columns:
        raise ValueError(
            f"{relation} exposes no editable columns."
        )

    return TableContract(
        work_type=normalized_type,
        schema_name=schema_name,
        table_name=table_name,
        conflict_columns=conflict_columns,
        editable_columns=editable_columns,
        has_created_at=(
            "created_at" in column_names
        ),
        has_updated_at=(
            "updated_at" in column_names
        ),
    )


def _load_existing_rows(
    connection: Connection,
    contract: TableContract,
    identities: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load current rows for selected listing identities."""
    if not identities:
        return {}

    predicates: list[str] = []
    parameters: dict[str, Any] = {}

    for index, identity in enumerate(
        identities
    ):
        predicates.append(
            "("
            "marketplace = :marketplace_"
            f"{index} "
            "AND listing_id = :listing_id_"
            f"{index}"
            ")"
        )

        parameters[
            f"marketplace_{index}"
        ] = identity[0]

        parameters[
            f"listing_id_{index}"
        ] = identity[1]

    relation = _qualified_table(contract)

    rows = connection.execute(
        text(
            f"""
            SELECT *
            FROM {relation}
            WHERE {" OR ".join(predicates)}
            """
        ),
        parameters,
    ).mappings().all()

    return {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        ): dict(row)
        for row in rows
    }


def export_workbook_csv(
    engine: Engine,
    work_type: str,
    identities: Iterable[tuple[str, str]],
) -> bytes:
    """Export a schema-accurate bulk worksheet."""
    contract = load_table_contract(
        engine,
        work_type,
    )

    normalized_identities = list(
        dict.fromkeys(
            (
                _required_text(
                    marketplace,
                    "Marketplace",
                ),
                _required_text(
                    listing_id,
                    "Listing ID",
                ),
            )
            for marketplace, listing_id
            in identities
        )
    )

    with engine.connect() as connection:
        existing = _load_existing_rows(
            connection,
            contract,
            normalized_identities,
        )

    output = io.StringIO()
    fieldnames = [
        "apply",
        "marketplace",
        "listing_id",
        *[
            column.name
            for column in contract.editable_columns
        ],
    ]

    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator="\n",
    )

    writer.writeheader()

    for marketplace, listing_id in normalized_identities:
        current = existing.get(
            (
                marketplace,
                listing_id,
            ),
            {},
        )

        row = {
            "apply":
                "FALSE",
            "marketplace":
                marketplace,
            "listing_id":
                listing_id,
        }

        for column in contract.editable_columns:
            row[column.name] = _serialize_cell(
                current.get(column.name)
            )

        writer.writerow(row)

    return output.getvalue().encode(
        "utf-8"
    )


def _parse_workbook(
    contract: TableContract,
    payload: bytes | str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse and structurally validate a worksheet."""
    text_payload = (
        payload.decode("utf-8-sig")
        if isinstance(payload, bytes)
        else payload
    )

    reader = csv.DictReader(
        io.StringIO(text_payload)
    )

    expected_headers = [
        "apply",
        "marketplace",
        "listing_id",
        *[
            column.name
            for column in contract.editable_columns
        ],
    ]

    if reader.fieldnames != expected_headers:
        return (
            [],
            [
                "Worksheet headers do not match "
                "the current database contract.",
            ],
        )

    rows: list[dict[str, str]] = []
    errors: list[str] = []
    identities: set[tuple[str, str]] = set()

    for row_number, raw_row in enumerate(
        reader,
        start=2,
    ):
        if not _truthy(
            raw_row.get("apply")
        ):
            continue

        marketplace = (
            raw_row.get("marketplace")
            or ""
        ).strip()

        listing_id = (
            raw_row.get("listing_id")
            or ""
        ).strip()

        if not marketplace or not listing_id:
            errors.append(
                f"Row {row_number}: marketplace "
                "and listing_id are required."
            )
            continue

        identity = (
            marketplace,
            listing_id,
        )

        if identity in identities:
            errors.append(
                f"Row {row_number}: duplicate listing "
                f"{marketplace}/{listing_id}."
            )
            continue

        identities.add(identity)

        row = {
            key:
                (
                    value.strip()
                    if value is not None
                    else ""
                )
            for key, value in raw_row.items()
        }

        row["_row_number"] = str(
            row_number
        )

        rows.append(row)

    return rows, errors


def _validate_listing_identities(
    connection: Connection,
    rows: list[dict[str, str]],
) -> list[str]:
    """Ensure worksheet identities exist in the warehouse."""
    if not rows:
        return []

    predicates: list[str] = []
    parameters: dict[str, Any] = {}

    for index, row in enumerate(rows):
        predicates.append(
            "("
            "marketplace = :marketplace_"
            f"{index} "
            "AND listing_id = :listing_id_"
            f"{index}"
            ")"
        )

        parameters[
            f"marketplace_{index}"
        ] = row["marketplace"]

        parameters[
            f"listing_id_{index}"
        ] = row["listing_id"]

    existing = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in connection.execute(
            text(
                f"""
                SELECT
                    marketplace,
                    listing_id
                FROM warehouse.auction
                WHERE {" OR ".join(predicates)}
                """
            ),
            parameters,
        ).mappings()
    }

    errors: list[str] = []

    for row in rows:
        identity = (
            row["marketplace"],
            row["listing_id"],
        )

        if identity not in existing:
            errors.append(
                "Row "
                f"{row['_row_number']}: unknown listing "
                f"{identity[0]}/{identity[1]}."
            )

    return errors


def _upsert_dynamic_row(
    connection: Connection,
    contract: TableContract,
    row: Mapping[str, str],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
]:
    """Insert or update one schema-accurate row."""
    relation = _qualified_table(
        contract
    )

    before = connection.execute(
        text(
            f"""
            SELECT *
            FROM {relation}
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """
        ),
        {
            "marketplace":
                row["marketplace"],
            "listing_id":
                row["listing_id"],
        },
    ).mappings().one_or_none()

    insert_columns = [
        "marketplace",
        "listing_id",
        *[
            column.name
            for column in contract.editable_columns
        ],
    ]

    quoted_insert_columns = [
        _quote_identifier(column)
        for column in insert_columns
    ]

    parameters: dict[str, Any] = {
        "marketplace":
            row["marketplace"],
        "listing_id":
            row["listing_id"],
    }

    value_expressions = [
        ":marketplace",
        ":listing_id",
    ]

    update_assignments: list[str] = []

    for index, column in enumerate(
        contract.editable_columns
    ):
        parameter_name = f"value_{index}"

        parameters[parameter_name] = (
            row.get(column.name)
            if row.get(column.name) != ""
            else None
        )

        value_expressions.append(
            f"CAST(:{parameter_name} "
            f"AS {column.sql_type})"
        )

        quoted_column = _quote_identifier(
            column.name
        )

        update_assignments.append(
            f"{quoted_column} = "
            f"EXCLUDED.{quoted_column}"
        )

    if contract.has_updated_at:
        update_assignments.append(
            '"updated_at" = now()'
        )

    conflict_columns = ", ".join(
        _quote_identifier(column)
        for column in contract.conflict_columns
    )

    after = connection.execute(
        text(
            f"""
            INSERT INTO {relation} (
                {", ".join(quoted_insert_columns)}
            )
            VALUES (
                {", ".join(value_expressions)}
            )
            ON CONFLICT ({conflict_columns})
            DO UPDATE SET
                {", ".join(update_assignments)}
            RETURNING *
            """
        ),
        parameters,
    ).mappings().one()

    return (
        dict(before)
        if before is not None
        else None,
        dict(after),
    )


def preview_workbook(
    engine: Engine,
    work_type: str,
    payload: bytes | str,
) -> dict[str, Any]:
    """Validate and dry-run a worksheet without persisting it."""
    contract = load_table_contract(
        engine,
        work_type,
    )

    rows, errors = _parse_workbook(
        contract,
        payload,
    )

    if errors:
        return {
            "ready":
                False,
            "work_type":
                contract.work_type,
            "requested_rows":
                len(rows),
            "errors":
                errors,
            "rows":
                [],
        }

    dry_run_rows: list[dict[str, Any]] = []

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            errors.extend(
                _validate_listing_identities(
                    connection,
                    rows,
                )
            )

            if errors:
                transaction.rollback()

                return {
                    "ready":
                        False,
                    "work_type":
                        contract.work_type,
                    "requested_rows":
                        len(rows),
                    "errors":
                        errors,
                    "rows":
                        [],
                }

            for row in rows:
                savepoint = (
                    connection.begin_nested()
                )

                try:
                    before, after = (
                        _upsert_dynamic_row(
                            connection,
                            contract,
                            row,
                        )
                    )
                except Exception as error:
                    savepoint.rollback()

                    errors.append(
                        "Row "
                        f"{row['_row_number']}: "
                        f"{error}"
                    )

                    continue

                savepoint.rollback()

                dry_run_rows.append(
                    {
                        "row_number":
                            int(
                                row[
                                    "_row_number"
                                ]
                            ),
                        "marketplace":
                            row[
                                "marketplace"
                            ],
                        "listing_id":
                            row[
                                "listing_id"
                            ],
                        "outcome":
                            (
                                "UPDATED"
                                if before is not None
                                else "INSERTED"
                            ),
                        "before_state":
                            before,
                        "after_state":
                            after,
                    }
                )
        finally:
            if transaction.is_active:
                transaction.rollback()

    return {
        "ready":
            not errors,
        "work_type":
            contract.work_type,
        "requested_rows":
            len(rows),
        "errors":
            errors,
        "rows":
            dry_run_rows,
    }


def _create_batch(
    engine: Engine,
    *,
    work_type: str,
    filename: str | None,
    payload: bytes,
    actor: str,
    reason: str,
    requested_rows: int,
) -> UUID:
    """Create one durable batch record."""
    batch_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO system.normalization_work_batch (
                    id,
                    work_type,
                    filename,
                    payload_sha256,
                    actor,
                    reason,
                    status,
                    requested_row_count
                )
                VALUES (
                    :id,
                    :work_type,
                    :filename,
                    :payload_sha256,
                    :actor,
                    :reason,
                    'RUNNING',
                    :requested_row_count
                )
                """
            ),
            {
                "id":
                    batch_id,
                "work_type":
                    work_type,
                "filename":
                    filename,
                "payload_sha256":
                    hashlib.sha256(
                        payload
                    ).hexdigest(),
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
                "requested_row_count":
                    requested_rows,
            },
        )

    return batch_id


def apply_workbook(
    engine: Engine,
    work_type: str,
    payload: bytes | str,
    *,
    actor: str,
    reason: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Apply one validated worksheet atomically."""
    payload_bytes = (
        payload
        if isinstance(payload, bytes)
        else payload.encode("utf-8")
    )

    preview = preview_workbook(
        engine,
        work_type,
        payload_bytes,
    )

    if not preview["ready"]:
        raise ValueError(
            "Worksheet is invalid:\n"
            + "\n".join(
                preview["errors"]
            )
        )

    contract = load_table_contract(
        engine,
        work_type,
    )

    parsed_rows, parse_errors = (
        _parse_workbook(
            contract,
            payload_bytes,
        )
    )

    if parse_errors:
        raise ValueError(
            "\n".join(parse_errors)
        )

    batch_id = _create_batch(
        engine,
        work_type=contract.work_type,
        filename=filename,
        payload=payload_bytes,
        actor=actor,
        reason=reason,
        requested_rows=len(parsed_rows),
    )

    applied_rows = 0

    try:
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
                    batch_id=batch_id,
                )

                for row in parsed_rows:
                    before, after = (
                        _upsert_dynamic_row(
                            connection,
                            contract,
                            row,
                        )
                    )

                    outcome = (
                        "UPDATED"
                        if before is not None
                        else "INSERTED"
                    )

                    connection.execute(
                        text(
                            """
                            INSERT INTO system.normalization_work_batch_row (
                                batch_id,
                                row_number,
                                entity_key,
                                outcome,
                                before_state,
                                after_state
                            )
                            VALUES (
                                :batch_id,
                                :row_number,
                                CAST(:entity_key AS jsonb),
                                :outcome,
                                CAST(:before_state AS jsonb),
                                CAST(:after_state AS jsonb)
                            )
                            """
                        ),
                        {
                            "batch_id":
                                batch_id,
                            "row_number":
                                int(
                                    row[
                                        "_row_number"
                                    ]
                                ),
                            "entity_key":
                                _json_text(
                                    {
                                        "marketplace":
                                            row[
                                                "marketplace"
                                            ],
                                        "listing_id":
                                            row[
                                                "listing_id"
                                            ],
                                    }
                                ),
                            "outcome":
                                outcome,
                            "before_state":
                                _json_text(
                                    before
                                ),
                            "after_state":
                                _json_text(
                                    after
                                ),
                        },
                    )

                    applied_rows += 1

                connection.execute(
                    text(
                        """
                        UPDATE system.normalization_work_batch
                        SET
                            status = 'COMPLETED',
                            applied_row_count =
                                :applied_row_count,
                            rejected_row_count = 0,
                            validation_summary =
                                CAST(:validation_summary AS jsonb),
                            completed_at = now()
                        WHERE id = :batch_id
                        """
                    ),
                    {
                        "batch_id":
                            batch_id,
                        "applied_row_count":
                            applied_rows,
                        "validation_summary":
                            _json_text(
                                {
                                    "preview_rows":
                                        len(
                                            preview[
                                                "rows"
                                            ]
                                        ),
                                    "errors":
                                        [],
                                }
                            ),
                    },
                )
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE system.normalization_work_batch
                    SET
                        status = 'FAILED',
                        rejected_row_count =
                            requested_row_count,
                        error_message = :error_message,
                        completed_at = now()
                    WHERE id = :batch_id
                    """
                ),
                {
                    "batch_id":
                        batch_id,
                    "error_message":
                        str(error),
                },
            )

        raise

    return {
        "batch_id":
            str(batch_id),
        "work_type":
            contract.work_type,
        "applied_rows":
            applied_rows,
        "status":
            "COMPLETED",
    }


def list_comparable_candidates(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> list[dict[str, Any]]:
    """Return exact-pressing candidate comparables."""
    with engine.connect() as connection:
        target = connection.execute(
            text(
                """
                SELECT pressing_id
                FROM analytics.auction_collector_base
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
            },
        ).mappings().one_or_none()

        if target is None:
            raise ValueError(
                "Target listing does not exist."
            )

        pressing_id = target[
            "pressing_id"
        ]

        if pressing_id is None:
            return []

        rows = connection.execute(
            text(
                """
                SELECT
                    candidate.marketplace,
                    candidate.listing_id,
                    auction.title,
                    auction.seller,
                    auction.ended_at,
                    candidate.selected_price_usd,
                    candidate.condition_market_factor,
                    candidate.completeness_market_factor,
                    candidate.normalization_ready,
                    review.decision,
                    review.reason,
                    review.actor,
                    review.updated_at
                FROM analytics.auction_collector_base
                    AS candidate
                JOIN warehouse.auction AS auction
                  ON auction.marketplace =
                        candidate.marketplace
                 AND auction.listing_id =
                        candidate.listing_id
                LEFT JOIN warehouse.auction_comparable_review
                    AS review
                  ON review.marketplace =
                        :marketplace
                 AND review.listing_id =
                        :listing_id
                 AND review.comparable_marketplace =
                        candidate.marketplace
                 AND review.comparable_listing_id =
                        candidate.listing_id
                WHERE candidate.pressing_id =
                        :pressing_id
                  AND (
                        candidate.marketplace <>
                            :marketplace
                        OR candidate.listing_id <>
                            :listing_id
                  )
                ORDER BY
                    candidate.normalization_ready DESC NULLS LAST,
                    auction.ended_at,
                    candidate.marketplace,
                    candidate.listing_id
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "pressing_id":
                    pressing_id,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def save_comparable_review(
    engine: Engine,
    *,
    marketplace: str,
    listing_id: str,
    comparable_marketplace: str,
    comparable_listing_id: str,
    decision: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Save one reviewed exact-pressing comparison decision."""
    normalized_decision = _required_text(
        decision,
        "Decision",
    ).upper()

    if normalized_decision not in COMPARABLE_DECISIONS:
        raise ValueError(
            "Unsupported comparable decision."
        )

    if (
        marketplace,
        listing_id,
    ) == (
        comparable_marketplace,
        comparable_listing_id,
    ):
        raise ValueError(
            "A listing cannot be compared to itself."
        )

    with engine.begin() as connection:
        pressing_rows = connection.execute(
            text(
                """
                SELECT
                    marketplace,
                    listing_id,
                    pressing_id
                FROM analytics.auction_collector_base
                WHERE (
                        marketplace = :marketplace
                        AND listing_id = :listing_id
                      )
                   OR (
                        marketplace =
                            :comparable_marketplace
                        AND listing_id =
                            :comparable_listing_id
                      )
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "comparable_marketplace":
                    comparable_marketplace,
                "comparable_listing_id":
                    comparable_listing_id,
            },
        ).mappings().all()

        if len(pressing_rows) != 2:
            raise ValueError(
                "Both listings must exist."
            )

        pressing_ids = {
            row["pressing_id"]
            for row in pressing_rows
        }

        if None in pressing_ids or len(
            pressing_ids
        ) != 1:
            raise ValueError(
                "Comparable review requires the same exact pressing."
            )

        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_comparable_review (
                    marketplace,
                    listing_id,
                    comparable_marketplace,
                    comparable_listing_id,
                    decision,
                    reason,
                    actor
                )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :comparable_marketplace,
                    :comparable_listing_id,
                    :decision,
                    :reason,
                    :actor
                )
                ON CONFLICT (
                    marketplace,
                    listing_id,
                    comparable_marketplace,
                    comparable_listing_id
                )
                DO UPDATE SET
                    decision =
                        EXCLUDED.decision,
                    reason =
                        EXCLUDED.reason,
                    actor =
                        EXCLUDED.actor,
                    updated_at = now()
                RETURNING *
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "comparable_marketplace":
                    comparable_marketplace,
                "comparable_listing_id":
                    comparable_listing_id,
                "decision":
                    normalized_decision,
                "reason":
                    _required_text(
                        reason,
                        "Reason",
                    ),
                "actor":
                    _required_text(
                        actor,
                        "Actor",
                    ),
            },
        ).mappings().one()

    return dict(row)


def list_work_batches(
    engine: Engine,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return recent normalization batches."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.normalization_work_batch
                ORDER BY
                    created_at DESC,
                    id
                LIMIT :limit
                """
            ),
            {
                "limit":
                    limit,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def list_work_audit(
    engine: Engine,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return immutable normalization history."""
    with engine.connect() as connection:
        rows = connection.execute(
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

    return [
        dict(row)
        for row in rows
    ]
