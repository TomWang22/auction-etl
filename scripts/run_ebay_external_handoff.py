"""Run the supported headed eBay structured-acquisition handoff safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

DEFAULT_CONFIG = ROOT / "config" / "ebay_sources.json"
DEFAULT_STORAGE_STATE = (
    Path.home()
    / ".auction-etl"
    / "private"
    / "ebay-storage-state.json"
)
DEFAULT_ARTIFACT_DIR = (
    ROOT
    / "logs"
    / "ebay-structured"
)
DEFAULT_EXPECTED_DATABASE_NAME = "auction_warehouse"
DEFAULT_EXPECTED_DATABASE_USER = "auction"

ACQUIRE_SCRIPT = (
    ROOT
    / "scripts"
    / "acquire_ebay_structured.py"
)
IMPORT_SCRIPT = (
    ROOT
    / "scripts"
    / "import_ebay_structured.py"
)
REFRESH_SCRIPT = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

ARTIFACT_SCHEMA = (
    "auction-etl/ebay-structured-acquisition/v1"
)
BROWSER_SKIP_SENTINEL = (
    "pending external eBay raw page(s); browser crawl skipped."
)
EBAY_BROWSER_COMMAND_MARKER = (
    "scripts/crawl_ebay_sources.py"
)
EBAY_BROWSER_PROFILE_MARKER = (
    "profile=ebay-public"
)


class OperatorError(RuntimeError):
    """Raised when the operator workflow cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class EbaySource:
    """Validated external-only eBay source configuration."""

    name: str
    url: str
    wait_seconds: float


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    """Small database identity and eBay-state snapshot."""

    database_name: str
    database_user: str
    ebay_rows: int
    raw_page_parsed: bool | None = None


def sha256_file(
    path: Path,
) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def require_file(
    path: Path,
    *,
    label: str,
) -> Path:
    """Resolve and require one non-empty file."""

    resolved = (
        path
        .expanduser()
        .resolve()
    )

    if not resolved.is_file():
        raise OperatorError(
            f"{label} does not exist: {resolved}"
        )

    if resolved.stat().st_size < 1:
        raise OperatorError(
            f"{label} is empty: {resolved}"
        )

    return resolved


def config_entries(
    payload: object,
) -> list[dict[str, Any]]:
    """Normalize supported eBay config shapes."""

    if isinstance(
        payload,
        list,
    ):
        return [
            entry
            for entry in payload
            if isinstance(
                entry,
                dict,
            )
        ]

    if isinstance(
        payload,
        dict,
    ):
        values = payload.get(
            "sources",
            payload,
        )

        if isinstance(
            values,
            list,
        ):
            return [
                entry
                for entry in values
                if isinstance(
                    entry,
                    dict,
                )
            ]

        if isinstance(
            values,
            dict,
        ):
            entries: list[
                dict[str, Any]
            ] = []

            for key, value in values.items():
                if not isinstance(
                    value,
                    dict,
                ):
                    continue

                normalized = dict(
                    value
                )

                normalized.setdefault(
                    "name",
                    str(key),
                )

                entries.append(
                    normalized
                )

            return entries

    return []


def load_external_source(
    config_path: Path,
) -> EbaySource:
    """Load exactly one enabled external-only production eBay source."""

    resolved = require_file(
        config_path,
        label="eBay source config",
    )

    payload = json.loads(
        resolved.read_text(
            encoding="utf-8",
        )
    )

    enabled = [
        entry
        for entry in config_entries(
            payload
        )
        if entry.get(
            "enabled",
            True,
        )
        is not False
    ]

    if len(enabled) != 1:
        raise OperatorError(
            "Expected exactly one enabled eBay source."
        )

    source = enabled[0]

    name = str(
        source.get(
            "name",
            "",
        )
    ).strip()

    if not name:
        raise OperatorError(
            "Enabled eBay source has no name."
        )

    mode = str(
        source.get(
            "acquisition_mode",
            "browser",
        )
    ).strip().casefold()

    if mode != "external":
        raise OperatorError(
            "Refusing eBay operator handoff because "
            f"acquisition_mode is {mode!r}, not 'external'."
        )

    profile = str(
        source.get(
            "profile",
            "",
        )
    ).strip()

    if profile != "ebay-public":
        raise OperatorError(
            "Expected eBay profile 'ebay-public'."
        )

    seller = str(
        source.get(
            "seller",
            "",
        )
    ).strip()

    if seller != "all-sellers":
        raise OperatorError(
            "Expected public all-sellers eBay scope."
        )

    url = str(
        source.get(
            "url",
            "",
        )
    ).strip()

    parts = urlsplit(
        url
    )

    host = (
        parts.hostname
        or ""
    ).casefold()

    if (
        parts.scheme.casefold()
        != "https"
    ):
        raise OperatorError(
            "Configured eBay source URL must use HTTPS."
        )

    if not (
        host == "ebay.com"
        or host.endswith(
            ".ebay.com"
        )
    ):
        raise OperatorError(
            "Configured eBay source URL is not an ebay.com URL."
        )

    query = parse_qs(
        parts.query
    )

    if query.get(
        "LH_Sold"
    ) != ["1"]:
        raise OperatorError(
            "Configured eBay source lacks LH_Sold=1."
        )

    if query.get(
        "LH_Complete"
    ) != ["1"]:
        raise OperatorError(
            "Configured eBay source lacks LH_Complete=1."
        )

    if query.get(
        "_sop"
    ) != ["13"]:
        raise OperatorError(
            "Configured eBay source is not newest-first."
        )

    if "_ssn" in query:
        raise OperatorError(
            "Configured public eBay source is unexpectedly seller-scoped."
        )

    wait_seconds = float(
        source.get(
            "wait_seconds",
            4.0,
        )
    )

    if wait_seconds < 0:
        raise OperatorError(
            "eBay source wait_seconds cannot be negative."
        )

    return EbaySource(
        name=name,
        url=url,
        wait_seconds=wait_seconds,
    )


def default_artifact_path() -> Path:
    """Return a timestamped structured-acquisition artifact path."""

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    return (
        DEFAULT_ARTIFACT_DIR
        / (
            "ebay-structured-headed-"
            f"{timestamp}.json"
        )
    )


def build_acquisition_command(
    *,
    source: EbaySource,
    storage_state: Path,
    artifact: Path,
    timeout_seconds: float,
    settle_seconds: float,
) -> list[str]:
    """Build the headed structured-acquisition command."""

    if timeout_seconds <= 0:
        raise OperatorError(
            "Acquisition timeout must be greater than zero."
        )

    if settle_seconds < 0:
        raise OperatorError(
            "Acquisition settle time cannot be negative."
        )

    command = [
        sys.executable,
        str(
            ACQUIRE_SCRIPT
        ),
        "--url",
        source.url,
        "--source-name",
        source.name,
        "--storage-state",
        str(
            storage_state
        ),
        "--output",
        str(
            artifact
        ),
        "--timeout-seconds",
        str(
            timeout_seconds
        ),
        "--settle-seconds",
        str(
            settle_seconds
        ),
    ]

    if "--headless" in command:
        raise OperatorError(
            "Operator acquisition unexpectedly became headless."
        )

    return command


def build_import_command(
    *,
    artifact: Path,
    source_name: str,
    apply: bool,
) -> list[str]:
    """Build one structured importer command."""

    command = [
        sys.executable,
        str(
            IMPORT_SCRIPT
        ),
        str(
            artifact
        ),
        "--source-name",
        source_name,
    ]

    if apply:
        command.append(
            "--apply"
        )

    return command


def build_refresh_command(
    *,
    database_url: str,
    expected_database_name: str,
    expected_database_user: str,
    raw_page_id: int,
) -> list[str]:
    """Build the exact raw-page refresh command."""

    if raw_page_id < 1:
        raise OperatorError(
            "Structured raw-page ID must be positive."
        )

    return [
        sys.executable,
        str(
            REFRESH_SCRIPT
        ),
        "--database-url",
        database_url,
        "--expected-database-name",
        expected_database_name,
        "--expected-database-user",
        expected_database_user,
        "--ebay-structured-raw-page-id",
        str(
            raw_page_id
        ),
    ]


def run_child(
    *,
    label: str,
    command: list[str],
    environment: Mapping[str, str],
) -> str:
    """Execute one repository command and return merged output."""

    print()
    print(
        f"================ {label} ================"
    )
    print()

    result = subprocess.run(
        command,
        cwd=ROOT,
        env=dict(
            environment
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    output = (
        result.stdout
        or ""
    )

    if output:
        print(
            output,
            end=(
                ""
                if output.endswith(
                    "\n"
                )
                else "\n"
            ),
        )

    if result.returncode != 0:
        raise OperatorError(
            f"{label} failed with exit code "
            f"{result.returncode}."
        )

    return output


def validate_artifact(
    *,
    artifact: Path,
    source: EbaySource,
) -> tuple[int, str]:
    """Validate non-secret acquisition artifact metadata."""

    resolved = require_file(
        artifact,
        label="Structured eBay artifact",
    )

    payload = json.loads(
        resolved.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise OperatorError(
            "Structured eBay artifact must be a JSON object."
        )

    if payload.get(
        "schema"
    ) != ARTIFACT_SCHEMA:
        raise OperatorError(
            "Structured eBay artifact schema is unexpected."
        )

    if payload.get(
        "source_name"
    ) != source.name:
        raise OperatorError(
            "Structured eBay artifact source name changed."
        )

    if payload.get(
        "source_url"
    ) != source.url:
        raise OperatorError(
            "Structured eBay artifact source URL changed."
        )

    listings = payload.get(
        "listings"
    )

    listing_count = payload.get(
        "listing_count"
    )

    if not isinstance(
        listings,
        list,
    ):
        raise OperatorError(
            "Structured eBay artifact listings are invalid."
        )

    if not isinstance(
        listing_count,
        int,
    ):
        raise OperatorError(
            "Structured eBay artifact listing_count is invalid."
        )

    if (
        listing_count < 1
        or listing_count
        != len(
            listings
        )
    ):
        raise OperatorError(
            "Structured eBay artifact contains an invalid listing count."
        )

    page = payload.get(
        "page"
    )

    if not isinstance(
        page,
        dict,
    ):
        raise OperatorError(
            "Structured eBay artifact page metadata is invalid."
        )

    if page.get(
        "http_status"
    ) != 200:
        raise OperatorError(
            "Structured eBay acquisition did not produce HTTP 200."
        )

    final_url = str(
        page.get(
            "final_url",
            "",
        )
    )

    final_parts = urlsplit(
        final_url
    )

    final_host = (
        final_parts.hostname
        or ""
    ).casefold()

    if not (
        final_host == "ebay.com"
        or final_host.endswith(
            ".ebay.com"
        )
    ):
        raise OperatorError(
            "Structured acquisition did not end on eBay."
        )

    if (
        "signin"
        in final_host
        or "/signin"
        in final_parts.path.casefold()
    ):
        raise OperatorError(
            "Structured acquisition ended at eBay sign-in."
        )

    return (
        listing_count,
        sha256_file(
            resolved
        ),
    )


def require_sentinel(
    output: str,
    sentinel: str,
) -> None:
    """Require one child-process success sentinel."""

    if sentinel not in output:
        raise OperatorError(
            f"Required sentinel is missing: {sentinel}"
        )


def parse_import_plan_summary(
    output: str,
) -> tuple[str, int]:
    """Extract deterministic importer plan identity."""

    sha_match = re.search(
        r"^✓ SHA-256\s*:\s*([0-9a-f]{64})\s*$",
        output,
        flags=re.MULTILINE,
    )

    listing_match = re.search(
        r"^✓ Listings\s*:\s*(\d+)\s*$",
        output,
        flags=re.MULTILINE,
    )

    if sha_match is None:
        raise OperatorError(
            "Importer did not emit a deterministic plan SHA-256."
        )

    if listing_match is None:
        raise OperatorError(
            "Importer did not emit a listing count."
        )

    return (
        sha_match.group(
            1
        ),
        int(
            listing_match.group(
                1
            )
        ),
    )


def parse_raw_page_id(
    output: str,
) -> int:
    """Extract the exact raw.page ID emitted by the importer."""

    matches = re.findall(
        r"^✓ Raw Page\s*:\s*(\d+)\s*$",
        output,
        flags=re.MULTILINE,
    )

    if len(
        matches
    ) != 1:
        raise OperatorError(
            "Importer did not emit exactly one raw-page ID."
        )

    raw_page_id = int(
        matches[0]
    )

    if raw_page_id < 1:
        raise OperatorError(
            "Importer emitted an invalid raw-page ID."
        )

    return raw_page_id


def parse_idempotent_reuse(
    output: str,
) -> bool:
    """Return whether importer reused an existing raw page."""

    match = re.search(
        r"^IDEMPOTENT_REUSE=(true|false)\s*$",
        output,
        flags=re.MULTILINE,
    )

    if match is None:
        raise OperatorError(
            "Importer did not emit IDEMPOTENT_REUSE."
        )

    return (
        match.group(
            1
        )
        == "true"
    )


def validate_write_request(
    *,
    apply: bool,
    confirm_write: bool,
    database_url: str | None,
) -> None:
    """Fail closed unless database writes are explicitly armed."""

    if not apply:
        if confirm_write:
            raise OperatorError(
                "--confirm-write requires --apply."
            )

        return

    if not confirm_write:
        raise OperatorError(
            "--apply requires --confirm-write."
        )

    if not (
        database_url
        and database_url.strip()
    ):
        raise OperatorError(
            "--apply requires an explicit database URL "
            "via --database-url or DATABASE_URL."
        )


def normalize_database_url(
    database_url: str,
) -> str:
    """Normalize SQLAlchemy-style PostgreSQL URLs for Psycopg."""

    from scripts.run_latest_auction_refresh import (
        normalize_psycopg_url,
    )

    return normalize_psycopg_url(
        database_url
    )


def database_snapshot(
    *,
    database_url: str,
    expected_database_name: str,
    expected_database_user: str,
    raw_page_id: int | None = None,
) -> DatabaseSnapshot:
    """Verify database identity and return eBay state."""

    import psycopg
    from psycopg.rows import dict_row

    psql_url = normalize_database_url(
        database_url
    )

    with psycopg.connect(
        psql_url,
        row_factory=dict_row,
    ) as connection:
        identity = connection.execute(
            """
            SELECT
                current_database() AS database_name,
                current_user AS database_user
            """
        ).fetchone()

        if identity is None:
            raise OperatorError(
                "Database identity query returned no row."
            )

        database_name = str(
            identity[
                "database_name"
            ]
        )

        database_user = str(
            identity[
                "database_user"
            ]
        )

        if (
            database_name
            != expected_database_name
        ):
            raise OperatorError(
                "Database name mismatch: "
                f"expected {expected_database_name!r}, "
                f"found {database_name!r}."
            )

        if (
            database_user
            != expected_database_user
        ):
            raise OperatorError(
                "Database user mismatch: "
                f"expected {expected_database_user!r}, "
                f"found {database_user!r}."
            )

        warehouse = connection.execute(
            """
            SELECT COUNT(*) AS ebay_rows
            FROM warehouse.auction
            WHERE marketplace = 'ebay'
            """
        ).fetchone()

        if warehouse is None:
            raise OperatorError(
                "Warehouse eBay count query returned no row."
            )

        parsed: bool | None = None

        if raw_page_id is not None:
            raw_page = connection.execute(
                """
                SELECT
                    source,
                    url,
                    parsed_at
                FROM raw.page
                WHERE id = %s
                """,
                (
                    raw_page_id,
                ),
            ).fetchone()

            if raw_page is None:
                raise OperatorError(
                    "Exact structured raw page does not exist."
                )

            if (
                str(
                    raw_page[
                        "source"
                    ]
                )
                != "ebay"
            ):
                raise OperatorError(
                    "Exact structured raw page is not eBay."
                )

            if not str(
                raw_page[
                    "url"
                ]
            ).startswith(
                "collector://ebay/"
            ):
                raise OperatorError(
                    "Exact raw page is not importer-owned."
                )

            parsed = (
                raw_page[
                    "parsed_at"
                ]
                is not None
            )

    return DatabaseSnapshot(
        database_name=database_name,
        database_user=database_user,
        ebay_rows=int(
            warehouse[
                "ebay_rows"
            ]
        ),
        raw_page_parsed=parsed,
    )


def backup_database(
    *,
    database_url: str,
    expected_database_name: str,
) -> Path:
    """Create the repository-standard verified PostgreSQL backup."""

    from scripts.run_latest_auction_refresh import (
        create_backup,
    )

    logger = logging.getLogger(
        "ebay-external-handoff-backup"
    )

    logger.setLevel(
        logging.INFO
    )

    logger.handlers.clear()

    logger.addHandler(
        logging.StreamHandler(
            sys.stdout
        )
    )

    return create_backup(
        psql_url=normalize_database_url(
            database_url
        ),
        backup_dir=(
            ROOT
            / "backups"
            / "private"
            / "postgres"
        ),
        label=(
            expected_database_name
            + "-before-ebay-external-handoff"
        ),
        logger=logger,
    )


def resolve_status_file() -> Path:
    """Return the latest-refresh status path."""

    raw_root = os.environ.get(
        "AUCTION_SOURCE_REFRESH_STATE_DIR",
        str(
            ROOT
            / "logs"
            / "latest-refresh"
        ),
    )

    state_root = Path(
        raw_root
    ).expanduser()

    if not state_root.is_absolute():
        state_root = (
            ROOT
            / state_root
        )

    return (
        state_root.resolve()
        / "status.json"
    )


def verify_no_ebay_browser_fallback(
    output: str,
) -> None:
    """Require exact-ID handoff evidence and reject eBay browser execution."""

    if (
        BROWSER_SKIP_SENTINEL
        not in output
    ):
        raise OperatorError(
            "Refresh did not emit explicit eBay browser-skip evidence."
        )

    forbidden = (
        EBAY_BROWSER_COMMAND_MARKER,
        EBAY_BROWSER_PROFILE_MARKER,
    )

    for marker in forbidden:
        if marker in output:
            raise OperatorError(
                "eBay browser fallback evidence appeared "
                f"during exact-ID refresh: {marker}"
            )


def verify_refresh_status(
    status_file: Path,
) -> int:
    """Validate completed refresh status and return final eBay row count."""

    resolved = require_file(
        status_file,
        label="Refresh status file",
    )

    payload = json.loads(
        resolved.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise OperatorError(
            "Refresh status must be a JSON object."
        )

    if payload.get(
        "state"
    ) != "success":
        raise OperatorError(
            "Latest refresh did not finish successfully."
        )

    if payload.get(
        "phase"
    ) != "completed":
        raise OperatorError(
            "Latest refresh did not reach completed phase."
        )

    marketplace_states = payload.get(
        "marketplace_states"
    )

    if not isinstance(
        marketplace_states,
        dict,
    ):
        raise OperatorError(
            "Refresh marketplace_states is invalid."
        )

    if marketplace_states.get(
        "ebay"
    ) != "done":
        raise OperatorError(
            "eBay refresh state is not done."
        )

    if payload.get(
        "ebay_runtime_semantics"
    ) != "EBAY_SOURCE_AVAILABLE":
        raise OperatorError(
            "eBay runtime semantics are not available."
        )

    final_state = payload.get(
        "final_state"
    )

    if not isinstance(
        final_state,
        dict,
    ):
        raise OperatorError(
            "Refresh final_state is invalid."
        )

    ebay_rows = final_state.get(
        "ebay_rows"
    )

    if not isinstance(
        ebay_rows,
        int,
    ):
        raise OperatorError(
            "Final eBay warehouse row count is unavailable."
        )

    return ebay_rows


def parse_arguments() -> argparse.Namespace:
    """Parse operator arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire eBay in a headed browser, validate the structured "
            "artifact, and optionally apply it through the exact raw-page "
            "handoff with browser fallback prohibited."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )

    parser.add_argument(
        "--storage-state",
        type=Path,
        default=DEFAULT_STORAGE_STATE,
    )

    parser.add_argument(
        "--artifact",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45.0,
    )

    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=None,
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL"
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

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply the validated artifact and run the exact-ID refresh."
        ),
    )

    parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Required together with --apply to authorize database writes."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Run the fail-closed operator workflow."""

    arguments = parse_arguments()

    try:
        validate_write_request(
            apply=arguments.apply,
            confirm_write=arguments.confirm_write,
            database_url=arguments.database_url,
        )

        source = load_external_source(
            arguments.config
        )

        storage_state = require_file(
            arguments.storage_state,
            label="eBay storage state",
        )

        artifact = (
            arguments.artifact
            if arguments.artifact
            is not None
            else default_artifact_path()
        ).expanduser().resolve()

        artifact.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if artifact.exists():
            raise OperatorError(
                "Refusing to overwrite existing artifact: "
                f"{artifact}"
            )

        settle_seconds = (
            source.wait_seconds
            if arguments.settle_seconds
            is None
            else arguments.settle_seconds
        )

        state_sha_before = sha256_file(
            storage_state
        )

        environment = os.environ.copy()

        acquisition_output = run_child(
            label="HEADED STRUCTURED EBAY ACQUISITION",
            command=build_acquisition_command(
                source=source,
                storage_state=storage_state,
                artifact=artifact,
                timeout_seconds=arguments.timeout_seconds,
                settle_seconds=settle_seconds,
            ),
            environment=environment,
        )

        require_sentinel(
            acquisition_output,
            "EBAY_STRUCTURED_ACQUISITION=PASS",
        )

        require_sentinel(
            acquisition_output,
            "DATABASE_REQUEST_EXECUTED=false",
        )

        listing_count, artifact_sha256 = validate_artifact(
            artifact=artifact,
            source=source,
        )

        state_sha_after = sha256_file(
            storage_state
        )

        if (
            state_sha_after
            != state_sha_before
        ):
            raise OperatorError(
                "eBay storage-state file changed during acquisition."
            )

        dry_run_output = run_child(
            label="STRUCTURED IMPORTER DRY RUN",
            command=build_import_command(
                artifact=artifact,
                source_name=source.name,
                apply=False,
            ),
            environment=environment,
        )

        require_sentinel(
            dry_run_output,
            "MODE=DRY_RUN",
        )

        require_sentinel(
            dry_run_output,
            "DATABASE_SESSION_OPENED=false",
        )

        require_sentinel(
            dry_run_output,
            "DATABASE_WRITE_EXECUTED=false",
        )

        require_sentinel(
            dry_run_output,
            "STRUCTURED_EBAY_IMPORT_DRY_RUN=PASS",
        )

        plan_sha256, plan_listing_count = (
            parse_import_plan_summary(
                dry_run_output
            )
        )

        if (
            plan_listing_count
            != listing_count
        ):
            raise OperatorError(
                "Importer plan listing count differs "
                "from acquired artifact."
            )

        print()
        print(
            "================ VALIDATED HANDOFF ================"
        )
        print()
        print(
            f"EBAY_SOURCE_NAME={source.name}"
        )
        print(
            "EBAY_ACQUISITION_MODE=external"
        )
        print(
            "EBAY_STRUCTURED_ACQUISITION_HEADLESS=false"
        )
        print(
            f"STRUCTURED_ARTIFACT={artifact}"
        )
        print(
            f"STRUCTURED_ARTIFACT_SHA256={artifact_sha256}"
        )
        print(
            f"STRUCTURED_ARTIFACT_LISTING_COUNT={listing_count}"
        )
        print(
            f"IMPORT_PLAN_SHA256={plan_sha256}"
        )
        print(
            "EBAY_STORAGE_STATE_MODIFIED=false"
        )

        if not arguments.apply:
            print(
                "DATABASE_WRITE=false"
            )
            print(
                "REAL_REFRESH_RUN=false"
            )
            print(
                "READY_FOR_STRUCTURED_EBAY_APPLY=true"
            )
            print(
                "EBAY_EXTERNAL_HANDOFF_DRY_RUN=PASS"
            )
            return 0

        database_url = str(
            arguments.database_url
        )

        expected_database_name = str(
            arguments.expected_database_name
        ).strip()

        expected_database_user = str(
            arguments.expected_database_user
        ).strip()

        if not expected_database_name:
            raise OperatorError(
                "Expected database name cannot be empty."
            )

        if not expected_database_user:
            raise OperatorError(
                "Expected database user cannot be empty."
            )

        pre_snapshot = database_snapshot(
            database_url=database_url,
            expected_database_name=expected_database_name,
            expected_database_user=expected_database_user,
        )

        print()
        print(
            "DATABASE_TARGET_IDENTITY=PASS"
        )
        print(
            f"DATABASE_NAME={pre_snapshot.database_name}"
        )
        print(
            f"DATABASE_USER={pre_snapshot.database_user}"
        )
        print(
            f"BASELINE_EBAY_WAREHOUSE_ROWS={pre_snapshot.ebay_rows}"
        )
        print(
            "DATABASE_PASSWORD_PRINTED=false"
        )

        backup = backup_database(
            database_url=database_url,
            expected_database_name=expected_database_name,
        )

        environment[
            "DATABASE_URL"
        ] = database_url

        apply_output = run_child(
            label="APPLY EXACT STRUCTURED ARTIFACT",
            command=build_import_command(
                artifact=artifact,
                source_name=source.name,
                apply=True,
            ),
            environment=environment,
        )

        require_sentinel(
            apply_output,
            "STRUCTURED_EBAY_RAWPAGE_IMPORT=PASS",
        )

        raw_page_id = parse_raw_page_id(
            apply_output
        )

        idempotent_reuse = (
            parse_idempotent_reuse(
                apply_output
            )
        )

        database_snapshot(
            database_url=database_url,
            expected_database_name=expected_database_name,
            expected_database_user=expected_database_user,
            raw_page_id=raw_page_id,
        )

        refresh_output = run_child(
            label="EXACT-ID REAL REFRESH",
            command=build_refresh_command(
                database_url=database_url,
                expected_database_name=expected_database_name,
                expected_database_user=expected_database_user,
                raw_page_id=raw_page_id,
            ),
            environment=environment,
        )

        verify_no_ebay_browser_fallback(
            refresh_output
        )

        status_file = resolve_status_file()

        status_ebay_rows = verify_refresh_status(
            status_file
        )

        final_snapshot = database_snapshot(
            database_url=database_url,
            expected_database_name=expected_database_name,
            expected_database_user=expected_database_user,
            raw_page_id=raw_page_id,
        )

        if (
            final_snapshot.raw_page_parsed
            is not True
        ):
            raise OperatorError(
                "Exact structured eBay raw page was not marked parsed."
            )

        if (
            final_snapshot.ebay_rows
            < pre_snapshot.ebay_rows
        ):
            raise OperatorError(
                "eBay warehouse row count decreased."
            )

        if (
            final_snapshot.ebay_rows
            != status_ebay_rows
        ):
            raise OperatorError(
                "Refresh status eBay row count differs from database."
            )

        final_state_sha = sha256_file(
            storage_state
        )

        if (
            final_state_sha
            != state_sha_before
        ):
            raise OperatorError(
                "eBay storage-state file changed during workflow."
            )

        if (
            sha256_file(
                artifact
            )
            != artifact_sha256
        ):
            raise OperatorError(
                "Structured artifact changed during workflow."
            )

        print()
        print(
            "================ RESULT ================"
        )
        print()
        print(
            "EBAY_EXTERNAL_HANDOFF_OPERATOR_GATE=PASS"
        )
        print(
            f"STRUCTURED_ARTIFACT={artifact}"
        )
        print(
            f"STRUCTURED_ARTIFACT_SHA256={artifact_sha256}"
        )
        print(
            f"STRUCTURED_ARTIFACT_LISTING_COUNT={listing_count}"
        )
        print(
            f"IMPORT_PLAN_SHA256={plan_sha256}"
        )
        print(
            f"STRUCTURED_EBAY_RAW_PAGE_ID={raw_page_id}"
        )
        print(
            "IDEMPOTENT_REUSE="
            + str(
                idempotent_reuse
            ).lower()
        )
        print(
            f"PREWRITE_BACKUP={backup}"
        )
        print(
            "DATABASE_WRITE=true"
        )
        print(
            "REAL_REFRESH_RUN=true"
        )
        print(
            "EXACT_STRUCTURED_RAW_PAGE_PARSED=true"
        )
        print(
            "EBAY_BROWSER_FALLBACK_PROHIBITED=true"
        )
        print(
            "EBAY_BROWSER_ACQUISITION_EXECUTED=false"
        )
        print(
            f"FINAL_EBAY_WAREHOUSE_ROWS={final_snapshot.ebay_rows}"
        )
        print(
            "EBAY_STORAGE_STATE_MODIFIED=false"
        )
        print(
            "STRUCTURED_ARTIFACT_IMMUTABILITY=PASS"
        )

        return 0

    except (
        OperatorError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "EBAY_EXTERNAL_HANDOFF_OPERATOR_GATE=FAIL",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
