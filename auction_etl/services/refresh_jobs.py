"""Durable PostgreSQL coordination for marketplace refresh jobs."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

MARKETPLACES: tuple[tuple[str, int], ...] = (
    ("buyee", 1),
    ("ebay", 2),
    ("gripsweat", 3),
)

JOB_STATES = frozenset(
    {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    }
)

MARKETPLACE_STATES = frozenset(
    {
        "waiting",
        "running",
        "done",
        "failed",
        "skipped",
    }
)

ACTIVE_JOB_STATES = frozenset(
    {
        "queued",
        "running",
    }
)

COUNTER_FIELDS = (
    "discovered",
    "already_known",
    "new_count",
    "detail_scraped",
    "detail_skipped",
    "discovery_pages",
    "consecutive_known_at_stop",
)

_COORDINATION_LOCK_KEY = 6_742_026_081_800_001


class RefreshCoordinationError(RuntimeError):
    """Base error for durable refresh coordination."""


class RefreshCoordinationUnavailable(RefreshCoordinationError):
    """Raised when the durable operational schema is unavailable."""


class RefreshJobNotFound(RefreshCoordinationError):
    """Raised when a refresh job does not exist."""


class RefreshLeaseLost(RefreshCoordinationError):
    """Raised when a worker no longer owns a running refresh job."""


def normalize_database_url(value: str) -> str:
    """Normalize PostgreSQL URLs for SQLAlchemy's Psycopg 3 dialect."""
    database_url = value.strip()

    if not database_url:
        raise ValueError(
            "A PostgreSQL database URL is required."
        )

    if database_url.startswith(
        "postgresql://"
    ):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return database_url


def build_refresh_engine(
    database_url: str,
) -> Engine:
    """Create the engine used by durable refresh coordination."""
    return create_engine(
        normalize_database_url(
            database_url
        ),
        pool_pre_ping=True,
        future=True,
    )


def _dictionary(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a plain dictionary from a SQLAlchemy mapping row."""
    return {
        str(key): value
        for key, value in row.items()
    }


def _job_uuid(
    value: str | uuid.UUID,
) -> uuid.UUID:
    """Return one validated refresh-job UUID."""
    if isinstance(
        value,
        uuid.UUID,
    ):
        return value

    try:
        return uuid.UUID(
            str(value)
        )
    except (
        TypeError,
        ValueError,
        AttributeError,
    ) as exc:
        raise ValueError(
            f"Invalid refresh job UUID: {value!r}"
        ) from exc


def _worker_id(
    value: str,
) -> str:
    """Validate one worker ownership identifier."""
    worker_id = value.strip()

    if not worker_id:
        raise ValueError(
            "worker_id is required."
        )

    if len(worker_id) > 200:
        raise ValueError(
            "worker_id cannot exceed 200 characters."
        )

    return worker_id


def _marketplace(
    value: str,
) -> str:
    """Validate one durable marketplace identifier."""
    marketplace = value.strip().casefold()

    valid = {
        name
        for name, _ordinal
        in MARKETPLACES
    }

    if marketplace not in valid:
        raise ValueError(
            f"Unsupported marketplace: {value!r}"
        )

    return marketplace


def _marketplace_state(
    value: str,
) -> str:
    """Validate one durable marketplace state."""
    state = value.strip().casefold()

    if state not in MARKETPLACE_STATES:
        raise ValueError(
            f"Unsupported marketplace state: {value!r}"
        )

    return state


def _counter(
    value: int | None,
    *,
    name: str,
) -> int | None:
    """Validate one optional non-negative marketplace counter."""
    if value is None:
        return None

    result = int(value)

    if result < 0:
        raise ValueError(
            f"{name} cannot be negative."
        )

    return result


def _require_schema(
    connection,
) -> None:
    """Raise when the Phase-C operational schema is unavailable."""
    row = connection.execute(
        text(
            """
            SELECT
                to_regclass(
                    'ops.refresh_job'
                ) IS NOT NULL
                    AS refresh_job,
                to_regclass(
                    'ops.refresh_marketplace'
                ) IS NOT NULL
                    AS refresh_marketplace,
                to_regclass(
                    'ops.refresh_event'
                ) IS NOT NULL
                    AS refresh_event
            """
        )
    ).mappings().one()

    if not all(
        bool(row[key])
        for key in (
            "refresh_job",
            "refresh_marketplace",
            "refresh_event",
        )
    ):
        raise RefreshCoordinationUnavailable(
            "Phase-C durable refresh tables are not installed."
        )


def coordination_schema_ready(
    engine: Engine,
) -> bool:
    """Return whether all durable refresh coordination tables exist."""
    try:
        with engine.connect() as connection:
            _require_schema(
                connection
            )
    except (
        RefreshCoordinationUnavailable,
        SQLAlchemyError,
    ):
        return False

    return True


def _append_event(
    connection,
    *,
    job_id: uuid.UUID,
    event_type: str,
    marketplace: str | None = None,
    message: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Append one durable operational event."""
    connection.execute(
        text(
            """
            INSERT INTO ops.refresh_event (
                job_id,
                marketplace,
                event_type,
                message,
                payload
            )
            VALUES (
                :job_id,
                :marketplace,
                :event_type,
                :message,
                CAST(
                    :payload AS jsonb
                )
            )
            """
        ),
        {
            "job_id": job_id,
            "marketplace": marketplace,
            "event_type": event_type,
            "message": message,
            "payload": _json_payload(
                payload
            ),
        },
    )


def _json_payload(
    payload: Mapping[str, Any] | None,
) -> str:
    """Return one JSON object suitable for a JSONB bind."""
    import json

    return json.dumps(
        dict(
            payload
            or {}
        ),
        default=str,
        sort_keys=True,
    )


def _marketplace_rows(
    connection,
    job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return marketplace lifecycle rows for one job."""
    rows = connection.execute(
        text(
            """
            SELECT
                job_id,
                marketplace,
                ordinal,
                state,
                started_at,
                finished_at,
                discovered,
                already_known,
                new_count,
                detail_scraped,
                detail_skipped,
                discovery_pages,
                consecutive_known_at_stop,
                message,
                error,
                updated_at
            FROM ops.refresh_marketplace
            WHERE job_id = :job_id
            ORDER BY ordinal
            """
        ),
        {
            "job_id": job_id,
        },
    ).mappings()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def _event_rows(
    connection,
    job_id: uuid.UUID,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent durable events for one refresh job."""
    bounded_limit = max(
        1,
        min(
            int(limit),
            500,
        ),
    )

    rows = connection.execute(
        text(
            """
            SELECT
                id,
                job_id,
                marketplace,
                event_type,
                message,
                payload,
                created_at
            FROM ops.refresh_event
            WHERE job_id = :job_id
            ORDER BY id DESC
            LIMIT :limit
            """
        ),
        {
            "job_id": job_id,
            "limit": bounded_limit,
        },
    ).mappings()

    result = [
        _dictionary(
            row
        )
        for row in rows
    ]

    result.reverse()

    return result


def _job_from_row(
    connection,
    row: Mapping[str, Any],
    *,
    include_events: bool = False,
) -> dict[str, Any]:
    """Build one complete durable refresh-job payload."""
    result = _dictionary(
        row
    )

    job_id = _job_uuid(
        result["id"]
    )

    result[
        "marketplaces"
    ] = _marketplace_rows(
        connection,
        job_id,
    )

    if include_events:
        result[
            "events"
        ] = _event_rows(
            connection,
            job_id,
        )

    return result


def _select_job(
    connection,
    job_id: uuid.UUID,
    *,
    include_events: bool = False,
) -> dict[str, Any] | None:
    """Select one durable refresh job."""
    row = connection.execute(
        text(
            """
            SELECT
                id,
                state,
                requested_at,
                requested_by,
                trigger,
                started_at,
                finished_at,
                source_commit,
                lease_owner,
                lease_expires_at,
                heartbeat_at,
                attempt,
                cancel_requested_at,
                message,
                error,
                created_at,
                updated_at
            FROM ops.refresh_job
            WHERE id = :job_id
            """
        ),
        {
            "job_id": job_id,
        },
    ).mappings().one_or_none()

    if row is None:
        return None

    return _job_from_row(
        connection,
        row,
        include_events=include_events,
    )


def get_refresh_job(
    engine: Engine,
    job_id: str | uuid.UUID,
    *,
    include_events: bool = False,
) -> dict[str, Any]:
    """Return one durable refresh job."""
    validated_job_id = _job_uuid(
        job_id
    )

    with engine.connect() as connection:
        _require_schema(
            connection
        )

        job = _select_job(
            connection,
            validated_job_id,
            include_events=include_events,
        )

    if job is None:
        raise RefreshJobNotFound(
            f"Refresh job {validated_job_id} does not exist."
        )

    return job


def get_latest_refresh_job(
    engine: Engine,
    *,
    include_events: bool = False,
) -> dict[str, Any] | None:
    """Return the newest durable refresh job."""
    with engine.connect() as connection:
        _require_schema(
            connection
        )

        row = connection.execute(
            text(
                """
                SELECT
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                FROM ops.refresh_job
                ORDER BY
                    requested_at DESC,
                    created_at DESC,
                    id DESC
                LIMIT 1
                """
            )
        ).mappings().one_or_none()

        if row is None:
            return None

        return _job_from_row(
            connection,
            row,
            include_events=include_events,
        )


def list_refresh_jobs(
    engine: Engine,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return newest durable refresh jobs."""
    bounded_limit = max(
        1,
        min(
            int(limit),
            200,
        ),
    )

    with engine.connect() as connection:
        _require_schema(
            connection
        )

        rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        id,
                        state,
                        requested_at,
                        requested_by,
                        trigger,
                        started_at,
                        finished_at,
                        source_commit,
                        lease_owner,
                        lease_expires_at,
                        heartbeat_at,
                        attempt,
                        cancel_requested_at,
                        message,
                        error,
                        created_at,
                        updated_at
                    FROM ops.refresh_job
                    ORDER BY
                        requested_at DESC,
                        created_at DESC,
                        id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "limit": bounded_limit,
                },
            ).mappings()
        )

        return [
            _job_from_row(
                connection,
                row,
                include_events=False,
            )
            for row in rows
        ]


def create_refresh_job(
    engine: Engine,
    *,
    requested_by: str | None = None,
    source_commit: str | None = None,
    trigger: str = "api",
) -> tuple[dict[str, Any], bool]:
    """Create one queued job or return the existing active job."""
    normalized_trigger = (
        trigger.strip()
        or "api"
    )

    job_id = uuid.uuid4()

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        connection.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    :lock_key
                )
                """
            ),
            {
                "lock_key":
                    _COORDINATION_LOCK_KEY,
            },
        )

        active = connection.execute(
            text(
                """
                SELECT
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                FROM ops.refresh_job
                WHERE state IN (
                    'queued',
                    'running'
                )
                ORDER BY requested_at
                LIMIT 1
                FOR UPDATE
                """
            )
        ).mappings().one_or_none()

        if active is not None:
            return (
                _job_from_row(
                    connection,
                    active,
                ),
                False,
            )

        row = connection.execute(
            text(
                """
                INSERT INTO ops.refresh_job (
                    id,
                    state,
                    requested_by,
                    trigger,
                    source_commit,
                    message
                )
                VALUES (
                    :job_id,
                    'queued',
                    :requested_by,
                    :trigger,
                    :source_commit,
                    'Waiting for the persistent marketplace worker.'
                )
                RETURNING
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                """
            ),
            {
                "job_id": job_id,
                "requested_by":
                    requested_by,
                "trigger":
                    normalized_trigger,
                "source_commit":
                    source_commit,
            },
        ).mappings().one()

        connection.execute(
            text(
                """
                INSERT INTO ops.refresh_marketplace (
                    job_id,
                    marketplace,
                    ordinal,
                    state,
                    message
                )
                VALUES (
                    :job_id,
                    :marketplace,
                    :ordinal,
                    'waiting',
                    'Waiting for marketplace execution.'
                )
                """
            ),
            [
                {
                    "job_id": job_id,
                    "marketplace":
                        marketplace,
                    "ordinal":
                        ordinal,
                }
                for marketplace, ordinal
                in MARKETPLACES
            ],
        )

        _append_event(
            connection,
            job_id=job_id,
            event_type="job_queued",
            message=(
                "Durable marketplace refresh job queued."
            ),
            payload={
                "trigger":
                    normalized_trigger,
                "requested_by":
                    requested_by,
                "source_commit":
                    source_commit,
            },
        )

        return (
            _job_from_row(
                connection,
                row,
            ),
            True,
        )


def requeue_expired_refresh_jobs(
    engine: Engine,
    *,
    limit: int = 10,
) -> list[uuid.UUID]:
    """Requeue running jobs whose worker lease has expired."""
    bounded_limit = max(
        1,
        min(
            int(limit),
            100,
        ),
    )

    recovered: list[
        uuid.UUID
    ] = []

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        id,
                        lease_owner
                    FROM ops.refresh_job
                    WHERE state = 'running'
                      AND lease_expires_at
                            < now()
                    ORDER BY lease_expires_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                    """
                ),
                {
                    "limit": bounded_limit,
                },
            ).mappings()
        )

        for row in rows:
            job_id = _job_uuid(
                row["id"]
            )

            previous_owner = row[
                "lease_owner"
            ]

            connection.execute(
                text(
                    """
                    UPDATE ops.refresh_job
                    SET
                        state = 'queued',
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        finished_at = NULL,
                        message = (
                            'Worker lease expired; queued for retry.'
                        ),
                        error = NULL,
                        updated_at = now()
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                },
            )

            connection.execute(
                text(
                    """
                    UPDATE ops.refresh_marketplace
                    SET
                        state = 'waiting',
                        started_at = NULL,
                        finished_at = NULL,
                        discovered = 0,
                        already_known = 0,
                        new_count = 0,
                        detail_scraped = 0,
                        detail_skipped = 0,
                        discovery_pages = 0,
                        consecutive_known_at_stop = 0,
                        message = (
                            'Waiting for marketplace execution.'
                        ),
                        error = NULL,
                        updated_at = now()
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                },
            )

            _append_event(
                connection,
                job_id=job_id,
                event_type=(
                    "job_lease_expired"
                ),
                message=(
                    "Expired worker lease recovered; job requeued."
                ),
                payload={
                    "previous_owner":
                        previous_owner,
                },
            )

            recovered.append(
                job_id
            )

    return recovered


def claim_next_refresh_job(
    engine: Engine,
    *,
    worker_id: str,
    lease_seconds: int = 90,
) -> dict[str, Any] | None:
    """Claim the oldest queued job with a durable worker lease."""
    validated_worker_id = _worker_id(
        worker_id
    )

    validated_lease = int(
        lease_seconds
    )

    if validated_lease < 30:
        raise ValueError(
            "lease_seconds must be at least 30."
        )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        connection.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    :lock_key
                )
                """
            ),
            {
                "lock_key":
                    _COORDINATION_LOCK_KEY,
            },
        )

        running = connection.execute(
            text(
                """
                SELECT id
                FROM ops.refresh_job
                WHERE state = 'running'
                  AND lease_expires_at
                        >= now()
                LIMIT 1
                FOR UPDATE
                """
            )
        ).scalar_one_or_none()

        if running is not None:
            return None

        row = connection.execute(
            text(
                """
                SELECT id
                FROM ops.refresh_job
                WHERE state = 'queued'
                ORDER BY
                    requested_at,
                    created_at,
                    id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        ).mappings().one_or_none()

        if row is None:
            return None

        job_id = _job_uuid(
            row["id"]
        )

        claimed = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    state = 'running',
                    lease_owner = :worker_id,
                    lease_expires_at = (
                        now()
                        + make_interval(
                            secs => :lease_seconds
                        )
                    ),
                    heartbeat_at = now(),
                    started_at = COALESCE(
                        started_at,
                        now()
                    ),
                    finished_at = NULL,
                    attempt = attempt + 1,
                    message = (
                        'Persistent marketplace worker claimed the job.'
                    ),
                    error = NULL,
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'queued'
                RETURNING
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                """
            ),
            {
                "worker_id":
                    validated_worker_id,
                "lease_seconds":
                    validated_lease,
                "job_id":
                    job_id,
            },
        ).mappings().one_or_none()

        if claimed is None:
            return None

        _append_event(
            connection,
            job_id=job_id,
            event_type="job_claimed",
            message=(
                "Persistent marketplace worker claimed the job."
            ),
            payload={
                "worker_id":
                    validated_worker_id,
                "lease_seconds":
                    validated_lease,
            },
        )

        return _job_from_row(
            connection,
            claimed,
        )


def heartbeat_refresh_job(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    lease_seconds: int = 90,
) -> datetime:
    """Extend one running job lease owned by the worker."""
    validated_job_id = _job_uuid(
        job_id
    )

    validated_worker_id = _worker_id(
        worker_id
    )

    validated_lease = int(
        lease_seconds
    )

    if validated_lease < 30:
        raise ValueError(
            "lease_seconds must be at least 30."
        )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        heartbeat = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    heartbeat_at = now(),
                    lease_expires_at = (
                        now()
                        + make_interval(
                            secs => :lease_seconds
                        )
                    ),
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'running'
                  AND lease_owner = :worker_id
                  AND lease_expires_at
                        >= now()
                RETURNING heartbeat_at
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "worker_id":
                    validated_worker_id,
                "lease_seconds":
                    validated_lease,
            },
        ).scalar_one_or_none()

    if heartbeat is None:
        raise RefreshLeaseLost(
            "The refresh worker no longer owns "
            f"job {validated_job_id}."
        )

    return heartbeat


def update_marketplace_state(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    marketplace: str,
    state: str,
    discovered: int | None = None,
    already_known: int | None = None,
    new_count: int | None = None,
    detail_scraped: int | None = None,
    detail_skipped: int | None = None,
    discovery_pages: int | None = None,
    consecutive_known_at_stop: int | None = None,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist one marketplace transition and its latest counters."""
    validated_job_id = _job_uuid(
        job_id
    )

    validated_worker_id = _worker_id(
        worker_id
    )

    validated_marketplace = _marketplace(
        marketplace
    )

    validated_state = _marketplace_state(
        state
    )

    counters = {
        "discovered":
            _counter(
                discovered,
                name="discovered",
            ),
        "already_known":
            _counter(
                already_known,
                name="already_known",
            ),
        "new_count":
            _counter(
                new_count,
                name="new_count",
            ),
        "detail_scraped":
            _counter(
                detail_scraped,
                name="detail_scraped",
            ),
        "detail_skipped":
            _counter(
                detail_skipped,
                name="detail_skipped",
            ),
        "discovery_pages":
            _counter(
                discovery_pages,
                name="discovery_pages",
            ),
        "consecutive_known_at_stop":
            _counter(
                consecutive_known_at_stop,
                name=(
                    "consecutive_known_at_stop"
                ),
            ),
    }

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        owned = connection.execute(
            text(
                """
                SELECT 1
                FROM ops.refresh_job
                WHERE id = :job_id
                  AND state = 'running'
                  AND lease_owner = :worker_id
                  AND lease_expires_at
                        >= now()
                FOR UPDATE
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "worker_id":
                    validated_worker_id,
            },
        ).scalar_one_or_none()

        if owned is None:
            raise RefreshLeaseLost(
                "The refresh worker no longer owns "
                f"job {validated_job_id}."
            )

        row = connection.execute(
            text(
                """
                UPDATE ops.refresh_marketplace
                SET
                    state = :state,
                    started_at = CASE
                        WHEN :state = 'running'
                        THEN COALESCE(
                            started_at,
                            now()
                        )
                        ELSE started_at
                    END,
                    finished_at = CASE
                        WHEN :state IN (
                            'done',
                            'failed',
                            'skipped'
                        )
                        THEN now()
                        WHEN :state = 'running'
                        THEN NULL
                        ELSE finished_at
                    END,
                    discovered = COALESCE(
                        :discovered,
                        discovered
                    ),
                    already_known = COALESCE(
                        :already_known,
                        already_known
                    ),
                    new_count = COALESCE(
                        :new_count,
                        new_count
                    ),
                    detail_scraped = COALESCE(
                        :detail_scraped,
                        detail_scraped
                    ),
                    detail_skipped = COALESCE(
                        :detail_skipped,
                        detail_skipped
                    ),
                    discovery_pages = COALESCE(
                        :discovery_pages,
                        discovery_pages
                    ),
                    consecutive_known_at_stop =
                        COALESCE(
                            :consecutive_known_at_stop,
                            consecutive_known_at_stop
                        ),
                    message = COALESCE(
                        :message,
                        message
                    ),
                    error = :error,
                    updated_at = now()
                WHERE job_id = :job_id
                  AND marketplace = :marketplace
                RETURNING
                    job_id,
                    marketplace,
                    ordinal,
                    state,
                    started_at,
                    finished_at,
                    discovered,
                    already_known,
                    new_count,
                    detail_scraped,
                    detail_skipped,
                    discovery_pages,
                    consecutive_known_at_stop,
                    message,
                    error,
                    updated_at
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "marketplace":
                    validated_marketplace,
                "state":
                    validated_state,
                "message":
                    message,
                "error":
                    error,
                **counters,
            },
        ).mappings().one_or_none()

        if row is None:
            raise RefreshCoordinationError(
                "Marketplace lifecycle row is missing for "
                f"{validated_marketplace}."
            )

        _append_event(
            connection,
            job_id=validated_job_id,
            marketplace=(
                validated_marketplace
            ),
            event_type=(
                "marketplace_"
                + validated_state
            ),
            message=message,
            payload={
                key: value
                for key, value
                in counters.items()
                if value is not None
            },
        )

        return _dictionary(
            row
        )


def mark_refresh_job_completed(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    message: str = "Marketplace refresh completed.",
) -> dict[str, Any]:
    """Complete a job after every marketplace is terminal-successful."""
    validated_job_id = _job_uuid(
        job_id
    )

    validated_worker_id = _worker_id(
        worker_id
    )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        states = list(
            connection.execute(
                text(
                    """
                    SELECT state
                    FROM ops.refresh_marketplace
                    WHERE job_id = :job_id
                    ORDER BY ordinal
                    FOR UPDATE
                    """
                ),
                {
                    "job_id":
                        validated_job_id,
                },
            ).scalars()
        )

        if len(states) != len(
            MARKETPLACES
        ):
            raise RefreshCoordinationError(
                "Refresh job does not contain every marketplace row."
            )

        if any(
            state not in {
                "done",
                "skipped",
            }
            for state in states
        ):
            raise RefreshCoordinationError(
                "Cannot complete a refresh job while "
                "marketplaces are non-terminal or failed."
            )

        row = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    state = 'completed',
                    finished_at = now(),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    message = :message,
                    error = NULL,
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'running'
                  AND lease_owner = :worker_id
                  AND lease_expires_at
                        >= now()
                RETURNING
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "worker_id":
                    validated_worker_id,
                "message":
                    message,
            },
        ).mappings().one_or_none()

        if row is None:
            raise RefreshLeaseLost(
                "The refresh worker no longer owns "
                f"job {validated_job_id}."
            )

        _append_event(
            connection,
            job_id=validated_job_id,
            event_type="job_completed",
            message=message,
        )

        return _job_from_row(
            connection,
            row,
        )


def mark_refresh_job_failed(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    error: str,
    marketplace: str | None = None,
    message: str = "Marketplace refresh failed.",
) -> dict[str, Any]:
    """Fail one running job owned by the worker."""
    validated_job_id = _job_uuid(
        job_id
    )

    validated_worker_id = _worker_id(
        worker_id
    )

    validated_marketplace = (
        _marketplace(
            marketplace
        )
        if marketplace
        else None
    )

    normalized_error = (
        error.strip()
        or "Unknown marketplace refresh failure."
    )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        if validated_marketplace:
            connection.execute(
                text(
                    """
                    UPDATE ops.refresh_marketplace
                    SET
                        state = 'failed',
                        finished_at = now(),
                        message = :message,
                        error = :error,
                        updated_at = now()
                    WHERE job_id = :job_id
                      AND marketplace = :marketplace
                    """
                ),
                {
                    "job_id":
                        validated_job_id,
                    "marketplace":
                        validated_marketplace,
                    "message":
                        message,
                    "error":
                        normalized_error,
                },
            )

        row = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    state = 'failed',
                    finished_at = now(),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    message = :message,
                    error = :error,
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'running'
                  AND lease_owner = :worker_id
                  AND lease_expires_at
                        >= now()
                RETURNING
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "worker_id":
                    validated_worker_id,
                "message":
                    message,
                "error":
                    normalized_error,
            },
        ).mappings().one_or_none()

        if row is None:
            raise RefreshLeaseLost(
                "The refresh worker no longer owns "
                f"job {validated_job_id}."
            )

        _append_event(
            connection,
            job_id=validated_job_id,
            marketplace=(
                validated_marketplace
            ),
            event_type="job_failed",
            message=message,
            payload={
                "error":
                    normalized_error,
            },
        )

        return _job_from_row(
            connection,
            row,
        )


def release_refresh_job(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    reason: str = "Worker shutdown requested.",
) -> bool:
    """Release a running lease and requeue the job for another worker."""
    validated_job_id = _job_uuid(
        job_id
    )

    validated_worker_id = _worker_id(
        worker_id
    )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        released = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    state = 'queued',
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    finished_at = NULL,
                    message = :reason,
                    error = NULL,
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'running'
                  AND lease_owner = :worker_id
                RETURNING id
                """
            ),
            {
                "job_id":
                    validated_job_id,
                "worker_id":
                    validated_worker_id,
                "reason":
                    reason,
            },
        ).scalar_one_or_none()

        if released is None:
            return False

        connection.execute(
            text(
                """
                UPDATE ops.refresh_marketplace
                SET
                    state = 'waiting',
                    started_at = NULL,
                    finished_at = NULL,
                    discovered = 0,
                    already_known = 0,
                    new_count = 0,
                    detail_scraped = 0,
                    detail_skipped = 0,
                    discovery_pages = 0,
                    consecutive_known_at_stop = 0,
                    message = (
                        'Waiting for marketplace execution.'
                    ),
                    error = NULL,
                    updated_at = now()
                WHERE job_id = :job_id
                """
            ),
            {
                "job_id":
                    validated_job_id,
            },
        )

        _append_event(
            connection,
            job_id=validated_job_id,
            event_type="job_requeued",
            message=reason,
            payload={
                "previous_owner":
                    validated_worker_id,
            },
        )

    return True


def request_refresh_job_cancel(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
) -> dict[str, Any]:
    """Record a cancellation request without killing a worker process."""
    validated_job_id = _job_uuid(
        job_id
    )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        row = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    cancel_requested_at = COALESCE(
                        cancel_requested_at,
                        now()
                    ),
                    message = (
                        'Cancellation requested.'
                    ),
                    updated_at = now()
                WHERE id = :job_id
                  AND state IN (
                    'queued',
                    'running'
                  )
                RETURNING
                    id,
                    state,
                    requested_at,
                    requested_by,
                    trigger,
                    started_at,
                    finished_at,
                    source_commit,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    attempt,
                    cancel_requested_at,
                    message,
                    error,
                    created_at,
                    updated_at
                """
            ),
            {
                "job_id":
                    validated_job_id,
            },
        ).mappings().one_or_none()

        if row is None:
            existing = _select_job(
                connection,
                validated_job_id,
            )

            if existing is None:
                raise RefreshJobNotFound(
                    f"Refresh job {validated_job_id} does not exist."
                )

            return existing

        _append_event(
            connection,
            job_id=validated_job_id,
            event_type=(
                "job_cancel_requested"
            ),
            message=(
                "Cancellation requested."
            ),
        )

        return _job_from_row(
            connection,
            row,
        )


def cancel_queued_refresh_job(
    engine: Engine,
    *,
    job_id: str | uuid.UUID,
) -> bool:
    """Cancel a job that has not been claimed yet."""
    validated_job_id = _job_uuid(
        job_id
    )

    with engine.begin() as connection:
        _require_schema(
            connection
        )

        cancelled = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    state = 'cancelled',
                    finished_at = now(),
                    message = (
                        'Queued refresh cancelled.'
                    ),
                    updated_at = now()
                WHERE id = :job_id
                  AND state = 'queued'
                RETURNING id
                """
            ),
            {
                "job_id":
                    validated_job_id,
            },
        ).scalar_one_or_none()

        if cancelled is None:
            return False

        connection.execute(
            text(
                """
                UPDATE ops.refresh_marketplace
                SET
                    state = 'skipped',
                    finished_at = now(),
                    message = (
                        'Refresh job cancelled before execution.'
                    ),
                    updated_at = now()
                WHERE job_id = :job_id
                """
            ),
            {
                "job_id":
                    validated_job_id,
            },
        )

        _append_event(
            connection,
            job_id=validated_job_id,
            event_type="job_cancelled",
            message=(
                "Queued refresh cancelled."
            ),
        )

    return True


def refresh_job_to_ui_status(
    job: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate durable rows into the existing Streamlit progress contract."""
    state = str(
        job.get(
            "state",
            "idle",
        )
    ).casefold()

    marketplace_rows = job.get(
        "marketplaces",
        []
    )

    marketplace_states = {
        marketplace:
            "waiting"
        for marketplace, _ordinal
        in MARKETPLACES
    }

    summary_marketplaces: dict[
        str,
        dict[str, Any],
    ] = {}

    if isinstance(
        marketplace_rows,
        list,
    ):
        for raw_row in marketplace_rows:
            if not isinstance(
                raw_row,
                Mapping,
            ):
                continue

            marketplace = str(
                raw_row.get(
                    "marketplace",
                    "",
                )
            ).casefold()

            if marketplace not in marketplace_states:
                continue

            marketplace_state = str(
                raw_row.get(
                    "state",
                    "waiting",
                )
            ).casefold()

            if marketplace_state == "skipped":
                marketplace_state = (
                    "unavailable"
                )

            marketplace_states[
                marketplace
            ] = marketplace_state

            summary_marketplaces[
                marketplace
            ] = {
                "newly_ingested":
                    int(
                        raw_row.get(
                            "new_count",
                            0,
                        )
                        or 0
                    ),
                "discovered":
                    int(
                        raw_row.get(
                            "discovered",
                            0,
                        )
                        or 0
                    ),
                "already_known":
                    int(
                        raw_row.get(
                            "already_known",
                            0,
                        )
                        or 0
                    ),
                "detail_scraped":
                    int(
                        raw_row.get(
                            "detail_scraped",
                            0,
                        )
                        or 0
                    ),
                "detail_skipped":
                    int(
                        raw_row.get(
                            "detail_skipped",
                            0,
                        )
                        or 0
                    ),
                "discovery_pages":
                    int(
                        raw_row.get(
                            "discovery_pages",
                            0,
                        )
                        or 0
                    ),
                "consecutive_known_at_stop":
                    int(
                        raw_row.get(
                            "consecutive_known_at_stop",
                            0,
                        )
                        or 0
                    ),
            }

    phase = state

    for marketplace, _ordinal in MARKETPLACES:
        if marketplace_states[
            marketplace
        ] == "running":
            phase = marketplace
            break

    return {
        "schema":
            "auction-refresh-job/postgres-v1",
        "job_id":
            str(
                job.get(
                    "id",
                    "",
                )
            ),
        "state":
            state,
        "status":
            state,
        "phase":
            phase,
        "message":
            str(
                job.get(
                    "message",
                    "",
                )
                or ""
            ),
        "error":
            job.get(
                "error"
            ),
        "trigger":
            job.get(
                "trigger"
            ),
        "requested_at":
            job.get(
                "requested_at"
            ),
        "started_at":
            job.get(
                "started_at"
            ),
        "finished_at":
            job.get(
                "finished_at"
            ),
        "updated_at":
            job.get(
                "updated_at"
            ),
        "attempt":
            int(
                job.get(
                    "attempt",
                    0,
                )
                or 0
            ),
        "marketplace_states":
            marketplace_states,
        "summary": {
            "marketplaces":
                summary_marketplaces,
        },
    }
