"""Tests for signed Collector Ledger control-plane refresh dispatch."""

from __future__ import annotations

import uuid

import httpx
import pytest

from auction_etl.auth.context import AccountContext
from auction_etl.auth.internal_request import (
    verify_account_request_signature,
)
from auction_etl.services.control_plane_refresh import (
    ControlPlaneRefreshError,
    REFRESH_JOB_PATH,
    enqueue_refresh_via_control_plane,
    normalize_control_plane_url,
    signed_account_headers,
)

CONTROL_ORIGIN = (
    "https"
    + "://control.example"
)


@pytest.fixture
def account_context() -> AccountContext:
    """Return one deterministic authenticated account."""
    return AccountContext(
        user_id=uuid.UUID(
            "11111111-1111-4111-8111-111111111111"
        ),
        account_id=uuid.UUID(
            "22222222-2222-4222-8222-222222222222"
        ),
        role="owner",
        email="owner@example.com",
        display_name="Owner",
        is_system_admin=False,
    )


def test_signed_headers_verify(
    account_context: AccountContext,
) -> None:
    """Client headers must satisfy the canonical server HMAC contract."""
    secret = "s" * 64
    timestamp = 1_777_777_777
    request_id = "request-123"

    headers = signed_account_headers(
        signing_secret=secret,
        account_context=account_context,
        method="POST",
        path=REFRESH_JOB_PATH,
        timestamp=timestamp,
        request_id=request_id,
    )

    assert headers[
        "Authorization"
    ] == f"Bearer {secret}"

    assert headers[
        "X-Auction-Account-ID"
    ] == str(
        account_context.account_id
    )

    assert headers[
        "X-Auction-User-ID"
    ] == str(
        account_context.user_id
    )

    assert verify_account_request_signature(
        secret,
        headers[
            "X-Auction-Signature"
        ],
        timestamp=timestamp,
        request_id=request_id,
        method="POST",
        path=REFRESH_JOB_PATH,
        account_id=account_context.account_id,
        user_id=account_context.user_id,
    )


def test_enqueue_uses_signed_control_plane(
    monkeypatch: pytest.MonkeyPatch,
    account_context: AccountContext,
) -> None:
    """Refresh creation must use Vercel with no trusted body identity."""
    secret = "x" * 64
    captured: dict[str, object] = {}

    def fake_post(
        url: str,
        **kwargs: object,
    ) -> httpx.Response:
        captured[
            "url"
        ] = url

        captured.update(
            kwargs
        )

        request = httpx.Request(
            "POST",
            url,
        )

        return httpx.Response(
            202,
            request=request,
            json={
                "created": True,
                "job": {
                    "id":
                        "33333333-3333-4333-8333-333333333333",
                    "state":
                        "queued",
                    "trigger":
                        "api",
                    "message":
                        "Refresh job queued.",
                    "attempt":
                        0,
                    "marketplaces": [
                        {
                            "marketplace":
                                "buyee",
                            "state":
                                "waiting",
                        },
                        {
                            "marketplace":
                                "ebay",
                            "state":
                                "waiting",
                        },
                        {
                            "marketplace":
                                "gripsweat",
                            "state":
                                "waiting",
                        },
                    ],
                },
            },
        )

    monkeypatch.setattr(
        httpx,
        "post",
        fake_post,
    )

    status, created = (
        enqueue_refresh_via_control_plane(
            base_url=CONTROL_ORIGIN,
            signing_secret=secret,
            account_context=account_context,
        )
    )

    assert created is True
    assert status[
        "state"
    ] == "queued"
    assert status[
        "coordination_ready"
    ] is True

    assert captured[
        "url"
    ] == (
        CONTROL_ORIGIN
        + REFRESH_JOB_PATH
    )

    body = captured[
        "json"
    ]

    assert isinstance(
        body,
        dict,
    )

    assert body == {}
    assert "account_id" not in body
    assert "user_id" not in body

    headers = captured[
        "headers"
    ]

    assert isinstance(
        headers,
        dict,
    )

    assert headers[
        "X-Auction-Account-ID"
    ] == str(
        account_context.account_id
    )

    assert headers[
        "X-Auction-User-ID"
    ] == str(
        account_context.user_id
    )


def test_enqueue_rejection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    account_context: AccountContext,
) -> None:
    """A rejected signed request must not fall back to Neon."""
    def fake_post(
        url: str,
        **kwargs: object,
    ) -> httpx.Response:
        del kwargs

        request = httpx.Request(
            "POST",
            url,
        )

        return httpx.Response(
            403,
            request=request,
            json={
                "error":
                    "Signed account authorization failed.",
            },
        )

    monkeypatch.setattr(
        httpx,
        "post",
        fake_post,
    )

    with pytest.raises(
        ControlPlaneRefreshError,
        match="HTTP 403",
    ):
        enqueue_refresh_via_control_plane(
            base_url=CONTROL_ORIGIN,
            signing_secret="y" * 64,
            account_context=account_context,
        )


@pytest.mark.parametrize(
    "value",
    (
        "",
        "http" + "://control.example",
        "https" + "://user:password@control.example",
        "https" + "://control.example/api",
        "https" + "://control.example?debug=true",
    ),
)
def test_control_plane_url_rejects_unsafe_values(
    value: str,
) -> None:
    """The refresh mutation target must be one HTTPS origin."""
    with pytest.raises(
        ControlPlaneRefreshError
    ):
        normalize_control_plane_url(
            value
        )


def test_missing_signing_secret_fails_closed(
    account_context: AccountContext,
) -> None:
    """Dispatch must never silently downgrade to unsigned traffic."""
    with pytest.raises(
        ControlPlaneRefreshError,
        match="AUCTION_REFRESH_SIGNING_SECRET",
    ):
        signed_account_headers(
            signing_secret="",
            account_context=account_context,
            method="POST",
            path=REFRESH_JOB_PATH,
        )
