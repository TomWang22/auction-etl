#!/usr/bin/env python3
"""Recover core Auction ETL records from exported CSV reports."""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://"
    "auction:auction@localhost:5444/auction_warehouse"
)

DEFAULT_OUTPUT_PATH = Path(
    "exports/recovery/auction_recovered_normalized.csv"
)

DEFAULT_BACKUP_DIRECTORY = Path("backups/recovery")

EXPECTED_INPUT_ROWS = 846
EXPECTED_UNIQUE_ROWS = 775
EXPECTED_MARKETPLACE_COUNTS = {
    "ebay": 698,
    "buyee": 77,
}

TARGET_COLUMNS = (
    "marketplace",
    "listing_id",
    "auction_url",
    "seller",
    "artist",
    "title",
    "media_type",
    "edition",
    "catalog_number",
    "condition_media",
    "condition_cover",
    "bulk_lot",
    "bid_count",
    "watch_count",
    "start_price",
    "final_price",
    "shipping_price",
    "tax_amount",
    "currency",
    "ended_at",
    "gross_price",
    "tax_rate",
    "price_includes_tax",
    "disc_count",
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "marketplace": (
        "marketplace",
        "source",
        "site",
        "platform",
    ),
    "listing_id": (
        "listing_id",
        "item_id",
        "auction_id",
        "id",
        "ebay_item_id",
        "buyee_item_id",
    ),
    "auction_url": (
        "auction_url",
        "url",
        "listing_url",
        "item_url",
        "source_url",
        "original_url",
    ),
    "seller": (
        "seller",
        "seller_name",
        "seller_username",
        "store",
        "store_name",
    ),
    "artist": (
        "artist",
        "artist_name",
        "performer",
    ),
    "title": (
        "title",
        "listing_title",
        "auction_title",
        "item_title",
    ),
    "media_type": (
        "media_type",
        "format",
        "record_format",
        "media",
    ),
    "edition": (
        "edition",
        "pressing",
        "release_type",
    ),
    "catalog_number": (
        "catalog_number",
        "catalog",
        "catalog_no",
        "catalogue_number",
        "catalogue_no",
        "cat_no",
        "cat_number",
        "pressing_number",
    ),
    "condition_media": (
        "condition_media",
        "media_condition",
        "record_condition",
        "vinyl_condition",
    ),
    "condition_cover": (
        "condition_cover",
        "cover_condition",
        "sleeve_condition",
        "jacket_condition",
    ),
    "bulk_lot": (
        "bulk_lot",
        "is_bulk",
        "bulk",
        "lot",
    ),
    "bid_count": (
        "bid_count",
        "bids",
        "number_of_bids",
    ),
    "watch_count": (
        "watch_count",
        "watchers",
        "number_of_watchers",
    ),
    "start_price": (
        "start_price",
        "starting_price",
        "opening_price",
    ),
    "final_price": (
        "final_price",
        "sold_price",
        "sale_price",
        "winning_bid",
        "price",
        "item_price",
    ),
    "shipping_price": (
        "shipping_price",
        "shipping",
        "postage",
        "delivery_price",
    ),
    "tax_amount": (
        "tax_amount",
        "tax",
        "sales_tax",
    ),
    "currency": (
        "currency",
        "currency_code",
    ),
    "ended_at": (
        "ended_at",
        "end_time",
        "ended",
        "sale_date",
        "sold_at",
        "completed_at",
        "auction_end",
    ),
    "gross_price": (
        "gross_price",
        "total_price",
        "all_in_price",
        "price_with_shipping",
    ),
    "tax_rate": (
        "tax_rate",
        "sales_tax_rate",
    ),
    "price_includes_tax": (
        "price_includes_tax",
        "includes_tax",
        "tax_included",
    ),
    "disc_count": (
        "disc_count",
        "number_of_discs",
        "discs",
        "record_count",
    ),
}

BOOLEAN_TRUE = {
    "1",
    "true",
    "t",
    "yes",
    "y",
    "on",
    "bulk",
}

BOOLEAN_FALSE = {
    "0",
    "false",
    "f",
    "no",
    "n",
    "off",
    "single",
    "not bulk",
    "not_bulk",
}


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Normalize exported Auction ETL reports and optionally "
            "upsert them into warehouse.auction."
        )
    )
    parser.add_argument(
        "csv_files",
        nargs="+",
        type=Path,
        help="Exported CSV files to normalize.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Normalized CSV output path.",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="SQLAlchemy PostgreSQL database URL.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the normalized records to PostgreSQL.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip pg_dump only for a known empty recovery database.",
    )
    parser.add_argument(
        "--allow-unexpected-counts",
        action="store_true",
        help="Allow counts other than the expected recovery snapshot.",
    )
    return parser.parse_args()


def normalize_header(value: Any) -> str:
    """Normalize one CSV column name."""
    text_value = str(value).strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", "_", text_value)
    return text_value.strip("_")


def clean_text(value: Any) -> str | None:
    """Return normalized text or None."""
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    cleaned = str(value).strip()

    if not cleaned:
        return None

    if cleaned.lower() in {
        "nan",
        "none",
        "null",
        "n/a",
        "na",
    }:
        return None

    return cleaned


def parse_number(value: Any) -> float | None:
    """Parse a numeric value from exported text."""
    cleaned = clean_text(value)

    if cleaned is None:
        return None

    normalized = (
        cleaned.replace(",", "")
        .replace("$", "")
        .replace("¥", "")
        .replace("£", "")
        .replace("€", "")
    )

    match = re.search(r"-?\d+(?:\.\d+)?", normalized)

    if match is None:
        return None

    try:
        result = float(match.group(0))
    except ValueError:
        return None

    if not math.isfinite(result):
        return None

    return result


def parse_integer(value: Any) -> int | None:
    """Parse an integer value."""
    number = parse_number(value)

    if number is None:
        return None

    return int(number)


def parse_boolean(value: Any) -> bool | None:
    """Parse a nullable boolean value."""
    cleaned = clean_text(value)

    if cleaned is None:
        return None

    normalized = cleaned.lower()

    if normalized in BOOLEAN_TRUE:
        return True

    if normalized in BOOLEAN_FALSE:
        return False

    return None


def parse_datetime(value: Any) -> str | None:
    """Parse a timestamp and return an ISO-8601 UTC value."""
    cleaned = clean_text(value)

    if cleaned is None:
        return None

    parsed = pd.to_datetime(
        cleaned,
        errors="coerce",
        utc=True,
    )

    if pd.isna(parsed):
        return None

    return parsed.isoformat()


def infer_marketplace(
    source_path: Path,
    row: pd.Series,
    source_columns: dict[str, str],
) -> str | None:
    """Infer marketplace from a field, filename, or URL."""
    marketplace_column = source_columns.get("marketplace")

    if marketplace_column:
        candidate = clean_text(row.get(marketplace_column))

        if candidate:
            normalized = candidate.lower()

            if "ebay" in normalized:
                return "ebay"

            if "buyee" in normalized or "yahoo" in normalized:
                return "buyee"

    filename = source_path.name.lower()

    if "buyee" in filename:
        return "buyee"

    if "ebay" in filename:
        return "ebay"

    url_column = source_columns.get("auction_url")
    url = clean_text(row.get(url_column)) if url_column else None

    if url:
        lowered = url.lower()

        if "ebay." in lowered:
            return "ebay"

        if (
            "buyee." in lowered
            or "yahoo.co.jp" in lowered
            or "auctions.yahoo" in lowered
        ):
            return "buyee"

    return None


def derive_listing_id(
    marketplace: str | None,
    value: Any,
    auction_url: str | None,
) -> str | None:
    """Return a stable listing identifier."""
    cleaned = clean_text(value)

    if cleaned:
        if re.fullmatch(r"\d+\.0", cleaned):
            cleaned = cleaned[:-2]

        return cleaned

    if not auction_url:
        return None

    patterns = []

    if marketplace == "ebay":
        patterns.extend(
            (
                r"/itm/(?:[^/?]+/)?(\d{9,15})",
                r"[?&]item=(\d{9,15})",
                r"/(\d{9,15})(?:[/?#]|$)",
            )
        )
    else:
        patterns.extend(
            (
                r"/auction/([A-Za-z]?\d+)",
                r"[?&](?:auction|id)=([A-Za-z]?\d+)",
                r"/([A-Za-z]\d{7,})",
            )
        )

    for pattern in patterns:
        match = re.search(
            pattern,
            auction_url,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def choose_source_columns(
    dataframe: pd.DataFrame,
) -> dict[str, str]:
    """Map normalized target names to existing CSV columns."""
    normalized_to_original = {
        normalize_header(column): str(column)
        for column in dataframe.columns
    }

    result: dict[str, str] = {}

    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_header(alias)

            if normalized_alias in normalized_to_original:
                result[target] = normalized_to_original[
                    normalized_alias
                ]
                break

    return result


def source_value(
    row: pd.Series,
    columns: dict[str, str],
    target: str,
) -> Any:
    """Return the source value mapped to a target field."""
    source_column = columns.get(target)

    if source_column is None:
        return None

    return row.get(source_column)


def normalize_row(
    source_path: Path,
    row: pd.Series,
    columns: dict[str, str],
    source_priority: int,
    source_row: int,
) -> dict[str, Any]:
    """Normalize one exported report row."""
    marketplace = infer_marketplace(
        source_path,
        row,
        columns,
    )

    auction_url = clean_text(
        source_value(
            row,
            columns,
            "auction_url",
        )
    )

    listing_id = derive_listing_id(
        marketplace,
        source_value(
            row,
            columns,
            "listing_id",
        ),
        auction_url,
    )

    final_price = parse_number(
        source_value(
            row,
            columns,
            "final_price",
        )
    )
    shipping_price = parse_number(
        source_value(
            row,
            columns,
            "shipping_price",
        )
    )
    tax_amount = parse_number(
        source_value(
            row,
            columns,
            "tax_amount",
        )
    )
    gross_price = parse_number(
        source_value(
            row,
            columns,
            "gross_price",
        )
    )

    if gross_price is None and final_price is not None:
        gross_price = final_price

        if shipping_price is not None:
            gross_price += shipping_price

        if tax_amount is not None:
            gross_price += tax_amount

    currency = clean_text(
        source_value(
            row,
            columns,
            "currency",
        )
    )

    if currency:
        currency = currency.upper()

    if not currency:
        currency = "JPY" if marketplace == "buyee" else "USD"

    return {
        "marketplace": marketplace,
        "listing_id": listing_id,
        "auction_url": auction_url,
        "seller": clean_text(
            source_value(row, columns, "seller")
        ),
        "artist": clean_text(
            source_value(row, columns, "artist")
        ),
        "title": clean_text(
            source_value(row, columns, "title")
        ),
        "media_type": clean_text(
            source_value(row, columns, "media_type")
        ),
        "edition": clean_text(
            source_value(row, columns, "edition")
        ),
        "catalog_number": clean_text(
            source_value(row, columns, "catalog_number")
        ),
        "condition_media": clean_text(
            source_value(row, columns, "condition_media")
        ),
        "condition_cover": clean_text(
            source_value(row, columns, "condition_cover")
        ),
        "bulk_lot": parse_boolean(
            source_value(row, columns, "bulk_lot")
        ),
        "bid_count": parse_integer(
            source_value(row, columns, "bid_count")
        ),
        "watch_count": parse_integer(
            source_value(row, columns, "watch_count")
        ),
        "start_price": parse_number(
            source_value(row, columns, "start_price")
        ),
        "final_price": final_price,
        "shipping_price": shipping_price,
        "tax_amount": tax_amount,
        "currency": currency,
        "ended_at": parse_datetime(
            source_value(row, columns, "ended_at")
        ),
        "gross_price": gross_price,
        "tax_rate": parse_number(
            source_value(row, columns, "tax_rate")
        ),
        "price_includes_tax": parse_boolean(
            source_value(
                row,
                columns,
                "price_includes_tax",
            )
        ),
        "disc_count": parse_integer(
            source_value(row, columns, "disc_count")
        ),
        "_source_priority": source_priority,
        "_source_row": source_row,
        "_source_file": source_path.name,
    }


def read_csv_file(path: Path) -> pd.DataFrame:
    """Read an exported CSV while preserving identifiers."""
    errors: list[Exception] = []

    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
    ):
        try:
            return pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            )
        except UnicodeDecodeError as error:
            errors.append(error)

    raise RuntimeError(
        f"Could not decode CSV file {path}: {errors[-1]}"
    )


def normalize_files(
    paths: Iterable[Path],
) -> tuple[pd.DataFrame, int]:
    """Read and normalize all recovery exports."""
    rows: list[dict[str, Any]] = []
    input_count = 0

    for source_priority, path in enumerate(paths):
        if not path.is_file():
            raise FileNotFoundError(
                f"Recovery CSV not found: {path}"
            )

        dataframe = read_csv_file(path)
        input_count += len(dataframe)

        columns = choose_source_columns(dataframe)

        print()
        print(f"Input: {path}")
        print(f"Rows : {len(dataframe)}")
        print(
            "Mapped columns: "
            + ", ".join(
                f"{target}={source}"
                for target, source in sorted(columns.items())
            )
        )

        for source_row, (_, row) in enumerate(
            dataframe.iterrows(),
            start=2,
        ):
            rows.append(
                normalize_row(
                    path,
                    row,
                    columns,
                    source_priority,
                    source_row,
                )
            )

    normalized = pd.DataFrame(rows)

    required = (
        "marketplace",
        "listing_id",
        "auction_url",
        "title",
    )

    missing_required = normalized[
        list(required)
    ].isna()

    if missing_required.any(axis=None):
        failures = normalized.loc[
            missing_required.any(axis=1),
            [
                *required,
                "_source_file",
                "_source_row",
            ],
        ]

        print()
        print("Rows missing required recovery fields")
        print("-------------------------------------")
        print(
            failures.head(30).to_string(
                index=False
            )
        )

        raise ValueError(
            f"{len(failures)} input rows are missing "
            "marketplace, listing_id, auction_url, or title."
        )

    normalized = normalized.sort_values(
        [
            "_source_priority",
            "_source_row",
        ],
        kind="stable",
    )

    normalized = normalized.drop_duplicates(
        subset=[
            "marketplace",
            "listing_id",
        ],
        keep="last",
    )

    normalized = normalized.sort_values(
        [
            "marketplace",
            "listing_id",
        ],
        kind="stable",
    ).reset_index(drop=True)

    return normalized, input_count


def validate_expected_counts(
    dataframe: pd.DataFrame,
    input_count: int,
    allow_unexpected: bool,
) -> None:
    """Validate this known recovery snapshot."""
    marketplace_counts = (
        dataframe.groupby("marketplace")
        .size()
        .to_dict()
    )

    duplicate_count = int(
        dataframe.duplicated(
            [
                "marketplace",
                "listing_id",
            ]
        ).sum()
    )

    duplicate_rows_removed = (
        input_count - len(dataframe)
    )

    print()
    print("Auction recovery summary")
    print("========================")
    print(f"Input rows              : {input_count}")
    print(
        "Unique marketplace keys : "
        f"{len(dataframe)}"
    )
    print(
        "Duplicate rows removed  : "
        f"{duplicate_rows_removed}"
    )

    for marketplace in sorted(marketplace_counts):
        print(
            f"{marketplace:24}: "
            f"{int(marketplace_counts[marketplace])}"
        )

    print(f"Duplicate output keys   : {duplicate_count}")

    if duplicate_count:
        raise ValueError(
            "Normalized recovery output contains duplicate keys."
        )

    if allow_unexpected:
        return

    errors: list[str] = []

    if input_count != EXPECTED_INPUT_ROWS:
        errors.append(
            f"expected {EXPECTED_INPUT_ROWS} input rows, "
            f"found {input_count}"
        )

    if len(dataframe) != EXPECTED_UNIQUE_ROWS:
        errors.append(
            f"expected {EXPECTED_UNIQUE_ROWS} unique rows, "
            f"found {len(dataframe)}"
        )

    for marketplace, expected in (
        EXPECTED_MARKETPLACE_COUNTS.items()
    ):
        actual = int(
            marketplace_counts.get(
                marketplace,
                0,
            )
        )

        if actual != expected:
            errors.append(
                f"{marketplace}: expected {expected}, "
                f"found {actual}"
            )

    if errors:
        raise ValueError(
            "Recovery count validation failed: "
            + "; ".join(errors)
        )


def write_normalized_export(
    dataframe: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write the normalized recovery CSV."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataframe[
        list(TARGET_COLUMNS)
    ].to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    print()
    print(f"Normalized export: {output_path}")


def postgres_cli_url(database_url: str) -> str:
    """Convert an SQLAlchemy URL into a libpq-compatible URL."""
    return database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    ).replace(
        "postgresql+psycopg2://",
        "postgresql://",
        1,
    )


def create_backup(
    engine: Engine,
    database_url: str,
) -> Path:
    """Create a PostgreSQL custom-format backup."""
    with engine.connect() as connection:
        table_exists = connection.execute(
            text(
                """
                SELECT to_regclass(
                    'warehouse.auction'
                ) IS NOT NULL
                """
            )
        ).scalar_one()

        row_count = 0

        if table_exists:
            row_count = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM warehouse.auction
                        """
                    )
                ).scalar_one()
            )

    if row_count == 0:
        print(
            "Existing auction table is empty; "
            "no pre-apply backup is required."
        )
        return Path()

    pg_dump = shutil.which("pg_dump")

    if pg_dump is None:
        raise RuntimeError(
            "pg_dump is required before modifying "
            "a non-empty database."
        )

    DEFAULT_BACKUP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d-%H%M%S")

    backup_path = (
        DEFAULT_BACKUP_DIRECTORY
        / f"auction_warehouse-before-recovery-{timestamp}.dump"
    )

    command = [
        pg_dump,
        "--format=custom",
        "--file",
        str(backup_path),
        postgres_cli_url(database_url),
    ]

    print()
    print("Creating pre-recovery database backup")
    print("-------------------------------------")
    print(f"Rows currently stored: {row_count}")
    print(f"Backup: {backup_path}")

    completed = subprocess.run(
        command,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "pg_dump failed; recovery was not applied."
        )

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise RuntimeError(
            "pg_dump did not create a valid backup file."
        )

    return backup_path


def ensure_database_identity(engine: Engine) -> None:
    """Refuse to write to an unexpected database."""
    with engine.connect() as connection:
        identity = connection.execute(
            text(
                """
                SELECT
                    current_database() AS database_name,
                    current_user AS database_user
                """
            )
        ).mappings().one()

    database_name = str(identity["database_name"])
    database_user = str(identity["database_user"])

    print()
    print("Database identity")
    print("=================")
    print(f"Database: {database_name}")
    print(f"User    : {database_user}")

    if database_name != "auction_warehouse":
        raise RuntimeError(
            "Refusing to write to database "
            f"{database_name!r}; expected 'auction_warehouse'."
        )


def ensure_core_schema(connection: Any) -> None:
    """Create only missing core recovery objects."""
    connection.execute(
        text(
            """
            CREATE SCHEMA IF NOT EXISTS warehouse
            """
        )
    )

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS warehouse.auction (
                id BIGSERIAL PRIMARY KEY,
                marketplace VARCHAR(32) NOT NULL,
                listing_id VARCHAR(255) NOT NULL,
                auction_url TEXT NOT NULL,
                seller VARCHAR(512),
                artist VARCHAR(512),
                title TEXT NOT NULL,
                media_type VARCHAR(128),
                edition VARCHAR(255),
                catalog_number VARCHAR(255),
                condition_media VARCHAR(128),
                condition_cover VARCHAR(128),
                bulk_lot BOOLEAN,
                bid_count INTEGER,
                watch_count INTEGER,
                start_price NUMERIC(18, 2),
                final_price NUMERIC(18, 2),
                shipping_price NUMERIC(18, 2),
                tax_amount NUMERIC(18, 2),
                currency VARCHAR(8),
                ended_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                gross_price NUMERIC(18, 2),
                tax_rate NUMERIC(12, 6),
                price_includes_tax BOOLEAN,
                disc_count INTEGER
            )
            """
        )
    )

    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_auction_marketplace_listing_id
            ON warehouse.auction (
                marketplace,
                listing_id
            )
            """
        )
    )


def database_records(
    dataframe: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Convert dataframe values into DB-safe records."""
    records: list[dict[str, Any]] = []

    for raw_record in dataframe[
        list(TARGET_COLUMNS)
    ].to_dict(orient="records"):
        record: dict[str, Any] = {}

        for key, value in raw_record.items():
            try:
                missing = pd.isna(value)
            except (TypeError, ValueError):
                missing = False

            if missing:
                record[key] = None
            else:
                record[key] = value

        records.append(record)

    return records


def apply_recovery(
    dataframe: pd.DataFrame,
    database_url: str,
    skip_backup: bool,
) -> None:
    """Apply the normalized rows transactionally."""
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
    )

    ensure_database_identity(engine)

    if not skip_backup:
        create_backup(
            engine,
            database_url,
        )
    else:
        print()
        print(
            "Backup explicitly skipped. "
            "Use this only for a new empty recovery database."
        )

    records = database_records(dataframe)

    upsert = text(
        """
        INSERT INTO warehouse.auction (
            marketplace,
            listing_id,
            auction_url,
            seller,
            artist,
            title,
            media_type,
            edition,
            catalog_number,
            condition_media,
            condition_cover,
            bulk_lot,
            bid_count,
            watch_count,
            start_price,
            final_price,
            shipping_price,
            tax_amount,
            currency,
            ended_at,
            gross_price,
            tax_rate,
            price_includes_tax,
            disc_count
        )
        VALUES (
            :marketplace,
            :listing_id,
            :auction_url,
            :seller,
            :artist,
            :title,
            :media_type,
            :edition,
            :catalog_number,
            :condition_media,
            :condition_cover,
            :bulk_lot,
            :bid_count,
            :watch_count,
            :start_price,
            :final_price,
            :shipping_price,
            :tax_amount,
            :currency,
            :ended_at,
            :gross_price,
            :tax_rate,
            :price_includes_tax,
            :disc_count
        )
        ON CONFLICT (
            marketplace,
            listing_id
        )
        DO UPDATE SET
            auction_url = EXCLUDED.auction_url,
            seller = COALESCE(
                EXCLUDED.seller,
                warehouse.auction.seller
            ),
            artist = COALESCE(
                EXCLUDED.artist,
                warehouse.auction.artist
            ),
            title = EXCLUDED.title,
            media_type = COALESCE(
                EXCLUDED.media_type,
                warehouse.auction.media_type
            ),
            edition = COALESCE(
                EXCLUDED.edition,
                warehouse.auction.edition
            ),
            catalog_number = COALESCE(
                EXCLUDED.catalog_number,
                warehouse.auction.catalog_number
            ),
            condition_media = COALESCE(
                EXCLUDED.condition_media,
                warehouse.auction.condition_media
            ),
            condition_cover = COALESCE(
                EXCLUDED.condition_cover,
                warehouse.auction.condition_cover
            ),
            bulk_lot = COALESCE(
                EXCLUDED.bulk_lot,
                warehouse.auction.bulk_lot
            ),
            bid_count = COALESCE(
                EXCLUDED.bid_count,
                warehouse.auction.bid_count
            ),
            watch_count = COALESCE(
                EXCLUDED.watch_count,
                warehouse.auction.watch_count
            ),
            start_price = COALESCE(
                EXCLUDED.start_price,
                warehouse.auction.start_price
            ),
            final_price = COALESCE(
                EXCLUDED.final_price,
                warehouse.auction.final_price
            ),
            shipping_price = COALESCE(
                EXCLUDED.shipping_price,
                warehouse.auction.shipping_price
            ),
            tax_amount = COALESCE(
                EXCLUDED.tax_amount,
                warehouse.auction.tax_amount
            ),
            currency = COALESCE(
                EXCLUDED.currency,
                warehouse.auction.currency
            ),
            ended_at = COALESCE(
                EXCLUDED.ended_at,
                warehouse.auction.ended_at
            ),
            gross_price = COALESCE(
                EXCLUDED.gross_price,
                warehouse.auction.gross_price
            ),
            tax_rate = COALESCE(
                EXCLUDED.tax_rate,
                warehouse.auction.tax_rate
            ),
            price_includes_tax = COALESCE(
                EXCLUDED.price_includes_tax,
                warehouse.auction.price_includes_tax
            ),
            disc_count = COALESCE(
                EXCLUDED.disc_count,
                warehouse.auction.disc_count
            )
        """
    )

    with engine.begin() as connection:
        ensure_core_schema(connection)

        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE
                    recovery_auction_keys (
                        marketplace VARCHAR(32) NOT NULL,
                        listing_id VARCHAR(255) NOT NULL,
                        PRIMARY KEY (
                            marketplace,
                            listing_id
                        )
                    )
                ON COMMIT DROP
                """
            )
        )

        connection.execute(
            text(
                """
                INSERT INTO recovery_auction_keys (
                    marketplace,
                    listing_id
                )
                VALUES (
                    :marketplace,
                    :listing_id
                )
                """
            ),
            [
                {
                    "marketplace": record["marketplace"],
                    "listing_id": record["listing_id"],
                }
                for record in records
            ],
        )

        staged_count = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM recovery_auction_keys
                    """
                )
            ).scalar_one()
        )

        if staged_count != len(records):
            raise RuntimeError(
                "Temporary staging key count did not match "
                "the normalized recovery record count."
            )

        connection.execute(
            upsert,
            records,
        )

    print()
    print("Recovery apply completed")
    print("========================")
    print(f"Inserted or updated: {len(records)}")


def main() -> int:
    """Run the recovery workflow."""
    arguments = parse_arguments()

    try:
        dataframe, input_count = normalize_files(
            arguments.csv_files
        )

        validate_expected_counts(
            dataframe,
            input_count,
            arguments.allow_unexpected_counts,
        )

        write_normalized_export(
            dataframe,
            arguments.output,
        )

        if not arguments.apply:
            print()
            print("DRY RUN ONLY")
            print("No database writes were performed.")
            return 0

        apply_recovery(
            dataframe,
            arguments.database_url,
            arguments.skip_backup,
        )

        return 0
    except Exception as error:
        print(
            f"\nERROR: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
