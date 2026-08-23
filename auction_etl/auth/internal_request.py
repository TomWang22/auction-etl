"""Signing helpers for authenticated internal account requests."""

from __future__ import annotations

import hashlib
import hmac
import uuid


SIGNATURE_VERSION = "collector-ledger-account-request/v1"


def normalize_request_path(path: str) -> str:
    """Return the canonical request path used for signing."""
    normalized = str(path or "/").strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized.rstrip("/") or "/"


def canonical_account_request(
    *,
    timestamp: int,
    request_id: str,
    method: str,
    path: str,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
) -> bytes:
    """Build the exact byte sequence signed by internal account requests."""
    bounded_request_id = str(request_id).strip()
    if (
        not bounded_request_id
        or len(bounded_request_id) > 128
        or "\n" in bounded_request_id
        or "\r" in bounded_request_id
    ):
        raise ValueError(
            "request_id must be non-empty, single-line, and <= 128 chars."
        )

    account_uuid = uuid.UUID(str(account_id))
    user_uuid = uuid.UUID(str(user_id))

    canonical = "\n".join(
        (
            SIGNATURE_VERSION,
            str(int(timestamp)),
            bounded_request_id,
            str(method or "GET").upper(),
            normalize_request_path(path),
            str(account_uuid),
            str(user_uuid),
        )
    )
    return canonical.encode("utf-8")


def sign_account_request(
    secret: str,
    *,
    timestamp: int,
    request_id: str,
    method: str,
    path: str,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
) -> str:
    """Sign one server-to-server account request."""
    signing_secret = str(secret).strip()
    if not signing_secret:
        raise ValueError("A non-empty signing secret is required.")

    canonical = canonical_account_request(
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path=path,
        account_id=account_id,
        user_id=user_id,
    )
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    return f"v1={digest}"


def verify_account_request_signature(
    secret: str,
    supplied_signature: str,
    *,
    timestamp: int,
    request_id: str,
    method: str,
    path: str,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
) -> bool:
    """Verify one server-to-server account request signature."""
    try:
        expected = sign_account_request(
            secret,
            timestamp=timestamp,
            request_id=request_id,
            method=method,
            path=path,
            account_id=account_id,
            user_id=user_id,
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(
        str(supplied_signature),
        expected,
    )
