#!/usr/bin/env python3
"""Backfill Buyee USD values from the archived displayed conversion."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_DATABASE_URL = (
    "postgresql://auction:auction@"
    "127.0.0.1:5544/auction_warehouse"
)

DISPLAYED_USD_PATTERN = re.compile(
    r"\(US\$\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\)",
    re.IGNORECASE,
)

CENT = Decimal("0.01")
RATE_QUANTUM = Decimal("0.000000000001")


@dataclass(frozen=True, slots=True)
class Conversion:
    """One archived Buyee conversion result."""

    listing_id: str
    rate_date: date
    rate_to_usd: Decimal
    start_price_usd: Decimal | None
    final_price_usd: Decimal | None
    shipping_price_usd: Decimal | None
    tax_usd: Decimal | None
    gross_price_usd: Decimal
    landed_price_usd: Decimal
    current_price_usd: Decimal | None
    buyout_price_usd: Decimal | None


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Backfill recent Buyee USD values using the US-dollar "
            "amount displayed in the captured Buyee watchlist HTML."
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
        help="Persist the derived conversion values.",
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


def decimal_or_none(
    value: Any,
) -> Decimal | None:
    """Return a Decimal for populated numeric values."""
    if value is None:
        return None

    return Decimal(
        str(value)
    )


def money(
    value: Decimal | None,
    rate: Decimal,
) -> Decimal | None:
    """Convert one local amount into rounded US dollars."""
    if value is None:
        return None

    return (
        value
        * rate
    ).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def displayed_usd(
    payload: Any,
) -> Decimal:
    """Extract the displayed US-dollar gross amount."""
    match = DISPLAYED_USD_PATTERN.search(
        str(payload or "")
    )

    if match is None:
        raise ValueError(
            "Captured payload contains no displayed US-dollar amount."
        )

    return Decimal(
        match.group("amount").replace(
            ",",
            "",
        )
    )


def conversion_from_row(
    row: dict[str, Any],
) -> Conversion:
    """Derive all normalized USD values for one Buyee row."""
    gross_price = decimal_or_none(
        row.get("gross_price")
    )

    if gross_price is None or gross_price <= 0:
        raise ValueError(
            "Cannot calculate FX without a positive gross price "
            f"for {row['listing_id']}."
        )

    gross_usd = displayed_usd(
        row.get("payload")
    )

    rate = (
        gross_usd
        / gross_price
    ).quantize(
        RATE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )

    shipping_usd = money(
        decimal_or_none(
            row.get("shipping_price")
        ),
        rate,
    )

    landed_usd = gross_usd + (
        shipping_usd
        or Decimal("0")
    )

    return Conversion(
        listing_id=str(
            row["listing_id"]
        ),
        rate_date=row[
            "staging_created_at"
        ].date(),
        rate_to_usd=rate,
        start_price_usd=money(
            decimal_or_none(
                row.get("start_price")
            ),
            rate,
        ),
        final_price_usd=money(
            decimal_or_none(
                row.get("final_price")
            ),
            rate,
        ),
        shipping_price_usd=shipping_usd,
        tax_usd=money(
            decimal_or_none(
                row.get("tax_amount")
            ),
            rate,
        ),
        gross_price_usd=gross_usd,
        landed_price_usd=landed_usd,
        current_price_usd=money(
            decimal_or_none(
                row.get(
                    "current_price_gross"
                )
            ),
            rate,
        ),
        buyout_price_usd=money(
            decimal_or_none(
                row.get(
                    "buyout_price_gross"
                )
            ),
            rate,
        ),
    )


def main() -> int:
    """Backfill and verify recent Buyee conversions."""
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
                SELECT DISTINCT ON (
                    auction.marketplace,
                    auction.listing_id
                )
                    auction.listing_id,
                    auction.start_price,
                    auction.final_price,
                    auction.shipping_price,
                    auction.tax_amount,
                    auction.gross_price,
                    auction.current_price_gross,
                    auction.buyout_price_gross,
                    staging.payload,
                    staging.created_at
                        AS staging_created_at
                FROM warehouse.auction AS auction
                JOIN system.auction_ingestion_identity
                    AS audit
                  ON audit.marketplace =
                     auction.marketplace
                 AND audit.listing_id =
                     auction.listing_id
                JOIN staging.listing AS staging
                  ON staging.marketplace =
                     auction.marketplace
                 AND staging.listing_id =
                     auction.listing_id
                WHERE auction.marketplace = 'buyee'
                  AND audit.first_seen_source =
                      'new-only-export'
                ORDER BY
                    auction.marketplace,
                    auction.listing_id,
                    staging.created_at DESC,
                    staging.id DESC
                """
            ).fetchall()
        )

        conversions = [
            conversion_from_row(
                dict(row)
            )
            for row in rows
        ]

        if len(conversions) != 61:
            raise RuntimeError(
                "Expected exactly 61 recent Buyee conversions; "
                f"found {len(conversions)}."
            )

        if arguments.apply:
            for item in conversions:
                connection.execute(
                    """
                    UPDATE warehouse.auction
                    SET
                        fx_rate_to_usd = %s,
                        fx_rate_date = %s,
                        start_price_usd = %s,
                        final_price_usd = %s,
                        shipping_price_usd = %s,
                        tax_usd = %s,
                        gross_price_usd = %s,
                        landed_price_usd = %s,
                        current_price_usd = %s,
                        buyout_price_usd = %s
                    WHERE marketplace = 'buyee'
                      AND listing_id = %s
                    """,
                    (
                        item.rate_to_usd,
                        item.rate_date,
                        item.start_price_usd,
                        item.final_price_usd,
                        item.shipping_price_usd,
                        item.tax_usd,
                        item.gross_price_usd,
                        item.landed_price_usd,
                        item.current_price_usd,
                        item.buyout_price_usd,
                        item.listing_id,
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
                COUNT(*) AS rows,
                COUNT(fx_rate_to_usd) AS rates,
                COUNT(fx_rate_date) AS rate_dates,
                COUNT(final_price_usd) AS final_usd,
                COUNT(gross_price_usd) AS gross_usd
            FROM warehouse.auction AS auction
            JOIN system.auction_ingestion_identity
                AS audit
              ON audit.marketplace =
                 auction.marketplace
             AND audit.listing_id =
                 auction.listing_id
            WHERE auction.marketplace = 'buyee'
              AND audit.first_seen_source =
                  'new-only-export'
            """
        ).fetchone()

        verification.rollback()

    print()
    print("Buyee displayed-USD backfill")
    print("============================")
    print(
        f"Mode       : "
        f"{'APPLY' if arguments.apply else 'DRY RUN'}"
    )
    print(
        f"Candidates : {len(conversions)}"
    )
    print(
        f"FX rates   : {coverage['rates']}"
    )
    print(
        f"Rate dates : {coverage['rate_dates']}"
    )
    print(
        f"Final USD  : {coverage['final_usd']}"
    )
    print(
        f"Gross USD  : {coverage['gross_usd']}"
    )

    if arguments.apply:
        expected = int(
            coverage["rows"]
        )

        for column in (
            "rates",
            "rate_dates",
            "final_usd",
            "gross_usd",
        ):
            if int(coverage[column]) != expected:
                raise RuntimeError(
                    "Buyee conversion coverage is incomplete: "
                    f"{column}={coverage[column]}, "
                    f"expected={expected}."
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
