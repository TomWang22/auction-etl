"""Audited administration of media-specific component profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


MEDIA_TYPE_PATTERN = re.compile(
    r"^[A-Z0-9][A-Z0-9_]{0,39}$"
)


@dataclass(frozen=True)
class MediaProfilePreview:
    """Deterministic media-profile mutation preview."""

    media_type: str
    digest: str
    confirmation_token: str
    status: str
    ready: bool
    operations: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return asdict(
            self
        )


def _text(value: object) -> str:
    """Normalize text."""
    return str(
        value
        or ""
    ).strip()


def _media_type(value: object) -> str:
    """Validate a professional media-type key."""
    normalized = _text(
        value
    ).upper()

    if not MEDIA_TYPE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "Media type must use 1–40 uppercase letters, "
            "numbers, or underscores."
        )

    return normalized


def _integer(
    value: object,
) -> int:
    """Normalize a positive integer."""
    try:
        normalized = int(
            str(
                value
            )
        )
    except Exception as error:
        raise ValueError(
            f"Expected a positive integer; received {value!r}."
        ) from error

    if normalized < 1:
        raise ValueError(
            "Sort order must be positive."
        )

    return normalized


def _boolean(value: object) -> bool:
    """Normalize one editor boolean."""
    if isinstance(
        value,
        bool,
    ):
        return value

    return _text(
        value
    ).casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def list_media_types(
    engine: Engine,
) -> list[str]:
    """List configured and observed media types."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT DISTINCT media_type
                FROM (
                    SELECT media_type
                    FROM system.media_profile_component

                    UNION

                    SELECT media_type
                    FROM warehouse.pressing_identity
                ) AS media
                WHERE media_type IS NOT NULL
                  AND trim(media_type) <> ''
                ORDER BY media_type
                """
            )
        ).scalars().all()

    return [
        str(
            value
        )
        for value in rows
    ]


def load_profile_editor(
    engine: Engine,
    media_type: str,
) -> list[dict[str, Any]]:
    """Return every component as an editable profile row."""
    normalized_media = _media_type(
        media_type
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    component.code AS component_code,
                    component.display_name,
                    profile.field_group,
                    profile.sort_order,
                    COALESCE(
                        profile.active,
                        false
                    ) AS enabled,
                    profile.notes,
                    (
                        profile.component_code
                        IS NOT NULL
                    ) AS persisted
                FROM system.component_type AS component
                LEFT JOIN system.media_profile_component
                    AS profile
                  ON profile.component_code =
                        component.code
                 AND profile.media_type =
                        :media_type
                WHERE component.active
                ORDER BY
                    COALESCE(
                        profile.sort_order,
                        99999
                    ),
                    component.code
                """
            ),
            {
                "media_type":
                    normalized_media,
            },
        ).mappings().all()

    return [
        {
            "component_code":
                row[
                    "component_code"
                ],
            "display_name":
                row[
                    "display_name"
                ],
            "enabled":
                bool(
                    row[
                        "enabled"
                    ]
                ),
            "field_group":
                row[
                    "field_group"
                ]
                or "Applicable components",
            "sort_order":
                int(
                    row[
                        "sort_order"
                    ]
                    or 1000
                ),
            "notes":
                row[
                    "notes"
                ],
            "persisted":
                bool(
                    row[
                        "persisted"
                    ]
                ),
        }
        for row in rows
    ]


def _current_rows(
    connection: Connection,
    media_type: str,
) -> dict[str, dict[str, Any]]:
    """Load current authoritative profile rows."""
    rows = connection.execute(
        text(
            """
            SELECT
                media_type,
                component_code,
                field_group,
                sort_order,
                active,
                notes
            FROM system.media_profile_component
            WHERE media_type =
                    :media_type
            """
        ),
        {
            "media_type":
                media_type,
        },
    ).mappings().all()

    return {
        str(
            row[
                "component_code"
            ]
        ):
            dict(
                row
            )
        for row in rows
    }


def _preview_with_connection(
    connection: Connection,
    media_type: str,
    rows: Sequence[Mapping[str, Any]],
) -> MediaProfilePreview:
    """Build one deterministic profile preview."""
    normalized_media = _media_type(
        media_type
    )

    valid_components = {
        str(
            value
        )
        for value in connection.execute(
            text(
                """
                SELECT code
                FROM system.component_type
                WHERE active
                """
            )
        ).scalars().all()
    }

    current = _current_rows(
        connection,
        normalized_media,
    )

    blockers: list[str] = []
    warnings: list[str] = []
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row_number, row in enumerate(
        rows,
        start=1,
    ):
        component_code = _text(
            row.get(
                "component_code"
            )
        ).upper()

        if component_code in seen:
            blockers.append(
                f"Row {row_number}: duplicate component {component_code}."
            )
            continue

        seen.add(
            component_code
        )

        if component_code not in valid_components:
            blockers.append(
                f"Row {row_number}: unknown active component "
                f"{component_code!r}."
            )
            continue

        enabled = _boolean(
            row.get(
                "enabled"
            )
        )

        persisted = current.get(
            component_code
        )

        if not enabled:
            if persisted is not None:
                operations.append(
                    {
                        "operation":
                            "DELETE",
                        "component_code":
                            component_code,
                        "before":
                            persisted,
                        "after":
                            None,
                    }
                )

            continue

        field_group = _text(
            row.get(
                "field_group"
            )
        )

        if not field_group:
            blockers.append(
                f"Row {row_number}: enabled components require a field group."
            )
            continue

        try:
            sort_order = _integer(
                row.get(
                    "sort_order"
                )
            )
        except ValueError as error:
            blockers.append(
                f"Row {row_number}: {error}"
            )
            continue

        after = {
            "media_type":
                normalized_media,
            "component_code":
                component_code,
            "field_group":
                field_group,
            "sort_order":
                sort_order,
            "active":
                True,
            "notes":
                _text(
                    row.get(
                        "notes"
                    )
                )
                or None,
        }

        comparable_before = (
            {
                key:
                    persisted.get(
                        key
                    )
                for key in after
            }
            if persisted is not None
            else None
        )

        if comparable_before == after:
            continue

        operations.append(
            {
                "operation":
                    (
                        "UPDATE"
                        if persisted is not None
                        else "INSERT"
                    ),
                "component_code":
                    component_code,
                "before":
                    persisted,
                "after":
                    after,
            }
        )

    current_fingerprint = [
        {
            "media_type":
                row[
                    "media_type"
                ],
            "component_code":
                row[
                    "component_code"
                ],
            "field_group":
                row[
                    "field_group"
                ],
            "sort_order":
                row[
                    "sort_order"
                ],
            "active":
                row[
                    "active"
                ],
            "notes":
                row[
                    "notes"
                ],
        }
        for row in current.values()
    ]

    current_fingerprint.sort(
        key=lambda row:
            str(
                row[
                    "component_code"
                ]
            )
    )

    digest_payload = {
        "media_type":
            normalized_media,
        "current":
            current_fingerprint,
        "operations":
            operations,
    }

    digest = sha256(
        json.dumps(
            digest_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
            default=str,
        ).encode(
            "utf-8"
        )
    ).hexdigest()

    if blockers:
        status = "BLOCKED"
    elif operations:
        status = "READY"
    else:
        status = "NO_CHANGES"

    return MediaProfilePreview(
        media_type=normalized_media,
        digest=digest,
        confirmation_token=(
            f"MEDIA_PROFILE:{normalized_media}:"
            f"{digest[:12].upper()}"
        ),
        status=status,
        ready=(
            status == "READY"
        ),
        operations=tuple(
            operations
        ),
        blockers=tuple(
            blockers
        ),
        warnings=tuple(
            warnings
        ),
    )


def preview_profile_changes(
    engine: Engine,
    media_type: str,
    rows: Sequence[Mapping[str, Any]],
) -> MediaProfilePreview:
    """Preview profile changes without writing."""
    with engine.connect() as connection:
        return _preview_with_connection(
            connection,
            media_type,
            rows,
        )


def apply_profile_changes(
    engine: Engine,
    media_type: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
    confirmation_token: str,
) -> dict[str, Any]:
    """Revalidate and atomically apply one profile change."""
    normalized_media = _media_type(
        media_type
    )

    normalized_actor = _text(
        actor
    )

    normalized_reason = _text(
        reason
    )

    normalized_token = _text(
        confirmation_token
    )

    if not normalized_actor:
        raise ValueError(
            "Reviewer is required."
        )

    if not normalized_reason:
        raise ValueError(
            "Change reason is required."
        )

    if not normalized_token:
        raise ValueError(
            "Confirmation token is required."
        )

    connection = engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    )

    applied = 0

    try:
        with connection.begin():
            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtext(
                            :lock_key
                        )
                    )
                    """
                ),
                {
                    "lock_key":
                        (
                            "media-profile:"
                            + normalized_media
                        ),
                },
            )

            preview = _preview_with_connection(
                connection,
                normalized_media,
                rows,
            )

            if not preview.ready:
                raise ValueError(
                    "Media-profile preview is not ready: "
                    + "; ".join(
                        preview.blockers
                        or (
                            "No mutations were requested.",
                        )
                    )
                )

            if (
                normalized_token
                != preview.confirmation_token
            ):
                raise ValueError(
                    "Confirmation token is stale or incorrect."
                )

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'auction_etl.actor',
                        :actor,
                        true
                    )
                    """
                ),
                {
                    "actor":
                        normalized_actor,
                },
            )

            connection.execute(
                text(
                    """
                    SELECT set_config(
                        'auction_etl.reason',
                        :reason,
                        true
                    )
                    """
                ),
                {
                    "reason":
                        normalized_reason,
                },
            )

            for operation in preview.operations:
                component_code = str(
                    operation[
                        "component_code"
                    ]
                )

                operation_name = str(
                    operation[
                        "operation"
                    ]
                )

                if operation_name == "DELETE":
                    result = connection.execute(
                        text(
                            """
                            DELETE FROM
                                system.media_profile_component
                            WHERE media_type =
                                    :media_type
                              AND component_code =
                                    :component_code
                            """
                        ),
                        {
                            "media_type":
                                normalized_media,
                            "component_code":
                                component_code,
                        },
                    )

                    if result.rowcount != 1:
                        raise ValueError(
                            "A reviewed profile DELETE no longer "
                            "matches one row."
                        )

                elif operation_name == "INSERT":
                    after = operation[
                        "after"
                    ]

                    connection.execute(
                        text(
                            """
                            INSERT INTO
                                system.media_profile_component (
                                    media_type,
                                    component_code,
                                    field_group,
                                    sort_order,
                                    active,
                                    notes
                                )
                            VALUES (
                                :media_type,
                                :component_code,
                                :field_group,
                                :sort_order,
                                true,
                                :notes
                            )
                            """
                        ),
                        after,
                    )

                elif operation_name == "UPDATE":
                    after = operation[
                        "after"
                    ]

                    result = connection.execute(
                        text(
                            """
                            UPDATE system.media_profile_component
                            SET field_group =
                                    :field_group,
                                sort_order =
                                    :sort_order,
                                active =
                                    true,
                                notes =
                                    :notes,
                                updated_at =
                                    now()
                            WHERE media_type =
                                    :media_type
                              AND component_code =
                                    :component_code
                            """
                        ),
                        after,
                    )

                    if result.rowcount != 1:
                        raise ValueError(
                            "A reviewed profile UPDATE no longer "
                            "matches one row."
                        )

                else:
                    raise AssertionError(
                        f"Unsupported operation {operation_name!r}."
                    )

                applied += 1

        return {
            "status":
                "COMPLETED",
            "media_type":
                normalized_media,
            "applied_operation_count":
                applied,
        }
    finally:
        connection.close()


def list_profile_audit(
    engine: Engine,
    media_type: str | None = None,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List immutable media-profile audit events."""
    normalized_media = (
        _media_type(
            media_type
        )
        if media_type
        else None
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    media_type,
                    component_code,
                    action,
                    actor,
                    reason,
                    before_state,
                    after_state,
                    created_at
                FROM system.media_profile_audit_event
                WHERE (
                    CAST(
                        :media_type
                        AS text
                    ) IS NULL
                    OR media_type =
                        CAST(
                            :media_type
                            AS text
                        )
                )
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "media_type":
                    normalized_media,
                "limit":
                    int(
                        limit
                    ),
            },
        ).mappings().all()

    return [
        dict(
            row
        )
        for row in rows
    ]
