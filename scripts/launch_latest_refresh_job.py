"""Launch the canonical ingestion round without blocking Streamlit."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


ROOT = Path(__file__).resolve().parents[1]


def configured_path(
    environment_name: str,
    default: Path,
) -> Path:
    """Resolve an optional environment-configured path."""
    raw_value = os.environ.get(
        environment_name
    )

    if not raw_value:
        return default

    path = Path(
        raw_value
    ).expanduser()

    if not path.is_absolute():
        path = ROOT / path

    return path


STATE_DIR = configured_path(
    "AUCTION_REFRESH_STATE_DIR",
    ROOT / "logs/latest-refresh",
)

STATUS_PATH = STATE_DIR / "status.json"
LOCK_PATH = STATE_DIR / "refresh.lock"

RUNNER_PATH = configured_path(
    "AUCTION_REFRESH_RUNNER_PATH",
    ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py",
)

INSPECTOR_PATH = configured_path(
    "AUCTION_REFRESH_INSPECTOR_PATH",
    ROOT / "scripts/inspect_recent_ingestion.py",
)

AUDIT_PATH = configured_path(
    "AUCTION_REFRESH_AUDIT_PATH",
    ROOT / "scripts/update_ingestion_audit.py",
)


def parse_args() -> argparse.Namespace:
    """Parse launcher arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Launch or inspect the canonical auction ingestion round."
        )
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            (
                "postgresql://auction:auction@"
                "127.0.0.1:5544/auction_warehouse"
            ),
        ),
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
    )
    parser.add_argument(
        "--trigger",
        choices=(
            "ui",
            "cron",
            "manual",
        ),
        default="manual",
    )

    return parser.parse_args()


def write_status(
    **values: object,
) -> None:
    """Atomically publish one launcher status."""
    STATUS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "updated_at":
            datetime.now(
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
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        STATUS_PATH
    )


def read_json(
    path: Path,
) -> dict[str, Any]:
    """Read one JSON object if present."""
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

    return (
        payload
        if isinstance(
            payload,
            dict,
        )
        else {}
    )


def latest_directory(
    parent: Path,
) -> Path | None:
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
        key=lambda path:
            path.stat().st_mtime,
    )


def run_command(
    command: list[str],
    *,
    environment: dict[str, str],
    log_handle: IO[str],
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

    return int(
        process.returncode
    )


def main() -> int:
    """Run inspection or one complete ingestion round."""
    args = parse_args()

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%d-%H%M%S"
    )

    run_name = (
        f"{args.trigger}-"
        f"{timestamp}-"
        f"{os.getpid()}"
    )

    run_dir = (
        STATE_DIR
        / run_name
    )
    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = (
        run_dir
        / "refresh.log"
    )

    report_dir = (
        ROOT
        / "reports"
        / "recent-ingestion"
        / run_name
    )

    ingestion_dir = (
        run_dir
        / "ingestion-round"
    )

    environment = os.environ.copy()
    environment[
        "DATABASE_URL"
    ] = args.database_url
    environment.pop(
        "DOCKER_HOST",
        None,
    )
    environment.pop(
        "PGOPTIONS",
        None,
    )

    started_epoch = time.time()

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
                json.dumps(
                    {
                        "state":
                            "blocked",
                        "trigger":
                            args.trigger,
                        "message": (
                            "Another ingestion round "
                            "is already running."
                        ),
                    },
                    indent=2,
                )
            )

            # Do not overwrite the active job's status.
            return 2

        write_status(
            state="running",
            phase=(
                "inspection"
                if args.inspect_only
                else "ingestion-round"
            ),
            trigger=args.trigger,
            message=(
                "Recent-ingestion inspection is running."
                if args.inspect_only
                else "A new ingestion round is running."
            ),
            log_path=str(
                log_path
            ),
            report_dir=str(
                report_dir
            ),
            run_dir=str(
                run_dir
            ),
            started_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        ingestion_result: dict[
            str,
            Any,
        ] = {}

        with log_path.open(
            "w",
            encoding="utf-8",
        ) as log_handle:
            if not args.inspect_only:
                if not RUNNER_PATH.is_file():
                    write_status(
                        state="failed",
                        phase="ingestion-round",
                        trigger=args.trigger,
                        message=(
                            "The canonical ingestion "
                            "runner is missing."
                        ),
                        log_path=str(
                            log_path
                        ),
                    )
                    return 1

                refresh_status = run_command(
                    [
                        sys.executable,
                        str(RUNNER_PATH),
                        "--database-url",
                        args.database_url,
                        "--output-dir",
                        str(
                            ingestion_dir
                        ),
                        "--execute",
                    ],
                    environment=environment,
                    log_handle=log_handle,
                )

                if refresh_status != 0:
                    write_status(
                        state="failed",
                        phase="ingestion-round",
                        trigger=args.trigger,
                        message=(
                            "The ingestion round stopped. "
                            "Review its log before retrying."
                        ),
                        error=(
                            "Runner exited with status "
                            f"{refresh_status}."
                        ),
                        log_path=str(
                            log_path
                        ),
                        run_dir=str(
                            run_dir
                        ),
                    )

                    return refresh_status

                ingestion_result = read_json(
                    ingestion_dir
                    / "result.json"
                )

                if not ingestion_result:
                    write_status(
                        state="failed",
                        phase="ingestion-round",
                        trigger=args.trigger,
                        message=(
                            "The ingestion runner exited "
                            "without a result artifact."
                        ),
                        log_path=str(
                            log_path
                        ),
                    )
                    return 1

                export_dir = latest_directory(
                    ROOT
                    / "exports"
                    / "new-only"
                )

                if (
                    export_dir is not None
                    and export_dir.stat().st_mtime
                    >= started_epoch
                    and AUDIT_PATH.is_file()
                ):
                    audit_status = run_command(
                        [
                            sys.executable,
                            str(
                                AUDIT_PATH
                            ),
                            "--database-url",
                            args.database_url,
                            "--seed-new-only",
                            str(
                                export_dir
                            ),
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
                            trigger=args.trigger,
                            message=(
                                "The ingestion completed, "
                                "but its audit update failed."
                            ),
                            log_path=str(
                                log_path
                            ),
                        )
                        return audit_status

            if not INSPECTOR_PATH.is_file():
                write_status(
                    state="failed",
                    phase="inspection",
                    trigger=args.trigger,
                    message=(
                        "The recent-ingestion inspector "
                        "is missing."
                    ),
                    log_path=str(
                        log_path
                    ),
                )
                return 1

            inspect_status = run_command(
                [
                    sys.executable,
                    str(
                        INSPECTOR_PATH
                    ),
                    "--database-url",
                    args.database_url,
                    "--output-dir",
                    str(
                        report_dir
                    ),
                ],
                environment=environment,
                log_handle=log_handle,
            )

            if inspect_status != 0:
                write_status(
                    state="failed",
                    phase="inspection",
                    trigger=args.trigger,
                    message=(
                        "Recent-ingestion inspection failed."
                    ),
                    log_path=str(
                        log_path
                    ),
                    report_dir=str(
                        report_dir
                    ),
                )
                return inspect_status

        summary = read_json(
            report_dir
            / "summary.json"
        )

        wrapper_report = (
            ingestion_result.get(
                "wrapper_report"
            )
            if isinstance(
                ingestion_result,
                dict,
            )
            else None
        )

        guarded_reports = (
            [wrapper_report]
            if isinstance(
                wrapper_report,
                dict,
            )
            else []
        )

        write_status(
            state="success",
            phase="completed",
            trigger=args.trigger,
            message=(
                "Inspection completed."
                if args.inspect_only
                else "Ingestion round completed."
            ),
            log_path=str(
                log_path
            ),
            report_dir=str(
                report_dir
            ),
            run_dir=str(
                run_dir
            ),
            summary=summary,
            ingestion_result=ingestion_result,
            guarded_ingest_reports=
                guarded_reports,
            finished_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
