#!/usr/bin/env python3
"""Run one guarded Buyee, eBay, and Gripsweat ingestion round."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

PRESSING_REFERENCE_POLICY = (
    "EVIDENCE_ONLY_NO_TITLE_ONLY_AUTO_ASSIGNMENT"
)


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATABASE_URL = (
    "postgresql://auction:auction@127.0.0.1:5544/"
    "auction_warehouse"
)

SOURCE_RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

LOCK_PATH = (
    ROOT
    / "logs"
    / "ingestion-round"
    / "multisource-ingestion-round.lock"
)

PROTECTED_KEYS = (
    "assignments",
    "snapshots",
    "timeline",
    "pressings",
    "families",
)


class MultiSourceIngestionError(RuntimeError):
    """Raised when a guarded multi-source invariant fails."""


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse multi-source ingestion arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run one protected Buyee + eBay + Gripsweat "
            "source refresh."
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
        "--output-dir",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--buyee-profile",
        default=os.environ.get(
            "AUCTION_BUYEE_PROFILE",
            "buyee",
        ),
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Execute live source refreshes. Without this "
            "flag only guarded preflight runs."
        ),
    )

    return parser.parse_args(argv)


def psql_url(database_url: str) -> str:
    """Normalize SQLAlchemy PostgreSQL URLs for psycopg."""

    value = database_url.strip()

    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ):
        if value.startswith(prefix):
            return (
                "postgresql://"
                + value[len(prefix):]
            )

    return value


def atomic_write_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    """Write one JSON object atomically."""

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


def read_json(
    path: Path,
) -> dict[str, Any]:
    """Read one JSON object if available."""

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        return {}

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return payload


def query_one(
    database_url: str,
    statement: str,
    parameters: Sequence[Any] = (),
) -> Mapping[str, Any]:
    """Run one read-only query and return its first row."""

    with psycopg.connect(
        psql_url(database_url),
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
        raise MultiSourceIngestionError(
            "Read-only query returned no row."
        )

    return row


def query_all(
    database_url: str,
    statement: str,
    parameters: Sequence[Any] = (),
) -> list[Mapping[str, Any]]:
    """Run one read-only query and return all rows."""

    with psycopg.connect(
        psql_url(database_url),
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


def database_state(
    database_url: str,
) -> dict[str, int]:
    """Capture core and protected ingestion state."""

    row = query_one(
        database_url,
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM warehouse.auction
            ) AS auctions,
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
            ) AS queue,
            (
                SELECT COUNT(*)
                FROM warehouse.pressing_identity
            ) AS pressings,
            (
                SELECT COUNT(*)
                FROM warehouse.release_family
            ) AS families,
            (
                SELECT COUNT(*)
                FROM warehouse.gripsweat_sale
            ) AS gripsweat_sales,
            (
                SELECT COUNT(*)
                FROM system.crawl_job
            ) AS crawl_jobs,
            (
                SELECT COUNT(*)
                FROM raw.page
            ) AS raw_pages
        """,
    )

    return {
        key: int(value)
        for key, value in row.items()
    }


def pending_marketplace_identities(
    database_url: str,
) -> dict[str, int]:
    """Count staged Buyee/eBay identities missing from warehouse."""

    rows = query_all(
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
            ) IN (
                'buyee',
                'ebay'
            )
        ),
        pending AS (
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
        )
        SELECT
            marketplace,
            COUNT(*) AS pending
        FROM pending
        GROUP BY marketplace
        ORDER BY marketplace
        """,
    )

    result = {
        "buyee": 0,
        "ebay": 0,
    }

    for row in rows:
        result[
            str(row["marketplace"])
        ] = int(
            row["pending"]
        )

    return result


def reference_coverage(
    database_url: str,
) -> list[dict[str, Any]]:
    """Report stable-reference evidence coverage in auctions."""

    rows = query_all(
        database_url,
        """
        SELECT
            lower(
                btrim(marketplace)
            ) AS marketplace,
            COUNT(*) AS rows,
            COUNT(*) FILTER (
                WHERE NULLIF(
                    btrim(catalog_number),
                    ''
                ) IS NOT NULL
            ) AS catalog_number_rows,
            COUNT(*) FILTER (
                WHERE NULLIF(
                    btrim(COALESCE(to_jsonb(auction)->>'release_country', to_jsonb(auction)->>'country')),
                    ''
                ) IS NOT NULL
            ) AS country_rows,
            COUNT(*) FILTER (
                WHERE NULLIF(
                    btrim(COALESCE(to_jsonb(auction)->>'release_format', to_jsonb(auction)->>'media_type', to_jsonb(auction)->>'format')),
                    ''
                ) IS NOT NULL
            ) AS format_rows,
            COUNT(*) FILTER (
                WHERE COALESCE(to_jsonb(auction)->>'release_year', to_jsonb(auction)->>'year') IS NOT NULL
            ) AS year_rows
        FROM warehouse.auction
        GROUP BY lower(
            btrim(marketplace)
        )
        ORDER BY marketplace
        """,
    )

    return [
        dict(row)
        for row in rows
    ]


def assert_pressing_reference_schema(
    database_url: str,
) -> None:
    """Require the installed stable pressing-reference contract."""

    row = query_one(
        database_url,
        """
        SELECT
            to_regclass(
                'warehouse.pressing_reference_catalog'
            ) IS NOT NULL
                AS catalog_view_exists,
            (
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'warehouse'
                  AND table_name =
                      'pressing_identity'
                  AND column_name IN (
                      'release_language',
                      'release_format',
                      'release_type'
                  )
            ) AS identity_columns,
            (
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'warehouse'
                  AND table_name =
                      'pressing_matrix_runout'
            ) AS matrix_tables
        """,
    )

    if row["catalog_view_exists"] is not True:
        raise MultiSourceIngestionError(
            "warehouse.pressing_reference_catalog "
            "is missing."
        )

    if int(
        row["identity_columns"]
    ) != 3:
        raise MultiSourceIngestionError(
            "Pressing-reference identity columns "
            "are incomplete."
        )

    if int(
        row["matrix_tables"]
    ) != 1:
        raise MultiSourceIngestionError(
            "warehouse.pressing_matrix_runout "
            "is missing."
        )

    forbidden = query_one(
        database_url,
        """
        SELECT
            COUNT(*) AS forbidden_columns
        FROM information_schema.columns
        WHERE table_schema = 'warehouse'
          AND table_name =
              'pressing_reference_catalog'
          AND column_name IN (
              'marketplace',
              'listing_id',
              'seller',
              'final_price',
              'gross_price',
              'bid_count',
              'condition_text'
          )
        """,
    )

    if int(
        forbidden[
            "forbidden_columns"
        ]
    ) != 0:
        raise MultiSourceIngestionError(
            "Stable pressing-reference view contains "
            "auction/copy fields."
        )


def git_tracked_hash() -> str:
    """Hash tracked repository differences relative to HEAD."""

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


def auction_keys(
    database_url: str,
) -> set[tuple[str, str]]:
    """Snapshot warehouse auction identities."""

    rows = query_all(
        database_url,
        """
        SELECT
            lower(
                btrim(marketplace)
            ) AS marketplace,
            listing_id
        FROM warehouse.auction
        """,
    )

    return {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in rows
    }


def gripsweat_keys(
    database_url: str,
) -> set[str]:
    """Snapshot retained Gripsweat URLs."""

    rows = query_all(
        database_url,
        """
        SELECT gripsweat_url
        FROM warehouse.gripsweat_sale
        WHERE gripsweat_url IS NOT NULL
        """,
    )

    return {
        str(row["gripsweat_url"])
        for row in rows
    }


def payload_matrix_strings(
    value: Any,
    *,
    key_hint: str = "",
) -> list[tuple[str, str]]:
    """Extract strings only from matrix/runout-shaped payload keys."""

    found: list[
        tuple[str, str]
    ] = []

    if isinstance(
        value,
        dict,
    ):
        for key, child in value.items():
            found.extend(
                payload_matrix_strings(
                    child,
                    key_hint=str(key),
                )
            )

        return found

    if isinstance(
        value,
        list,
    ):
        for child in value:
            found.extend(
                payload_matrix_strings(
                    child,
                    key_hint=key_hint,
                )
            )

        return found

    if (
        isinstance(
            value,
            str,
        )
        and re.search(
            r"matrix|runout",
            key_hint,
            re.IGNORECASE,
        )
    ):
        cleaned = " ".join(
            value.split()
        )

        if cleaned:
            found.append(
                (
                    key_hint,
                    cleaned,
                )
            )

    return found


def release_language_hint(
    payload: Any,
) -> str | None:
    """Return an explicitly supplied language value when present."""

    if not isinstance(
        payload,
        dict,
    ):
        return None

    for key, value in payload.items():
        if not re.fullmatch(
            r"(release_)?language",
            str(key),
            flags=re.IGNORECASE,
        ):
            continue

        if not isinstance(
            value,
            str,
        ):
            continue

        cleaned = " ".join(
            value.split()
        )

        return cleaned or None

    return None


def release_format_hint(
    value: Any,
) -> str | None:
    """Conservatively normalize a physical format hint."""

    if not isinstance(
        value,
        str,
    ):
        return None

    cleaned = (
        " ".join(
            value.upper().split()
        )
    )

    mappings = (
        ("CASSETTE", "CASSETTE"),
        ("TAPE", "CASSETTE"),
        ("CD", "CD"),
        ('12"', '12"'),
        ('10"', '10"'),
        ('7"', '7"'),
        ("EP", "EP"),
        ("LP", "LP"),
    )

    for marker, normalized in mappings:
        if marker in cleaned:
            return normalized

    return None


def release_type_hint(
    title: Any,
    format_hint: str | None,
) -> str | None:
    """Return a non-authoritative release-type hint."""

    cleaned = (
        str(title or "")
        .casefold()
    )

    if re.search(
        r"\blive\b|concert",
        cleaned,
    ):
        return "LIVE"

    if re.search(
        r"soundtrack|\bost\b",
        cleaned,
    ):
        return "SOUNDTRACK"

    if re.search(
        r"compilation|greatest hits|best of",
        cleaned,
    ):
        return "COMPILATION"

    if re.search(
        r"\bpromo\b|promotional",
        cleaned,
    ):
        return "PROMO"

    if format_hint == "EP":
        return "EP"

    if format_hint in {
        '7"',
        '10"',
        '12"',
    }:
        return "SINGLE"

    return None


def stable_reference_evidence(
    database_url: str,
    *,
    prior_auction_keys: set[
        tuple[str, str]
    ],
    prior_gripsweat_keys: set[str],
) -> dict[str, Any]:
    """Build stable-field evidence for newly observed records.

    Listing titles remain observations. They are not promoted to a
    canonical pressing title automatically.
    """

    auction_rows = query_all(
        database_url,
        """
        SELECT
            lower(
                btrim(marketplace)
            ) AS marketplace,
            listing_id,
            title,
            COALESCE(
                to_jsonb(auction)->>'label',
                to_jsonb(auction)->>'record_label'
            ) AS label,
            catalog_number,
            COALESCE(
                to_jsonb(auction)->>'release_country',
                to_jsonb(auction)->>'country'
            ) AS country,
            COALESCE(
                to_jsonb(auction)->>'release_format',
                to_jsonb(auction)->>'media_type',
                to_jsonb(auction)->>'format'
            ) AS format,
            COALESCE(
                to_jsonb(auction)->>'release_year',
                to_jsonb(auction)->>'year'
            ) AS year,
            to_jsonb(auction)->'payload' AS payload
        FROM warehouse.auction AS auction
        ORDER BY
            marketplace,
            listing_id
        """,
    )

    auction_observations: list[
        dict[str, Any]
    ] = []

    for row in auction_rows:
        identity = (
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
        )

        if identity in prior_auction_keys:
            continue

        payload = row.get(
            "payload"
        )

        format_hint = release_format_hint(
            row.get(
                "format"
            )
        )

        matrix_candidates = [
            {
                "source_key": key,
                "value": value,
            }
            for key, value in
            payload_matrix_strings(
                payload
            )
        ]

        auction_observations.append(
            {
                "marketplace":
                    identity[0],
                "listing_id":
                    identity[1],
                "listing_title":
                    row.get("title"),
                "catalog_number":
                    row.get(
                        "catalog_number"
                    ),
                "label":
                    row.get("label"),
                "release_country":
                    row.get("country"),
                "release_language_hint":
                    release_language_hint(
                        payload
                    ),
                "release_year":
                    row.get("year"),
                "release_format_hint":
                    format_hint,
                "release_type_hint":
                    release_type_hint(
                        row.get("title"),
                        format_hint,
                    ),
                "matrix_runout_candidates":
                    matrix_candidates,
            }
        )

    gripsweat_rows = query_all(
        database_url,
        """
        SELECT
            source_name,
            configured_artist,
            title,
            gripsweat_url
        FROM warehouse.gripsweat_sale
        WHERE gripsweat_url IS NOT NULL
        ORDER BY gripsweat_url
        """,
    )

    gripsweat_observations = [
        {
            "source_name":
                row.get(
                    "source_name"
                ),
            "artist":
                row.get(
                    "configured_artist"
                ),
            "listing_title":
                row.get(
                    "title"
                ),
            "gripsweat_url":
                row.get(
                    "gripsweat_url"
                ),
            "catalog_number":
                None,
            "release_country":
                None,
            "release_language_hint":
                None,
            "release_format_hint":
                None,
            "release_type_hint":
                release_type_hint(
                    row.get("title"),
                    None,
                ),
            "matrix_runout_candidates":
                [],
        }
        for row in gripsweat_rows
        if str(
            row["gripsweat_url"]
        )
        not in prior_gripsweat_keys
    ]

    return {
        "schema":
            "pressing-reference-evidence/v1",
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "policy": (
            "Evidence only. Listing title cannot create or "
            "assign a pressing. Reviewed catalog/matrix and "
            "release metadata remain the identity boundary."
        ),
        "auction_observations":
            auction_observations,
        "gripsweat_observations":
            gripsweat_observations,
    }


def verify_transition(
    before: Mapping[str, int],
    after: Mapping[str, int],
) -> dict[str, int]:
    """Verify the post-refresh protected-state transition."""

    for key in PROTECTED_KEYS:
        if int(
            after[key]
        ) != int(
            before[key]
        ):
            raise MultiSourceIngestionError(
                "Protected state changed: "
                f"{key}: "
                f"{before[key]} -> "
                f"{after[key]}"
            )

    if int(
        after["auctions"]
    ) < int(
        before["auctions"]
    ):
        raise MultiSourceIngestionError(
            "Warehouse auction count decreased."
        )

    if int(
        after["gripsweat_sales"]
    ) < int(
        before["gripsweat_sales"]
    ):
        raise MultiSourceIngestionError(
            "Gripsweat sale count decreased."
        )

    expected_queue_before = (
        int(
            before["auctions"]
        )
        - int(
            before["assignments"]
        )
    )

    expected_queue_after = (
        int(
            after["auctions"]
        )
        - int(
            after["assignments"]
        )
    )

    if int(
        before["queue"]
    ) != expected_queue_before:
        raise MultiSourceIngestionError(
            "Pre-run assignment queue invariant failed."
        )

    if int(
        after["queue"]
    ) != expected_queue_after:
        raise MultiSourceIngestionError(
            "Post-run assignment queue invariant failed."
        )

    auction_delta = (
        int(
            after["auctions"]
        )
        - int(
            before["auctions"]
        )
    )

    queue_delta = (
        int(
            after["queue"]
        )
        - int(
            before["queue"]
        )
    )

    if queue_delta != auction_delta:
        raise MultiSourceIngestionError(
            f"Queue delta {queue_delta} "
            f"!= auction delta {auction_delta}."
        )

    return {
        "auction_delta":
            auction_delta,
        "queue_delta":
            queue_delta,
        "gripsweat_delta":
            int(
                after[
                    "gripsweat_sales"
                ]
            )
            - int(
                before[
                    "gripsweat_sales"
                ]
            ),
        "crawl_job_delta":
            int(
                after[
                    "crawl_jobs"
                ]
            )
            - int(
                before[
                    "crawl_jobs"
                ]
            ),
        "raw_page_delta":
            int(
                after[
                    "raw_pages"
                ]
            )
            - int(
                before[
                    "raw_pages"
                ]
            ),
    }


def stream_command(
    command: list[str],
    *,
    environment: Mapping[str, str],
    log_path: Path,
) -> int:
    """Run one child process while teeing its output."""

    log_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with log_path.open(
        "w",
        encoding="utf-8",
    ) as log_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=dict(
                environment
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert process.stdout is not None

        for line in process.stdout:
            sys.stdout.write(
                line
            )
            sys.stdout.flush()

            log_handle.write(
                line
            )
            log_handle.flush()

        return int(
            process.wait()
        )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run preflight or one live guarded all-source round."""
    from auction_etl.services.artist_tracking import prepare_runtime_marketplace_configs
    prepare_runtime_marketplace_configs()

    arguments = parse_args(
        argv
    )

    database_url = psql_url(
        arguments.database_url
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%d-%H%M%S"
    )

    output_dir = (
        arguments.output_dir
        if arguments.output_dir
        is not None
        else (
            ROOT
            / "logs"
            / "ingestion-round"
            / f"multisource-{timestamp}"
        )
    )

    if not output_dir.is_absolute():
        output_dir = (
            ROOT
            / output_dir
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path = (
        output_dir
        / "result.json"
    )

    child_log_path = (
        output_dir
        / "source-refresh.log"
    )

    child_state_dir = (
        output_dir
        / "source-refresh-state"
    )

    evidence_path = (
        output_dir
        / "pressing-reference-evidence.json"
    )

    if not SOURCE_RUNNER.is_file():
        raise MultiSourceIngestionError(
            "Missing all-source runner: "
            f"{SOURCE_RUNNER}"
        )

    assert_pressing_reference_schema(
        database_url
    )

    before = database_state(
        database_url
    )

    pending_before = (
        pending_marketplace_identities(
            database_url
        )
    )

    coverage_before = (
        reference_coverage(
            database_url
        )
    )

    tracked_before = (
        git_tracked_hash()
    )

    prior_auction_keys = (
        auction_keys(
            database_url
        )
    )

    prior_gripsweat_keys = (
        gripsweat_keys(
            database_url
        )
    )

    if any(
        pending_before.values()
    ):
        raise MultiSourceIngestionError(
            "Existing Buyee/eBay staging "
            "contains pending identities: "
            f"{pending_before}"
        )

    verify_transition(
        before,
        before,
    )

    planned = {
        "schema":
            "multisource-ingestion-round/v1",
        "status":
            "PLANNED",
        "executed":
            False,
        "source":
            "multisource",
        "sources": [
            "buyee",
            "ebay",
            "gripsweat",
        ],
        "buyee_profile":
            arguments.buyee_profile,
        "database_before":
            before,
        "pending_before":
            pending_before,
        "reference_coverage_before":
            coverage_before,
        "tracked_hash_before":
            tracked_before,
        "output_dir":
            str(
                output_dir
            ),
        "pressing_reference_policy":
            (
                "EVIDENCE_ONLY_"
                "NO_TITLE_ONLY_AUTO_ASSIGNMENT"
            ),
    }

    if not arguments.execute:
        atomic_write_json(
            result_path,
            planned,
        )

        print(
            json.dumps(
                planned,
                indent=2,
                sort_keys=True,
            )
        )

        print()
        print(
            "RESULT="
            "MULTISOURCE_INGESTION_"
            "PREFLIGHT_PASS"
        )

        return 0

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
                lock_handle.fileno(),
                fcntl.LOCK_EX
                | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            blocked = {
                **planned,
                "status":
                    "BLOCKED",
                "error": (
                    "Another multi-source "
                    "ingestion round is running."
                ),
            }

            atomic_write_json(
                result_path,
                blocked,
            )

            print(
                json.dumps(
                    blocked,
                    indent=2,
                    sort_keys=True,
                )
            )

            return 2

        environment = (
            os.environ.copy()
        )

        environment[
            "DATABASE_URL"
        ] = arguments.database_url

        environment[
            "AUCTION_SOURCE_REFRESH_STATE_DIR"
        ] = str(
            child_state_dir
        )

        environment.pop(
            "DOCKER_HOST",
            None,
        )

        environment.pop(
            "PGOPTIONS",
            None,
        )

        command = [
            sys.executable,
            str(
                SOURCE_RUNNER
            ),
            "--database-url",
            arguments.database_url,
            "--buyee-profile",
            arguments.buyee_profile,
        ]

        return_code = stream_command(
            command,
            environment=environment,
            log_path=child_log_path,
        )

        child_status = read_json(
            child_state_dir
            / "status.json"
        )

        if (
            return_code != 0
            or child_status.get(
                "state"
            )
            != "success"
        ):
            failed = {
                **planned,
                "status":
                    "FAILED",
                "executed":
                    True,
                "return_code":
                    return_code,
                "child_status":
                    child_status,
                "source_refresh_log":
                    str(
                        child_log_path
                    ),
            }

            atomic_write_json(
                result_path,
                failed,
            )

            print()
            print(
                json.dumps(
                    failed,
                    indent=2,
                    sort_keys=True,
                )
            )

            return (
                return_code
                or 1
            )

        after = database_state(
            database_url
        )

        pending_after = (
            pending_marketplace_identities(
                database_url
            )
        )

        tracked_after = (
            git_tracked_hash()
        )

        deltas = verify_transition(
            before,
            after,
        )

        if any(
            pending_after.values()
        ):
            raise MultiSourceIngestionError(
                "Buyee/eBay staging remains "
                "pending after refresh: "
                f"{pending_after}"
            )

        if (
            tracked_after
            != tracked_before
        ):
            raise MultiSourceIngestionError(
                "Tracked repository content "
                "changed during source refresh."
            )

        evidence = (
            stable_reference_evidence(
                database_url,
                prior_auction_keys=
                    prior_auction_keys,
                prior_gripsweat_keys=
                    prior_gripsweat_keys,
            )
        )

        if (
            len(
                evidence[
                    "auction_observations"
                ]
            )
            != deltas[
                "auction_delta"
            ]
        ):
            raise MultiSourceIngestionError(
                "New auction evidence count "
                "does not equal warehouse delta."
            )

        atomic_write_json(
            evidence_path,
            evidence,
        )

        result = {
            "schema":
                "multisource-ingestion-round/v1",
            "status":
                "COMPLETED",
            "executed":
                True,
            "source":
                "multisource",
            "sources": [
                "buyee",
                "ebay",
                "gripsweat",
            ],
            "buyee_profile":
                arguments.buyee_profile,
            "database_before":
                before,
            "database_after":
                after,
            "warehouse_before":
                before["auctions"],
            "warehouse_after":
                after["auctions"],
            "warehouse_delta":
                deltas[
                    "auction_delta"
                ],
            "new_auctions":
                deltas[
                    "auction_delta"
                ],
            "queue_before":
                before["queue"],
            "queue_after":
                after["queue"],
            "queue_delta":
                deltas[
                    "queue_delta"
                ],
            "gripsweat_before":
                before[
                    "gripsweat_sales"
                ],
            "gripsweat_after":
                after[
                    "gripsweat_sales"
                ],
            "gripsweat_delta":
                deltas[
                    "gripsweat_delta"
                ],
            "crawl_job_delta":
                deltas[
                    "crawl_job_delta"
                ],
            "raw_page_delta":
                deltas[
                    "raw_page_delta"
                ],
            "pending_before":
                pending_before,
            "pending_after":
                pending_after,
            "pending_ebay_after":
                pending_after[
                    "ebay"
                ],
            "pending_buyee_after":
                pending_after[
                    "buyee"
                ],
            "reference_coverage_before":
                coverage_before,
            "reference_coverage_after":
                reference_coverage(
                    database_url
                ),
            "pressing_reference_rows_before":
                before[
                    "pressings"
                ],
            "pressing_reference_rows_after":
                after[
                    "pressings"
                ],
            "pressing_reference_delta":
                (
                    after[
                        "pressings"
                    ]
                    - before[
                        "pressings"
                    ]
                ),
            "pressing_reference_evidence":
                str(
                    evidence_path
                ),
            "new_auction_reference_evidence":
                len(
                    evidence[
                        "auction_observations"
                    ]
                ),
            "new_gripsweat_reference_evidence":
                len(
                    evidence[
                        "gripsweat_observations"
                    ]
                ),
            "pressing_reference_policy":
                (
                    "EVIDENCE_ONLY_"
                    "NO_TITLE_ONLY_AUTO_ASSIGNMENT"
                ),
            "tracked_hash_before":
                tracked_before,
            "tracked_hash_after":
                tracked_after,
            "tracked_hash_unchanged":
                (
                    tracked_after
                    == tracked_before
                ),
            "child_status":
                child_status,
            # BUYEE_PARENT_DEGRADED_METADATA_PROPAGATION_CONTRACT_V1
            "degraded":
                bool(
                    child_status.get(
                        "degraded",
                        False,
                    )
                ),
            "buyee_source_state":
                child_status.get(
                    "buyee_source_state"
                ),
            "buyee_runtime_semantics":
                child_status.get(
                    "buyee_runtime_semantics"
                ),
            "buyee_verifier_exit_code":
                child_status.get(
                    "buyee_verifier_exit_code"
                ),
            "source_refresh_log":
                str(
                    child_log_path
                ),
            "completed_at":
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
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
        )

        print()
        print(
            "RESULT="
            "MULTISOURCE_INGESTION_ROUND_PASS"
        )

        print(
            "PRESSING_REFERENCE_POLICY="
            "EVIDENCE_ONLY_"
            "NO_TITLE_ONLY_AUTO_ASSIGNMENT"
        )

        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except MultiSourceIngestionError as error:
        print(
            f"\nERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(
            1
        ) from error
