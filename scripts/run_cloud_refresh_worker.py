#!/usr/bin/env python3
"""Run the persistent cloud marketplace refresh worker."""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from auction_etl.services.refresh_jobs import (  # noqa: E402
    RefreshLeaseLost,
    build_refresh_engine,
    claim_next_refresh_job,
    heartbeat_refresh_job,
    mark_refresh_job_completed,
    mark_refresh_job_failed,
    release_refresh_job,
    requeue_expired_refresh_jobs,
    update_marketplace_state,
)

CANONICAL_RUNNER = (
    ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py"
)

SOURCE_STATE_PATTERN = re.compile(
    r"^AUCTION_SOURCE_STATE "
    r"source=(?P<source>\S+) "
    r"state=(?P<state>\S+)"
)

COUNTER_PATTERN = re.compile(
    r"\b("
    r"discovered|"
    r"already_known|"
    r"new_count|"
    r"detail_scraped|"
    r"detail_skipped|"
    r"discovery_pages|"
    r"consecutive_known_at_stop"
    r")\s*[:=]\s*(\d+)\b",
    re.IGNORECASE,
)

BUYEE_NEW_PATTERN = re.compile(
    r"\bNew detail candidates\s*:\s*(\d+)\b",
    re.IGNORECASE,
)

SOURCE_NAMES = {
    "buyee":
        "buyee",
    "ebay":
        "ebay",
    "gripsweat":
        "gripsweat",
}

SOURCE_STATE_MAP = {
    "waiting":
        "waiting",
    "running":
        "running",
    "done":
        "done",
    "failed":
        "failed",
    "unavailable":
        "skipped",
    "skipped":
        "skipped",
}

_STOP_EVENT = threading.Event()


class WorkerError(RuntimeError):
    """Raised when the persistent refresh worker cannot continue."""


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse persistent worker arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Claim durable refresh jobs from PostgreSQL "
            "and run the canonical marketplace ingestion round."
        )
    )

    parser.add_argument(
        "--database-url",
        default=(
            os.environ.get(
                "DATABASE_URL_WORKER"
            )
            or os.environ.get(
                "DATABASE_URL"
            )
            or ""
        ),
    )

    parser.add_argument(
        "--worker-id",
        default=os.environ.get(
            "AUCTION_WORKER_ID",
            "",
        ),
    )

    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(
            os.environ.get(
                "AUCTION_WORKER_POLL_SECONDS",
                "3",
            )
        ),
    )

    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(
            os.environ.get(
                "AUCTION_WORKER_LEASE_SECONDS",
                "90",
            )
        ),
    )

    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(
            os.environ.get(
                "AUCTION_WORKER_HEARTBEAT_SECONDS",
                "20",
            )
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
        "--buyee-profile-dir",
        type=Path,
        default=(
            Path(
                os.environ[
                    "AUCTION_BUYEE_PROFILE_DIR"
                ]
            )
            if os.environ.get(
                "AUCTION_BUYEE_PROFILE_DIR"
            )
            else None
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            Path(
                os.environ[
                    "AUCTION_WORKER_OUTPUT_DIR"
                ]
            )
            if os.environ.get(
                "AUCTION_WORKER_OUTPUT_DIR"
            )
            else None
        ),
    )

    return parser.parse_args(
        argv
    )


def worker_id(
    configured: str,
) -> str:
    """Return a stable-enough worker identity for one service process."""
    explicit = configured.strip()

    if explicit:
        return explicit

    railway_service = os.environ.get(
        "RAILWAY_SERVICE_ID",
        "",
    ).strip()

    railway_deployment = os.environ.get(
        "RAILWAY_DEPLOYMENT_ID",
        "",
    ).strip()

    identity_parts = [
        value
        for value in (
            railway_service,
            railway_deployment,
        )
        if value
    ]

    if identity_parts:
        return ":".join(
            identity_parts
        )

    return (
        f"{socket.gethostname()}:"
        f"{os.getpid()}:"
        f"{uuid.uuid4().hex[:8]}"
    )


def validate_configuration(
    args: argparse.Namespace,
) -> None:
    """Reject unsafe or unusable worker configuration."""
    if not str(
        args.database_url
    ).strip():
        raise WorkerError(
            "DATABASE_URL_WORKER or DATABASE_URL is required."
        )

    if not CANONICAL_RUNNER.is_file():
        raise WorkerError(
            f"Canonical runner is missing: {CANONICAL_RUNNER}"
        )

    if args.poll_seconds < 0.25:
        raise WorkerError(
            "poll-seconds must be at least 0.25."
        )

    if args.lease_seconds < 30:
        raise WorkerError(
            "lease-seconds must be at least 30."
        )

    if args.heartbeat_seconds <= 0:
        raise WorkerError(
            "heartbeat-seconds must be positive."
        )

    if (
        args.heartbeat_seconds
        >= args.lease_seconds / 2
    ):
        raise WorkerError(
            "heartbeat-seconds must be less than half "
            "of lease-seconds."
        )

    if (
        "/" in args.buyee_profile
        or args.buyee_profile in {
            "",
            ".",
            "..",
        }
    ):
        raise WorkerError(
            "buyee-profile must be a simple profile name."
        )


def prepare_persistent_profile(
    *,
    profile_name: str,
    persistent_directory: Path | None,
) -> None:
    """Bind the canonical profile path to persistent worker storage."""
    if persistent_directory is None:
        return

    target = persistent_directory.expanduser()

    if not target.is_absolute():
        raise WorkerError(
            "AUCTION_BUYEE_PROFILE_DIR must be absolute."
        )

    target.mkdir(
        parents=True,
        exist_ok=True,
    )

    profile_root = (
        ROOT
        / "profiles"
    )

    profile_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    canonical = (
        profile_root
        / profile_name
    )

    if canonical.is_symlink():
        current_target = canonical.resolve(
            strict=False
        )

        if (
            current_target
            != target.resolve(
                strict=False
            )
        ):
            raise WorkerError(
                "Existing Buyee profile symlink points to "
                f"{current_target}, expected {target}."
            )

        return

    if canonical.exists():
        raise WorkerError(
            "Refusing to replace the existing non-symlink "
            f"Buyee profile path: {canonical}"
        )

    canonical.symlink_to(
        target,
        target_is_directory=True,
    )


def prepare_output_directory(
    path: Path | None,
) -> Path | None:
    """Create the optional durable worker evidence/output directory."""
    if path is None:
        return None

    target = path.expanduser()

    if not target.is_absolute():
        raise WorkerError(
            "AUCTION_WORKER_OUTPUT_DIR must be absolute."
        )

    target.mkdir(
        parents=True,
        exist_ok=True,
    )

    return target


def normalize_source(
    value: str,
) -> str | None:
    """Normalize one canonical runner marketplace name."""
    return SOURCE_NAMES.get(
        value.strip().casefold()
    )


def parse_source_state(
    line: str,
) -> tuple[str, str] | None:
    """Parse one explicit canonical marketplace state protocol line."""
    match = SOURCE_STATE_PATTERN.search(
        line.strip()
    )

    if match is None:
        return None

    marketplace = normalize_source(
        match.group(
            "source"
        )
    )

    if marketplace is None:
        return None

    state = SOURCE_STATE_MAP.get(
        match.group(
            "state"
        ).strip().casefold()
    )

    if state is None:
        return None

    return (
        marketplace,
        state,
    )


def parse_progress_counters(
    line: str,
) -> dict[str, int]:
    """Parse known incremental marketplace counters from one output line."""
    result = {
        match.group(1).casefold():
            int(
                match.group(2)
            )
        for match in COUNTER_PATTERN.finditer(
            line
        )
    }

    buyee_match = (
        BUYEE_NEW_PATTERN.search(
            line
        )
    )

    if buyee_match:
        result[
            "new_count"
        ] = int(
            buyee_match.group(
                1
            )
        )

    return result


def _signal_handler(
    _signum: int,
    _frame: Any,
) -> None:
    """Request a graceful worker shutdown."""
    _STOP_EVENT.set()


def install_signal_handlers() -> None:
    """Install graceful shutdown handlers for persistent platforms."""
    signal.signal(
        signal.SIGTERM,
        _signal_handler,
    )

    signal.signal(
        signal.SIGINT,
        _signal_handler,
    )


def terminate_child(
    child: subprocess.Popen[str],
    *,
    grace_seconds: float = 20.0,
) -> None:
    """Terminate the canonical runner and its process group."""
    if child.poll() is not None:
        return

    try:
        os.killpg(
            child.pid,
            signal.SIGTERM,
        )
    except (
        ProcessLookupError,
        PermissionError,
        OSError,
    ):
        try:
            child.terminate()
        except OSError:
            return

    deadline = (
        time.monotonic()
        + grace_seconds
    )

    while (
        child.poll() is None
        and time.monotonic()
        < deadline
    ):
        time.sleep(
            0.2
        )

    if child.poll() is not None:
        return

    try:
        os.killpg(
            child.pid,
            signal.SIGKILL,
        )
    except (
        ProcessLookupError,
        PermissionError,
        OSError,
    ):
        try:
            child.kill()
        except OSError:
            pass


class Heartbeat:
    """Maintain one durable lease while a marketplace process is running."""

    def __init__(
        self,
        *,
        engine,
        job_id: str,
        worker_id_value: str,
        lease_seconds: int,
        heartbeat_seconds: float,
    ) -> None:
        self._engine = engine
        self._job_id = job_id
        self._worker_id = (
            worker_id_value
        )
        self._lease_seconds = (
            lease_seconds
        )
        self._heartbeat_seconds = (
            heartbeat_seconds
        )
        self._stop = threading.Event()
        self._lease_lost = (
            threading.Event()
        )
        self._error: Exception | None = (
            None
        )
        self._thread = threading.Thread(
            target=self._run,
            name=(
                "auction-refresh-heartbeat"
            ),
            daemon=True,
        )

    @property
    def lease_lost(
        self,
    ) -> bool:
        """Return whether durable ownership was lost."""
        return self._lease_lost.is_set()

    @property
    def error(
        self,
    ) -> Exception | None:
        """Return the heartbeat failure, if any."""
        return self._error

    def start(
        self,
    ) -> None:
        """Start the heartbeat loop."""
        self._thread.start()

    def stop(
        self,
    ) -> None:
        """Stop and join the heartbeat loop."""
        self._stop.set()
        self._thread.join(
            timeout=(
                self._heartbeat_seconds
                + 5
            )
        )

    def _run(
        self,
    ) -> None:
        while not self._stop.wait(
            self._heartbeat_seconds
        ):
            try:
                heartbeat_refresh_job(
                    self._engine,
                    job_id=(
                        self._job_id
                    ),
                    worker_id=(
                        self._worker_id
                    ),
                    lease_seconds=(
                        self._lease_seconds
                    ),
                )
            except Exception as exc:
                self._error = exc
                self._lease_lost.set()
                return


class DurableProgress:
    """Persist canonical runner output into durable marketplace rows."""

    def __init__(
        self,
        *,
        engine,
        job_id: str,
        worker_id_value: str,
    ) -> None:
        self._engine = engine
        self._job_id = job_id
        self._worker_id = (
            worker_id_value
        )
        self.current_marketplace: (
            str | None
        ) = None
        self._states = {
            marketplace:
                "waiting"
            for marketplace
            in SOURCE_NAMES.values()
        }
        self._counters: dict[
            str,
            dict[str, int],
        ] = {
            marketplace: {}
            for marketplace
            in SOURCE_NAMES.values()
        }

    def consume(
        self,
        line: str,
    ) -> None:
        """Persist one canonical runner output line."""
        source_state = (
            parse_source_state(
                line
            )
        )

        if source_state is not None:
            marketplace, state = (
                source_state
            )

            self.current_marketplace = (
                marketplace
            )

            self._states[
                marketplace
            ] = state

            update_marketplace_state(
                self._engine,
                job_id=self._job_id,
                worker_id=(
                    self._worker_id
                ),
                marketplace=marketplace,
                state=state,
                message=(
                    "Marketplace "
                    f"{state}."
                ),
                **self._counters[
                    marketplace
                ],
            )

            return

        counters = (
            parse_progress_counters(
                line
            )
        )

        if (
            not counters
            or self.current_marketplace
            is None
        ):
            return

        marketplace = (
            self.current_marketplace
        )

        self._counters[
            marketplace
        ].update(
            counters
        )

        current_state = self._states[
            marketplace
        ]

        if current_state not in {
            "running",
            "done",
            "skipped",
        }:
            current_state = "running"

        update_marketplace_state(
            self._engine,
            job_id=self._job_id,
            worker_id=(
                self._worker_id
            ),
            marketplace=marketplace,
            state=current_state,
            **self._counters[
                marketplace
            ],
        )


def runner_command(
    *,
    database_url: str,
    buyee_profile: str,
    output_directory: Path | None,
) -> list[str]:
    """Build the canonical marketplace execution command."""
    command = [
        sys.executable,
        str(
            CANONICAL_RUNNER
        ),
        "--database-url",
        database_url,
        "--buyee-profile",
        buyee_profile,
        "--execute",
    ]

    if output_directory is not None:
        run_directory = (
            output_directory
            / time.strftime(
                "%Y%m%d-%H%M%S"
            )
        )

        run_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        command.extend(
            [
                "--output-dir",
                str(
                    run_directory
                ),
            ]
        )

    return command


def execute_claimed_job(
    *,
    engine,
    job: dict[str, Any],
    worker_id_value: str,
    database_url: str,
    buyee_profile: str,
    output_directory: Path | None,
    lease_seconds: int,
    heartbeat_seconds: float,
) -> None:
    """Execute one claimed durable refresh job."""
    job_id = str(
        job["id"]
    )

    progress = DurableProgress(
        engine=engine,
        job_id=job_id,
        worker_id_value=(
            worker_id_value
        ),
    )

    command = runner_command(
        database_url=database_url,
        buyee_profile=buyee_profile,
        output_directory=(
            output_directory
        ),
    )

    environment = os.environ.copy()
    environment[
        "DATABASE_URL"
    ] = database_url

    child = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    heartbeat = Heartbeat(
        engine=engine,
        job_id=job_id,
        worker_id_value=(
            worker_id_value
        ),
        lease_seconds=(
            lease_seconds
        ),
        heartbeat_seconds=(
            heartbeat_seconds
        ),
    )

    heartbeat.start()

    tail: deque[str] = deque(
        maxlen=80
    )

    try:
        assert child.stdout is not None

        for raw_line in child.stdout:
            line = raw_line.rstrip(
                "\n"
            )

            print(
                line,
                flush=True,
            )

            tail.append(
                line
            )

            if _STOP_EVENT.is_set():
                terminate_child(
                    child
                )
                break

            if heartbeat.lease_lost:
                terminate_child(
                    child
                )
                break

            try:
                progress.consume(
                    line
                )
            except RefreshLeaseLost:
                terminate_child(
                    child
                )
                raise

        return_code = child.wait()

        if heartbeat.lease_lost:
            error = heartbeat.error

            if isinstance(
                error,
                RefreshLeaseLost,
            ):
                raise error

            raise RefreshLeaseLost(
                "Heartbeat failed and durable "
                "worker ownership can no longer be proven."
            )

        if _STOP_EVENT.is_set():
            release_refresh_job(
                engine,
                job_id=job_id,
                worker_id=(
                    worker_id_value
                ),
                reason=(
                    "Worker shutdown interrupted marketplace "
                    "execution; job queued for retry."
                ),
            )
            return

        if return_code == 0:
            mark_refresh_job_completed(
                engine,
                job_id=job_id,
                worker_id=(
                    worker_id_value
                ),
            )
            return

        failure_text = "\n".join(
            tail
        ).strip()

        if not failure_text:
            failure_text = (
                "Canonical marketplace runner exited "
                f"with status {return_code}."
            )

        mark_refresh_job_failed(
            engine,
            job_id=job_id,
            worker_id=(
                worker_id_value
            ),
            marketplace=(
                progress.current_marketplace
            ),
            error=failure_text[-8000:],
            message=(
                "Canonical marketplace runner failed "
                f"with status {return_code}."
            ),
        )
    finally:
        heartbeat.stop()

        if child.poll() is None:
            terminate_child(
                child
            )


def run_worker(
    args: argparse.Namespace,
) -> int:
    """Run the persistent claim/execute loop."""
    validate_configuration(
        args
    )

    prepare_persistent_profile(
        profile_name=(
            args.buyee_profile
        ),
        persistent_directory=(
            args.buyee_profile_dir
        ),
    )

    output_directory = (
        prepare_output_directory(
            args.output_dir
        )
    )

    effective_worker_id = worker_id(
        args.worker_id
    )

    engine = build_refresh_engine(
        args.database_url
    )

    print(
        "Auction ETL persistent refresh worker",
        flush=True,
    )
    print(
        "=====================================",
        flush=True,
    )
    print(
        f"WORKER_ID={effective_worker_id}",
        flush=True,
    )
    print(
        "DATABASE_CONFIGURATION=environment",
        flush=True,
    )
    print(
        f"BUYEE_PROFILE={args.buyee_profile}",
        flush=True,
    )
    print(
        "BUYEE_PROFILE_DIR="
        + (
            str(
                args.buyee_profile_dir
            )
            if args.buyee_profile_dir
            else "<canonical-local-profile>"
        ),
        flush=True,
    )

    while not _STOP_EVENT.is_set():
        try:
            recovered = (
                requeue_expired_refresh_jobs(
                    engine
                )
            )

            for recovered_job in recovered:
                print(
                    "RECOVERED_EXPIRED_JOB="
                    f"{recovered_job}",
                    flush=True,
                )

            job = claim_next_refresh_job(
                engine,
                worker_id=(
                    effective_worker_id
                ),
                lease_seconds=(
                    args.lease_seconds
                ),
            )
        except Exception as exc:
            print(
                "WORKER_COORDINATION_ERROR="
                f"{exc}",
                file=sys.stderr,
                flush=True,
            )

            _STOP_EVENT.wait(
                min(
                    max(
                        args.poll_seconds,
                        1.0,
                    ),
                    15.0,
                )
            )
            continue

        if job is None:
            _STOP_EVENT.wait(
                args.poll_seconds
            )
            continue

        job_id = str(
            job["id"]
        )

        print(
            f"CLAIMED_REFRESH_JOB={job_id}",
            flush=True,
        )

        try:
            execute_claimed_job(
                engine=engine,
                job=job,
                worker_id_value=(
                    effective_worker_id
                ),
                database_url=(
                    args.database_url
                ),
                buyee_profile=(
                    args.buyee_profile
                ),
                output_directory=(
                    output_directory
                ),
                lease_seconds=(
                    args.lease_seconds
                ),
                heartbeat_seconds=(
                    args.heartbeat_seconds
                ),
            )
        except RefreshLeaseLost as exc:
            print(
                "REFRESH_LEASE_LOST="
                f"{job_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            print(
                "REFRESH_JOB_WORKER_ERROR="
                f"{job_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )

            try:
                mark_refresh_job_failed(
                    engine,
                    job_id=job_id,
                    worker_id=(
                        effective_worker_id
                    ),
                    error=str(
                        exc
                    ),
                    message=(
                        "Persistent marketplace worker failed."
                    ),
                )
            except RefreshLeaseLost:
                pass
            except Exception as nested:
                print(
                    "REFRESH_JOB_FAILURE_PERSIST_ERROR="
                    f"{nested}",
                    file=sys.stderr,
                    flush=True,
                )

    print(
        "WORKER_SHUTDOWN=clean",
        flush=True,
    )

    return 0


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the persistent cloud worker."""
    install_signal_handlers()

    try:
        args = parse_args(
            argv
        )

        return run_worker(
            args
        )
    except WorkerError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
