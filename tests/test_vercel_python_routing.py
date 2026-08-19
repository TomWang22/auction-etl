"""Vercel Python routing contract tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from api.index import app


ROOT = Path(__file__).resolve().parents[1]


async def _request(
    *,
    path: str,
) -> tuple[int, dict[str, object]]:
    messages: list[dict[str, object]] = []

    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent

        if request_sent:
            return {
                "type": "http.disconnect",
            }

        request_sent = True

        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    async def send(
        message: dict[str, object],
    ) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api",
        "raw_path": b"/api",
        "query_string": (
            f"__auction_path={path}"
        ).encode(
            "utf-8"
        ),
        "headers": [],
    }

    await app(
        scope,
        receive,
        send,
    )

    start = next(
        message
        for message in messages
        if message["type"]
        == "http.response.start"
    )

    body_message = next(
        message
        for message in messages
        if message["type"]
        == "http.response.body"
    )

    body = json.loads(
        bytes(
            body_message["body"]
        ).decode(
            "utf-8"
        )
    )

    return (
        int(
            start["status"]
        ),
        body,
    )


def test_vercel_health_rewrite_reaches_control_plane() -> None:
    """The Vercel catch-all must preserve the logical API path."""
    status, payload = asyncio.run(
        _request(
            path="health",
        )
    )

    assert status == 200
    assert payload == {
        "service": "auction-etl-control-plane",
        "status": "ok",
    }


def test_vercel_configuration_routes_api_to_python_function() -> None:
    """All API paths must enter the file-based Python function."""
    configuration = json.loads(
        (
            ROOT
            / "vercel.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert configuration["rewrites"] == [
        {
            "source": "/api/:path*",
            "destination": "/api?__auction_path=:path*",
        }
    ]
