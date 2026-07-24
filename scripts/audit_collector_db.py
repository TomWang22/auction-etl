from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from auction_etl.database.session import SessionLocal, engine
from auction_etl.models.raw import RawPage
from auction_etl.models.staging import Listing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only auction warehouse audit."
    )
    parser.add_argument(
        "--marketplace",
        choices=("all", "buyee", "ebay"),
        default="all",
    )
    parser.add_argument(
        "--seller",
        help="Case-insensitive seller filter.",
    )
    parser.add_argument(
        "--listing-id",
        help="Inspect one exact listing ID.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--suspicious-limit",
        type=int,
        default=50,
    )
    return parser.parse_args()


def format_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, Decimal):
        return format(value, "f")

    return str(value)


def print_table(
    title: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    print()
    print(title)
    print("-" * len(title))

    if not rows:
        print("(0 rows)")
        return

    columns = list(rows[0].keys())
    widths: dict[str, int] = {}

    for column in columns:
        widths[column] = min(
            max(
                len(column),
                *(
                    len(format_value(row.get(column)))
                    for row in rows
                ),
            ),
            60,
        )

    print(
        " | ".join(
            column.ljust(widths[column])
            for column in columns
        )
    )
    print(
        "-+-".join(
            "-" * widths[column]
            for column in columns
        )
    )

    for row in rows:
        values: list[str] = []

        for column in columns:
            value = format_value(row.get(column))

            if len(value) > widths[column]:
                value = value[: widths[column] - 1] + "…"

            values.append(value.ljust(widths[column]))

        print(" | ".join(values))

    print(f"({len(rows)} rows)")


def query_rows(
    statement: str,
    parameters: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        result = connection.execute(
            text(statement),
            dict(parameters or {}),
        ).mappings()

        return [dict(row) for row in result]


def relation_exists(
    schema: str,
    relation: str,
) -> bool:
    inspector = inspect(engine)

    return (
        relation in inspector.get_table_names(schema=schema)
        or relation in inspector.get_view_names(schema=schema)
    )


def print_database_connection() -> None:
    rows = query_rows(
        """
        SELECT
            current_database() AS database,
            current_user AS database_user,
            current_setting('server_version') AS postgresql
        """
    )

    print_table(
        "Database connection",
        rows,
    )


def print_model_tables() -> None:
    print()
    print("SQLAlchemy model tables")
    print("-----------------------")
    print(
        "RawPage:",
        f"{RawPage.__table__.schema or 'public'}."
        f"{RawPage.__table__.name}",
    )
    print(
        "Listing:",
        f"{Listing.__table__.schema or 'public'}."
        f"{Listing.__table__.name}",
    )


def print_raw_coverage() -> None:
    with SessionLocal() as session:
        rows = (
            session.query(
                RawPage.source.label("marketplace"),
                func.count(RawPage.id).label("raw_pages"),
                func.count(RawPage.parsed_at).label(
                    "parsed_pages"
                ),
                func.coalesce(
                    func.sum(RawPage.listing_count),
                    0,
                ).label("parser_listing_total"),
            )
            .group_by(RawPage.source)
            .order_by(RawPage.source)
            .all()
        )

    print_table(
        "Raw-page coverage",
        [
            {
                "marketplace": row.marketplace,
                "raw_pages": row.raw_pages,
                "parsed_pages": row.parsed_pages,
                "parser_listing_total": row.parser_listing_total,
            }
            for row in rows
        ],
    )


def print_staging_coverage() -> None:
    with SessionLocal() as session:
        rows = (
            session.query(
                Listing.marketplace.label("marketplace"),
                func.count(Listing.id).label("staging_rows"),
                func.count(
                    func.distinct(Listing.listing_id)
                ).label("unique_listing_ids"),
            )
            .group_by(Listing.marketplace)
            .order_by(Listing.marketplace)
            .all()
        )

    output = []

    for row in rows:
        output.append(
            {
                "marketplace": row.marketplace,
                "staging_rows": row.staging_rows,
                "unique_listing_ids": row.unique_listing_ids,
                "duplicate_rows": (
                    row.staging_rows
                    - row.unique_listing_ids
                ),
            }
        )

    print_table(
        "Staging coverage",
        output,
    )


def print_warehouse_coverage() -> None:
    if not relation_exists("warehouse", "auction"):
        print()
        print("Warehouse coverage")
        print("------------------")
        print("warehouse.auction does not exist.")
        return

    rows = query_rows(
        """
        SELECT
            marketplace,
            COUNT(*) AS warehouse_rows,
            COUNT(DISTINCT listing_id)
                AS unique_listing_ids,
            COUNT(ended_at) AS ended_dates,
            COUNT(start_price) AS starting_prices,
            COUNT(gross_price) AS gross_prices
        FROM warehouse.auction
        GROUP BY marketplace
        ORDER BY marketplace
        """
    )

    print_table(
        "Warehouse coverage",
        rows,
    )


def print_detail_coverage() -> None:
    if not relation_exists(
        "warehouse",
        "auction_detail",
    ):
        return

    rows = query_rows(
        """
        SELECT
            marketplace,
            COUNT(*) AS detail_rows,
            COUNT(DISTINCT listing_id)
                AS unique_listing_ids,
            COUNT(started_at) AS opening_dates,
            COUNT(condition_text)
                AS detail_conditions,
            COUNT(auction_id) AS auction_ids
        FROM warehouse.auction_detail
        GROUP BY marketplace
        ORDER BY marketplace
        """
    )

    print_table(
        "Detail-page coverage",
        rows,
    )


def print_duplicate_checks() -> None:
    with SessionLocal() as session:
        staging_duplicates = (
            session.query(
                Listing.marketplace,
                Listing.listing_id,
                func.count(Listing.id).label("copies"),
            )
            .group_by(
                Listing.marketplace,
                Listing.listing_id,
            )
            .having(func.count(Listing.id) > 1)
            .order_by(
                func.count(Listing.id).desc(),
                Listing.marketplace,
                Listing.listing_id,
            )
            .limit(100)
            .all()
        )

    print_table(
        "Staging duplicate keys",
        [
            {
                "marketplace": row.marketplace,
                "listing_id": row.listing_id,
                "copies": row.copies,
            }
            for row in staging_duplicates
        ],
    )

    for relation, title in (
        ("auction", "Warehouse duplicate keys"),
        (
            "auction_collector",
            "Collector duplicate keys",
        ),
        (
            "auction_collector_effective",
            "Effective-view duplicate keys",
        ),
    ):
        if not relation_exists("warehouse", relation):
            continue

        rows = query_rows(
            f"""
            SELECT
                marketplace,
                listing_id,
                COUNT(*) AS copies
            FROM warehouse.{relation}
            GROUP BY marketplace, listing_id
            HAVING COUNT(*) > 1
            ORDER BY
                copies DESC,
                marketplace,
                listing_id
            LIMIT 100
            """
        )

        print_table(title, rows)


def print_collector_coverage() -> None:
    if not relation_exists(
        "warehouse",
        "auction_collector_effective",
    ):
        return

    rows = query_rows(
        """
        SELECT
            marketplace,
            COUNT(*) AS rows,
            COUNT(effective_catalog_number)
                AS catalog_numbers,
            COUNT(effective_region) AS regions,
            COUNT(effective_media_type)
                AS media_types,
            COUNT(effective_disc_count)
                AS disc_counts,
            COUNT(*) FILTER (
                WHERE effective_obi IS NOT NULL
            ) AS obi_values,
            COUNT(*) FILTER (
                WHERE effective_insert_present
                    IS NOT NULL
            ) AS insert_values,
            COUNT(*) FILTER (
                WHERE effective_poster_present
                    IS NOT NULL
            ) AS poster_values,
            COUNT(*) FILTER (
                WHERE effective_bulk_lot
            ) AS bulk_lots,
            COUNT(effective_importance_score)
                AS scores,
            COUNT(effective_verdict) AS verdicts
        FROM warehouse.auction_collector_effective
        GROUP BY marketplace
        ORDER BY marketplace
        """
    )

    print_table(
        "Collector classification coverage",
        rows,
    )

    rows = query_rows(
        """
        SELECT
            marketplace,
            effective_verdict,
            COUNT(*) AS listings
        FROM warehouse.auction_collector_effective
        GROUP BY
            marketplace,
            effective_verdict
        ORDER BY
            marketplace,
            listings DESC,
            effective_verdict
        """
    )

    print_table(
        "Collector verdict distribution",
        rows,
    )


def print_manual_overrides() -> None:
    if not relation_exists(
        "warehouse",
        "auction_collector",
    ):
        return

    rows = query_rows(
        """
        SELECT
            marketplace,
            COUNT(*) FILTER (
                WHERE manual_catalog_number
                    IS NOT NULL
            ) AS manual_catalogs,
            COUNT(*) FILTER (
                WHERE manual_region IS NOT NULL
            ) AS manual_regions,
            COUNT(*) FILTER (
                WHERE manual_media_type
                    IS NOT NULL
            ) AS manual_media,
            COUNT(*) FILTER (
                WHERE manual_disc_count
                    IS NOT NULL
            ) AS manual_disc_counts,
            COUNT(*) FILTER (
                WHERE manual_obi IS NOT NULL
            ) AS manual_obi,
            COUNT(*) FILTER (
                WHERE manual_importance_score
                    IS NOT NULL
            ) AS manual_scores,
            COUNT(*) FILTER (
                WHERE manual_verdict
                    IS NOT NULL
            ) AS manual_verdicts,
            COUNT(*) FILTER (
                WHERE manual_collector_notes
                    IS NOT NULL
            ) AS manual_notes
        FROM warehouse.auction_collector
        GROUP BY marketplace
        ORDER BY marketplace
        """
    )

    print_table(
        "Manual override coverage",
        rows,
    )


def build_filter(
    marketplace: str,
    seller: str | None,
    listing_id: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    parameters: dict[str, Any] = {}

    if marketplace != "all":
        clauses.append(
            "a.marketplace = :marketplace"
        )
        parameters["marketplace"] = marketplace

    if seller:
        clauses.append(
            "COALESCE(a.seller, '') ILIKE :seller"
        )
        parameters["seller"] = f"%{seller}%"

    if listing_id:
        clauses.append(
            "a.listing_id = :listing_id"
        )
        parameters["listing_id"] = listing_id

    if not clauses:
        return "", parameters

    return (
        "WHERE " + " AND ".join(clauses),
        parameters,
    )


def print_filtered_rows(
    marketplace: str,
    seller: str | None,
    listing_id: str | None,
    limit: int,
) -> None:
    if not relation_exists(
        "warehouse",
        "auction_collector_effective",
    ):
        return

    where_clause, parameters = build_filter(
        marketplace,
        seller,
        listing_id,
    )
    parameters["limit"] = limit

    rows = query_rows(
        f"""
        SELECT
            a.marketplace,
            a.listing_id,
            a.ended_at AT TIME ZONE
                'America/New_York'
                AS ended_new_york,
            a.seller,
            a.effective_media_type
                AS media_type,
            a.effective_disc_count AS discs,
            a.effective_bulk_lot AS bulk,
            a.effective_catalog_number
                AS catalog_number,
            a.effective_region AS region,
            a.effective_obi AS obi,
            a.start_price,
            a.final_price,
            a.tax_amount,
            a.gross_price,
            a.currency,
            a.bid_count,
            a.effective_importance_score
                AS score,
            a.effective_verdict AS verdict,
            LEFT(a.title, 100) AS title
        FROM warehouse.auction_collector_effective
            AS a
        {where_clause}
        ORDER BY
            a.ended_at DESC NULLS LAST,
            a.id DESC
        LIMIT :limit
        """,
        parameters,
    )

    print_table(
        "Newest filtered collector rows",
        rows,
    )


def print_seller_history(
    marketplace: str,
    seller: str | None,
    limit: int,
) -> None:
    if not relation_exists(
        "warehouse",
        "auction_collector_effective",
    ):
        return

    clauses = [
        "NULLIF(BTRIM(a.seller), '') IS NOT NULL"
    ]
    parameters: dict[str, Any] = {
        "limit": limit,
    }

    if marketplace != "all":
        clauses.append(
            "a.marketplace = :marketplace"
        )
        parameters["marketplace"] = marketplace

    if seller:
        clauses.append(
            "a.seller ILIKE :seller"
        )
        parameters["seller"] = f"%{seller}%"

    rows = query_rows(
        f"""
        SELECT
            a.marketplace,
            a.seller,
            COUNT(*) AS sales,
            MIN(a.ended_at) AT TIME ZONE
                'America/New_York'
                AS first_sale_new_york,
            MAX(a.ended_at) AT TIME ZONE
                'America/New_York'
                AS last_sale_new_york,
            ROUND(
                AVG(a.gross_price),
                2
            ) AS average_gross,
            MAX(a.gross_price)
                AS maximum_gross,
            COUNT(*) FILTER (
                WHERE a.effective_bulk_lot
            ) AS bulk_sales
        FROM warehouse.auction_collector_effective
            AS a
        WHERE {" AND ".join(clauses)}
        GROUP BY
            a.marketplace,
            a.seller
        ORDER BY
            sales DESC,
            last_sale_new_york DESC NULLS LAST
        LIMIT :limit
        """,
        parameters,
    )

    print_table(
        "Seller history",
        rows,
    )


def print_suspicious_rows(
    marketplace: str,
    seller: str | None,
    listing_id: str | None,
    limit: int,
) -> None:
    if not relation_exists(
        "warehouse",
        "auction_collector_effective",
    ):
        return

    filter_clause, parameters = build_filter(
        marketplace,
        seller,
        listing_id,
    )

    review_condition = """
        (
            a.final_price IS NULL
            OR a.gross_price IS NULL
            OR a.final_price < 0
            OR a.gross_price < 0
            OR (
                a.start_price IS NOT NULL
                AND a.start_price < 0
            )
            OR (
                a.tax_amount IS NOT NULL
                AND a.final_price IS NOT NULL
                AND a.gross_price IS NOT NULL
                AND ABS(
                    a.gross_price
                    - a.final_price
                    - a.tax_amount
                ) > 1.01
            )
            OR (
                a.effective_media_type IS NULL
                AND COALESCE(
                    a.effective_bulk_lot,
                    FALSE
                ) = FALSE
            )
            OR (
                a.effective_disc_count IS NOT NULL
                AND a.effective_disc_count <= 0
            )
            OR a.ended_at IS NULL
        )
    """

    if filter_clause:
        where_clause = (
            filter_clause
            + " AND "
            + review_condition
        )
    else:
        where_clause = (
            "WHERE " + review_condition
        )

    parameters["limit"] = limit

    rows = query_rows(
        f"""
        SELECT
            a.marketplace,
            a.listing_id,
            a.ended_at AT TIME ZONE
                'America/New_York'
                AS ended_new_york,
            a.seller,
            a.effective_media_type
                AS media_type,
            a.effective_disc_count AS discs,
            a.effective_bulk_lot AS bulk,
            a.final_price,
            a.tax_rate,
            a.tax_amount,
            a.gross_price,
            a.currency,
            LEFT(a.title, 100) AS title
        FROM warehouse.auction_collector_effective
            AS a
        {where_clause}
        ORDER BY
            a.ended_at DESC NULLS LAST,
            a.id DESC
        LIMIT :limit
        """,
        parameters,
    )

    print_table(
        "Rows requiring classification review",
        rows,
    )


def main() -> int:
    args = parse_args()

    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")

    if args.suspicious_limit < 1:
        raise SystemExit(
            "--suspicious-limit must be at least 1."
        )

    print_database_connection()
    print_model_tables()
    print_raw_coverage()
    print_staging_coverage()
    print_warehouse_coverage()
    print_detail_coverage()
    print_duplicate_checks()
    print_collector_coverage()
    print_manual_overrides()

    print_filtered_rows(
        marketplace=args.marketplace,
        seller=args.seller,
        listing_id=args.listing_id,
        limit=args.limit,
    )

    print_seller_history(
        marketplace=args.marketplace,
        seller=args.seller,
        limit=args.limit,
    )

    print_suspicious_rows(
        marketplace=args.marketplace,
        seller=args.seller,
        listing_id=args.listing_id,
        limit=args.suspicious_limit,
    )

    print()
    print("Audit complete.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SQLAlchemyError as exc:
        print()
        print("DATABASE AUDIT ERROR")
        print("--------------------")
        print(exc)
        raise SystemExit(1)
