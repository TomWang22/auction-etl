#!/usr/bin/env python3
"""Run one fresh FaceRecords eBay ingestion round behind invariants."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATABASE_URL = (
    "postgresql://auction:auction@"
    "127.0.0.1:5544/auction_warehouse"
)

DEFAULT_SOURCE = "facerecords"
DEFAULT_CONFIG = Path("config/ebay_sources.json")

CRAWLER = ROOT / "scripts/crawl_ebay_sources.py"
INGEST_WRAPPER = (
    ROOT / "scripts/run_ingest_with_assignment_queue.py"
)

LOCK_PATH = (
    ROOT
    / "logs"
    / "ingestion-round"
    / "ingestion-round.lock"
)

PIPELINE_PATTERN = (
    "crawl_ebay_sources.py|"
    "run_latest_auction_refresh.py|"
    "run_ingest_with_assignment_queue.py|"
    "sync_warehouse_incremental.py|"
    "auction_etl.cli.main.*parse|"
    "auction_etl.cli.main.*normalize|"
    "auction_etl.cli.main.*sync"
)


class IngestionRoundError(RuntimeError):
    """Raised when a guarded ingestion-round contract fails."""


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse ingestion-round arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Crawl one fresh eBay source, parse and normalize it, "
            "then guarded-ingest only when new identities exist."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        ),
    )
    parser.add_argument(
        "--source",
        default=os.environ.get(
            "AUCTION_EBAY_SOURCE",
            DEFAULT_SOURCE,
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the crawl and guarded ingestion.",
    )

    return parser.parse_args(argv)


def psql_url(database_url: str) -> str:
    """Normalize a SQLAlchemy PostgreSQL URL for psycopg."""
    return database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )


def atomic_write_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    """Atomically write one JSON object."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def git_tracked_hash() -> str:
    """Return the SHA-256 of the current tracked diff."""
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return hashlib.sha256(
        completed.stdout
    ).hexdigest()


def query_one(
    database_url: str,
    statement: str,
    parameters: Sequence[Any] = (),
) -> Mapping[str, Any]:
    """Run one read-only query and return its first row."""
    with psycopg.connect(
        database_url,
        autocommit=True,
        row_factory=dict_row,
    ) as connection:
        connection.execute(
            "SET default_transaction_read_only = on"
        )
        connection.execute(
            "SET statement_timeout = '15s'"
        )

        row = connection.execute(
            statement,
            parameters,
        ).fetchone()

    if row is None:
        raise IngestionRoundError(
            "Read-only query returned no row."
        )

    return row


def query_all(
    database_url: str,
    statement: str,
    parameters: Sequence[Any] = (),
) -> list[Mapping[str, Any]]:
    """Run one read-only query and return every row."""
    with psycopg.connect(
        database_url,
        autocommit=True,
        row_factory=dict_row,
    ) as connection:
        connection.execute(
            "SET default_transaction_read_only = on"
        )
        connection.execute(
            "SET statement_timeout = '15s'"
        )

        rows = connection.execute(
            statement,
            parameters,
        ).fetchall()

    return list(rows)


def protected_state(
    database_url: str,
) -> dict[str, int]:
    """Read warehouse and protected workflow counts."""
    row = query_one(
        database_url,
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM warehouse.auction
            ) AS auction_count,
            (
                SELECT COUNT(*)
                FROM warehouse.auction_pressing_assignment
            ) AS assignments,
            (
                SELECT COUNT(*)
                FROM system.listing_completeness_snapshot
            ) AS snapshots,
            (
                SELECT COUNT(*)
                FROM system.listing_completeness_timeline
            ) AS timeline,
            (
                SELECT COUNT(*)
                FROM system.new_auction_assignment_queue
            ) AS queue
        """,
    )

    return {
        key: int(value)
        for key, value in row.items()
    }


def global_pending_ebay(
    database_url: str,
) -> int:
    """Count staged eBay identities absent from the warehouse."""
    row = query_one(
        database_url,
        """
        WITH identities AS (
            SELECT DISTINCT
                lower(
                    btrim(listing.marketplace)
                ) AS marketplace,
                listing.listing_id
            FROM staging.listing AS listing
            WHERE lower(
                btrim(listing.marketplace)
            ) = 'ebay'
        )
        SELECT COUNT(*) AS pending
        FROM identities AS identity
        WHERE NOT EXISTS (
            SELECT 1
            FROM warehouse.auction AS auction
            WHERE lower(
                btrim(auction.marketplace)
            ) = identity.marketplace
              AND auction.listing_id =
                  identity.listing_id
        )
        """,
    )

    return int(row["pending"])


def max_crawl_job_id(
    database_url: str,
) -> int:
    """Return the maximum crawl-job identifier."""
    row = query_one(
        database_url,
        """
        SELECT COALESCE(MAX(id), 0) AS maximum_id
        FROM system.crawl_job
        """,
    )

    return int(row["maximum_id"])


def new_source_jobs(
    database_url: str,
    *,
    source: str,
    after_id: int,
) -> list[Mapping[str, Any]]:
    """Return jobs created for this source after the boundary."""
    return query_all(
        database_url,
        """
        SELECT
            id,
            source,
            status
        FROM system.crawl_job
        WHERE id > %s
          AND source = %s
        ORDER BY id
        """,
        (
            after_id,
            f"ebay:{source}",
        ),
    )


def raw_page_count(
    database_url: str,
    job_id: int,
) -> int:
    """Count raw pages for one crawl job."""
    row = query_one(
        database_url,
        """
        SELECT COUNT(*) AS row_count
        FROM raw.page
        WHERE crawl_job_id = %s
        """,
        (job_id,),
    )

    return int(row["row_count"])


def cohort_contract(
    database_url: str,
    job_id: int,
) -> dict[str, int]:
    """Classify one crawl-job staging cohort."""
    row = query_one(
        database_url,
        """
        WITH cohort_rows AS (
            SELECT
                lower(
                    btrim(listing.marketplace)
                ) AS marketplace,
                listing.listing_id
            FROM staging.listing AS listing
            JOIN raw.page AS page
              ON page.id = listing.raw_page_id
            WHERE page.crawl_job_id = %s
        ),
        identities AS (
            SELECT DISTINCT
                marketplace,
                listing_id
            FROM cohort_rows
        )
        SELECT
            (
                SELECT COUNT(*)
                FROM cohort_rows
            ) AS staging_rows,
            (
                SELECT COUNT(*)
                FROM identities
            ) AS unique_rows,
            (
                (
                    SELECT COUNT(*)
                    FROM cohort_rows
                )
                -
                (
                    SELECT COUNT(*)
                    FROM identities
                )
            ) AS duplicate_rows,
            (
                SELECT COUNT(*)
                FROM identities AS identity
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM warehouse.auction AS auction
                    WHERE lower(
                        btrim(auction.marketplace)
                    ) = identity.marketplace
                      AND auction.listing_id =
                          identity.listing_id
                )
            ) AS new_rows,
            (
                SELECT COUNT(*)
                FROM identities AS identity
                WHERE EXISTS (
                    SELECT 1
                    FROM warehouse.auction AS auction
                    WHERE lower(
                        btrim(auction.marketplace)
                    ) = identity.marketplace
                      AND auction.listing_id =
                          identity.listing_id
                )
            ) AS existing_rows
        """,
        (job_id,),
    )

    return {
        key: int(value)
        for key, value in row.items()
    }


def new_identities(
    database_url: str,
    job_id: int,
) -> list[Mapping[str, Any]]:
    """Return identities in a fresh job absent from warehouse."""
    return query_all(
        database_url,
        """
        WITH identities AS (
            SELECT DISTINCT
                lower(
                    btrim(listing.marketplace)
                ) AS marketplace,
                listing.listing_id
            FROM staging.listing AS listing
            JOIN raw.page AS page
              ON page.id = listing.raw_page_id
            WHERE page.crawl_job_id = %s
        )
        SELECT
            identity.marketplace,
            identity.listing_id
        FROM identities AS identity
        WHERE NOT EXISTS (
            SELECT 1
            FROM warehouse.auction AS auction
            WHERE lower(
                btrim(auction.marketplace)
            ) = identity.marketplace
              AND auction.listing_id =
                  identity.listing_id
        )
        ORDER BY
            identity.marketplace,
            identity.listing_id
        """,
        (job_id,),
    )


def remaining_fresh(
    database_url: str,
    job_id: int,
) -> int:
    """Count fresh-cohort identities still absent from warehouse."""
    row = query_one(
        database_url,
        """
        WITH identities AS (
            SELECT DISTINCT
                lower(
                    btrim(listing.marketplace)
                ) AS marketplace,
                listing.listing_id
            FROM staging.listing AS listing
            JOIN raw.page AS page
              ON page.id = listing.raw_page_id
            WHERE page.crawl_job_id = %s
        )
        SELECT COUNT(*) AS remaining
        FROM identities AS identity
        WHERE NOT EXISTS (
            SELECT 1
            FROM warehouse.auction AS auction
            WHERE lower(
                btrim(auction.marketplace)
            ) = identity.marketplace
              AND auction.listing_id =
                  identity.listing_id
        )
        """,
        (job_id,),
    )

    return int(row["remaining"])


def ensure_no_pipeline_process() -> None:
    """Refuse to overlap an independently started ETL process."""
    if not shutil_which("pgrep"):
        return

    completed = subprocess.run(
        [
            "pgrep",
            "-f",
            PIPELINE_PATTERN,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if completed.returncode == 0:
        raise IngestionRoundError(
            "Another crawl/parse/normalize/sync process is already running: "
            + completed.stdout.strip()
        )


def shutil_which(command: str) -> str | None:
    """Return an executable path without importing shell helpers."""
    for directory in os.environ.get(
        "PATH",
        "",
    ).split(os.pathsep):
        candidate = Path(directory) / command

        if candidate.is_file() and os.access(
            candidate,
            os.X_OK,
        ):
            return str(candidate)

    return None


def run_logged(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    log_path: Path,
) -> tuple[int, str]:
    """Run one command while teeing output to a log."""
    log_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_lines: list[str] = []

    with log_path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        process = subprocess.Popen(
            list(command),
            cwd=ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert process.stdout is not None

        for line in process.stdout:
            output_lines.append(line)
            handle.write(line)
            handle.flush()
            print(
                line,
                end="",
                flush=True,
            )

        status = process.wait()

    return status, "".join(output_lines)


def parse_json_output(text: str) -> dict[str, Any]:
    """Parse the wrapper's final JSON report."""
    stripped = text.strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")

        if start < 0 or end < start:
            raise IngestionRoundError(
                "Guarded wrapper did not emit a JSON report."
            ) from None

        try:
            payload = json.loads(
                stripped[start : end + 1]
            )
        except json.JSONDecodeError as error:
            raise IngestionRoundError(
                "Guarded wrapper JSON could not be parsed."
            ) from error

    if not isinstance(payload, dict):
        raise IngestionRoundError(
            "Guarded wrapper report is not an object."
        )

    return payload


def validate_initial_state(
    state: Mapping[str, int],
) -> None:
    """Validate the assignment-queue relationship."""
    expected_queue = (
        int(state["auction_count"])
        - int(state["assignments"])
    )

    if int(state["queue"]) != expected_queue:
        raise IngestionRoundError(
            "Queue invariant failed before ingestion: "
            f"{state['queue']} != "
            f"{state['auction_count']} - "
            f"{state['assignments']}"
        )


def validate_final_state(
    *,
    before: Mapping[str, int],
    after: Mapping[str, int],
    expected_new: int,
) -> None:
    """Validate protected workflow and queue invariants."""
    auction_delta = (
        int(after["auction_count"])
        - int(before["auction_count"])
    )
    queue_delta = (
        int(after["queue"])
        - int(before["queue"])
    )

    if auction_delta != expected_new:
        raise IngestionRoundError(
            "Warehouse delta does not match new identities: "
            f"{auction_delta} != {expected_new}"
        )

    for key in (
        "assignments",
        "snapshots",
        "timeline",
    ):
        if int(after[key]) != int(before[key]):
            raise IngestionRoundError(
                f"Protected count changed: {key}: "
                f"{before[key]} -> {after[key]}"
            )

    if int(after["queue"]) != (
        int(after["auction_count"])
        - int(after["assignments"])
    ):
        raise IngestionRoundError(
            "Queue invariant failed after ingestion."
        )

    if queue_delta != expected_new:
        raise IngestionRoundError(
            "Queue delta does not match new identities: "
            f"{queue_delta} != {expected_new}"
        )


def main() -> int:
    """Execute one fresh guarded eBay ingestion round."""
    args = parse_args()

    database_url = psql_url(
        args.database_url
    )

    config_path = (
        args.config
        if args.config.is_absolute()
        else ROOT / args.config
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d-%H%M%S")

    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else (
            ROOT
            / "logs"
            / "ingestion-round"
            / timestamp
        )
    )

    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path = output_dir / "result.json"

    for path in (
        CRAWLER,
        INGEST_WRAPPER,
        config_path,
    ):
        if not path.is_file():
            raise IngestionRoundError(
                f"Missing required file: {path}"
            )

    LOCK_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK_PATH.open(
        "w",
        encoding="utf-8",
    ) as lock_handle:
        try:
            fcntl.flock(
                lock_handle,
                fcntl.LOCK_EX
                | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            print(
                "Another ingestion round is already running.",
                file=sys.stderr,
            )
            return 2

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url
        environment.setdefault(
            "PGPASSWORD",
            os.environ.get(
                "AUCTION_DB_PASSWORD",
                "auction",
            ),
        )
        environment.setdefault(
            "PGCONNECT_TIMEOUT",
            "10",
        )
        environment.pop(
            "DOCKER_HOST",
            None,
        )
        environment.pop(
            "PGOPTIONS",
            None,
        )

        before = protected_state(
            database_url
        )
        pending_before = global_pending_ebay(
            database_url
        )
        tracked_before = git_tracked_hash()

        validate_initial_state(
            before
        )

        if pending_before != 0:
            raise IngestionRoundError(
                "Existing eBay staging contains "
                f"{pending_before} pending identities. "
                "Resolve them before crawling again."
            )

        max_job_before = max_crawl_job_id(
            database_url
        )

        dry_run_payload = {
            "status": "DRY_RUN",
            "executed": False,
            "source": args.source,
            "database_url": database_url,
            "warehouse_before":
                before["auction_count"],
            "queue_before": before["queue"],
            "pending_before": pending_before,
            "maximum_crawl_job_before":
                max_job_before,
            "output_dir": str(output_dir),
        }

        if not args.execute:
            atomic_write_json(
                result_path,
                dry_run_payload,
            )
            print(
                json.dumps(
                    dry_run_payload,
                    indent=2,
                )
            )
            return 0

        ensure_no_pipeline_process()

        print(
            "================ FRESH EBAY INGESTION ROUND ================"
        )
        print(
            f"Source:           {args.source}"
        )
        print(
            f"Warehouse before: {before['auction_count']}"
        )
        print(
            f"Assignments:      {before['assignments']}"
        )
        print(
            f"Queue:            {before['queue']}"
        )
        print(
            f"Pending eBay:     {pending_before}"
        )

        crawl_status, _ = run_logged(
            [
                sys.executable,
                str(CRAWLER),
                "--config",
                str(
                    config_path.relative_to(ROOT)
                ),
                "--source",
                args.source,
            ],
            environment=environment,
            log_path=output_dir / "crawl.log",
        )

        if crawl_status != 0:
            raise IngestionRoundError(
                "Fresh crawl failed. Do not retry automatically."
            )

        jobs = new_source_jobs(
            database_url,
            source=args.source,
            after_id=max_job_before,
        )

        if len(jobs) != 1:
            raise IngestionRoundError(
                "Expected exactly one new crawl job; "
                f"found {len(jobs)}."
            )

        job = jobs[0]
        job_id = int(job["id"])

        if str(job["status"]) != "finished":
            raise IngestionRoundError(
                f"Fresh crawl job {job_id} is "
                f"{job['status']!r}, not 'finished'."
            )

        pages = raw_page_count(
            database_url,
            job_id,
        )

        if pages < 1:
            raise IngestionRoundError(
                f"Fresh crawl job {job_id} produced no raw pages."
            )

        parse_status, _ = run_logged(
            [
                sys.executable,
                "-m",
                "auction_etl.cli.main",
                "parse",
                "latest",
            ],
            environment=environment,
            log_path=output_dir / "parse.log",
        )

        if parse_status != 0:
            raise IngestionRoundError(
                "Parser failed. Do not run another crawl."
            )

        normalize_status, _ = run_logged(
            [
                sys.executable,
                "-m",
                "auction_etl.cli.main",
                "normalize",
                "staging",
            ],
            environment=environment,
            log_path=output_dir / "normalize.log",
        )

        if normalize_status != 0:
            raise IngestionRoundError(
                "Normalization failed. Do not run another crawl."
            )

        cohort = cohort_contract(
            database_url,
            job_id,
        )

        if cohort["staging_rows"] < 1:
            raise IngestionRoundError(
                "Fresh job has zero staging rows."
            )

        if cohort["unique_rows"] < 1:
            raise IngestionRoundError(
                "Fresh job has zero unique identities."
            )

        if cohort["duplicate_rows"] != 0:
            raise IngestionRoundError(
                "Fresh job contains duplicate identities."
            )

        if (
            cohort["new_rows"]
            + cohort["existing_rows"]
            != cohort["unique_rows"]
        ):
            raise IngestionRoundError(
                "Fresh cohort partition is inconsistent."
            )

        pending_after_parse = (
            global_pending_ebay(
                database_url
            )
        )

        if (
            pending_after_parse
            != cohort["new_rows"]
        ):
            raise IngestionRoundError(
                "Pending eBay identities exist outside "
                "the fresh cohort: "
                f"{pending_after_parse} != "
                f"{cohort['new_rows']}"
            )

        identities = new_identities(
            database_url,
            job_id,
        )

        identities_path = (
            output_dir
            / "new-identities.tsv"
        )

        with identities_path.open(
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "marketplace\tlisting_id\n"
            )

            for identity in identities:
                handle.write(
                    f"{identity['marketplace']}\t"
                    f"{identity['listing_id']}\n"
                )

        print()
        print(
            "================ COHORT ================"
        )
        print(
            f"Job:               {job_id}"
        )
        print(
            f"Raw pages:         {pages}"
        )
        print(
            f"Staging rows:      {cohort['staging_rows']}"
        )
        print(
            f"Unique identities: {cohort['unique_rows']}"
        )
        print(
            f"New identities:    {cohort['new_rows']}"
        )
        print(
            f"Existing:          {cohort['existing_rows']}"
        )

        wrapper_report: dict[str, Any] | None = None

        if cohort["new_rows"] > 0:
            ingest_dir = (
                output_dir
                / "guarded-ingest"
            )

            ingest_status, ingest_output = (
                run_logged(
                    [
                        sys.executable,
                        str(INGEST_WRAPPER),
                        "--database-url",
                        database_url,
                        "--output-dir",
                        str(ingest_dir),
                        "--execute",
                        "--",
                        sys.executable,
                        "-m",
                        "auction_etl.cli.main",
                        "sync",
                        "warehouse",
                        "--marketplace",
                        "ebay",
                        "--no-prune",
                    ],
                    environment=environment,
                    log_path=(
                        output_dir
                        / "ingest.log"
                    ),
                )
            )

            if ingest_status != 0:
                raise IngestionRoundError(
                    "Guarded warehouse ingestion failed."
                )

            wrapper_report = parse_json_output(
                ingest_output
            )

            if (
                wrapper_report.get("status")
                != "COMPLETED"
            ):
                raise IngestionRoundError(
                    "Guarded wrapper did not report COMPLETED."
                )

            if (
                wrapper_report.get("executed")
                is not True
            ):
                raise IngestionRoundError(
                    "Guarded wrapper did not execute."
                )

            if wrapper_report.get(
                "protected_changes"
            ):
                raise IngestionRoundError(
                    "Guarded wrapper reported protected changes."
                )

            reported_new = int(
                wrapper_report.get(
                    "new_auctions",
                    -1,
                )
            )

            if reported_new != cohort["new_rows"]:
                raise IngestionRoundError(
                    "Wrapper new-auction count does not "
                    "match fresh cohort: "
                    f"{reported_new} != "
                    f"{cohort['new_rows']}"
                )

        after = protected_state(
            database_url
        )

        validate_final_state(
            before=before,
            after=after,
            expected_new=cohort["new_rows"],
        )

        pending_after = global_pending_ebay(
            database_url
        )

        if pending_after != 0:
            raise IngestionRoundError(
                f"{pending_after} eBay identities remain pending."
            )

        remaining = remaining_fresh(
            database_url,
            job_id,
        )

        if remaining != 0:
            raise IngestionRoundError(
                f"{remaining} fresh identities remain absent "
                "from warehouse."
            )

        tracked_after = git_tracked_hash()

        if tracked_after != tracked_before:
            raise IngestionRoundError(
                "Tracked repository content changed."
            )

        result = {
            "status": "COMPLETED",
            "executed": True,
            "source": args.source,
            "crawl_job_id": job_id,
            "raw_pages": pages,
            "staging_rows":
                cohort["staging_rows"],
            "unique_identities":
                cohort["unique_rows"],
            "new_auctions":
                cohort["new_rows"],
            "existing_identities":
                cohort["existing_rows"],
            "warehouse_before":
                before["auction_count"],
            "warehouse_after":
                after["auction_count"],
            "warehouse_delta":
                (
                    after["auction_count"]
                    - before["auction_count"]
                ),
            "assignments_before":
                before["assignments"],
            "assignments_after":
                after["assignments"],
            "queue_before":
                before["queue"],
            "queue_after":
                after["queue"],
            "queue_delta":
                (
                    after["queue"]
                    - before["queue"]
                ),
            "snapshots_before":
                before["snapshots"],
            "snapshots_after":
                after["snapshots"],
            "timeline_before":
                before["timeline"],
            "timeline_after":
                after["timeline"],
            "pending_ebay_after":
                pending_after,
            "remaining_fresh":
                remaining,
            "tracked_hash_before":
                tracked_before,
            "tracked_hash_after":
                tracked_after,
            "new_identities": [
                {
                    "marketplace":
                        str(
                            identity[
                                "marketplace"
                            ]
                        ),
                    "listing_id":
                        str(
                            identity[
                                "listing_id"
                            ]
                        ),
                }
                for identity in identities
            ],
            "wrapper_report":
                wrapper_report,
            "evidence_dir":
                str(output_dir),
            "finished_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        }

        atomic_write_json(
            result_path,
            result,
        )

        print()
        print(
            "================ RESULT ================"
        )
        print(
            json.dumps(
                result,
                indent=2,
                default=str,
            )
        )

        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IngestionRoundError as error:
        print(
            f"\nERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
