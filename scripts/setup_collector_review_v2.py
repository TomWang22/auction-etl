#!/usr/bin/env python3
"""Install additive Collector Review v2 database columns."""

from __future__ import annotations

import os
import sys

import psycopg


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://auction:auction@localhost:5444/auction_warehouse",
)

STATEMENTS = (
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS in_collection boolean
    """,
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS purchase_date date
    """,
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS purchase_price numeric(14, 2)
    """,
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS purchase_currency varchar(3)
    """,
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS manual_sale_type varchar(32)
    """,
    """
    ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS manual_pressing_group varchar(160)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS
        ux_auction_collector_marketplace_listing
    ON warehouse.auction_collector (
        marketplace,
        listing_id
    )
    """,
)


def main() -> int:
    """Apply additive schema changes in one transaction."""
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    current_user
                """
            )
            database_name, database_user = cursor.fetchone()

            if database_name != "auction_warehouse":
                raise RuntimeError(
                    "Refusing to modify database "
                    f"{database_name!r}."
                )

            for statement in STATEMENTS:
                cursor.execute(statement)

        connection.commit()

    print(f"Database: {database_name}")
    print(f"User    : {database_user}")
    print()
    print("✓ Purchase tracking columns are available.")
    print("✓ Manual sale-type override is available.")
    print("✓ Manual pressing-group override is available.")
    print("✓ No table or row was removed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
