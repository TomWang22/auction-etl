#!/usr/bin/env python3
"""Add collection tracking and auction-format fields safely."""

from __future__ import annotations

import os
from collections.abc import Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://"
    "auction:auction@localhost:5444/auction_warehouse"
)
EXPECTED_DATABASE = "auction_warehouse"


def normalize_database_url(database_url: str) -> str:
    """Return a Psycopg 3 SQLAlchemy URL."""
    cleaned = database_url.strip()

    if cleaned.startswith("postgresql+psycopg://"):
        return cleaned

    if cleaned.startswith("postgresql://"):
        return cleaned.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    raise ValueError(
        "DATABASE_URL must use the PostgreSQL scheme."
    )


def verify_database(connection: Connection) -> None:
    """Refuse to modify any database except auction_warehouse."""
    row = connection.execute(
        text(
            """
            SELECT
                current_database() AS database_name,
                current_user AS database_user
            """
        )
    ).mappings().one()

    if row["database_name"] != EXPECTED_DATABASE:
        raise RuntimeError(
            "Refusing to modify database "
            f"{row['database_name']!r}."
        )

    print(
        f"Database: {row['database_name']}"
    )
    print(
        f"User    : {row['database_user']}"
    )


def upgrade_schema(connection: Connection) -> None:
    """Apply only additive, idempotent schema changes."""
    statements = (
        """
        ALTER TABLE warehouse.auction
            ADD COLUMN IF NOT EXISTS
                auction_format VARCHAR
        """,
        """
        ALTER TABLE warehouse.auction_collector
            ADD COLUMN IF NOT EXISTS
                manual_auction_format VARCHAR,
            ADD COLUMN IF NOT EXISTS
                manual_purchased BOOLEAN,
            ADD COLUMN IF NOT EXISTS
                manual_purchase_date DATE,
            ADD COLUMN IF NOT EXISTS
                manual_purchase_price NUMERIC(18, 2),
            ADD COLUMN IF NOT EXISTS
                manual_purchase_currency VARCHAR,
            ADD COLUMN IF NOT EXISTS
                manual_purchase_notes TEXT,
            ADD COLUMN IF NOT EXISTS
                purchase_updated_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS
                auto_pressing_type VARCHAR,
            ADD COLUMN IF NOT EXISTS
                manual_pressing_type VARCHAR
        """,
        """
        UPDATE warehouse.auction
        SET auction_format =
            CASE
                WHEN buyout_price_gross IS NOT NULL
                 AND COALESCE(bid_count, 0) > 0
                    THEN 'AUCTION_WITH_BUYOUT'

                WHEN buyout_price_gross IS NOT NULL
                 AND COALESCE(bid_count, 0) = 0
                    THEN 'FIXED_PRICE'

                WHEN COALESCE(bid_count, 0) > 0
                  OR start_price IS NOT NULL
                    THEN 'AUCTION'

                ELSE 'UNKNOWN'
            END
        WHERE auction_format IS NULL
           OR BTRIM(auction_format) = ''
        """,
        """
        UPDATE warehouse.auction_collector
        SET auto_pressing_type =
            CASE
                WHEN COALESCE(
                    manual_promo,
                    auto_promo,
                    false
                )
                    THEN 'PROMO_SAMPLE'

                WHEN COALESCE(
                    manual_first_press,
                    auto_first_press,
                    false
                )
                    THEN 'FIRST_PRESSING'

                WHEN COALESCE(
                    manual_reissue,
                    auto_reissue,
                    false
                )
                    THEN 'REISSUE'

                ELSE 'STANDARD'
            END
        WHERE auto_pressing_type IS NULL
           OR BTRIM(auto_pressing_type) = ''
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_auction_auction_format
        ON warehouse.auction (
            auction_format
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_auction_collector_purchased
        ON warehouse.auction_collector (
            manual_purchased
        )
        """,
    )

    for statement in statements:
        connection.execute(text(statement))


def verify_schema(connection: Connection) -> None:
    """Verify the expected recovered-row counts."""
    rows = connection.execute(
        text(
            """
            SELECT
                marketplace,
                COUNT(*) AS rows,
                COUNT(
                    DISTINCT listing_id
                ) AS unique_rows,
                COUNT(auction_format)
                    AS auction_formats
            FROM warehouse.auction
            GROUP BY marketplace
            ORDER BY marketplace
            """
        )
    ).mappings().all()

    expected = {
        "buyee": 77,
        "ebay": 698,
    }

    for row in rows:
        marketplace = str(
            row["marketplace"]
        )

        print()
        print(marketplace)
        print("-" * len(marketplace))
        print(
            f"Rows           : {row['rows']}"
        )
        print(
            f"Unique rows    : {row['unique_rows']}"
        )
        print(
            f"Auction formats: {row['auction_formats']}"
        )

        if marketplace in expected:
            required = expected[marketplace]

            if int(row["rows"]) != required:
                raise RuntimeError(
                    f"{marketplace}: expected "
                    f"{required} rows."
                )

            if int(row["unique_rows"]) != required:
                raise RuntimeError(
                    f"{marketplace}: duplicate keys detected."
                )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the schema upgrade."""
    del arguments

    database_url = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        )
    )

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
    )

    try:
        with engine.begin() as connection:
            verify_database(connection)
            upgrade_schema(connection)
            verify_schema(connection)
    finally:
        engine.dispose()

    print()
    print("✓ Collector schema upgrade completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
