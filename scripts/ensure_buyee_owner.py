"""Ensure the long-lived Buyee browser owner is running."""

from __future__ import annotations

import argparse
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from auction_etl.browser.buyee_owner import (
    OWNER_PROTOCOL_VERSION,
    BuyeeOwnerError,
    health,
    owner_socket_path,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OWNER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run_buyee_owner.py"


def parse_arguments() -> argparse.Namespace:
    """Parse owner startup arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Start or reuse the long-lived headed/offscreen "
            "Buyee browser owner."
        )
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(
            "profiles/buyee"
        ),
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
    )
    return parser.parse_args()


def socket_is_connectable(
    path: Path,
) -> bool:
    """Return whether a process currently accepts connections on the socket."""

    if not path.exists():
        return False

    try:
        with socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        ) as connection:
            connection.settimeout(
                0.5
            )
            connection.connect(
                str(
                    path
                )
            )
    except OSError:
        return False

    return True


def owner_health(
    path: Path,
) -> dict[str, Any] | None:
    """Return health metadata when the owner is reachable."""

    try:
        return health(
            socket_path=path,
            timeout_seconds=1.0,
        )
    except BuyeeOwnerError:
        return None


def print_health(
    payload: dict[str, Any],
    *,
    state: str,
) -> None:
    """Print stable non-secret owner metadata."""

    print(
        f"BUYEE_OWNER={state}"
    )
    print(
        "BUYEE_OWNER_PROTOCOL_VERSION="
        + str(
            payload.get(
                "protocol_version",
                "<none>",
            )
        )
    )
    print(
        "BUYEE_OWNER_PID="
        + str(
            payload.get(
                "pid",
                "<none>",
            )
        )
    )
    print(
        "BUYEE_OWNER_PROFILE="
        + str(
            payload.get(
                "profile",
                "<none>",
            )
        )
    )
    print(
        "BUYEE_OWNER_EXECUTABLE="
        + str(
            payload.get(
                "executable",
                "<none>",
            )
        )
    )
    print(
        "BUYEE_OWNER_HEADLESS="
        + str(
            payload.get(
                "headless",
                "<none>",
            )
        ).lower()
    )
    print(
        "BUYEE_OWNER_CDP="
        + str(
            payload.get(
                "cdp",
                "<none>",
            )
        ).lower()
    )


def _main_once() -> int:
    """Start the owner once and reuse it on later refreshes."""

    arguments = parse_arguments()
    profile_dir = (
        arguments.profile_dir
        .expanduser()
        .resolve()
    )
    socket_path = (
        owner_socket_path()
        if arguments.socket_path is None
        else (
            arguments.socket_path
            .expanduser()
            .resolve()
        )
    )

    if not profile_dir.is_dir():
        raise RuntimeError(
            f"Buyee profile is missing: {profile_dir}"
        )

    socket_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock_path = (
        socket_path.parent
        / "ensure.lock"
    )
    log_path = (
        socket_path.parent
        / "owner.log"
    )

    with lock_path.open(
        "a+"
    ) as lock_handle:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX,
        )

        existing = owner_health(
            socket_path
        )

        if existing is not None:
            if (
                existing.get(
                    "protocol_version"
                )
                != OWNER_PROTOCOL_VERSION
            ):
                raise RuntimeError(
                    "Running Buyee owner uses an incompatible protocol."
                )

            existing_profile = Path(
                str(
                    existing.get(
                        "profile",
                        "",
                    )
                )
            ).expanduser().resolve()

            if existing_profile != profile_dir:
                raise RuntimeError(
                    "Running Buyee owner uses a different profile: "
                    f"{existing_profile}"
                )

            print_health(
                existing,
                state="reused",
            )
            print(
                f"BUYEE_OWNER_SOCKET={socket_path}"
            )
            print(
                "VISIBLE_BROWSER_LAUNCHED=false"
            )
            print(
                "NEW_BROWSER_PER_REFRESH=false"
            )
            return 0

        if socket_is_connectable(
            socket_path
        ):
            raise RuntimeError(
                "The Buyee owner socket is occupied by an "
                "unrecognized live service."
            )

        try:
            socket_path.unlink(
                missing_ok=True
            )
        except OSError as error:
            raise RuntimeError(
                f"Could not remove stale owner socket: {socket_path}"
            ) from error

        environment = os.environ.copy()
        environment.pop(
            "AUCTION_BUYEE_CDP_URL",
            None,
        )
        environment[
            "AUCTION_BUYEE_OWNER_SOCKET"
        ] = str(
            socket_path
        )

        with log_path.open(
            "ab",
            buffering=0,
        ) as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(
                        OWNER_SCRIPT
                    ),
                    "--profile-dir",
                    str(
                        profile_dir
                    ),
                    "--socket-path",
                    str(
                        socket_path
                    ),
                ],
                cwd=str(
                    REPOSITORY_ROOT
                ),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=environment,
            )

        deadline = (
            time.monotonic()
            + max(
                arguments.timeout_seconds,
                1.0,
            )
        )

        while time.monotonic() < deadline:
            payload = owner_health(
                socket_path
            )

            if payload is not None:
                existing_profile = Path(
                    str(
                        payload.get(
                            "profile",
                            "",
                        )
                    )
                ).expanduser().resolve()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != OWNER_PROTOCOL_VERSION
                ):
                    raise RuntimeError(
                        "Started Buyee owner reported an incompatible protocol."
                    )

                if existing_profile != profile_dir:
                    raise RuntimeError(
                        "Started Buyee owner reported the wrong profile."
                    )

                print_health(
                    payload,
                    state="started",
                )
                print(
                    f"BUYEE_OWNER_SOCKET={socket_path}"
                )
                print(
                    f"BUYEE_OWNER_LOG={log_path}"
                )
                print(
                    "VISIBLE_BROWSER_LAUNCHED=false"
                )
                print(
                    "NEW_BROWSER_PER_REFRESH=false"
                )
                return 0

            exit_code = process.poll()

            if exit_code is not None:
                try:
                    tail = log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).splitlines()[
                        -80:
                    ]
                except OSError:
                    tail = []

                if tail:
                    print()
                    print(
                        "--- Buyee owner log ---"
                    )
                    print(
                        "\n".join(
                            tail
                        )
                    )

                raise RuntimeError(
                    "Buyee owner exited before becoming ready "
                    f"with status {exit_code}."
                )

            time.sleep(
                0.25
            )

    raise RuntimeError(
        "Timed out waiting for the Buyee owner to become ready."
    )



OWNER_SOCKET_UNRECOGNIZED_ERROR = (
    "The Buyee owner socket is occupied by "
    "an unrecognized live service."
)

OWNER_SOCKET_RECOVERY_RETRIES = 20

OWNER_SOCKET_RECOVERY_DELAY_SECONDS = 0.25


def _wait_before_owner_retry() -> None:
    """Wait briefly for an unhealthy owner to finish shutting down."""

    import time

    time.sleep(
        OWNER_SOCKET_RECOVERY_DELAY_SECONDS
    )


def main():
    """Ensure the Buyee owner, tolerating its bounded teardown race."""

    for retry_index in range(
        OWNER_SOCKET_RECOVERY_RETRIES
        + 1
    ):
        try:
            return _main_once()
        except RuntimeError as error:
            if (
                str(error)
                != OWNER_SOCKET_UNRECOGNIZED_ERROR
                or retry_index
                >= OWNER_SOCKET_RECOVERY_RETRIES
            ):
                raise

            _wait_before_owner_retry()

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
