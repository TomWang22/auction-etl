"""Vercel-compatible control-plane contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from auction_etl.cloud_api import app


ROOT = Path(__file__).resolve().parents[1]

ASGI = ROOT / "asgi.py"
CONTROL = (
    ROOT
    / "auction_etl"
    / "cloud_api.py"
)


def run_request(
    *,
    path: str,
    method: str = "GET",
    headers: list[
        tuple[bytes, bytes]
    ] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, object]]:
    """Run one in-process ASGI request."""
    messages: list[
        dict[str, object]
    ] = []

    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered

        if delivered:
            return {
                "type": "http.disconnect"
            }

        delivered = True

        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    async def send(
        message: dict[str, object],
    ) -> None:
        messages.append(
            message
        )

    asyncio.run(
        app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": (
                    headers
                    or []
                ),
            },
            receive,
            send,
        )
    )

    start = next(
        message
        for message in messages
        if message["type"]
        == "http.response.start"
    )

    response = next(
        message
        for message in messages
        if message["type"]
        == "http.response.body"
    )

    return (
        int(
            start["status"]
        ),
        json.loads(
            bytes(
                response["body"]
            ).decode(
                "utf-8"
            )
        ),
    )


def test_asgi_entrypoint_exports_control_plane() -> None:
    """Vercel discovers one supported ASGI entrypoint."""
    source = ASGI.read_text(
        encoding="utf-8"
    )

    assert (
        "from auction_etl.cloud_api import app"
        in source
    )


def test_control_plane_exposes_required_routes() -> None:
    """The Vercel surface contains the Phase-B API contract."""
    source = CONTROL.read_text(
        encoding="utf-8"
    )

    for route in (
        "/api/health",
        "/api/readiness",
        "/api/refresh-jobs",
        "/api/refresh-jobs/latest",
    ):
        assert route in source

    assert "create_refresh_job" in source
    assert "get_refresh_job" in source
    assert "get_latest_refresh_job" in source


def test_health_does_not_require_database_access() -> None:
    """Liveness remains available even before managed DB configuration."""
    status, payload = run_request(
        path="/api/health"
    )

    assert status == 200
    assert payload["status"] == "ok"


def test_production_dispatch_requires_a_secret(
    monkeypatch,
) -> None:
    """Production cannot enqueue anonymously when no secret is configured."""
    monkeypatch.setenv(
        "AUCTION_ENV",
        "production",
    )
    monkeypatch.setenv(
        "AUCTION_REFRESH_ENABLED",
        "true",
    )
    monkeypatch.delenv(
        "AUCTION_REFRESH_SIGNING_SECRET",
        raising=False,
    )

    status, payload = run_request(
        path="/api/refresh-jobs",
        method="POST",
        body=b"{}",
    )

    assert status == 503
    assert (
        "AUCTION_REFRESH_SIGNING_SECRET"
        in str(
            payload["error"]
        )
    )
