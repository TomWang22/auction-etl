"""Ensure the long-lived headed eBay browser owner is running."""

from __future__ import annotations

import argparse
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from auction_etl.browser.ebay_owner import (
    OWNER_PROTOCOL_VERSION,
    EbayOwnerError,
    health,
    owner_socket_path,
)
from auction_etl.runtime_authority import (
    LOCAL_DATABASE_TARGET,
    cloud_runtime_detected,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OWNER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run_ebay_owner.py"


def owner_process_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the persistent browser owner's DB-free startup environment."""

    source = (
        os.environ
        if environment is None
        else environment
    )

    return {
        key: value
        for key, value in source.items()
        if (
            key != "DATABASE_URL"
            and key
            not in {
                "AUCTION_EXPECTED_DATABASE_NAME",
                "AUCTION_EXPECTED_DATABASE_USER",
                "AUCTION_EBAY_CDP_URL",
            }
            and not key.startswith("PG")
        )
    }


def parse_arguments() -> argparse.Namespace:
    """Parse owner startup arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Start or reuse the long-lived headed/offscreen "
            "eBay browser owner."
        )
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        required=True,
        help="Authenticated Playwright storage-state JSON file.",
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
    parser.add_argument(
        "--background",
        action="store_true",
        help=(
            "Keep the owner running in the background. "
            "ensure always daemonizes; this flag documents that intent."
        ),
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
            connection.settimeout(0.5)
            connection.connect(str(path))
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
    except EbayOwnerError:
        return None


def print_health(
    payload: dict[str, Any],
    *,
    state: str,
) -> None:
    """Print stable non-secret owner metadata."""

    print(f"EBAY_OWNER={state}")
    print(
        "EBAY_OWNER_PROTOCOL_VERSION="
        + str(payload.get("protocol_version", "<none>"))
    )
    print(
        "EBAY_OWNER_PID="
        + str(payload.get("pid", "<none>"))
    )
    print(
        "EBAY_OWNER_STORAGE_STATE="
        + str(payload.get("storage_state", "<none>"))
    )
    print(
        "EBAY_OWNER_EXECUTABLE="
        + str(payload.get("executable", "<none>"))
    )
    print(
        "EBAY_OWNER_HEADLESS="
        + str(payload.get("headless", "<none>")).lower()
    )
    print(
        "EBAY_OWNER_CDP="
        + str(payload.get("cdp", "<none>")).lower()
    )


def _main_once() -> int:
    """Start the owner once and reuse it on later refreshes."""

    if cloud_runtime_detected():
        raise RuntimeError(
            "The eBay browser owner may only run on the local machine. "
            "Vercel and Railway must not acquire eBay. "
            f"Local warehouse remains {LOCAL_DATABASE_TARGET}."
        )

    arguments = parse_arguments()
    storage_state = (
        arguments.storage_state
        .expanduser()
        .resolve()
    )
    socket_path = (
        owner_socket_path()
        if arguments.socket_path is None
        else arguments.socket_path.expanduser().resolve()
    )

    if not storage_state.is_file():
        raise RuntimeError(
            f"eBay storage-state file is missing: {storage_state}"
        )

    socket_path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = socket_path.parent / "ensure.lock"
    log_path = socket_path.parent / "owner.log"

    with lock_path.open("a+") as lock_handle:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX,
        )

        existing = owner_health(socket_path)

        if existing is not None:
            if (
                existing.get("protocol_version")
                != OWNER_PROTOCOL_VERSION
            ):
                raise RuntimeError(
                    "Running eBay owner uses an incompatible protocol."
                )

            if existing.get("headless") is not False:
                raise RuntimeError(
                    "Running eBay owner is not headed."
                )

            existing_state = Path(
                str(existing.get("storage_state", ""))
            ).expanduser().resolve()

            if existing_state != storage_state:
                raise RuntimeError(
                    "Running eBay owner uses a different storage-state file: "
                    f"{existing_state}"
                )

            print_health(existing, state="reused")
            print(f"EBAY_OWNER_SOCKET={socket_path}")
            print("VISIBLE_BROWSER_LAUNCHED=false")
            print("NEW_BROWSER_PER_REFRESH=false")
            return 0

        if socket_is_connectable(socket_path):
            raise RuntimeError(
                "The eBay owner socket is occupied by an "
                "unrecognized live service."
            )

        try:
            socket_path.unlink(missing_ok=True)
        except OSError as error:
            raise RuntimeError(
                f"Could not remove stale owner socket: {socket_path}"
            ) from error

        environment = owner_process_environment()
        environment["AUCTION_EBAY_OWNER_SOCKET"] = str(socket_path)
        environment["AUCTION_LOCAL_EBAY_STATE_FILE"] = str(storage_state)

        with log_path.open("ab", buffering=0) as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(OWNER_SCRIPT),
                    "--storage-state",
                    str(storage_state),
                    "--socket-path",
                    str(socket_path),
                ],
                cwd=str(REPOSITORY_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=environment,
            )

        deadline = time.monotonic() + max(arguments.timeout_seconds, 1.0)

        while time.monotonic() < deadline:
            payload = owner_health(socket_path)

            if payload is not None:
                if (
                    payload.get("protocol_version")
                    != OWNER_PROTOCOL_VERSION
                ):
                    raise RuntimeError(
                        "Started eBay owner reported an incompatible protocol."
                    )

                if payload.get("headless") is not False:
                    raise RuntimeError(
                        "Started eBay owner is not headed."
                    )

                existing_state = Path(
                    str(payload.get("storage_state", ""))
                ).expanduser().resolve()

                if existing_state != storage_state:
                    raise RuntimeError(
                        "Started eBay owner reported the wrong storage-state."
                    )

                print_health(payload, state="started")
                print(f"EBAY_OWNER_SOCKET={socket_path}")
                print(f"EBAY_OWNER_LOG={log_path}")
                print("VISIBLE_BROWSER_LAUNCHED=false")
                print("NEW_BROWSER_PER_REFRESH=false")
                return 0

            exit_code = process.poll()

            if exit_code is not None:
                try:
                    tail = log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).splitlines()[-80:]
                except OSError:
                    tail = []

                if tail:
                    print()
                    print("--- eBay owner log ---")
                    print("\n".join(tail))

                raise RuntimeError(
                    "eBay owner exited before becoming ready "
                    f"with status {exit_code}."
                )

            time.sleep(0.25)

    raise RuntimeError(
        "Timed out waiting for the eBay owner to become ready."
    )


OWNER_SOCKET_UNRECOGNIZED_ERROR = (
    "The eBay owner socket is occupied by "
    "an unrecognized live service."
)

OWNER_SOCKET_RECOVERY_RETRIES = 20
OWNER_SOCKET_RECOVERY_DELAY_SECONDS = 0.25


def _wait_before_owner_retry() -> None:
    """Wait briefly for an unhealthy owner to finish shutting down."""

    time.sleep(OWNER_SOCKET_RECOVERY_DELAY_SECONDS)


def main() -> int:
    """Ensure the eBay owner, tolerating its bounded teardown race."""

    for retry_index in range(OWNER_SOCKET_RECOVERY_RETRIES + 1):
        try:
            return _main_once()
        except RuntimeError as error:
            if (
                str(error) != OWNER_SOCKET_UNRECOGNIZED_ERROR
                or retry_index >= OWNER_SOCKET_RECOVERY_RETRIES
            ):
                raise

            _wait_before_owner_retry()

    raise RuntimeError(
        "Timed out recovering the eBay owner socket."
    )


if __name__ == "__main__":
    raise SystemExit(main())
