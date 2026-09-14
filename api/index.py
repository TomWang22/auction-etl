"""Database-free Vercel compatibility shell for Collector Ledger."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

from auction_etl.runtime_authority import (
    DATA_AUTHORITY,
    LOCAL_DATABASE_TARGET,
)


_ROUTE_PARAMETER = "__auction_path"


def _logical_path(
    scope: dict[str, Any],
) -> str:
    """Return the logical API path after the Vercel wildcard rewrite."""

    path = str(
        scope.get(
            "path",
            "/",
        )
    )

    raw_query = scope.get(
        "query_string",
        b"",
    )

    if isinstance(
        raw_query,
        bytes,
    ):
        query_text = raw_query.decode(
            "utf-8",
            errors="replace",
        )
    else:
        query_text = str(
            raw_query
        )

    for key, value in parse_qsl(
        query_text,
        keep_blank_values=True,
    ):
        if key != _ROUTE_PARAMETER:
            continue

        suffix = value.strip(
            "/"
        )

        return (
            "/api"
            if not suffix
            else f"/api/{suffix}"
        )

    normalized = path.rstrip(
        "/"
    )

    return normalized or "/"


async def _respond(
    send,
    status: int,
    payload: dict[str, Any],
) -> None:
    """Send one JSON ASGI response."""

    body = json.dumps(
        payload,
        separators=(
            ",",
            ":",
        ),
        sort_keys=True,
    ).encode(
        "utf-8"
    )

    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (
                    b"content-type",
                    b"application/json; charset=utf-8",
                ),
                (
                    b"cache-control",
                    b"no-store",
                ),
                (
                    b"content-length",
                    str(
                        len(body)
                    ).encode(
                        "ascii"
                    ),
                ),
            ],
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )


async def app(
    scope: dict[str, Any],
    receive,
    send,
) -> None:
    """Expose only non-database cloud cutover status."""

    del receive

    if scope.get(
        "type"
    ) != "http":
        return

    method = str(
        scope.get(
            "method",
            "GET",
        )
    ).upper()

    path = _logical_path(
        scope
    )

    if (
        method == "GET"
        and path == "/api/health"
    ):
        await _respond(
            send,
            200,
            {
                "status": "ok",
                "service": "collector-ledger-cloud-shell",
                "data_authority": DATA_AUTHORITY,
                "local_database_target": LOCAL_DATABASE_TARGET,
                "cloud_database_access": False,
                "refresh_dispatch": False,
            },
        )
        return

    if (
        method == "GET"
        and path == "/api/readiness"
    ):
        await _respond(
            send,
            503,
            {
                "status": "disabled",
                "reason": "local-postgresql-authoritative",
                "data_authority": DATA_AUTHORITY,
                "cloud_database_access": False,
                "refresh_dispatch": False,
            },
        )
        return

    if (
        path == "/api/refresh-jobs"
        or path.startswith(
            "/api/refresh-jobs/"
        )
    ):
        await _respond(
            send,
            410,
            {
                "error": "Cloud refresh coordination is retired.",
                "data_authority": DATA_AUTHORITY,
                "cloud_database_access": False,
                "refresh_dispatch": False,
            },
        )
        return

    await _respond(
        send,
        404,
        {
            "error": "Not found.",
            "data_authority": DATA_AUTHORITY,
        },
    )


__all__ = [
    "app",
]
