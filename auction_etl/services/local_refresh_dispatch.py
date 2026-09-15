"""Enqueue durable refresh jobs into the local PostgreSQL warehouse.

Streamlit queues work here. The local persistent worker claims it.
This module never launches a browser and never calls Vercel or Railway.
"""

from __future__ import annotations

from collections.abc import Mapping
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


class LocalRefreshDispatchError(RuntimeError):
    """Raised when local Streamlit cannot queue a durable refresh."""


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

    status = refresh_job_to_ui_status(job)
    status["coordination_ready"] = True
    return status, created
