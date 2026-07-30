"""Hard-test safe synchronization, reporting, and the Streamlit UI."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psycopg
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    """Parse hard-test arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--database-url",
        required=True,
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8502,
    )

    return parser.parse_args()


def normalize_database_url(
    database_url: str,
) -> str:
    """Normalize a SQLAlchemy PostgreSQL URL."""
    return database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )


def database_state(
    database_url: str,
) -> str:
    """Return the protected warehouse state."""
    with psycopg.connect(
        normalize_database_url(database_url)
    ) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*)::text
                || '|'
                || COUNT(
                    DISTINCT (
                        marketplace,
                        listing_id
                    )
                )::text
                || '|'
                || COUNT(*) FILTER (
                    WHERE marketplace = 'buyee'
                )::text
                || '|'
                || COUNT(*) FILTER (
                    WHERE marketplace = 'ebay'
                )::text
                || '|'
                || (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector
                )::text
                || '|'
                || (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector_effective
                )::text
                || '|'
                || (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector_review
                )::text
            FROM warehouse.auction
            """
        ).fetchone()

    if row is None:
        raise RuntimeError(
            "Database state query returned no row."
        )

    return str(row[0])


def run(
    command: list[str],
    *,
    environment: dict[str, str],
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command and validate its status."""
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    print(result.stdout)

    if expect_success and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {command}"
        )

    if not expect_success and result.returncode == 0:
        raise RuntimeError(
            "Command unexpectedly succeeded: "
            f"{command}"
        )

    return result


def wait_for_health(
    port: int,
    timeout: float = 60.0,
) -> None:
    """Wait for the disposable Streamlit server."""
    deadline = time.monotonic() + timeout
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
            time.sleep(1)

    raise RuntimeError(
        "Disposable Streamlit server did not become healthy."
    )


def main() -> int:
    """Run all non-production-write hard tests."""
    args = parse_args()

    live_url = normalize_database_url(
        args.database_url
    )
    initial_live_state = database_state(
        live_url
    )

    if initial_live_state != (
        "848|848|138|710|848|848|848"
    ):
        raise RuntimeError(
            "Unexpected live baseline: "
            f"{initial_live_state}"
        )

    test_name = (
        "auction_reporting_test_"
        + time.strftime("%Y%m%d_%H%M%S")
    )
    maintenance_url = (
        "postgresql://auction:auction@"
        "127.0.0.1:5544/postgres"
    )
    test_url = (
        "postgresql://auction:auction@"
        f"127.0.0.1:5544/{test_name}"
    )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = test_url
    environment.pop(
        "DOCKER_HOST",
        None,
    )
    environment.pop(
        "DOCKER_CONTEXT",
        None,
    )
    environment.pop(
        "PGOPTIONS",
        None,
    )

    with tempfile.TemporaryDirectory(
        prefix="auction-reporting-hard-test-"
    ) as temporary_directory:
        temporary = Path(
            temporary_directory
        )
        dump_path = temporary / "live.dump"
        report_dir = temporary / "report"
        streamlit_log = (
            temporary / "streamlit.log"
        )
        screenshot_path = (
            temporary / "latest-refresh.png"
        )

        run(
            [
                "pg_dump",
                "--dbname",
                live_url,
                "--format=custom",
                "--file",
                str(dump_path),
            ],
            environment=environment,
        )

        run(
            [
                "createdb",
                "--maintenance-db",
                maintenance_url,
                test_name,
            ],
            environment=environment,
        )

        try:
            run(
                [
                    "pg_restore",
                    "--dbname",
                    test_url,
                    "--no-owner",
                    "--no-privileges",
                    str(dump_path),
                ],
                environment=environment,
            )

            restored_state = database_state(
                test_url
            )

            if restored_state != initial_live_state:
                raise RuntimeError(
                    "Disposable restore does not match live state."
                )

            print()
            print("Safe no-prune synchronization")
            print("=============================")

            run(
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
                environment=environment,
            )

            if database_state(
                test_url
            ) != initial_live_state:
                raise RuntimeError(
                    "No-prune synchronization changed identity counts."
                )

            print()
            print("Global prune rejection")
            print("======================")

            run(
                [
                    sys.executable,
                    "-m",
                    "auction_etl.cli.main",
                    "sync",
                    "warehouse",
                    "--prune",
                ],
                environment=environment,
                expect_success=False,
            )

            print()
            print("Incomplete scoped-prune rejection")
            print("=================================")

            run(
                [
                    sys.executable,
                    "-m",
                    "auction_etl.cli.main",
                    "sync",
                    "warehouse",
                    "--marketplace",
                    "buyee",
                    "--prune",
                ],
                environment=environment,
                expect_success=False,
            )

            print()
            print("Recent-ingestion report validation")
            print("==================================")

            run(
                [
                    sys.executable,
                    "scripts/inspect_recent_ingestion.py",
                    "--database-url",
                    test_url,
                    "--baseline",
                    str(args.baseline),
                    "--output-dir",
                    str(report_dir),
                ],
                environment=environment,
            )

            summary = json.loads(
                (
                    report_dir
                    / "summary.json"
                ).read_text(
                    encoding="utf-8"
                )
            )

            buyee = summary[
                "marketplaces"
            ]["buyee"]
            ebay = summary[
                "marketplaces"
            ]["ebay"]

            expected = {
                "buyee_new": 61,
                "buyee_refreshed": 28,
                "buyee_pending": 0,
                "ebay_new": 0,
                "ebay_refreshed": 59,
                "ebay_pending": 0,
                "missing": 0,
            }

            actual = {
                "buyee_new": buyee[
                    "newly_ingested"
                ],
                "buyee_refreshed": buyee[
                    "refreshed_existing"
                ],
                "buyee_pending": buyee[
                    "pending"
                ],
                "ebay_new": ebay[
                    "newly_ingested"
                ],
                "ebay_refreshed": ebay[
                    "refreshed_existing"
                ],
                "ebay_pending": ebay[
                    "pending"
                ],
                "missing": summary[
                    "missing_from_warehouse"
                ],
            }

            if actual != expected:
                raise RuntimeError(
                    "Incorrect identity classification:\n"
                    f"Expected: {expected}\n"
                    f"Actual  : {actual}"
                )

            print("✓ 61 new Buyee identities")
            print("✓ 28 refreshed Buyee identities")
            print("✓ 59 refreshed eBay identities")
            print("✓ No pending or deleted identities")

            print()
            print("Disposable Streamlit UI test")
            print("============================")

            streamlit_environment = (
                environment.copy()
            )
            streamlit_environment[
                "DATABASE_URL"
            ] = test_url

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
                        str(args.port),
                        "--server.headless",
                        "true",
                    ],
                    cwd=ROOT,
                    env=streamlit_environment,
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
                        ).wait_for()

                        page.get_by_text(
                            "Browse & export",
                            exact=True,
                        ).click()

                        page.get_by_text(
                            "Auction data browser",
                            exact=True,
                        ).wait_for()

                        page.get_by_text(
                            "Recent additions",
                            exact=True,
                        ).wait_for()

                        page.get_by_text(
                            "Report fields",
                            exact=True,
                        ).wait_for()

                        page.get_by_role(
                            "button",
                            name="Load report",
                        ).click()

                        page.get_by_text(
                            "Formatted export",
                            exact=True,
                        ).wait_for(
                            timeout=60_000
                        )

                        page.get_by_role(
                            "button",
                            name=(
                                "Download formatted CSV"
                            ),
                        ).wait_for()

                        page.get_by_text(
                            "Run history",
                            exact=True,
                        ).click()

                        page.get_by_text(
                            "Refresh and report history",
                            exact=True,
                        ).wait_for()

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

                    process.wait(
                        timeout=20
                    )

            if database_state(
                live_url
            ) != initial_live_state:
                raise RuntimeError(
                    "The live database changed during hard testing."
                )

            print()
            print("Hard-test suite passed")
            print("======================")
            print("✓ Disposable database restore passed.")
            print("✓ Safe no-prune synchronization passed.")
            print("✓ Global pruning was rejected.")
            print("✓ Incomplete scoped pruning was rejected.")
            print("✓ Recent-ingestion classification passed.")
            print("✓ Date/report UI rendered successfully.")
            print("✓ Formatted-download control rendered.")
            print("✓ Streamlit produced no exception.")
            print("✓ Live database remained unchanged.")
        finally:
            run(
                [
                    "dropdb",
                    "--maintenance-db",
                    maintenance_url,
                    "--if-exists",
                    test_name,
                ],
                environment=environment,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
