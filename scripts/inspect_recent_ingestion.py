"""Inspect recent warehouse ingestion and generate export files."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from psycopg import sql

from auction_etl.reporting.recent_ingestion import (
    CSVExportOptions,
    QueryFilters,
    REPORT_PRESETS,
    available_report_columns,
    classify_identities,
    connect,
    get_report_rows,
    load_identity_csv,
    write_formatted_csv,
)


def parse_date(value: str) -> date:
    """Parse an ISO calendar date."""
    return date.fromisoformat(value)


def parse_args() -> argparse.Namespace:
    """Parse inspection and export options."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare baseline, staging, and warehouse "
            "identities and generate filtered reports."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            (
                "postgresql://auction:auction@"
                "127.0.0.1:5544/auction_warehouse"
            ),
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--marketplace",
        action="append",
        choices=("buyee", "ebay"),
    )
    parser.add_argument(
        "--media-type",
        action="append",
    )
    parser.add_argument(
        "--added-from",
        type=parse_date,
    )
    parser.add_argument(
        "--added-to",
        type=parse_date,
    )
    parser.add_argument(
        "--ended-from",
        type=parse_date,
    )
    parser.add_argument(
        "--ended-to",
        type=parse_date,
    )
    parser.add_argument(
        "--recent-days",
        type=int,
    )
    parser.add_argument(
        "--seller",
    )
    parser.add_argument(
        "--search",
    )
    parser.add_argument(
        "--preset",
        choices=tuple(REPORT_PRESETS),
        default="Recent additions",
    )
    parser.add_argument(
        "--fields",
        help="Comma-separated field list.",
    )
    parser.add_argument(
        "--delimiter",
        choices=("comma", "tab", "semicolon", "pipe"),
        default="comma",
    )
    parser.add_argument(
        "--quote-style",
        choices=("minimal", "all", "nonnumeric", "none"),
        default="minimal",
    )
    parser.add_argument(
        "--no-bom",
        action="store_true",
    )
    parser.add_argument(
        "--date-format",
        choices=("iso", "date", "us", "eu"),
        default="iso",
    )
    parser.add_argument(
        "--decimal-places",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--null-text",
        default="",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5_000,
    )

    return parser.parse_args()


def discover_baseline() -> Path:
    """Find the newest preserved pre-ingestion identity snapshot."""
    patterns = (
        "logs/latest-refresh/**/auction-keys-before.csv",
        "logs/all-source-refresh/**/auction-keys-before.csv",
    )

    candidates: list[Path] = []

    for pattern in patterns:
        candidates.extend(
            Path(".").glob(pattern)
        )

    existing = [
        path
        for path in candidates
        if path.is_file()
        and path.stat().st_size > 0
    ]

    if not existing:
        raise RuntimeError(
            "No auction identity baseline was found."
        )

    return max(
        existing,
        key=lambda path: path.stat().st_mtime,
    )


def read_relation_identities(
    connection,
    schema: str,
    relation: str,
) -> frozenset[tuple[str, str]]:
    """Read marketplace/listing keys from one relation."""
    rows = connection.execute(
        sql.SQL(
            """
            SELECT DISTINCT
                marketplace,
                listing_id
            FROM {}.{}
            WHERE marketplace IS NOT NULL
              AND listing_id IS NOT NULL
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(relation),
        )
    ).fetchall()

    return frozenset(
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in rows
    )


def filter_rows_by_identities(
    rows: Iterable[dict[str, Any]],
    identities: frozenset[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Select rows matching an identity set."""
    return [
        row
        for row in rows
        if (
            str(row.get("marketplace") or ""),
            str(row.get("listing_id") or ""),
        )
        in identities
    ]


def write_rows(
    path: Path,
    rows: list[dict[str, Any]],
    columns: list[str],
    options: CSVExportOptions,
) -> None:
    """Write one formatted report file."""
    payload = write_formatted_csv(
        rows,
        columns=columns,
        options=options,
    )

    path.write_bytes(payload)


def write_pending_rows(
    connection,
    path: Path,
    identities: frozenset[tuple[str, str]],
    options: CSVExportOptions,
) -> None:
    """Export pending staging rows without assuming every column."""
    columns = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'staging'
          AND table_name = 'listing'
        ORDER BY ordinal_position
        """
    ).fetchall()

    available = {
        str(row["column_name"])
        for row in columns
    }

    preferred = [
        "marketplace",
        "listing_id",
        "seller",
        "artist",
        "title",
        "media_type",
        "catalog_number",
        "bid_count",
        "final_price",
        "gross_price",
        "currency",
        "ended_at",
        "auction_url",
        "created_at",
    ]

    selected = [
        column
        for column in preferred
        if column in available
    ]

    if not identities:
        write_rows(
            path,
            [],
            selected or [
                "marketplace",
                "listing_id",
            ],
            options,
        )
        return

    query = sql.SQL(
        """
        SELECT {columns}
        FROM staging.listing
        WHERE (marketplace, listing_id) = ANY(%s)
        ORDER BY marketplace, listing_id
        """
    ).format(
        columns=sql.SQL(", ").join(
            sql.Identifier(column)
            for column in selected
        )
    )

    rows = connection.execute(
        query,
        (list(identities),),
    ).fetchall()

    write_rows(
        path,
        [
            dict(row)
            for row in rows
        ],
        selected,
        options,
    )


def main() -> int:
    """Generate identity classifications and filtered reports."""
    args = parse_args()

    baseline_path = (
        args.baseline
        if args.baseline is not None
        else discover_baseline()
    )

    if not baseline_path.is_file():
        raise SystemExit(
            f"Baseline does not exist: {baseline_path}"
        )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    delimiter_map = {
        "comma": ",",
        "tab": "\t",
        "semicolon": ";",
        "pipe": "|",
    }

    export_options = CSVExportOptions(
        delimiter=delimiter_map[args.delimiter],
        quote_style=args.quote_style,
        include_bom=not args.no_bom,
        date_format=args.date_format,
        decimal_places=max(
            0,
            min(args.decimal_places, 8),
        ),
        null_text=args.null_text,
    )

    with connect(args.database_url) as connection:
        baseline = load_identity_csv(
            baseline_path
        )

        warehouse = read_relation_identities(
            connection,
            "warehouse",
            "auction",
        )
        staging = read_relation_identities(
            connection,
            "staging",
            "listing",
        )

        classification = classify_identities(
            baseline,
            warehouse,
            staging,
        )

        available = available_report_columns(
            connection
        )

        if args.fields:
            selected_columns = [
                field.strip()
                for field in args.fields.split(",")
                if field.strip() in available
            ]
        else:
            selected_columns = [
                field
                for field in REPORT_PRESETS[
                    args.preset
                ]
                if field in available
            ]

        required = (
            "marketplace",
            "listing_id",
        )

        for field in reversed(required):
            if field not in selected_columns:
                selected_columns.insert(
                    0,
                    field,
                )

        all_rows = get_report_rows(
            connection,
            columns=selected_columns,
            filters=QueryFilters(
                limit=100_000,
            ),
        )

        filters = QueryFilters(
            marketplaces=tuple(
                args.marketplace or ()
            ),
            media_types=tuple(
                args.media_type or ()
            ),
            added_from=args.added_from,
            added_to=args.added_to,
            ended_from=args.ended_from,
            ended_to=args.ended_to,
            recent_days=args.recent_days,
            seller=args.seller,
            search=args.search,
            limit=args.limit,
        )

        filtered_rows = get_report_rows(
            connection,
            columns=selected_columns,
            filters=filters,
        )

        paths: dict[str, str] = {}

        for marketplace in ("buyee", "ebay"):
            marketplace_new = frozenset(
                identity
                for identity
                in classification.newly_ingested
                if identity[0] == marketplace
            )
            marketplace_refreshed = frozenset(
                identity
                for identity
                in classification.refreshed_existing
                if identity[0] == marketplace
            )
            marketplace_pending = frozenset(
                identity
                for identity
                in classification.pending
                if identity[0] == marketplace
            )

            new_path = (
                output_dir
                / f"newly_ingested_{marketplace}.csv"
            )
            refreshed_path = (
                output_dir
                / f"refreshed_existing_{marketplace}.csv"
            )
            pending_path = (
                output_dir
                / f"pending_{marketplace}.csv"
            )

            write_rows(
                new_path,
                filter_rows_by_identities(
                    all_rows,
                    marketplace_new,
                ),
                selected_columns,
                export_options,
            )
            write_rows(
                refreshed_path,
                filter_rows_by_identities(
                    all_rows,
                    marketplace_refreshed,
                ),
                selected_columns,
                export_options,
            )
            write_pending_rows(
                connection,
                pending_path,
                marketplace_pending,
                export_options,
            )

            paths[
                f"newly_ingested_{marketplace}"
            ] = str(new_path)
            paths[
                f"refreshed_existing_{marketplace}"
            ] = str(refreshed_path)
            paths[
                f"pending_{marketplace}"
            ] = str(pending_path)

        filtered_path = output_dir / "filtered.csv"

        write_rows(
            filtered_path,
            filtered_rows,
            selected_columns,
            export_options,
        )

        media_counter = Counter(
            str(
                row.get("display_media_type")
                or row.get("effective_media_type")
                or row.get("media_type")
                or "UNKNOWN"
            )
            for row in filtered_rows
        )

        media_path = output_dir / "media_breakdown.csv"

        with media_path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ("media_type", "rows")
            )

            for media_type, count in sorted(
                media_counter.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            ):
                writer.writerow(
                    (media_type, count)
                )

    marketplace_summary: dict[str, dict[str, int]] = {}

    for marketplace in ("buyee", "ebay"):
        marketplace_summary[marketplace] = {
            "warehouse": sum(
                1
                for identity in warehouse
                if identity[0] == marketplace
            ),
            "staging": sum(
                1
                for identity in staging
                if identity[0] == marketplace
            ),
            "newly_ingested": sum(
                1
                for identity
                in classification.newly_ingested
                if identity[0] == marketplace
            ),
            "pending": sum(
                1
                for identity
                in classification.pending
                if identity[0] == marketplace
            ),
            "refreshed_existing": sum(
                1
                for identity
                in classification.refreshed_existing
                if identity[0] == marketplace
            ),
        }

    summary = {
        "baseline": str(
            baseline_path.resolve()
        ),
        "report_dir": str(output_dir),
        "baseline_identity_count": len(
            classification.baseline
        ),
        "warehouse_identity_count": len(
            classification.warehouse
        ),
        "staging_identity_count": len(
            classification.staging
        ),
        "missing_from_warehouse": len(
            classification.missing_from_warehouse
        ),
        "filtered_rows": len(filtered_rows),
        "selected_columns": selected_columns,
        "marketplaces": marketplace_summary,
        "media_breakdown": dict(media_counter),
        "paths": {
            **paths,
            "filtered": str(filtered_path),
            "media_breakdown": str(media_path),
        },
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    pointer_path = Path(
        "reports/recent-ingestion/latest.json"
    )
    pointer_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    pointer_path.write_text(
        json.dumps(
            {
                "report_dir": str(output_dir),
                "summary": str(summary_path),
                "baseline": str(
                    baseline_path.resolve()
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("Recent auction ingestion inspection")
    print("===================================")
    print(f"Baseline: {baseline_path.resolve()}")
    print(f"Report  : {output_dir}")

    for marketplace in ("buyee", "ebay"):
        values = marketplace_summary[
            marketplace
        ]

        print()
        print(marketplace.upper())
        print("-" * len(marketplace))
        print(
            f"Warehouse          : "
            f"{values['warehouse']}"
        )
        print(
            f"Staging            : "
            f"{values['staging']}"
        )
        print(
            f"Newly ingested     : "
            f"{values['newly_ingested']}"
        )
        print(
            f"Pending ingestion  : "
            f"{values['pending']}"
        )
        print(
            f"Refreshed existing : "
            f"{values['refreshed_existing']}"
        )

    print()
    print(
        "Filtered report rows: "
        f"{len(filtered_rows)}"
    )
    print(
        "Missing baseline rows: "
        f"{len(classification.missing_from_warehouse)}"
    )

    if classification.missing_from_warehouse:
        raise SystemExit(
            "Baseline identities are missing from the warehouse."
        )

    print("✓ No baseline auction identity was deleted.")
    print("✓ Inspection was read-only.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
