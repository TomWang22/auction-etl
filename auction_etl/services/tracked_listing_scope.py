"""Keep operator surfaces on the artists this account actually tracks."""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.discogs_identity import artist_overlaps


def _optional_listing_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "<na>", "nat"}:
        return None
    return text


def _account_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid UUID: {value!r}") from exc


def enabled_tracked_artist_names(
    bind: Engine | Connection,
    *,
    account_id: uuid.UUID | str | None = None,
) -> tuple[str, ...]:
    """Enabled tracked-artist names, or empty when tracking is not configured."""

    def fetch(connection: Connection) -> tuple[str, ...]:
        try:
            if not inspect(connection).has_table(
                "tracked_artist",
                schema="account",
            ):
                return ()
        except Exception:
            return ()
        sql = """
            SELECT DISTINCT name
            FROM account.tracked_artist
            WHERE COALESCE(enabled, true) IS TRUE
              AND NULLIF(BTRIM(name), '') IS NOT NULL
        """
        params: dict[str, Any] = {}
        if account_id is not None:
            sql += " AND account_id = :account_id"
            params["account_id"] = _account_uuid(account_id)
        sql += " ORDER BY name"
        return tuple(
            str(row[0]).strip()
            for row in connection.execute(text(sql), params)
            if row[0] and str(row[0]).strip()
        )

    if isinstance(bind, Engine):
        with bind.connect() as connection:
            return fetch(connection)
    return fetch(bind)


def listing_belongs_to_tracked_artists(
    *,
    title: object = None,
    artist: object = None,
    tracked_names: Sequence[str],
) -> bool:
    """True when the listing is one of the artists this account tracks.

    An empty tracked-name list means tracking is not configured, so the
    listing stays visible. That keeps tests and empty accounts intact.

    A shared family name is not enough: ``Goro Yamaguchi`` must not count
    as Momoe, and ``Mioko Yamaguchi`` must not either.
    """
    names = tuple(
        str(name).strip()
        for name in tracked_names
        if str(name or "").strip()
    )
    if not names:
        return True
    listing_artist = _optional_listing_text(artist)
    listing_title = _optional_listing_text(title)
    if not artist_overlaps(
        listing_artist=listing_artist,
        listing_title=listing_title,
        discogs_names=names,
    ):
        return False
    blob_cf = f"{listing_artist or ''} {listing_title or ''}".casefold()
    given_names: list[str] = []
    family_names: list[str] = []
    for name in names:
        parts = [
            part.casefold()
            for part in name.split()
            if part.isascii() and part.isalpha() and len(part) >= 3
        ]
        if len(parts) >= 2 and all(part in blob_cf for part in parts):
            return True
        if parts:
            given_names.append(parts[0])
            if len(parts) >= 2:
                family_names.append(parts[-1])
    if any(token in blob_cf for token in (*given_names, *family_names)):
        return False
    return True
