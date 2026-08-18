"""Run one high-level Buyee job through the local browser owner."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from auction_etl.browser.buyee_owner import (
    BuyeeOwnerError,
    forwarded_environment,
    owner_socket_path,
    run_job,
)


COMMANDS = (
    "verify_closed_watchlist",
    "crawl_closed_watchlist",
    "crawl_live_details",
)


def parse_arguments() -> argparse.Namespace:
    """Parse owner options and preserve target-command arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Execute Buyee browser work inside the long-lived "
            "local Playwright owner."
        )
    )
    parser.add_argument(
        "command",
        choices=COMMANDS,
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=900.0,
    )

    arguments, job_arguments = parser.parse_known_args()

    if (
        job_arguments
        and job_arguments[0]
        == "--"
    ):
        job_arguments = (
            job_arguments[
                1:
            ]
        )

    arguments.job_arguments = job_arguments

    return arguments


def main() -> int:
    """Forward one command and mirror its output and exit code."""

    arguments = parse_arguments()
    socket_path = (
        owner_socket_path()
        if arguments.socket_path is None
        else (
            arguments.socket_path
            .expanduser()
            .resolve()
        )
    )

    try:
        response = run_job(
            arguments.command,
            arguments=list(
                arguments.job_arguments
            ),
            environment=forwarded_environment(
                os.environ
            ),
            socket_path=socket_path,
            timeout_seconds=(
                arguments.timeout_seconds
            ),
        )
    except BuyeeOwnerError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    output = str(
        response.get(
            "output",
            "",
        )
    )

    if output:
        print(
            output,
            end=(
                ""
                if output.endswith(
                    "\n"
                )
                else "\n"
            ),
        )

    try:
        exit_code = int(
            response.get(
                "exit_code",
                1,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        print(
            "ERROR: Buyee owner returned an invalid exit code.",
            file=sys.stderr,
        )
        return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
