"""Regression coverage for the local-authority cutover."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from api.index import app as vercel_app
from auction_etl import cloud_api
from auction_etl.runtime_authority import (
    DATA_AUTHORITY,
    LOCAL_DATABASE_TARGET,
    cloud_runtime_detected,
)
from auction_etl.services.refresh_jobs import (
    RefreshCoordinationUnavailable,
)
from scripts import run_cloud_refresh_worker


def invoke_vercel_app(
    path: str,
    *,
    method: str = "GET",
    query_string: str = "",
) -> tuple[int, dict[str, Any]]:
    """Invoke the Vercel ASGI shell without an HTTP server."""

    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    async def send(
        message: dict[str, Any],
    ) -> None:
        messages.append(
            message
        )

    async def run() -> None:
        await vercel_app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "raw_path": path.encode(
                    "utf-8"
                ),
                "query_string": query_string.encode(
                    "utf-8"
                ),
                "headers": [],
            },
            receive,
            send,
        )

    asyncio.run(
        run()
    )

    start = next(
        message
        for message in messages
        if message.get(
            "type"
        ) == "http.response.start"
    )

    body = b"".join(
        message.get(
            "body",
            b"",
        )
        for message in messages
        if message.get(
            "type"
        ) == "http.response.body"
    )

    return (
        int(
            start["status"]
        ),
        json.loads(
            body.decode(
                "utf-8"
            )
        ),
    )


def test_source_authority_is_local() -> None:
    """The cutover must require a source edit to restore cloud authority."""

    assert DATA_AUTHORITY == "local"
    assert (
        LOCAL_DATABASE_TARGET
        == "127.0.0.1:5544/auction_warehouse"
    )


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, False),
        ({"VERCEL": "1"}, True),
        ({"VERCEL_ENV": "production"}, True),
        ({"RAILWAY_DEPLOYMENT_ID": "deployment-id"}, True),
        ({"RAILWAY_ENVIRONMENT_ID": "environment-id"}, True),
    ],
)
def test_cloud_runtime_detection(
    environment: dict[str, str],
    expected: bool,
) -> None:
    """Recognize the cloud hosts that must not own the database."""

    assert (
        cloud_runtime_detected(
            environment
        )
        is expected
    )


def test_vercel_health_is_database_free() -> None:
    """Vercel health reports local authority without touching PostgreSQL."""

    status, payload = invoke_vercel_app(
        "/api/health"
    )

    assert status == 200
    assert payload["data_authority"] == "local"
    assert payload["cloud_database_access"] is False
    assert payload["refresh_dispatch"] is False


def test_vercel_rewrite_health_is_database_free() -> None:
    """The existing wildcard rewrite resolves to the same safe health route."""

    status, payload = invoke_vercel_app(
        "/api",
        query_string="__auction_path=health",
    )

    assert status == 200
    assert payload["data_authority"] == "local"


def test_vercel_readiness_refuses_cloud_database() -> None:
    """Readiness must not imply that a cloud data plane exists."""

    status, payload = invoke_vercel_app(
        "/api/readiness"
    )

    assert status == 503
    assert payload["cloud_database_access"] is False


def test_vercel_refresh_dispatch_is_retired() -> None:
    """Cloud refresh creation is gone after local authority cutover."""

    status, payload = invoke_vercel_app(
        "/api/refresh-jobs",
        method="POST",
    )

    assert status == 410
    assert payload["refresh_dispatch"] is False


def test_legacy_cloud_api_refuses_vercel_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even direct legacy API mounting must fail before database use."""

    monkeypatch.setenv(
        "VERCEL",
        "1",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://should-not-connect.invalid/auction_warehouse",
    )

    with pytest.raises(
        RefreshCoordinationUnavailable,
        match="Cloud database access is disabled",
    ):
        cloud_api._database_url()


def test_cloud_worker_refuses_railway_before_argument_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Railway must not enter the durable cloud worker loop."""

    monkeypatch.setenv(
        "RAILWAY_DEPLOYMENT_ID",
        "deployment-id",
    )

    def forbidden_parse_args(
        argv,
    ):
        del argv

        pytest.fail(
            "Cloud worker parsed arguments after the Railway cutover guard."
        )

    monkeypatch.setattr(
        run_cloud_refresh_worker,
        "parse_args",
        forbidden_parse_args,
    )

    assert (
        run_cloud_refresh_worker.main(
            []
        )
        == 3
    )
