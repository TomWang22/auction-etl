"""Define the Collector Ledger runtime data-authority boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping


DATA_AUTHORITY = "local"
LOCAL_DATABASE_TARGET = "127.0.0.1:5544/auction_warehouse"

_CLOUD_RUNTIME_MARKERS = (
    "VERCEL",
    "VERCEL_ENV",
    "RAILWAY_DEPLOYMENT_ID",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)


def cloud_runtime_detected(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether execution is occurring on a retired cloud data host."""

    values = (
        os.environ
        if environment is None
        else environment
    )

    return any(
        str(
            values.get(
                variable,
                "",
            )
        ).strip()
        for variable in _CLOUD_RUNTIME_MARKERS
    )


def require_database_access_allowed_here() -> None:
    """Reject database access from Vercel or Railway."""

    if not cloud_runtime_detected():
        return

    raise RuntimeError(
        "Cloud database access is disabled. "
        "Local PostgreSQL at "
        f"{LOCAL_DATABASE_TARGET} is authoritative."
    )


def cloud_worker_execution_allowed_here() -> bool:
    """Return whether the legacy durable cloud worker may execute here."""

    return not cloud_runtime_detected()
