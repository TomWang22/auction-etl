#!/usr/bin/env python3
"""Browser acceptance for the new-ingestion-round Streamlit control."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (
    ROOT / "scripts/launch_latest_refresh_job.py"
)


def parse_args() -> argparse.Namespace:
    """Parse acceptance-test arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--database-url",
        default=(
            "postgresql://auction:auction@"
            "127.0.0.1:5544/auction_warehouse"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8502,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
    )

    return parser.parse_args()


def normalize_database_url(
    value: str,
) -> str:
    """Normalize a SQLAlchemy URL for psycopg."""
    return value.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )


def database_state(
    database_url: str,
) -> str:
    """Capture mutable ingestion-related live counts."""
    with psycopg.connect(
        normalize_database_url(
            database_url
        )
    ) as connection:
        row = connection.execute(
            """
            SELECT concat_ws(
                '|',
                (
                    SELECT COUNT(*)
                    FROM warehouse.auction
                ),
                (
                    SELECT COUNT(*)
                    FROM warehouse.auction_pressing_assignment
                ),
                (
                    SELECT COUNT(*)
                    FROM system.listing_completeness_snapshot
                ),
                (
                    SELECT COUNT(*)
                    FROM system.listing_completeness_timeline
                ),
                (
                    SELECT COUNT(*)
                    FROM system.new_auction_assignment_queue
                ),
                (
                    SELECT COUNT(*)
                    FROM system.crawl_job
                ),
                (
                    SELECT COUNT(*)
                    FROM raw.page
                ),
                (
                    SELECT COUNT(*)
                    FROM staging.listing
                )
            )
            """
        ).fetchone()

    if row is None:
        raise RuntimeError(
            "Database-state query returned no row."
        )

    return str(row[0])


def tracked_hash() -> str:
    """Hash the current tracked repository diff."""
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


def wait_for_health(
    port: int,
    timeout: float = 60.0,
) -> None:
    """Wait for Streamlit health."""
    deadline = (
        time.monotonic()
        + timeout
    )

    url = (
        f"http://127.0.0.1:{port}/"
        "_stcore/health"
    )

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                url,
                timeout=2,
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)

    raise RuntimeError(
        "Streamlit did not become healthy."
    )


def wait_for_path(
    path: Path,
    timeout: float = 15.0,
) -> None:
    """Wait until a path exists."""
    deadline = (
        time.monotonic()
        + timeout
    )

    while time.monotonic() < deadline:
        if path.exists():
            return

        time.sleep(0.1)

    raise RuntimeError(
        f"Timed out waiting for {path}"
    )


def read_status(
    path: Path,
) -> dict[str, Any]:
    """Read launcher test status."""
    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
    ):
        return {}

    return (
        payload
        if isinstance(payload, dict)
        else {}
    )


def wait_for_state(
    path: Path,
    state: str,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Wait for a launcher status state."""
    deadline = (
        time.monotonic()
        + timeout
    )

    while time.monotonic() < deadline:
        payload = read_status(
            path
        )

        if payload.get(
            "state"
        ) == state:
            return payload

        time.sleep(0.1)

    raise RuntimeError(
        f"Timed out waiting for status={state}: "
        f"{read_status(path)}"
    )


def write_fake_tools(
    directory: Path,
) -> tuple[Path, Path, Path]:
    """Create fake child tools for zero-write UI testing."""
    runner = (
        directory / "fake_runner.py"
    )
    inspector = (
        directory / "fake_inspector.py"
    )
    audit = (
        directory / "fake_audit.py"
    )

    runner.write_text(
        '''\
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--database-url")
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--execute", action="store_true")
args, _ = parser.parse_known_args()

marker = Path(
    os.environ["AUCTION_REFRESH_TEST_MARKER"]
)

with marker.open(
    "a",
    encoding="utf-8",
) as handle:
    handle.write("runner-invoked\\n")

time.sleep(8)

args.output_dir.mkdir(
    parents=True,
    exist_ok=True,
)

result = {
    "status": "COMPLETED",
    "executed": True,
    "source": "facerecords-ui-test",
    "crawl_job_id": None,
    "raw_pages": 0,
    "staging_rows": 0,
    "unique_identities": 0,
    "new_auctions": 0,
    "existing_identities": 0,
    "warehouse_delta": 0,
    "queue_delta": 0,
    "pending_ebay_after": 0,
    "remaining_fresh": 0,
    "wrapper_report": None,
}

(
    args.output_dir
    / "result.json"
).write_text(
    json.dumps(
        result,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)

print(
    json.dumps(
        result,
        indent=2,
    )
)
''',
        encoding="utf-8",
    )

    inspector.write_text(
        '''\
from __future__ import annotations

import argparse
import json
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--database-url")
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()

args.output_dir.mkdir(
    parents=True,
    exist_ok=True,
)

summary = {
    "marketplaces": {
        "buyee": {
            "newly_ingested": 0,
        },
        "ebay": {
            "newly_ingested": 0,
        },
    },
    "missing_from_warehouse": 0,
}

(
    args.output_dir
    / "summary.json"
).write_text(
    json.dumps(
        summary,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
''',
        encoding="utf-8",
    )

    audit.write_text(
        '''\
raise SystemExit(0)
''',
        encoding="utf-8",
    )

    return (
        runner,
        inspector,
        audit,
    )


def main() -> int:
    """Test the actual Streamlit ingestion-round control safely."""
    args = parse_args()

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%d-%H%M%S"
    )

    evidence_dir = (
        args.evidence_dir
        if args.evidence_dir is not None
        else (
            ROOT
            / "logs"
            / "ingestion-round-ui-test"
            / timestamp
        )
    )

    if not evidence_dir.is_absolute():
        evidence_dir = (
            ROOT / evidence_dir
        )

    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    state_dir = (
        evidence_dir / "state"
    )
    fake_dir = (
        evidence_dir / "fake-tools"
    )
    fake_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    marker = (
        evidence_dir
        / "runner-marker.txt"
    )
    status_path = (
        state_dir
        / "status.json"
    )
    streamlit_log = (
        evidence_dir
        / "streamlit.log"
    )
    screenshot_path = (
        evidence_dir
        / "new-ingestion-round.png"
    )

    runner, inspector, audit = (
        write_fake_tools(
            fake_dir
        )
    )

    before_database = database_state(
        args.database_url
    )
    before_tracked = tracked_hash()

    cron = subprocess.run(
        [
            "crontab",
            "-l",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    expected_cron = (
        "15 6 * * * /bin/bash "
        "/Users/tom/auction-etl/scripts/run_reports.sh"
    )

    if expected_cron not in cron.stdout:
        raise RuntimeError(
            "The expected 06:15 run_reports.sh cron "
            "entry is not installed."
        )

    reports_source = (
        ROOT
        / "scripts"
        / "run_reports.sh"
    ).read_text(
        encoding="utf-8",
    )

    if (
        "launch_latest_refresh_job.py"
        not in reports_source
        or "--trigger cron"
        not in reports_source
    ):
        raise RuntimeError(
            "run_reports.sh is not wired to the "
            "shared cron launcher."
        )

    environment = os.environ.copy()
    environment[
        "DATABASE_URL"
    ] = args.database_url
    environment[
        "AUCTION_REFRESH_STATE_DIR"
    ] = str(
        state_dir
    )
    environment[
        "AUCTION_REFRESH_RUNNER_PATH"
    ] = str(
        runner
    )
    environment[
        "AUCTION_REFRESH_INSPECTOR_PATH"
    ] = str(
        inspector
    )
    environment[
        "AUCTION_REFRESH_AUDIT_PATH"
    ] = str(
        audit
    )
    environment[
        "AUCTION_REFRESH_TEST_MARKER"
    ] = str(
        marker
    )

    # Streamlit itself can only read from PostgreSQL during this test.
    environment[
        "PGOPTIONS"
    ] = (
        "-c default_transaction_read_only=on "
        "-c statement_timeout=15000"
    )

    environment.pop(
        "DOCKER_HOST",
        None,
    )

    with streamlit_log.open(
        "w",
        encoding="utf-8",
    ) as log_handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app/collector_review.py",
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(
                    args.port
                ),
                "--server.headless",
                "true",
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

        try:
            wait_for_health(
                args.port
            )

            with sync_playwright() as playwright:
                browser = (
                    playwright.chromium.launch(
                        headless=True
                    )
                )

                page = browser.new_page(
                    viewport={
                        "width": 1600,
                        "height": 1200,
                    }
                )

                page.goto(
                    (
                        "http://127.0.0.1:"
                        f"{args.port}/"
                        "Latest_Auction_Refresh"
                    ),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )

                page.get_by_text(
                    "Latest Auction Refresh",
                    exact=True,
                ).first.wait_for(
                    timeout=60_000
                )

                page.get_by_text(
                    "Refresh controls",
                    exact=True,
                ).click()

                confirmation = (
                    page.get_by_label(
                        "Type RUN to enable a new ingestion round"
                    )
                )

                run_button = (
                    page.get_by_role(
                        "button",
                        name="Run new ingestion round",
                    )
                )

                run_button.wait_for()

                if not run_button.is_disabled():
                    raise RuntimeError(
                        "Run button was enabled before RUN confirmation."
                    )

                confirmation.fill(
                    "RUN"
                )

                # Streamlit commits text_input changes on Enter/blur.
                confirmation.press(
                    "Enter"
                )

                enable_deadline = (
                    time.monotonic()
                    + 15.0
                )

                while (
                    time.monotonic()
                    < enable_deadline
                ):
                    if run_button.is_enabled():
                        break

                    page.wait_for_timeout(
                        100
                    )
                else:
                    page.screenshot(
                        path=str(
                            evidence_dir
                            / "run-button-still-disabled.png"
                        ),
                        full_page=True,
                    )

                    raise RuntimeError(
                        "Run button stayed disabled after "
                        "RUN was committed and the Streamlit "
                        "rerun was given 15 seconds."
                    )

                run_button.click()

                wait_for_path(
                    marker
                )

                running = wait_for_state(
                    status_path,
                    "running",
                )

                if running.get(
                    "trigger"
                ) != "ui":
                    raise RuntimeError(
                        f"Unexpected UI trigger: {running}"
                    )

                second_launch = subprocess.run(
                    [
                        sys.executable,
                        str(
                            LAUNCHER
                        ),
                        "--database-url",
                        args.database_url,
                        "--trigger",
                        "ui",
                    ],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )

                if second_launch.returncode != 2:
                    raise RuntimeError(
                        "Concurrent launcher was not blocked:\n"
                        + second_launch.stdout
                    )

                marker_lines = (
                    marker.read_text(
                        encoding="utf-8"
                    )
                    .splitlines()
                )

                if marker_lines != [
                    "runner-invoked"
                ]:
                    raise RuntimeError(
                        "The fake runner was invoked more "
                        "than once while the lock was held."
                    )

                success = wait_for_state(
                    status_path,
                    "success",
                    timeout=30.0,
                )

                if success.get(
                    "trigger"
                ) != "ui":
                    raise RuntimeError(
                        f"Final trigger is not UI: {success}"
                    )

                page.get_by_role(
                    "button",
                    name="Reload job status",
                ).click()

                page.get_by_text(
                    "Ingestion round completed.",
                    exact=True,
                ).wait_for(
                    timeout=20_000
                )

                exceptions = page.locator(
                    "[data-testid='stException']"
                )

                if exceptions.count() > 0:
                    raise RuntimeError(
                        "Streamlit rendered an exception."
                    )

                page.screenshot(
                    path=str(
                        screenshot_path
                    ),
                    full_page=True,
                )

                browser.close()
        finally:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGTERM,
                )
            except ProcessLookupError:
                pass

            try:
                process.wait(
                    timeout=20
                )
            except subprocess.TimeoutExpired:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )
                process.wait(
                    timeout=10
                )

    after_database = database_state(
        args.database_url
    )
    after_tracked = tracked_hash()

    if after_database != before_database:
        raise RuntimeError(
            "UI acceptance changed PostgreSQL state:\n"
            f"before={before_database}\n"
            f"after ={after_database}"
        )

    if after_tracked != before_tracked:
        raise RuntimeError(
            "UI acceptance changed tracked repository content."
        )

    print()
    print(
        "================ RESULT ================"
    )
    print(
        "RESULT=NEW_INGESTION_ROUND_UI_PASS"
    )
    print(
        f"Database before: {before_database}"
    )
    print(
        f"Database after:  {after_database}"
    )
    print(
        f"Tracked before:  {before_tracked}"
    )
    print(
        f"Tracked after:   {after_tracked}"
    )
    print(
        f"Evidence:        {evidence_dir}"
    )
    print()
    print(
        "✓ Existing 06:15 cron entry is present."
    )
    print(
        "✓ Cron routes through the shared launcher."
    )
    print(
        "✓ Run button requires exact RUN confirmation."
    )
    print(
        "✓ Run new ingestion round button was clicked."
    )
    print(
        "✓ The real launcher was invoked."
    )
    print(
        "✓ The injected fake runner was invoked exactly once."
    )
    print(
        "✓ Concurrent launch was rejected by the lock."
    )
    print(
        "✓ Launcher reached SUCCESS."
    )
    print(
        "✓ No real crawler was executed."
    )
    print(
        "✓ No PostgreSQL state changed."
    )
    print(
        "✓ No tracked repository content changed."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
