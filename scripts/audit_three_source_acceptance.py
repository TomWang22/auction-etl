"""Read-only acceptance audit for one completed three-source refresh."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


MARKETPLACES = (
    "buyee",
    "ebay",
    "gripsweat",
)

SOURCE_STATE_PATTERN = re.compile(
    r"^AUCTION_SOURCE_STATE\s+"
    r"source=(?P<source>\S+)\s+"
    r"state=(?P<state>\S+)\s*$"
)


def normalize_source(
    value: str,
) -> str | None:
    """Normalize one canonical marketplace name."""

    normalized = value.strip().casefold()

    if normalized in MARKETPLACES:
        return normalized

    return None


def parse_latest_source_states(
    log_text: str,
) -> dict[str, str]:
    """Return each marketplace's final explicit runner state."""

    states: dict[
        str,
        str,
    ] = {}

    for raw_line in log_text.splitlines():
        match = SOURCE_STATE_PATTERN.match(
            raw_line.strip()
        )

        if match is None:
            continue

        source = normalize_source(
            match.group(
                "source"
            )
        )

        if source is None:
            continue

        states[
            source
        ] = (
            match.group(
                "state"
            )
            .strip()
            .casefold()
        )

    return states


def resolve_database_url() -> str:
    """Return the configured production PostgreSQL URL."""

    for name in (
        "DATABASE_URL",
        "DATABASE_PUBLIC_URL",
        "POSTGRES_URL",
    ):
        value = os.environ.get(
            name,
            "",
        ).strip()

        if value:
            return value

    raise RuntimeError(
        "No PostgreSQL URL is configured."
    )


def database_snapshot(
    database_url: str,
) -> dict[str, Any]:
    """Read population and stable-identity invariants."""

    counts = {
        "buyee":
            0,
        "ebay":
            0,
        "gripsweat":
            0,
    }

    duplicate_groups = {
        "auction":
            0,
        "gripsweat":
            0,
    }

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        connection.execute(
            "SET TRANSACTION READ ONLY"
        )

        auction_rows = connection.execute(
            """
            SELECT
                marketplace,
                COUNT(*) AS row_count
            FROM warehouse.auction
            WHERE marketplace IN (
                'buyee',
                'ebay'
            )
            GROUP BY marketplace
            """
        ).fetchall()

        for row in auction_rows:
            marketplace = str(
                row[
                    "marketplace"
                ]
            ).casefold()

            if marketplace in counts:
                counts[
                    marketplace
                ] = int(
                    row[
                        "row_count"
                    ]
                )

        gripsweat_row = connection.execute(
            """
            SELECT COUNT(*) AS row_count
            FROM warehouse.gripsweat_sale
            """
        ).fetchone()

        if gripsweat_row is not None:
            counts[
                "gripsweat"
            ] = int(
                gripsweat_row[
                    "row_count"
                ]
            )

        auction_duplicate_row = connection.execute(
            """
            SELECT COUNT(*) AS duplicate_groups
            FROM (
                SELECT
                    marketplace,
                    listing_id
                FROM warehouse.auction
                WHERE marketplace IN (
                    'buyee',
                    'ebay'
                )
                  AND listing_id IS NOT NULL
                GROUP BY
                    marketplace,
                    listing_id
                HAVING COUNT(*) > 1
            ) duplicated
            """
        ).fetchone()

        if auction_duplicate_row is not None:
            duplicate_groups[
                "auction"
            ] = int(
                auction_duplicate_row[
                    "duplicate_groups"
                ]
            )

        gripsweat_duplicate_row = connection.execute(
            """
            SELECT COUNT(*) AS duplicate_groups
            FROM (
                SELECT
                    source_name,
                    gripsweat_item_key
                FROM warehouse.gripsweat_sale
                WHERE gripsweat_item_key IS NOT NULL
                GROUP BY
                    source_name,
                    gripsweat_item_key
                HAVING COUNT(*) > 1
            ) duplicated
            """
        ).fetchone()

        if gripsweat_duplicate_row is not None:
            duplicate_groups[
                "gripsweat"
            ] = int(
                gripsweat_duplicate_row[
                    "duplicate_groups"
                ]
            )

        connection.rollback()

    return {
        "counts":
            counts,
        "duplicate_groups":
            duplicate_groups,
    }


def acceptance_passes(
    states: dict[str, str],
    counts: dict[str, int],
    duplicate_groups: dict[str, int],
) -> bool:
    """Accept successful zero-new incremental runs without hiding failures."""

    all_sources_done = all(
        states.get(
            marketplace
        )
        == "done"
        for marketplace
        in MARKETPLACES
    )

    all_sources_populated = all(
        int(
            counts.get(
                marketplace,
                0,
            )
        )
        > 0
        for marketplace
        in MARKETPLACES
    )

    duplicates_clear = all(
        int(
            value
        )
        == 0
        for value
        in duplicate_groups.values()
    )

    return bool(
        all_sources_done
        and all_sources_populated
        and duplicates_clear
    )


def parse_arguments() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--log",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    """Run the read-only production acceptance audit."""

    arguments = parse_arguments()

    log_text = arguments.log.read_text(
        encoding="utf-8",
        errors="replace",
    )

    states = parse_latest_source_states(
        log_text
    )

    snapshot = database_snapshot(
        resolve_database_url()
    )

    counts = snapshot[
        "counts"
    ]

    duplicate_groups = snapshot[
        "duplicate_groups"
    ]

    complete = acceptance_passes(
        states,
        counts,
        duplicate_groups,
    )

    payload = {
        "source_states":
            states,
        "warehouse_counts":
            counts,
        "duplicate_groups":
            duplicate_groups,
        "zero_new_rows_allowed":
            True,
        "three_source_e2e_pass":
            complete,
    }

    arguments.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    arguments.output.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "SOURCE_STATES="
        + json.dumps(
            states,
            sort_keys=True,
        )
    )

    print(
        "WAREHOUSE_COUNTS="
        + json.dumps(
            counts,
            sort_keys=True,
        )
    )

    print(
        "DUPLICATE_GROUPS="
        + json.dumps(
            duplicate_groups,
            sort_keys=True,
        )
    )

    print(
        "ZERO_NEW_ROWS_ALLOWED=true"
    )

    print(
        "THREE_SOURCE_E2E="
        + (
            "PASS"
            if complete
            else "NEEDS_REVIEW"
        )
    )

    return (
        0
        if complete
        else 3
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
