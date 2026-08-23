"""Signed client for account-owned Vercel refresh dispatch."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from auction_etl.auth.context import AccountContext
from auction_etl.auth.internal_request import sign_account_request
from auction_etl.services.refresh_jobs import refresh_job_to_ui_status

REFRESH_JOB_PATH = "/api/refresh-jobs"
DEFAULT_TIMEOUT_SECONDS = 20.0


class ControlPlaneRefreshError(RuntimeError):
    """Raised when signed control-plane refresh dispatch fails."""


def normalize_control_plane_url(value: str) -> str:
    """Validate and normalize one HTTPS control-plane origin."""
    base_url = str(value or "").strip().rstrip("/")

    if not base_url:
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL is not configured."
        )

    parsed = urlsplit(base_url)

    if parsed.scheme.casefold() != "https":
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL must use HTTPS."
        )

    if not parsed.hostname:
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL has no hostname."
        )

    if parsed.username is not None or parsed.password is not None:
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL must not contain credentials."
        )

    if parsed.query or parsed.fragment:
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL must not contain "
            "a query string or fragment."
        )

    if parsed.path not in {"", "/"}:
        raise ControlPlaneRefreshError(
            "AUCTION_CONTROL_PLANE_URL must be an origin, "
            "not an API path."
        )

    return base_url


def require_signing_secret(value: str) -> str:
    """Return the server-to-server refresh signing secret."""
    secret = str(value or "").strip()

    if not secret:
        raise ControlPlaneRefreshError(
            "AUCTION_REFRESH_SIGNING_SECRET is not configured."
        )

    if len(secret) < 32:
        raise ControlPlaneRefreshError(
            "AUCTION_REFRESH_SIGNING_SECRET is unexpectedly short."
        )

    return secret


def signed_account_headers(
    *,
    signing_secret: str,
    account_context: AccountContext,
    method: str,
    path: str,
    timestamp: int | None = None,
    request_id: str | None = None,
) -> dict[str, str]:
    """Build bearer and canonical HMAC account-request headers."""
    secret = require_signing_secret(
        signing_secret
    )

    request_timestamp = (
        int(time.time())
        if timestamp is None
        else int(timestamp)
    )

    bounded_request_id = (
        str(uuid.uuid4())
        if request_id is None
        else str(request_id).strip()
    )

    signature = sign_account_request(
        secret,
        timestamp=request_timestamp,
        request_id=bounded_request_id,
        method=method,
        path=path,
        account_id=account_context.account_id,
        user_id=account_context.user_id,
    )

    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "X-Auction-Account-ID": str(
            account_context.account_id
        ),
        "X-Auction-User-ID": str(
            account_context.user_id
        ),
        "X-Auction-Timestamp": str(
            request_timestamp
        ),
        "X-Auction-Request-ID": bounded_request_id,
        "X-Auction-Signature": signature,
    }


def _json_object(
    response: httpx.Response,
) -> dict[str, Any]:
    """Decode one JSON-object control-plane response."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise ControlPlaneRefreshError(
            "The Vercel control plane returned invalid JSON "
            f"(HTTP {response.status_code})."
        ) from exc

    if not isinstance(payload, dict):
        raise ControlPlaneRefreshError(
            "The Vercel control plane returned an unexpected "
            f"JSON type (HTTP {response.status_code})."
        )

    return payload


def _error_detail(
    payload: Mapping[str, Any],
) -> str:
    """Return a bounded server error suitable for the UI."""
    for key in (
        "error",
        "detail",
        "message",
    ):
        value = payload.get(
            key
        )

        if value is None:
            continue

        text = str(
            value
        ).strip()

        if text:
            return text[:500]

    return "No server error detail was returned."


def enqueue_refresh_via_control_plane(
    *,
    base_url: str,
    signing_secret: str,
    account_context: AccountContext,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], bool]:
    """Create or reuse an account-owned refresh through Vercel."""
    control_plane_url = normalize_control_plane_url(
        base_url
    )

    headers = signed_account_headers(
        signing_secret=signing_secret,
        account_context=account_context,
        method="POST",
        path=REFRESH_JOB_PATH,
    )

    url = (
        control_plane_url
        + REFRESH_JOB_PATH
    )

    try:
        response = httpx.post(
            url,
            headers=headers,
            json={},
            timeout=float(
                timeout_seconds
            ),
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise ControlPlaneRefreshError(
            "Could not reach the Vercel refresh control plane."
        ) from exc

    payload = _json_object(
        response
    )

    if response.status_code not in {
        200,
        202,
    }:
        raise ControlPlaneRefreshError(
            "Vercel refresh dispatch failed "
            f"(HTTP {response.status_code}): "
            f"{_error_detail(payload)}"
        )

    created = payload.get(
        "created"
    )

    if not isinstance(
        created,
        bool,
    ):
        raise ControlPlaneRefreshError(
            "Vercel refresh response is missing a boolean "
            "'created' field."
        )

    job = payload.get(
        "job"
    )

    if not isinstance(
        job,
        Mapping,
    ):
        raise ControlPlaneRefreshError(
            "Vercel refresh response is missing the durable job."
        )

    status = refresh_job_to_ui_status(
        job
    )

    status[
        "coordination_ready"
    ] = True

    return (
        status,
        created,
    )
