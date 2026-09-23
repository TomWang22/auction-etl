"""Persist Discogs identity onto pressings, assignments, and auctions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.collector_curation import normalize_identity_key
from auction_etl.services.discogs_client import DiscogsClient, DiscogsRateLimitError
from auction_etl.services.discogs_identity import (
    PressingIdentityDraft,
    SearchHit,
    artist_overlaps,
    catalog_token,
    classify_search_hits,
    fold_catalog,
    map_release_payload,
    parse_search_hits,
    shortlist_payload,
    unique_hit_can_auto_fill,
)


logger = logging.getLogger(__name__)


@dataclass
class IdentityFillStats:
    scanned: int = 0
    searched: int = 0
    filled_auto: int = 0
    filled_manual: int = 0
    needs_review: int = 0
    unmatched: int = 0
    reused: int = 0
    images_copied: int = 0
    stopped_reason: str | None = None

    def caption(self) -> str:
        parts = [
            f"{self.filled_auto} filled",
            f"{self.needs_review} need review",
        ]
        if self.unmatched:
            parts.append(f"{self.unmatched} unmatched")
        return " · ".join(parts)


def copy_listing_images(connection: Connection) -> int:
    """Promote staging listing photos onto warehouse.auction.image_url."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction AS auction
            SET image_url = listing.image_url
            FROM staging.listing AS listing
            WHERE auction.marketplace = listing.marketplace
              AND auction.listing_id = listing.listing_id
              AND listing.image_url IS NOT NULL
              AND BTRIM(listing.image_url) <> ''
              AND (
                  auction.image_url IS NULL
                  OR BTRIM(auction.image_url) = ''
              )
            """
        )
    )
    return int(result.rowcount or 0)


def mark_existing_assignments_filled(connection: Connection) -> int:
    """Keep already-assigned sales visible without a Discogs rewrite."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction AS auction
            SET identity_status = 'filled_manual',
                identity_source = COALESCE(auction.identity_source, 'listing'),
                identity_filled_at = COALESCE(auction.identity_filled_at, now()),
                identity_status_changed_at = now()
            FROM warehouse.auction_pressing_assignment AS assignment
            WHERE assignment.marketplace = auction.marketplace
              AND assignment.listing_id = auction.listing_id
              AND auction.identity_status = 'unmatched'
            """
        )
    )
    return int(result.rowcount or 0)


def fill_unmatched_identities(
    engine: Engine,
    *,
    client: DiscogsClient | None = None,
    limit: int | None = None,
    marketplace: str | None = None,
) -> IdentityFillStats:
    """Search Discogs for unmatched warehouse rows and auto-fill dead-on hits."""
    stats = IdentityFillStats()
    discogs = client or DiscogsClient()
    search_cache: dict[str, tuple[SearchHit, ...]] = {}
    release_cache: dict[int, PressingIdentityDraft] = {}

    with engine.begin() as connection:
        stats.images_copied = copy_listing_images(connection)
        stats.filled_manual = mark_existing_assignments_filled(connection)
        rows = list(_load_candidates(connection, marketplace=marketplace, limit=limit))
    stats.scanned = len(rows)

    for row in rows:
        token = catalog_token(
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
        )
        if not token:
            stats.unmatched += 1
            continue
        cache_key = fold_catalog(token)
        try:
            if cache_key not in search_cache:
                search_cache[cache_key] = discogs.search_releases(catno=token)
                stats.searched += 1
            hits = search_cache[cache_key]
            classification = classify_search_hits(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
                artist=row.get("artist"),
                media_type=row.get("media_type"),
                hits=hits,
            )
            if (
                classification.status == "filled_auto"
                and classification.chosen is not None
            ):
                _release_draft(
                    discogs,
                    classification.chosen.discogs_id,
                    release_cache,
                )
            elif (
                classification.status == "needs_review"
                and classification.reason == "artist_mismatch"
                and len(classification.hits) == 1
            ):
                _release_draft(
                    discogs,
                    classification.hits[0].discogs_id,
                    release_cache,
                )
            with engine.begin() as connection:
                outcome = _fill_one_row(
                    connection,
                    row=row,
                    client=discogs,
                    search_cache=search_cache,
                    release_cache=release_cache,
                    stats=stats,
                )
        except DiscogsRateLimitError as error:
            stats.stopped_reason = str(error)
            logger.warning("Discogs identity fill stopped: rate limit")
            break
        except httpx.HTTPError:
            stats.stopped_reason = "discogs_http_error"
            logger.warning("Discogs identity fill stopped: HTTP error")
            break
        except Exception:
            logger.warning(
                "identity fill skipped %s %s",
                row.get("marketplace"),
                row.get("listing_id"),
            )
            stats.unmatched += 1
            continue

        if outcome == "filled_auto":
            stats.filled_auto += 1
        elif outcome == "needs_review":
            stats.needs_review += 1
        else:
            stats.unmatched += 1

    _promote_unique_shortlists(
        engine,
        client=discogs,
        release_cache=release_cache,
        stats=stats,
    )
    return stats


def apply_release_choice(
    engine: Engine,
    *,
    marketplace: str,
    listing_id: str,
    release_id: int,
    discogs_label_id: int | None = None,
    client: DiscogsClient | None = None,
) -> dict[str, Any]:
    """Operator click: persist one Discogs release as filled_manual."""
    discogs = client or DiscogsClient()
    payload = discogs.get_release(release_id)
    draft = map_release_payload(payload)
    if draft.requires_label_choice and discogs_label_id is None:
        raise ValueError("This release has more than one label; choose one.")
    if discogs_label_id is not None:
        draft = _choose_label(draft, discogs_label_id)

    with engine.begin() as connection:
        pressing_id = upsert_pressing(connection, draft)
        _assign_pressing(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            pressing_id=pressing_id,
            match_basis="MANUAL",
            manual=True,
        )
        _set_auction_identity(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            status="filled_manual",
            source="discogs",
            thumb_url=draft.discogs_thumb_url,
            shortlist=None,
        )
        return {
            "pressing_id": pressing_id,
            "identity_status": "filled_manual",
            "discogs_release_id": draft.discogs_release_id,
        }


def upsert_pressing(
    connection: Connection,
    draft: PressingIdentityDraft,
) -> int:
    """Insert or reuse the canonical pressing for one Discogs release."""
    existing = connection.execute(
        text(
            """
            SELECT id
            FROM warehouse.pressing_identity
            WHERE discogs_release_id = :release_id
            """
        ),
        {"release_id": draft.discogs_release_id},
    ).scalar()
    if existing is not None:
        return int(existing)

    label_id = _upsert_label(connection, draft)
    artist_key = normalize_identity_key(draft.display_artist or draft.display_title)
    title_key = normalize_identity_key(draft.display_title or draft.display_artist)
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
            ON CONFLICT (artist_key, title_key)
            DO UPDATE SET
                display_artist = EXCLUDED.display_artist,
                display_title = EXCLUDED.display_title,
                original_release_year = COALESCE(
                    warehouse.release_family.original_release_year,
                    EXCLUDED.original_release_year
                ),
                updated_at = now()
            RETURNING id
            """
        ),
        {
            "artist_key": artist_key,
            "title_key": title_key,
            "display_artist": draft.display_artist or draft.display_title,
            "display_title": draft.display_title,
            "original_release_year": draft.release_year,
        },
    ).scalar_one()

    natural = connection.execute(
        text(
            """
            SELECT id
            FROM warehouse.pressing_identity
            WHERE release_family_id = :release_family_id
              AND catalog_number = :catalog_number
              AND matrix_number = :matrix_number
              AND region = :region
              AND media_type = :media_type
              AND pressing_variant_key = ''
            """
        ),
        {
            "release_family_id": int(family_id),
            "catalog_number": draft.catalog_number,
            "matrix_number": draft.matrix_number or "",
            "region": draft.region or "",
            "media_type": draft.media_type,
        },
    ).scalar()
    if natural is not None:
        connection.execute(
            text(
                """
                UPDATE warehouse.pressing_identity
                SET label_name = :label_name,
                    label_id = COALESCE(label_id, :label_id),
                    country = :country,
                    format_detail = :format_detail,
                    disc_count = COALESCE(disc_count, :disc_count),
                    release_year = COALESCE(release_year, :release_year),
                    generation = CASE
                        WHEN generation = 'UNKNOWN' THEN :generation
                        ELSE generation
                    END,
                    notes = COALESCE(notes, :notes),
                    discogs_release_id = COALESCE(
                        discogs_release_id,
                        :discogs_release_id
                    ),
                    discogs_master_id = COALESCE(
                        discogs_master_id,
                        :discogs_master_id
                    ),
                    discogs_uri = COALESCE(discogs_uri, :discogs_uri),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": int(natural),
                "label_name": draft.label_name or "",
                "label_id": label_id,
                "country": draft.country or "",
                "format_detail": draft.format_detail or "",
                "disc_count": draft.disc_count,
                "release_year": draft.release_year,
                "generation": draft.generation,
                "notes": draft.notes_hint,
                "discogs_release_id": draft.discogs_release_id,
                "discogs_master_id": draft.discogs_master_id,
                "discogs_uri": draft.discogs_uri,
            },
        )
        return int(natural)

    pressing_id = connection.execute(
        text(
            """
            INSERT INTO warehouse.pressing_identity (
                release_family_id,
                catalog_number,
                matrix_number,
                label_name,
                label_id,
                region,
                country,
                media_type,
                format_detail,
                disc_count,
                release_year,
                generation,
                pressing_variant_key,
                is_first_press,
                notes,
                discogs_release_id,
                discogs_master_id,
                discogs_uri
            )
            VALUES (
                :release_family_id,
                :catalog_number,
                :matrix_number,
                :label_name,
                :label_id,
                :region,
                :country,
                :media_type,
                :format_detail,
                :disc_count,
                :release_year,
                :generation,
                '',
                FALSE,
                :notes,
                :discogs_release_id,
                :discogs_master_id,
                :discogs_uri
            )
            RETURNING id
            """
        ),
        {
            "release_family_id": int(family_id),
            "catalog_number": draft.catalog_number,
            "matrix_number": draft.matrix_number or "",
            "label_name": draft.label_name or "",
            "label_id": label_id,
            "region": draft.region or "",
            "country": draft.country or "",
            "media_type": draft.media_type,
            "format_detail": draft.format_detail or "",
            "disc_count": draft.disc_count,
            "release_year": draft.release_year,
            "generation": draft.generation,
            "notes": draft.notes_hint,
            "discogs_release_id": draft.discogs_release_id,
            "discogs_master_id": draft.discogs_master_id,
            "discogs_uri": draft.discogs_uri,
        },
    ).scalar_one()
    return int(pressing_id)


def _fill_one_row(
    connection: Connection,
    *,
    row: dict[str, Any],
    client: DiscogsClient,
    search_cache: dict[str, tuple[SearchHit, ...]],
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
) -> str:
    marketplace = str(row["marketplace"])
    listing_id = str(row["listing_id"])
    token = catalog_token(
        catalog_number=row.get("catalog_number"),
        title=row.get("title"),
    )
    reused = _reuse_local_pressing(connection, row=row, token=token)
    if reused is not None:
        stats.reused += 1
        return "filled_auto"

    if not token:
        _set_auction_identity(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            status="unmatched",
            source="listing",
            thumb_url=None,
            shortlist=[],
        )
        return "unmatched"

    cache_key = fold_catalog(token)
    if cache_key not in search_cache:
        search_cache[cache_key] = client.search_releases(catno=token)
        stats.searched += 1
    hits = search_cache[cache_key]

    remaining_classification = classify_search_hits(
        catalog_number=row.get("catalog_number"),
        title=row.get("title"),
        artist=row.get("artist"),
        media_type=row.get("media_type"),
        hits=hits,
    )
    candidate = remaining_classification.chosen
    if (
        candidate is None
        and remaining_classification.status == "needs_review"
        and remaining_classification.reason == "artist_mismatch"
        and len(remaining_classification.hits) == 1
    ):
        candidate = remaining_classification.hits[0]
    if candidate is not None:
        draft = _release_draft(
            client,
            candidate.discogs_id,
            release_cache,
        )
        if draft.requires_label_choice:
            _flag_needs_review(
                connection,
                marketplace=marketplace,
                listing_id=listing_id,
                hits=remaining_classification.hits or (candidate,),
                thumb_url=draft.discogs_thumb_url,
            )
            return "needs_review"
        if unique_hit_can_auto_fill(
            remaining_classification,
            listing_artist=row.get("artist"),
            listing_title=row.get("title"),
            release_artist_names=draft.artist_names,
        ):
            pressing_id = upsert_pressing(connection, draft)
            _assign_pressing(
                connection,
                marketplace=marketplace,
                listing_id=listing_id,
                pressing_id=pressing_id,
                match_basis="CATALOG_EXACT",
                manual=False,
            )
            _set_auction_identity(
                connection,
                marketplace=marketplace,
                listing_id=listing_id,
                status="filled_auto",
                source="discogs",
                thumb_url=draft.discogs_thumb_url,
                shortlist=shortlist_payload(remaining_classification.hits or (candidate,)),
            )
            return "filled_auto"

    if remaining_classification.status == "needs_review":
        _flag_needs_review(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            hits=remaining_classification.hits,
            thumb_url=(
                remaining_classification.hits[0].thumb_url
                if remaining_classification.hits
                else None
            ),
        )
        return "needs_review"

    _set_auction_identity(
        connection,
        marketplace=marketplace,
        listing_id=listing_id,
        status="unmatched",
        source="listing",
        thumb_url=None,
        shortlist=shortlist_payload(hits),
    )
    return "unmatched"


def _release_draft(
    client: DiscogsClient,
    release_id: int,
    cache: dict[int, PressingIdentityDraft],
) -> PressingIdentityDraft:
    if release_id not in cache:
        cache[release_id] = map_release_payload(client.get_release(release_id))
    return cache[release_id]


def _promote_unique_shortlists(
    engine: Engine,
    *,
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
) -> None:
    """Auto-fill unique cached shortlists whose Latin artist names overlap."""
    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        marketplace,
                        listing_id,
                        artist,
                        title,
                        catalog_number,
                        media_type,
                        discogs_shortlist
                    FROM warehouse.auction
                    WHERE identity_status = 'needs_review'
                      AND jsonb_typeof(discogs_shortlist) = 'array'
                      AND jsonb_array_length(discogs_shortlist) = 1
                    ORDER BY marketplace, listing_id
                    """
                )
            ).mappings()
        ]

    for row in rows:
        raw_hits = row.get("discogs_shortlist") or []
        if isinstance(raw_hits, str):
            raw_hits = json.loads(raw_hits)
        hits = parse_search_hits(raw_hits)
        if len(hits) != 1:
            continue
        try:
            draft = _release_draft(client, hits[0].discogs_id, release_cache)
            classification = classify_search_hits(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
                artist=row.get("artist"),
                media_type=row.get("media_type"),
                hits=hits,
                discogs_artist_names=draft.artist_names,
            )
            if not unique_hit_can_auto_fill(
                classification,
                listing_artist=row.get("artist"),
                listing_title=row.get("title"),
                release_artist_names=draft.artist_names,
            ):
                continue
            if draft.requires_label_choice:
                continue
            with engine.begin() as connection:
                pressing_id = upsert_pressing(connection, draft)
                _assign_pressing(
                    connection,
                    marketplace=str(row["marketplace"]),
                    listing_id=str(row["listing_id"]),
                    pressing_id=pressing_id,
                    match_basis="CATALOG_EXACT",
                    manual=False,
                )
                _set_auction_identity(
                    connection,
                    marketplace=str(row["marketplace"]),
                    listing_id=str(row["listing_id"]),
                    status="filled_auto",
                    source="discogs",
                    thumb_url=draft.discogs_thumb_url,
                    shortlist=shortlist_payload(hits),
                )
            stats.filled_auto += 1
            if stats.needs_review > 0:
                stats.needs_review -= 1
        except DiscogsRateLimitError:
            stats.stopped_reason = "rate_limit"
            logger.warning("Discogs identity fill stopped: rate limit")
            break
        except httpx.HTTPError:
            stats.stopped_reason = "discogs_http_error"
            logger.warning("Discogs identity fill stopped: HTTP error")
            break
        except Exception:
            logger.warning(
                "identity promote skipped %s %s",
                row.get("marketplace"),
                row.get("listing_id"),
            )


def _reuse_local_pressing(
    connection: Connection,
    *,
    row: dict[str, Any],
    token: str | None,
) -> int | None:
    if not token:
        return None
    folded = fold_catalog(token)
    matches = connection.execute(
        text(
            """
            SELECT
                pressing.id,
                pressing.discogs_release_id,
                pressing.discogs_uri,
                family.display_artist,
                family.display_title
            FROM warehouse.pressing_identity AS pressing
            JOIN warehouse.release_family AS family
              ON family.id = pressing.release_family_id
            WHERE regexp_replace(upper(pressing.catalog_number), '[^A-Z0-9]', '', 'g')
                  = :folded
              AND pressing.discogs_release_id IS NOT NULL
            """
        ),
        {"folded": folded},
    ).mappings().all()
    if len(matches) != 1:
        return None
    match = dict(matches[0])
    names = [
        str(match.get("display_artist") or ""),
        str(match.get("display_title") or ""),
    ]
    if not artist_overlaps(
        listing_artist=row.get("artist"),
        listing_title=row.get("title"),
        discogs_names=names,
    ):
        return None
    pressing_id = int(match["id"])
    _assign_pressing(
        connection,
        marketplace=str(row["marketplace"]),
        listing_id=str(row["listing_id"]),
        pressing_id=pressing_id,
        match_basis="CATALOG_EXACT",
        manual=False,
    )
    thumb = connection.execute(
        text(
            """
            SELECT discogs_thumb_url
            FROM warehouse.auction
            WHERE discogs_thumb_url IS NOT NULL
              AND BTRIM(discogs_thumb_url) <> ''
              AND (marketplace, listing_id) IN (
                  SELECT marketplace, listing_id
                  FROM warehouse.auction_pressing_assignment
                  WHERE pressing_id = :pressing_id
              )
            LIMIT 1
            """
        ),
        {"pressing_id": pressing_id},
    ).scalar()
    _set_auction_identity(
        connection,
        marketplace=str(row["marketplace"]),
        listing_id=str(row["listing_id"]),
        status="filled_auto",
        source="discogs",
        thumb_url=str(thumb) if thumb else None,
        shortlist=None,
    )
    return pressing_id


def _load_candidates(
    connection: Connection,
    *,
    marketplace: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            marketplace,
            listing_id,
            artist,
            title,
            catalog_number,
            media_type
        FROM warehouse.auction
        WHERE identity_status = 'unmatched'
          AND discogs_shortlist_fetched_at IS NULL
    """
    params: dict[str, Any] = {}
    if marketplace:
        sql += " AND marketplace = :marketplace"
        params["marketplace"] = marketplace
    sql += """
        ORDER BY
            CASE
                WHEN catalog_number IS NOT NULL
                 AND BTRIM(catalog_number) <> ''
                THEN 0
                ELSE 1
            END,
            marketplace,
            listing_id
    """
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)
    return [dict(row) for row in connection.execute(text(sql), params).mappings()]


def _upsert_label(
    connection: Connection,
    draft: PressingIdentityDraft,
) -> int | None:
    if draft.requires_label_choice or not draft.label_name:
        return None
    if draft.discogs_label_id is not None:
        existing = connection.execute(
            text(
                """
                SELECT id
                FROM warehouse.label
                WHERE discogs_label_id = :discogs_label_id
                """
            ),
            {"discogs_label_id": draft.discogs_label_id},
        ).scalar()
        if existing is not None:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.label
                    SET display_name = :display_name,
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "display_name": draft.label_name,
                    "id": int(existing),
                },
            )
            return int(existing)
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO warehouse.label (
                        display_name,
                        discogs_label_id
                    )
                    VALUES (
                        :display_name,
                        :discogs_label_id
                    )
                    RETURNING id
                    """
                ),
                {
                    "display_name": draft.label_name,
                    "discogs_label_id": draft.discogs_label_id,
                },
            ).scalar_one()
        )
    existing = connection.execute(
        text(
            """
            SELECT id
            FROM warehouse.label
            WHERE lower(btrim(display_name)) = lower(btrim(:display_name))
            LIMIT 1
            """
        ),
        {"display_name": draft.label_name},
    ).scalar()
    if existing is not None:
        return int(existing)
    return int(
        connection.execute(
            text(
                """
                INSERT INTO warehouse.label (display_name)
                VALUES (:display_name)
                RETURNING id
                """
            ),
            {"display_name": draft.label_name},
        ).scalar_one()
    )


def _assign_pressing(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
    match_basis: str,
    manual: bool,
) -> None:
    account_id = connection.execute(
        text(
            """
            SELECT account_id
            FROM account.auction_listing
            WHERE lower(btrim(marketplace)) = lower(btrim(:marketplace))
              AND listing_id = :listing_id
            LIMIT 1
            """
        ),
        {"marketplace": marketplace, "listing_id": listing_id},
    ).scalar()
    connection.execute(
        text(
            """
            INSERT INTO warehouse.auction_pressing_assignment (
                account_id,
                marketplace,
                listing_id,
                pressing_id,
                match_basis,
                match_confidence,
                is_manual_override,
                notes,
                assigned_at,
                updated_at
            )
            VALUES (
                :account_id,
                :marketplace,
                :listing_id,
                :pressing_id,
                :match_basis,
                1.0,
                :manual,
                :notes,
                now(),
                now()
            )
            ON CONFLICT (marketplace, listing_id)
            DO UPDATE SET
                pressing_id = EXCLUDED.pressing_id,
                match_basis = EXCLUDED.match_basis,
                match_confidence = EXCLUDED.match_confidence,
                is_manual_override = EXCLUDED.is_manual_override,
                notes = EXCLUDED.notes,
                updated_at = now()
            """
        ),
        {
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
            "pressing_id": pressing_id,
            "match_basis": match_basis,
            "manual": manual,
            "notes": "discogs identity fill",
        },
    )


def _flag_needs_review(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    hits: tuple[SearchHit, ...],
    thumb_url: str | None,
) -> None:
    _set_auction_identity(
        connection,
        marketplace=marketplace,
        listing_id=listing_id,
        status="needs_review",
        source="discogs",
        thumb_url=thumb_url,
        shortlist=shortlist_payload(hits),
    )


def _set_auction_identity(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    status: str,
    source: str | None,
    thumb_url: str | None,
    shortlist: list[dict[str, Any]] | None,
) -> None:
    connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET identity_status = :status,
                identity_source = :source,
                identity_filled_at = CASE
                    WHEN :status IN ('filled_auto', 'filled_manual')
                    THEN now()
                    ELSE identity_filled_at
                END,
                identity_status_changed_at = now(),
                discogs_thumb_url = COALESCE(:thumb_url, discogs_thumb_url),
                discogs_shortlist = COALESCE(
                    CAST(:shortlist AS jsonb),
                    discogs_shortlist
                ),
                discogs_shortlist_fetched_at = CASE
                    WHEN CAST(:shortlist AS jsonb) IS NULL
                    THEN discogs_shortlist_fetched_at
                    ELSE now()
                END
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """
        ),
        {
            "status": status,
            "source": source,
            "thumb_url": thumb_url,
            "shortlist": None if shortlist is None else json.dumps(shortlist),
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    )


def _choose_label(
    draft: PressingIdentityDraft,
    discogs_label_id: int,
) -> PressingIdentityDraft:
    chosen = next(
        (
            label
            for label in draft.labels
            if label.discogs_label_id == discogs_label_id
        ),
        None,
    )
    if chosen is None:
        raise ValueError("Chosen Discogs label is not on this release.")
    return PressingIdentityDraft(
        discogs_release_id=draft.discogs_release_id,
        discogs_master_id=draft.discogs_master_id,
        discogs_uri=draft.discogs_uri,
        discogs_thumb_url=draft.discogs_thumb_url,
        display_artist=draft.display_artist,
        display_title=draft.display_title,
        artist_names=draft.artist_names,
        label_name=chosen.display_name,
        discogs_label_id=chosen.discogs_label_id,
        labels=draft.labels,
        requires_label_choice=False,
        catalog_number=chosen.catno or draft.catalog_number,
        matrix_number=draft.matrix_number,
        country=draft.country,
        region=draft.region,
        media_type=draft.media_type,
        format_detail=draft.format_detail,
        disc_count=draft.disc_count,
        release_year=draft.release_year,
        generation=draft.generation,
        is_first_press=False,
        notes_hint=draft.notes_hint,
        component_expectations=(),
    )


def identity_counts(engine: Engine) -> dict[str, int]:
    """Return warehouse identity_status totals."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT identity_status, COUNT(*)
                FROM warehouse.auction
                GROUP BY identity_status
                """
            )
        ).all()
    counts = {str(status): int(count) for status, count in rows}
    return {
        "filled_auto": counts.get("filled_auto", 0),
        "filled_manual": counts.get("filled_manual", 0),
        "needs_review": counts.get("needs_review", 0),
        "unmatched": counts.get("unmatched", 0),
        "filled": counts.get("filled_auto", 0) + counts.get("filled_manual", 0),
    }
