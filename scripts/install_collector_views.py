#!/usr/bin/env python3
"""Install or verify the managed Collector Review views."""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine

from auction_etl.database.collector_views import (
    COLLECTOR_VIEW_DDL,
    install_collector_views,
    verify_collector_views,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically install and verify both managed "
            "Collector Review views."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="SQLAlchemy PostgreSQL URL.",
    )
    parser.add_argument(
        "--expected-database",
        default="auction_warehouse",
        help="Required database name. Use an empty value to skip.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print managed DDL without connecting.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the existing views without replacing them.",
    )
    parser.add_argument(
        "--require-collector-parity",
        action="store_true",
        help=(
            "Require one collector row for every warehouse row."
        ),
    )
    return parser.parse_args()


def database_name(database_url: str) -> str:
    return urlsplit(database_url).path.lstrip("/")


def main() -> int:
    args = parse_args()

    if args.dry_run:
        for index, statement in enumerate(
            COLLECTOR_VIEW_DDL,
            start=1,
        ):
            print(f"-- statement {index}")
            print(statement.rstrip())
            print()

        return 0

    if not args.database_url:
        raise RuntimeError(
            "DATABASE_URL or --database-url is required."
        )

    actual_database = database_name(args.database_url)

    if (
        args.expected_database
        and actual_database != args.expected_database
    ):
        raise RuntimeError(
            f"Refusing database {actual_database!r}; expected "
            f"{args.expected_database!r}."
        )

    engine = create_engine(args.database_url)

    with engine.begin() as connection:
        if args.verify_only:
            state = verify_collector_views(
                connection,
                require_collector_parity=(
                    args.require_collector_parity
                ),
            )
        else:
            state = install_collector_views(
                connection,
                require_collector_parity=(
                    args.require_collector_parity
                ),
            )

    print(f"Database rows : {state.warehouse_rows}")
    print(f"Collector rows: {state.collector_rows}")
    print(f"Effective rows: {state.effective_rows}")
    print(f"Review rows   : {state.review_rows}")
    print(
        "Effective columns: "
        f"{len(state.effective_columns)}"
    )
    print(
        "Review columns   : "
        f"{len(state.review_columns)}"
    )
    print()
    print("✓ Collector views are managed and verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

