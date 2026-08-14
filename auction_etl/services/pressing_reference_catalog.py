"""Persistence service for stable physical pressing references."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.domain.pressing_reference import (
    MatrixRunout,
    PressingReference,
    ReleaseFormat,
    ReleaseType,
)


def normalize_identity_key(
    value: str,
) -> str:
    """Return a stable family identity key."""

    return re.sub(
        r"\s+",
        " ",
        value.strip().casefold(),
    )


def _clean(
    value: str | None,
) -> str:
    if value is None:
        return ""

    return value.strip()


def _matrices_from_value(
    value: Any,
) -> list[dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value

    if not isinstance(parsed, list):
        return []

    return [
        dict(item)
        for item in parsed
        if isinstance(item, dict)
    ]


def _row(
    result: Any,
) -> dict[str, Any] | None:
    mapping = result.mappings().first()

    if mapping is None:
        return None

    row = dict(mapping)

    if "matrices" in row:
        row["matrices"] = _matrices_from_value(
            row["matrices"]
        )

    return row


def _get_reference(
    connection: Connection,
    pressing_id: int,
) -> dict[str, Any] | None:
    return _row(
        connection.execute(
            text(
                """
                SELECT *
                FROM warehouse.pressing_reference_catalog
                WHERE pressing_reference_id = :pressing_id
                """
            ),
            {
                "pressing_id": pressing_id,
            },
        )
    )


def get_pressing_reference(
    engine: Engine,
    pressing_id: int,
) -> dict[str, Any]:
    """Load one auction-independent pressing reference."""

    with engine.connect() as connection:
        reference = _get_reference(
            connection,
            pressing_id,
        )

    if reference is None:
        raise ValueError(
            f"pressing reference {pressing_id} does not exist"
        )

    return reference


def list_pressing_references(
    engine: Engine,
    *,
    search: str = "",
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """List stable physical pressing references."""

    cleaned_search = search.strip()

    parameters: dict[str, Any] = {
        "limit": max(
            1,
            min(
                int(limit),
                10000,
            ),
        ),
    }

    where_clause = ""

    if cleaned_search:
        where_clause = """
        WHERE
            artist ILIKE :search
            OR canonical_title ILIKE :search
            OR catalog_number ILIKE :search
            OR label ILIKE :search
            OR release_country ILIKE :search
            OR release_language ILIKE :search
            OR release_format ILIKE :search
            OR release_type ILIKE :search
            OR EXISTS (
                SELECT 1
                FROM warehouse.pressing_matrix_runout AS matrix
                WHERE matrix.pressing_id =
                      pressing_reference_id
                  AND matrix.value ILIKE :search
            )
        """

        parameters["search"] = (
            f"%{cleaned_search}%"
        )

    with engine.connect() as connection:
        result = connection.execute(
            text(
                f"""
                SELECT *
                FROM warehouse.pressing_reference_catalog
                {where_clause}
                ORDER BY
                    artist,
                    canonical_title,
                    release_year NULLS LAST,
                    catalog_number NULLS LAST,
                    pressing_reference_id
                LIMIT :limit
                """
            ),
            parameters,
        )

        rows = []

        for mapping in result.mappings():
            row = dict(mapping)
            row["matrices"] = (
                _matrices_from_value(
                    row.get("matrices")
                )
            )
            rows.append(row)

    return rows


def _audit(
    connection: Connection,
    *,
    pressing_id: int,
    action: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    actor: str,
    reason: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO system.reference_audit_event (
                entity_type,
                entity_key,
                action,
                before_state,
                after_state,
                reason,
                actor
            )
            VALUES (
                'PRESSING_IDENTITY',
                CAST(:entity_key AS jsonb),
                :action,
                CAST(:before_state AS jsonb),
                CAST(:after_state AS jsonb),
                :reason,
                :actor
            )
            """
        ),
        {
            "entity_key": json.dumps(
                {
                    "pressing_id":
                        pressing_id,
                }
            ),
            "action": action,
            "before_state": (
                json.dumps(
                    before_state,
                    default=str,
                )
                if before_state is not None
                else None
            ),
            "after_state": (
                json.dumps(
                    after_state,
                    default=str,
                )
                if after_state is not None
                else None
            ),
            "reason": reason,
            "actor": actor,
        },
    )


def _replace_matrices(
    connection: Connection,
    *,
    pressing_id: int,
    matrices: list[MatrixRunout],
) -> None:
    connection.execute(
        text(
            """
            DELETE FROM warehouse.pressing_matrix_runout
            WHERE pressing_id = :pressing_id
            """
        ),
        {
            "pressing_id": pressing_id,
        },
    )

    for matrix in matrices:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.pressing_matrix_runout (
                    pressing_id,
                    side,
                    value
                )
                VALUES (
                    :pressing_id,
                    :side,
                    :value
                )
                """
            ),
            {
                "pressing_id":
                    pressing_id,
                "side":
                    matrix.side or "",
                "value":
                    matrix.value,
            },
        )


def save_pressing_reference(
    engine: Engine,
    reference: PressingReference,
    *,
    pressing_id: int | None = None,
    actor: str = "STREAMLIT_PRESSING_REFERENCE",
    reason: str,
) -> dict[str, Any]:
    """Create or update one stable pressing reference.

    Existing release-family artist/title keys cannot be silently
    changed through this editor because one family can own multiple
    pressings.
    """

    cleaned_actor = actor.strip()
    cleaned_reason = reason.strip()

    if not cleaned_actor:
        raise ValueError(
            "actor is required"
        )

    if not cleaned_reason:
        raise ValueError(
            "reason is required"
        )

    artist_key = normalize_identity_key(
        reference.artist
    )
    title_key = normalize_identity_key(
        reference.canonical_title
    )

    primary_matrix = (
        reference.matrices[0].value
        if reference.matrices
        else ""
    )

    country = _clean(
        reference.release_country
    )

    language = _clean(
        reference.release_language
    )

    catalog_number = _clean(
        reference.catalog_number
    )

    label = _clean(
        reference.label
    )

    release_format = (
        reference.release_format.value
    )
    release_type = (
        reference.release_type.value
    )

    with engine.begin() as connection:
        if pressing_id is None:
            family_id = connection.execute(
                text(
                    """
                    INSERT INTO warehouse.release_family (
                        artist_key,
                        title_key,
                        display_artist,
                        display_title,
                        original_release_year
                    )
                    VALUES (
                        :artist_key,
                        :title_key,
                        :display_artist,
                        :display_title,
                        :original_release_year
                    )
                    ON CONFLICT (
                        artist_key,
                        title_key
                    )
                    DO UPDATE SET
                        display_artist =
                            EXCLUDED.display_artist,
                        display_title =
                            EXCLUDED.display_title,
                        updated_at = now()
                    RETURNING id
                    """
                ),
                {
                    "artist_key":
                        artist_key,
                    "title_key":
                        title_key,
                    "display_artist":
                        reference.artist,
                    "display_title":
                        reference.canonical_title,
                    "original_release_year":
                        reference.release_year,
                },
            ).scalar_one()

            existing_id = connection.execute(
                text(
                    """
                    SELECT id
                    FROM warehouse.pressing_identity
                    WHERE release_family_id =
                          :release_family_id
                      AND catalog_number =
                          :catalog_number
                      AND matrix_number =
                          :matrix_number
                      AND region =
                          :region
                      AND media_type =
                          :media_type
                      AND pressing_variant_key = ''
                    LIMIT 1
                    """
                ),
                {
                    "release_family_id":
                        family_id,
                    "catalog_number":
                        catalog_number,
                    "matrix_number":
                        primary_matrix,
                    "region":
                        country,
                    "media_type":
                        release_format,
                },
            ).scalar_one_or_none()

            if existing_id is not None:
                raise ValueError(
                    "An existing pressing already has the "
                    "same legacy natural identity: "
                    f"pressing #{existing_id}."
                )

            generation = (
                "PROMO"
                if (
                    reference.release_type
                    == ReleaseType.PROMO
                )
                else "UNKNOWN"
            )

            pressing_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse.pressing_identity (
                            release_family_id,
                            catalog_number,
                            matrix_number,
                            label_name,
                            region,
                            country,
                            media_type,
                            format_detail,
                            release_year,
                            generation,
                            pressing_variant_key,
                            notes,
                            release_language,
                            release_format,
                            release_type
                        )
                        VALUES (
                            :release_family_id,
                            :catalog_number,
                            :matrix_number,
                            :label_name,
                            :region,
                            :country,
                            :media_type,
                            '',
                            :release_year,
                            :generation,
                            '',
                            :notes,
                            :release_language,
                            :release_format,
                            :release_type
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "release_family_id":
                            family_id,
                        "catalog_number":
                            catalog_number,
                        "matrix_number":
                            primary_matrix,
                        "label_name":
                            label,
                        "region":
                            country,
                        "country":
                            country,
                        "media_type":
                            release_format,
                        "release_year":
                            reference.release_year,
                        "generation":
                            generation,
                        "notes":
                            reference.edition_notes,
                        "release_language":
                            language,
                        "release_format":
                            release_format,
                        "release_type":
                            release_type,
                    },
                ).scalar_one()
            )

            before_state = None
            action = "INSERT"
        else:
            before_state = _get_reference(
                connection,
                pressing_id,
            )

            if before_state is None:
                raise ValueError(
                    f"pressing reference {pressing_id} does not exist"
                )

            if (
                normalize_identity_key(
                    str(
                        before_state[
                            "artist"
                        ]
                    )
                )
                != artist_key
                or normalize_identity_key(
                    str(
                        before_state[
                            "canonical_title"
                        ]
                    )
                )
                != title_key
            ):
                raise ValueError(
                    "Artist/title identify the shared release family "
                    "and cannot be silently changed here. Create a "
                    "new pressing family or use a reviewed family "
                    "merge/correction workflow."
                )

            current_region = connection.execute(
                text(
                    """
                    SELECT region
                    FROM warehouse.pressing_identity
                    WHERE id = :pressing_id
                    """
                ),
                {
                    "pressing_id":
                        pressing_id,
                },
            ).scalar_one()

            region = (
                str(current_region).strip()
                if current_region
                else country
            )

            connection.execute(
                text(
                    """
                    UPDATE warehouse.pressing_identity
                    SET
                        catalog_number =
                            :catalog_number,
                        matrix_number =
                            :matrix_number,
                        label_name =
                            :label_name,
                        region =
                            :region,
                        country =
                            :country,
                        media_type =
                            :media_type,
                        release_year =
                            :release_year,
                        notes =
                            :notes,
                        release_language =
                            :release_language,
                        release_format =
                            :release_format,
                        release_type =
                            :release_type,
                        updated_at =
                            now()
                    WHERE id =
                          :pressing_id
                    """
                ),
                {
                    "pressing_id":
                        pressing_id,
                    "catalog_number":
                        catalog_number,
                    "matrix_number":
                        primary_matrix,
                    "label_name":
                        label,
                    "region":
                        region,
                    "country":
                        country,
                    "media_type":
                        release_format,
                    "release_year":
                        reference.release_year,
                    "notes":
                        reference.edition_notes,
                    "release_language":
                        language,
                    "release_format":
                        release_format,
                    "release_type":
                        release_type,
                },
            )

            action = "UPDATE"

        _replace_matrices(
            connection,
            pressing_id=pressing_id,
            matrices=reference.matrices,
        )

        after_state = _get_reference(
            connection,
            pressing_id,
        )

        if after_state is None:
            raise RuntimeError(
                "saved pressing reference could not be reloaded"
            )

        _audit(
            connection,
            pressing_id=pressing_id,
            action=action,
            before_state=before_state,
            after_state=after_state,
            actor=cleaned_actor,
            reason=cleaned_reason,
        )

        return after_state


def build_reference_from_mapping(
    payload: dict[str, Any],
) -> PressingReference:
    """Build a validated domain reference from UI/import data."""

    raw_matrices = payload.get(
        "matrices",
        []
    )

    matrices = []

    for raw_matrix in raw_matrices:
        if not isinstance(
            raw_matrix,
            dict,
        ):
            continue

        value = str(
            raw_matrix.get(
                "value",
                "",
            )
            or ""
        ).strip()

        if not value:
            continue

        raw_side = raw_matrix.get(
            "side"
        )

        side = (
            str(raw_side)
            if raw_side is not None
            else None
        )

        matrices.append(
            MatrixRunout(
                side=side,
                value=value,
            )
        )

    release_year_value = payload.get(
        "release_year"
    )

    release_year = (
        int(release_year_value)
        if release_year_value
        not in {
            None,
            "",
        }
        else None
    )

    return PressingReference(
        artist=str(
            payload.get(
                "artist",
                "",
            )
        ),
        canonical_title=str(
            payload.get(
                "canonical_title",
                "",
            )
        ),
        catalog_number=payload.get(
            "catalog_number"
        ),
        label=payload.get(
            "label"
        ),
        release_country=payload.get(
            "release_country"
        ),
        release_language=payload.get(
            "release_language"
        ),
        release_year=release_year,
        release_format=ReleaseFormat(
            payload.get(
                "release_format",
                ReleaseFormat.OTHER.value,
            )
        ),
        release_type=ReleaseType(
            payload.get(
                "release_type",
                ReleaseType.UNKNOWN.value,
            )
        ),
        matrices=matrices,
        edition_notes=payload.get(
            "edition_notes"
        ),
    )
