#!/usr/bin/env python3
"""Persist local-currency and USD auction values.

The updater uses a retained JPY-to-USD rate from the Buyee recovery
export unless an explicit rate is supplied. It performs every SQL
command separately for Psycopg 3 compatibility.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://"
    "auction:auction@localhost:5444/auction_warehouse"
)
DEFAULT_SOURCE_CSV = Path(
    "recovery-input/auction_report_buyee_no_bulk.csv"
)
DEFAULT_EXPECTED_DATABASE_NAME = "auction_warehouse"
DEFAULT_EXPECTED_DATABASE_USER = "auction"


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """One retained exchange-rate observation."""

    rate: Decimal
    rate_date: date
    source: str


def parse_arguments(
    arguments: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Store persistent USD values for Auction ETL listings."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        ),
        help="SQLAlchemy PostgreSQL URL.",
    )
    parser.add_argument(
        "--expected-database-name",
        default=os.getenv(
            "AUCTION_EXPECTED_DATABASE_NAME",
            DEFAULT_EXPECTED_DATABASE_NAME,
        ),
        help="Required current_database() identity.",
    )
    parser.add_argument(
        "--expected-database-user",
        default=os.getenv(
            "AUCTION_EXPECTED_DATABASE_USER",
            DEFAULT_EXPECTED_DATABASE_USER,
        ),
        help="Required current_user identity.",
    )
    parser.add_argument(
        "--source-csv",
        type=Path,
        default=DEFAULT_SOURCE_CSV,
        help="Retained Buyee CSV containing fx_rate_to_usd.",
    )
    parser.add_argument(
        "--rate",
        type=Decimal,
        help="Explicit JPY-to-USD multiplier.",
    )
    parser.add_argument(
        "--rate-date",
        type=date.fromisoformat,
        help="Explicit ISO rate date.",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help=(
            "Accepted for compatibility. This updater never "
            "uses the network."
        ),
    )

    return parser.parse_args(arguments)


def normalize_database_url(database_url: str) -> str:
    """Force SQLAlchemy to use Psycopg 3."""
    cleaned = database_url.strip()

    if cleaned.startswith(
        "postgresql+psycopg://"
    ):
        return cleaned

    if cleaned.startswith(
        "postgresql://"
    ):
        return cleaned.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    raise ValueError(
        "Database URL must use the PostgreSQL scheme."
    )


def parse_decimal(value: object) -> Decimal | None:
    """Parse one positive decimal value."""
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None

    if not parsed.is_finite() or parsed <= 0:
        return None

    return parsed


def parse_date(value: object) -> date | None:
    """Parse one ISO date or timestamp."""
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    try:
        return date.fromisoformat(
            cleaned[:10]
        )
    except ValueError:
        return None


def load_retained_rate(
    source_csv: Path,
) -> ExchangeRate:
    """Load the most frequently retained positive JPY rate."""
    if not source_csv.is_file():
        raise FileNotFoundError(
            f"Exchange-rate source is missing: {source_csv}"
        )

    rate_counts: Counter[Decimal] = Counter()
    dates_by_rate: defaultdict[
        Decimal,
        list[date],
    ] = defaultdict(list)

    with source_csv.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as input_file:
        reader = csv.DictReader(input_file)

        required = {
            "fx_rate_to_usd",
        }

        missing = required - set(
            reader.fieldnames or []
        )

        if missing:
            raise ValueError(
                "Exchange-rate source is missing columns: "
                + ", ".join(sorted(missing))
            )

        for row in reader:
            rate = parse_decimal(
                row.get("fx_rate_to_usd")
            )

            if rate is None:
                continue

            rate_counts[rate] += 1

            observed_date = parse_date(
                row.get("fx_rate_date")
            )

            if observed_date is not None:
                dates_by_rate[rate].append(
                    observed_date
                )

    if not rate_counts:
        raise ValueError(
            "No positive fx_rate_to_usd values were found."
        )

    selected_rate, _ = rate_counts.most_common(
        1
    )[0]

    observed_dates = dates_by_rate[
        selected_rate
    ]

    selected_date = (
        max(observed_dates)
        if observed_dates
        else date.today()
    )

    return ExchangeRate(
        rate=selected_rate,
        rate_date=selected_date,
        source=str(source_csv),
    )


def load_persisted_rate(
    connection: Connection,
) -> ExchangeRate | None:
    """Load the newest positive JPY/USD rate already stored in PostgreSQL."""
    row = connection.execute(
        text(
            """
            SELECT
                fx_rate_to_usd,
                fx_rate_date,
                COUNT(*) AS usage_count
            FROM warehouse.auction
            WHERE marketplace = 'buyee'
              AND fx_rate_to_usd IS NOT NULL
              AND fx_rate_to_usd > 0
            GROUP BY
                fx_rate_to_usd,
                fx_rate_date
            ORDER BY
                fx_rate_date DESC NULLS LAST,
                COUNT(*) DESC,
                fx_rate_to_usd DESC
            LIMIT 1
            """
        )
    ).mappings().one_or_none()

    if row is None:
        return None

    rate = parse_decimal(
        row["fx_rate_to_usd"]
    )

    if rate is None:
        return None

    observed_date = parse_date(
        row["fx_rate_date"]
    )

    return ExchangeRate(
        rate=rate,
        rate_date=(
            observed_date
            if observed_date is not None
            else date.today()
        ),
        source="warehouse.auction",
    )


def resolve_exchange_rate(
    *,
    explicit_rate: Decimal | None,
    explicit_date: date | None,
    source_csv: Path,
) -> ExchangeRate:
    """Resolve either explicit or retained rate values."""
    if explicit_rate is None:
        retained = load_retained_rate(
            source_csv
        )

        if explicit_date is None:
            return retained

        return ExchangeRate(
            rate=retained.rate,
            rate_date=explicit_date,
            source=retained.source,
        )

    if (
        not explicit_rate.is_finite()
        or explicit_rate <= 0
    ):
        raise ValueError(
            "Explicit rate must be a positive finite value."
        )

    return ExchangeRate(
        rate=explicit_rate,
        rate_date=(
            explicit_date
            if explicit_date is not None
            else date.today()
        ),
        source="command line",
    )


def verify_database(
    connection: Connection,
    *,
    expected_database_name: str = DEFAULT_EXPECTED_DATABASE_NAME,
    expected_database_user: str = DEFAULT_EXPECTED_DATABASE_USER,
) -> None:
    """Refuse to update an unexpected database identity."""
    expected_name = expected_database_name.strip()
    expected_user = expected_database_user.strip()

    if not expected_name:
        raise ValueError(
            "Expected database name must not be empty."
        )

    if not expected_user:
        raise ValueError(
            "Expected database user must not be empty."
        )

    row = connection.execute(
        text(
            """
            SELECT
                current_database() AS database_name,
                current_user AS database_user
            """
        )
    ).mappings().one()

    database_name = str(
        row["database_name"]
    )
    database_user = str(
        row["database_user"]
    )

    if database_name != expected_name:
        raise RuntimeError(
            "Refusing to update database "
            f"{database_name!r}; expected "
            f"{expected_name!r}."
        )

    if database_user != expected_user:
        raise RuntimeError(
            "Refusing to update as database user "
            f"{database_user!r}; expected "
            f"{expected_user!r}."
        )

    print(
        f"Database: {database_name}"
    )
    print(
        f"User    : {database_user}"
    )


def ensure_columns(
    connection: Connection,
) -> None:
    """Create only missing additive currency columns."""
    columns = {
        "fx_rate_to_usd": "NUMERIC(18, 8)",
        "fx_rate_date": "DATE",
        "start_price_usd": "NUMERIC(18, 2)",
        "final_price_usd": "NUMERIC(18, 2)",
        "shipping_price_usd": "NUMERIC(18, 2)",
        "tax_usd": "NUMERIC(18, 2)",
        "gross_price_usd": "NUMERIC(18, 2)",
        "landed_price_usd": "NUMERIC(18, 2)",
        "current_price_gross": "NUMERIC(18, 2)",
        "buyout_price_gross": "NUMERIC(18, 2)",
        "current_price_usd": "NUMERIC(18, 2)",
        "buyout_price_usd": "NUMERIC(18, 2)",
    }

    for column_name, column_type in columns.items():
        connection.execute(
            text(
                f"""
                ALTER TABLE warehouse.auction
                ADD COLUMN IF NOT EXISTS
                    {column_name} {column_type}
                """
            )
        )


def apply_rate(
    connection: Connection,
    exchange_rate: ExchangeRate,
) -> tuple[int, int]:
    """Store exchange rates and calculated USD columns."""
    parameters = {
        "jpy_rate": exchange_rate.rate,
        "rate_date": exchange_rate.rate_date,
    }

    rate_result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET
                fx_rate_to_usd =
                    CASE
                        WHEN UPPER(currency) = 'USD'
                            THEN 1
                        WHEN UPPER(currency) = 'JPY'
                            THEN :jpy_rate
                        ELSE fx_rate_to_usd
                    END,
                fx_rate_date =
                    CASE
                        WHEN UPPER(currency) IN (
                            'USD',
                            'JPY'
                        )
                            THEN :rate_date
                        ELSE fx_rate_date
                    END
            WHERE UPPER(
                COALESCE(currency, '')
            ) IN (
                'USD',
                'JPY'
            )
            """
        ),
        parameters,
    )

    value_result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET
                start_price_usd =
                    CASE
                        WHEN start_price IS NULL
                            THEN NULL
                        ELSE ROUND(
                            start_price
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                final_price_usd =
                    CASE
                        WHEN final_price IS NULL
                            THEN NULL
                        ELSE ROUND(
                            final_price
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                shipping_price_usd =
                    CASE
                        WHEN shipping_price IS NULL
                            THEN NULL
                        ELSE ROUND(
                            shipping_price
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                tax_usd =
                    CASE
                        WHEN tax_amount IS NULL
                            THEN NULL
                        ELSE ROUND(
                            tax_amount
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                gross_price_usd =
                    CASE
                        WHEN gross_price IS NULL
                            THEN NULL
                        ELSE ROUND(
                            gross_price
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                landed_price_usd =
                    CASE
                        WHEN gross_price IS NULL
                         AND shipping_price IS NULL
                            THEN NULL
                        ELSE ROUND(
                            (
                                COALESCE(
                                    gross_price,
                                    0
                                )
                                + COALESCE(
                                    shipping_price,
                                    0
                                )
                            )
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                current_price_usd =
                    CASE
                        WHEN current_price_gross
                            IS NULL
                            THEN NULL
                        ELSE ROUND(
                            current_price_gross
                            * fx_rate_to_usd,
                            2
                        )
                    END,

                buyout_price_usd =
                    CASE
                        WHEN buyout_price_gross
                            IS NULL
                            THEN NULL
                        ELSE ROUND(
                            buyout_price_gross
                            * fx_rate_to_usd,
                            2
                        )
                    END
            WHERE fx_rate_to_usd IS NOT NULL
            """
        )
    )

    return (
        int(rate_result.rowcount or 0),
        int(value_result.rowcount or 0),
    )


def verify_results(
    connection: Connection,
) -> None:
    """Validate auction-key uniqueness and dynamic conversion coverage."""

    totals = connection.execute(
        text(
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT (
                        marketplace,
                        listing_id
                    )
                ) AS unique_rows
            FROM warehouse.auction
            """
        )
    ).mappings().one()

    if (
        int(totals["total_rows"]) <= 0
        or int(totals["unique_rows"])
        != int(totals["total_rows"])
    ):
        raise RuntimeError(
            "Expected a non-empty auction table with unique keys; "
            f"found {totals['total_rows']} rows and "
            f"{totals['unique_rows']} keys."
        )

    marketplace_rows = connection.execute(
        text(
            """
            SELECT
                marketplace,
                COUNT(*) AS rows,
                COUNT(fx_rate_to_usd)
                    AS fx_rates,
                COUNT(final_price_usd)
                    AS final_prices_usd,
                COUNT(gross_price_usd)
                    AS gross_prices_usd,
                COUNT(current_price_usd)
                    AS current_prices_usd
            FROM warehouse.auction
            GROUP BY marketplace
            ORDER BY marketplace
            """
        )
    ).mappings().all()

    by_marketplace = {
        str(row["marketplace"]): row
        for row in marketplace_rows
    }

    for marketplace in (
        "buyee",
        "ebay",
    ):
        row = by_marketplace.get(
            marketplace
        )

        if row is None:
            raise RuntimeError(
                f"Expected non-empty {marketplace} marketplace data; "
                "found no rows."
            )

        expected = int(
            row["rows"]
        )

        if expected <= 0:
            raise RuntimeError(
                f"Expected non-empty {marketplace} marketplace data; "
                f"found {expected} rows."
            )

        for column in (
            "fx_rates",
            "final_prices_usd",
            "gross_prices_usd",
        ):
            actual = int(
                row[column]
            )

            if actual != expected:
                raise RuntimeError(
                    f"{marketplace}: expected "
                    f"{expected} {column}; found "
                    f"{actual}."
                )

    print()
    print("Conversion coverage")
    print("===================")

    for row in marketplace_rows:
        print()
        print(row["marketplace"])
        print("-" * len(str(row["marketplace"])))
        print(
            "Rows              :",
            row["rows"],
        )
        print(
            "FX rates          :",
            row["fx_rates"],
        )
        print(
            "Final prices USD  :",
            row["final_prices_usd"],
        )
        print(
            "Gross prices USD  :",
            row["gross_prices_usd"],
        )
        print(
            "Current prices USD:",
            row["current_prices_usd"],
        )


def build_engine(
    database_url: str,
) -> Engine:
    """Create the Psycopg 3 SQLAlchemy engine."""
    return create_engine(
        normalize_database_url(
            database_url
        ),
        pool_pre_ping=True,
    )


def main(
    arguments: Sequence[str] | None = None,
) -> int:
    """Run the persistent exchange-rate update."""
    options = parse_arguments(
        arguments
    )

    engine = build_engine(
        options.database_url
    )

    try:
        with engine.begin() as connection:
            verify_database(
                connection,
                expected_database_name=(
                    options.expected_database_name
                ),
                expected_database_user=(
                    options.expected_database_user
                ),
            )

            if options.rate is not None:
                exchange_rate = resolve_exchange_rate(
                    explicit_rate=options.rate,
                    explicit_date=options.rate_date,
                    source_csv=options.source_csv,
                )
            else:
                exchange_rate = load_persisted_rate(
                    connection
                )

                if exchange_rate is None:
                    exchange_rate = resolve_exchange_rate(
                        explicit_rate=None,
                        explicit_date=options.rate_date,
                        source_csv=options.source_csv,
                    )
                elif options.rate_date is not None:
                    exchange_rate = ExchangeRate(
                        rate=exchange_rate.rate,
                        rate_date=options.rate_date,
                        source=exchange_rate.source,
                    )

            print()
            print("JPY to USD exchange rate")
            print("========================")
            print(
                f"Rate  : {exchange_rate.rate}"
            )
            print(
                f"Date  : {exchange_rate.rate_date}"
            )
            print(
                f"Source: {exchange_rate.source}"
            )

            ensure_columns(connection)

            rate_rows, value_rows = apply_rate(
                connection,
                exchange_rate,
            )

            verify_results(connection)

        print()
        print("FX update completed")
        print("===================")
        print(
            f"Rate rows updated : {rate_rows}"
        )
        print(
            f"Value rows updated: {value_rows}"
        )
        print()
        print(
            "✓ USD values were committed in one transaction."
        )

        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
