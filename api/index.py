"""Vercel file-based ASGI entrypoint for Auction ETL."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode

from auction_etl.cloud_api import app as control_plane_app


_ROUTE_PARAMETER = "__auction_path"


async def app(
    scope: dict[str, Any],
    receive,
    send,
) -> None:
    """Forward rewritten Vercel API paths into the control plane."""
    if scope.get("type") != "http":
        await control_plane_app(
            scope,
            receive,
            send,
        )
        return

    routed_scope = dict(scope)

    raw_query = scope.get(
        "query_string",
        b"",
    )

    if isinstance(raw_query, bytes):
        query_text = raw_query.decode(
            "utf-8",
            errors="replace",
        )
    else:
        query_text = str(raw_query)

    pairs = parse_qsl(
        query_text,
        keep_blank_values=True,
    )

    routed_path: str | None = None
    forwarded_pairs: list[tuple[str, str]] = []

    for key, value in pairs:
        if key == _ROUTE_PARAMETER:
            routed_path = value
        else:
            forwarded_pairs.append(
                (
                    key,
                    value,
                )
            )

    if routed_path is not None:
        suffix = routed_path.strip("/")

        path = (
            "/api"
            if not suffix
            else f"/api/{suffix}"
        )

        routed_scope["path"] = path
        routed_scope["raw_path"] = path.encode(
            "utf-8"
        )
        routed_scope["query_string"] = urlencode(
            forwarded_pairs,
            doseq=True,
        ).encode(
            "utf-8"
        )

    await control_plane_app(
        routed_scope,
        receive,
        send,
    )


__all__ = [
    "app",
]
