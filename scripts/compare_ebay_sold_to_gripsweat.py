#!/usr/bin/env python3
"""Comb eBay completed/sold URLs against Gripsweat and write a gitignored report.

The overlap notes belong in reports/ (gitignored). Do not add that file to git.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from auction_etl.reporting.main_review_integration import (
    configured_database_url,
)
from auction_etl.services.sold_item_overlap import (
    SoldOverlapReport,
    flag_sold_item_overlaps,
    merge_sold_items,
    sold_item_from_warehouse_auction,
    sold_items_from_structured_artifact,
)


DEFAULT_ARTIFACT = Path(
    "logs/ebay-structured/ebay-structured-headed-20260919T223654Z.json"
)
DEFAULT_OUTPUT = Path("reports/COMMIT_NOTES-ebay-sold-gripsweat-overlap.md")


def parse_args() -> argparse.Namespace:
    """Parse combing options."""

    parser = argparse.ArgumentParser(
        description=(
            "Compare Teresa Teng eBay completed/sold item URLs to Gripsweat "
            "and flag overlaps. Writes a gitignored report by default."
        )
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path(
            os.environ.get(
                "EBAY_STRUCTURED_ARTIFACT",
                str(DEFAULT_ARTIFACT),
            )
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown notes file. Default lives under gitignored reports/.",
    )
    return parser.parse_args()


def json_ready(value: object) -> object:
    """Convert dates and decimals for a sidecar JSON dump."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def render_report(
    *,
    artifact_path: Path,
    search_url: str,
    artifact_report: SoldOverlapReport,
    warehouse_report: SoldOverlapReport,
) -> str:
    """Render operator notes for a future commit without putting them in git."""

    def section(title: str, report: SoldOverlapReport) -> list[str]:
        lines = [
            f"## {title}",
            "",
            f"- Sold URLs combed: **{len(report.overlaps) + len(report.ebay_only)}**",
            f"- Gripsweat overlap flagged: **{len(report.overlaps)}**",
            f"- eBay-only (expected for many sold cards): **{len(report.ebay_only)}**",
            "",
        ]
        if report.overlaps:
            lines.extend(
                [
                    "| Listing | eBay sold URL | Gripsweat URL | eBay local | Official USD (Gripsweat) | Flags |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
            for overlap in report.overlaps:
                ebay_local = (
                    f"{overlap.ebay_currency or 'display'} "
                    f"{overlap.ebay_price or ''}"
                ).strip()
                official = (
                    f"{overlap.official_usd} on {overlap.official_usd_date}"
                    if overlap.official_usd is not None
                    else (
                        f"not USD ({overlap.gripsweat_currency} "
                        f"{overlap.gripsweat_price})"
                    )
                )
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            overlap.listing_id,
                            overlap.ebay_url,
                            overlap.gripsweat_url,
                            ebay_local,
                            official,
                            ", ".join(overlap.flags),
                        ]
                    )
                    + " |"
                )
            lines.append("")
        return lines

    lines = [
        "# eBay sold-item URLs vs Gripsweat overlap notes",
        "",
        "Gitignored operator notes. Do not add this file to a git commit.",
        "",
        f"- Headed completed/sold artifact: `{artifact_path}`",
        f"- Sold search: {search_url}",
        "- Identity: eBay `itm/{id}` equals Gripsweat `/item/{id}/` "
        "(or `original_listing_id` when present).",
        "- eBay sold cards are local display currency. Bare `$` is not official USD.",
        "- Duplicate rule: Gripsweat USD on sold_at is the official transaction-day USD.",
        "- Missing Gripsweat coverage is expected, not a warehouse miss.",
        "- Native eBay still wins in Collector Review; this file only flags the overlap.",
        "",
    ]
    lines.extend(
        section(
            "This Teresa Teng completed/sold capture",
            artifact_report,
        )
    )
    lines.extend(
        section(
            "All warehouse Teresa Teng eBay sold URLs",
            warehouse_report,
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    """Comb sold URLs, flag overlaps, write gitignored notes."""

    arguments = parse_args()
    artifact = json.loads(arguments.artifact.read_text(encoding="utf-8"))
    search_url = str(
        (artifact.get("page") or {}).get("final_url")
        or artifact.get("source_url")
        or ""
    )
    artifact_sold = sold_items_from_structured_artifact(artifact)

    database_url = configured_database_url(arguments.database_url)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        gripsweat_rows = list(
            connection.execute(
                """
                SELECT
                    original_listing_id,
                    gripsweat_url,
                    gripsweat_item_id,
                    gripsweat_item_key,
                    title,
                    sold_price,
                    sold_at,
                    sold_at_text
                FROM warehouse.gripsweat_sale
                """
            ).fetchall()
        )
        warehouse_rows = list(
            connection.execute(
                """
                SELECT
                    listing_id,
                    auction_url,
                    title,
                    final_price,
                    ended_at
                FROM warehouse.auction
                WHERE marketplace = 'ebay'
                  AND (
                    artist = 'Teresa Teng'
                    OR title ~* 'teresa[[:space:]]*teng'
                    OR title ILIKE '%teresateng%'
                    OR title LIKE '%鄧麗君%'
                    OR title LIKE '%邓丽君%'
                    OR title LIKE '%テレサ%'
                  )
                """
            ).fetchall()
        )

    artifact_report = flag_sold_item_overlaps(artifact_sold, gripsweat_rows)
    warehouse_sold = merge_sold_items(
        artifact_sold,
        [
            sold_item_from_warehouse_auction(row)
            for row in warehouse_rows
        ],
    )
    warehouse_report = flag_sold_item_overlaps(warehouse_sold, gripsweat_rows)

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        render_report(
            artifact_path=arguments.artifact,
            search_url=search_url,
            artifact_report=artifact_report,
            warehouse_report=warehouse_report,
        ),
        encoding="utf-8",
    )
    sidecar = arguments.output.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "artifact": str(arguments.artifact),
                "search_url": search_url,
                "artifact_sold_count": len(artifact_sold),
                "warehouse_sold_count": len(warehouse_sold),
                "artifact_overlap_ids": [
                    overlap.listing_id for overlap in artifact_report.overlaps
                ],
                "warehouse_overlap_ids": [
                    overlap.listing_id for overlap in warehouse_report.overlaps
                ],
                "artifact_overlaps": [
                    {
                        "listing_id": overlap.listing_id,
                        "ebay_url": overlap.ebay_url,
                        "gripsweat_url": overlap.gripsweat_url,
                        "ebay_title": overlap.ebay_title,
                        "gripsweat_title": overlap.gripsweat_title,
                        "ebay_price": json_ready(overlap.ebay_price),
                        "ebay_currency": overlap.ebay_currency,
                        "gripsweat_price": json_ready(overlap.gripsweat_price),
                        "gripsweat_currency": overlap.gripsweat_currency,
                        "official_usd": json_ready(overlap.official_usd),
                        "official_usd_date": json_ready(overlap.official_usd_date),
                        "ebay_sold_on": json_ready(overlap.ebay_sold_on),
                        "gripsweat_sold_on": json_ready(overlap.gripsweat_sold_on),
                        "flags": list(overlap.flags),
                    }
                    for overlap in artifact_report.overlaps
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"COMMIT_FILE={arguments.output}")
    print(f"SIDECAR={sidecar}")
    print(
        "ARTIFACT_SOLD="
        f"{len(artifact_sold)} OVERLAP={len(artifact_report.overlaps)} "
        f"EBAY_ONLY={len(artifact_report.ebay_only)}"
    )
    print(
        "WAREHOUSE_SOLD="
        f"{len(warehouse_sold)} OVERLAP={len(warehouse_report.overlaps)} "
        f"EBAY_ONLY={len(warehouse_report.ebay_only)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
