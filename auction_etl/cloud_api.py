"""Minimal ASGI control plane for durable marketplace refresh jobs."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, text

from auction_etl.auth.context import AccountContext
from auction_etl.auth.internal_request import verify_account_request_signature
from auction_etl.services.refresh_job_inputs import (
    MAX_REFRESH_REQUEST_BYTES,
    validate_structured_ebay_input,
)
from auction_etl.services.refresh_jobs import (
    RefreshCoordinationUnavailable,
    RefreshJobNotFound,
    build_refresh_engine,
    coordination_schema_ready,
    create_refresh_job,
    get_latest_refresh_job,
    get_refresh_job,
)

_JOB_PATH = re.compile(
    r"^/api/refresh-jobs/"
    r"(?P<job_id>[0-9a-fA-F-]{36})/?$"
)


def _environment() -> str:
    """Return the normalized deployment environment."""
    return (
        os.environ.get(
            "AUCTION_ENV"
        )
        or os.environ.get(
            "VERCEL_ENV"
        )
        or "development"
    ).strip().casefold()


def _database_url() -> str:
    """Return the configured control-plane database URL."""
    value = os.environ.get(
        "DATABASE_URL",
        "",
    ).strip()

    if not value:
        raise RefreshCoordinationUnavailable(
            "DATABASE_URL is required."
        )

    return value


@lru_cache(maxsize=1)
def _engine() -> Engine:
    """Return the process-local SQLAlchemy engine."""
    return build_refresh_engine(
        _database_url()
    )


def _headers(
    scope: dict[str, Any],
) -> dict[str, str]:
    """Return lowercase HTTP headers."""
    result: dict[str, str] = {}

    for raw_key, raw_value in scope.get(
        "headers",
        [],
    ):
        key = raw_key.decode(
            "latin-1"
        ).casefold()

        result[key] = raw_value.decode(
            "latin-1"
        )

    return result


def _authorized(
    scope: dict[str, Any],
) -> tuple[bool, str | None]:
    """Validate the optional refresh bearer secret."""
    secret = os.environ.get(
        "AUCTION_REFRESH_SIGNING_SECRET",
        "",
    ).strip()

    if not secret:
        if _environment() == "production":
            return (
                False,
                (
                    "AUCTION_REFRESH_SIGNING_SECRET "
                    "is required in production."
                ),
            )

        return (
            True,
            None,
        )

    authorization = _headers(
        scope
    ).get(
        "authorization",
        "",
    )

    expected = (
        "Bearer "
        + secret
    )

    import hmac

    if not hmac.compare_digest(
        authorization,
        expected,
    ):
        return (
            False,
            "Bearer authorization failed.",
        )

    return (
        True,
        None,
    )


def _account_auth_secret() -> str:
    """Return the internal account-request signing secret."""
    secret = os.environ.get(
        "AUCTION_REFRESH_SIGNING_SECRET",
        "",
    ).strip()

    if not secret:
        raise RefreshCoordinationUnavailable(
            "AUCTION_REFRESH_SIGNING_SECRET is required "
            "for account-owned refresh endpoints."
        )

    return secret


def _signed_account_context(
    scope: dict[str, Any],
) -> AccountContext:
    """Verify signed server identity and authoritative account membership."""
    _account_auth_secret()
    authorized, reason = _authorized(scope)

    if not authorized:
        raise PermissionError(reason or "Bearer authorization failed.")

    headers = _headers(scope)

    account_text = headers.get(
        "x-auction-account-id",
        "",
    ).strip()
    user_text = headers.get(
        "x-auction-user-id",
        "",
    ).strip()
    timestamp_text = headers.get(
        "x-auction-timestamp",
        "",
    ).strip()
    request_id = headers.get(
        "x-auction-request-id",
        "",
    ).strip()
    supplied_signature = headers.get(
        "x-auction-signature",
        "",
    ).strip()

    try:
        account_id = uuid.UUID(account_text)
        user_id = uuid.UUID(user_text)
    except ValueError as exc:
        raise PermissionError(
            "Signed account/user identity headers are invalid."
        ) from exc

    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise PermissionError(
            "X-Auction-Timestamp must be Unix epoch seconds."
        ) from exc

    if abs(int(time.time()) - timestamp) > 300:
        raise PermissionError(
            "Signed account request timestamp is outside the 5-minute window."
        )

    if (
        not request_id
        or len(request_id) > 128
        or "\n" in request_id
        or "\r" in request_id
    ):
        raise PermissionError(
            "X-Auction-Request-ID is required and must be bounded."
        )

    method = str(scope.get("method", "GET")).upper()
    path = str(scope.get("path", "/"))

    if not verify_account_request_signature(
        _account_auth_secret(),
        supplied_signature,
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path=path,
        account_id=account_id,
        user_id=user_id,
    ):
        raise PermissionError(
            "Signed account authorization failed."
        )

    with _engine().connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    member.account_id,
                    app_user.id AS user_id,
                    member.role,
                    app_user.email,
                    app_user.display_name,
                    app_user.is_system_admin
                FROM identity.account_member AS member
                JOIN identity.app_user AS app_user
                  ON app_user.id = member.user_id
                WHERE member.account_id = :account_id
                  AND member.user_id = :user_id
                """
            ),
            {
                "account_id": account_id,
                "user_id": user_id,
            },
        ).mappings().one_or_none()

    if row is None:
        raise PermissionError(
            "Authenticated user is not a member of the requested account."
        )

    return AccountContext(
        user_id=row["user_id"],
        account_id=row["account_id"],
        role=str(row["role"]),
        email=str(row["email"]),
        display_name=str(row["display_name"] or ""),
        is_system_admin=bool(row["is_system_admin"]),
    )


def _audit_requested_by(context: AccountContext) -> str:
    """Return a bounded server-derived audit label."""
    label = context.email or context.display_name or str(context.user_id)
    return label[:200]



def _refresh_enabled() -> bool:
    """Return whether refresh-job creation is enabled."""
    value = os.environ.get(
        "AUCTION_REFRESH_ENABLED",
        "false",
    ).strip().casefold()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def _json_safe(
    value: Any,
) -> Any:
    """Recursively convert database values into JSON-safe values."""
    if value is None:
        return None

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        uuid.UUID,
    ):
        return str(
            value
        )

    if hasattr(
        value,
        "isoformat",
    ):
        try:
            return value.isoformat()
        except Exception:
            pass

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key):
                _json_safe(
                    item
                )
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (list, tuple),
    ):
        return [
            _json_safe(
                item
            )
            for item in value
        ]

    return str(
        value
    )


async def _request_json(
    receive,
) -> dict[str, Any]:
    """Read one bounded JSON request body."""
    body = bytearray()
    more_body = True

    while more_body:
        message = await receive()

        if message.get(
            "type"
        ) != "http.request":
            continue

        body.extend(
            message.get(
                "body",
                b"",
            )
        )

        if len(body) > MAX_REFRESH_REQUEST_BYTES:
            raise ValueError(
                "Request body exceeds 512 KiB."
            )

        more_body = bool(
            message.get(
                "more_body",
                False,
            )
        )

    if not body:
        return {}

    try:
        value = json.loads(
            body.decode(
                "utf-8"
            )
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            "Request body must be a JSON object."
        ) from exc

    if not isinstance(
        value,
        dict,
    ):
        raise ValueError(
            "Request body must be a JSON object."
        )

    return value


async def _respond(
    send,
    status: int,
    payload: dict[str, Any],
    *,
    headers: list[
        tuple[bytes, bytes]
    ] | None = None,
) -> None:
    """Send one JSON ASGI response."""
    body = json.dumps(
        _json_safe(
            payload
        ),
        separators=(
            ",",
            ":",
        ),
        sort_keys=True,
    ).encode(
        "utf-8"
    )

    response_headers = [
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
    ]

    if headers:
        response_headers.extend(
            headers
        )

    await send(
        {
            "type":
                "http.response.start",
            "status":
                status,
            "headers":
                response_headers,
        }
    )

    await send(
        {
            "type":
                "http.response.body",
            "body":
                body,
        }
    )


def _requested_by(
    scope: dict[str, Any],
    body: dict[str, Any],
) -> str | None:
    """Return one bounded request attribution string."""
    value = body.get(
        "requested_by"
    )

    if value is None:
        value = _headers(
            scope
        ).get(
            "x-auction-user"
        )

    if value is None:
        return None

    result = str(
        value
    ).strip()

    if not result:
        return None

    if len(result) > 200:
        raise ValueError(
            "requested_by cannot exceed 200 characters."
        )

    return result


def _source_commit(
    body: dict[str, Any],
) -> str | None:
    """Return the immutable source commit recorded on a job."""
    deployment_commit = os.environ.get(
        "VERCEL_GIT_COMMIT_SHA",
        "",
    ).strip()

    if deployment_commit:
        return deployment_commit

    value = body.get(
        "source_commit"
    )

    if value is None:
        return None

    result = str(
        value
    ).strip()

    if not result:
        return None

    if len(result) > 100:
        raise ValueError(
            "source_commit cannot exceed 100 characters."
        )

    return result


async def _health(
    send,
) -> None:
    """Serve process-level health."""
    await _respond(
        send,
        200,
        {
            "status":
                "ok",
            "service":
                "auction-etl-control-plane",
        },
    )


async def _readiness(
    send,
) -> None:
    """Serve database and durable-schema readiness."""
    try:
        engine = _engine()

        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT 1"
                )
            ).scalar_one()

        schema_ready = (
            coordination_schema_ready(
                engine
            )
        )
    except Exception as exc:
        await _respond(
            send,
            503,
            {
                "status":
                    "not-ready",
                "database":
                    False,
                "coordination_schema":
                    False,
                "error":
                    str(exc),
            },
        )
        return

    if not schema_ready:
        await _respond(
            send,
            503,
            {
                "status":
                    "not-ready",
                "database":
                    True,
                "coordination_schema":
                    False,
            },
        )
        return

    await _respond(
        send,
        200,
        {
            "status":
                "ready",
            "database":
                True,
            "coordination_schema":
                True,
            "refresh_enabled":
                _refresh_enabled(),
        },
    )


async def _create_job(
    scope: dict[str, Any],
    receive,
    send,
) -> None:
    """Queue one account-owned durable refresh job."""
    if not _refresh_enabled():
        await _respond(
            send,
            503,
            {"error": "Refresh dispatch is disabled."},
        )
        return

    try:
        body = await _request_json(receive)

        if "account_id" in body or "user_id" in body:
            raise ValueError(
                "account_id/user_id are derived from signed server context."
            )

        context = _signed_account_context(scope)

        job, created = create_refresh_job(
            _engine(),
            account_id=context.account_id,
            requested_by_user_id=context.user_id,
            requested_by=_audit_requested_by(context),
            source_commit=_source_commit(body),
            trigger="api",
            ebay_input=(
                validate_structured_ebay_input(
                    body["ebay_input"]
                )
                if "ebay_input" in body
                else None
            ),
        )
    except PermissionError as exc:
        await _respond(
            send,
            403,
            {"error": str(exc)},
        )
        return
    except ValueError as exc:
        await _respond(
            send,
            400,
            {"error": str(exc)},
        )
        return
    except RefreshCoordinationUnavailable as exc:
        await _respond(
            send,
            503,
            {"error": str(exc)},
        )
        return
    except Exception as exc:
        await _respond(
            send,
            503,
            {
                "error": "Durable refresh dispatch failed.",
                "detail": str(exc),
            },
        )
        return

    await _respond(
        send,
        202 if created else 200,
        {
            "created": created,
            "job": job,
        },
    )



async def _latest_job(
    scope: dict[str, Any],
    send,
) -> None:
    """Return the caller account's most recent durable refresh job."""
    try:
        context = _signed_account_context(scope)
        job = get_latest_refresh_job(
            _engine(),
            account_id=context.account_id,
            include_events=True,
        )
    except PermissionError as exc:
        await _respond(send, 403, {"error": str(exc)})
        return
    except RefreshCoordinationUnavailable as exc:
        await _respond(send, 503, {"error": str(exc)})
        return
    except Exception as exc:
        await _respond(
            send,
            503,
            {
                "error": "Durable refresh status failed.",
                "detail": str(exc),
            },
        )
        return

    if job is None:
        await _respond(
            send,
            404,
            {"error": "No refresh job exists for this account."},
        )
        return

    await _respond(send, 200, {"job": job})



async def _job_by_id(
    scope: dict[str, Any],
    send,
    job_id: str,
) -> None:
    """Return one durable job only when it belongs to the caller account."""
    try:
        context = _signed_account_context(scope)
        job = get_refresh_job(
            _engine(),
            job_id,
            account_id=context.account_id,
            include_events=True,
        )
    except PermissionError as exc:
        await _respond(send, 403, {"error": str(exc)})
        return
    except (ValueError, RefreshJobNotFound) as exc:
        await _respond(send, 404, {"error": str(exc)})
        return
    except RefreshCoordinationUnavailable as exc:
        await _respond(send, 503, {"error": str(exc)})
        return
    except Exception as exc:
        await _respond(
            send,
            503,
            {
                "error": "Durable refresh status failed.",
                "detail": str(exc),
            },
        )
        return

    await _respond(send, 200, {"job": job})



async def app(
    scope: dict[str, Any],
    receive,
    send,
) -> None:
    """Route the Vercel-compatible Auction ETL ASGI control plane."""
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

    path = str(
        scope.get(
            "path",
            "/",
        )
    ).rstrip(
        "/"
    )

    if not path:
        path = "/"

    if (
        method == "GET"
        and path == "/api/health"
    ):
        await _health(
            send
        )
        return

    if (
        method == "GET"
        and path == "/api/readiness"
    ):
        await _readiness(
            send
        )
        return

    if (
        method == "POST"
        and path == "/api/refresh-jobs"
    ):
        await _create_job(
            scope,
            receive,
            send,
        )
        return

    if (
        method == "GET"
        and path == "/api/refresh-jobs/latest"
    ):
        await _latest_job(
            scope,
            send,
        )
        return

    match = _JOB_PATH.fullmatch(
        path
    )

    if (
        method == "GET"
        and match is not None
    ):
        await _job_by_id(
            scope,
            send,
            match.group(
                "job_id"
            ),
        )
        return

    if path.startswith(
        "/api/"
    ):
        await _respond(
            send,
            404,
            {
                "error":
                    "API route not found.",
            },
        )
        return

    await _respond(
        send,
        404,
        {
            "error":
                "Not found.",
        },
    )
