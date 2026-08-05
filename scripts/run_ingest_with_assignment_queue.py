#!/usr/bin/env python3
"""Run an existing ingest command and report assignment-queue changes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row


DEFAULT_COMMAND = (
    sys.executable,
    "scripts/sync_warehouse_incremental.py",
)


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse safe ingestion-wrapper arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run an existing auction ingest command, report new or "
            "updated auctions, and verify that ingestion did not create "
            "pressing assignments or completeness snapshots."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "PSQL_URL",
            "postgresql://auction:auction@127.0.0.1:5544/"
            "auction_warehouse",
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Execute the command. Without this flag, only the planned "
            "command and current queue state are reported."
        ),
    )

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help=(
            "Command following --. The tracked incremental warehouse "
            "sync is used when no command is supplied."
        ),
    )

    return parser.parse_args(
        argv
    )


def _command(
    values: Sequence[str],
) -> list[str]:
    """Return the command without argparse's optional separator."""
    command = list(
        values
    )

    if command and command[0] == "--":
        command = command[
            1:
        ]

    if not command:
        command = list(
            DEFAULT_COMMAND
        )

    return command


def _fingerprint(
    payload: Any,
) -> str:
    """Return a stable JSON fingerprint."""
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _state(
    connection: psycopg.Connection[Any],
) -> dict[str, Any]:
    """Return auction identities and protected workflow counts."""
    auction_rows = list(
        connection.execute(
            """
            SELECT
                marketplace,
                listing_id,
                to_jsonb(
                    auction_record
                ) AS auction_payload
            FROM warehouse.auction AS auction_record
            ORDER BY
                marketplace,
                listing_id
            """
        ).fetchall()
    )

    auctions = {
        (
            str(
                row[
                    "marketplace"
                ]
            ),
            str(
                row[
                    "listing_id"
                ]
            ),
        ):
            {
                "fingerprint":
                    _fingerprint(
                        row[
                            "auction_payload"
                        ]
                    ),
                "payload":
                    row[
                        "auction_payload"
                    ],
            }
        for row in auction_rows
    }

    protected = connection.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM warehouse.auction_pressing_assignment
            )::integer AS assignments,
            (
                SELECT COUNT(*)
                FROM system.listing_completeness_snapshot
            )::integer AS snapshots,
            (
                SELECT COUNT(*)
                FROM system.listing_completeness_timeline
            )::integer AS timeline,
            (
                SELECT COUNT(*)
                FROM system.new_auction_assignment_queue
            )::integer AS queue
        """
    ).fetchone()

    return {
        "auctions":
            auctions,
        "auction_count":
            len(
                auctions
            ),
        "assignments":
            int(
                protected[
                    "assignments"
                ]
            ),
        "snapshots":
            int(
                protected[
                    "snapshots"
                ]
            ),
        "timeline":
            int(
                protected[
                    "timeline"
                ]
            ),
        "queue":
            int(
                protected[
                    "queue"
                ]
            ),
    }


def _write_tsv(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write one report worksheet."""
    fieldnames = (
        [
            "marketplace",
            "listing_id",
            "before_fingerprint",
            "after_fingerprint",
        ]
        if rows
        else [
            "marketplace",
            "listing_id",
            "before_fingerprint",
            "after_fingerprint",
        ]
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(
            rows
        )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run or preview one safe ingestion command."""
    args = parse_args(
        argv
    )

    command = _command(
        args.command
    )

    output_dir = (
        args.output_dir
        or Path(
            "logs"
        )
        / (
            "ingest-assignment-queue-"
            + datetime.now(
                timezone.utc
            ).strftime(
                "%Y%m%d-%H%M%S"
            )
        )
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    with psycopg.connect(
        args.database_url,
        row_factory=dict_row,
    ) as connection:
        before = _state(
            connection
        )

    report: dict[str, Any] = {
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "command":
            command,
        "executed":
            False,
        "return_code":
            None,
        "before": {
            key:
                value
            for key, value in before.items()
            if key != "auctions"
        },
        "new_auctions":
            0,
        "updated_auctions":
            0,
        "database_writes_by_wrapper":
            0,
    }

    if not args.execute:
        report[
            "status"
        ] = "DRY_RUN"

        (
            output_dir
            / "report.json"
        ).write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    completed = subprocess.run(
        command,
        cwd=Path.cwd(),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )

    (
        output_dir
        / "command.stdout.txt"
    ).write_text(
        completed.stdout,
        encoding="utf-8",
    )

    (
        output_dir
        / "command.stderr.txt"
    ).write_text(
        completed.stderr,
        encoding="utf-8",
    )

    report[
        "executed"
    ] = True

    report[
        "return_code"
    ] = completed.returncode

    with psycopg.connect(
        args.database_url,
        row_factory=dict_row,
    ) as connection:
        after = _state(
            connection
        )

    before_auctions = before[
        "auctions"
    ]

    after_auctions = after[
        "auctions"
    ]

    new_keys = sorted(
        set(
            after_auctions
        )
        - set(
            before_auctions
        )
    )

    updated_keys = sorted(
        key
        for key in (
            set(
                after_auctions
            )
            & set(
                before_auctions
            )
        )
        if (
            after_auctions[
                key
            ][
                "fingerprint"
            ]
            != before_auctions[
                key
            ][
                "fingerprint"
            ]
        )
    )

    new_rows = [
        {
            "marketplace":
                marketplace,
            "listing_id":
                listing_id,
            "before_fingerprint":
                "",
            "after_fingerprint":
                after_auctions[
                    (
                        marketplace,
                        listing_id,
                    )
                ][
                    "fingerprint"
                ],
        }
        for marketplace, listing_id in new_keys
    ]

    updated_rows = [
        {
            "marketplace":
                marketplace,
            "listing_id":
                listing_id,
            "before_fingerprint":
                before_auctions[
                    (
                        marketplace,
                        listing_id,
                    )
                ][
                    "fingerprint"
                ],
            "after_fingerprint":
                after_auctions[
                    (
                        marketplace,
                        listing_id,
                    )
                ][
                    "fingerprint"
                ],
        }
        for marketplace, listing_id in updated_keys
    ]

    _write_tsv(
        output_dir
        / "new-auctions.tsv",
        new_rows,
    )

    _write_tsv(
        output_dir
        / "updated-auctions.tsv",
        updated_rows,
    )

    report[
        "after"
    ] = {
        key:
            value
        for key, value in after.items()
        if key != "auctions"
    }

    report[
        "new_auctions"
    ] = len(
        new_rows
    )

    report[
        "updated_auctions"
    ] = len(
        updated_rows
    )

    protected_changes = {
        name: {
            "before":
                before[
                    name
                ],
            "after":
                after[
                    name
                ],
        }
        for name in (
            "assignments",
            "snapshots",
            "timeline",
        )
        if before[
            name
        ] != after[
            name
        ]
    }

    report[
        "protected_changes"
    ] = protected_changes

    if completed.returncode != 0:
        report[
            "status"
        ] = "COMMAND_FAILED"
    elif protected_changes:
        report[
            "status"
        ] = "BLOCKED_PROTECTED_WORKFLOW_CHANGE"
    else:
        report[
            "status"
        ] = "COMPLETED"

    (
        output_dir
        / "report.json"
    ).write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    if completed.returncode != 0:
        return completed.returncode

    if protected_changes:
        raise RuntimeError(
            "The ingest command changed reviewed assignments or "
            "completeness history. Automatic assignment during ingestion "
            "is forbidden."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
