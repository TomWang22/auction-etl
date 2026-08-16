"""Background orchestration for user-triggered multisource auction ingestion."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final


REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_RUNNER: Final[Path] = (
    REPOSITORY_ROOT
    / "scripts"
    / "run_auction_refresh_on_demand.sh"
)

RUNTIME_ROOT: Final[Path] = (
    Path.home()
    / ".auction-etl"
    / "runtime"
    / "auction-ingest"
)

JOB_ROOT: Final[Path] = RUNTIME_ROOT / "jobs"
LOG_ROOT: Final[Path] = RUNTIME_ROOT / "logs"
LATEST_PATH: Final[Path] = RUNTIME_ROOT / "latest.json"
CONTROLLER_LOCK: Final[Path] = RUNTIME_ROOT / "controller.lock"

PLANNED_SOURCES: Final[tuple[str, ...]] = (
    "eBay",
    "Buyee",
    "Gripsweat",
)

RUNNING_STATES: Final[frozenset[str]] = frozenset(
    {
        "queued",
        "running",
    }
)

ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)


SOURCE_STATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^AUCTION_SOURCE_STATE "
    r"source=(eBay|Buyee|Gripsweat) "
    r"state=(running|done|unavailable|failed)$"
)

def utc_now() -> str:
    """Return a stable UTC timestamp."""

    return datetime.now(UTC).isoformat()


def ensure_runtime_directories() -> None:
    """Create local runtime storage outside the repository."""

    RUNTIME_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )
    JOB_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )
    LOG_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


def job_path(job_id: str) -> Path:
    """Return the persisted status path for one job."""

    validate_job_id(job_id)
    return JOB_ROOT / f"{job_id}.json"


def log_path(job_id: str) -> Path:
    """Return the persisted log path for one job."""

    validate_job_id(job_id)
    return LOG_ROOT / f"{job_id}.log"


def validate_job_id(job_id: str) -> None:
    """Reject arbitrary paths passed through worker CLI arguments."""

    try:
        parsed = uuid.UUID(hex=job_id)
    except ValueError as exc:
        raise ValueError(
            f"Invalid auction ingest job id: {job_id!r}"
        ) from exc

    if parsed.hex != job_id:
        raise ValueError(
            f"Invalid auction ingest job id: {job_id!r}"
        )



def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Persist JSON atomically using a private temporary file per writer."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_handle:
            temporary_path = Path(
                temporary_handle.name
            )

            json.dump(
                payload,
                temporary_handle,
                indent=2,
                sort_keys=True,
            )

            temporary_handle.write(
                "\n"
            )

            temporary_handle.flush()

            os.fsync(
                temporary_handle.fileno()
            )

        os.replace(
            temporary_path,
            path,
        )

        temporary_path = None

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink(
                missing_ok=True,
            )



def read_json(
    path: Path,
) -> dict[str, Any] | None:
    """Read a persisted JSON object when present and valid."""

    if not path.is_file():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        json.JSONDecodeError,
        OSError,
    ):
        return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    return payload


def persist_status(
    status: dict[str, Any],
) -> dict[str, Any]:
    """Persist both the job-specific and latest status documents."""

    status["updated_at"] = utc_now()

    atomic_write_json(
        job_path(
            str(
                status["job_id"]
            )
        ),
        status,
    )

    atomic_write_json(
        LATEST_PATH,
        status,
    )

    return status


def process_is_alive(
    pid: int | None,
) -> bool:
    """Return whether a local process still exists."""

    if not pid:
        return False

    try:
        os.kill(
            int(pid),
            0,
        )
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False

    return True


def get_latest_status() -> dict[str, Any] | None:
    """Return the latest job and repair stale running state if required."""

    ensure_runtime_directories()

    status = read_json(
        LATEST_PATH
    )

    if status is None:
        return None

    state = str(
        status.get(
            "status",
            "",
        )
    )

    if state not in RUNNING_STATES:
        return status

    pid = status.get(
        "worker_pid"
    )

    if (
        state == "queued"
        and not isinstance(
            pid,
            int,
        )
    ):
        registration_deadline = status.get(
            "worker_registration_deadline"
        )

        if (
            isinstance(
                registration_deadline,
                (
                    int,
                    float,
                ),
            )
            and time.time()
            <= float(
                registration_deadline
            )
        ):
            return status

        status["status"] = "failed"
        status["phase"] = "Worker did not start"
        status["stage"] = "starting"
        status["failure_stage"] = "starting"
        status["message"] = (
            "The background refresh did not finish starting. "
            "You can retry when ready."
        )
        status["finished_at"] = utc_now()
        status["return_code"] = None

        return persist_status(
            status
        )

    worker_pid = (
        int(pid)
        if isinstance(
            pid,
            int,
        )
        else None
    )

    if process_is_alive(
        worker_pid
    ):
        return status

    status["status"] = "failed"
    status["phase"] = "Worker exited unexpectedly"
    status["message"] = (
        "The background refresh stopped before publishing "
        "a completion result."
    )
    status["finished_at"] = utc_now()
    status["return_code"] = None
    status["failure_stage"] = str(
        status.get(
            "stage",
            "starting",
        )
    )

    source_states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    for name, source_state in source_states.items():
        if source_state == "running":
            source_states[name] = "failed"

    status["source_states"] = source_states

    return persist_status(
        status
    )


def build_runner_command() -> list[str]:
    """Resolve the configured production ingestion entrypoint."""

    configured = os.environ.get(
        "AUCTION_INGEST_RUNNER"
    )

    if configured:
        command = shlex.split(
            configured
        )

        if not command:
            raise RuntimeError(
                "AUCTION_INGEST_RUNNER is empty."
            )

        return command

    if not DEFAULT_RUNNER.is_file():
        raise RuntimeError(
            "Missing production ingestion runner: "
            f"{DEFAULT_RUNNER}"
        )

    return [
        "bash",
        str(
            DEFAULT_RUNNER
        ),
    ]


def new_status(
    job_id: str,
) -> dict[str, Any]:
    """Create a queued multisource-ingestion status document."""

    return {
        "schema":
            "auction-ingest-job/v1",
        "job_id":
            job_id,
        "status":
            "queued",
        "progress":
            2,
        "phase":
            "Queued",
        "stage":
            "queued",
        "failure_stage":
            None,
        "message":
            "Waiting for the background ingestion worker.",
        "created_at":
            utc_now(),
        "started_at":
            None,
        "finished_at":
            None,
        "updated_at":
            utc_now(),
        "worker_pid":
            None,
        "worker_registration_deadline":
            time.time()
            + 15.0,
        "runner_pid":
            None,
        "return_code":
            None,
        "runner_command":
            None,
        "planned_sources":
            list(
                PLANNED_SOURCES
            ),
        "source_state_protocol":
            "explicit-v1",
        "source_states": {
            source:
                "waiting"
            for source
            in PLANNED_SOURCES
        },
        "last_output":
            None,
        "log_path":
            str(
                log_path(
                    job_id
                )
            ),
    }


def start_job() -> dict[str, Any]:
    """Start exactly one background ingestion job."""

    ensure_runtime_directories()

    with CONTROLLER_LOCK.open(
        "a+",
        encoding="utf-8",
    ) as lock_handle:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX,
        )

        latest = get_latest_status()

        if (
            latest is not None
            and latest.get("status")
            in RUNNING_STATES
        ):
            return latest

        job_id = uuid.uuid4().hex

        status = new_status(
            job_id
        )

        persist_status(
            status
        )

        worker_output_path = log_path(
            job_id
        )

        try:
            with worker_output_path.open(
                "ab",
                buffering=0,
            ) as worker_log:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        str(
                            Path(
                                __file__
                            ).resolve()
                        ),
                        "worker",
                        job_id,
                    ],
                    cwd=str(
                        REPOSITORY_ROOT
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=worker_log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )

        except (
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            status["status"] = "failed"
            status["phase"] = (
                "Could not start background refresh"
            )
            status["stage"] = "starting"
            status["failure_stage"] = "starting"
            status["finished_at"] = utc_now()
            status["message"] = (
                "The background refresh could not be started."
            )
            status["last_output"] = (
                f"{type(error).__name__}: {error}"
            )

            return persist_status(
                status
            )

        status["worker_pid"] = worker.pid
        status["worker_registration_deadline"] = None
        status["stage"] = "starting"
        status["message"] = (
            "Background ingestion worker started."
        )

        persist_status(
            status
        )

        return status



def strip_terminal_codes(
    line: str,
) -> str:
    """Return log output suitable for progress inspection."""

    return ANSI_ESCAPE_RE.sub(
        "",
        line,
    ).strip()


def advance_progress(
    status: dict[str, Any],
    candidate: int,
    phase: str,
    message: str,
) -> None:
    """Advance progress monotonically."""

    current = int(
        status.get(
            "progress",
            0,
        )
    )

    if candidate > current:
        status["progress"] = candidate

    status["phase"] = phase
    status["message"] = message


def apply_explicit_source_state(
    status: dict[str, Any],
    clean_line: str,
) -> bool:
    """Apply one machine-readable marketplace lifecycle event."""

    match = SOURCE_STATE_RE.fullmatch(
        clean_line
    )

    if match is None:
        return False

    source_name = match.group(1)
    source_state = match.group(2)

    states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    states[
        source_name
    ] = source_state

    status[
        "source_states"
    ] = states

    status[
        "source_state_protocol"
    ] = "explicit-v1"

    status[
        "stage"
    ] = "marketplace"

    progress_values = {
        ("Buyee", "running"): (
            12,
            "Refreshing Buyee",
        ),
        ("Buyee", "done"): (
            28,
            "Buyee complete",
        ),
        ("Buyee", "unavailable"): (
            28,
            "Buyee unavailable",
        ),
        ("eBay", "running"): (
            32,
            "Refreshing eBay",
        ),
        ("eBay", "done"): (
            52,
            "eBay complete",
        ),
        ("Gripsweat", "running"): (
            56,
            "Refreshing Gripsweat",
        ),
        ("Gripsweat", "done"): (
            72,
            "Gripsweat complete",
        ),
    }

    if source_state == "failed":
        status[
            "failure_stage"
        ] = "marketplace"

        advance_progress(
            status,
            64,
            f"{source_name} refresh failed",
            clean_line,
        )

        return True

    progress_value = progress_values.get(
        (
            source_name,
            source_state,
        )
    )

    if progress_value is not None:
        candidate, phase = progress_value

        advance_progress(
            status,
            candidate,
            phase,
            clean_line,
        )

    return True


def observe_source(
    status: dict[str, Any],
    source_name: str,
) -> None:
    """Mark one source as observed by the production runner."""

    if (
        status.get(
            "source_state_protocol"
        )
        == "explicit-v1"
    ):
        return

    states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    for name in PLANNED_SOURCES:
        if (
            states.get(name)
            == "running"
            and name != source_name
        ):
            states[name] = "observed"

    if states.get(
        source_name
    ) not in {
        "done",
        "failed",
    }:
        states[source_name] = "running"

    status["source_states"] = states
    status["stage"] = "marketplace"


def finish_active_sources(
    status: dict[str, Any],
) -> None:
    """Close marketplace activity before post-processing begins."""

    if (
        status.get(
            "source_state_protocol"
        )
        == "explicit-v1"
    ):
        return

    states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    for source, source_state in states.items():
        if source_state == "running":
            states[source] = "observed"

    status["source_states"] = states


def interpret_output(
    status: dict[str, Any],
    raw_line: str,
) -> None:
    """Convert production output into stable product-facing progress."""

    clean_line = strip_terminal_codes(
        raw_line
    )

    if not clean_line:
        return

    status["last_output"] = clean_line

    if apply_explicit_source_state(
        status,
        clean_line,
    ):
        return

    lowered = clean_line.lower()

    explicit_failure_line = (
        "refresh failed:" in lowered
        or "commandfailure:" in lowered
    )

    if explicit_failure_line:
        failed_source: str | None = None

        if "gripsweat" in lowered:
            failed_source = "Gripsweat"
        elif "buyee" in lowered:
            failed_source = "Buyee"
        elif "ebay" in lowered:
            failed_source = "eBay"

        if failed_source is not None:
            states = dict(
                status.get(
                    "source_states",
                    {},
                )
            )

            if (
                status.get(
                    "source_state_protocol"
                )
                != "explicit-v1"
            ):
                for source, source_state in states.items():
                    if (
                        source_state == "running"
                        and source != failed_source
                    ):
                        states[source] = "observed"

            states[
                failed_source
            ] = "failed"

            status[
                "source_states"
            ] = states

            status[
                "stage"
            ] = "marketplace"

            status[
                "failure_stage"
            ] = "marketplace"

            advance_progress(
                status,
                64,
                f"{failed_source} refresh failed",
                clean_line,
            )

            return

    if status.get(
        "failure_stage"
    ):
        return

    stage_order = {
        "queued": 0,
        "starting": 1,
        "marketplace": 2,
        "post_processing": 3,
        "verification": 4,
        "finalizing": 5,
        "complete": 6,
    }

    def stage_rank() -> int:
        """Return the rank of the current refresh stage."""

        return stage_order.get(
            str(
                status.get(
                    "stage",
                    "starting",
                )
            ),
            stage_order[
                "starting"
            ],
        )

    if (
        not status.get(
            "source_state_protocol"
        )
        and stage_rank()
        <= stage_order[
            "marketplace"
        ]
    ):
        if "ebay" in lowered:
            observe_source(
                status,
                "eBay",
            )

            advance_progress(
                status,
                20,
                "Ingesting eBay",
                clean_line,
            )

        if "buyee" in lowered:
            observe_source(
                status,
                "Buyee",
            )

            advance_progress(
                status,
                42,
                "Ingesting Buyee",
                clean_line,
            )

        if "gripsweat" in lowered:
            observe_source(
                status,
                "Gripsweat",
            )

            advance_progress(
                status,
                64,
                "Ingesting Gripsweat",
                clean_line,
            )

    post_processing_marker = any(
        marker in lowered
        for marker in (
            "collector reclassification",
            "reclassif",
            "normalize",
            "enrich",
            "update auction fx",
            "exchange rate",
        )
    )

    if (
        post_processing_marker
        and stage_rank()
        <= stage_order[
            "post_processing"
        ]
    ):
        finish_active_sources(
            status
        )

        status[
            "stage"
        ] = "post_processing"

        if any(
            marker in lowered
            for marker in (
                "update auction fx",
                "exchange rate",
            )
        ):
            advance_progress(
                status,
                88,
                "Updating derived auction values",
                clean_line,
            )
        else:
            advance_progress(
                status,
                78,
                "Updating normalized auction data",
                clean_line,
            )

    verification_marker = any(
        marker in lowered
        for marker in (
            "health check",
            "verification",
            "verify refreshed",
            "verify results",
        )
    )

    if (
        verification_marker
        and stage_rank()
        >= stage_order[
            "post_processing"
        ]
        and stage_rank()
        <= stage_order[
            "verification"
        ]
    ):
        finish_active_sources(
            status
        )

        status[
            "stage"
        ] = "verification"

        advance_progress(
            status,
            94,
            "Verifying refreshed data",
            clean_line,
        )

    stripped = lowered.strip()

    finishing_marker = (
        stripped.startswith(
            "result="
        )
        or "completed successfully"
        in lowered
        or "refresh completed"
        in lowered
    )

    if (
        finishing_marker
        and stage_rank()
        >= stage_order[
            "post_processing"
        ]
        and stage_rank()
        <= stage_order[
            "finalizing"
        ]
    ):
        finish_active_sources(
            status
        )

        status[
            "stage"
        ] = "finalizing"

        advance_progress(
            status,
            97,
            "Finishing",
            clean_line,
        )



def mark_all_sources_done(
    status: dict[str, Any],
) -> None:
    """Finalize source states after the production runner exits cleanly."""

    states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    if (
        status.get(
            "source_state_protocol"
        )
        == "explicit-v1"
    ):
        terminal_states = {
            "done",
            "failed",
            "unavailable",
        }

        for source in PLANNED_SOURCES:
            if states.get(
                source
            ) not in terminal_states:
                states[
                    source
                ] = "failed"
    else:
        states = {
            source:
                "done"
            for source
            in PLANNED_SOURCES
        }

    status[
        "source_states"
    ] = states

    status[
        "stage"
    ] = "complete"


def mark_active_sources_failed(
    status: dict[str, Any],
) -> None:
    """Mark only a marketplace that was active during marketplace failure."""

    if (
        status.get(
            "source_state_protocol"
        )
        == "explicit-v1"
    ):
        states = dict(
            status.get(
                "source_states",
                {},
            )
        )

        for source, source_state in states.items():
            if source_state == "running":
                states[
                    source
                ] = "failed"

        status[
            "source_states"
        ] = states
        return

    states = dict(
        status.get(
            "source_states",
            {},
        )
    )

    if str(
        status.get(
            "failure_stage",
            status.get(
                "stage",
                "",
            ),
        )
    ) != "marketplace":
        for source, source_state in states.items():
            if source_state == "running":
                states[source] = "observed"

        status["source_states"] = states
        return

    for source, source_state in states.items():
        if source_state == "running":
            states[source] = "failed"

    status["source_states"] = states



def wait_for_worker_registration(
    job_id: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Wait until the parent records this worker PID before changing status."""

    validate_job_id(
        job_id
    )

    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    observed_worker_pid: object = None

    while True:
        status = read_json(
            job_path(
                job_id
            )
        )

        if status is not None:
            observed_worker_pid = status.get(
                "worker_pid"
            )

            if (
                isinstance(
                    observed_worker_pid,
                    int,
                )
                and observed_worker_pid
                == os.getpid()
            ):
                return status

        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Parent did not register the ingestion worker "
                f"within {timeout_seconds:.1f} seconds. "
                f"Expected PID {os.getpid()}, "
                f"observed {observed_worker_pid!r}."
            )

        time.sleep(
            0.02
        )


def run_worker(
    job_id: str,
) -> int:
    """Run the production ingestion process and publish progress."""

    validate_job_id(
        job_id
    )
    ensure_runtime_directories()

    status = wait_for_worker_registration(
        job_id
    )

    command = build_runner_command()

    status["status"] = "running"
    status["progress"] = 5
    status["phase"] = "Starting ingestion"
    status["stage"] = "starting"
    status["failure_stage"] = None
    status["message"] = (
        "Launching the existing multisource auction refresh pipeline."
    )
    status["started_at"] = utc_now()
    status["worker_pid"] = os.getpid()
    status["runner_command"] = command

    persist_status(
        status
    )

    output_path = log_path(
        job_id
    )

    with output_path.open(
        "a",
        encoding="utf-8",
        buffering=1,
    ) as log_handle:
        log_handle.write(
            f"[{utc_now()}] Starting auction ingestion\n"
        )
        log_handle.write(
            "Command: "
            + shlex.join(
                command
            )
            + "\n\n"
        )

        process = subprocess.Popen(
            command,
            cwd=str(
                REPOSITORY_ROOT
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
            env=os.environ.copy(),
        )

        status["runner_pid"] = process.pid
        persist_status(
            status
        )

        assert process.stdout is not None

        try:
            for line in process.stdout:
                log_handle.write(
                    line
                )

                interpret_output(
                    status,
                    line,
                )

                persist_status(
                    status
                )

        except KeyboardInterrupt:
            try:
                os.killpg(
                    os.getpgid(
                        process.pid
                    ),
                    signal.SIGTERM,
                )
            except OSError:
                pass

            raise

        return_code = process.wait()

        log_handle.write(
            f"\n[{utc_now()}] "
            f"Runner exit status: {return_code}\n"
        )

    status["return_code"] = return_code
    status["finished_at"] = utc_now()

    if return_code == 0:
        mark_all_sources_done(
            status
        )
        status["status"] = "completed"
        status["progress"] = 100
        status["phase"] = "Complete"
        status["failure_stage"] = None
        status["message"] = (
            "New auction ingestion finished successfully."
        )

    else:
        failure_stage = str(
            status.get(
                "failure_stage"
            )
            or status.get(
                "stage",
                "starting",
            )
        )

        status["failure_stage"] = failure_stage

        mark_active_sources_failed(
            status
        )

        status["status"] = "failed"

        if failure_stage == "post_processing":
            status["phase"] = "Post-processing failed"
            status["message"] = (
                "Marketplace collection finished, but processing "
                "the refreshed data failed. Open technical details "
                "for the underlying command."
            )

        elif failure_stage == "verification":
            status["phase"] = "Verification failed"
            status["message"] = (
                "Marketplace data was refreshed, but verification "
                "did not finish successfully. Open technical details "
                "for the underlying command."
            )

        elif failure_stage == "finalizing":
            status["phase"] = "Finalization failed"
            status["message"] = (
                "Marketplace data was refreshed, but the final "
                "processing step failed. Open technical details "
                "for the underlying command."
            )

        else:
            status["phase"] = "Ingestion failed"
            status["message"] = (
                "The production refresh pipeline exited with "
                f"status {return_code}. Open technical details "
                "for the underlying command."
            )

    persist_status(
        status
    )

    return return_code



def tail_log(
    path: str | Path | None,
    line_count: int = 100,
) -> str:
    """Return the last lines from one job log."""

    if not path:
        return ""

    log_file = Path(
        path
    )

    if not log_file.is_file():
        return ""

    try:
        lines = log_file.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return ""

    return "\n".join(
        lines[
            -line_count:
        ]
    )


def parse_cli() -> argparse.Namespace:
    """Parse the private worker CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Background worker for Streamlit auction ingestion."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    worker_parser = subparsers.add_parser(
        "worker"
    )
    worker_parser.add_argument(
        "job_id"
    )

    return parser.parse_args()


def main() -> int:
    """Run the worker command."""

    arguments = parse_cli()

    if arguments.command == "worker":
        return run_worker(
            arguments.job_id
        )

    raise RuntimeError(
        f"Unsupported command: {arguments.command}"
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
