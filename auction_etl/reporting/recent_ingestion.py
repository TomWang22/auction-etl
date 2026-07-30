"""Recent-ingestion classification, filtering, and CSV reporting."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


Identity = tuple[str, str]

AUDIT_FIELDS = (
    "first_seen_at",
    "last_seen_at",
    "first_seen_run_id",
    "last_seen_run_id",
    "first_seen_source",
    "last_seen_source",
    "display_media_type",
)

REPORT_PRESETS: dict[str, tuple[str, ...]] = {
    "Recent additions": (
        "marketplace",
        "listing_id",
        "first_seen_at",
        "ended_at",
        "seller",
        "artist",
        "title",
        "display_media_type",
        "effective_catalog_number",
        "bid_count",
        "final_price",
        "gross_price",
        "currency",
        "effective_verdict",
        "auction_url",
    ),
    "Collector review": (
        "marketplace",
        "listing_id",
        "first_seen_at",
        "ended_at",
        "seller",
        "artist",
        "title",
        "display_media_type",
        "effective_catalog_number",
        "effective_region",
        "effective_disc_count",
        "effective_bulk_lot",
        "effective_obi",
        "effective_insert_present",
        "effective_poster_present",
        "effective_promo",
        "effective_sealed",
        "effective_reissue",
        "effective_first_press",
        "effective_importance_score",
        "effective_verdict",
        "effective_condition_media",
        "effective_condition_cover",
        "manual_collector_notes",
        "auction_url",
    ),
    "Pricing": (
        "marketplace",
        "listing_id",
        "first_seen_at",
        "ended_at",
        "seller",
        "title",
        "display_media_type",
        "bid_count",
        "start_price",
        "final_price",
        "shipping_price",
        "tax_amount",
        "gross_price",
        "currency",
        "fx_rate_to_usd",
        "final_price_usd",
        "shipping_price_usd",
        "tax_usd",
        "gross_price_usd",
        "landed_price_usd",
        "auction_url",
    ),
    "Compact": (
        "marketplace",
        "listing_id",
        "first_seen_at",
        "ended_at",
        "seller",
        "title",
        "display_media_type",
        "final_price",
        "gross_price",
        "currency",
        "auction_url",
    ),
}


@dataclass(frozen=True)
class IdentityClassification:
    """Identity-set comparison for one ingestion snapshot."""

    baseline: frozenset[Identity]
    warehouse: frozenset[Identity]
    staging: frozenset[Identity]
    newly_ingested: frozenset[Identity]
    pending: frozenset[Identity]
    refreshed_existing: frozenset[Identity]
    missing_from_warehouse: frozenset[Identity]


@dataclass(frozen=True)
class QueryFilters:
    """Filters available to reports and the Streamlit UI."""

    marketplaces: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    added_from: date | None = None
    added_to: date | None = None
    ended_from: date | None = None
    ended_to: date | None = None
    recent_days: int | None = None
    seller: str | None = None
    search: str | None = None
    limit: int = 5_000


@dataclass(frozen=True)
class CSVExportOptions:
    """Formatting controls for generated delimited reports."""

    delimiter: str = ","
    quote_style: str = "minimal"
    include_bom: bool = True
    date_format: str = "iso"
    decimal_places: int = 2
    null_text: str = ""
    line_ending: str = "\n"


def normalize_database_url(database_url: str) -> str:
    """Convert SQLAlchemy PostgreSQL URLs into Psycopg URLs."""
    normalized = database_url.strip()

    replacements = (
        ("postgresql+psycopg://", "postgresql://"),
        ("postgresql+psycopg2://", "postgresql://"),
    )

    for prefix, replacement in replacements:
        if normalized.startswith(prefix):
            return replacement + normalized[len(prefix) :]

    return normalized


def classify_identities(
    baseline: Iterable[Identity],
    warehouse: Iterable[Identity],
    staging: Iterable[Identity],
) -> IdentityClassification:
    """Classify new, pending, refreshed, and missing identities."""
    baseline_set = frozenset(baseline)
    warehouse_set = frozenset(warehouse)
    staging_set = frozenset(staging)

    return IdentityClassification(
        baseline=baseline_set,
        warehouse=warehouse_set,
        staging=staging_set,
        newly_ingested=warehouse_set - baseline_set,
        pending=staging_set - warehouse_set,
        refreshed_existing=staging_set & baseline_set,
        missing_from_warehouse=baseline_set - warehouse_set,
    )


def load_identity_csv(path: Path) -> frozenset[Identity]:
    """Read marketplace/listing identities from a CSV file."""
    identities: set[Identity] = set()

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            marketplace = str(
                row.get("marketplace") or ""
            ).strip()
            listing_id = str(
                row.get("listing_id") or ""
            ).strip()

            if marketplace and listing_id:
                identities.add(
                    (marketplace, listing_id)
                )

    return frozenset(identities)


def relation_columns(
    connection: psycopg.Connection,
    schema: str,
    relation: str,
) -> tuple[str, ...]:
    """Return relation columns in ordinal order."""
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, relation),
    ).fetchall()

    return tuple(
        str(row["column_name"])
        for row in rows
    )


def available_report_columns(
    connection: psycopg.Connection,
) -> tuple[str, ...]:
    """Return all selectable view and virtual audit columns."""
    view_columns = relation_columns(
        connection,
        "warehouse",
        "auction_collector_review",
    )

    ordered = list(view_columns)

    for field in AUDIT_FIELDS:
        if field not in ordered:
            ordered.append(field)

    return tuple(ordered)


def ensure_ingestion_audit_schema(
    connection: psycopg.Connection,
) -> None:
    """Install the durable first-seen/last-seen identity audit."""
    connection.execute(
        """
        CREATE SCHEMA IF NOT EXISTS system
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS
            system.auction_ingestion_identity
        (
            marketplace VARCHAR NOT NULL,
            listing_id VARCHAR NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL,
            first_seen_run_id TEXT,
            last_seen_run_id TEXT,
            first_seen_source TEXT NOT NULL,
            last_seen_source TEXT NOT NULL,
            PRIMARY KEY (
                marketplace,
                listing_id
            )
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_auction_ingestion_identity_first_seen
        ON system.auction_ingestion_identity (
            first_seen_at DESC
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_auction_ingestion_identity_last_seen
        ON system.auction_ingestion_identity (
            last_seen_at DESC
        )
        """
    )


def backfill_ingestion_audit(
    connection: psycopg.Connection,
) -> int:
    """Backfill identities that predate the audit table."""
    result = connection.execute(
        """
        INSERT INTO system.auction_ingestion_identity (
            marketplace,
            listing_id,
            first_seen_at,
            last_seen_at,
            first_seen_run_id,
            last_seen_run_id,
            first_seen_source,
            last_seen_source
        )
        SELECT
            marketplace,
            listing_id,
            COALESCE(
                created_at,
                ended_at,
                NOW()
            ),
            COALESCE(
                created_at,
                ended_at,
                NOW()
            ),
            'warehouse-backfill',
            'warehouse-backfill',
            'warehouse-backfill',
            'warehouse-backfill'
        FROM warehouse.auction
        ON CONFLICT (
            marketplace,
            listing_id
        )
        DO NOTHING
        """
    )

    return int(result.rowcount or 0)


def _parse_run_timestamp(path: Path) -> datetime:
    """Infer an export run time from its directory name."""
    patterns = (
        ("%Y%m%d-%H%M%S", r"^\d{8}-\d{6}$"),
        ("%Y%m%d_%H%M%S", r"^\d{8}_\d{6}$"),
    )

    for format_string, pattern in patterns:
        if re.match(pattern, path.name):
            parsed = datetime.strptime(
                path.name,
                format_string,
            )

            return parsed.replace(
                tzinfo=timezone.utc,
            )

    return datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone.utc,
    )


def _read_export_identities(
    path: Path,
) -> list[Identity]:
    """Read identity rows from one export CSV."""
    if not path.is_file() or path.stat().st_size == 0:
        return []

    return sorted(load_identity_csv(path))



def partition_export_identities(
    newly_ingested: Iterable[Identity],
    refreshed_existing: Iterable[Identity],
) -> tuple[
    tuple[Identity, ...],
    tuple[Identity, ...],
]:
    """Return deterministic, mutually exclusive export identities."""
    new_identities = frozenset(
        newly_ingested
    )
    refreshed_identities = (
        frozenset(refreshed_existing)
        - new_identities
    )

    return (
        tuple(sorted(new_identities)),
        tuple(sorted(refreshed_identities)),
    )


def seed_audit_from_export_directory(
    connection: psycopg.Connection,
    export_directory: Path,
    *,
    run_id: str | None = None,
) -> dict[str, int]:
    """Record newly ingested and refreshed identities from an export."""
    run_timestamp = _parse_run_timestamp(
        export_directory
    )
    effective_run_id = run_id or export_directory.name

    newly_ingested: list[Identity] = []
    refreshed: list[Identity] = []

    for marketplace in ("buyee", "ebay"):
        newly_ingested.extend(
            _read_export_identities(
                export_directory
                / f"newly_ingested_{marketplace}.csv"
            )
        )
        refreshed.extend(
            _read_export_identities(
                export_directory
                / f"refreshed_existing_{marketplace}.csv"
            )
        )

    newly_ingested, refreshed = (
        partition_export_identities(
            newly_ingested,
            refreshed,
        )
    )

    for marketplace, listing_id in newly_ingested:
        connection.execute(
            """
            INSERT INTO system.auction_ingestion_identity (
                marketplace,
                listing_id,
                first_seen_at,
                last_seen_at,
                first_seen_run_id,
                last_seen_run_id,
                first_seen_source,
                last_seen_source
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'new-only-export',
                'new-only-export'
            )
            ON CONFLICT (
                marketplace,
                listing_id
            )
            DO UPDATE SET
                first_seen_at = EXCLUDED.first_seen_at,
                first_seen_run_id = EXCLUDED.first_seen_run_id,
                first_seen_source = EXCLUDED.first_seen_source,
                last_seen_at = GREATEST(
                    system.auction_ingestion_identity.last_seen_at,
                    EXCLUDED.last_seen_at
                ),
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                last_seen_source = EXCLUDED.last_seen_source
            """,
            (
                marketplace,
                listing_id,
                run_timestamp,
                run_timestamp,
                effective_run_id,
                effective_run_id,
            ),
        )

    for marketplace, listing_id in refreshed:
        connection.execute(
            """
            UPDATE system.auction_ingestion_identity
            SET
                last_seen_at = GREATEST(
                    last_seen_at,
                    %s
                ),
                last_seen_run_id = %s,
                last_seen_source = 'refreshed-export'
            WHERE marketplace = %s
              AND listing_id = %s
            """,
            (
                run_timestamp,
                effective_run_id,
                marketplace,
                listing_id,
            ),
        )

    return {
        "newly_ingested": len(newly_ingested),
        "refreshed_existing": len(refreshed),
    }


def get_media_types(
    connection: psycopg.Connection,
) -> tuple[str, ...]:
    """Return effective media types currently represented."""
    rows = connection.execute(
        """
        SELECT DISTINCT
            COALESCE(
                effective_media_type,
                media_type,
                'UNKNOWN'
            ) AS media_type
        FROM warehouse.auction_collector_review
        ORDER BY media_type
        """
    ).fetchall()

    return tuple(
        str(row["media_type"])
        for row in rows
        if row["media_type"]
    )


def _audit_expression(field: str) -> sql.Composable:
    """Build one virtual audit-field expression."""
    expressions: dict[str, sql.Composable] = {
        "first_seen_at": sql.SQL(
            "COALESCE(i.first_seen_at, r.created_at) "
            "AS first_seen_at"
        ),
        "last_seen_at": sql.SQL(
            "COALESCE(i.last_seen_at, r.created_at) "
            "AS last_seen_at"
        ),
        "first_seen_run_id": sql.SQL(
            "i.first_seen_run_id AS first_seen_run_id"
        ),
        "last_seen_run_id": sql.SQL(
            "i.last_seen_run_id AS last_seen_run_id"
        ),
        "first_seen_source": sql.SQL(
            "i.first_seen_source AS first_seen_source"
        ),
        "last_seen_source": sql.SQL(
            "i.last_seen_source AS last_seen_source"
        ),
        "display_media_type": sql.SQL(
            "COALESCE("
            "r.effective_media_type, "
            "r.media_type, "
            "'UNKNOWN'"
            ") AS display_media_type"
        ),
    }

    return expressions[field]


def get_report_rows(
    connection: psycopg.Connection,
    *,
    columns: Sequence[str],
    filters: QueryFilters | None = None,
) -> list[dict[str, Any]]:
    """Read filtered collector-review rows using safe identifiers."""
    effective_filters = filters or QueryFilters()
    available = set(
        available_report_columns(connection)
    )

    selected = [
        column
        for column in columns
        if column in available
    ]

    if not selected:
        raise ValueError(
            "No valid report columns were selected."
        )

    select_fragments: list[sql.Composable] = []

    for column in selected:
        if column in AUDIT_FIELDS:
            select_fragments.append(
                _audit_expression(column)
            )
        else:
            select_fragments.append(
                sql.SQL("r.{}").format(
                    sql.Identifier(column)
                )
            )

    where_fragments: list[sql.Composable] = []
    parameters: list[Any] = []

    if effective_filters.marketplaces:
        where_fragments.append(
            sql.SQL("r.marketplace = ANY(%s)")
        )
        parameters.append(
            list(effective_filters.marketplaces)
        )

    if effective_filters.media_types:
        where_fragments.append(
            sql.SQL(
                "COALESCE("
                "r.effective_media_type, "
                "r.media_type, "
                "'UNKNOWN'"
                ") = ANY(%s)"
            )
        )
        parameters.append(
            list(effective_filters.media_types)
        )

    if effective_filters.added_from:
        where_fragments.append(
            sql.SQL(
                "COALESCE("
                "i.first_seen_at, "
                "r.created_at"
                ")::date >= %s"
            )
        )
        parameters.append(
            effective_filters.added_from
        )

    if effective_filters.added_to:
        where_fragments.append(
            sql.SQL(
                "COALESCE("
                "i.first_seen_at, "
                "r.created_at"
                ")::date <= %s"
            )
        )
        parameters.append(
            effective_filters.added_to
        )

    if effective_filters.ended_from:
        where_fragments.append(
            sql.SQL("r.ended_at::date >= %s")
        )
        parameters.append(
            effective_filters.ended_from
        )

    if effective_filters.ended_to:
        where_fragments.append(
            sql.SQL("r.ended_at::date <= %s")
        )
        parameters.append(
            effective_filters.ended_to
        )

    if effective_filters.recent_days is not None:
        recent_days = max(
            0,
            int(effective_filters.recent_days),
        )

        where_fragments.append(
            sql.SQL(
                "COALESCE("
                "i.first_seen_at, "
                "r.created_at"
                ") >= NOW() - make_interval(days => %s)"
            )
        )
        parameters.append(recent_days)

    if effective_filters.seller:
        where_fragments.append(
            sql.SQL("r.seller ILIKE %s")
        )
        parameters.append(
            f"%{effective_filters.seller.strip()}%"
        )

    if effective_filters.search:
        search_value = (
            f"%{effective_filters.search.strip()}%"
        )

        where_fragments.append(
            sql.SQL(
                "("
                "r.title ILIKE %s "
                "OR r.artist ILIKE %s "
                "OR r.seller ILIKE %s "
                "OR r.listing_id ILIKE %s "
                "OR r.catalog_number ILIKE %s "
                "OR r.effective_catalog_number ILIKE %s"
                ")"
            )
        )

        parameters.extend(
            [search_value] * 6
        )

    query = sql.SQL(
        """
        SELECT {columns}
        FROM warehouse.auction_collector_review AS r
        LEFT JOIN system.auction_ingestion_identity AS i
          ON i.marketplace = r.marketplace
         AND i.listing_id = r.listing_id
        """
    ).format(
        columns=sql.SQL(", ").join(
            select_fragments
        )
    )

    if where_fragments:
        query += sql.SQL(" WHERE ")
        query += sql.SQL(" AND ").join(
            where_fragments
        )

    query += sql.SQL(
        """
        ORDER BY
            COALESCE(
                i.first_seen_at,
                r.created_at
            ) DESC NULLS LAST,
            r.ended_at DESC NULLS LAST,
            r.marketplace,
            r.listing_id
        LIMIT %s
        """
    )

    parameters.append(
        max(
            1,
            min(
                int(effective_filters.limit),
                100_000,
            ),
        )
    )

    rows = connection.execute(
        query,
        parameters,
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def _format_date_value(
    value: date | datetime,
    date_format: str,
) -> str:
    """Format dates according to an export preference."""
    formats = {
        "iso": "%Y-%m-%dT%H:%M:%S%z",
        "date": "%Y-%m-%d",
        "us": "%m/%d/%Y",
        "eu": "%d/%m/%Y",
    }

    selected = formats.get(
        date_format,
        formats["iso"],
    )

    return value.strftime(selected)


def _format_scalar(
    value: Any,
    options: CSVExportOptions,
) -> Any:
    """Convert one value into a stable exported representation."""
    if value is None:
        return options.null_text

    if isinstance(value, datetime):
        return _format_date_value(
            value,
            options.date_format,
        )

    if isinstance(value, date):
        return _format_date_value(
            value,
            options.date_format,
        )

    if isinstance(value, Decimal):
        return f"{value:.{options.decimal_places}f}"

    if isinstance(value, float):
        return f"{value:.{options.decimal_places}f}"

    if isinstance(value, bool):
        return "true" if value else "false"

    return value


def write_formatted_csv(
    rows: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str],
    options: CSVExportOptions | None = None,
    header_aliases: Mapping[str, str] | None = None,
) -> bytes:
    """Render rows as configurable CSV/TSV bytes."""
    effective_options = (
        options or CSVExportOptions()
    )
    aliases = dict(header_aliases or {})

    quote_styles = {
        "minimal": csv.QUOTE_MINIMAL,
        "all": csv.QUOTE_ALL,
        "nonnumeric": csv.QUOTE_NONNUMERIC,
        "none": csv.QUOTE_NONE,
    }

    quoting = quote_styles.get(
        effective_options.quote_style,
        csv.QUOTE_MINIMAL,
    )

    output = io.StringIO(
        newline="",
    )

    writer = csv.writer(
        output,
        delimiter=effective_options.delimiter,
        quoting=quoting,
        escapechar=(
            "\\"
            if quoting == csv.QUOTE_NONE
            else None
        ),
        lineterminator=effective_options.line_ending,
    )

    writer.writerow(
        [
            aliases.get(column, column)
            for column in columns
        ]
    )

    for row in rows:
        writer.writerow(
            [
                _format_scalar(
                    row.get(column),
                    effective_options,
                )
                for column in columns
            ]
        )

    encoding = (
        "utf-8-sig"
        if effective_options.include_bom
        else "utf-8"
    )

    return output.getvalue().encode(
        encoding
    )


def connect(
    database_url: str,
) -> psycopg.Connection:
    """Open a dictionary-row Psycopg connection."""
    return psycopg.connect(
        normalize_database_url(database_url),
        row_factory=dict_row,
    )
