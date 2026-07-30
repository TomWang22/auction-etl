"""Launch the permanent refresh runner without blocking Streamlit."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "logs/latest-refresh/status.json"
LOCK_PATH = ROOT / "logs/latest-refresh/refresh.lock"
RUNNER_PATH = ROOT / "scripts/run_latest_auction_refresh.py"
INSPECTOR_PATH = ROOT / "scripts/inspect_recent_ingestion.py"
AUDIT_PATH = ROOT / "scripts/update_ingestion_audit.py"


def parse_args() -> argparse.Namespace:
    """Parse launcher arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Launch the latest-auction refresh and "
            "publish its resulting status."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            (
                "postgresql+psycopg://auction:auction@"
                "127.0.0.1:5544/auction_warehouse"
            ),
        ),
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
    )

    return parser.parse_args()


def write_status(**values: object) -> None:
    """Atomically publish one UI status payload."""
    STATUS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        **values,
    }

    temporary = STATUS_PATH.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(STATUS_PATH)


def latest_directory(parent: Path) -> Path | None:
    """Return the newest immediate child directory."""
    if not parent.is_dir():
        return None

    directories = [
        path
        for path in parent.iterdir()
        if path.is_dir()
    ]

    if not directories:
        return None

    return max(
        directories,
        key=lambda path: path.stat().st_mtime,
    )


def run_command(
    command: list[str],
    *,
    environment: dict[str, str],
    log_handle,
) -> int:
    """Execute one logged non-interactive command."""
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    return int(process.returncode)


def main() -> int:
    """Run inspection or the complete refresh pipeline."""
    args = parse_args()

    LOCK_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d-%H%M%S")

    run_dir = (
        ROOT
        / "logs/latest-refresh"
        / f"ui-{timestamp}"
    )
    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = run_dir / "refresh.log"
    report_dir = (
        ROOT
        / "reports/recent-ingestion"
        / f"ui-{timestamp}"
    )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        args.database_url
    )
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

    with LOCK_PATH.open("w") as lock_handle:
        try:
            fcntl.flock(
                lock_handle,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            write_status(
                state="blocked",
                phase="lock",
                message=(
                    "Another latest-auction refresh "
                    "is already running."
                ),
                log_path=str(log_path),
            )
            return 2

        write_status(
            state="running",
            phase=(
                "inspection"
                if args.inspect_only
                else "source-refresh"
            ),
            message=(
                "Recent-ingestion inspection is running."
                if args.inspect_only
                else "The source refresh is running."
            ),
            log_path=str(log_path),
            report_dir=str(report_dir),
            started_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with log_path.open(
            "w",
            encoding="utf-8",
        ) as log_handle:
            if not args.inspect_only:
                if not RUNNER_PATH.is_file():
                    write_status(
                        state="failed",
                        phase="source-refresh",
                        message=(
                            "The permanent refresh runner "
                            "is missing."
                        ),
                        log_path=str(log_path),
                    )
                    return 1

                refresh_status = run_command(
                    [
                        sys.executable,
                        str(RUNNER_PATH),
                    ],
                    environment=environment,
                    log_handle=log_handle,
                )

                if refresh_status != 0:
                    write_status(
                        state="failed",
                        phase="source-refresh",
                        message=(
                            "The source refresh stopped. "
                            "Review its log before retrying."
                        ),
                        error=(
                            "Refresh exited with status "
                            f"{refresh_status}."
                        ),
                        log_path=str(log_path),
                    )
                    return refresh_status

                export_dir = latest_directory(
                    ROOT / "exports/new-only"
                )

                if export_dir is not None:
                    audit_status = run_command(
                        [
                            sys.executable,
                            str(AUDIT_PATH),
                            "--database-url",
                            args.database_url,
                            "--seed-new-only",
                            str(export_dir),
                            "--run-id",
                            export_dir.name,
                        ],
                        environment=environment,
                        log_handle=log_handle,
                    )

                    if audit_status != 0:
                        write_status(
                            state="failed",
                            phase="audit-update",
                            message=(
                                "The refresh completed, but "
                                "the first-seen audit failed."
                            ),
                            log_path=str(log_path),
                            export_dir=str(export_dir),
                        )
                        return audit_status

            inspect_status = run_command(
                [
                    sys.executable,
                    str(INSPECTOR_PATH),
                    "--database-url",
                    args.database_url,
                    "--output-dir",
                    str(report_dir),
                ],
                environment=environment,
                log_handle=log_handle,
            )

            if inspect_status != 0:
                write_status(
                    state="failed",
                    phase="inspection",
                    message=(
                        "The recent-ingestion inspection failed."
                    ),
                    log_path=str(log_path),
                    report_dir=str(report_dir),
                )
                return inspect_status

        summary_path = report_dir / "summary.json"
        summary = {}

        if summary_path.is_file():
            summary = json.loads(
                summary_path.read_text(
                    encoding="utf-8"
                )
            )

        write_status(
            state="success",
            phase="completed",
            message=(
                "Inspection completed."
                if args.inspect_only
                else "All source refresh steps completed."
            ),
            log_path=str(log_path),
            report_dir=str(report_dir),
            summary=summary,
            finished_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
