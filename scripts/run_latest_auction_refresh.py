"""Retrieve and safely ingest current Buyee, eBay, and Gripsweat data."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_PSQL_URL = (
    "postgresql://auction:auction@127.0.0.1:5544/"
    "auction_warehouse"
)
DEFAULT_SQLALCHEMY_URL = (
    "postgresql+psycopg://auction:auction@127.0.0.1:5544/"
    "auction_warehouse"
)
DEFAULT_EXPECTED_DATABASE_NAME = "auction_warehouse"
DEFAULT_EXPECTED_DATABASE_USER = "auction"

BUYEE_URL = (
    "https://buyee.jp/myorders/watchlist/closed"
)


BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE = 2
BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE = 3
BUYEE_ACCESS_BLOCKED_EXIT_CODE = 4

BUYEE_MAINTENANCE_EXIT_CODE = 5
BUYEE_SOURCE_AVAILABLE = (
    "BUYEE_SOURCE_AVAILABLE"
)
BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED = (
    "BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED"
)

BUYEE_SOURCE_UNAVAILABLE_MAINTENANCE = (
    "BUYEE_SOURCE_UNAVAILABLE_MAINTENANCE"
)

# BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED_CONTRACT_V2


class CommandFailure(RuntimeError):
    """Raised when a child command fails."""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a protected all-source Auction ETL refresh."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            DEFAULT_SQLALCHEMY_URL,
        ),
    )
    parser.add_argument(
        "--buyee-profile",
        default=os.environ.get(
            "AUCTION_BUYEE_PROFILE",
            "buyee",
        ),
    )
    parser.add_argument(
        "--require-all-sources",
        action="store_true",
        help=(
            "Fail if Buyee or eBay is unavailable instead of "
            "continuing in degraded mode."
        ),
    )
    parser.add_argument(
        "--expected-database-name",
        default=os.environ.get(
            "AUCTION_EXPECTED_DATABASE_NAME",
            DEFAULT_EXPECTED_DATABASE_NAME,
        ),
    )
    parser.add_argument(
        "--expected-database-user",
        default=os.environ.get(
            "AUCTION_EXPECTED_DATABASE_USER",
            DEFAULT_EXPECTED_DATABASE_USER,
        ),
    )
    return parser.parse_args()


def normalize_psycopg_url(database_url: str) -> str:
    """Convert a SQLAlchemy URL into a Psycopg URL."""
    normalized = database_url.strip()

    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ):
        if normalized.startswith(prefix):
            return "postgresql://" + normalized[len(prefix) :]

    return normalized


def sqlalchemy_url(database_url: str) -> str:
    """Return a SQLAlchemy Psycopg URL."""
    normalized = database_url.strip()

    if normalized.startswith("postgresql://"):
        return (
            "postgresql+psycopg://"
            + normalized[len("postgresql://") :]
        )

    return normalized


def write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def configure_logging(log_path: Path) -> logging.Logger:
    """Configure console and file logging."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("latest-auction-refresh")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(
        log_path,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(
        sys.stdout
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def emit_source_state(
    logger: logging.Logger,
    source: str,
    state: str,
    *,
    status_file: Path | None = None,
    status: dict[str, Any] | None = None,
) -> None:
    """Emit and persist one marketplace lifecycle event."""

    source_keys = {
        "Buyee": "buyee",
        "eBay": "ebay",
        "Gripsweat": "gripsweat",
    }
    allowed_states = {
        "running",
        "done",
        "unavailable",
        "failed",
    }

    if source not in source_keys:
        raise ValueError(
            f"Unsupported marketplace source: {source!r}"
        )

    if state not in allowed_states:
        raise ValueError(
            f"Unsupported marketplace state: {state!r}"
        )

    logger.info(
        "AUCTION_SOURCE_STATE source=%s state=%s",
        source,
        state,
    )

    if status_file is None or status is None:
        return

    source_key = source_keys[source]
    now = datetime.now(
        timezone.utc
    ).isoformat()

    if (
        source_key == "buyee"
        and state == "running"
    ):
        status["marketplace_states"] = {
            "buyee": "running",
            "ebay": "waiting",
            "gripsweat": "waiting",
        }
        status["marketplace_timing"] = {
            "buyee": {
                "started_at": now,
            },
            "ebay": {},
            "gripsweat": {},
        }
    else:
        marketplace_states = status.setdefault(
            "marketplace_states",
            {
                "buyee": "waiting",
                "ebay": "waiting",
                "gripsweat": "waiting",
            },
        )
        marketplace_states[
            source_key
        ] = state

        timing = status.setdefault(
            "marketplace_timing",
            {},
        )
        source_timing = timing.setdefault(
            source_key,
            {},
        )

        if state == "running":
            source_timing[
                "started_at"
            ] = now
            source_timing.pop(
                "finished_at",
                None,
            )
        else:
            source_timing[
                "finished_at"
            ] = now

    status["current_marketplace"] = source_key
    status["current_marketplace_state"] = state
    status["updated_at"] = now

    write_json_atomic(
        status_file,
        status,
    )

    diagnostic = {
        "message":
            str(
                status.get(
                    "message",
                    "",
                )
                or ""
            ),
        "source_state":
            status.get(
                f"{source_key}_source_state"
            ),
        "runtime_semantics":
            status.get(
                f"{source_key}_runtime_semantics"
            ),
    }

    if source_key == "buyee":
        diagnostic[
            "verifier_exit_code"
        ] = status.get(
            "buyee_verifier_exit_code"
        )

    logger.info(
        "AUCTION_SOURCE_DIAGNOSTIC source=%s payload=%s",
        source,
        json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ),
    )



def run_command(
    command: list[str],
    *,
    root: Path,
    environment: dict[str, str],
    logger: logging.Logger,
    phase: str,
    status_file: Path,
    status: dict[str, Any],
    allow_failure: bool = False,
) -> tuple[int, str]:
    """Run one command while streaming and recording its output."""
    status.update(
        {
            "state": "running",
            "phase": phase,
            "message": "Running: "
            + " ".join(command),
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }
    )
    write_json_atomic(status_file, status)

    logger.info("")
    logger.info(phase)
    logger.info("-" * len(phase))
    logger.info("Command: %s", " ".join(command))
    logger.info("")

    process = subprocess.Popen(
        command,
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines: list[str] = []

    assert process.stdout is not None

    for line in process.stdout:
        output_lines.append(line)
        logger.info(line.rstrip())

    return_code = process.wait()
    output = "".join(output_lines)

    if return_code != 0 and not allow_failure:
        raise CommandFailure(
            f"{phase} exited with status {return_code}."
        )

    return return_code, output



def scalar(
    connection: psycopg.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> Any:
    """Return the first value from a scalar query."""
    row = connection.execute(
        query,
        parameters,
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Scalar query returned no result row."
        )

    if isinstance(row, dict):
        try:
            return next(iter(row.values()))
        except StopIteration as exc:
            raise RuntimeError(
                "Scalar query returned an empty result row."
            ) from exc

    return row[0]

def database_state(
    connection: psycopg.Connection,
) -> dict[str, int | str]:
    """Read protected warehouse counts."""
    row = connection.execute(
        """
        SELECT
            current_database() AS database_name,
            current_user AS database_user,
            COUNT(*) AS total_rows,
            COUNT(
                DISTINCT (
                    marketplace,
                    listing_id
                )
            ) AS unique_rows,
            COUNT(*) FILTER (
                WHERE marketplace = 'buyee'
            ) AS buyee_rows,
            COUNT(*) FILTER (
                WHERE marketplace = 'ebay'
            ) AS ebay_rows
        FROM warehouse.auction
        """
    ).fetchone()

    duplicates = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                marketplace,
                listing_id
            FROM warehouse.auction
            GROUP BY
                marketplace,
                listing_id
            HAVING COUNT(*) > 1
        ) AS duplicates
        """,
    )

    gripsweat = scalar(
        connection,
        "SELECT COUNT(*) FROM warehouse.gripsweat_sale",
    )
    collectors = scalar(
        connection,
        "SELECT COUNT(*) FROM warehouse.auction_collector",
    )
    effective = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM warehouse.auction_collector_effective
        """,
    )
    review = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM warehouse.auction_collector_review
        """,
    )

    return {
        "database_name": str(row["database_name"]),
        "database_user": str(row["database_user"]),
        "total_rows": int(row["total_rows"]),
        "unique_rows": int(row["unique_rows"]),
        "buyee_rows": int(row["buyee_rows"]),
        "ebay_rows": int(row["ebay_rows"]),
        "gripsweat_rows": int(gripsweat),
        "collector_rows": int(collectors),
        "effective_rows": int(effective),
        "review_rows": int(review),
        "duplicate_groups": int(duplicates),
    }


def verify_state(
    state: dict[str, int | str],
    *,
    expected_database_name: str = DEFAULT_EXPECTED_DATABASE_NAME,
    expected_database_user: str = DEFAULT_EXPECTED_DATABASE_USER,
) -> None:
    """Validate core database invariants."""
    expected_name = expected_database_name.strip()
    expected_user = expected_database_user.strip()

    if not expected_name:
        raise ValueError(
            "Expected database name must not be empty."
        )

    if not expected_user:
        raise ValueError(
            "Expected database user must not be empty."
        )

    if state["database_name"] != expected_name:
        raise RuntimeError(
            "Unexpected database name: "
            f"expected {expected_name!r}, "
            f"found {state['database_name']!r}."
        )

    if state["database_user"] != expected_user:
        raise RuntimeError(
            "Unexpected database user: "
            f"expected {expected_user!r}, "
            f"found {state['database_user']!r}."
        )

    if state["total_rows"] != state["unique_rows"]:
        raise RuntimeError(
            "Warehouse auction identities are not unique."
        )

    if state["duplicate_groups"] != 0:
        raise RuntimeError(
            "Duplicate marketplace/listing identities exist."
        )

    if state["collector_rows"] != state["total_rows"]:
        raise RuntimeError(
            "Collector rows do not match warehouse rows."
        )

    if state["effective_rows"] != state["total_rows"]:
        raise RuntimeError(
            "Effective-view rows do not match warehouse rows."
        )

    if state["review_rows"] != state["total_rows"]:
        raise RuntimeError(
            "Review-view rows do not match warehouse rows."
        )


def snapshot_auction_keys(
    connection: psycopg.Connection,
    path: Path,
) -> None:
    """Save all pre-run auction identities."""
    rows = connection.execute(
        """
        SELECT
            marketplace,
            listing_id
        FROM warehouse.auction
        ORDER BY
            marketplace,
            listing_id
        """
    ).fetchall()

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ("marketplace", "listing_id")
        )

        for row in rows:
            writer.writerow(
                (
                    row["marketplace"],
                    row["listing_id"],
                )
            )


def create_backup(
    *,
    psql_url: str,
    backup_dir: Path,
    label: str,
    logger: logging.Logger,
) -> Path:
    """Create and verify a custom PostgreSQL archive."""
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    final_path = (
        backup_dir
        / f"{label}-{timestamp}.dump"
    )
    partial_path = final_path.with_suffix(
        ".dump.partial"
    )
    manifest_path = Path(
        str(final_path) + ".contents.txt"
    )
    checksum_path = Path(
        str(final_path) + ".sha256"
    )

    backup_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "pg_dump",
            "--dbname",
            psql_url,
            "--format",
            "custom",
            "--file",
            str(partial_path),
        ],
        check=True,
    )

    if not partial_path.is_file() or (
        partial_path.stat().st_size == 0
    ):
        raise RuntimeError(
            "pg_dump produced an empty archive."
        )

    with manifest_path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        subprocess.run(
            [
                "pg_restore",
                "--list",
                str(partial_path),
            ],
            check=True,
            stdout=handle,
        )

    partial_path.replace(final_path)

    digest = hashlib.sha256(
        final_path.read_bytes()
    ).hexdigest()

    checksum_path.write_text(
        f"{digest}  {final_path.name}\n",
        encoding="utf-8",
    )

    os.chmod(final_path, 0o600)
    os.chmod(manifest_path, 0o600)
    os.chmod(checksum_path, 0o600)

    logger.info("")
    logger.info("Backup: %s", final_path)
    logger.info("SHA-256: %s", digest)

    return final_path


def enabled_ebay_sources(
    path: Path,
) -> list[str]:
    """Read enabled eBay source names."""
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if isinstance(payload, dict):
        values = payload.get("sources", payload)

        if isinstance(values, dict):
            entries = [
                dict(value, _fallback_name=key)
                for key, value in values.items()
                if isinstance(value, dict)
            ]
        elif isinstance(values, list):
            entries = values
        else:
            entries = []
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = []

    names: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        if entry.get("enabled", True) is False:
            continue

        name = (
            entry.get("name")
            or entry.get("source")
            or entry.get("slug")
            or entry.get("_fallback_name")
        )

        if name:
            names.append(str(name))

    if not names:
        raise RuntimeError(
            "No enabled eBay source exists."
        )

    return list(dict.fromkeys(names))


def ebay_access_blocked(
    return_code: int,
    output: str,
) -> bool:
    """Return whether eBay blocked anonymous programmatic access."""
    if return_code == 0:
        return False

    normalized = output.casefold()

    if (
        "ebay rejected the deployed worker's request with http "
        in normalized
    ):
        return True

    blocked_signals = (
        "blocked http status 403",
        (
            "ebay unexpectedly redirected the anonymous "
            "completed-search page to sign-in"
        ),
    )

    return any(
        signal in normalized
        for signal in blocked_signals
    )


def staging_count(
    connection: psycopg.Connection,
    marketplace: str,
) -> int:
    """Count unique staged listings for one marketplace."""
    return int(
        scalar(
            connection,
            """
            SELECT COUNT(DISTINCT listing_id)
            FROM staging.listing
            WHERE marketplace = %s
            """,
            (marketplace,),
        )
    )


def unparsed_external_ebay_raw_page_count(
    connection: psycopg.Connection,
) -> int:
    """Count pending raw pages created by the structured eBay importer."""
    return int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM raw.page
            WHERE source = 'ebay'
              AND parsed_at IS NULL
              AND url LIKE 'collector://ebay/%%'
            """,
        )
    )


def process_ebay_raw_pages(
    *,
    root: Path,
    environment: dict[str, str],
    logger: logging.Logger,
    status_file: Path,
    status: dict[str, Any],
    psql_url: str,
    phase_label: str,
) -> None:
    """Parse, normalize, validate, and safely synchronize pending eBay pages."""
    run_command(
        [
            sys.executable,
            "-m",
            "auction_etl.cli.main",
            "parse",
            "source",
            "ebay",
        ],
        root=root,
        environment=environment,
        logger=logger,
        phase=f"Parse eBay source {phase_label}",
        status_file=status_file,
        status=status,
    )

    run_command(
        [
            sys.executable,
            "-m",
            "auction_etl.cli.main",
            "normalize",
            "staging",
        ],
        root=root,
        environment=environment,
        logger=logger,
        phase=f"Normalize eBay source {phase_label}",
        status_file=status_file,
        status=status,
    )

    with psycopg.connect(
        psql_url,
        row_factory=dict_row,
    ) as connection:
        ebay_staged = staging_count(
            connection,
            "ebay",
        )

    if ebay_staged < 1:
        raise RuntimeError(
            "No eBay identities exist in staging."
        )

    run_command(
        [
            sys.executable,
            "-m",
            "auction_etl.cli.main",
            "sync",
            "warehouse",
            "--marketplace",
            "ebay",
            "--no-prune",
        ],
        root=root,
        environment=environment,
        logger=logger,
        phase="Safely synchronize eBay without pruning",
        status_file=status_file,
        status=status,
    )



EBAY_KNOWN_STOP_THRESHOLD = 20
GRIPSWEAT_KNOWN_STOP_THRESHOLD = 20

INCREMENTAL_PROGRESS_FIELDS = (
    "discovered",
    "already_known",
    "new",
    "detail_scraped",
    "detail_skipped",
    "discovery_pages",
    "consecutive_known_at_stop",
)


def _read_incremental_json(
    path: Path,
):
    """Read one runtime JSON artifact."""

    import json

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def _read_incremental_object(
    path: Path,
) -> dict[str, object]:
    """Read one runtime JSON object."""

    value = _read_incremental_json(
        path
    )

    if not isinstance(
        value,
        dict,
    ):
        raise RuntimeError(
            f"Expected JSON object: {path}"
        )

    return value


def _safe_incremental_name(
    value: str,
) -> str:
    """Return a filesystem-safe source name."""

    import re

    result = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        value,
    ).strip(
        "-."
    )

    return result or "source"


def _write_incremental_ids(
    path: Path,
    values: set[str] | list[str],
) -> None:
    """Write deterministic newline-delimited IDs."""

    normalized = sorted(
        {
            str(value).strip()
            for value in values
            if str(value).strip()
        }
    )

    path.write_text(
        (
            "\n".join(
                normalized
            )
            + (
                "\n"
                if normalized
                else ""
            )
        ),
        encoding="utf-8",
    )


def _set_incremental_progress(
    status: dict[str, object],
    status_file: Path,
    marketplace: str,
    counters: dict[str, int],
) -> None:
    """Persist one marketplace's counters."""

    root = status.setdefault(
        "marketplace_progress",
        {},
    )

    if not isinstance(
        root,
        dict,
    ):
        root = {}
        status[
            "marketplace_progress"
        ] = root

    root[
        marketplace
    ] = {
        field: int(
            counters.get(
                field,
                0,
            )
        )
        for field in (
            INCREMENTAL_PROGRESS_FIELDS
        )
    }

    write_json_atomic(
        status_file,
        status,
    )


def _merge_incremental_progress(
    status: dict[str, object],
    status_file: Path,
    marketplace: str,
    incoming: dict[str, object],
) -> None:
    """Aggregate one configured source into marketplace counters."""

    root = status.setdefault(
        "marketplace_progress",
        {},
    )

    if not isinstance(
        root,
        dict,
    ):
        root = {}
        status[
            "marketplace_progress"
        ] = root

    current = root.get(
        marketplace
    )

    if not isinstance(
        current,
        dict,
    ):
        current = {
            field: 0
            for field in (
                INCREMENTAL_PROGRESS_FIELDS
            )
        }

    merged: dict[str, int] = {}

    for field in (
        INCREMENTAL_PROGRESS_FIELDS
    ):
        old = int(
            current.get(
                field,
                0,
            )
        )
        new = int(
            incoming.get(
                field,
                0,
            )
        )

        if (
            field
            == "consecutive_known_at_stop"
        ):
            merged[
                field
            ] = max(
                old,
                new,
            )
        else:
            merged[
                field
            ] = old + new

    root[
        marketplace
    ] = merged

    write_json_atomic(
        status_file,
        status,
    )


def _incremental_identity_sequence(
    path: Path,
    field: str,
) -> list[str]:
    """Extract nested JSON identity values in encounter order."""

    if not path.is_file():
        return []

    value = _read_incremental_json(
        path
    )
    result: list[str] = []

    def visit(
        node,
    ) -> None:
        if isinstance(
            node,
            dict,
        ):
            raw = node.get(
                field
            )

            if raw is not None:
                normalized = str(
                    raw
                ).strip()

                if normalized:
                    result.append(
                        normalized
                    )

            for child in node.values():
                visit(
                    child
                )

        elif isinstance(
            node,
            list,
        ):
            for child in node:
                visit(
                    child
                )

    visit(
        value
    )

    return result


def _incremental_unique(
    values: list[str],
) -> list[str]:
    """De-duplicate without changing discovery order."""

    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        if value in seen:
            continue

        seen.add(
            value
        )
        result.append(
            value
        )

    return result


def _incremental_trailing_known(
    values: list[str],
    known: set[str],
) -> int:
    """Count trailing warehouse-known IDs."""

    count = 0

    for value in reversed(
        values
    ):
        if value not in known:
            break

        count += 1

    return count


def _incremental_page_count(
    path: Path,
) -> int:
    """Count discovery page records in nested JSON."""

    if not path.is_file():
        return 0

    value = _read_incremental_json(
        path
    )
    count = 0

    def visit(
        node,
    ) -> None:
        nonlocal count

        if isinstance(
            node,
            dict,
        ):
            if (
                "page_number"
                in node
                and isinstance(
                    node.get(
                        "items"
                    ),
                    list,
                )
            ):
                count += 1

            for child in node.values():
                visit(
                    child
                )

        elif isinstance(
            node,
            list,
        ):
            for child in node:
                visit(
                    child
                )

    visit(
        value
    )

    return count


def _incremental_result_count(
    path: Path,
) -> int:
    """Count detail result rows."""

    if not path.is_file():
        return 0

    value = _read_incremental_json(
        path
    )

    return (
        len(
            value
        )
        if isinstance(
            value,
            list,
        )
        else 0
    )


def main() -> int:
    """Run a complete safe all-source refresh."""
    from auction_etl.services.artist_tracking import prepare_runtime_marketplace_configs
    prepare_runtime_marketplace_configs()
    arguments = parse_arguments()
    root = Path(__file__).resolve().parents[1]

    os.environ.pop("DOCKER_HOST", None)
    os.environ.pop("DOCKER_CONTEXT", None)
    os.environ.pop("PGOPTIONS", None)

    psql_url = normalize_psycopg_url(
        arguments.database_url
    )
    sqlalchemy_database_url = sqlalchemy_url(
        arguments.database_url
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    state_root = Path(
        os.environ.get(
            "AUCTION_SOURCE_REFRESH_STATE_DIR",
            str(
                root
                / "logs"
                / "latest-refresh"
            ),
        )
    ).expanduser()

    if not state_root.is_absolute():
        state_root = (
            root
            / state_root
        )

    run_dir = (
        state_root
        / "runs"
        / timestamp
    )
    export_dir = (
        root
        / "exports"
        / "new-only"
        / timestamp
    )
    status_file = (
        state_root
        / "status.json"
    )
    lock_path = (
        state_root
        / "refresh.lock"
    )
    log_path = run_dir / "refresh.log"
    baseline_path = (
        run_dir / "auction-keys-before.csv"
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger = configure_logging(log_path)

    status: dict[str, Any] = {
        "state": "starting",
        "phase": "preflight",
        "message": "Starting protected auction refresh.",
        "pid": os.getpid(),
        "started_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "run_dir": str(run_dir),
        "export_dir": str(export_dir),
        "log_path": str(log_path),
        "authentication_required": False,
    }
    write_json_atomic(status_file, status)

    lock_handle = lock_path.open("w")

    try:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        status.update(
            {
                "state": "failed",
                "message": (
                    "Another auction refresh is already running."
                ),
                "finished_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )
        write_json_atomic(status_file, status)
        return 1

    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        sqlalchemy_database_url
    )
    environment.pop("DOCKER_HOST", None)
    environment.pop("DOCKER_CONTEXT", None)
    environment.pop("PGOPTIONS", None)

    required_paths = (
        root / "scripts" / "verify_buyee_session.py",
        root / "scripts" / "ensure_buyee_owner.py",
        root / "scripts" / "run_buyee_owner.py",
        root / "scripts" / "run_buyee_owner_job.py",
        root / "scripts" / "inspect_recent_ingestion.py",
        root / "scripts" / "crawl_buyee_live_details.py",
        root / "scripts" / "crawl_buyee_http_details.py",
        root / "scripts" / "crawl_ebay_sources.py",
        root / "scripts" / "setup_gripsweat_schema.py",
        root / "scripts" / "probe_gripsweat.py",
        root / "scripts" / "import_gripsweat_probe.py",
        root / "scripts" / "audit_gripsweat_pagination.py",
        root
        / "scripts"
        / "import_gripsweat_pagination_audit.py",
        root / "scripts" / "enrich_gripsweat_details.py",
        root / "scripts" / "collector_features.py",
        root / "scripts" / "reclassify_collector.py",
        root / "config" / "ebay_sources.json",
        root / "config" / "gripsweat_sources.json",
    )

    try:
        logger.info(
            "Auction ETL safe latest-data refresh"
        )
        logger.info(
            "===================================="
        )
        logger.info("Run: %s", run_dir)
        logger.info(
            "No Docker or Colima command will run."
        )

        for path in required_paths:
            if not path.is_file():
                raise RuntimeError(
                    f"Required file is missing: {path}"
                )

        with psycopg.connect(
            psql_url,
            row_factory=dict_row,
        ) as connection:
            initial_state = database_state(connection)
            verify_state(
                initial_state,
                expected_database_name=(
                    arguments.expected_database_name
                ),
                expected_database_user=(
                    arguments.expected_database_user
                ),
            )

            buyee_listing_ids_before = {
                str(row["listing_id"])
                for row in connection.execute(
                    """
                    SELECT listing_id
                    FROM warehouse.auction
                    WHERE marketplace = %s
                    """,
                    ("buyee",),
                ).fetchall()
            }

            snapshot_auction_keys(
                connection,
                baseline_path,
            )

        logger.info("")
        logger.info("Initial state")
        logger.info("-------------")
        logger.info(
            json.dumps(
                initial_state,
                indent=2,
                sort_keys=True,
            )
        )

        help_status, help_output = run_command(
            [
                sys.executable,
                "-m",
                "auction_etl.cli.main",
                "sync",
                "warehouse",
                "--help",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Validate safe warehouse synchronization",
            status_file=status_file,
            status=status,
            allow_failure=True,
        )

        if help_status != 0 or (
            "--no-prune" not in help_output
        ):
            raise RuntimeError(
                "The safe --no-prune warehouse interface "
                "is unavailable."
            )

        emit_source_state(
            logger,
            "Buyee",
            "running",
            status_file=status_file,
            status=status,
        )

        buyee_owner_socket = Path(
            environment.get(
                "AUCTION_BUYEE_OWNER_SOCKET",
                str(
                    Path.home()
                    / ".auction-etl"
                    / "runtime"
                    / "buyee-owner"
                    / "owner.sock"
                ),
            )
        ).expanduser().resolve()

        environment["AUCTION_BUYEE_PROFILE"] = (
            arguments.buyee_profile
        )

        default_buyee_profile_dir = (
            root
            / "profiles"
            / arguments.buyee_profile
        ).resolve()

        buyee_profile_dir = Path(
            environment.get(
                "AUCTION_BUYEE_PROFILE_DIR",
                str(
                    default_buyee_profile_dir
                ),
            )
        ).expanduser()

        if not buyee_profile_dir.is_absolute():
            buyee_profile_dir = (
                root
                / buyee_profile_dir
            )

        buyee_profile_dir = (
            buyee_profile_dir.resolve()
        )

        buyee_profile_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        environment[
            "AUCTION_BUYEE_PROFILE_DIR"
        ] = str(
            buyee_profile_dir
        )

        buyee_storage_state = Path(
            environment.get(
                "BUYEE_STORAGE_STATE_FILE",
                '/data/buyee-profile/.auction-etl/private/buyee-storage-state.json',
            )
        ).expanduser()

        environment["BUYEE_STORAGE_STATE_FILE"] = str(
            buyee_storage_state
        )

        environment["AUCTION_BUYEE_OWNER_SOCKET"] = str(
            buyee_owner_socket
        )
        environment.pop(
            "AUCTION_BUYEE_CDP_URL",
            None,
        )

        run_command(
            [
                sys.executable,
                "scripts/ensure_buyee_owner.py",
                "--profile-dir",
                str(
                    buyee_profile_dir
                ),
                "--socket-path",
                str(
                    buyee_owner_socket
                ),
                "--timeout-seconds",
                "60",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Ensure reusable Buyee browser owner",
            status_file=status_file,
            status=status,
        )
        logger.info(
            "Buyee browser owner ready; "
            "authenticated HTTPS mode is active."
        )

        status["buyee_profile"] = (
            arguments.buyee_profile
        )
        status["buyee_owner_socket"] = str(
            buyee_owner_socket
        )
        status.pop(
            "buyee_cdp_url",
            None,
        )

        auth_status, _ = run_command(
            [
                sys.executable,
                "scripts/verify_buyee_session.py",
                "--storage-state",
                str(buyee_storage_state),
                "--profile-dir",
                str(
                    buyee_profile_dir
                ),
                "--headless",
                "--timeout-minutes",
                "1",
                "--evidence-dir",
                str(run_dir / "buyee-auth-check"),
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Verify reusable Buyee HTTPS authentication",
            status_file=status_file,
            status=status,
            allow_failure=True,
        )

        status["buyee_verifier_exit_code"] = auth_status
        status["authentication_required"] = False
        status["degraded"] = False

        buyee_available = auth_status == 0

        if auth_status == 0:
            status["buyee_source_state"] = "available"
            status["buyee_runtime_semantics"] = (
                BUYEE_SOURCE_AVAILABLE
            )
        elif (
            auth_status
            == BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE
        ):
            status["authentication_required"] = True
            status["buyee_source_state"] = (
                "authentication_required"
            )
            status["buyee_runtime_semantics"] = (
                "BUYEE_AUTHENTICATION_REQUIRED"
            )

            raise RuntimeError(
                "Buyee authentication is required. "
                "Use the UI authentication button first."
            )
        elif (
            auth_status
            == BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE
        ):
            status["buyee_source_state"] = (
                "verification_timeout"
            )
            status["buyee_runtime_semantics"] = (
                "BUYEE_AUTHENTICATION_STATE_"
                "INDETERMINATE_TIMEOUT"
            )

            raise RuntimeError(
                "Buyee authentication verification timed out; "
                "authentication state remains indeterminate."
            )
        elif (
            auth_status
            == BUYEE_ACCESS_BLOCKED_EXIT_CODE
        ):
            status["buyee_source_state"] = (
                "unavailable_access_blocked"
            )
            status["buyee_runtime_semantics"] = (
                BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED
            )
            status["degraded"] = True
            status["message"] = (
                "Buyee programmatic access is blocked; "
                "continuing the remaining sources."
            )
            status["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            write_json_atomic(
                status_file,
                status,
            )

            logger.warning("")
            emit_source_state(
                logger,
                "Buyee",
                "unavailable",
                status_file=status_file,
                status=status,
            )

            logger.warning(
                "Buyee source unavailable: programmatic "
                "access is blocked."
            )
            logger.warning(
                "Skipping Buyee crawl, parse, synchronization, "
                "and detail enrichment."
            )
            logger.warning(
                "Continuing eBay and Gripsweat refreshes."
            )

            if arguments.require_all_sources:
                raise RuntimeError(
                    "Required source Buyee is unavailable: "
                    + str(
                        status.get(
                            "buyee_source_state",
                            "unknown",
                        )
                    )
                )
        elif (
            auth_status
            == BUYEE_MAINTENANCE_EXIT_CODE
        ):
            status["buyee_source_state"] = (
                "unavailable_maintenance"
            )
            status["buyee_runtime_semantics"] = (
                BUYEE_SOURCE_UNAVAILABLE_MAINTENANCE
            )
            status["degraded"] = True
            status["message"] = (
                "Buyee is undergoing maintenance; "
                "continuing the remaining sources."
            )
            status["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            write_json_atomic(
                status_file,
                status,
            )

            logger.warning("")
            emit_source_state(
                logger,
                "Buyee",
                "unavailable",
                status_file=status_file,
                status=status,
            )

            logger.warning(
                "Buyee source unavailable: site maintenance "
                "was detected."
            )
            logger.warning(
                "Skipping Buyee crawl, parse, synchronization, "
                "and detail enrichment."
            )
            logger.warning(
                "Continuing eBay and Gripsweat refreshes."
            )
        else:
            status["buyee_source_state"] = (
                "verifier_error"
            )
            status["buyee_runtime_semantics"] = (
                "BUYEE_VERIFIER_ERROR"
            )

            raise RuntimeError(
                "Buyee authentication verifier failed with "
                f"unexpected exit status {auth_status}."
            )

        create_backup(
            psql_url=psql_url,
            backup_dir=(
                root
                / "backups"
                / "private"
                / "postgres"
            ),
            label=(
                "auction_warehouse-before-latest-refresh"
            ),
            logger=logger,
        )

        if buyee_available:
            _, buyee_crawl_output = run_command(
                [
                    sys.executable,
                    "scripts/crawl_buyee_http.py",
                    "--state-file",
                    environment.get(
                        "AUCTION_BUYEE_STORAGE_STATE",
                        str(buyee_storage_state),
                    ),
                    "--url",
                    BUYEE_URL,
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Crawl authenticated Buyee closed watchlist",
                status_file=status_file,
                status=status,
            )

            fetched_match = re.search(
                r"Fetched\s+(\d+)\s+page",
                buyee_crawl_output,
                re.IGNORECASE,
            )

            if (
                fetched_match is not None
                and int(fetched_match.group(1)) < 1
            ):
                status["authentication_required"] = True
                raise RuntimeError(
                    "Buyee returned zero fetched pages."
                )

            run_command(
                [
                    sys.executable,
                    "-m",
                    "auction_etl.cli.main",
                    "parse",
                    "latest",
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Parse latest Buyee pages",
                status_file=status_file,
                status=status,
            )

            run_command(
                [
                    sys.executable,
                    "-m",
                    "auction_etl.cli.main",
                    "normalize",
                    "staging",
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Normalize Buyee staging",
                status_file=status_file,
                status=status,
            )

            with psycopg.connect(
                psql_url,
                row_factory=dict_row,
            ) as connection:
                buyee_staged = staging_count(
                    connection,
                    "buyee",
                )

            if buyee_staged < 1:
                raise RuntimeError(
                    "No Buyee identities exist in staging."
                )

            run_command(
                [
                    sys.executable,
                    "-m",
                    "auction_etl.cli.main",
                    "sync",
                    "warehouse",
                    "--marketplace",
                    "buyee",
                    "--no-prune",
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase=(
                    "Safely synchronize Buyee without pruning"
                ),
                status_file=status_file,
                status=status,
            )

            with psycopg.connect(
                psql_url,
                row_factory=dict_row,
            ) as connection:
                buyee_listing_ids_after = {
                    str(row["listing_id"])
                    for row in connection.execute(
                        """
                        SELECT listing_id
                        FROM warehouse.auction
                        WHERE marketplace = %s
                        """,
                        ("buyee",),
                    ).fetchall()
                }

            buyee_new_listing_ids = sorted(
                buyee_listing_ids_after
                - buyee_listing_ids_before
            )

            status[
                "buyee_new_listing_count"
            ] = len(
                buyee_new_listing_ids
            )
            status[
                "buyee_detail_candidate_count"
            ] = len(
                buyee_new_listing_ids
            )
            status[
                "buyee_existing_listing_count"
            ] = len(
                buyee_listing_ids_before
            )
            status["message"] = (
                "Buyee identity synchronization complete: "
                f"{len(buyee_new_listing_ids)} new listing(s) "
                "require detail enrichment."
            )
            status["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            write_json_atomic(
                status_file,
                status,
            )

            logger.info("")
            logger.info(
                "Buyee new-only detail enrichment"
            )
            logger.debug(
                "Buyee internal-owner compatibility: %s %s",
                "scripts/run_buyee_owner_job.py",
                "crawl_live_details",
            )
            logger.info(
                "--------------------------------"
            )
            logger.info(
                "Existing before refresh : %s",
                len(
                    buyee_listing_ids_before
                ),
            )
            logger.info(
                "Warehouse after refresh : %s",
                len(
                    buyee_listing_ids_after
                ),
            )
            logger.info(
                "New detail candidates   : %s",
                len(
                    buyee_new_listing_ids
                ),
            )
            logger.info(
                "Existing listing details are not "
                "revisited by the normal latest refresh."
            )

            if buyee_new_listing_ids:
                buyee_detail_command = [
                    sys.executable,
                    "scripts/crawl_buyee_http_details.py",
                    "--state-file",
                    str(
                        buyee_storage_state
                    ),
                    "--apply",
                    "--delay",
                    "2",
                    "--timeout",
                    "45",
                    "--log-dir",
                    str(
                        run_dir
                        / "buyee-details"
                    ),
                ]

                for listing_id in (
                    buyee_new_listing_ids
                ):
                    buyee_detail_command.extend(
                        [
                            "--listing-id",
                            listing_id,
                        ]
                    )

                run_command(
                    buyee_detail_command,
                    root=root,
                    environment=environment,
                    logger=logger,
                    phase=(
                        "Apply new-only Buyee HTTPS "
                        "detail enrichment"
                    ),
                    status_file=status_file,
                    status=status,
                )
            else:
                logger.info(
                    "No new Buyee listing identities; "
                    "detail-page crawl skipped."
                )

        if buyee_available:
            emit_source_state(
                logger,
                "Buyee",
                "done",
                status_file=status_file,
                status=status,
            )

        emit_source_state(
            logger,
            "eBay",
            "running",
            status_file=status_file,
            status=status,
        )

        ebay_available = True

        with psycopg.connect(
            psql_url,
            row_factory=dict_row,
        ) as connection:
            pending_ebay_raw_pages = (
                unparsed_external_ebay_raw_page_count(
                    connection
                )
            )

        if pending_ebay_raw_pages > 0:
            logger.info(
                "Using %d pending external eBay raw page(s); "
                "browser crawl skipped.",
                pending_ebay_raw_pages,
            )

            process_ebay_raw_pages(
                root=root,
                environment=environment,
                logger=logger,
                status_file=status_file,
                status=status,
                psql_url=psql_url,
                phase_label="external raw-page handoff",
            )
        else:
            for source_name in enabled_ebay_sources(
                root / "config" / "ebay_sources.json"
            ):
                ebay_incremental_stats = (
                    run_dir
                    / (
                        "ebay-incremental-"
                        + _safe_incremental_name(
                            source_name
                        )
                        + ".json"
                    )
                )

                crawl_status, crawl_output = run_command(
                    [
                        sys.executable,
                        "scripts/crawl_ebay_sources.py",
                        "--config",
                        "config/ebay_sources.json",
                        "--source",
                        source_name,
                        "--incremental-newest-first",
                        "--known-stop-threshold",
                        str(
                            EBAY_KNOWN_STOP_THRESHOLD
                        ),
                        "--incremental-stats-file",
                        str(
                            ebay_incremental_stats
                        ),
                    ],
                    root=root,
                    environment=environment,
                    logger=logger,
                    phase=f"Crawl eBay source {source_name}",
                    status_file=status_file,
                    status=status,
                    allow_failure=True,
                )

                if crawl_status != 0:
                    if ebay_access_blocked(
                        crawl_status,
                        crawl_output,
                    ):
                        ebay_available = False

                        status["ebay_source_state"] = (
                            "unavailable_access_blocked"
                        )
                        status["ebay_runtime_semantics"] = (
                            "EBAY_SOURCE_UNAVAILABLE_ACCESS_BLOCKED"
                        )
                        status["degraded"] = True
                        status["message"] = (
                            "eBay programmatic access is blocked; "
                            "continuing Gripsweat refresh."
                        )
                        status["updated_at"] = datetime.now(
                            timezone.utc
                        ).isoformat()

                        write_json_atomic(
                            status_file,
                            status,
                        )

                        logger.warning("")
                        emit_source_state(
                            logger,
                            "eBay",
                            "unavailable",
                            status_file=status_file,
                            status=status,
                        )
                        logger.warning(
                            "eBay source unavailable: "
                            "HTTP 403 access block."
                        )
                        logger.warning(
                            "Skipping eBay parse, normalization, "
                            "warehouse synchronization, and remaining "
                            "eBay sources."
                        )
                        logger.warning(
                            "Continuing Gripsweat refresh."
                        )

                        if arguments.require_all_sources:
                            raise RuntimeError(
                                "Required source eBay is unavailable: "
                                + str(
                                    status.get(
                                        "ebay_source_state",
                                        "unknown",
                                    )
                                )
                            )

                        break

                    raise CommandFailure(
                        f"Crawl eBay source {source_name} "
                        f"exited with status {crawl_status}."
                    )

                _merge_incremental_progress(
                    status,
                    status_file,
                    "ebay",
                    _read_incremental_object(
                        ebay_incremental_stats
                    ),
                )

                process_ebay_raw_pages(
                    root=root,
                    environment=environment,
                    logger=logger,
                    status_file=status_file,
                    status=status,
                    psql_url=psql_url,
                    phase_label=source_name,
                )

        if ebay_available:
            status["ebay_source_state"] = "available"
            status["ebay_runtime_semantics"] = (
                "EBAY_SOURCE_AVAILABLE"
            )

            emit_source_state(
                logger,
                "eBay",
                "done",
                status_file=status_file,
                status=status,
            )

        emit_source_state(
            logger,
            "Gripsweat",
            "running",
            status_file=status_file,
            status=status,
        )

        run_command(
            [
                sys.executable,
                "scripts/setup_gripsweat_schema.py",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Prepare Gripsweat schema",
            status_file=status_file,
            status=status,
        )

        with psycopg.connect(
            psql_url,
            row_factory=dict_row,
        ) as connection:
            gripsweat_before_rows = (
                connection.execute(
                    """
                    SELECT
                        gripsweat_item_key,
                        gripsweat_item_id
                    FROM warehouse.gripsweat_sale
                    """
                ).fetchall()
            )

        gripsweat_item_keys_before = {
            str(
                row[
                    "gripsweat_item_key"
                ]
            ).strip()
            for row in gripsweat_before_rows
            if row[
                "gripsweat_item_key"
            ] is not None
            and str(
                row[
                    "gripsweat_item_key"
                ]
            ).strip()
        }

        gripsweat_item_ids_before = {
            str(
                row[
                    "gripsweat_item_id"
                ]
            ).strip()
            for row in gripsweat_before_rows
            if row[
                "gripsweat_item_id"
            ] is not None
            and str(
                row[
                    "gripsweat_item_id"
                ]
            ).strip()
        }

        _set_incremental_progress(
            status,
            status_file,
            "gripsweat",
            {
                field: 0
                for field in (
                    INCREMENTAL_PROGRESS_FIELDS
                )
            },
        )

        probe_path = run_dir / "gripsweat-probe.json"
        audit_path = (
            run_dir
            / "gripsweat-pagination-audit.json"
        )

        run_command(
            [
                sys.executable,
                "scripts/probe_gripsweat.py",
                "--config",
                "config/gripsweat_sources.json",
                "--max-pages",
                "1",
                "--wait-seconds",
                "8",
                "--output",
                str(probe_path),
                "--diagnostic-dir",
                str(run_dir / "gripsweat-probe"),
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Probe configured Gripsweat sources",
            status_file=status_file,
            status=status,
        )

        run_command(
            [
                sys.executable,
                "scripts/import_gripsweat_probe.py",
                "--config",
                "config/gripsweat_sources.json",
                "--probe",
                str(probe_path),
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Import Gripsweat probe",
            status_file=status_file,
            status=status,
        )

        gripsweat_probe_sequence = (
            _incremental_identity_sequence(
                probe_path,
                "gripsweat_item_key",
            )
        )
        gripsweat_probe_unique = (
            _incremental_unique(
                gripsweat_probe_sequence
            )
        )
        gripsweat_probe_known = sum(
            value
            in gripsweat_item_keys_before
            for value in (
                gripsweat_probe_unique
            )
        )
        gripsweat_probe_new = (
            len(
                gripsweat_probe_unique
            )
            - gripsweat_probe_known
        )
        gripsweat_probe_trailing_known = (
            _incremental_trailing_known(
                gripsweat_probe_sequence,
                gripsweat_item_keys_before,
            )
        )
        gripsweat_stop_after_probe = (
            bool(
                gripsweat_probe_sequence
            )
            and gripsweat_probe_trailing_known
            >= GRIPSWEAT_KNOWN_STOP_THRESHOLD
        )

        _set_incremental_progress(
            status,
            status_file,
            "gripsweat",
            {
                "discovered": len(
                    gripsweat_probe_unique
                ),
                "already_known": (
                    gripsweat_probe_known
                ),
                "new": gripsweat_probe_new,
                "detail_scraped": 0,
                "detail_skipped": (
                    gripsweat_probe_known
                ),
                "discovery_pages": (
                    _incremental_page_count(
                        probe_path
                    )
                ),
                "consecutive_known_at_stop": (
                    gripsweat_probe_trailing_known
                    if gripsweat_stop_after_probe
                    else 0
                ),
            },
        )

        logger.info("")
        logger.info(
            "Gripsweat incremental discovery gate"
        )
        logger.info(
            "------------------------------------"
        )
        logger.info(
            "Discovered           : %s",
            len(
                gripsweat_probe_unique
            ),
        )
        logger.info(
            "Already known        : %s",
            gripsweat_probe_known,
        )
        logger.info(
            "New                  : %s",
            gripsweat_probe_new,
        )
        logger.info(
            "Trailing known       : %s",
            gripsweat_probe_trailing_known,
        )

        if not gripsweat_stop_after_probe:
            run_command(
                [
                    sys.executable,
                    "scripts/audit_gripsweat_pagination.py",
                    "--config",
                    "config/gripsweat_sources.json",
                    "--pages",
                    "10",
                    "--delay",
                    "2",
                    "--wait-seconds",
                    "6",
                    "--output",
                    str(audit_path),
                    "--diagnostics-dir",
                    str(run_dir / "gripsweat-pagination"),
                    "--empty-page-limit",
                    "2",
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Crawl Gripsweat pagination",
                status_file=status_file,
                status=status,
            )

            run_command(
                [
                    sys.executable,
                    "scripts/import_gripsweat_pagination_audit.py",
                    "--input",
                    str(audit_path),
                    "--dry-run",
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Validate Gripsweat identities",
                status_file=status_file,
                status=status,
            )

            run_command(
                [
                    sys.executable,
                    "scripts/import_gripsweat_pagination_audit.py",
                    "--input",
                    str(audit_path),
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Import Gripsweat identities",
                status_file=status_file,
                status=status,
            )

        else:
            logger.info(
                "Skipping Gripsweat pagination audit: "
                "newest-page overlap already reached "
                "the known-ID threshold."
            )

        with psycopg.connect(
            psql_url,
            row_factory=dict_row,
        ) as connection:
            gripsweat_after_rows = (
                connection.execute(
                    """
                    SELECT
                        gripsweat_item_key,
                        gripsweat_item_id
                    FROM warehouse.gripsweat_sale
                    """
                ).fetchall()
            )

        gripsweat_item_keys_after = {
            str(
                row[
                    "gripsweat_item_key"
                ]
            ).strip()
            for row in gripsweat_after_rows
            if row[
                "gripsweat_item_key"
            ] is not None
            and str(
                row[
                    "gripsweat_item_key"
                ]
            ).strip()
        }

        gripsweat_item_ids_after = {
            str(
                row[
                    "gripsweat_item_id"
                ]
            ).strip()
            for row in gripsweat_after_rows
            if row[
                "gripsweat_item_id"
            ] is not None
            and str(
                row[
                    "gripsweat_item_id"
                ]
            ).strip()
        }

        gripsweat_new_item_keys = (
            gripsweat_item_keys_after
            - gripsweat_item_keys_before
        )
        gripsweat_new_item_ids = sorted(
            gripsweat_item_ids_after
            - gripsweat_item_ids_before
        )

        gripsweat_audit_sequence = (
            _incremental_identity_sequence(
                audit_path,
                "gripsweat_item_key",
            )
            if audit_path.is_file()
            else []
        )

        gripsweat_discovery_sequence = (
            gripsweat_probe_sequence
            + gripsweat_audit_sequence
        )
        gripsweat_discovered_unique = (
            _incremental_unique(
                gripsweat_discovery_sequence
            )
        )

        gripsweat_already_known = sum(
            value
            in gripsweat_item_keys_before
            for value in (
                gripsweat_discovered_unique
            )
        )

        gripsweat_stop_sequence = (
            gripsweat_audit_sequence
            or gripsweat_probe_sequence
        )

        gripsweat_consecutive_known = (
            _incremental_trailing_known(
                gripsweat_stop_sequence,
                gripsweat_item_keys_before,
            )
        )

        gripsweat_discovery_pages = (
            _incremental_page_count(
                probe_path
            )
            + (
                _incremental_page_count(
                    audit_path
                )
                if audit_path.is_file()
                else 0
            )
        )

        gripsweat_id_file = (
            run_dir
            / "gripsweat-new-item-ids.txt"
        )
        gripsweat_detail_output = (
            run_dir
            / "gripsweat-detail-apply.json"
        )

        detail_scraped = 0

        if gripsweat_new_item_ids:
            _write_incremental_ids(
                gripsweat_id_file,
                gripsweat_new_item_ids,
            )

            run_command(
                [
                    sys.executable,
                    "scripts/enrich_gripsweat_details.py",
                    "--apply",
                    "--probe",
                    str(
                        probe_path
                    ),
                    "--delay",
                    "2",
                    "--wait-seconds",
                    "6",
                    "--attempts",
                    "3",
                    "--retry-delay",
                    "10",
                    "--item-id-file",
                    str(
                        gripsweat_id_file
                    ),
                    "--output",
                    str(
                        gripsweat_detail_output
                    ),
                    "--diagnostics-dir",
                    str(
                        run_dir
                        / "gripsweat-details"
                    ),
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Apply Gripsweat detail enrichment",
                status_file=status_file,
                status=status,
            )

            detail_scraped = (
                _incremental_result_count(
                    gripsweat_detail_output
                )
            )
        else:
            logger.info("")
            logger.info(
                "No new Gripsweat identities; "
                "detail-page crawl skipped."
            )

        gripsweat_discovered_count = max(
            len(
                gripsweat_discovered_unique
            ),
            len(
                gripsweat_new_item_keys
            ),
        )

        _set_incremental_progress(
            status,
            status_file,
            "gripsweat",
            {
                "discovered": (
                    gripsweat_discovered_count
                ),
                "already_known": (
                    gripsweat_already_known
                ),
                "new": len(
                    gripsweat_new_item_keys
                ),
                "detail_scraped": (
                    detail_scraped
                ),
                "detail_skipped": max(
                    0,
                    gripsweat_discovered_count
                    - detail_scraped,
                ),
                "discovery_pages": (
                    gripsweat_discovery_pages
                ),
                "consecutive_known_at_stop": (
                    gripsweat_consecutive_known
                ),
            },
        )

        logger.info("")
        logger.info(
            "Gripsweat incremental summary"
        )
        logger.info(
            "-----------------------------"
        )
        logger.info(
            "Discovered             : %s",
            gripsweat_discovered_count,
        )
        logger.info(
            "Already known          : %s",
            gripsweat_already_known,
        )
        logger.info(
            "New identities         : %s",
            len(
                gripsweat_new_item_keys
            ),
        )
        logger.info(
            "Detail pages scraped   : %s",
            detail_scraped,
        )
        logger.info(
            "Discovery pages        : %s",
            gripsweat_discovery_pages,
        )
        logger.info(
            "Consecutive known stop : %s",
            gripsweat_consecutive_known,
        )

        emit_source_state(
            logger,
            "Gripsweat",
            "done",
            status_file=status_file,
            status=status,
        )

        run_command(
            [
                sys.executable,
                "scripts/collector_features.py",
                "build",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Rebuild collector features",
            status_file=status_file,
            status=status,
        )

        run_command(
            [
                sys.executable,
                "scripts/reclassify_collector.py",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Reclassify collector values",
            status_file=status_file,
            status=status,
        )

        update_fx = (
            root / "scripts" / "update_auction_fx.py"
        )

        if update_fx.is_file():
            run_command(
                [
                    sys.executable,
                    str(update_fx),
                ],
                root=root,
                environment=environment,
                logger=logger,
                phase="Update auction FX values",
                status_file=status_file,
                status=status,
            )

        run_command(
            [
                sys.executable,
                "-m",
                "auction_etl.cli.main",
                "doctor",
                "run",
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Run application health checks",
            status_file=status_file,
            status=status,
        )

        run_command(
            [
                sys.executable,
                "scripts/inspect_recent_ingestion.py",
                "--database-url",
                psql_url,
                "--baseline",
                str(baseline_path),
                "--output-dir",
                str(export_dir),
            ],
            root=root,
            environment=environment,
            logger=logger,
            phase="Export newly ingested auction identities",
            status_file=status_file,
            status=status,
        )

        with psycopg.connect(
            psql_url,
            row_factory=dict_row,
        ) as connection:
            final_state = database_state(connection)

        verify_state(
            final_state,
            expected_database_name=(
                arguments.expected_database_name
            ),
            expected_database_user=(
                arguments.expected_database_user
            ),
        )

        if (
            int(final_state["total_rows"])
            < int(initial_state["total_rows"])
        ):
            raise RuntimeError(
                "Warehouse row count decreased."
            )

        if (
            int(final_state["buyee_rows"])
            < int(initial_state["buyee_rows"])
        ):
            raise RuntimeError(
                "Buyee warehouse rows decreased."
            )

        if (
            int(final_state["ebay_rows"])
            < int(initial_state["ebay_rows"])
        ):
            raise RuntimeError(
                "eBay warehouse rows decreased."
            )

        create_backup(
            psql_url=psql_url,
            backup_dir=(
                root
                / "backups"
                / "private"
                / "postgres"
            ),
            label=(
                "auction_warehouse-after-latest-refresh"
            ),
            logger=logger,
        )

        summary_path = export_dir / "summary.json"
        summary = json.loads(
            summary_path.read_text(encoding="utf-8")
        )

        status.update(
            {
                "state": "success",
                "phase": "completed",
                "message": (
                    "Latest auction refresh completed."
                ),
                "finished_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "authentication_required": False,
                "initial_state": initial_state,
                "final_state": final_state,
                "summary": summary,
            }
        )
        write_json_atomic(status_file, status)

        logger.info("")
        logger.info("Refresh completed")
        logger.info("=================")
        logger.info(
            json.dumps(
                final_state,
                indent=2,
                sort_keys=True,
            )
        )
        logger.info("Exports: %s", export_dir)
        return 0
    except Exception as exc:
        logger.exception("Refresh failed: %s", exc)

        status.update(
            {
                "state": "failed",
                "phase": "failed",
                "message": str(exc),
                "error": str(exc),
                "finished_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )
        write_json_atomic(status_file, status)
        return 1
    finally:
        try:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
