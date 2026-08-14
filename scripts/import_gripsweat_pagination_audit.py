"""Import read-only Gripsweat pagination-audit results.

The importer creates one normalized row per configured source and numeric
Gripsweat item ID. Existing detail enrichment is preserved.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from auction_etl.database.session import engine


DEFAULT_INPUT = Path(
    "logs/gripsweat/pagination-audit/"
    "gripsweat_pagination_audit.json"
)

NUMERIC_ID_PATTERN = re.compile(r"^[0-9]{6,20}$")


@dataclass(frozen=True, slots=True)
class AuditItem:
    """One normalized Gripsweat search result."""

    source_name: str
    configured_artist: str
    gripsweat_item_id: str
    gripsweat_url: str
    source_page: int


@dataclass(slots=True)
class ImportStats:
    """Import counters."""

    attempted: int = 0
    unique_items: int = 0
    inserted: int = 0
    matched: int = 0
    updated_identity: int = 0
    invalid: int = 0


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Import normalized items from the read-only "
            "Gripsweat pagination audit."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count rows without database writes.",
    )
    return parser.parse_args()


def normalize_item_url(value: str) -> str | None:
    """Validate and normalize one Gripsweat item URL."""
    cleaned = value.strip()

    if not cleaned:
        return None

    parsed = urlparse(cleaned)

    if parsed.scheme not in {"http", "https"}:
        return None

    if (parsed.hostname or "").casefold() not in {
        "gripsweat.com",
        "www.gripsweat.com",
    }:
        return None

    segments = [
        segment
        for segment in parsed.path.split("/")
        if segment
    ]

    if len(segments) < 2 or segments[0] != "item":
        return None

    if not NUMERIC_ID_PATTERN.fullmatch(segments[1]):
        return None

    return cleaned


def item_id_from_url(value: str) -> str | None:
    """Extract the stable numeric Gripsweat item ID."""
    normalized = normalize_item_url(value)

    if normalized is None:
        return None

    segments = [
        segment
        for segment in urlparse(normalized).path.split("/")
        if segment
    ]

    return segments[1]


def load_items(path: Path) -> tuple[list[AuditItem], int]:
    """Load and deduplicate audit items."""
    if not path.exists():
        raise FileNotFoundError(
            f"Pagination audit not found: {path}"
        )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not payload.get("read_only"):
        raise ValueError(
            "Input is not marked as a read-only audit."
        )

    items: dict[tuple[str, str], AuditItem] = {}
    attempted = 0

    for source in payload.get("sources", []):
        source_name = str(
            source.get("source_name") or ""
        ).strip()
        artist = str(
            source.get("artist") or ""
        ).strip()

        if not source_name or not artist:
            continue

        for page in source.get("pages", []):
            if page.get("error"):
                continue

            page_number = int(
                page.get("requested_page") or 0
            )
            item_ids = page.get("item_ids") or []
            item_urls = page.get("item_urls") or []

            urls_by_id: dict[str, str] = {}

            for url in item_urls:
                attempted += 1

                normalized_url = normalize_item_url(
                    str(url)
                )

                if normalized_url is None:
                    continue

                numeric_id = item_id_from_url(
                    normalized_url
                )

                if numeric_id is not None:
                    urls_by_id[numeric_id] = (
                        normalized_url
                    )

            for raw_item_id in item_ids:
                item_id = str(raw_item_id).strip()

                if not NUMERIC_ID_PATTERN.fullmatch(
                    item_id
                ):
                    continue

                url = urls_by_id.get(item_id)

                if url is None:
                    continue

                key = (
                    source_name,
                    item_id,
                )

                items.setdefault(
                    key,
                    AuditItem(
                        source_name=source_name,
                        configured_artist=artist,
                        gripsweat_item_id=item_id,
                        gripsweat_url=url,
                        source_page=page_number,
                    ),
                )

    return list(items.values()), attempted


def table_columns(
    connection: Connection,
    table_name: str,
) -> set[str]:
    """Return columns for one warehouse table."""
    inspector = inspect(connection)

    return {
        str(column["name"])
        for column in inspector.get_columns(
            table_name,
            schema="warehouse",
        )
    }


def ensure_required_tables(
    connection: Connection,
) -> None:
    """Confirm the normalized Gripsweat tables exist."""
    inspector = inspect(connection)

    tables = set(
        inspector.get_table_names(
            schema="warehouse"
        )
    )

    required = {
        "gripsweat_source",
        "gripsweat_sale",
    }
    missing = sorted(required - tables)

    if missing:
        raise RuntimeError(
            "Missing Gripsweat tables: "
            + ", ".join(missing)
        )


def ensure_item_id_column(
    connection: Connection,
    columns: set[str],
) -> set[str]:
    """Add the stable numeric item-ID column when absent."""
    if "gripsweat_item_id" in columns:
        return columns

    connection.execute(
        text(
            """
            ALTER TABLE warehouse.gripsweat_sale
            ADD COLUMN gripsweat_item_id VARCHAR(32)
            """
        )
    )

    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_gripsweat_sale_source_numeric_item
            ON warehouse.gripsweat_sale (
                source_name,
                gripsweat_item_id
            )
            WHERE gripsweat_item_id IS NOT NULL
            """
        )
    )

    return table_columns(
        connection,
        "gripsweat_sale",
    )


def upsert_source(
    connection: Connection,
    item: AuditItem,
    source_columns: set[str],
) -> int:
    """Resolve one initialized configured source without mutating it."""
    # GRIPSWEAT_PAGINATION_SOURCE_EXISTENCE_CONTRACT_V1
    # GRIPSWEAT_PAGINATION_SOURCE_ID_RESOLUTION_CONTRACT_V1

    if "source_name" in source_columns:
        identity_column = "source_name"
    elif "name" in source_columns:
        identity_column = "name"
    else:
        raise RuntimeError(
            "warehouse.gripsweat_source has no "
            "supported identity column."
        )

    if "id" not in source_columns:
        raise RuntimeError(
            "warehouse.gripsweat_source has no id column."
        )

    source_id = connection.execute(
        text(
            f"""
            SELECT id
            FROM warehouse.gripsweat_source
            WHERE {identity_column} = :identity_value
            """
        ),
        {
            "identity_value": item.source_name,
        },
    ).scalar_one_or_none()

    if source_id is None:
        raise RuntimeError(
            "Gripsweat source is not initialized: "
            f"{item.source_name}"
        )

    return int(source_id)


def source_query_for_source_id(
    connection: Connection,
    source_id: int,
) -> str:
    """Return the initialized search query for one source row."""
    # GRIPSWEAT_PAGINATION_SALE_PROVENANCE_CONTRACT_V1

    source_query = connection.execute(
        text(
            """
            SELECT search_query
            FROM warehouse.gripsweat_source
            WHERE id = :source_id
            """
        ),
        {
            "source_id": source_id,
        },
    ).scalar_one_or_none()

    if source_query is None:
        raise RuntimeError(
            "Initialized Gripsweat source has no search query: "
            f"{source_id}"
        )

    source_query_text = str(
        source_query
    )

    if not source_query_text.strip():
        raise RuntimeError(
            "Initialized Gripsweat source has a blank search query: "
            f"{source_id}"
        )

    return source_query_text


def find_existing_sale(
    connection: Connection,
    item: AuditItem,
    sale_columns: set[str],
) -> dict[str, Any] | None:
    """Find an existing row by numeric ID, URL, or old key."""
    predicates: list[str] = []
    parameters: dict[str, Any] = {
        "source_name": item.source_name,
        "item_id": item.gripsweat_item_id,
        "url": item.gripsweat_url,
    }

    if {
        "source_name",
        "gripsweat_item_id",
    }.issubset(sale_columns):
        predicates.append(
            """
            (
                source_name = :source_name
                AND gripsweat_item_id = :item_id
            )
            """
        )

    if "gripsweat_url" in sale_columns:
        predicates.append(
            "gripsweat_url = :url"
        )

    if {
        "source_name",
        "gripsweat_item_key",
    }.issubset(sale_columns):
        predicates.append(
            """
            (
                source_name = :source_name
                AND gripsweat_item_key = :item_id
            )
            """
        )

    if not predicates:
        raise RuntimeError(
            "warehouse.gripsweat_sale has no "
            "supported identity columns."
        )

    row = connection.execute(
        text(
            f"""
            SELECT *
            FROM warehouse.gripsweat_sale
            WHERE {" OR ".join(predicates)}
            ORDER BY id
            LIMIT 1
            """
        ),
        parameters,
    ).mappings().first()

    return dict(row) if row is not None else None


def identity_values(
    item: AuditItem,
    sale_columns: set[str],
) -> dict[str, Any]:
    """Build only non-destructive identity values."""
    candidates: dict[str, Any] = {
        "source_name": item.source_name,
        "configured_artist": item.configured_artist,
        "gripsweat_item_id": item.gripsweat_item_id,
        "gripsweat_item_key": item.gripsweat_item_id,
        "gripsweat_url": item.gripsweat_url,
        "source_page": item.source_page,
    }

    return {
        key: value
        for key, value in candidates.items()
        if key in sale_columns
    }


def update_existing_sale(
    connection: Connection,
    row_id: Any,
    values: dict[str, Any],
) -> int:
    """Fill missing identity fields without replacing detail data."""
    assignments = [
        f"{column} = COALESCE({column}, :{column})"
        for column in values
        if column != "id"
    ]

    if not assignments:
        return 0

    result = connection.execute(
        text(
            f"""
            UPDATE warehouse.gripsweat_sale
            SET
                {", ".join(assignments)}
            WHERE id = :row_id
            """
        ),
        {
            "row_id": row_id,
            **values,
        },
    )

    return int(result.rowcount or 0)


def insert_sale(
    connection: Connection,
    values: dict[str, Any],
) -> None:
    """Insert one minimal normalized sale identity."""
    columns_sql = ", ".join(values)
    values_sql = ", ".join(
        f":{column}"
        for column in values
    )

    connection.execute(
        text(
            f"""
            INSERT INTO warehouse.gripsweat_sale (
                {columns_sql}
            )
            VALUES (
                {values_sql}
            )
            """
        ),
        values,
    )


def print_expected_counts(
    items: list[AuditItem],
) -> None:
    """Print input counts by configured artist."""
    counts: dict[str, int] = {}

    for item in items:
        counts[item.configured_artist] = (
            counts.get(
                item.configured_artist,
                0,
            )
            + 1
        )

    print()
    print("Pagination audit input")
    print("----------------------")

    for artist, count in sorted(
        counts.items()
    ):
        print(f"{artist:20}: {count}")

    print(f"{'total':20}: {len(items)}")


def main() -> int:
    """Import the pagination audit."""
    args = parse_args()
    items, attempted = load_items(
        args.input
    )

    stats = ImportStats(
        attempted=attempted,
        unique_items=len(items),
    )

    if not items:
        raise SystemExit(
            "No valid numeric Gripsweat items were found."
        )

    print_expected_counts(items)

    if args.dry_run:
        print()
        print("DRY RUN")
        print("-------")
        print("No database rows were changed.")
        print("Item URL attempts:", stats.attempted)
        print("Unique items     :", stats.unique_items)
        return 0

    source_ids: dict[str, int] = {}
    source_queries: dict[str, str] = {}

    with engine.begin() as connection:
        ensure_required_tables(connection)

        source_columns = table_columns(
            connection,
            "gripsweat_source",
        )
        sale_columns = table_columns(
            connection,
            "gripsweat_sale",
        )
        sale_columns = ensure_item_id_column(
            connection,
            sale_columns,
        )

        if "source_id" not in sale_columns:
            raise RuntimeError(
                "warehouse.gripsweat_sale has no source_id column."
            )

        if "search_query" not in source_columns:
            raise RuntimeError(
                "warehouse.gripsweat_source has no search_query column."
            )

        for required_column in (
            "source_query",
            "page_number",
            "source_position",
        ):
            if required_column not in sale_columns:
                raise RuntimeError(
                    "warehouse.gripsweat_sale has no "
                    f"{required_column} column."
                )

        for item in items:
            if item.source_name not in source_ids:
                source_ids[
                    item.source_name
                ] = upsert_source(
                    connection,
                    item,
                    source_columns,
                )

            values = identity_values(
                item,
                sale_columns,
            )

            if not {
                "source_name",
                "gripsweat_url",
            }.issubset(values):
                raise RuntimeError(
                    "Sale table is missing source_name "
                    "or gripsweat_url."
                )

            existing = find_existing_sale(
                connection,
                item,
                sale_columns,
            )

            if existing is not None:
                stats.matched += 1
                stats.updated_identity += (
                    update_existing_sale(
                        connection,
                        existing["id"],
                        values,
                    )
                )
                continue

            if item.source_name not in source_queries:
                source_queries[
                    item.source_name
                ] = source_query_for_source_id(
                    connection,
                    source_ids[
                        item.source_name
                    ],
                )

            if item.source_page <= 0:
                raise RuntimeError(
                    "Gripsweat source page must be positive: "
                    f"{item.source_page!r}"
                )

            values["source_query"] = source_queries[
                item.source_name
            ]
            values["page_number"] = item.source_page
            values["source_position"] = None

            values["source_id"] = source_ids[
                item.source_name
            ]

            insert_sale(
                connection,
                values,
            )
            stats.inserted += 1

    print()
    print("Gripsweat pagination import")
    print("---------------------------")
    print("URL attempts    :", stats.attempted)
    print("Unique items    :", stats.unique_items)
    print("Inserted        :", stats.inserted)
    print("Already matched :", stats.matched)
    print("Identity updated:", stats.updated_identity)
    print("Invalid         :", stats.invalid)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
