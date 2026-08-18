"""Local client for the long-lived Buyee browser owner."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Mapping

OWNER_PROTOCOL_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 180.0


class BuyeeOwnerError(RuntimeError):
    """Raised when the local Buyee owner cannot complete a request."""


def owner_runtime_dir() -> Path:
    """Return the runtime directory used by the Buyee owner."""

    configured = os.environ.get("AUCTION_BUYEE_OWNER_RUNTIME_DIR")

    if configured:
        return Path(configured).expanduser().resolve()

    return (
        Path.home()
        / ".auction-etl"
        / "runtime"
        / "buyee-owner"
    )


def owner_socket_path() -> Path:
    """Return the configured local Unix-domain socket path."""

    configured = os.environ.get("AUCTION_BUYEE_OWNER_SOCKET")

    if configured:
        return Path(configured).expanduser().resolve()

    return owner_runtime_dir() / "owner.sock"


def forwarded_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the small environment subset required by owner-executed jobs."""

    source = os.environ if environment is None else environment

    forwarded = {
        key: value
        for key, value in source.items()
        if key == "DATABASE_URL"
        or key.startswith("AUCTION_")
    }

    forwarded.pop("AUCTION_BUYEE_CDP_URL", None)
    forwarded.pop("AUCTION_BUYEE_OWNER_SOCKET", None)

    return forwarded


def request(
    command: str,
    *,
    payload: Mapping[str, Any] | None = None,
    socket_path: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send one high-level job to the local Buyee owner."""

    path = (
        owner_socket_path()
        if socket_path is None
        else socket_path.expanduser().resolve()
    )

    message = {
        "protocol_version": OWNER_PROTOCOL_VERSION,
        "command": command,
        "payload": dict(payload or {}),
    }

    encoded = (
        json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    try:
        with socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        ) as connection:
            connection.settimeout(
                timeout_seconds
            )
            connection.connect(
                str(path)
            )
            connection.sendall(
                encoded
            )

            response_bytes = bytearray()

            while True:
                chunk = connection.recv(
                    65_536
                )

                if not chunk:
                    break

                response_bytes.extend(
                    chunk
                )

                newline = response_bytes.find(
                    b"\n"
                )

                if newline >= 0:
                    response_bytes = response_bytes[
                        :newline
                    ]
                    break
    except (
        FileNotFoundError,
        ConnectionRefusedError,
        socket.timeout,
        OSError,
    ) as error:
        raise BuyeeOwnerError(
            f"Buyee owner is unavailable at {path}: {error}"
        ) from error

    if not response_bytes:
        raise BuyeeOwnerError(
            "Buyee owner returned an empty response."
        )

    try:
        response = json.loads(
            response_bytes.decode(
                "utf-8"
            )
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise BuyeeOwnerError(
            "Buyee owner returned invalid JSON."
        ) from error

    if not isinstance(
        response,
        dict,
    ):
        raise BuyeeOwnerError(
            "Buyee owner response is not an object."
        )

    if not response.get(
        "ok",
        False,
    ):
        error_message = str(
            response.get(
                "error",
                "Buyee owner job failed.",
            )
        )
        raise BuyeeOwnerError(
            error_message
        )

    return response


def health(
    *,
    socket_path: Path | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Return owner health metadata."""

    return request(
        "health",
        socket_path=socket_path,
        timeout_seconds=timeout_seconds,
    )


def run_job(
    command: str,
    *,
    arguments: list[str],
    environment: Mapping[str, str] | None = None,
    socket_path: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one owner-executed Buyee command."""

    return request(
        command,
        payload={
            "arguments": list(
                arguments
            ),
            "environment": (
                forwarded_environment(
                    environment
                )
            ),
        },
        socket_path=socket_path,
        timeout_seconds=timeout_seconds,
    )
