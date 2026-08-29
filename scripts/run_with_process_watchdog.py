#!/usr/bin/env python3
"""Run a subprocess under a hard wall-clock process-group watchdog."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from collections.abc import Sequence


WATCHDOG_TIMEOUT_EXIT_CODE = 124


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse watchdog options and the command following ``--``."""

    parser = argparse.ArgumentParser(
        description=(
            "Run a command in a dedicated process session and "
            "terminate the full process group if its wall-clock "
            "deadline expires."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        required=True,
        type=float,
    )
    parser.add_argument(
        "--kill-grace-seconds",
        type=float,
        default=10.0,
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
    )

    args = parser.parse_args(argv)

    command = list(args.command)

    if command and command[0] == "--":
        command.pop(0)

    if not command:
        parser.error(
            "a command is required after --"
        )

    if args.timeout_seconds <= 0:
        parser.error(
            "--timeout-seconds must be greater than zero"
        )

    if args.kill_grace_seconds < 0:
        parser.error(
            "--kill-grace-seconds cannot be negative"
        )

    args.command = command

    return args


def terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float,
) -> None:
    """Terminate the isolated child process group."""

    if process.poll() is not None:
        return

    try:
        process_group = os.getpgid(
            process.pid
        )
    except ProcessLookupError:
        return

    try:
        os.killpg(
            process_group,
            signal.SIGTERM,
        )
    except ProcessLookupError:
        return

    try:
        process.wait(
            timeout=grace_seconds,
        )
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(
            process_group,
            signal.SIGKILL,
        )
    except ProcessLookupError:
        pass

    process.wait()


def run_guarded_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    kill_grace_seconds: float,
) -> int:
    """Run a command and return its exit code or 124 on timeout."""

    process = subprocess.Popen(
        list(command),
        start_new_session=True,
    )

    try:
        return process.wait(
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(
            "PROCESS_WATCHDOG_TIMEOUT="
            f"{timeout_seconds:g}",
            file=sys.stderr,
            flush=True,
        )
        print(
            "PROCESS_WATCHDOG_PID="
            f"{process.pid}",
            file=sys.stderr,
            flush=True,
        )

        terminate_process_group(
            process,
            grace_seconds=kill_grace_seconds,
        )

        print(
            "PROCESS_WATCHDOG_TERMINATED_PROCESS_GROUP=true",
            file=sys.stderr,
            flush=True,
        )

        return WATCHDOG_TIMEOUT_EXIT_CODE


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the requested command under the watchdog."""

    args = parse_args(argv)

    return run_guarded_command(
        args.command,
        timeout_seconds=args.timeout_seconds,
        kill_grace_seconds=args.kill_grace_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
