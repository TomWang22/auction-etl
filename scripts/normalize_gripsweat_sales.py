#!/usr/bin/env python3
"""Normalize archived Gripsweat sale fields without creating auction duplicates."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from auction_etl.reporting.main_review_integration import (
    gripsweat_original_listing_id,
    parse_gripsweat_sold_at,
    parse_gripsweat_title,
)


DEFAULT_DATABASE_URL = (
    "postgresql://auction:auction@"
    "127.0.0.1:5544/auction_warehouse"
)


@dataclass(frozen=True, slots=True)
class NormalizedSale:
    """Derived durable fields for one Gripsweat sale."""

    row_id: int
    title: str
    sold_at: datetime
    sold_at_text: str
    original_marketplace: str
    original_listing_id: str


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Normalize existing Gripsweat archive rows and report "
            "exact native-eBay duplicates."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist missing normalized fields.",
    )
    return parser.parse_args()


def normalize_database_url(value: str) -> str:
    """Convert SQLAlchemy PostgreSQL URLs into Psycopg URLs."""
    normalized = value.strip()

    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ):
        if normalized.startswith(prefix):
            return (
                "postgresql://"
                + normalized[len(prefix):]
            )

    return normalized


def sold_at_text(raw_text: Any) -> str:
    """Return the trailing archived sale-date text."""
    parsed = parse_gripsweat_sold_at(
        raw_text
    )

    if parsed is None or str(parsed) == "NaT":
        return ""

    return parsed.strftime(
        "%b %-d, %Y"
    )


def normalize_row(
    row: dict[str, Any],
) -> NormalizedSale:
    """Derive all required normalized fields."""
    listing_id = (
        str(
            row.get(
                "original_listing_id"
            )
            or ""
        ).strip()
        or gripsweat_original_listing_id(
            row.get("gripsweat_url")
        )
    )

    if not listing_id:
        raise ValueError(
            "Could not derive an original listing ID "
            f"for Gripsweat row {row['id']}."
        )

    parsed_date = parse_gripsweat_sold_at(
        row.get("raw_text")
    )

    if str(parsed_date) == "NaT":
        raise ValueError(
            "Could not derive sold_at "
            f"for Gripsweat row {row['id']}."
        )

    parsed_title = parse_gripsweat_title(
        row.get("title"),
        row.get("raw_text"),
    )

    if not parsed_title:
        raise ValueError(
            "Could not derive title "
            f"for Gripsweat row {row['id']}."
        )

    date_text = str(
        row.get("sold_at_text")
        or ""
    ).strip()

    if not date_text:
        date_text = parsed_date.strftime(
            "%b %d, %Y"
        ).replace(" 0", " ")

    return NormalizedSale(
        row_id=int(row["id"]),
        title=parsed_title,
        sold_at=parsed_date.to_pydatetime(),
        sold_at_text=date_text,
        original_marketplace=(
            str(
                row.get(
                    "original_marketplace"
                )
                or "ebay"
            ).strip()
            or "ebay"
        ),
        original_listing_id=listing_id,
    )


def main() -> int:
    """Normalize Gripsweat rows and report deduplication counts."""
    arguments = parse_args()
    database_url = normalize_database_url(
        arguments.database_url
    )

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        database_name = connection.execute(
            "SELECT current_database()"
        ).fetchone()["current_database"]

        if database_name != "auction_warehouse":
            raise RuntimeError(
                "Refusing unexpected database: "
                f"{database_name}"
            )

        rows = list(
            connection.execute(
                """
                SELECT *
                FROM warehouse.gripsweat_sale
                ORDER BY id
                """
            ).fetchall()
        )

        normalized = [
            normalize_row(
                dict(row)
            )
            for row in rows
        ]

        if arguments.apply:
            for sale in normalized:
                connection.execute(
                    """
                    UPDATE warehouse.gripsweat_sale
                    SET
                        title = COALESCE(
                            NULLIF(BTRIM(title), ''),
                            %s
                        ),
                        sold_at = COALESCE(
                            sold_at,
                            %s
                        ),
                        sold_at_text = COALESCE(
                            NULLIF(BTRIM(sold_at_text), ''),
                            %s
                        ),
                        original_marketplace = COALESCE(
                            NULLIF(
                                BTRIM(original_marketplace),
                                ''
                            ),
                            %s
                        ),
                        original_listing_id = COALESCE(
                            NULLIF(
                                BTRIM(original_listing_id),
                                ''
                            ),
                            %s
                        ),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        sale.title,
                        sale.sold_at.date(),
                        sale.sold_at_text,
                        sale.original_marketplace,
                        sale.original_listing_id,
                        sale.row_id,
                    ),
                )

            connection.commit()
        else:
            connection.rollback()

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as verification:
        coverage = verification.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE title IS NOT NULL
                      AND BTRIM(title) <> ''
                ) AS titles,
                COUNT(sold_at) AS sold_dates,
                COUNT(*) FILTER (
                    WHERE original_marketplace = 'ebay'
                      AND original_listing_id IS NOT NULL
                      AND BTRIM(original_listing_id) <> ''
                ) AS original_ids,
                COUNT(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM warehouse.auction AS auction
                        WHERE auction.marketplace = 'ebay'
                          AND auction.listing_id =
                              warehouse.gripsweat_sale
                              .original_listing_id
                    )
                ) AS native_ebay_duplicates,
                COUNT(*) FILTER (
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM warehouse.auction AS auction
                        WHERE auction.marketplace = 'ebay'
                          AND auction.listing_id =
                              warehouse.gripsweat_sale
                              .original_listing_id
                    )
                ) AS gripsweat_only
            FROM warehouse.gripsweat_sale
            """
        ).fetchone()

        verification.rollback()

    print()
    print("Gripsweat normalization")
    print("=======================")
    print(
        f"Mode                  : "
        f"{'APPLY' if arguments.apply else 'DRY RUN'}"
    )
    print(
        f"Rows                  : {len(normalized)}"
    )
    print(
        f"Normalized titles     : {coverage['titles']}"
    )
    print(
        f"Normalized sold dates : {coverage['sold_dates']}"
    )
    print(
        f"Original eBay IDs     : {coverage['original_ids']}"
    )
    print(
        "Native eBay duplicates: "
        f"{coverage['native_ebay_duplicates']}"
    )
    print(
        f"Gripsweat-only rows   : "
        f"{coverage['gripsweat_only']}"
    )

    if arguments.apply:
        expected = (
            int(coverage["total_rows"]),
            int(coverage["titles"]),
            int(coverage["sold_dates"]),
            int(coverage["original_ids"]),
        )

        if len(set(expected)) != 1:
            raise RuntimeError(
                "Gripsweat normalization coverage is incomplete: "
                f"{expected}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
