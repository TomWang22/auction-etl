"""Main Collector Review integration for ingestion activity and Gripsweat."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import psycopg
from psycopg.rows import dict_row


def _coalesce_duplicate_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Coalesce duplicate DataFrame columns from left to right."""
    if not isinstance(frame, pd.DataFrame):
        return frame

    if frame.columns.is_unique:
        return frame

    ordered_columns = list(
        dict.fromkeys(
            frame.columns.tolist()
        )
    )

    coalesced: dict[object, pd.Series] = {}

    for column in ordered_columns:
        matching = frame.loc[
            :,
            frame.columns == column,
        ]

        if matching.shape[1] == 1:
            coalesced[column] = matching.iloc[:, 0]
            continue

        coalesced[column] = (
            matching
            .bfill(axis=1)
            .iloc[:, 0]
        )

    return pd.DataFrame(
        coalesced,
        index=frame.index,
    ).loc[:, ordered_columns]


def _concat_unique_columns(
    objects: object,
    *args: object,
    **kwargs: object,
) -> pd.DataFrame:
    """Concatenate frames after coalescing duplicate columns."""
    if isinstance(objects, pd.DataFrame):
        normalized: object = [
            _coalesce_duplicate_columns(objects)
        ]
    elif isinstance(objects, dict):
        normalized = {
            key: (
                _coalesce_duplicate_columns(value)
                if isinstance(value, pd.DataFrame)
                else value
            )
            for key, value in objects.items()
        }
    else:
        normalized = [
            (
                _coalesce_duplicate_columns(value)
                if isinstance(value, pd.DataFrame)
                else value
            )
            for value in objects
        ]

    result = pd.concat(
        normalized,
        *args,
        **kwargs,
    )

    if isinstance(result, pd.DataFrame):
        return _coalesce_duplicate_columns(result)

    return result




DEFAULT_DATABASE_URL = (
    "postgresql://auction:auction@"
    "127.0.0.1:5544/auction_warehouse"
)

GRIPSWEAT_ITEM_ID_PATTERN = re.compile(
    r"^/item/(?P<listing_id>[0-9]{9,15})(?:/|$)",
    re.IGNORECASE,
)

GRIPSWEAT_DATE_PATTERN = re.compile(
    r"(?P<date>[A-Za-z]{3,9}\s+[0-9]{1,2},\s+[0-9]{4})\s*$",
    re.IGNORECASE,
)

GRIPSWEAT_TRAILING_SALE_PATTERN = re.compile(
    r"\s+"
    r"(?:(?:US\s*)?[$£€¥]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?\s*)+"
    r"(?:\([A-Z]{3}\))?\s*"
    r"[A-Za-z]{3,9}\s+[0-9]{1,2},\s+[0-9]{4}\s*$",
    re.IGNORECASE,
)

GRIPSWEAT_DATE_FORMATS = (
    "%B %d, %Y",
    "%b %d, %Y",
)


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


def configured_database_url(
    database_url: str | None = None,
) -> str:
    """Return the configured Psycopg database URL."""
    return normalize_database_url(
        database_url
        or os.environ.get(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        )
    )


def _coalesce_named_column(
    dataframe: pd.DataFrame,
    column_name: str,
) -> pd.Series | None:
    """Return one Series when duplicate column labels are present."""
    if column_name not in dataframe.columns:
        return None

    selected = dataframe.loc[:, column_name]

    if isinstance(selected, pd.DataFrame):
        return (
            selected
            .bfill(axis=1)
            .iloc[:, 0]
        )

    return selected


def _load_metadata_rows(
    database_url: str,
) -> list[dict[str, Any]]:
    """Load durable first-seen and last-seen metadata."""
    query = """
        SELECT
            marketplace,
            listing_id,
            first_seen_at,
            last_seen_at,
            first_seen_source,
            last_seen_source
        FROM system.auction_ingestion_identity
    """

    with psycopg.connect(
        normalize_database_url(database_url),
        row_factory=dict_row,
    ) as connection:
        return list(
            connection.execute(
                query
            ).fetchall()
        )


def _metadata_index(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index audit metadata by marketplace and listing ID."""
    result: dict[
        tuple[str, str],
        Mapping[str, Any],
    ] = {}

    for row in rows:
        marketplace = str(
            row.get("marketplace") or ""
        )
        listing_id = str(
            row.get("listing_id") or ""
        )

        result[
            marketplace,
            listing_id,
        ] = row

    return result


def _datetime_series(
    dataframe: pd.DataFrame,
    candidates: Sequence[str],
) -> pd.Series:
    """Coalesce datetime candidates into one UTC Series."""
    result = pd.Series(
        pd.NaT,
        index=dataframe.index,
        dtype="datetime64[ns, UTC]",
    )

    for candidate in candidates:
        selected = _coalesce_named_column(
            dataframe,
            candidate,
        )

        if selected is None:
            continue

        converted = pd.to_datetime(
            selected,
            errors="coerce",
            utc=True,
        )

        result = result.combine_first(
            converted
        )

    return result


def gripsweat_original_listing_id(
    url: Any,
) -> str:
    """Extract the original marketplace listing ID from a Gripsweat URL."""
    value = str(url or "").strip()

    if not value:
        return ""

    match = GRIPSWEAT_ITEM_ID_PATTERN.match(
        urlparse(value).path
    )

    if match is None:
        return ""

    return match.group("listing_id")


def parse_gripsweat_sold_at(
    raw_text: Any,
) -> pd.Timestamp | pd.NaT:
    """Parse a Gripsweat sale date from archived card text."""
    text = " ".join(
        str(raw_text or "").split()
    )

    match = GRIPSWEAT_DATE_PATTERN.search(
        text
    )

    if match is None:
        return pd.NaT

    raw_date = match.group("date")

    for date_format in GRIPSWEAT_DATE_FORMATS:
        try:
            parsed = datetime.strptime(
                raw_date,
                date_format,
            )
            return pd.Timestamp(
                parsed,
                tz="UTC",
            )
        except ValueError:
            continue

    return pd.NaT


def parse_gripsweat_title(
    title: Any,
    raw_text: Any,
) -> str:
    """Return the stored title or derive it from archived card text."""
    stored = str(title or "").strip()

    if stored and stored.casefold() not in {
        "nan",
        "none",
        "null",
    }:
        return stored

    text = " ".join(
        str(raw_text or "").split()
    )

    return GRIPSWEAT_TRAILING_SALE_PATTERN.sub(
        "",
        text,
    ).strip()


def _collector_values(
    value: Any,
) -> dict[str, Any]:
    """Normalize a JSON collector record."""
    if isinstance(value, Mapping):
        return dict(value)

    return {}


def load_gripsweat_records(
    *,
    database_url: str | None = None,
) -> pd.DataFrame:
    """Load Gripsweat-only sales, suppressing exact native eBay IDs."""
    query = """
        SELECT *
        FROM warehouse.gripsweat_sale
        ORDER BY
            sold_at DESC NULLS LAST,
            id
    """

    with psycopg.connect(
        configured_database_url(
            database_url
        ),
        row_factory=dict_row,
    ) as connection:
        sale_rows = list(
            connection.execute(
                query
            ).fetchall()
        )

        ebay_ids = {
            str(row["listing_id"])
            for row in connection.execute(
                """
                SELECT listing_id
                FROM warehouse.auction
                WHERE marketplace = 'ebay'
                """
            ).fetchall()
        }

        collector_index = {
            str(row["listing_id"]): row
            for row in connection.execute(
                """
                SELECT *
                FROM warehouse.auction_collector
                WHERE marketplace = 'gripsweat'
                """
            ).fetchall()
        }

    records: list[dict[str, Any]] = []

    for sale in sale_rows:
        derived_listing_id = (
            str(
                sale.get(
                    "original_listing_id"
                )
                or ""
            ).strip()
            or gripsweat_original_listing_id(
                sale.get("gripsweat_url")
            )
        )

        if not derived_listing_id:
            continue

        if derived_listing_id in ebay_ids:
            continue

        sold_at = pd.to_datetime(
            sale.get("sold_at"),
            errors="coerce",
            utc=True,
        )

        if pd.isna(sold_at):
            sold_at = parse_gripsweat_sold_at(
                sale.get("raw_text")
            )

        currency = str(
            sale.get("currency")
            or ""
        ).strip().upper()

        sold_price = sale.get(
            "sold_price"
        )

        record: dict[str, Any] = {
            "marketplace": "gripsweat",
            "listing_id": derived_listing_id,
            "auction_url": sale.get(
                "gripsweat_url"
            ),
            "seller": sale.get(
                "source_name"
            ),
            "artist": sale.get(
                "configured_artist"
            ),
            "title": parse_gripsweat_title(
                sale.get("title"),
                sale.get("raw_text"),
            ),
            "bid_count": 0,
            "final_price": sold_price,
            "gross_price": sold_price,
            "currency": currency,
            "fx_rate_to_usd": (
                1
                if currency == "USD"
                else None
            ),
            "fx_rate_date": (
                sold_at.date()
                if (
                    currency == "USD"
                    and not pd.isna(
                        sold_at
                    )
                )
                else None
            ),
            "final_price_usd": (
                sold_price
                if currency == "USD"
                else None
            ),
            "gross_price_usd": (
                sold_price
                if currency == "USD"
                else None
            ),
            "landed_price_usd": (
                sold_price
                if currency == "USD"
                else None
            ),
            "ended_at": sold_at,
            "closing_at": sold_at,
            "created_at": sale.get(
                "created_at"
            ),
            "detail_status": (
                "archived"
            ),
            "detail_fetched_at": sale.get(
                "updated_at"
            ),
            "auction_format": (
                "ARCHIVE"
            ),
            "source_name": sale.get(
                "source_name"
            ),
            "gripsweat_item_key": sale.get(
                "gripsweat_item_key"
            ),
            "gripsweat_url": sale.get(
                "gripsweat_url"
            ),
            "_source_first_seen_at": sale.get(
                "first_seen_at"
            ),
            "_source_last_seen_at": sale.get(
                "last_seen_at"
            ),
            "_source_kind": "gripsweat",
        }

        for key, value in _collector_values(
            collector_index.get(
                derived_listing_id
            )
        ).items():
            if key in {
                "id",
                "marketplace",
                "listing_id",
            }:
                continue

            record[
                f"collector_{key}"
            ] = value

        records.append(record)

    return pd.DataFrame.from_records(
        records
    )


def integrate_recent_activity(
    dataframe: pd.DataFrame,
    *,
    metadata_rows: Sequence[
        Mapping[str, Any]
    ] | None = None,
    database_url: str | None = None,
) -> pd.DataFrame:
    """Add audit metadata and activity dates without fabricating closes."""
    result = dataframe.copy()

    marketplace = _coalesce_named_column(
        result,
        "marketplace",
    )
    listing_id = _coalesce_named_column(
        result,
        "listing_id",
    )

    if marketplace is None or listing_id is None:
        return result

    if metadata_rows is None:
        metadata_rows = _load_metadata_rows(
            configured_database_url(
                database_url
            )
        )

    indexed = _metadata_index(
        metadata_rows
    )

    keys = list(
        zip(
            marketplace
            .fillna("")
            .astype(str),
            listing_id
            .fillna("")
            .astype(str),
            strict=True,
        )
    )

    matched_rows = [
        indexed.get(key, {})
        for key in keys
    ]

    audit_first_seen = pd.Series(
        pd.to_datetime(
            [
                row.get("first_seen_at")
                for row in matched_rows
            ],
            errors="coerce",
            utc=True,
        ),
        index=result.index,
    )

    audit_last_seen = pd.Series(
        pd.to_datetime(
            [
                row.get("last_seen_at")
                for row in matched_rows
            ],
            errors="coerce",
            utc=True,
        ),
        index=result.index,
    )

    source_first_seen = _datetime_series(
        result,
        (
            "_source_first_seen_at",
        ),
    )
    source_last_seen = _datetime_series(
        result,
        (
            "_source_last_seen_at",
        ),
    )

    first_seen = audit_first_seen.combine_first(
        source_first_seen
    )
    last_seen = audit_last_seen.combine_first(
        source_last_seen
    )

    first_source = pd.Series(
        [
            row.get("first_seen_source")
            for row in matched_rows
        ],
        index=result.index,
        dtype="object",
    )

    last_source = pd.Series(
        [
            row.get("last_seen_source")
            for row in matched_rows
        ],
        index=result.index,
        dtype="object",
    )

    source_kind = _coalesce_named_column(
        result,
        "_source_kind",
    )

    if source_kind is not None:
        first_source = first_source.combine_first(
            source_kind
        )
        last_source = last_source.combine_first(
            source_kind
        )

    result["_audit_first_seen_at"] = (
        first_seen
    )
    result["_audit_last_seen_at"] = (
        last_seen
    )
    result["_audit_first_seen_source"] = (
        first_source
    )
    result["_audit_last_seen_source"] = (
        last_source
    )

    result["_ingestion_status"] = (
        first_source
        .fillna("")
        .eq("new-only-export")
        .map(
            {
                True: "NEW",
                False: "EXISTING",
            }
        )
    )

    actual_closed = _datetime_series(
        result,
        (
            "closing_display",
            "closing_sort",
            "closed_sort",
            "closing_at",
            "ended_at",
        ),
    )

    activity = actual_closed.combine_first(
        first_seen
    )

    result["_actual_closed_at"] = (
        actual_closed
    )
    result["_activity_sort"] = activity
    result["_activity_display"] = activity
    result["_activity_date_basis"] = (
        actual_closed.notna().map(
            {
                True: "CLOSED",
                False: "ADDED",
            }
        )
    )
    result["_is_recent_addition"] = (
        first_source
        .fillna("")
        .eq("new-only-export")
    )

    result.sort_values(
        by=[
            "_activity_sort",
            "listing_id",
        ],
        ascending=[
            False,
            True,
        ],
        na_position="last",
        inplace=True,
        kind="stable",
    )

    result.reset_index(
        drop=True,
        inplace=True,
    )

    return result
