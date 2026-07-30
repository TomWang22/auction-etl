#!/usr/bin/env python3
"""Upsert normalized marketplace rows without pruning unrelated auctions."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Iterable

import psycopg
from psycopg import sql


TARGET_SCHEMA = "warehouse"
TARGET_TABLE = "auction"
CONSTRAINT_NAME = "uq_auction_marketplace_listing"


@dataclass(frozen=True)
class RelationCandidate:
    """A possible normalized staging relation."""

    schema: str
    name: str
    row_count: int
    unique_count: int
    marketplaces: tuple[str, ...]
    common_columns: int
    score: int

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally upsert normalized marketplace rows "
            "without pruning unrelated warehouse records."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
    )
    parser.add_argument(
        "--marketplace",
        default="ebay",
    )
    parser.add_argument(
        "--expected-source-rows",
        type=int,
        default=59,
    )
    parser.add_argument(
        "--minimum-existing-marketplace-rows",
        type=int,
        default=698,
    )
    parser.add_argument(
        "--expected-protected-rows",
        type=int,
        default=77,
    )
    parser.add_argument(
        "--protected-marketplace",
        default="buyee",
    )
    parser.add_argument(
        "--source-relation",
        help="Optional schema-qualified staging relation.",
    )
    return parser.parse_args()


def relation_columns(
    connection: psycopg.Connection,
    schema: str,
    table: str,
) -> list[str]:
    """Return relation columns in ordinal order."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [row[0] for row in cursor.fetchall()]


def target_required_columns(
    connection: psycopg.Connection,
) -> set[str]:
    """Return non-null target columns that lack generated defaults."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND is_nullable = 'NO'
              AND column_default IS NULL
              AND is_identity = 'NO'
              AND is_generated = 'NEVER'
            """,
            (TARGET_SCHEMA, TARGET_TABLE),
        )
        return {row[0] for row in cursor.fetchall()}


def relation_statistics(
    connection: psycopg.Connection,
    schema: str,
    table: str,
) -> tuple[int, int, tuple[str, ...]]:
    """Return count, unique key count, and marketplaces."""
    query = sql.SQL(
        """
        SELECT
            COUNT(*),
            COUNT(
                DISTINCT (
                    {marketplace},
                    {listing_id}
                )
            ),
            COALESCE(
                ARRAY_AGG(
                    DISTINCT {marketplace}
                    ORDER BY {marketplace}
                ),
                ARRAY[]::TEXT[]
            )
        FROM {relation}
        """
    ).format(
        marketplace=sql.Identifier("marketplace"),
        listing_id=sql.Identifier("listing_id"),
        relation=sql.Identifier(schema, table),
    )

    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            f"Could not inspect {schema}.{table}"
        )

    marketplaces = tuple(
        str(value)
        for value in row[2]
        if value is not None
    )

    return int(row[0]), int(row[1]), marketplaces


def candidate_score(
    schema: str,
    table: str,
    common_columns: int,
) -> int:
    """Prefer normalized staging relations with broad column coverage."""
    lowered = table.casefold()
    score = common_columns * 100

    if schema.casefold() == "staging":
        score += 500

    if "normalized" in lowered:
        score += 400

    if "auction" in lowered:
        score += 200

    if "listing" in lowered:
        score += 100

    if "raw" in lowered:
        score -= 1_000

    return score


def discover_candidates(
    connection: psycopg.Connection,
    *,
    marketplace: str,
    expected_rows: int,
) -> list[RelationCandidate]:
    """Find relations matching the normalized crawl snapshot."""
    target_columns = set(
        relation_columns(
            connection,
            TARGET_SCHEMA,
            TARGET_TABLE,
        )
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                columns.table_schema,
                columns.table_name
            FROM information_schema.columns AS columns
            JOIN pg_namespace AS namespace
              ON namespace.nspname =
                    columns.table_schema
            JOIN pg_class AS relation
              ON relation.relnamespace =
                    namespace.oid
             AND relation.relname =
                    columns.table_name
            WHERE relation.relkind IN (
                'r',
                'p',
                'v',
                'm',
                'f'
            )
              AND columns.column_name IN (
                'marketplace',
                'listing_id'
            )
              AND columns.table_schema NOT IN (
                'pg_catalog',
                'information_schema'
            )
            GROUP BY
                columns.table_schema,
                columns.table_name
            HAVING COUNT(
                DISTINCT columns.column_name
            ) = 2
            ORDER BY
                columns.table_schema,
                columns.table_name
            """
        )
        relations = cursor.fetchall()

    candidates: list[RelationCandidate] = []

    for schema, table in relations:
        if (
            schema == TARGET_SCHEMA
            and table == TARGET_TABLE
        ):
            continue

        columns = set(
            relation_columns(
                connection,
                schema,
                table,
            )
        )

        try:
            row_count, unique_count, marketplaces = (
                relation_statistics(
                    connection,
                    schema,
                    table,
                )
            )
        except psycopg.Error:
            continue

        if row_count != expected_rows:
            continue

        if unique_count != expected_rows:
            continue

        if marketplaces != (marketplace,):
            continue

        common_count = len(
            columns.intersection(target_columns)
        )

        candidates.append(
            RelationCandidate(
                schema=schema,
                name=table,
                row_count=row_count,
                unique_count=unique_count,
                marketplaces=marketplaces,
                common_columns=common_count,
                score=candidate_score(
                    schema,
                    table,
                    common_count,
                ),
            )
        )

    return sorted(
        candidates,
        key=lambda value: (
            value.score,
            value.qualified_name,
        ),
        reverse=True,
    )


def parse_relation_name(
    relation_name: str,
) -> tuple[str, str]:
    """Parse a simple schema-qualified relation name."""
    parts = relation_name.split(".", maxsplit=1)

    if len(parts) != 2 or not all(parts):
        raise ValueError(
            "--source-relation must be schema.table"
        )

    return parts[0], parts[1]


def choose_source(
    connection: psycopg.Connection,
    args: argparse.Namespace,
) -> RelationCandidate:
    """Choose one unambiguous normalized source relation."""
    if args.source_relation:
        schema, table = parse_relation_name(
            args.source_relation
        )

        columns = set(
            relation_columns(
                connection,
                schema,
                table,
            )
        )

        if not {
            "marketplace",
            "listing_id",
        }.issubset(columns):
            raise RuntimeError(
                f"{args.source_relation} lacks required keys"
            )

        row_count, unique_count, marketplaces = (
            relation_statistics(
                connection,
                schema,
                table,
            )
        )

        target_columns = set(
            relation_columns(
                connection,
                TARGET_SCHEMA,
                TARGET_TABLE,
            )
        )

        return RelationCandidate(
            schema=schema,
            name=table,
            row_count=row_count,
            unique_count=unique_count,
            marketplaces=marketplaces,
            common_columns=len(
                columns.intersection(target_columns)
            ),
            score=0,
        )

    candidates = discover_candidates(
        connection,
        marketplace=args.marketplace,
        expected_rows=args.expected_source_rows,
    )

    print()
    print("Normalized-source candidates")
    print("----------------------------")

    if not candidates:
        raise RuntimeError(
            "No 59-row normalized eBay relation was found."
        )

    for candidate in candidates:
        print(
            f"{candidate.qualified_name}: "
            f"rows={candidate.row_count}, "
            f"unique={candidate.unique_count}, "
            f"common_columns={candidate.common_columns}, "
            f"score={candidate.score}"
        )

    best = candidates[0]

    if (
        len(candidates) > 1
        and candidates[1].score == best.score
    ):
        raise RuntimeError(
            "Source selection is ambiguous. Rerun with "
            "--source-relation schema.table."
        )

    return best


def build_upsert(
    source: RelationCandidate,
    insert_columns: Iterable[str],
    update_columns: Iterable[str],
    marketplace: str,
) -> sql.Composed:
    """Build a protected incremental upsert."""
    insert_columns = list(insert_columns)
    update_columns = list(update_columns)

    insert_identifiers = sql.SQL(", ").join(
        sql.Identifier(column)
        for column in insert_columns
    )

    select_identifiers = sql.SQL(", ").join(
        sql.SQL("source.{}").format(
            sql.Identifier(column)
        )
        for column in insert_columns
    )

    assignments: list[sql.Composed] = []

    for column in update_columns:
        if column == "updated_at":
            assignments.append(
                sql.SQL("{} = CURRENT_TIMESTAMP").format(
                    sql.Identifier(column)
                )
            )
        else:
            assignments.append(
                sql.SQL(
                    "{} = COALESCE("
                    "EXCLUDED.{}, "
                    "target.{}"
                    ")"
                ).format(
                    sql.Identifier(column),
                    sql.Identifier(column),
                    sql.Identifier(column),
                )
            )

    update_sql = sql.SQL(", ").join(assignments)

    return sql.SQL(
        """
        INSERT INTO {target} AS target (
            {insert_columns}
        )
        SELECT
            {select_columns}
        FROM {source} AS source
        WHERE source.{marketplace_column} = %s
          AND source.{listing_id_column}
                IS NOT NULL
        ON CONFLICT ON CONSTRAINT {constraint}
        DO UPDATE SET
            {assignments}
        """
    ).format(
        target=sql.Identifier(
            TARGET_SCHEMA,
            TARGET_TABLE,
        ),
        insert_columns=insert_identifiers,
        select_columns=select_identifiers,
        source=sql.Identifier(
            source.schema,
            source.name,
        ),
        marketplace_column=sql.Identifier(
            "marketplace"
        ),
        listing_id_column=sql.Identifier(
            "listing_id"
        ),
        constraint=sql.Identifier(
            CONSTRAINT_NAME
        ),
        assignments=update_sql,
    )


def scalar(
    connection: psycopg.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> int:
    """Return one integer scalar."""
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Scalar query returned no row")

    return int(row[0])


def main() -> int:
    """Run a guarded incremental marketplace upsert."""
    args = parse_args()

    if not args.database_url:
        raise SystemExit(
            "DATABASE_URL or --database-url is required."
        )

    with psycopg.connect(
        args.database_url,
        autocommit=False,
    ) as connection:
        source = choose_source(
            connection,
            args,
        )

        if source.row_count != args.expected_source_rows:
            raise RuntimeError(
                "Unexpected source row count: "
                f"{source.row_count}"
            )

        if source.unique_count != args.expected_source_rows:
            raise RuntimeError(
                "Source keys are not unique."
            )

        if source.marketplaces != (
            args.marketplace,
        ):
            raise RuntimeError(
                "Source contains unexpected marketplaces: "
                f"{source.marketplaces}"
            )

        target_columns = relation_columns(
            connection,
            TARGET_SCHEMA,
            TARGET_TABLE,
        )

        source_columns = set(
            relation_columns(
                connection,
                source.schema,
                source.name,
            )
        )

        excluded_insert_columns = {
            "id",
            "created_at",
        }

        insert_columns = [
            column
            for column in target_columns
            if column in source_columns
            and column not in excluded_insert_columns
        ]

        required_columns = target_required_columns(
            connection
        )

        missing_required = sorted(
            required_columns.difference(
                insert_columns
            )
        )

        if missing_required:
            raise RuntimeError(
                "Source lacks required warehouse columns: "
                + ", ".join(missing_required)
            )

        update_columns = [
            column
            for column in insert_columns
            if column not in {
                "marketplace",
                "listing_id",
            }
        ]

        if not update_columns:
            raise RuntimeError(
                "No update columns are shared."
            )

        expected_union_query = sql.SQL(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    marketplace,
                    listing_id
                FROM {target}

                UNION

                SELECT
                    marketplace,
                    listing_id
                FROM {source}
                WHERE marketplace = %s
            ) AS unique_keys
            """
        ).format(
            target=sql.Identifier(
                TARGET_SCHEMA,
                TARGET_TABLE,
            ),
            source=sql.Identifier(
                source.schema,
                source.name,
            ),
        )

        with connection.cursor() as cursor:
            cursor.execute(
                expected_union_query,
                (args.marketplace,),
            )
            expected_total = int(
                cursor.fetchone()[0]
            )

        existing_marketplace_rows = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE marketplace = %s
            """,
            (args.marketplace,),
        )

        protected_rows = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE marketplace = %s
            """,
            (args.protected_marketplace,),
        )

        if (
            existing_marketplace_rows
            < args.minimum_existing_marketplace_rows
        ):
            raise RuntimeError(
                "Existing marketplace count is too low: "
                f"{existing_marketplace_rows}"
            )

        if (
            protected_rows
            != args.expected_protected_rows
        ):
            raise RuntimeError(
                "Protected marketplace count is wrong: "
                f"{protected_rows}"
            )

        print()
        print("Incremental warehouse synchronization")
        print("-------------------------------------")
        print(
            f"Source relation : "
            f"{source.qualified_name}"
        )
        print(
            f"Source rows     : "
            f"{source.row_count}"
        )
        print(
            f"Shared columns  : "
            f"{len(insert_columns)}"
        )
        print(
            f"Existing eBay   : "
            f"{existing_marketplace_rows}"
        )
        print(
            f"Protected Buyee : "
            f"{protected_rows}"
        )
        print(
            f"Expected total  : "
            f"{expected_total}"
        )

        upsert_query = build_upsert(
            source,
            insert_columns,
            update_columns,
            args.marketplace,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                LOCK TABLE warehouse.auction
                IN SHARE ROW EXCLUSIVE MODE
                """
            )

            cursor.execute(
                upsert_query,
                (args.marketplace,),
            )

            affected_rows = cursor.rowcount

        final_total = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM warehouse.auction
            """,
        )

        final_unique = scalar(
            connection,
            """
            SELECT COUNT(
                DISTINCT (
                    marketplace,
                    listing_id
                )
            )
            FROM warehouse.auction
            """,
        )

        final_marketplace_rows = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE marketplace = %s
            """,
            (args.marketplace,),
        )

        final_protected_rows = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE marketplace = %s
            """,
            (args.protected_marketplace,),
        )

        duplicate_groups = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    marketplace,
                    listing_id
                FROM warehouse.auction
                GROUP BY
                    marketplace,
                    listing_id
                HAVING COUNT(*) > 1
            ) AS duplicates
            """,
        )

        if final_total != expected_total:
            raise RuntimeError(
                "Final count does not equal the protected "
                f"union count: {final_total} != "
                f"{expected_total}"
            )

        if final_unique != final_total:
            raise RuntimeError(
                "Warehouse keys are not unique."
            )

        if (
            final_marketplace_rows
            < args.minimum_existing_marketplace_rows
        ):
            raise RuntimeError(
                "Existing eBay history was lost."
            )

        if (
            final_protected_rows
            != args.expected_protected_rows
        ):
            raise RuntimeError(
                "Protected Buyee rows changed."
            )

        if duplicate_groups != 0:
            raise RuntimeError(
                "Duplicate auction keys were created."
            )

        connection.commit()

        print()
        print("Incremental synchronization complete")
        print("------------------------------------")
        print(f"Rows upserted   : {affected_rows}")
        print(f"Total rows      : {final_total}")
        print(f"Unique rows     : {final_unique}")
        print(
            f"eBay rows       : "
            f"{final_marketplace_rows}"
        )
        print(
            f"Buyee rows      : "
            f"{final_protected_rows}"
        )
        print(
            f"Duplicate groups: "
            f"{duplicate_groups}"
        )
        print()
        print("✓ No warehouse rows were pruned.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
