"""Enqueue durable refresh jobs into the local PostgreSQL warehouse.

Streamlit queues work here and starts the local persistent worker if needed.
This module never launches a browser and never calls Vercel or Railway.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from auction_etl.auth.context import AccountContext
from auction_etl.runtime_authority import (
    LOCAL_DATABASE_TARGET,
    cloud_runtime_detected,
    require_database_access_allowed_here,
)
from auction_etl.services.refresh_jobs import (
    build_refresh_engine,
    create_refresh_job,
    refresh_job_to_ui_status,
)


ROOT = Path(__file__).resolve().parents[2]
WORKER_SCRIPT = ROOT / "scripts" / "run_cloud_refresh_worker.py"
WORKER_PID_PATH = ROOT / "logs" / "runtime" / "local-refresh-worker.pid"
WORKER_LOG_PATH = ROOT / "logs" / "runtime" / "local-refresh-worker.log"


class LocalRefreshDispatchError(RuntimeError):
    """Raised when local Streamlit cannot queue a durable refresh."""


def _pid_is_running(pid: int) -> bool:
    """Return whether a local process ID is still alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def ensure_local_refresh_worker(
    *,
    database_url: str,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Start or reuse the local persistent worker that claims queued jobs."""
    if cloud_runtime_detected(environment):
        raise LocalRefreshDispatchError(
            "Local durable refresh worker is not allowed on "
            "Vercel or Railway."
        )

    url = str(database_url or "").strip()
    if not url:
        raise LocalRefreshDispatchError(
            "DATABASE_URL is required to start the local refresh worker."
        )

    WORKER_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    if WORKER_PID_PATH.exists():
        try:
            existing = int(WORKER_PID_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            existing = 0
        if _pid_is_running(existing):
            return existing

    worker_environment = os.environ.copy()
    if environment is not None:
        worker_environment.update(
            {
                str(key): str(value)
                for key, value in environment.items()
            }
        )
    worker_environment["DATABASE_URL"] = url
    worker_environment.setdefault("AUCTION_ENV", "development")
    worker_environment.setdefault("OIDC_ENV", "development")
    for key in list(worker_environment):
        if key.startswith("RAILWAY_"):
            worker_environment.pop(key, None)
    worker_environment.setdefault("AUCTION_WORKER_LEASE_SECONDS", "1800")
    worker_environment["AUCTION_MARKETPLACE_BROWSER_MODE"] = "managed"

    with WORKER_LOG_PATH.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                str(WORKER_SCRIPT),
                "--database-url",
                url,
                "--poll-seconds",
                "1",
                "--lease-seconds",
                str(worker_environment["AUCTION_WORKER_LEASE_SECONDS"]),
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=worker_environment,
        )

    WORKER_PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    return process.pid


def enqueue_refresh_via_local_worker(
    *,
    database_url: str,
    account_context: AccountContext,
    environment: Mapping[str, str] | None = None,
    engine: Engine | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create or reuse one account-owned refresh job in local PostgreSQL."""

    if cloud_runtime_detected(environment):
        raise LocalRefreshDispatchError(
            "Local durable refresh enqueue is not allowed on "
            "Vercel or Railway. Queue jobs only on the local machine "
            f"against {LOCAL_DATABASE_TARGET}."
        )

    require_database_access_allowed_here()

    url = str(database_url or "").strip()
    if not url:
        raise LocalRefreshDispatchError(
            "DATABASE_URL is required to queue a local refresh job."
        )

    resolved_engine = (
        engine
        if engine is not None
        else build_refresh_engine(url)
    )

    job, created = create_refresh_job(
        resolved_engine,
        account_id=account_context.account_id,
        requested_by_user_id=account_context.user_id,
        requested_by=account_context.email,
        trigger="streamlit-local",
    )

    ensure_local_refresh_worker(
        database_url=url,
        environment=environment,
    )

    status = refresh_job_to_ui_status(job)
    status["coordination_ready"] = True
    return status, created
