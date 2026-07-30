"""Create and update durable auction first-seen metadata."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from auction_etl.reporting.recent_ingestion import (
    backfill_ingestion_audit,
    connect,
    ensure_ingestion_audit_schema,
    seed_audit_from_export_directory,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Maintain first-seen and last-seen metadata "
            "for auction identities."
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
        "--seed-new-only",
        type=Path,
    )
    parser.add_argument(
        "--run-id",
    )

    return parser.parse_args()


def main() -> int:
    """Install, backfill, and optionally seed the audit."""
    args = parse_args()

    with connect(args.database_url) as connection:
        ensure_ingestion_audit_schema(
            connection
        )

        backfilled = backfill_ingestion_audit(
            connection
        )

        seeded = {
            "newly_ingested": 0,
            "refreshed_existing": 0,
        }

        if args.seed_new_only is not None:
            if not args.seed_new_only.is_dir():
                raise SystemExit(
                    "Seed export directory does not exist: "
                    f"{args.seed_new_only}"
                )

            seeded = seed_audit_from_export_directory(
                connection,
                args.seed_new_only,
                run_id=args.run_id,
            )

        connection.commit()

        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS identities,
                COUNT(*) FILTER (
                    WHERE first_seen_source =
                          'new-only-export'
                ) AS explicit_new,
                COUNT(*) FILTER (
                    WHERE last_seen_source =
                          'refreshed-export'
                ) AS explicitly_refreshed
            FROM system.auction_ingestion_identity
            """
        ).fetchone()

    print()
    print("Auction ingestion audit")
    print("=======================")
    print(f"Backfilled           : {backfilled}")
    print(
        "Seeded new           : "
        f"{seeded['newly_ingested']}"
    )
    print(
        "Seeded refreshed     : "
        f"{seeded['refreshed_existing']}"
    )
    print(
        "Tracked identities   : "
        f"{counts['identities']}"
    )
    print(
        "Explicit recent adds : "
        f"{counts['explicit_new']}"
    )
    print(
        "Explicit refreshes   : "
        f"{counts['explicitly_refreshed']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
