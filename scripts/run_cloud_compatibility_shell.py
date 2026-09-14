#!/usr/bin/env python3
"""Keep the retired Railway service healthy without data-plane execution."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence

from auction_etl.runtime_authority import (
    DATA_AUTHORITY,
    cloud_runtime_detected,
)


_STOP_EVENT = threading.Event()


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse compatibility-shell arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the database-free Railway compatibility shell."
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the Railway runtime contract and exit."
        ),
    )

    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=300.0,
        help=(
            "Seconds between local liveness messages."
        ),
    )

    arguments = parser.parse_args(
        argv
    )

    if arguments.heartbeat_seconds < 5.0:
        parser.error(
            "--heartbeat-seconds must be at least 5."
        )

    return arguments


def railway_runtime_detected(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether this process is running inside Railway."""
    values = (
        os.environ
        if environment is None
        else environment
    )

    return bool(
        str(
            values.get(
                "RAILWAY_DEPLOYMENT_ID",
                "",
            )
        ).strip()
    )


def validate_runtime(
    environment: Mapping[str, str] | None = None,
) -> None:
    """Require the intended retired Railway compatibility runtime."""
    values = (
        os.environ
        if environment is None
        else environment
    )

    if not railway_runtime_detected(
        values
    ):
        raise RuntimeError(
            "Railway deployment identity is unavailable."
        )

    if not cloud_runtime_detected(
        values
    ):
        raise RuntimeError(
            "Railway was not recognized as a cloud runtime."
        )

    if DATA_AUTHORITY != "local":
        raise RuntimeError(
            "Data authority is not local."
        )


def emit_contract() -> None:
    """Emit the non-data execution contract."""
    print(
        "RAILWAY_COMPATIBILITY_SHELL=true",
        flush=True,
    )
    print(
        "DATA_AUTHORITY=local",
        flush=True,
    )
    print(
        "CLOUD_DATABASE_ACCESS=false",
        flush=True,
    )
    print(
        "CLOUD_REFRESH_WORKER_EXECUTED=false",
        flush=True,
    )
    print(
        "MARKETPLACE_REQUEST_EXECUTED=false",
        flush=True,
    )
    print(
        "REAL_REFRESH_RUN=false",
        flush=True,
    )


def request_shutdown(
    _signum: int,
    _frame: object,
) -> None:
    """Request a clean process shutdown."""
    _STOP_EVENT.set()


def install_signal_handlers() -> None:
    """Install clean Railway deployment shutdown handlers."""
    signal.signal(
        signal.SIGTERM,
        request_shutdown,
    )
    signal.signal(
        signal.SIGINT,
        request_shutdown,
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the compatibility shell."""
    arguments = parse_arguments(
        argv
    )

    try:
        validate_runtime()
    except RuntimeError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    emit_contract()

    if arguments.check:
        print(
            "RAILWAY_COMPATIBILITY_SHELL_CHECK=PASS",
            flush=True,
        )
        return 0

    _STOP_EVENT.clear()
    install_signal_handlers()

    print(
        "RAILWAY_COMPATIBILITY_SHELL_STATE=ready",
        flush=True,
    )

    while not _STOP_EVENT.wait(
        arguments.heartbeat_seconds
    ):
        print(
            "RAILWAY_COMPATIBILITY_SHELL_STATE=alive",
            flush=True,
        )

    print(
        "RAILWAY_COMPATIBILITY_SHELL_STATE=shutdown",
        flush=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
