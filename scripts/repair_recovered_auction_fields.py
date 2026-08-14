#!/usr/bin/env python3
"""Repair recovered auction fields from retained report exports."""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import bindparam, create_engine, text


DATABASE_URL = (
    "postgresql+psycopg://"
    "auction:auction@localhost:5444/auction_warehouse"
)

MONEY_QUANTUM = Decimal("0.01")

TAX_RATES = {
    "ebay": Decimal("0.0625"),
    "buyee": Decimal("0.10"),
}

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "marketplace": (
        "marketplace",
        "source",
        "site",
    ),
    "listing_id": (
        "listing_id",
        "item_id",
        "auction_id",
        "listing",
    ),
    "auction_url": (
        "auction_url",
        "listing_url",
        "item_url",
        "url",
    ),
    "seller": (
        "seller",
        "seller_name",
        "vendor",
    ),
    "artist": (
        "artist",
        "artist_name",
    ),
    "title": (
        "title",
        "listing_title",
        "item_title",
        "auction_title",
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
    "disc_count": (
        "disc_count",
        "record_count",
        "number_of_discs",
        "discs",
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
        "hammer_price_local",
        "final_price",
        "hammer_price",
        "winning_bid",
        "sold_price",
        "sale_price",
        "item_price",
        "auction_price",
        "price",
        "final_bid",
    ),
    "shipping_price": (
        "shipping_price",
        "shipping",
        "postage",
        "delivery_price",
        "delivery",
    ),
    "tax_amount": (
        "tax_amount_local",
        "tax_amount",
        "sales_tax",
        "tax",
    ),
    "gross_price": (
        "gross_price_local",
        "gross_price",
        "total_price",
        "total_paid",
        "price_with_tax",
        "all_in_price",
        "grand_total",
    ),
    "currency": (
        "currency",
        "currency_code",
    ),
    "ended_at": (
        "ended_at",
        "end_date",
        "ended",
        "completed_at",
        "sold_at",
        "sale_date",
    ),
    "price_includes_tax": (
        "price_includes_tax",
        "tax_included",
        "includes_tax",
    ),
    "obi": (
        "obi",
        "obi_present",
        "has_obi",
    ),
    "insert_present": (
        "insert_present",
        "insert",
        "has_insert",
    ),
    "poster_present": (
        "poster_present",
        "poster",
        "has_poster",
    ),
}


@dataclass(slots=True)
class RepairRow:
    """Normalized repair values for one marketplace listing."""

    marketplace: str
    listing_id: str
    values: dict[str, Any]


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Repair recovered auction fields from retained CSV reports."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Recovery report CSV paths.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates to PostgreSQL.",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=Path(
            "exports/recovery/"
            "auction_recovered_field_repairs.csv"
        ),
        help="Normalized repair export.",
    )
    return parser.parse_args()


def normalized_column(value: Any) -> str:
    """Normalize a report column name."""
    text_value = str(value).strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", "_", text_value)
    return text_value.strip("_")


def clean_text(value: Any) -> str | None:
    """Return clean text or None."""
    if value is None or pd.isna(value):
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    if cleaned.lower() in {
        "none",
        "null",
        "nan",
        "n/a",
        "na",
        "-",
        "—",
    }:
        return None

    return cleaned


def decimal_value(value: Any) -> Decimal | None:
    """Parse a report monetary or numeric value."""
    cleaned = clean_text(value)

    if cleaned is None:
        return None

    negative = (
        cleaned.startswith("(")
        and cleaned.endswith(")")
    )

    normalized = re.sub(
        r"[^0-9,.\-]",
        "",
        cleaned,
    )

    if not normalized:
        return None

    if "," in normalized and "." not in normalized:
        groups = normalized.split(",")

        if len(groups[-1]) == 2:
            normalized = ".".join(groups)
        else:
            normalized = "".join(groups)
    else:
        normalized = normalized.replace(",", "")

    try:
        result = Decimal(normalized)
    except InvalidOperation:
        return None

    if negative:
        result = -result

    if not result.is_finite():
        return None

    return result


def integer_value(value: Any) -> int | None:
    """Parse an integer-like value."""
    number = decimal_value(value)

    if number is None:
        return None

    return int(number)


def boolean_value(value: Any) -> bool | None:
    """Parse common boolean labels."""
    cleaned = clean_text(value)

    if cleaned is None:
        return None

    normalized = cleaned.lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "y",
        "present",
        "included",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "n",
        "absent",
        "not included",
    }:
        return False

    return None


def datetime_value(value: Any) -> datetime | None:
    """Parse a report timestamp."""
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

    return parsed.to_pydatetime()


def first_value(
    row: pd.Series,
    columns: Iterable[str],
) -> Any:
    """Return the first populated candidate column."""
    for column in columns:
        if column not in row.index:
            continue

        value = row[column]

        if clean_text(value) is not None:
            return value

    return None


def mapped_columns(
    dataframe: pd.DataFrame,
) -> dict[str, list[str]]:
    """Map canonical fields to columns present in a report."""
    normalized_to_original: dict[str, str] = {
        normalized_column(column): str(column)
        for column in dataframe.columns
    }

    result: dict[str, list[str]] = {}

    for canonical_name, aliases in COLUMN_ALIASES.items():
        matches: list[str] = []

        for alias in aliases:
            original = normalized_to_original.get(alias)

            if original is not None:
                matches.append(original)

        result[canonical_name] = matches

    return result


def infer_marketplace(
    path: Path,
    value: Any,
) -> str | None:
    """Infer marketplace from a field or source path."""
    cleaned = clean_text(value)

    if cleaned:
        normalized = cleaned.lower()

        if "buyee" in normalized:
            return "buyee"

        if "ebay" in normalized:
            return "ebay"

    path_name = str(path).lower()

    if "buyee" in path_name:
        return "buyee"

    if "ebay" in path_name:
        return "ebay"

    return None


def quantize_money(value: Decimal | None) -> Decimal | None:
    """Round money to two decimal places."""
    if value is None:
        return None

    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def calculate_prices(
    *,
    marketplace: str,
    final_price: Decimal | None,
    shipping_price: Decimal | None,
    tax_amount: Decimal | None,
    gross_price: Decimal | None,
    price_includes_tax: bool | None,
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal,
    bool,
]:
    """Normalize hammer, tax, and gross prices."""
    tax_rate = TAX_RATES[marketplace]
    shipping = shipping_price or Decimal("0")

    raw_final = final_price
    raw_tax = tax_amount
    raw_gross = gross_price

    if raw_final is None and raw_gross is not None:
        taxable_total = raw_gross - shipping

        if taxable_total >= 0:
            if price_includes_tax is False:
                raw_final = taxable_total
            else:
                raw_final = (
                    taxable_total
                    / (Decimal("1") + tax_rate)
                )

    if raw_final is not None:
        calculated_tax = raw_final * tax_rate

        if raw_tax is None:
            raw_tax = calculated_tax

        if raw_gross is None:
            raw_gross = (
                raw_final
                + shipping
                + raw_tax
            )

    return (
        quantize_money(raw_final),
        quantize_money(shipping_price),
        quantize_money(raw_tax),
        tax_rate,
        False,
    ) if raw_final is None else (
        quantize_money(raw_final),
        quantize_money(shipping_price),
        quantize_money(raw_tax),
        tax_rate,
        False,
    )


def calculated_gross(
    *,
    final_price: Decimal | None,
    shipping_price: Decimal | None,
    tax_amount: Decimal | None,
    existing_gross: Decimal | None,
) -> Decimal | None:
    """Calculate the all-in price."""
    if final_price is None:
        return quantize_money(existing_gross)

    return quantize_money(
        final_price
        + (shipping_price or Decimal("0"))
        + (tax_amount or Decimal("0"))
    )


def parse_report(
    path: Path,
) -> list[RepairRow]:
    """Parse one recovery report."""
    dataframe = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )

    mapping = mapped_columns(dataframe)

    print()
    print(f"Input: {path}")
    print(f"Rows : {len(dataframe)}")
    print("Columns:")
    print("  " + ", ".join(map(str, dataframe.columns)))

    detected = {
        field: columns
        for field, columns in mapping.items()
        if columns
    }

    print("Detected mappings:")

    for field, columns in detected.items():
        print(f"  {field}: {', '.join(columns)}")

    repairs: list[RepairRow] = []

    for _, row in dataframe.iterrows():
        marketplace = infer_marketplace(
            path,
            first_value(
                row,
                mapping["marketplace"],
            ),
        )

        listing_id = clean_text(
            first_value(
                row,
                mapping["listing_id"],
            )
        )

        if marketplace not in TAX_RATES or not listing_id:
            continue

        final_price = decimal_value(
            first_value(
                row,
                mapping["final_price"],
            )
        )
        shipping_price = decimal_value(
            first_value(
                row,
                mapping["shipping_price"],
            )
        )
        tax_amount = decimal_value(
            first_value(
                row,
                mapping["tax_amount"],
            )
        )
        gross_price = decimal_value(
            first_value(
                row,
                mapping["gross_price"],
            )
        )
        includes_tax = boolean_value(
            first_value(
                row,
                mapping["price_includes_tax"],
            )
        )

        (
            final_price,
            shipping_price,
            tax_amount,
            tax_rate,
            price_includes_tax,
        ) = calculate_prices(
            marketplace=marketplace,
            final_price=final_price,
            shipping_price=shipping_price,
            tax_amount=tax_amount,
            gross_price=gross_price,
            price_includes_tax=includes_tax,
        )

        gross_price = calculated_gross(
            final_price=final_price,
            shipping_price=shipping_price,
            tax_amount=tax_amount,
            existing_gross=gross_price,
        )

        values: dict[str, Any] = {
            "auction_url": clean_text(
                first_value(
                    row,
                    mapping["auction_url"],
                )
            ),
            "seller": clean_text(
                first_value(
                    row,
                    mapping["seller"],
                )
            ),
            "artist": clean_text(
                first_value(
                    row,
                    mapping["artist"],
                )
            ),
            "title": clean_text(
                first_value(
                    row,
                    mapping["title"],
                )
            ),
            "media_type": clean_text(
                first_value(
                    row,
                    mapping["media_type"],
                )
            ),
            "edition": clean_text(
                first_value(
                    row,
                    mapping["edition"],
                )
            ),
            "catalog_number": clean_text(
                first_value(
                    row,
                    mapping["catalog_number"],
                )
            ),
            "condition_media": clean_text(
                first_value(
                    row,
                    mapping["condition_media"],
                )
            ),
            "condition_cover": clean_text(
                first_value(
                    row,
                    mapping["condition_cover"],
                )
            ),
            "disc_count": integer_value(
                first_value(
                    row,
                    mapping["disc_count"],
                )
            ),
            "bulk_lot": boolean_value(
                first_value(
                    row,
                    mapping["bulk_lot"],
                )
            ),
            "bid_count": integer_value(
                first_value(
                    row,
                    mapping["bid_count"],
                )
            ),
            "watch_count": integer_value(
                first_value(
                    row,
                    mapping["watch_count"],
                )
            ),
            "start_price": decimal_value(
                first_value(
                    row,
                    mapping["start_price"],
                )
            ),
            "final_price": final_price,
            "shipping_price": shipping_price,
            "tax_amount": tax_amount,
            "gross_price": gross_price,
            "tax_rate": tax_rate,
            "price_includes_tax": price_includes_tax,
            "currency": (
                clean_text(
                    first_value(
                        row,
                        mapping["currency"],
                    )
                )
                or (
                    "JPY"
                    if marketplace == "buyee"
                    else "USD"
                )
            ),
            "ended_at": datetime_value(
                first_value(
                    row,
                    mapping["ended_at"],
                )
            ),
            "obi": boolean_value(
                first_value(
                    row,
                    mapping["obi"],
                )
            ),
            "insert_present": boolean_value(
                first_value(
                    row,
                    mapping["insert_present"],
                )
            ),
            "poster_present": boolean_value(
                first_value(
                    row,
                    mapping["poster_present"],
                )
            ),
        }

        repairs.append(
            RepairRow(
                marketplace=marketplace,
                listing_id=listing_id,
                values=values,
            )
        )

    return repairs


def merge_repairs(
    rows: Iterable[RepairRow],
) -> dict[tuple[str, str], RepairRow]:
    """Merge duplicate report rows without discarding enrichment."""
    merged: dict[tuple[str, str], RepairRow] = {}

    for row in rows:
        key = (
            row.marketplace,
            row.listing_id,
        )

        existing = merged.get(key)

        if existing is None:
            merged[key] = row
            continue

        combined = dict(existing.values)

        for field, value in row.values.items():
            if value is not None:
                combined[field] = value

        merged[key] = RepairRow(
            marketplace=row.marketplace,
            listing_id=row.listing_id,
            values=combined,
        )

    return merged


def export_repairs(
    rows: Iterable[RepairRow],
    output_path: Path,
) -> pd.DataFrame:
    """Write normalized repairs for inspection."""
    records = []

    for row in rows:
        records.append(
            {
                "marketplace": row.marketplace,
                "listing_id": row.listing_id,
                **row.values,
            }
        )

    dataframe = pd.DataFrame(records)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataframe.to_csv(
        output_path,
        index=False,
    )

    return dataframe


def print_summary(dataframe: pd.DataFrame) -> None:
    """Print field-recovery coverage."""
    print()
    print("Recovered field coverage")
    print("========================")

    print(f"Rows: {len(dataframe)}")

    for marketplace, group in dataframe.groupby(
        "marketplace"
    ):
        print()
        print(marketplace)
        print("-" * len(marketplace))

        for column in (
            "final_price",
            "shipping_price",
            "tax_amount",
            "gross_price",
            "ended_at",
            "catalog_number",
            "condition_media",
            "condition_cover",
            "obi",
            "insert_present",
            "poster_present",
        ):
            populated = int(
                group[column].notna().sum()
            )
            print(
                f"{column:22}: "
                f"{populated:4} / {len(group)}"
            )


def ensure_auction_detail(engine: Any) -> None:
    """Create the missing optional-detail relation."""
    statement = """
    CREATE TABLE IF NOT EXISTS warehouse.auction_detail (
        id BIGSERIAL PRIMARY KEY,
        marketplace VARCHAR NOT NULL,
        listing_id VARCHAR NOT NULL,
        source_url TEXT,
        started_at TIMESTAMPTZ,
        ended_at TIMESTAMPTZ,
        condition_text TEXT,
        detail_price NUMERIC,
        detail_currency VARCHAR,
        seller_location TEXT,
        description TEXT,
        image_urls JSONB,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_auction_detail_marketplace_listing
            UNIQUE (marketplace, listing_id)
    );

    CREATE INDEX IF NOT EXISTS
        ix_auction_detail_marketplace_listing
    ON warehouse.auction_detail (
        marketplace,
        listing_id
    );
    """

    with engine.begin() as connection:
        connection.execute(text(statement))


def apply_repairs(
    engine: Any,
    rows: Iterable[RepairRow],
) -> int:
    """Apply normalized repairs in one transaction."""
    update_statement = text(
        """
        UPDATE warehouse.auction
        SET
            auction_url = COALESCE(
                :auction_url,
                auction_url
            ),
            seller = COALESCE(
                :seller,
                seller
            ),
            artist = COALESCE(
                :artist,
                artist
            ),
            title = COALESCE(
                :title,
                title
            ),
            media_type = COALESCE(
                :media_type,
                media_type
            ),
            edition = COALESCE(
                :edition,
                edition
            ),
            catalog_number = COALESCE(
                :catalog_number,
                catalog_number
            ),
            condition_media = COALESCE(
                :condition_media,
                condition_media
            ),
            condition_cover = COALESCE(
                :condition_cover,
                condition_cover
            ),
            disc_count = COALESCE(
                :disc_count,
                disc_count
            ),
            bulk_lot = COALESCE(
                :bulk_lot,
                bulk_lot
            ),
            bid_count = COALESCE(
                :bid_count,
                bid_count
            ),
            watch_count = COALESCE(
                :watch_count,
                watch_count
            ),
            start_price = COALESCE(
                :start_price,
                start_price
            ),
            final_price = COALESCE(
                :final_price,
                final_price
            ),
            shipping_price = COALESCE(
                :shipping_price,
                shipping_price
            ),
            tax_amount = COALESCE(
                :tax_amount,
                tax_amount
            ),
            gross_price = COALESCE(
                :gross_price,
                gross_price
            ),
            tax_rate = COALESCE(
                :tax_rate,
                tax_rate
            ),
            price_includes_tax = COALESCE(
                :price_includes_tax,
                price_includes_tax
            ),
            currency = COALESCE(
                :currency,
                currency
            ),
            ended_at = COALESCE(
                :ended_at,
                ended_at
            )
        WHERE marketplace = :marketplace
          AND listing_id = :listing_id
        """
    )

    updated = 0

    with engine.begin() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        if database_name != "auction_warehouse":
            raise RuntimeError(
                f"Refusing database {database_name!r}."
            )

        for row in rows:
            parameters = {
                "marketplace": row.marketplace,
                "listing_id": row.listing_id,
                **{
                    field: value
                    for field, value in row.values.items()
                    if field
                    not in {
                        "obi",
                        "insert_present",
                        "poster_present",
                    }
                },
            }

            result = connection.execute(
                update_statement,
                parameters,
            )
            updated += result.rowcount

    return updated


def apply_collector_flags(
    engine: Any,
    rows: Iterable[RepairRow],
) -> int:
    """Apply report-provided collector flags after its table exists."""
    statement = text(
        """
        UPDATE warehouse.auction_collector
        SET
            manual_obi = COALESCE(
                :obi,
                manual_obi
            ),
            manual_insert_present = COALESCE(
                :insert_present,
                manual_insert_present
            ),
            manual_poster_present = COALESCE(
                :poster_present,
                manual_poster_present
            ),
            updated_at = now()
        WHERE marketplace = :marketplace
          AND listing_id = :listing_id
        """
    )

    updated = 0

    with engine.begin() as connection:
        table_exists = connection.execute(
            text(
                """
                SELECT to_regclass(
                    'warehouse.auction_collector'
                )
                """
            )
        ).scalar_one()

        if table_exists is None:
            return 0

        for row in rows:
            flags = {
                "obi": row.values.get("obi"),
                "insert_present": row.values.get(
                    "insert_present"
                ),
                "poster_present": row.values.get(
                    "poster_present"
                ),
            }

            if all(
                value is None
                for value in flags.values()
            ):
                continue

            result = connection.execute(
                statement,
                {
                    "marketplace": row.marketplace,
                    "listing_id": row.listing_id,
                    **flags,
                },
            )
            updated += result.rowcount

    return updated


def main() -> int:
    """Run the recovery-field repair."""
    args = parse_args()

    missing = [
        path
        for path in args.paths
        if not path.is_file()
    ]

    if missing:
        for path in missing:
            print(f"Missing input: {path}")

        return 1

    parsed_rows = [
        repair
        for path in args.paths
        for repair in parse_report(path)
    ]

    merged = merge_repairs(parsed_rows)
    ordered_rows = [
        merged[key]
        for key in sorted(merged)
    ]

    dataframe = export_repairs(
        ordered_rows,
        args.export,
    )

    print_summary(dataframe)

    duplicates = dataframe.duplicated(
        [
            "marketplace",
            "listing_id",
        ]
    ).sum()

    print()
    print(f"Duplicate repair keys: {int(duplicates)}")
    print(f"Repair export: {args.export}")

    if duplicates:
        raise RuntimeError(
            "Repair export contains duplicate keys."
        )

    price_count = int(
        dataframe["final_price"].notna().sum()
    )
    gross_count = int(
        dataframe["gross_price"].notna().sum()
    )

    if price_count == 0:
        raise RuntimeError(
            "No hammer prices were detected. "
            "Refusing to continue."
        )

    if gross_count == 0:
        raise RuntimeError(
            "No gross prices were calculated. "
            "Refusing to continue."
        )

    if not args.apply:
        print()
        print("DRY RUN ONLY")
        print("No database writes were performed.")
        return 0

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )

    ensure_auction_detail(engine)

    updated = apply_repairs(
        engine,
        ordered_rows,
    )

    print()
    print(f"Auction rows updated: {updated}")
    print("Collector flags will be applied after rebuild.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
