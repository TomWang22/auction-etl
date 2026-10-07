"""Persist Discogs identity onto pressings, assignments, and auctions."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Sequence

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.reporting.main_review_integration import (
    description_catalog,
    gripsweat_original_listing_id,
    parse_gripsweat_title,
)
from auction_etl.parsers.buyee import is_placeholder_image
from auction_etl.parsers.buyee import parse_image as parse_buyee_image
from auction_etl.parsers.ebay import parse_image as parse_ebay_image
from auction_etl.classifiers.labels import extract_record_label
from auction_etl.classifiers.media import classify_media_details, is_job_lot
from auction_etl.services.tracked_listing_scope import (
    enabled_tracked_artist_names,
    listing_belongs_to_tracked_artists,
)
from auction_etl.services.collector_curation import normalize_identity_key
from auction_etl.services.cjk_text import fold_hanzi, hanzi_variants
from auction_etl.services.discogs_client import DiscogsClient, DiscogsRateLimitError, DiscogsUnavailableError
from auction_etl.services.discogs_cover import (
    COVER_MAX_DISTANCE,
    COVER_SHORTLIST_MAX_DISTANCE,
    COVER_SHORTLIST_UNIQUE_GAP,
    COVER_UNIQUE_GAP,
    choose_cover_hit_multi,
    choose_cover_match_multi,
    best_listing_cover_distance,
    fetch_image,
    hash_image_url,
    hamming_distance,
    image_hashes,
    listing_agrees_with_cover,
    listing_color_side,
    listing_cover_hashes,
    image_color_side,
    rank_cover_hits,
)
from auction_etl.services.discogs_identity import (
    Classification,
    PressingIdentityDraft,
    SearchHit,
    artist_from_english_title,
    artist_overlaps,
    canonical_artist_key,
    canonical_title_key,
    catalog_has_range,
    catalog_identity_key,
    catalog_printed_on_listing,
    catalog_search_variants,
    catalog_token,
    printed_matrix_on_discogs,
    catno_covers_listing_token,
    catno_locks_listing,
    catalog_letter_prefix,
    covering_hits_for_listing,
    classify_search_hits,
    discogs_search_format,
    fold_catalog,
    hit_fits_listing_year,
    hit_is_modern_reissue,
    inferred_release_catalog,
    known_album_phrase,
    equivalent_title_spellings,
    hit_bundles_other_album,
    is_junk_catalog,
    is_modern_reissue_catalog,
    listing_barcode,
    listing_identity_catalog,
    listing_media_compatible,
    listing_preferred_country,
    listing_search_artist,
    media_family,
    listing_title_wants_seven_inch,
    listing_is_promo,
    listing_wants_original_pressing,
    original_pressing_for_promo_copy,
    listing_label_hints,
    listing_volume_number,
    is_generic_songbook_album,
    extract_release_year,
    prefer_listing_generation,
    prefer_listing_label,
    map_release_payload,
    names_from_search_hit,
    parse_search_hits,
    refine_hits_for_listing,
    search_artist,
    shortlist_format_options,
    shortlist_option_shape,
    shortlist_payload,
    unique_hit_can_auto_fill,
    effective_listing_media,
    title_claims_reissue,
    apply_title_aliases,
    album_name_in_listing,
    bare_best_hit_title,
    best_hit_album_title,
    listing_names_other_work,
    artist_local_name,
    concert_program_related,
    listing_is_self_titled,
    listing_names_specific_album,
    stored_catalog_fits_listing,
    catalog_fits_listing_media,
    _is_known_album_title,
    _is_known_artist_name,
    _ARTIST_CANON,
    _known_catalog_prefix,
    _listing_leftover_album_compact,
    _release_album_key,
    _script_compact,
    _slash_part_is_noise,
    _unique_shortlist_catno,
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
    images_backfilled: int = 0
    junk_cleared: int = 0
    shortlists_promoted: int = 0
    cover_matched: int = 0
    search_errors: int = 0
    leftover_researched: int = 0
    stopped_reason: str | None = None
    ingest_fail_fast: bool = False
    deadline: float | None = None
    budget_exhausted: bool = False
    aborted: bool = False

    def caption(self) -> str:
        parts = [
            f"{self.filled_auto} filled",
            f"{self.needs_review} need review",
        ]
        if self.unmatched:
            parts.append(f"{self.unmatched} unmatched")
        if self.cover_matched:
            parts.append(f"{self.cover_matched} cover-matched")
        if self.stopped_reason:
            parts.append("stopped early")
        return " · ".join(parts)


def _clear_currency_labels(connection: Connection) -> int:
    """Yen in a Buyee title is a price, not YEN Records."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET label = NULL
            WHERE label IS NOT NULL
              AND (
                  BTRIM(label) ~* '^yen$'
                  OR BTRIM(label) ~* '^[0-9][0-9,.]*[[:space:]]*yen$'
              )
            """
        )
    )
    return int(result.rowcount or 0)


def _reset_unmatched_for_retune(connection: Connection) -> int:
    """Re-search unmatched rows that never went through artist/format/title lookup."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET discogs_shortlist_fetched_at = NULL
            WHERE identity_status = 'unmatched'
              AND COALESCE(identity_source, 'listing') <> 'discogs'
              AND discogs_shortlist_fetched_at IS NOT NULL
            """
        )
    )
    return int(result.rowcount or 0)


def _retag_and_park_job_lots(connection: Connection) -> int:
    """Mark leftover boxes as lots and keep them off Discogs identity."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, title, catalog_number,
                   bulk_lot, identity_status
            FROM warehouse.auction
            """
        )
    ).mappings().all()
    parked = 0
    for row in rows:
        title = str(row.get("title") or "")
        catalog = str(row.get("catalog_number") or "").strip() or None
        media = classify_media_details(title)
        job = is_job_lot(title)
        bulk = bool(media.bulk_lot or job)
        junk = bool(catalog and is_junk_catalog(catalog, title=title))
        status = str(row.get("identity_status") or "")
        was_bulk = bool(row.get("bulk_lot"))
        park = job and status in {"unmatched", "needs_review"}
        unpark = was_bulk and not job and status in {"unmatched", "needs_review"}
        if (
            bulk == was_bulk
            and not junk
            and not park
            and not unpark
        ):
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET bulk_lot = CAST(:bulk_lot AS boolean),
                    catalog_number = CASE
                        WHEN CAST(:clear_catalog AS boolean)
                        THEN NULL
                        ELSE catalog_number
                    END,
                    identity_status = CASE
                        WHEN CAST(:park AS boolean)
                        THEN 'unmatched'
                        ELSE identity_status
                    END,
                    identity_source = CASE
                        WHEN CAST(:park AS boolean)
                        THEN 'listing'
                        ELSE identity_source
                    END,
                    discogs_shortlist = CASE
                        WHEN CAST(:park AS boolean)
                        THEN '[]'::jsonb
                        ELSE discogs_shortlist
                    END,
                    discogs_shortlist_fetched_at = CASE
                        WHEN CAST(:park AS boolean)
                        THEN now()
                        WHEN CAST(:unpark AS boolean)
                        THEN NULL
                        ELSE discogs_shortlist_fetched_at
                    END,
                    discogs_thumb_url = CASE
                        WHEN CAST(:park AS boolean)
                        THEN NULL
                        ELSE discogs_thumb_url
                    END,
                    identity_status_changed_at = CASE
                        WHEN CAST(:park AS boolean) OR CAST(:unpark AS boolean)
                        THEN now()
                        ELSE identity_status_changed_at
                    END
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "bulk_lot": bulk,
                "clear_catalog": junk,
                "park": park,
                "unpark": unpark,
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )
        parked += int(park)
    return parked


def _reset_photographed_empty_shortlists(connection: Connection) -> int:
    """Re-search leftover records whose last Discogs pass returned no hits."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET discogs_shortlist_fetched_at = NULL
            WHERE identity_status = 'unmatched'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND COALESCE(media_type, '') NOT IN (
                  'MAGAZINE', 'PHOTO', 'PHOTOBOOK', 'PRINT', 'STAMP',
                  'USB', 'DVD', 'VHS', 'LASERDISC', 'SHEET_MUSIC', 'TOY'
              )
              AND (
                  discogs_shortlist IS NULL
                  OR jsonb_typeof(discogs_shortlist) <> 'array'
                  OR jsonb_array_length(discogs_shortlist) = 0
              )
            """
        )
    )
    return int(result.rowcount or 0)


def _reset_format_and_region_misses(connection: Connection) -> int:
    """Re-search LPs, CDs, 7\" singles, and Anita pieces with empty shortlists."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET discogs_shortlist_fetched_at = NULL
            WHERE identity_status = 'unmatched'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND (
                  discogs_shortlist IS NULL
                  OR jsonb_typeof(discogs_shortlist) <> 'array'
                  OR jsonb_array_length(discogs_shortlist) = 0
              )
              AND (
                    COALESCE(media_type, '') ILIKE 'LP%'
                 OR COALESCE(media_type, '') ILIKE 'VINYL%'
                 OR COALESCE(media_type, '') ILIKE 'CD%'
                 OR COALESCE(media_type, '') ILIKE 'EP%'
                 OR COALESCE(media_type, '') ILIKE '%12_INCH%'
                 OR COALESCE(media_type, '') ILIKE 'CASSETTE%'
                 OR title ~ 'シングル'
                 OR title ~ '梅艷芳|梅艳芳|Anita Mui|Anita|山口百恵|テレサ|鄧麗君|邓丽君'
                 OR title ~* 'momoe yamaguchi|teresa teng'
                 OR (
                    catalog_number IS NOT NULL
                    AND BTRIM(catalog_number) <> ''
                 )
              )
              AND (
                    title ~ '[\u3040-\u9fff]'
                 OR title ~ '梅艷芳|梅艳芳|Anita Mui|Anita|山口百恵|テレサ|鄧麗君|邓丽君'
                 OR title ~* 'momoe yamaguchi|teresa teng|anita mui|paula tsui'
                 OR title ~ '[「『《\"]'
                 OR (
                    catalog_number IS NOT NULL
                    AND BTRIM(catalog_number) <> ''
                 )
              )
            """
        )
    )
    return int(result.rowcount or 0)


def _reset_empty_review_shortlists(connection: Connection) -> int:
    """Empty review rows cannot be decided; re-search them as unmatched."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET identity_status = 'unmatched',
                discogs_shortlist = '[]'::jsonb,
                discogs_shortlist_fetched_at = NULL,
                discogs_thumb_url = NULL,
                identity_status_changed_at = now()
            WHERE identity_status = 'needs_review'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND (
                  discogs_shortlist IS NULL
                  OR jsonb_typeof(discogs_shortlist) <> 'array'
                  OR jsonb_array_length(discogs_shortlist) = 0
              )
            """
        )
    )
    return int(result.rowcount or 0)


def _reset_extractable_latin_unmatched(connection: Connection) -> int:
    """Re-search romanized titles whose artist can now be read from the title."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, artist, title
            FROM warehouse.auction
            WHERE identity_status = 'unmatched'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND discogs_shortlist_fetched_at IS NOT NULL
              AND (
                  discogs_shortlist IS NULL
                  OR jsonb_typeof(discogs_shortlist) <> 'array'
                  OR jsonb_array_length(discogs_shortlist) = 0
              )
              AND title !~ '[\u3040-\u9fff]'
            """
        )
    ).mappings().all()
    reset = 0
    for row in rows:
        title = str(row.get("title") or "")
        if is_job_lot(title):
            continue
        if not (
            listing_search_artist(row.get("artist"), title)
            or artist_from_english_title(title)
        ):
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET discogs_shortlist_fetched_at = NULL
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )
        reset += 1
    return reset


def _reset_piece_identity_misses(connection: Connection) -> int:
    """Re-search individual records whose catalog match was empty or colliding."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, title, catalog_number,
                   artist, media_type, identity_status, discogs_shortlist,
                   bulk_lot
            FROM warehouse.auction
            WHERE identity_status IN ('unmatched', 'needs_review')
              AND COALESCE(bulk_lot, false) IS NOT TRUE
            """
        )
    ).mappings().all()
    reset = 0
    for row in rows:
        title = str(row.get("title") or "")
        if is_job_lot(title):
            continue
        raw_hits = row.get("discogs_shortlist") or []
        if isinstance(raw_hits, str):
            raw_hits = json.loads(raw_hits)
        hits = parse_search_hits(raw_hits) if raw_hits else ()
        empty = len(hits) == 0
        collision = (
            len(hits) == 1
            and not artist_overlaps(
                listing_artist=str(row.get("artist") or "") or None,
                listing_title=title,
                discogs_names=names_from_search_hit(hits[0]),
            )
        )
        status = str(row.get("identity_status") or "")
        retry = False
        if status == "needs_review" and (empty or collision):
            retry = True
        if (
            not retry
            and status == "needs_review"
            and len(hits) == 1
        ):
            classified = classify_search_hits(
                catalog_number=row.get("catalog_number"),
                title=title,
                artist=listing_search_artist(row.get("artist"), title),
                media_type=row.get("media_type"),
                hits=hits,
                require_catalog_token=False,
            )
            if classified.reason == "media_mismatch":
                retry = True
        if not retry:
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET identity_status = 'unmatched',
                    discogs_shortlist = '[]'::jsonb,
                    discogs_shortlist_fetched_at = NULL,
                    discogs_thumb_url = NULL,
                    identity_status_changed_at = now()
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )
        reset += 1
    return reset


def _reset_tracked_artist_pieces(connection: Connection) -> int:
    """Re-search tracked pieces that never had a Discogs lookup or a catalog token."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET discogs_shortlist_fetched_at = NULL
            WHERE identity_status = 'unmatched'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND discogs_shortlist_fetched_at IS NOT NULL
              AND COALESCE(identity_source, 'listing') <> 'discogs'
              AND (
                artist ~* 'teresa|momoe|anita|yamaguchi|mui'
                OR title ~ 'テレサ|鄧麗君|邓丽君|山口百恵|梅艷芳|梅艳芳'
                OR title ~* 'teresa teng|momoe yamaguchi|anita mui'
              )
              AND (
                media_type IS NULL
                OR lower(BTRIM(media_type)) NOT IN (
                    'magazine', 'photo', 'print', 'photobook', 'stamp', 'usb',
                    'dvd', 'vhs', 'laserdisc', 'sheet_music', 'toy'
                )
              )
            """
        )
    )
    return int(result.rowcount or 0)


def backfill_images_from_payload(connection: Connection) -> int:
    """Recover listing photos from stored search-card HTML."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, payload, image_url
            FROM staging.listing
            WHERE payload IS NOT NULL
              AND (
                  image_url IS NULL
                  OR BTRIM(image_url) = ''
                  OR image_url ILIKE '%spacer.gif%'
                  OR image_url ILIKE '%noimage%'
                  OR image_url IN (
                      SELECT image_url
                      FROM staging.listing
                      WHERE NULLIF(BTRIM(image_url), '') IS NOT NULL
                      GROUP BY image_url
                      HAVING COUNT(*) > 1
                  )
              )
            """
        )
    ).mappings().all()
    updated = 0
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            continue
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            continue
        soup = BeautifulSoup(html, "html.parser")
        root = soup.find("li") or soup
        marketplace = str(row.get("marketplace") or "")
        if marketplace == "ebay":
            image_url = parse_ebay_image(root)
        else:
            image_url = parse_buyee_image(root)
        if not image_url or is_placeholder_image(image_url):
            continue
        current = str(row.get("image_url") or "").strip()
        if current == image_url:
            continue
        connection.execute(
            text(
                """
                UPDATE staging.listing
                SET image_url = :image_url
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "image_url": image_url,
                "marketplace": marketplace,
                "listing_id": str(row["listing_id"]),
            },
        )
        updated += 1
    return updated


def _clear_junk_catalogs(connection: Connection) -> int:
    """Strip price SKUs and title-fragment catalogs from stored rows."""
    cleared = 0
    tables = (
        (
            """
            SELECT marketplace, listing_id, catalog_number, title
            FROM warehouse.auction
            WHERE catalog_number IS NOT NULL
              AND BTRIM(catalog_number) <> ''
            """,
            """
            UPDATE warehouse.auction
            SET catalog_number = NULL,
                discogs_shortlist = CASE
                    WHEN identity_status IN ('unmatched', 'needs_review')
                    THEN '[]'::jsonb
                    ELSE discogs_shortlist
                END,
                discogs_shortlist_fetched_at = CASE
                    WHEN identity_status IN ('unmatched', 'needs_review')
                    THEN NULL
                    ELSE discogs_shortlist_fetched_at
                END,
                identity_status = CASE
                    WHEN identity_status = 'needs_review'
                    THEN 'unmatched'
                    ELSE identity_status
                END,
                discogs_thumb_url = CASE
                    WHEN identity_status IN ('unmatched', 'needs_review')
                    THEN NULL
                    ELSE discogs_thumb_url
                END
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """,
        ),
        (
            """
            SELECT marketplace, listing_id, catalog_number, title
            FROM staging.listing
            WHERE catalog_number IS NOT NULL
              AND BTRIM(catalog_number) <> ''
            """,
            """
            UPDATE staging.listing
            SET catalog_number = NULL
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """,
        ),
        (
            """
            SELECT
                collector.marketplace,
                collector.listing_id,
                collector.auto_catalog_number AS catalog_number,
                auction.title
            FROM warehouse.auction_collector AS collector
            JOIN warehouse.auction AS auction
              ON auction.marketplace = collector.marketplace
             AND auction.listing_id = collector.listing_id
            WHERE collector.account_id IS NULL
              AND collector.auto_catalog_number IS NOT NULL
              AND BTRIM(collector.auto_catalog_number) <> ''
            """,
            """
            UPDATE warehouse.auction_collector
            SET auto_catalog_number = NULL
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
              AND account_id IS NULL
            """,
        ),
    )
    for select_sql, update_sql in tables:
        rows = connection.execute(text(select_sql)).mappings().all()
        for row in rows:
            catalog = str(row.get("catalog_number") or "")
            title = str(row.get("title") or "")
            if not is_junk_catalog(catalog, title=title):
                continue
            connection.execute(
                text(update_sql),
                {
                    "marketplace": row["marketplace"],
                    "listing_id": row["listing_id"],
                },
            )
            cleared += 1
    return cleared


def _reclassify_listing_facts(connection: Connection) -> int:
    """Apply title media/catalog rules to every warehouse row."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, title, catalog_number, media_type,
                   bulk_lot, label
            FROM warehouse.auction
            """
        )
    ).mappings().all()
    updated = 0
    for row in rows:
        title = str(row.get("title") or "")
        details = classify_media_details(title)
        job = is_job_lot(title)
        stored = str(row.get("catalog_number") or "").strip() or None
        token = listing_identity_catalog(
            stored=stored,
            title=title,
            media_type=details.format or row.get("media_type"),
        )
        new_catalog = token
        new_media = details.format or row.get("media_type")
        new_lot = bool(details.bulk_lot or job)
        stored_label = str(row.get("label") or "").strip() or None
        hinted_label = extract_record_label(title)
        new_label = stored_label
        if hinted_label and (
            not stored_label or stored_label.casefold() == "yen"
        ):
            new_label = hinted_label
        if (
            new_media == row.get("media_type")
            and new_lot == bool(row.get("bulk_lot"))
            and new_catalog == (str(row.get("catalog_number") or "").strip() or None)
            and new_label == stored_label
        ):
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET media_type = :media_type,
                    bulk_lot = CAST(:bulk_lot AS boolean),
                    catalog_number = :catalog_number,
                    label = :label,
                    discogs_shortlist_fetched_at = CASE
                        WHEN identity_status IN ('unmatched', 'needs_review')
                         AND CAST(:bulk_lot AS boolean) IS NOT TRUE
                         AND (
                            identity_status = 'unmatched'
                            OR CAST(:media_changed AS boolean)
                         )
                        THEN NULL
                        ELSE discogs_shortlist_fetched_at
                    END,
                    identity_status = CASE
                        WHEN CAST(:media_changed AS boolean)
                         AND identity_status IN ('unmatched', 'needs_review')
                         AND CAST(:bulk_lot AS boolean) IS NOT TRUE
                        THEN 'unmatched'
                        ELSE identity_status
                    END
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "media_type": new_media,
                "media_changed": new_media != row.get("media_type"),
                "bulk_lot": new_lot,
                "catalog_number": new_catalog,
                "label": new_label,
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )
        updated += 1
    return updated


def _backfill_listing_catalogs_from_pressings(connection: Connection) -> int:
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction AS auction
            SET catalog_number = pressing.catalog_number
            FROM warehouse.auction_pressing_assignment AS assignment
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            WHERE assignment.marketplace = auction.marketplace
              AND assignment.listing_id = auction.listing_id
              AND (auction.catalog_number IS NULL OR BTRIM(auction.catalog_number) = '')
              AND pressing.catalog_number IS NOT NULL
              AND BTRIM(pressing.catalog_number) <> ''
            """
        )
    )
    return int(result.rowcount or 0)


def _promote_unmatched_shortlists(connection: Connection) -> int:
    """Review only when leftover hits could be the listing artist."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, artist, title, catalog_number,
                   media_type, discogs_shortlist
            FROM warehouse.auction
            WHERE identity_status = 'unmatched'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND jsonb_typeof(discogs_shortlist) = 'array'
              AND jsonb_array_length(discogs_shortlist) >= 1
              AND (
                media_type IS NULL
                OR lower(BTRIM(media_type)) NOT IN (
                    'magazine', 'photo', 'print', 'photobook', 'stamp', 'usb',
                    'sheet_music', 'toy'
                )
              )
            """
        )
    ).mappings().all()
    updated = 0
    for row in rows:
        raw = row.get("discogs_shortlist") or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        hits = parse_search_hits(raw)
        if not hits:
            continue
        token = catalog_token(
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
        )
        covered = covering_hits_for_listing(
            hits,
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
        )
        if token and not covered:
            continue
        resolved = listing_search_artist(row.get("artist"), row.get("title"))
        classified = classify_search_hits(
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
            artist=resolved,
            media_type=row.get("media_type"),
            hits=covered or hits,
            require_catalog_token=bool(token),
        )
        review_hits = classified.hits or ()
        if classified.status not in {"needs_review", "filled_auto"} and not review_hits:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET discogs_shortlist = '[]'::jsonb,
                        discogs_shortlist_fetched_at = NULL,
                        discogs_thumb_url = NULL,
                        identity_status_changed_at = now()
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace": row["marketplace"],
                    "listing_id": row["listing_id"],
                },
            )
            updated += 1
            continue
        ranked = review_hits or covered or hits
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET identity_status = 'needs_review',
                    discogs_shortlist = CAST(:shortlist AS jsonb),
                    identity_status_changed_at = now()
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
                "shortlist": json.dumps(shortlist_payload(ranked), ensure_ascii=False),
            },
        )
        updated += 1
    return updated


def _narrow_review_shortlists(connection: Connection) -> int:
    """Re-score review shortlists; lock same-album picks and retry stolen artists."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, artist, title, catalog_number,
                   media_type, discogs_shortlist
            FROM warehouse.auction
            WHERE identity_status = 'needs_review'
              AND COALESCE(bulk_lot, false) IS NOT TRUE
              AND jsonb_typeof(discogs_shortlist) = 'array'
              AND jsonb_array_length(discogs_shortlist) >= 1
            """
        )
    ).mappings().all()
    updated = 0
    for row in rows:
        raw = row.get("discogs_shortlist") or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        hits = parse_search_hits(raw)
        if not hits:
            continue
        original_count = len(hits)
        token = catalog_token(
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
        )
        covered = covering_hits_for_listing(
            hits,
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
        )
        if token and not covered:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET identity_status = 'unmatched',
                        discogs_shortlist = '[]'::jsonb,
                        discogs_shortlist_fetched_at = NULL,
                        discogs_thumb_url = NULL,
                        identity_status_changed_at = now()
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace": row["marketplace"],
                    "listing_id": row["listing_id"],
                },
            )
            updated += 1
            continue
        resolved = listing_search_artist(row.get("artist"), row.get("title"))
        classified = classify_search_hits(
            catalog_number=row.get("catalog_number"),
            title=row.get("title"),
            artist=resolved,
            media_type=_listing_media_for_row(row),
            hits=covered,
            require_catalog_token=bool(token),
        )
        if (
            classified.status == "unmatched"
            and classified.reason in {"artist_mismatch", "empty_shortlist"}
        ):
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET identity_status = 'unmatched',
                        discogs_shortlist = '[]'::jsonb,
                        discogs_shortlist_fetched_at = NULL,
                        discogs_thumb_url = NULL,
                        identity_status_changed_at = now()
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace": row["marketplace"],
                    "listing_id": row["listing_id"],
                },
            )
            updated += 1
            continue
        narrowed = classified.hits
        if classified.status == "filled_auto" and classified.chosen is not None:
            narrowed = (classified.chosen,)
        persist = narrowed or hits
        if not persist or len(persist) >= original_count:
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET discogs_shortlist = CAST(:shortlist AS jsonb),
                    identity_status_changed_at = now()
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "shortlist": json.dumps(shortlist_payload(persist), ensure_ascii=False),
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )
        updated += 1
    return updated


def copy_listing_images(connection: Connection) -> int:
    """Promote staging listing photos onto warehouse.auction.image_url."""
    filled = connection.execute(
        text(
            """
            UPDATE warehouse.auction AS auction
            SET image_url = listing.image_url
            FROM staging.listing AS listing
            WHERE auction.marketplace = listing.marketplace
              AND auction.listing_id = listing.listing_id
              AND listing.image_url IS NOT NULL
              AND BTRIM(listing.image_url) <> ''
              AND listing.image_url NOT ILIKE '%spacer.gif%'
              AND listing.image_url NOT ILIKE '%noimage%'
              AND (
                  auction.image_url IS NULL
                  OR BTRIM(auction.image_url) = ''
                  OR auction.image_url ILIKE '%spacer.gif%'
                  OR auction.image_url ILIKE '%noimage%'
                  OR (
                      auction.image_url IS DISTINCT FROM listing.image_url
                      AND auction.image_url IN (
                          SELECT image_url
                          FROM warehouse.auction
                          WHERE NULLIF(BTRIM(image_url), '') IS NOT NULL
                          GROUP BY image_url
                          HAVING COUNT(*) > 1
                      )
                  )
              )
            """
        )
    )
    return int(filled.rowcount or 0)


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


INGEST_IDENTITY_LOOKBACK = timedelta(hours=12)
INGEST_IDENTITY_BUDGET_SECONDS = 45.0
INGEST_LEFTOVER_BUDGET_SECONDS = 45.0


def fill_unmatched_identities(
    engine: Engine,
    *,
    client: DiscogsClient | None = None,
    limit: int | None = None,
    marketplace: str | None = None,
    retune: bool = True,
    since: datetime | None = None,
) -> IdentityFillStats:
    """Search Discogs for unmatched warehouse rows and auto-fill dead-on hits.

    ``retune=False`` fills newly ingested rows first, then leftover unmatched
    and Need-a-decision piles with a short Discogs search (listing format plus
    unfiltered). It does not grind every extra format.
    """
    stats = IdentityFillStats()
    stats.ingest_fail_fast = not retune
    discogs = client or DiscogsClient()
    search_cache: dict[str, tuple[SearchHit, ...]] = {}
    release_cache: dict[int, PressingIdentityDraft] = {}
    created_after = since
    if not retune and created_after is None:
        created_after = datetime.now(timezone.utc) - INGEST_IDENTITY_LOOKBACK

    with engine.begin() as connection:
        if retune:
            stats.images_backfilled = backfill_images_from_payload(connection)
            stats.images_copied = copy_listing_images(connection)
            stats.filled_manual = mark_existing_assignments_filled(connection)
            _clear_currency_labels(connection)
            stats.junk_cleared = _clear_junk_catalogs(connection)
            stats.junk_cleared += _unfill_print_and_junk_identities(connection)
            _retarget_promo_copies_to_original(connection)
            _retarget_bare_best_hit_sleeves(connection)
            stats.junk_cleared += _unfill_year_and_media_mismatches(connection)
            stats.junk_cleared += _unfill_unreliable_auto_identities(connection)
            stats.junk_cleared += _unfill_untracked_auto_identities(connection)
            stats.junk_cleared += _clear_conflicting_reissue_catalogs(connection)
            _clear_unconfirmed_discogs_thumbs(connection)
            _reclassify_listing_facts(connection)
            _backfill_listing_catalogs_from_pressings(connection)
            _retag_and_park_job_lots(connection)
            _upsert_gripsweat_auctions(connection)
            _apply_known_pressings(connection)
            _reset_tracked_artist_pieces(connection)
            stats.shortlists_promoted = _promote_unmatched_shortlists(connection)
            _narrow_review_shortlists(connection)
            _reset_unmatched_for_retune(connection)
            _reset_photographed_empty_shortlists(connection)
            _reset_piece_identity_misses(connection)
            _reset_empty_review_shortlists(connection)
            _reset_format_and_region_misses(connection)
            _reset_extractable_latin_unmatched(connection)
        else:
            stats.filled_manual = mark_existing_assignments_filled(connection)
            _reclassify_listing_facts(connection)
            _reset_empty_review_shortlists(connection)
            _narrow_review_shortlists(connection)
            _apply_known_pressings(connection)
        identified_pressings = _identified_pressing_rows(connection)
        rows = list(
            _load_candidates(
                connection,
                marketplace=marketplace,
                limit=limit,
                created_after=created_after if not retune else None,
            )
        )
    stats.scanned = len(rows)
    http = httpx.Client(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "auction-etl/1.0"},
    )
    try:
        ingest_deadline = (
            None
            if retune
            else time.monotonic() + INGEST_IDENTITY_BUDGET_SECONDS
        )
        for row in rows:
            if stats.stopped_reason:
                break
            if ingest_deadline is not None and time.monotonic() >= ingest_deadline:
                stats.stopped_reason = "ingest identity budget"
                logger.warning("Discogs identity fill stopped: ingest budget")
                break
            try:
                with engine.begin() as connection:
                    outcome = _fill_one_row(
                        connection,
                        row=row,
                        client=discogs,
                        search_cache=search_cache,
                        release_cache=release_cache,
                        stats=stats,
                        image_client=http,
                        identified_pressings=identified_pressings,
                        fast_search=True,
                    )
            except DiscogsRateLimitError as error:
                stats.stopped_reason = str(error)
                logger.warning("Discogs identity fill stopped: rate limit")
                break
            except httpx.HTTPError as error:
                logger.warning(
                    "identity fill skipped %s %s after Discogs HTTP error",
                    row.get("marketplace"),
                    row.get("listing_id"),
                )
                if not retune:
                    stats.stopped_reason = (
                        stats.stopped_reason
                        or f"Discogs HTTP error: {error.__class__.__name__}"
                    )
                    break
                stats.unmatched += 1
                continue
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
            done = stats.filled_auto + stats.needs_review + stats.unmatched
            if done == 1 or done % 25 == 0 or done == stats.scanned:
                logger.info(
                    "identity fill progress %s/%s filled=%s review=%s unmatched=%s searches=%s",
                    done,
                    stats.scanned,
                    stats.filled_auto,
                    stats.needs_review,
                    stats.unmatched,
                    stats.searched,
                )

        if retune:
            _promote_unique_shortlists(
                engine,
                client=discogs,
                release_cache=release_cache,
                stats=stats,
                image_client=http,
            )
            _promote_cover_matches(
                engine,
                client=discogs,
                release_cache=release_cache,
                search_cache=search_cache,
                stats=stats,
            )
        if (
            stats.stopped_reason is None
            or stats.stopped_reason == "ingest identity budget"
        ):
            leftover_deadline = (
                None
                if retune
                else time.monotonic() + INGEST_LEFTOVER_BUDGET_SECONDS
            )
            _research_leftover_identities(
                engine,
                client=discogs,
                search_cache=search_cache,
                release_cache=release_cache,
                stats=stats,
                image_client=http,
                marketplace=marketplace,
                deadline=leftover_deadline,
            )
        if retune:
            if not stats.stopped_reason:
                _promote_unique_shortlists(
                    engine,
                    client=discogs,
                    release_cache=release_cache,
                    stats=stats,
                    image_client=http,
                )
                _promote_cover_matches(
                    engine,
                    client=discogs,
                    release_cache=release_cache,
                    search_cache=search_cache,
                    stats=stats,
                )
            with engine.begin() as connection:
                stats.shortlists_promoted += _promote_unmatched_shortlists(connection)
            _unfill_photo_mismatches(engine, image_client=http)
            _backfill_missing_discogs_thumbs(engine)
            _backfill_missing_matrices(
                engine,
                client=discogs,
                release_cache=release_cache,
                stats=stats,
            )
    finally:
        http.close()
    return stats


def draft_for_operator_choice(
    draft: PressingIdentityDraft,
    discogs_label_id: int | None = None,
) -> PressingIdentityDraft:
    """One click locks the release; extra Discogs labels use the primary row."""
    if discogs_label_id is not None:
        return _choose_label(draft, discogs_label_id)
    if draft.requires_label_choice and draft.discogs_label_id is not None:
        return _choose_label(draft, draft.discogs_label_id)
    return draft


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
    draft = draft_for_operator_choice(
        map_release_payload(payload),
        discogs_label_id,
    )

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


def research_listing_identity(
    engine: Engine,
    *,
    marketplace: str,
    listing_id: str,
    client: DiscogsClient | None = None,
) -> str:
    """Search Discogs for one open Review sale so Use this has candidates."""
    discogs = client or DiscogsClient()
    stats = IdentityFillStats()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    a.marketplace,
                    a.listing_id,
                    a.artist,
                    a.title,
                    COALESCE(
                        NULLIF(BTRIM(c.manual_catalog_number), ''),
                        NULLIF(BTRIM(a.catalog_number), '')
                    ) AS catalog_number,
                    a.media_type,
                    a.bulk_lot,
                    a.image_url,
                    a.label,
                    a.identity_status,
                    d.description
                FROM warehouse.auction AS a
                LEFT JOIN warehouse.auction_collector AS c
                  ON c.marketplace = a.marketplace
                 AND c.listing_id = a.listing_id
                 AND c.account_id IS NULL
                LEFT JOIN warehouse.auction_detail AS d
                  ON d.marketplace = a.marketplace
                 AND d.listing_id = a.listing_id
                WHERE a.marketplace = :marketplace
                  AND a.listing_id = :listing_id
                """
            ),
            {"marketplace": marketplace, "listing_id": listing_id},
        ).mappings().first()
        pressings = _identified_pressing_rows(connection)
    if row is None:
        return "unmatched"
    http = httpx.Client(
        timeout=4.0,
        follow_redirects=True,
        headers={"User-Agent": "auction-etl/1.0"},
    )
    stats.deadline = time.monotonic() + 18.0
    try:
        with engine.begin() as connection:
            status = _fill_one_row(
                connection,
                row=dict(row),
                client=discogs,
                search_cache={},
                release_cache={},
                stats=stats,
                image_client=http,
                identified_pressings=pressings,
                fast_search=False,
                operator_choice=True,
            )
        if stats.aborted:
            raise DiscogsUnavailableError("Discogs search did not finish")
        return status
    finally:
        http.close()


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
        if draft.disc_count:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.pressing_identity
                    SET disc_count = :disc_count
                    WHERE id = :id
                      AND disc_count IS NULL
                    """
                ),
                {"id": int(existing), "disc_count": draft.disc_count},
            )
        return int(existing)

    label_id = _upsert_label(connection, draft)
    artist_key = canonical_artist_key(draft.display_artist) or normalize_identity_key(
        draft.display_artist or draft.display_title
    )
    title_key = canonical_title_key(draft.display_title) or normalize_identity_key(
        draft.display_title or draft.display_artist
    )
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


_UNIQUE_REVIEW_REASONS = frozenset(
    {
        "artist_mismatch",
        "title_search",
        "media_mismatch",
    }
)


def _keep_usable_classification(primary: Any, retry: Any) -> Any:
    """Keep a catalog-path review; only retry when that path has no candidate."""
    if primary.chosen is not None or _unique_review_candidate(primary) is not None:
        return primary
    if retry.chosen is not None or _unique_review_candidate(retry) is not None:
        return retry
    return primary


def _unique_review_candidate(classification: Any) -> SearchHit | None:
    """Promote a unique title/artist/media shortlist the same way catno hits promote."""
    hits = tuple(classification.hits or ())
    option_shapes = {shortlist_option_shape(hit.formats) for hit in hits}
    if classification.chosen is not None:
        if len(option_shapes) > 1:
            return None
        return classification.chosen
    if classification.status != "needs_review":
        return None
    if classification.reason in _UNIQUE_REVIEW_REASONS and len(hits) == 1:
        return hits[0]
    album_keys = {
        _release_album_key(hit) for hit in hits if _release_album_key(hit)
    }
    if (
        classification.reason in {"title_search", "ambiguous_hits"}
        and 2 <= len(hits) <= 12
        and len(album_keys) == 1
        and len(option_shapes) <= 1
        and _unique_shortlist_catno(hits)
    ):
        return hits[0]
    return None


def _sleeve_matches_listing(
    row: dict[str, Any],
    thumb_url: str | None,
    image_client: httpx.Client | None,
) -> bool:
    """True only when both sleeves download and the hash says they are the same.

    A missing photo is not agreement. A title that names two records stays
    unmatched until the listing photo is the Discogs sleeve.
    """
    if image_client is None:
        return False
    listing_url = str(row.get("image_url") or "").strip()
    if not listing_url or "spacer.gif" in listing_url or "noimage" in listing_url:
        return False
    listing = fetch_image(listing_url, client=image_client)
    cover = fetch_image(thumb_url, client=image_client)
    if listing is None or cover is None:
        return False
    return listing_agrees_with_cover(listing, cover)


def _photo_confirms_listing(
    row: dict[str, Any],
    thumb_url: str | None,
    image_client: httpx.Client | None,
) -> bool:
    """Require the listing photo to be the same sleeve when a photo exists."""
    listing_url = str(row.get("image_url") or "").strip()
    if (
        not listing_url
        or "spacer.gif" in listing_url
        or "noimage" in listing_url
    ):
        return True
    if image_client is None:
        return True
    listing = fetch_image(listing_url, client=image_client)
    cover = fetch_image(thumb_url, client=image_client)
    if listing is None or cover is None:
        return True
    return listing_agrees_with_cover(listing, cover)


def _catalog_locks_identity(row: dict[str, Any], candidate: Any) -> bool:
    """A unique known catno is the pressing even when sleeve hashes disagree."""
    if candidate is None:
        return False
    token = listing_identity_catalog(
        stored=row.get("catalog_number"),
        title=row.get("title"),
        artist=row.get("artist"),
        media_type=row.get("media_type"),
    )
    catno = getattr(candidate, "catno", None)
    if not token or not catno:
        return False
    return fold_catalog(token) == fold_catalog(catno) or catno_covers_listing_token(
        catno,
        token,
    )


def _unique_shortlist_locks_identity(
    row: dict[str, Any],
    candidate: Any,
    hits: Sequence[Any],
    thumb_url: str | None,
    image_client: httpx.Client | None,
) -> bool:
    """Unique artist-locked hits can fill without a matching sleeve hash."""
    if _catalog_locks_identity(row, candidate):
        return True
    matched_title = _release_album_key(candidate) if candidate is not None else ""
    if not matched_title:
        matched_title = str(getattr(candidate, "title", "") or "")
    if listing_names_other_work(row.get("title"), matched_title):
        return _sleeve_matches_listing(row, thumb_url, image_client)
    if bare_best_hit_title(row.get("title")) and best_hit_album_title(matched_title):
        return _sleeve_matches_listing(row, thumb_url, image_client)
    if len(hits) == 1:
        return True
    album_keys = {
        _release_album_key(hit)
        for hit in hits
        if _release_album_key(hit)
    }
    if len(album_keys) == 1:
        album_key = next(iter(album_keys))
        listing_key = canonical_title_key(row.get("title"))
        if album_key and listing_key and (
            album_key == listing_key
            or album_key in listing_key
            or listing_key in album_key
        ):
            return True
        tokens = _distinctive_title_tokens(row.get("title"), row.get("artist"))
        if tokens and any(_hit_matches_title_tokens(hit, tokens) for hit in hits):
            return True
    return _photo_confirms_listing(row, thumb_url, image_client)


def _unassign_auto_identity(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    keep_shortlist: bool,
    title: str | None = None,
) -> None:
    """Drop an auto Discogs fill that the listing photo does not support."""
    if title is None:
        title = str(
            connection.execute(
                text(
                    """
                    SELECT title
                    FROM warehouse.auction
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {"marketplace": marketplace, "listing_id": listing_id},
            ).scalar()
            or ""
        )
    connection.execute(
        text(
            """
            DELETE FROM warehouse.auction_pressing_assignment
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
              AND COALESCE(is_manual_override, false) IS NOT TRUE
            """
        ),
        {"marketplace": marketplace, "listing_id": listing_id},
    )
    connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET identity_status = CASE
                    WHEN CAST(:keep_shortlist AS boolean)
                     AND jsonb_typeof(discogs_shortlist) = 'array'
                     AND jsonb_array_length(discogs_shortlist) > 0
                    THEN 'needs_review'
                    ELSE 'unmatched'
                END,
                identity_source = 'discogs',
                discogs_thumb_url = NULL,
                identity_filled_at = NULL,
                discogs_shortlist_fetched_at = CASE
                    WHEN CAST(:keep_shortlist AS boolean)
                    THEN discogs_shortlist_fetched_at
                    ELSE NULL
                END,
                identity_status_changed_at = now()
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
              AND identity_status IN ('filled_auto', 'needs_review')
            """
        ),
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
            "keep_shortlist": keep_shortlist,
        },
    )
    _restore_listing_catalog(
        connection,
        marketplace=marketplace,
        listing_id=listing_id,
        title=title or "",
    )


def _restore_listing_catalog(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    title: str,
) -> None:
    """Put the title catalog back after a leftover Discogs catno is unfilled."""
    token = catalog_token(title=title)
    connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET catalog_number = :catalog_number
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
              AND identity_status IN ('unmatched', 'needs_review')
            """
        ),
        {
            "catalog_number": token,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    )


def _rows_for_tracked_artists(
    bind: Engine | Connection,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep Discogs work on listings that belong to tracked artists."""
    names = enabled_tracked_artist_names(bind)
    if not names:
        return rows
    return [
        row
        for row in rows
        if listing_belongs_to_tracked_artists(
            title=row.get("title"),
            artist=row.get("artist"),
            tracked_names=names,
        )
    ]


def _unfill_untracked_auto_identities(connection: Connection) -> int:
    """Drop auto Discogs fills for listings outside the tracked collection."""
    names = enabled_tracked_artist_names(connection)
    if not names:
        return 0
    rows = connection.execute(
        text(
            """
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.artist
            FROM warehouse.auction AS auction
            JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            WHERE COALESCE(assignment.is_manual_override, false) IS NOT TRUE
            """
        )
    ).mappings().all()
    cleared = 0
    for row in rows:
        title = str(row.get("title") or "")
        artist = str(row.get("artist") or "")
        if listing_belongs_to_tracked_artists(
            title=title,
            artist=artist,
            tracked_names=names,
        ):
            continue
        _unassign_auto_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            keep_shortlist=False,
            title=title,
        )
        cleared += 1
    logger.info("untracked auto-fill unfilled=%s", cleared)
    return cleared


def _retarget_promo_copies_to_original(connection: Connection) -> int:
    """Move an auto-filled プロモ copy off a UPJY repress onto the original catalog.

    A saved manual catalog, pressing type, or promo flag is left alone.
    """
    rows = connection.execute(
        text(
            """
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.media_type,
                pressing.media_type AS pressing_media,
                pressing.catalog_number AS pressing_catalog
            FROM warehouse.auction AS auction
            JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            LEFT JOIN warehouse.auction_collector AS collector
              ON collector.marketplace = auction.marketplace
             AND collector.listing_id = auction.listing_id
             AND collector.account_id IS NULL
            WHERE auction.identity_status = 'filled_auto'
              AND COALESCE(assignment.is_manual_override, false) IS NOT TRUE
              AND NULLIF(BTRIM(collector.manual_catalog_number), '') IS NULL
              AND NULLIF(BTRIM(collector.manual_pressing_type), '') IS NULL
              AND collector.manual_promo IS NULL
              AND collector.manual_reissue IS NULL
              AND collector.manual_first_press IS NULL
            """
        )
    ).mappings().all()
    pressings = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT
                    pressing.id,
                    pressing.catalog_number,
                    pressing.release_year,
                    pressing.generation,
                    pressing.media_type,
                    family.display_title
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id = pressing.release_family_id
                WHERE pressing.discogs_release_id IS NOT NULL
                """
            )
        ).mappings()
    ]
    moved = 0
    for row in rows:
        listing_media = (
            _listing_media_for_row(dict(row))
            or row.get("media_type")
            or row.get("pressing_media")
        )
        chosen = original_pressing_for_promo_copy(
            row.get("title"),
            listing_media=listing_media,
            current_catalog=row.get("pressing_catalog"),
            candidates=pressings,
        )
        if chosen is None:
            continue
        _assign_pressing(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            pressing_id=int(chosen["id"]),
            match_basis="TITLE_RULE",
            manual=False,
        )
        moved += 1
    logger.info("promo copies moved onto original pressings=%s", moved)
    return moved


def _retarget_bare_best_hit_sleeves(connection: Connection) -> int:
    """A bare ベスト・ヒット title follows the sleeve, not the Polydor album name."""
    rows = connection.execute(
        text(
            """
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.image_url,
                pressing.catalog_number AS pressing_catalog
            FROM warehouse.auction AS auction
            LEFT JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            LEFT JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            LEFT JOIN warehouse.auction_collector AS collector
              ON collector.marketplace = auction.marketplace
             AND collector.listing_id = auction.listing_id
             AND collector.account_id IS NULL
            WHERE auction.identity_status = 'filled_auto'
              AND COALESCE(assignment.is_manual_override, false) IS NOT TRUE
              AND NULLIF(BTRIM(collector.manual_catalog_number), '') IS NULL
              AND auction.image_url IS NOT NULL
              AND BTRIM(auction.image_url) <> ''
              AND (
                  auction.title LIKE '%ベスト%'
                  OR auction.title ILIKE '%best hit%'
              )
            """
        )
    ).mappings().all()
    pending = [
        row
        for row in rows
        if bare_best_hit_title(row.get("title"))
        and fold_catalog(str(row.get("pressing_catalog") or "")) != fold_catalog("28TR-2092")
    ]
    if not pending:
        return 0
    original = connection.execute(
        text(
            """
            SELECT pressing.id, sibling.thumb
            FROM warehouse.pressing_identity AS pressing
            LEFT JOIN LATERAL (
                SELECT NULLIF(BTRIM(other.discogs_thumb_url), '') AS thumb
                FROM warehouse.auction_pressing_assignment AS other_asg
                JOIN warehouse.auction AS other
                  ON other.marketplace = other_asg.marketplace
                 AND other.listing_id = other_asg.listing_id
                WHERE other_asg.pressing_id = pressing.id
                  AND NULLIF(BTRIM(other.discogs_thumb_url), '') IS NOT NULL
                LIMIT 1
            ) AS sibling ON true
            WHERE regexp_replace(upper(pressing.catalog_number), '[^A-Z0-9]', '', 'g') = '28TR2092'
              AND pressing.media_type = 'LP'
            ORDER BY pressing.release_year NULLS LAST, pressing.id
            LIMIT 1
            """
        )
    ).mappings().first()
    polydor_thumb = connection.execute(
        text(
            """
            SELECT NULLIF(BTRIM(auction.discogs_thumb_url), '')
            FROM warehouse.auction AS auction
            JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            WHERE regexp_replace(upper(pressing.catalog_number), '[^A-Z0-9]', '', 'g') = 'MR3037'
              AND NULLIF(BTRIM(auction.discogs_thumb_url), '') IS NOT NULL
            LIMIT 1
            """
        )
    ).scalar()
    if original is None or not original.get("thumb") or not polydor_thumb:
        return 0
    moved = 0
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        original_cover = fetch_image(str(original["thumb"]), client=client)
        polydor_cover = fetch_image(str(polydor_thumb), client=client)
        if original_cover is None or polydor_cover is None:
            return 0
        for row in pending:
            listing = fetch_image(str(row.get("image_url") or ""), client=client)
            if listing is None:
                continue
            original_distance = best_listing_cover_distance(listing, original_cover)
            polydor_distance = best_listing_cover_distance(listing, polydor_cover)
            if original_distance > 80 or original_distance >= polydor_distance:
                continue
            _assign_pressing(
                connection,
                marketplace=str(row["marketplace"]),
                listing_id=str(row["listing_id"]),
                pressing_id=int(original["id"]),
                match_basis="TITLE_RULE",
                manual=False,
            )
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET discogs_thumb_url = :thumb,
                        identity_status = 'filled_auto',
                        identity_source = 'discogs',
                        identity_filled_at = COALESCE(identity_filled_at, now()),
                        identity_status_changed_at = now()
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                      AND identity_status IS DISTINCT FROM 'filled_manual'
                    """
                ),
                {
                    "thumb": str(original["thumb"]),
                    "marketplace": str(row["marketplace"]),
                    "listing_id": str(row["listing_id"]),
                },
            )
            moved += 1
    logger.info("bare best-hit sleeves moved to original best hits=%s", moved)
    return moved


def _unfill_year_and_media_mismatches(connection: Connection) -> int:
    """Drop auto-fills whose Discogs year or media is not the listed copy."""
    rows = connection.execute(
        text(
            """
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.media_type,
                auction.catalog_number,
                pressing.media_type AS pressing_media,
                pressing.release_year,
                pressing.catalog_number AS pressing_catalog
            FROM warehouse.auction AS auction
            JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            WHERE auction.identity_status = 'filled_auto'
              AND COALESCE(assignment.is_manual_override, false) IS NOT TRUE
            """
        )
    ).mappings().all()
    cleared = 0
    for row in rows:
        title = str(row.get("title") or "")
        listing_media = str(row.get("media_type") or "")
        pressing_media = str(row.get("pressing_media") or "")
        mismatch = not listing_media_compatible(listing_media, pressing_media)
        mismatch = mismatch or not hit_fits_listing_year(
            title,
            row.get("release_year"),
        )
        leftover = listing_wants_original_pressing(title) and (
            is_modern_reissue_catalog(str(row.get("pressing_catalog") or ""))
            or is_modern_reissue_catalog(str(row.get("catalog_number") or ""))
        )
        if not mismatch and not leftover:
            continue
        _unassign_auto_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            keep_shortlist=False,
            title=title,
        )
        cleared += 1
    logger.info("year/media mismatch unfilled=%s", cleared)
    return cleared


def _unfill_unreliable_auto_identities(connection: Connection) -> int:
    """Drop auto-fills whose Discogs row is a different copy than the listing."""
    rows = connection.execute(
        text(
            """
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.artist,
                auction.catalog_number,
                auction.media_type,
                family.display_title,
                family.display_artist,
                pressing.media_type AS pressing_media,
                pressing.catalog_number AS pressing_catalog
            FROM warehouse.auction AS auction
            JOIN warehouse.auction_pressing_assignment AS assignment
              ON assignment.marketplace = auction.marketplace
             AND assignment.listing_id = auction.listing_id
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            JOIN warehouse.release_family AS family
              ON family.id = pressing.release_family_id
            WHERE auction.identity_status = 'filled_auto'
              AND COALESCE(assignment.is_manual_override, false) IS NOT TRUE
            """
        )
    ).mappings().all()
    cleared = 0
    for row in rows:
        title = str(row.get("title") or "")
        media_mismatch = not listing_media_compatible(
            row.get("media_type"),
            row.get("pressing_media"),
        )
        agrees = _pressing_agrees_with_listing(
            {
                "title": title,
                "artist": row.get("artist"),
                "catalog_number": None,
            },
            {
                "display_title": row.get("display_title"),
                "display_artist": row.get("display_artist"),
                "catalog_number": row.get("pressing_catalog"),
            },
        )
        if not media_mismatch and agrees:
            continue
        _unassign_auto_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            keep_shortlist=True,
            title=title,
        )
        cleared += 1
    logger.info("unreliable auto identity unfilled=%s", cleared)
    return cleared


def _clear_conflicting_reissue_catalogs(connection: Connection) -> int:
    """Strip UPJY-style catalogs from original-era titles that were unfilled."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, title, catalog_number
            FROM warehouse.auction
            WHERE identity_status IN ('unmatched', 'needs_review')
              AND catalog_number IS NOT NULL
              AND BTRIM(catalog_number) <> ''
            """
        )
    ).mappings().all()
    cleared = 0
    for row in rows:
        title = str(row.get("title") or "")
        stored = str(row.get("catalog_number") or "")
        token = listing_identity_catalog(
            stored=stored,
            title=title,
            media_type=row.get("media_type"),
        )
        stale = listing_wants_original_pressing(title) and is_modern_reissue_catalog(
            stored
        )
        title_fold = re.sub(r"[^A-Z0-9]", "", title.upper())
        leftover = (
            bool(fold_catalog(stored))
            and fold_catalog(stored) != fold_catalog(token)
            and fold_catalog(stored) not in title_fold
            and listing_wants_original_pressing(title)
            and not stored_catalog_fits_listing(
                stored,
                title=title,
                media_type=row.get("media_type"),
            )
        )
        if not stale and not leftover:
            continue
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET catalog_number = :catalog_number,
                    discogs_shortlist_fetched_at = NULL
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "catalog_number": token,
                "marketplace": str(row["marketplace"]),
                "listing_id": str(row["listing_id"]),
            },
        )
        cleared += 1
    return cleared


def _clear_unconfirmed_discogs_thumbs(connection: Connection) -> int:
    """Do not preview a shortlist sleeve as if it were the matched pressing."""
    result = connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET discogs_thumb_url = NULL
            WHERE identity_status IN ('unmatched', 'needs_review')
              AND NULLIF(BTRIM(discogs_thumb_url), '') IS NOT NULL
            """
        )
    )
    return int(result.rowcount or 0)


def _unfill_print_and_junk_identities(connection: Connection) -> int:
    """Prints and junk catalogs are not Discogs pressings."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, title, catalog_number, media_type
            FROM warehouse.auction
            WHERE identity_status IN ('filled_auto', 'needs_review')
            """
        )
    ).mappings().all()
    cleared = 0
    for row in rows:
        title = str(row.get("title") or "")
        catalog = str(row.get("catalog_number") or "").strip() or None
        media = (
            str(row.get("media_type") or "").upper()
            or (classify_media_details(title).format or "")
        )
        printish = media in {
            "PHOTO",
            "PRINT",
            "PHOTOBOOK",
            "MAGAZINE",
            "STAMP",
            "SHEET_MUSIC",
            "TOY",
        } or bool(re.search(r"スチール写真|生写真|\b\d+\s*x\s*\d+\s*photos?\b", title, re.IGNORECASE))
        junk = bool(catalog and is_junk_catalog(catalog, title=title))
        if not printish and not junk:
            continue
        _unassign_auto_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            keep_shortlist=False,
            title=title,
        )
        cleared += 1
    return cleared


def _series_shortlist_hits(
    title: str | None,
    hits: Sequence[SearchHit],
) -> tuple[SearchHit, ...]:
    """Keep Stereo Sound / 鄧麗君之歌 series cards so the sleeve can pick the volume."""
    listing_cf = (title or "").casefold()
    want_stereo = "stereo sound" in listing_cf or bool(
        re.search(r"\b180g\b|\bssar-?\d+", listing_cf)
    )
    want_songbook = bool(
        re.search(r"space\s+records?|宇宙唱片|太空唱片|之歌第", listing_cf)
        or re.search(r"之歌第", title or "")
    )
    if not want_stereo and not want_songbook:
        return ()
    kept: list[SearchHit] = []
    seen: set[int] = set()
    for hit in hits:
        blob = f"{hit.title} {' '.join(hit.labels)}".casefold()
        keep = False
        catno_fold = (hit.catno or "").upper().replace(" ", "")
        if want_stereo and (
            "stereo sound" in blob or catno_fold.startswith("SSAR")
        ):
            keep = True
        if want_songbook and (
            re.search(r"之歌第", hit.title)
            or "宇宙" in blob
            or "yeu jow" in blob
            or (hit.catno or "").casefold().startswith("awk")
        ):
            listing_vol = listing_volume_number(title)
            hit_vol = listing_volume_number(hit.title)
            keep = listing_vol is None or hit_vol in {None, listing_vol}
            if keep and is_generic_songbook_album(hit.title) and listing_vol is not None:
                keep = hit_vol == listing_vol
        if keep and hit.discogs_id not in seen:
            seen.add(hit.discogs_id)
            kept.append(hit)
    return tuple(kept)


def _hits_agree_with_listing_volume(
    title: str | None,
    hits: Sequence[SearchHit],
) -> tuple[SearchHit, ...]:
    """Drop 第十二集 when the listing is vol 11; artist-only titles still pass."""
    listing_vol = listing_volume_number(title)
    if listing_vol is None:
        return tuple(hits)
    return tuple(
        hit
        for hit in hits
        if listing_volume_number(hit.title) in {None, listing_vol}
    )


def _cover_close_hits_for_row(
    hits: Sequence[SearchHit],
    *,
    row: dict[str, Any],
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    image_client: httpx.Client | None,
    lookup_releases: bool = True,
    deadline: float | None = None,
    hash_cache: dict[str, int | None] | None = None,
) -> tuple[SearchHit, ...]:
    """Hits whose Discogs sleeve is close to the listing photo."""
    listing_url = str(row.get("image_url") or "").strip()
    if (
        not hits
        or image_client is None
        or not listing_url
        or "spacer.gif" in listing_url
        or "noimage" in listing_url
        or is_placeholder_image(listing_url)
    ):
        return ()
    if deadline is not None and time.monotonic() >= deadline:
        return ()
    listing_image = fetch_image(listing_url, client=image_client)
    if listing_image is None:
        return ()
    listing_hashes = listing_cover_hashes(listing_image)
    if not listing_hashes:
        return ()
    listing_media = _listing_media_for_row(row)

    def _compatible(hit: SearchHit) -> bool:
        return listing_media_compatible(listing_media, " ".join(hit.formats))

    compatible_ids = {hit.discogs_id for hit in hits if _compatible(hit)}
    compatible_pool = tuple(hit for hit in hits if hit.discogs_id in compatible_ids)
    other_pool = tuple(hit for hit in hits if hit.discogs_id not in compatible_ids)
    ranked_pool = (*compatible_pool[:16], *other_pool[:8])[:20]
    if not lookup_releases:
        ranked_pool = ranked_pool[:6]
    try:
        hashes, thumbs, sides = _hash_shortlist_covers(
            ranked_pool,
            listing_hashes=listing_hashes,
            client=client,
            release_cache=release_cache,
            image_client=image_client,
            cache=hash_cache if hash_cache is not None else {},
            lookup_releases=lookup_releases,
            deadline=deadline,
        )
    except DiscogsRateLimitError:
        return ()
    except Exception:
        return ()
    ranked_hits = tuple(
        replace(hit, thumb_url=thumb or hit.thumb_url)
        for hit, thumb in zip(ranked_pool, thumbs)
    )
    listing_side = listing_color_side(listing_image)
    pool_hits = ranked_hits
    pool_hashes = hashes
    if listing_side in {"warm", "cool"}:
        same_side: list[tuple[SearchHit, int | None]] = []
        for hit, hashed, side in zip(ranked_hits, hashes, sides):
            if side == listing_side:
                same_side.append((hit, hashed))
        compatible_side = [
            (hit, hashed) for hit, hashed in same_side if _compatible(hit)
        ]
        chosen_side = compatible_side or same_side
        if chosen_side:
            pool_hits = tuple(hit for hit, _hashed in chosen_side)
            pool_hashes = [hashed for _hit, hashed in chosen_side]
    close = rank_cover_hits(listing_hashes, pool_hits, pool_hashes)
    compatible_close = tuple(hit for hit in close if _compatible(hit))
    if compatible_close:
        return (
            *compatible_close,
            *(hit for hit in close if hit.discogs_id not in {item.discogs_id for item in compatible_close}),
        )
    scored: list[tuple[int, int, SearchHit]] = []
    for hit, hashed in zip(pool_hits, pool_hashes):
        if hashed is None or not _compatible(hit):
            continue
        scored.append(
            (
                min(
                    hamming_distance(listing_hash, hashed)
                    for listing_hash in listing_hashes
                ),
                hit.discogs_id,
                hit,
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(hit for _distance, _discogs_id, hit in scored)


def _cover_may_lead_shortlist(
    unique: SearchHit,
    *,
    row: dict[str, Any],
) -> bool:
    """Fuzzy sleeves must not outrank a printed catalog prefix family."""
    token = listing_identity_catalog(
        stored=row.get("catalog_number"),
        title=row.get("title"),
        artist=row.get("artist"),
        media_type=_listing_media_for_row(row),
        infer=False,
    )
    listing_prefix = catalog_letter_prefix(token)
    if not listing_prefix:
        return True
    return catalog_letter_prefix(unique.catno) == listing_prefix


def _rank_classification_by_listing_photo(
    classification: Classification,
    *,
    row: dict[str, Any],
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    image_client: httpx.Client | None,
    extra_hits: Sequence[SearchHit] = (),
    lookup_releases: bool = True,
    deadline: float | None = None,
    hash_cache: dict[str, int | None] | None = None,
) -> Classification:
    """Put the Discogs sleeve that matches the listing photo first."""
    title = row.get("title")
    hits = tuple(extra_hits) or classification.hits
    ranked = _cover_close_hits_for_row(
        hits,
        row=row,
        client=client,
        release_cache=release_cache,
        image_client=image_client,
        lookup_releases=lookup_releases,
        deadline=deadline,
        hash_cache=hash_cache,
    )
    listing_media = _listing_media_for_row(row)

    def _compatible(hit: SearchHit) -> bool:
        return listing_media_compatible(listing_media, " ".join(hit.formats))

    compatible_ranked = tuple(hit for hit in ranked if _compatible(hit))
    if listing_is_promo(title) and listing_wants_original_pressing(title):
        vintage_pool = tuple(
            hit
            for hit in (compatible_ranked or ranked)
            if not hit_is_modern_reissue(hit)
        )
        if vintage_pool:
            compatible_ranked = vintage_pool
            ranked = tuple(
                hit for hit in ranked if not hit_is_modern_reissue(hit)
            ) or vintage_pool
    unique = (compatible_ranked or ranked)[0] if (compatible_ranked or ranked) else None
    if unique is not None and not _compatible(unique) and classification.hits:
        return classification
    if (
        unique is not None
        and listing_wants_original_pressing(title)
        and is_modern_reissue_catalog(unique.catno)
    ):
        vintage_close = tuple(
            hit
            for hit in compatible_ranked or ranked
            if not hit_is_modern_reissue(hit)
        )
        if vintage_close:
            unique = vintage_close[0]
    if unique is not None and (
        media_family(listing_media) == "cd" or listing_is_self_titled(str(title or ""))
    ):
        claimed = extract_release_year(title)
        seen_year: set[int] = set()
        year_fit: list[SearchHit] = []
        for hit in (*compatible_ranked, *ranked, *classification.hits, *hits):
            if hit.discogs_id in seen_year:
                continue
            if not (_compatible(hit) and hit_fits_listing_year(title, hit.year)):
                continue
            seen_year.add(hit.discogs_id)
            year_fit.append(hit)
        if claimed is not None:
            def _year_delta(hit: SearchHit) -> int:
                try:
                    return abs(int(str(hit.year).strip()[:4]) - claimed)
                except (TypeError, ValueError):
                    return 9999
            year_fit.sort(key=_year_delta)
        if year_fit:
            unique = year_fit[0]
    if unique is None or not _cover_may_lead_shortlist(unique, row=row):
        return classification
    rest = tuple(
        hit
        for hit in (*ranked, *hits, *classification.hits)
        if hit.discogs_id != unique.discogs_id
    )
    seen_ids = {unique.discogs_id}
    compatible_rest: list[SearchHit] = []
    other_rest: list[SearchHit] = []
    for hit in rest:
        if hit.discogs_id in seen_ids:
            continue
        seen_ids.add(hit.discogs_id)
        if _compatible(hit):
            compatible_rest.append(hit)
        else:
            other_rest.append(hit)
    ordered = shortlist_format_options((unique, *compatible_rest, *other_rest))
    if media_family(listing_media) == "cd" or listing_is_self_titled(str(title or "")):
        claimed = extract_release_year(title)

        def _cd_year_delta(hit: SearchHit) -> int:
            if claimed is None:
                return 50
            try:
                return abs(int(str(hit.year).strip()[:4]) - claimed)
            except (TypeError, ValueError):
                return 9999

        year_fit = [
            hit
            for hit in ordered
            if _compatible(hit) and hit_fits_listing_year(title, hit.year)
        ]
        year_fit.sort(key=_cd_year_delta)
        if year_fit and year_fit[0].discogs_id != ordered[0].discogs_id:
            lead_hit = year_fit[0]
            ordered = shortlist_format_options(
                (lead_hit, *[hit for hit in ordered if hit.discogs_id != lead_hit.discogs_id])
            )
    chosen = classification.chosen
    if chosen is not None and chosen.discogs_id != ordered[0].discogs_id:
        chosen = ordered[0] if _compatible(ordered[0]) else chosen
    return replace(classification, hits=ordered, chosen=chosen)


def _unfill_photo_mismatches(
    engine: Engine,
    *,
    image_client: httpx.Client,
) -> int:
    """Drop auto-fills whose Discogs sleeve is not the listing photo."""
    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        marketplace,
                        listing_id,
                        title,
                        catalog_number,
                        image_url,
                        discogs_thumb_url,
                        discogs_shortlist
                    FROM warehouse.auction
                    WHERE identity_status = 'filled_auto'
                      AND NULLIF(BTRIM(image_url), '') IS NOT NULL
                      AND image_url NOT ILIKE '%spacer.gif%'
                      AND NULLIF(BTRIM(discogs_thumb_url), '') IS NOT NULL
                    ORDER BY marketplace, listing_id
                    """
                )
            ).mappings()
        ]
    cleared = 0
    for row in rows:
        raw = row.get("discogs_shortlist") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
        hits = parse_search_hits(raw) if isinstance(raw, list) else ()
        if _unique_shortlist_locks_identity(
            row,
            SimpleNamespace(catno=row.get("catalog_number")),
            hits,
            row.get("discogs_thumb_url"),
            image_client,
        ):
            continue
        keep = isinstance(raw, list) and len(raw) > 0
        with engine.begin() as connection:
            _unassign_auto_identity(
                connection,
                marketplace=str(row["marketplace"]),
                listing_id=str(row["listing_id"]),
                keep_shortlist=keep,
                title=str(row.get("title") or ""),
            )
        cleared += 1
    logger.info("photo mismatch unfilled=%s", cleared)
    return cleared


def _pressing_formats(media_type: str | None) -> tuple[str, ...]:
    blob = (media_type or "").upper()
    if "CASS" in blob:
        return ("Cassette",)
    if "7" in blob:
        return ("Vinyl", '7"')
    if "12" in blob:
        return ("Vinyl", '12"')
    if blob.startswith("CD") or "SACD" in blob or "SHM" in blob:
        return ("CD",)
    if blob.startswith("LP") or "VINYL" in blob:
        return ("Vinyl", "LP")
    return ((media_type or "Vinyl"),)


def _identified_pressing_rows(connection: Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT
                    pressing.discogs_release_id,
                    pressing.catalog_number,
                    pressing.release_year,
                    pressing.country,
                    pressing.media_type,
                    pressing.discogs_uri,
                    pressing.label_name,
                    family.display_artist,
                    family.display_title
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id = pressing.release_family_id
                WHERE pressing.discogs_release_id IS NOT NULL
                """
            )
        ).mappings()
    ]


def _local_album_search_hits(
    row: dict[str, Any],
    pressings: Sequence[dict[str, Any]],
) -> tuple[SearchHit, ...]:
    """Reuse Discogs pressings already identified for the same album."""
    title = str(row.get("title") or "")
    artist = listing_search_artist(row.get("artist"), title)
    listing_media = _listing_media_for_row(row)
    leftover = _listing_leftover_album_compact(title)
    if len(leftover) < 2:
        return ()
    hits: list[SearchHit] = []
    seen: set[int] = set()
    for pressing in pressings:
        release_id = pressing.get("discogs_release_id")
        if release_id is None:
            continue
        discogs_id = int(release_id)
        if discogs_id in seen:
            continue
        display_title = str(pressing.get("display_title") or "")
        display_artist = str(pressing.get("display_artist") or "")
        if not artist_overlaps(
            listing_artist=artist,
            listing_title=title,
            discogs_names=(display_artist, display_title),
        ):
            continue
        if not album_name_in_listing(title, display_title):
            continue
        if not listing_media_compatible(listing_media, str(pressing.get("media_type") or "")):
            continue
        if not catalog_fits_listing_media(
            str(pressing.get("catalog_number") or ""),
            listing_media,
            title,
        ):
            continue
        seen.add(discogs_id)
        year = pressing.get("release_year")
        hits.append(
            SearchHit(
                discogs_id=discogs_id,
                title=f"{display_artist} - {display_title}".strip(" -"),
                catno=str(pressing.get("catalog_number") or ""),
                year=None if year is None else str(year),
                country=str(pressing.get("country") or "") or None,
                formats=_pressing_formats(str(pressing.get("media_type") or "")),
                labels=(
                    (str(pressing.get("label_name")),)
                    if pressing.get("label_name")
                    else ()
                ),
                thumb_url=None,
                uri=str(pressing.get("discogs_uri") or "") or None,
            )
        )
    return tuple(hits)


def _local_hits_cover_listing(
    row: dict[str, Any],
    hits: Sequence[SearchHit],
) -> bool:
    """Reuse warehouse Discogs hits unless they are only modern represses of a vintage copy."""
    if not hits:
        return False
    title = str(row.get("title") or "")
    if listing_wants_original_pressing(title) and all(
        hit_is_modern_reissue(hit) for hit in hits
    ):
        return False
    return True


def _fill_one_row(
    connection: Connection,
    *,
    row: dict[str, Any],
    client: DiscogsClient,
    search_cache: dict[str, tuple[SearchHit, ...]],
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
    image_client: httpx.Client | None = None,
    identified_pressings: list[dict[str, Any]] | None = None,
    fast_search: bool = False,
    operator_choice: bool = False,
) -> str:
    marketplace = str(row["marketplace"])
    listing_id = str(row["listing_id"])
    title_text = str(row.get("title") or "")
    stored_lot = bool(row.get("bulk_lot")) and classify_media_details(title_text).bulk_lot
    if is_job_lot(title_text) or stored_lot:
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
    listing_media = _listing_media_for_row(row)
    format_name = discogs_search_format(listing_media)
    if format_name is None:
        _set_auction_identity(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            status="unmatched",
            source="discogs",
            thumb_url=None,
            shortlist=[],
        )
        return "unmatched"

    stored_catalog = str(row.get("catalog_number") or "").strip() or None
    token = listing_identity_catalog(
        stored=stored_catalog,
        title=row.get("title"),
        artist=row.get("artist"),
        media_type=listing_media,
    )
    # A catalog saved from an earlier wrong match must not override the
    # album named in the title. 妖女 was locked to the self-titled CAL-04-1039.
    if (
        token
        and known_album_phrase(row.get("title"))
        and not catalog_printed_on_listing(token, row.get("title"))
    ):
        token = listing_identity_catalog(
            stored=None,
            title=row.get("title"),
            artist=row.get("artist"),
            media_type=listing_media,
            infer=False,
        )
    inferred = inferred_release_catalog(
        title=row.get("title"),
        artist=row.get("artist"),
        media_type=listing_media,
    )
    # Discogs titles the Hong Kong LP 梅艷芳. The catalog number is the album.
    # Use it when the listing did not print a different number.
    if inferred and fold_catalog(token) != fold_catalog(inferred):
        if not catalog_printed_on_listing(token, row.get("title")):
            token = inferred
    # A number in the seller description is the copy. Cal 04-1056 is not
    # the Taiwan album that shares the English title.
    printed_description = description_catalog(row.get("description"))
    if printed_description:
        token = printed_description
    persist_catalog = token
    if persist_catalog != stored_catalog and (
        persist_catalog
        or (
            stored_catalog
            and not stored_catalog_fits_listing(
                stored_catalog,
                title=row.get("title"),
                media_type=listing_media,
            )
            and not catalog_printed_on_listing(stored_catalog, row.get("title"))
        )
    ):
        if persist_catalog and stored_catalog and not (
            catalog_has_range(persist_catalog) and not catalog_has_range(stored_catalog)
        ) and catalog_printed_on_listing(stored_catalog, row.get("title")):
            persist_catalog = stored_catalog
        else:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET catalog_number = :catalog_number
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "catalog_number": persist_catalog,
                    "marketplace": marketplace,
                    "listing_id": listing_id,
                },
            )
            row["catalog_number"] = persist_catalog

    pressings = identified_pressings
    if pressings is None and not operator_choice:
        pressings = _identified_pressing_rows(connection)
    # Comparing this title with every saved pressing is several seconds
    # of CPU. The open-row search asks Discogs directly.
    local_hits = (
        ()
        if operator_choice
        else _local_album_search_hits(row, pressings or [])
    )
    if token:
        hits, require_catalog_token = _search_hits_for_row(
            row=row,
            token=token,
            format_name=format_name,
            client=client,
            search_cache=search_cache,
            stats=stats,
            fast_search=fast_search,
            listing_format_only=operator_choice,
        )
        locked_local = tuple(
            hit
            for hit in local_hits
            if catno_locks_listing(hit.catno, token)
        )
        if locked_local:
            seen = {hit.discogs_id for hit in hits or ()}
            hits = tuple(
                [
                    *(hits or ()),
                    *[hit for hit in locked_local if hit.discogs_id not in seen],
                ]
            )
    elif not operator_choice and _local_hits_cover_listing(row, local_hits):
        hits = local_hits
        require_catalog_token = False
    else:
        hits, require_catalog_token = _search_hits_for_row(
            row=row,
            token=token,
            format_name=format_name,
            client=client,
            search_cache=search_cache,
            stats=stats,
            fast_search=fast_search,
            listing_format_only=operator_choice,
        )
        if local_hits:
            seen = {hit.discogs_id for hit in hits}
            hits = tuple(
                [
                    *hits,
                    *[hit for hit in local_hits if hit.discogs_id not in seen],
                ]
            )
            require_catalog_token = False
        if not hits and local_hits and not stats.search_errors:
            hits = local_hits
            require_catalog_token = False
    hits = _hits_agree_with_listing_volume(row.get("title"), hits)
    if printed_description and hits:
        # The description named this catalog. A same-title pressing with
        # another number, such as Taiwan RR-164 for Flaming Lips, stays out.
        locked_hits = tuple(
            hit
            for hit in hits
            if catno_locks_listing(hit.catno, printed_description)
            or catalog_identity_key(hit.catno) == catalog_identity_key(printed_description)
        )
        if locked_hits:
            hits = locked_hits
            require_catalog_token = True
    # The review panel has a short clock. A finished 7" search with no
    # match is "not in the catalog", not a hung Discogs call. Timeouts
    # and a batch fill that ran out of clock still keep the old shortlist.
    search_finished_empty = (
        operator_choice
        and not hits
        and stats.searched
        and not stats.search_errors
    )
    if not hits and not search_finished_empty and (
        stats.search_errors or stats.budget_exhausted
    ):
        stats.aborted = True
        return str(row.get("identity_status") or "unmatched")
    if not hits:
        reused = _reuse_local_pressing(
            connection,
            row=row,
            token=token,
            image_client=image_client,
        )
        if reused is not None:
            stats.reused += 1
            return "filled_auto"
        _set_auction_identity(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            status="unmatched",
            source="discogs",
            thumb_url=None,
            shortlist=[],
        )
        return "unmatched"

    remaining_classification = classify_search_hits(
        catalog_number=token,
        title=row.get("title"),
        artist=listing_search_artist(row.get("artist"), row.get("title")),
        media_type=listing_media,
        hits=hits,
        require_catalog_token=require_catalog_token,
    )
    cover_hash_cache: dict[str, int | None] = {}
    if not operator_choice:
        remaining_classification = _rank_classification_by_listing_photo(
            remaining_classification,
            row=row,
            client=client,
            release_cache=release_cache,
            image_client=image_client,
            extra_hits=hits,
            lookup_releases=True,
            deadline=stats.deadline,
            hash_cache=cover_hash_cache,
        )
    if operator_choice:
        source_hits = remaining_classification.hits or hits
        locked = tuple(
            hit
            for hit in source_hits
            if token and catno_locks_listing(hit.catno, token)
        )
        album_hits = prefer_listing_generation(
            tuple(
                hit
                for hit in source_hits
                if album_name_in_listing(row.get("title"), hit.title)
                and hit_fits_listing_year(row.get("title"), hit.year)
                and artist_overlaps(
                    listing_artist=listing_search_artist(
                        row.get("artist"),
                        row.get("title"),
                    ),
                    listing_title=row.get("title"),
                    discogs_names=names_from_search_hit(hit),
                )
                and not hit_bundles_other_album(row.get("title"), hit.title)
            ),
            row.get("title"),
        )
        # Sleeve hashing downloads every candidate. The click path shows
        # the search thumb instead, so the next row can open immediately.
        cover_hits = ()
        series_hits = tuple(
            hit
            for hit in _series_shortlist_hits(
                row.get("title"),
                hits,
            )
            if hit_fits_listing_year(row.get("title"), hit.year)
        )
        family = _operator_album_family(
            hits,
            title=row.get("title"),
            media_type=listing_media,
            artist=listing_search_artist(row.get("artist"), row.get("title")),
        )
        hits_to_show = family or _merge_cover_hits(locked, cover_hits, album_hits, series_hits)
        if series_hits and re.search(r"stereo sound|\bssar\b", str(row.get("title") or ""), re.I):
            cover_order = {hit.discogs_id: index for index, hit in enumerate(cover_hits)}
            hits_to_show = tuple(
                sorted(
                    series_hits,
                    key=lambda hit: cover_order.get(hit.discogs_id, 1000),
                )
            )[:12]
        if not hits_to_show:
            refined = refine_hits_for_listing(
                source_hits,
                title=row.get("title"),
                media_type=listing_media,
                label=row.get("label"),
            )
            # A named album that did not match must not be filled with other
            # records by the same artist. That is how Premonition of Farewell
            # showed 永遠的珍藏 and 時の流れに身をまかせ.
            if known_album_phrase(row.get("title")) or listing_names_specific_album(
                row.get("title")
            ):
                refined = tuple(
                    hit
                    for hit in refined
                    if album_name_in_listing(row.get("title"), hit.title)
                    or concert_program_related(row.get("title"), hit.title)
                )
                hits_to_show = shortlist_format_options(refined)
            else:
                # A shared word such as Rebirth or Gold is not a match.
                # Other artists, and other albums by the same artist, stay off
                # the card until the sleeve title agrees.
                listing_artist = listing_search_artist(
                    row.get("artist"),
                    row.get("title"),
                )
                kept = tuple(
                    hit
                    for hit in (refined or source_hits)
                    if artist_overlaps(
                        listing_artist=listing_artist,
                        listing_title=row.get("title"),
                        discogs_names=names_from_search_hit(hit),
                    )
                    and (
                        album_name_in_listing(row.get("title"), hit.title)
                        or concert_program_related(row.get("title"), hit.title)
                        or (
                            token
                            and catno_locks_listing(hit.catno, token)
                        )
                    )
                )
                hits_to_show = shortlist_format_options(kept)
        if hits_to_show:
            _set_auction_identity(
                connection,
                marketplace=marketplace,
                listing_id=listing_id,
                status="needs_review",
                source="discogs",
                thumb_url=None,
                shortlist=shortlist_payload(hits_to_show),
            )
            return "needs_review"
        _set_auction_identity(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            status=str(row.get("identity_status") or "unmatched"),
            source="discogs",
            thumb_url=None,
            shortlist=[],
        )
        return str(row.get("identity_status") or "unmatched")
    candidate = _unique_review_candidate(remaining_classification)
    if candidate is not None:
        draft = _release_draft(
            client,
            candidate.discogs_id,
            release_cache,
        )
        if unique_hit_can_auto_fill(
            remaining_classification,
            listing_artist=listing_search_artist(
                row.get("artist"),
                row.get("title"),
            ),
            listing_title=row.get("title"),
            release_artist_names=draft.artist_names,
            listing_catalog=token,
        ) and hit_fits_listing_year(
            row.get("title"),
            draft.release_year,
        ) and listing_media_compatible(
            listing_media,
            draft.media_type,
        ) and _pressing_agrees_with_listing(
            {
                "title": row.get("title"),
                "artist": row.get("artist"),
                "catalog_number": token,
            },
            {
                "display_title": draft.display_title,
                "display_artist": draft.display_artist,
                "catalog_number": draft.catalog_number,
            },
            matrix_on_discogs=printed_matrix_on_discogs(
                remaining_classification.hits or hits,
                token,
            ),
        ) and _unique_shortlist_locks_identity(
            row,
            candidate,
            remaining_classification.hits or (candidate,),
            draft.discogs_thumb_url,
            image_client,
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
        _flag_needs_review(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            hits=remaining_classification.hits or (candidate,),
            thumb_url=None,
        )
        return "needs_review"

    if remaining_classification.status == "needs_review":
        _flag_needs_review(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            hits=remaining_classification.hits,
            thumb_url=None,
        )
        return "needs_review"

    if remaining_classification.hits:
        _flag_needs_review(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            hits=remaining_classification.hits,
            thumb_url=None,
        )
        return "needs_review"

    _set_auction_identity(
        connection,
        marketplace=marketplace,
        listing_id=listing_id,
        status="unmatched",
        source="discogs",
        thumb_url=None,
        shortlist=shortlist_payload(remaining_classification.hits),
    )
    return "unmatched"


def _listing_media_for_row(row: dict[str, Any]) -> str | None:
    """Classifier media, widened to 7\" when the title names an EP/single."""
    classified = classify_media_details(str(row.get("title") or "")).format
    return effective_listing_media(
        classified or row.get("media_type"),
        row.get("title"),
    )


def discogs_extra_formats(format_name: str | None) -> tuple[str | None, ...]:
    """Try every record format; matrix/runout tokens overlap across media."""
    formats: list[str | None] = []

    def add(item: str | None) -> None:
        if item not in formats:
            formats.append(item)

    add(format_name)
    add("Vinyl")
    add('7"')
    add('12"')
    add("CD")
    add("SACD")
    add("Cassette")
    add("DVD")
    add(None)
    return tuple(formats)


def title_search_formats(format_name: str | None) -> tuple[str | None, ...]:
    """LP, CD, cassette, and 7\". Skip the unfiltered Discogs page on title search."""
    formats: list[str | None] = []
    for item in (format_name, "Vinyl", "CD", "Cassette", '7"'):
        if item not in formats:
            formats.append(item)
    return tuple(formats)


def _search_hits_for_row(
    *,
    row: dict[str, Any],
    token: str | None,
    format_name: str,
    client: DiscogsClient,
    search_cache: dict[str, tuple[SearchHit, ...]],
    stats: IdentityFillStats,
    fast_search: bool = False,
    listing_format_only: bool = False,
) -> tuple[tuple[SearchHit, ...] | None, bool]:
    """Search catno+artist+format, then catno, then a short title query."""
    title = str(row.get("title") or "").strip() or None
    raw_artist = str(row.get("artist") or "").strip() or None
    artist = listing_search_artist(raw_artist, title) or None
    queries = _title_queries(raw_artist, title, label=row.get("label"))

    def cached_search(
        cache_key: str,
        *,
        format_filter: str | None = format_name,
        **params: str | None,
    ) -> tuple[SearchHit, ...]:
        if cache_key not in search_cache:
            if stats.deadline is not None and time.monotonic() >= stats.deadline:
                stats.budget_exhausted = True
                return ()
            try:
                search_cache[cache_key] = client.search_releases(
                    catno=params.get("catno"),
                    artist=params.get("artist"),
                    query=params.get("query"),
                    title=params.get("title"),
                    format_name=format_filter,
                )
            except (
                httpx.HTTPStatusError,
                httpx.TimeoutException,
                httpx.TransportError,
            ) as error:
                logger.warning("Discogs search failed; skipping this query")
                stats.search_errors += 1
                search_cache[cache_key] = ()
                if stats.ingest_fail_fast:
                    if isinstance(error, httpx.HTTPStatusError):
                        reason = f"Discogs HTTP {error.response.status_code}"
                    else:
                        reason = "Discogs request failed"
                    stats.stopped_reason = stats.stopped_reason or reason
                    raise
            stats.searched += 1
        return search_cache[cache_key]

    def extra_formats() -> tuple[str | None, ...]:
        return discogs_extra_formats(format_name)

    def title_search(
        query_text: str,
        *,
        formats: tuple[str | None, ...] | None = None,
    ) -> tuple[SearchHit, ...]:
        tokens = _distinctive_title_tokens(title, artist)
        phrase = query_text
        if artist and query_text.startswith(f"{artist} "):
            phrase = query_text[len(artist) + 1 :].strip()
        phrase = _strip_known_artist_from_phrase(phrase, artist)
        combined: list[SearchHit] = []
        seen_ids: set[int] = set()
        for fmt in formats or extra_formats():
            found: tuple[SearchHit, ...] = ()
            if artist and phrase and _use_discogs_title_param(phrase):
                found = cached_search(
                    f"artist|{artist.casefold()}|title|{phrase.casefold()}|{fmt or ''}",
                    artist=artist,
                    title=phrase,
                    format_filter=fmt,
                )
            if not found:
                found = cached_search(
                    f"q|{query_text.casefold()}|{fmt or ''}",
                    format_filter=fmt,
                    query=query_text,
                )
            matched = tuple(
                hit
                for hit in found
                if _hit_matches_title_tokens(hit, tokens)
                or album_name_in_listing(title, hit.title)
                or concert_program_related(title, hit.title)
            )
            hints = listing_label_hints(title=title)
            if hints:
                labeled = prefer_listing_label(matched or found, title=title)
                album_hits = tuple(
                    hit
                    for hit in matched
                    if album_name_in_listing(title, hit.title)
                    or concert_program_related(title, hit.title)
                )
                if labeled or album_hits:
                    merged: list[SearchHit] = []
                    seen_match: set[int] = set()
                    for hit in (*labeled, *album_hits):
                        if hit.discogs_id in seen_match:
                            continue
                        seen_match.add(hit.discogs_id)
                        merged.append(hit)
                    matched = tuple(merged)
                elif matched:
                    matched = ()
            picked = matched
            if not picked and not tokens and not hints:
                picked = tuple(
                    hit
                    for hit in found
                    if artist_overlaps(
                        listing_artist=artist,
                        listing_title=title,
                        discogs_names=names_from_search_hit(hit),
                    )
                )
            for hit in picked:
                if hit.discogs_id in seen_ids:
                    continue
                seen_ids.add(hit.discogs_id)
                combined.append(hit)
        return tuple(combined)

    def with_album_formats(
        seed: tuple[SearchHit, ...],
        *,
        require_token: bool,
    ) -> tuple[tuple[SearchHit, ...], bool]:
        """Catno lock keeps the pressing; title search still adds LP/CD/cassette."""
        if not queries:
            return seed, require_token
        combined = list(seed)
        seen = {hit.discogs_id for hit in seed}
        extras = False
        search_formats = (
            (format_name,)
            if listing_format_only
            else probe_formats()
            if fast_search
            else title_search_formats(format_name)
        )
        # 巨星名曲23 is one title. Sweeping every later seller phrase
        # burns the page budget and still returns nothing.
        numbered_series = bool(re.search(r"巨星名曲\s*\d", title or ""))
        if numbered_series and not fast_search:
            search_formats = (format_name,)
        for index, query_text in enumerate(queries):
            batch = title_search(query_text, formats=search_formats)
            for hit in batch:
                if hit.discogs_id in seen:
                    continue
                seen.add(hit.discogs_id)
                combined.append(hit)
                extras = True
            if numbered_series:
                break
            if listing_names_specific_album(title) and any(
                album_name_in_listing(title, hit.title)
                or concert_program_related(title, hit.title)
                for hit in combined
            ) and not _album_spelling_queries_pending(queries, index + 1, title):
                break
            if (
                len({shortlist_option_shape(hit.formats) for hit in combined}) >= 2
                and not _photo_series_queries_pending(queries[index + 1 :])
            ):
                break
        if extras:
            return tuple(combined), False
        return seed, require_token

    def probe_formats() -> tuple[str | None, ...]:
        """Listing format, then unfiltered. Ghost catnos are not on Discogs."""
        if listing_format_only:
            return (format_name,)
        formats: list[str | None] = []
        for item in (format_name, None):
            if item not in formats:
                formats.append(item)
        return tuple(formats)

    def search_catno(
        catno: str,
        *,
        artist_name: str | None,
        formats: tuple[str | None, ...],
    ) -> tuple[SearchHit, ...]:
        folded = fold_catalog(catno) or catno
        found: list[SearchHit] = []
        seen_batch: set[int] = set()
        for fmt in formats:
            batch = cached_search(
                f"catno|{catno.casefold()}|{folded}|{(artist_name or '').casefold()}|{fmt or ''}",
                catno=catno,
                artist=artist_name,
                format_filter=fmt,
            )
            for hit in batch:
                if hit.discogs_id in seen_batch:
                    continue
                seen_batch.add(hit.discogs_id)
                found.append(hit)
        return tuple(found)

    def prefix_catalog_hits() -> tuple[SearchHit, ...]:
        prefix = catalog_letter_prefix(token)
        if not prefix:
            return ()
        tokens = _distinctive_title_tokens(title, artist)
        combined: list[SearchHit] = []
        seen: set[int] = set()
        for fmt in probe_formats():
            batch = cached_search(
                f"catno|{prefix.casefold()}|{prefix}|{(artist or '').casefold()}|{fmt or ''}",
                catno=prefix,
                artist=artist,
                format_filter=fmt,
            )
            for hit in batch:
                if hit.discogs_id in seen:
                    continue
                if catalog_letter_prefix(hit.catno) != prefix:
                    continue
                if artist and not artist_overlaps(
                    listing_artist=artist,
                    listing_title=title,
                    discogs_names=names_from_search_hit(hit),
                ):
                    continue
                album_hit = album_name_in_listing(title, hit.title)
                if not album_hit:
                    continue
                seen.add(hit.discogs_id)
                combined.append(hit)
        return tuple(combined)

    def barcode_hits() -> tuple[SearchHit, ...]:
        barcode = listing_barcode(title)
        if not barcode:
            return ()
        found = cached_search(
            f"q|{barcode}|{format_name}",
            query=barcode,
        )
        if not found:
            found = cached_search(
                f"q|{barcode}|",
                query=barcode,
                format_filter=None,
            )
        overlapped = tuple(
            hit
            for hit in found
            if artist_overlaps(
                listing_artist=artist,
                listing_title=title,
                discogs_names=names_from_search_hit(hit),
            )
        )
        return overlapped

    if token:
        listing_key = catalog_identity_key(token)
        locked: list[SearchHit] = []
        covering: list[SearchHit] = []
        seen_ids: set[int] = set()
        seen_folds: set[str] = set()
        variant_limit = 1 if listing_format_only else 2 if fast_search else None
        for catno in catalog_search_variants(token)[:variant_limit]:
            folded = fold_catalog(catno) or catno
            if folded in seen_folds and not catalog_has_range(token):
                continue
            hits = search_catno(
                catno,
                artist_name=artist,
                formats=probe_formats(),
            )
            if not hits and artist and not listing_format_only:
                hits = search_catno(
                    catno,
                    artist_name=None,
                    formats=probe_formats(),
                )
            if not hits:
                if not catalog_has_range(token):
                    seen_folds.add(folded)
                continue
            seen_folds.add(folded)
            for hit in hits:
                if hit.discogs_id in seen_ids:
                    continue
                if not artist_overlaps(
                    listing_artist=artist,
                    listing_title=title,
                    discogs_names=names_from_search_hit(hit),
                ):
                    continue
                seen_ids.add(hit.discogs_id)
                if catno_locks_listing(hit.catno, token) or (
                    listing_key and catalog_identity_key(hit.catno) == listing_key
                ):
                    locked.append(hit)
                elif catno_covers_listing_token(hit.catno, token):
                    covering.append(hit)
                elif album_name_in_listing(title, hit.title) and listing_media_compatible(
                    format_name,
                    " ".join(hit.formats),
                ):
                    covering.append(hit)
            if locked:
                break
            if covering and not catalog_has_range(token):
                break
            if hits and not catalog_has_range(token):
                break
        if locked:
            return with_album_formats(tuple(locked), require_token=True)
        if covering:
            return with_album_formats(tuple(covering), require_token=True)
        if not listing_format_only:
            barcode_match = barcode_hits()
            if barcode_match:
                return barcode_match, False
            prefix_hits = prefix_catalog_hits()
            if prefix_hits:
                return prefix_hits, False
        search_queries: list[str] = []
        named_album = known_album_phrase(title)
        if listing_format_only and named_album:
            spellings = (named_album, *equivalent_title_spellings(named_album))
            for spelling in spellings:
                query = f"{artist} {spelling}" if artist else spelling
                if query not in search_queries:
                    search_queries.append(query)
        elif artist and token:
            search_queries.append(f"{artist} {token}")
        for query_text in queries:
            if query_text not in search_queries:
                search_queries.append(query_text)
        combined_titles: list[SearchHit] = []
        seen_titles: set[int] = set()
        locked_from_title: list[SearchHit] = []
        covering_from_title: list[SearchHit] = []
        title_query_limit = (
            len(search_queries)
            if listing_format_only and named_album
            else 1
            if listing_format_only
            else 2
        )
        for title_query in search_queries[:title_query_limit]:
            title_overlap = title_search(title_query, formats=probe_formats())
            if not title_overlap:
                continue
            for hit in title_overlap:
                if hit.discogs_id in seen_titles:
                    continue
                seen_titles.add(hit.discogs_id)
                combined_titles.append(hit)
                if catno_locks_listing(hit.catno, token) or (
                    listing_key
                    and catalog_identity_key(hit.catno) == listing_key
                ):
                    locked_from_title.append(hit)
                elif catno_covers_listing_token(hit.catno, token):
                    covering_from_title.append(hit)
        if locked_from_title:
            return with_album_formats(tuple(locked_from_title), require_token=True)
        if covering_from_title:
            return with_album_formats(tuple(covering_from_title), require_token=True)
        album_titles = tuple(
            hit
            for hit in combined_titles
            if album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        )
        if album_titles:
            # A number printed on the sleeve that Discogs does not have
            # must not hide the 7" the title actually names. Batch fill
            # still refuses to swap a real printed catno for another.
            if (
                not listing_format_only
                and token
                and catalog_printed_on_listing(token, title)
            ):
                return (), True
            return album_titles, False
        return (), True

    if not queries:
        return None, False
    combined_titles: list[SearchHit] = []
    seen_titles: set[int] = set()
    volume_locked: list[SearchHit] = []
    numbered_series = bool(re.search(r"巨星名曲\s*\d", title or ""))
    for index, query_text in enumerate(queries):
        filtered = title_search(
            query_text,
            formats=(
                (format_name,)
                if listing_format_only or (numbered_series and not fast_search)
                else probe_formats()
                if fast_search
                else title_search_formats(format_name)
            ),
        )
        if re.search(r"之歌第", query_text):
            for hit in filtered:
                if hit.discogs_id not in {item.discogs_id for item in volume_locked}:
                    volume_locked.append(hit)
        for hit in filtered:
            if hit.discogs_id in seen_titles:
                continue
            seen_titles.add(hit.discogs_id)
            combined_titles.append(hit)
        if volume_locked:
            seed_keys = {
                _release_album_key(hit)
                for hit in volume_locked
                if _release_album_key(hit)
            }
            extras = [
                hit
                for hit in combined_titles
                if _release_album_key(hit) in seed_keys
            ]
            seen: set[int] = set()
            ordered: list[SearchHit] = []
            for hit in (*volume_locked, *extras):
                if hit.discogs_id in seen:
                    continue
                seen.add(hit.discogs_id)
                ordered.append(hit)
            return tuple(ordered), False
        if listing_names_specific_album(title) and any(
            album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
            for hit in combined_titles
        ) and not _album_spelling_queries_pending(queries, index + 1, title):
            break
        album_shapes = {
            shortlist_option_shape(hit.formats)
            for hit in combined_titles
            if album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        }
        if (
            len(album_shapes) >= 2
            and not _photo_series_queries_pending(queries[index + 1 :])
        ):
            break
        if numbered_series:
            break
    if listing_names_specific_album(title):
        specific = [
            hit
            for hit in combined_titles
            if not hit_bundles_other_album(title, hit.title)
        ]
        if specific:
            combined_titles = specific
    if numbered_series:
        album_hits = tuple(
            hit
            for hit in combined_titles
            if album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        )
        return album_hits, False
    if combined_titles:
        album_hits = tuple(
            hit
            for hit in combined_titles
            if album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        )
        return (album_hits or tuple(combined_titles)), False
    filtered = ()
    tokens = _distinctive_title_tokens(title, artist)
    raw_body = " ".join(tokens[:4])
    raw_query = None
    if raw_body and artist:
        raw_query = f"{artist} {raw_body}"[:100]
    elif raw_body:
        raw_query = raw_body[:100]
    if raw_query and raw_query not in queries:
        combined: list[SearchHit] = []
        seen_raw: set[int] = set()
        for fmt in (
            (format_name,)
            if listing_format_only
            else probe_formats()
            if fast_search
            else extra_formats()
        ):
            raw_hits = cached_search(
                f"q|{raw_query.casefold()}|{fmt or ''}",
                query=raw_query,
                format_filter=fmt,
            )
            for hit in raw_hits:
                if hit.discogs_id in seen_raw:
                    continue
                if not _hit_matches_title_tokens(hit, tokens):
                    continue
                seen_raw.add(hit.discogs_id)
                combined.append(hit)
        filtered = tuple(combined)
    if not filtered and artist and not listing_names_specific_album(title):
        photo_hits = cached_search(
            f"artist-photo|{artist.casefold()}|{format_name}",
            artist=artist,
            format_filter=format_name or "Vinyl",
        )
        filtered = tuple(
            hit
            for hit in photo_hits
            if artist_overlaps(
                listing_artist=artist,
                listing_title=title,
                discogs_names=names_from_search_hit(hit),
            )
        )[:15]
    return filtered, False


_GRIPSWEAT_PREFIX = re.compile(r"^Gripsweat\s*[-–]\s*", re.IGNORECASE)
_SKU_PREFIX = re.compile(r"^\d{6,}[;:]?\s*")
_BRACKET_HINT = re.compile(r"[【\[(（][^】\]\)）]{0,40}[】\]\)）]")
_PRICE_NOISE = re.compile(r"\d+円[〜～]?|\$\d+")
_MARKETPLACE_SPAM = re.compile(
    r"(?:所有|請信息|请信息|截圖|截图|下單|下单|邮費|郵費|合拼|優惠|优惠).*$",
)
_STAR_NOISE = re.compile(r"[★☆◆■●※]+")
_INSPECTION_TAIL = re.compile(r"検\s*[)）].*")
_SKUISH_TOKEN = re.compile(
    r"^(?:mkt|sku|jan)\d|[a-z]{2,4}\d{6,}|(?:best|ベスト)\d{3,}$",
    re.IGNORECASE,
)
_SHIPPING_TOKEN = re.compile(r"佐川|ヤマト|ゆうパック|クリックポスト")
_TITLE_TOKEN = re.compile(
    r"\d{1,2}[\u3040-\u9fff]{2,}|"
    r"\d{1,2}(?:st|nd|rd|th)|"
    r"[A-Za-z0-9]{3,}|"
    r"[\u3040-\u9fff]{2,}[0-9]*",
    re.IGNORECASE,
)
_TITLE_STOP = frozenset(
    {
        "cd",
        "lp",
        "ep",
        "dvd",
        "vhs",
        "cassette",
        "tape",
        "vinyl",
        "record",
        "records",
        "japan",
        "japanese",
        "idol",
        "obi",
        "cbs",
        "sony",
        "from",
        "the",
        "and",
        "with",
        "for",
        "this",
        "that",
        "your",
        "2xlp",
        "gatefold",
        "sleeve",
        "compilation",
        "teresa",
        "teng",
        "国内正規品",
        "国内正規",
        "正規品",
        "未開封品",
        "未開封",
        "帯付き",
        "帯付",
        "永久保存版",
        "momoe",
        "yamaguchi",
        "anita",
        "mui",
        "テレサ",
        "テン",
        "テレサテン",
        "鄧麗君",
        "邓丽君",
        "山口",
        "百恵",
        "梅艷芳",
        "梅艳芳",
        "美盤",
        "美品",
        "極美品",
        "ライブ盤",
        "ライブ",
        "日本盤",
        "帯付",
        "帯付き",
        "帯傷み",
        "プロモ",
        "見本品",
        "見本盤",
        "サンプル",
        "新品",
        "未開封",
        "国内盤",
        "レコード",
        "カセット",
        "カセットテープ",
        "ポスター",
        "ポスター付き",
        "直筆",
        "サイン",
        "サイン入り",
        "直筆サイン入り",
        "歌詞カード",
        "当時物",
        "追悼盤",
        "レア盤",
        "歌謡曲",
        "アナログ盤",
        "台湾盤",
        "香港盤",
        "国内盤",
        "良好美品",
        "ポリドール",
        "コンパクトディスク",
        "未使用品",
        "kolin",
        "taiwan",
        "hongkong",
        "hong",
        "kong",
        "gatefol",
        "中古",
        "中古品",
        "輸入盤",
        "廃盤",
        "gripsweat",
        "insert",
        "inserts",
        "original",
        "送料無料",
        "ゴールドディスク",
        "中国語ベストアルバム",
        "中国語",
        "中国語盤",
        "日本語盤",
        "中華ポップス",
        "昭和歌謡",
        "昭和",
        "歌謡曲",
        "演歌",
        "ポップス",
        "ポリドールレコード",
        "ポリドール",
        "トーラス",
        "taurus",
        "polydor",
        "名盤",
        "女性歌手",
        "和モノ",
        "帯あり",
        "新品同様",
        "激レア",
        "高音質",
        "枚組",
        "枚組揃",
        "枚組cd",
        "現状品",
        "コレクション",
        "香港",
        "台湾",
        "hong",
        "kong",
        "ブックレット",
        "ピクチャー",
        "仕様盤",
        "万セット限定",
        "セット",
        "音楽",
        "直輸入盤",
        "中国語直輸入盤",
        "歌詞本付良好美品",
        "歌詞カード付き",
        "新品未開封",
        "条件付き",
        "の音楽館",
        "best",
        "vol",
        "volume",
        "hits",
        "hit",
        "selection",
        "selections",
        "hybrid",
        "sacd",
        "佐川",
        "ヤマト",
        "まとめて",
        "サイズ",
        "シュリンク",
        "first",
        "検",
        "終了品",
        "重量",
        "送料",
        "年版",
        "所有",
        "以下",
        "mandopop",
        "rare",
        "mint",
        "gram",
        "complete",
        "new",
        "music",
        "chinese",
        "self",
        "titled",
        "factory",
        "polygram",
        "2lp",
        "early",
        "recording",
        "exclusive",
        "unopened",
        "sealed",
        "limited",
        "edition",
        "180g",
    }
)
_TITLE_SEARCH_ALIASES = (
    (re.compile(r"スーパーセレクション"), "Super Selection"),
    (re.compile(r"ゴールデンヒット"), "Golden Hit"),
    (re.compile(r"オリジナルベストカラオケ"), "Original Best Karaoke"),
    (re.compile(r"時の流れに身をまかせ"), "Toki no Nagare ni Mi wo Makase"),
    (re.compile(r"酒醉的探戈|酒酔的探戈"), "Jiu Zui De Tan Ge"),
    (re.compile(r"一個小心願|一个小心愿"), "A Small Wish"),
    (re.compile(r"難忘的一天|难忘的一天"), "Nan Wang De Yi Tian"),
    (re.compile(r"甜蜜蜜"), "Tian Mi Mi"),
    (re.compile(r"矢切の渡し"), "Yagiri no Watashi"),
    (re.compile(r"カバーソング"), "Cover Song"),
    (re.compile(r"影視名曲精選|影视名曲精选"), "Movie Hits"),
    (re.compile(r"夜の乗客"), "Yoru no Jokaku"),
    (re.compile(r"女の生きがい|女のいきがい"), "Onna no Ikigai"),
    (re.compile(r"我只在乎你|我只在乎尓"), "Wo Zhi Zai Hu Ni"),
    (re.compile(r"星願|星愿"), "Xing Yuan"),
    (re.compile(r"全曲集"), "Greatest Hits"),
    (re.compile(r"つぐない|償還"), "Tsugunai"),
    (re.compile(r"31(?:st|th)\s+single|sayonara no mukougawa", re.IGNORECASE), "さよならの向う側"),
    (re.compile(r"evil girl", re.IGNORECASE), "妖女"),
    (re.compile(r"bad girl", re.IGNORECASE), "壞女孩"),
    (re.compile(r"jump stage", re.IGNORECASE), "飛躍舞台"),
    (re.compile(r"flaming(?: red)? lips", re.IGNORECASE), "烈焰紅唇"),
    (re.compile(r"^yokosuka(?:\s+story)?$", re.IGNORECASE), "横須賀ストーリー"),
    (re.compile(r"^again$", re.IGNORECASE), "Again 百恵"),
    (re.compile(r"ラスト[・\s]?コンサート"), "Last Concert"),
    (re.compile(r"ファースト[・\s]?コンサート"), "First Concert"),
    (re.compile(r"momoe\s+festival|from the momoe festival|百恵ちゃん祭り", re.IGNORECASE), "百恵ライブ"),
    (re.compile(r"momoe\s+live", re.IGNORECASE), "百恵ライブ"),
    (re.compile(r"永遠的情懐|永远的情怀"), "永遠的情懷"),
    (re.compile(r"島國之情歌第七集|島國情歌第七集|岛国之情歌第七集"), "假如我是真的"),
    (re.compile(r"島國情歌六(?:集)?|島国情歌第六集"), "小城故事"),
    (re.compile(r"encore\s+live(?:\s+in\s+japan)?(?:\s+concert)?", re.IGNORECASE), "演唱會"),
    (re.compile(r"ベスト[・\s]?10"), "Best 10"),
    (re.compile(r"best\s*20", re.IGNORECASE), "ベスト20"),
    (re.compile(r"anata\s*magokoro", re.IGNORECASE), "まごころ"),
    (re.compile(r"one\s*(?:&\s*|and\s+)?only", re.IGNORECASE), "One & Only"),
    (re.compile(r"stroll\s+through\s+life", re.IGNORECASE), "漫步人生路"),
    (re.compile(r"mistress|ai\s*jin|aijin|あいじん", re.IGNORECASE), "愛人"),
    (re.compile(r"NHK\s+Live", re.IGNORECASE), "NHK Live"),
)
_PHRASE_ALIASES = (
    (re.compile(r"31(?:st|th)\s+single|sayonara no mukougawa", re.IGNORECASE), "さよならの向う側"),
    (re.compile(r"evil girl", re.IGNORECASE), "妖女"),
    (re.compile(r"bad girl", re.IGNORECASE), "壞女孩"),
    (re.compile(r"jump stage", re.IGNORECASE), "飛躍舞台"),
    (re.compile(r"flaming(?: red)? lips", re.IGNORECASE), "烈焰紅唇"),
    (re.compile(r"yokosuka\s+story", re.IGNORECASE), "横須賀ストーリー"),
    (re.compile(r"\bagain\b", re.IGNORECASE), "Again 百恵"),
    (re.compile(r"ラスト[・\s]?コンサート"), "Last Concert"),
    (re.compile(r"ファースト[・\s]?コンサート"), "First Concert"),
    (re.compile(r"momoe\s+festival|from the momoe festival|百恵ちゃん祭り", re.IGNORECASE), "百恵ライブ"),
    (re.compile(r"momoe\s+live", re.IGNORECASE), "百恵ライブ"),
    (re.compile(r"永遠的情懐|永远的情怀"), "永遠的情懷"),
    (re.compile(r"島國之情歌第七集|島國情歌第七集|岛国之情歌第七集"), "假如我是真的"),
    (re.compile(r"島國情歌六(?:集)?|島国情歌第六集"), "小城故事"),
    (re.compile(r"encore\s+live(?:\s+in\s+japan)?(?:\s+concert)?", re.IGNORECASE), "演唱會"),
    (re.compile(r"ベスト[・\s]?10"), "Best 10"),
    (re.compile(r"best\s*20", re.IGNORECASE), "ベスト20"),
    (re.compile(r"anata\s*magokoro", re.IGNORECASE), "まごころ"),
    (re.compile(r"one\s*(?:&\s*|and\s+)?only", re.IGNORECASE), "One & Only"),
    (re.compile(r"stroll\s+through\s+life", re.IGNORECASE), "漫步人生路"),
    (re.compile(r"mistress|ai\s*jin|aijin|あいじん", re.IGNORECASE), "愛人"),
)


_WEAK_DISCOGS_TITLE_PHRASE = re.compile(
    r"^(?:19[4-9]\d|20[0-2]\d|polydor|polygram|taurus|sony|cbs|"
    r"stereo\s*sound|space\s*records?|vol(?:ume)?\.?\s*\d{1,2})$",
    re.IGNORECASE,
)


def _use_discogs_title_param(phrase: str) -> bool:
    """Label/year fragments belong in q=, not Discogs title=."""
    parts = [part for part in re.split(r"\s+", phrase.strip()) if part]
    if not parts:
        return False
    return not all(_WEAK_DISCOGS_TITLE_PHRASE.fullmatch(part) for part in parts)


def _cleaned_listing_title(title: str | None) -> str:
    cleaned = _GRIPSWEAT_PREFIX.sub("", (title or "").strip())
    cleaned = _SKU_PREFIX.sub("", cleaned)
    cleaned = _BRACKET_HINT.sub(" ", cleaned)
    cleaned = _INSPECTION_TAIL.sub(" ", cleaned)
    cleaned = _PRICE_NOISE.sub(" ", cleaned)
    cleaned = _MARKETPLACE_SPAM.sub(" ", cleaned)
    cleaned = _STAR_NOISE.sub(" ", cleaned)
    cleaned = re.sub(r"[【】\[\]]+", " ", cleaned)
    cleaned = _SPACE_RECORD_VOLUME.sub(
        lambda match: _cjk_songbook_volume(int(match.group(1))),
        cleaned,
    )
    cleaned = re.sub(r"玉女巨星", " ", cleaned)
    cleaned = _SHIPPING_TOKEN.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:MKT|SKU|JAN)\d+\w*\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-Z]{2,4}\d{6,}\b", " ", cleaned)
    cleaned = re.sub(r"\+\s+[A-Za-z].{0,60}$", " ", cleaned)
    cleaned = cleaned.replace("・", " ").replace("「", " ").replace("」", " ")
    cleaned = cleaned.replace("《", " ").replace("》", " ").replace("『", " ").replace("』", " ")
    for pattern, replacement in _PHRASE_ALIASES:
        cleaned = pattern.sub(replacement, cleaned)
    return re.sub(r"[\s/|,]+", " ", cleaned).strip()


def _alias_title_token(token: str) -> str:
    for pattern, replacement in _TITLE_SEARCH_ALIASES:
        if pattern.search(token):
            return replacement
    return token


def _strip_known_artist_from_phrase(phrase: str, artist: str | None = None) -> str:
    """Drop テレサテン from quoted albums and 鄧麗君 from 鄧麗君小城故事."""
    leftover = phrase.replace("玉女巨星", " ")
    leftover = re.sub(r"\s+", " ", leftover).strip(" ・")
    if _is_known_album_title(leftover or phrase):
        return leftover or phrase
    leftover = leftover or phrase
    for part in re.split(r"[\s・]+", phrase):
        if _is_known_artist_name(part):
            leftover = leftover.replace(part, " ")
    leftover = re.sub(r"\s+", " ", leftover).strip(" ・")
    if leftover and _is_known_album_title(leftover):
        return leftover
    listing_key = canonical_artist_key(artist) if artist else ""
    compact = _script_compact(leftover or phrase)
    aliases = [
        alias
        for alias, canon in _ARTIST_CANON.items()
        if listing_key and canon == listing_key
    ]
    aliases.sort(key=len, reverse=True)
    for alias in aliases:
        if compact.startswith(alias) and len(compact) > len(alias) + 1:
            remainder = compact[len(alias) :]
            if remainder and not _is_known_artist_name(remainder):
                return remainder
    return leftover or phrase


def _concert_program_search_alias(title: str | None) -> str | None:
    text = title or ""
    if re.search(r"ファースト[・\s]?コンサート|first\s*concert", text, re.IGNORECASE):
        return "First Concert"
    if re.search(r"ラスト[・\s]?コンサート|last\s*concert", text, re.IGNORECASE):
        return "Last Concert"
    return None


def _photo_series_queries_pending(queries: Sequence[str]) -> bool:
    """Keep searching when later queries are Part II / Stereo Sound photo hints."""
    return any(
        re.search(r"stereo sound|analog record|後編|\bpart\b", query, re.IGNORECASE)
        for query in queries
    )


def _quoted_album_phrases(
    title: str | None,
    artist: str | None = None,
) -> tuple[str, ...]:
    phrases: list[str] = []
    text = title or ""
    for match in _QUOTED_ALBUM.finditer(text):
        phrase = _INNER_ANGLE.sub(" ", match.group(1))
        phrase = re.sub(r"\s+", " ", phrase).strip()
        if len(phrase) >= 2 and not re.search(r"[「『《]", phrase):
            phrases.append(_strip_known_artist_from_phrase(phrase, artist))
    for match in _ASCII_QUOTED_ALBUM.finditer(text):
        phrase = re.sub(r"\s+", " ", match.group(1)).strip()
        if len(phrase) >= 2 and not _QUOTE_NOISE.fullmatch(phrase):
            phrases.append(phrase)
    for match in _PAREN_ALBUM.finditer(text):
        album = _album_from_paren_inner(match.group(1))
        if album:
            phrases.append(album)
    phrases.extend(_slash_album_phrases(title))
    return tuple(dict.fromkeys(phrases))


def _slash_album_phrases(title: str | None) -> tuple[str, ...]:
    """Album names after Buyee ``artist / 淡淡幽情`` slashes, not the artist lead."""
    cleaned = _SKU_PREFIX.sub("", (title or "").strip())
    cleaned = _BRACKET_HINT.sub(" ", cleaned)
    parts = [
        re.sub(r"\s+", " ", part).strip(" ;:-|")
        for part in re.split(r"[/／]", cleaned)
    ]
    if len(parts) < 2:
        return ()
    rest = parts[1:]
    # 「山口百恵 / 沢田研二 / 私は小鳥」: the middle credit is another singer.
    # Song titles on these singles use kana. A short kanji name is the guest.
    has_kana_song = any(re.search(r"[\u3040-\u30ff]", part) for part in rest)
    albums: list[str] = []
    for part in rest:
        if not part or _QUOTE_NOISE.fullmatch(part):
            continue
        if _slash_part_is_noise(part):
            continue
        if _is_known_artist_name(part):
            continue
        if has_kana_song and re.fullmatch(r"[\u4e00-\u9fff]{2,5}", re.sub(r"\s+", "", part)):
            continue
        compact = re.sub(r"\s+", "", part)
        if _is_known_album_title(part) or (
            _JP_CHAR.search(part) and 2 <= len(compact) <= 16
        ):
            albums.append(part)
    return tuple(albums)


def _album_from_paren_inner(inner: str) -> str | None:
    scored: list[tuple[int, str]] = []
    for part in re.split(r"[/／]", inner):
        cleaned = re.sub(r"\s+", " ", part).strip()
        if not cleaned or _QUOTE_NOISE.fullmatch(cleaned):
            continue
        if _EDITION_ONLY.fullmatch(cleaned):
            continue
        compact = _EDITION_MARK.sub("", cleaned)
        if _is_known_artist_name(cleaned):
            continue
        if _JP_CHAR.search(cleaned) and len(compact) >= 2:
            scored.append((len(compact), cleaned))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _cjk_songbook_volume(number: int) -> str:
    ones = "一二三四五六七八九"
    if number == 10:
        token = "十"
    elif 1 <= number <= 9:
        token = ones[number - 1]
    elif 11 <= number <= 19:
        token = "十" + ones[number - 11]
    else:
        token = str(number)
    return f"之歌第{token}集"


def _title_query(artist: str | None, title: str | None) -> str | None:
    """Keep Discogs q= short so Buyee lot titles do not 500 the search API."""
    return _compose_title_query(artist, title, alias_tokens=False)


def _aliased_title_query(artist: str | None, title: str | None) -> str | None:
    return _compose_title_query(artist, title, alias_tokens=True)


def _compose_title_query(
    artist: str | None,
    title: str | None,
    *,
    alias_tokens: bool,
) -> str | None:
    raw = (artist or "").strip() or None
    if raw:
        mapped = listing_search_artist(raw, title)
        if mapped:
            raw = mapped
        elif re.search(r"\d{8,}|[【\[]", raw) or len(raw) > 40:
            raw = None
    artist = raw
    named = known_album_phrase(title)
    if named and re.sub(r"[\s・]", "", named).casefold() in {"星願", "星愿", "xingyuan"}:
        if artist:
            return f"{artist} {named}"[:100]
        return named[:100]
    quoted = _quoted_album_phrases(title, artist)
    if quoted:
        body = quoted[0]
        if alias_tokens:
            body = _alias_title_token(body)
        if artist:
            return f"{artist} {body}"[:100]
        return body[:100]
    raw_tokens = _distinctive_title_tokens(title, artist)
    tokens = (
        [_alias_title_token(token) for token in raw_tokens]
        if alias_tokens
        else list(raw_tokens)
    )
    if tokens:
        body = " ".join(tokens[:4])
        if artist:
            return f"{artist} {body}"[:100]
        return body[:100]
    leftover: list[str] = []
    for part in _TITLE_TOKEN.findall(_cleaned_listing_title(title)):
        part = re.sub(r"(?:19[4-9]\d|20[0-2]\d)$", "", part)
        if not part:
            continue
        artist_stripped = _strip_known_artist_from_phrase(part, artist)
        if artist_stripped and artist_stripped != part:
            part = artist_stripped
        key = part.replace("・", "").casefold()
        if (
            part.isdigit()
            or re.fullmatch(r"\d+枚組", part)
            or key in _TITLE_STOP
            or _SKUISH_TOKEN.search(part)
            or _SHIPPING_TOKEN.search(part)
            or (
                artist
                and canonical_artist_key(part) == canonical_artist_key(artist)
            )
        ):
            continue
        leftover.append(_alias_title_token(part) if alias_tokens else part)
    cleaned = " ".join(leftover)[:80]
    if artist and cleaned:
        if artist.casefold() in cleaned.casefold():
            return cleaned[:100]
        return f"{artist} {cleaned}"[:100]
    return (cleaned or "")[:100] or None


def _album_spelling_queries_pending(
    queries: tuple[str, ...] | list[str],
    start: int,
    title: str | None,
) -> bool:
    """Keep going while a later query is the spelling Discogs actually uses."""
    album = known_album_phrase(title)
    if not album:
        return False
    keys = [
        key
        for spelling in equivalent_title_spellings(album)
        if (key := _script_compact(spelling))
    ]
    if not keys:
        return False
    for query in queries[start:]:
        compact = _script_compact(query)
        if any(key in compact for key in keys):
            return True
    return False


def _title_queries(
    artist: str | None,
    title: str | None,
    label: str | None = None,
) -> tuple[str, ...]:
    """CJK title first, then label, volume, simplified Hanzi, and romanized aliases."""
    queries: list[str] = []
    mapped = listing_search_artist(artist, title) if artist or title else None

    def _add(value: str | None) -> None:
        text = (value or "").strip()
        if not text:
            return
        for variant in hanzi_variants(text):
            if variant not in queries:
                queries.append(variant)

    album = known_album_phrase(title)
    if album:
        spellings = (album, *equivalent_title_spellings(album))
        for spelling in spellings:
            if mapped:
                _add(f"{mapped} {spelling}")
            else:
                _add(spelling)
    elif (greatest := _GREAT_HITS_PHRASE.search(title or "")):
        phrase = re.sub(r"\s+", " ", greatest.group(0)).strip()
        if mapped:
            _add(f"{mapped} {phrase}")
        else:
            _add(phrase)
    if (
        mapped == "Teresa Teng"
        and re.search(r"made\s+in\s+germany", title or "", re.IGNORECASE)
        and not album
    ):
        _add(f"{mapped} 25週年")
    if mapped == "Anita Mui" and re.search(r"splatter", title or "", re.IGNORECASE):
        _add(f"{mapped} 赤色梅艷芳")
    named_volume = listing_volume_number(title)
    if mapped and named_volume and re.search(r"巨星名曲", title or ""):
        _add(f"{mapped} 巨星名曲{named_volume}")
    if mapped and listing_is_self_titled(title):
        local = artist_local_name(mapped)
        year = extract_release_year(title)
        if local:
            _add(f"{mapped} {local}")
            if year:
                _add(f"{mapped} {local} {year}")
    hints = listing_label_hints(title=title, label=label)
    if mapped and "stereo sound" in hints and not listing_names_specific_album(title):
        _add(f"{mapped} SSAR")
    if mapped and "stereo sound" in hints:
        for token in _distinctive_title_tokens(title, mapped):
            aliased = _alias_title_token(token)
            if _JP_CHAR.search(aliased):
                _add(f"{mapped} stereo sound {aliased}")
    wanted = listing_volume_number(title)
    if mapped and wanted is not None and re.search(r"之歌第|宇宙唱片|太空唱片", title or ""):
        songbook = _cjk_songbook_volume(wanted)
        _add(f"{mapped} {songbook}")
        _add(f"{mapped} 第{wanted}集")
    query_artist = mapped or artist
    for value in (
        _title_query(query_artist, title),
        _aliased_title_query(query_artist, title),
    ):
        _add(value)
    concert_alias = _concert_program_search_alias(title)
    analog = bool(re.search(r"\blp\b|レコード|帯付|vinyl|アナログ", title or "", re.I))
    if mapped and concert_alias and analog:
        _add(f"{mapped} {concert_alias} Part")
        _add(f"{mapped} {concert_alias} 後編")
        _add(f"{mapped} stereo sound")
        _add(f"{mapped} Analog Record Collection")
    for token in _distinctive_title_tokens(title, mapped):
        stripped = re.sub(r"\d+$", "", token)
        if (
            stripped != token
            and _JP_CHAR.search(stripped)
            and len(stripped) >= 2
        ):
            if mapped:
                _add(f"{mapped} {stripped}")
            _add(stripped)
    volume = None
    wanted = listing_volume_number(title)
    if wanted is not None:
        volume = f"Vol. {wanted}"
        if mapped:
            _add(f"{mapped} {volume}")
            if re.search(r"\bbest\b", title or "", re.IGNORECASE):
                _add(f"{mapped} Best {volume}")
        else:
            _add(volume)
    for hint in listing_label_hints(title=title, label=label):
        if mapped:
            if volume:
                _add(f"{mapped} {hint} {volume}")
            _add(f"{mapped} {hint}")
        elif volume:
            _add(f"{hint} {volume}")
        else:
            _add(hint)
    space = _SPACE_RECORD_VOLUME.search(title or "")
    if space or re.search(r"space\s+records?", title or "", re.IGNORECASE):
        if space:
            number = int(space.group(1))
            songbook = _cjk_songbook_volume(number)
            if mapped:
                _add(f"{mapped} {songbook}")
            else:
                _add(songbook)
        if mapped:
            _add(f"{mapped} 鄧麗君之歌第")
            _add(f"{mapped} 宇宙唱片")
            _add("鄧麗君 AWK")
    if mapped and re.search(r"\b180g\b|\bssar-?\d+", title or "", re.IGNORECASE):
        _add(f"{mapped} stereo sound")
        _add(f"{mapped} Analog Record Collection")
    year = extract_release_year(title)
    if mapped and year:
        _add(f"{mapped} {year}")
        for hint in listing_label_hints(title=title, label=label):
            _add(f"{mapped} {hint} {year}")
    return tuple(queries[:10])


def _distinctive_title_tokens(
    title: str | None,
    artist: str | None,
) -> tuple[str, ...]:
    blob = _cleaned_listing_title(title)
    artist_fold = re.sub(r"[\s・]", "", artist or "").casefold()
    tokens: list[str] = []
    seen: set[str] = set()
    for phrase in _quoted_album_phrases(title, artist):
        key = phrase.casefold()
        if key in seen or (artist_fold and key in artist_fold):
            continue
        seen.add(key)
        tokens.append(phrase)
    for match in _GREAT_HITS_PHRASE.finditer(title or ""):
        phrase = match.group(0)
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(phrase)
    for match in _VOLUME_KEEP_PHRASE.finditer(title or ""):
        phrase = match.group(0)
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(phrase)
    for match in _WORK_KEEP_PHRASE.finditer(title or ""):
        phrase = match.group(0)
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(phrase)
    for part in _TITLE_TOKEN.findall(blob):
        part = re.sub(r"(?:19[4-9]\d|20[0-2]\d)$", "", part)
        if not part:
            continue
        artist_stripped = _strip_known_artist_from_phrase(part, artist)
        if artist_stripped and artist_stripped != part:
            part = artist_stripped
        compact = part.replace("・", "")
        key = compact.casefold()
        if (
            part.isdigit()
            or re.fullmatch(r"\d+枚組", part)
            or key in _TITLE_STOP
            or key in seen
            or (artist_fold and key in artist_fold)
            or (
                artist
                and canonical_artist_key(part) == canonical_artist_key(artist)
            )
            or is_modern_reissue_catalog(part)
            or _SKUISH_TOKEN.search(part)
            or _SHIPPING_TOKEN.search(part)
        ):
            continue
        seen.add(key)
        tokens.append(part)
        if len(tokens) == 8:
            break
    volume_kept = any(_VOLUME_KEEP_PHRASE.search(token) for token in tokens)
    if any(_JP_CHAR.search(token) for token in tokens) and not volume_kept:
        return tuple(
            token
            for token in tokens
            if _JP_CHAR.search(token)
            or _GREAT_HITS_PHRASE.search(token)
            or _WORK_KEEP_PHRASE.search(token)
            or (token.isascii() and token.isupper() and len(token) >= 4)
        )
    return tuple(tokens)


_QUOTED_ALBUM = re.compile(r"[「『《]([^」』》「『《]{2,40})[」』》]")
_ASCII_QUOTED_ALBUM = re.compile(r'"([^"]{2,40})"')
_PAREN_ALBUM = re.compile(r"[（(]([^)）]{2,60})[)）]")
_INNER_ANGLE = re.compile(r"[〈<][^〉>]{0,20}[〉>]")
_GREAT_HITS_PHRASE = re.compile(
    r"greatest\s+hits(?:\s+vol(?:ume)?\.?\s*\d+)?",
    re.IGNORECASE,
)
_VOLUME_KEEP_PHRASE = re.compile(
    r"(?:best\s+)?vol(?:ume)?\.?\s*\d{1,2}",
    re.IGNORECASE,
)
_WORK_KEEP_PHRASE = re.compile(
    r"one\s*(?:&\s*|and\s+)?only|NHK\s+Live|stroll\s+through\s+life|anata\s*magokoro",
    re.IGNORECASE,
)
_SPACE_RECORD_VOLUME = re.compile(
    r"(?:taiwan\s+)?space\s+records?\s+vol(?:ume)?\.?\s*(\d{1,2})",
    re.IGNORECASE,
)
_QUOTE_NOISE = re.compile(
    r'^(?:lp|ep|cd|dvd|ld|vhs|7"?|12"?|vinyl|record)$',
    re.IGNORECASE,
)
_EDITION_ONLY = re.compile(
    r"^(?:銀圈|金装|金裝|銀標|黒膠|黑膠|彩色)*\s*[A-Z]?\d{0,5}\s*版?$",
    re.IGNORECASE,
)
_EDITION_MARK = re.compile(r"銀圈|金装|金裝|銀標|黒膠|黑膠|彩色|版|[A-Z]?\d{2,5}")
_JP_CHAR = re.compile(r"[\u3040-\u9fff]")


def _compact_title_text(value: str) -> str:
    folded = fold_hanzi(value)
    return re.sub(r"[\s・=＊*'\"]+", "", folded)


def _hit_matches_title_tokens(hit: SearchHit, tokens: Sequence[str]) -> bool:
    if not tokens:
        return True
    blob = hit.title
    blob_cf = blob.casefold()
    compact_blob = _compact_title_text(blob)
    compact_blob_cf = compact_blob.casefold()
    for token in tokens:
        if len(token) < 2:
            continue
        aliased = _alias_title_token(token)
        compact_token = _compact_title_text(token)
        compact_alias = _compact_title_text(aliased)
        if token in blob or token.casefold() in blob_cf:
            return True
        if compact_token and compact_token in compact_blob:
            return True
        if "之歌" in token:
            token_vol = listing_volume_number(token)
            hit_vol = listing_volume_number(blob)
            if token_vol is not None and hit_vol in {None, token_vol}:
                return True
            if "之歌" in blob and (
                token_vol is None or hit_vol is None or token_vol == hit_vol
            ):
                return True
            continue
        stem = re.sub(r"\d+$", "", compact_token)
        if stem != compact_token and len(stem) >= 2 and stem in compact_blob:
            return True
        token_key = canonical_title_key(token)
        blob_key = canonical_title_key(hit.title)
        if token_key and blob_key and token_key == blob_key:
            return True
        if aliased != token and (
            aliased in blob
            or aliased.casefold() in blob_cf
            or compact_alias in compact_blob
            or compact_alias.casefold() in compact_blob_cf
        ):
            return True
    return False


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
    image_client: httpx.Client | None = None,
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
                        image_url,
                        bulk_lot,
                        discogs_shortlist
                    FROM warehouse.auction
                    WHERE identity_status = 'needs_review'
                      AND COALESCE(bulk_lot, false) IS NOT TRUE
                      AND jsonb_typeof(discogs_shortlist) = 'array'
                      AND jsonb_array_length(discogs_shortlist) BETWEEN 1 AND 12
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
        if not hits or len(hits) > 12:
            continue
        if is_job_lot(str(row.get("title") or "")):
            continue
        listing_media = _listing_media_for_row(row)
        try:
            resolved_artist = listing_search_artist(
                row.get("artist"),
                row.get("title"),
            )
            token = catalog_token(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
            )
            hits = covering_hits_for_listing(
                hits,
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
            )
            if token and not hits:
                continue
            preliminary = classify_search_hits(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
                artist=resolved_artist,
                media_type=listing_media,
                hits=hits,
            )
            if preliminary.chosen is None and not token:
                preliminary = _keep_usable_classification(
                    preliminary,
                    classify_search_hits(
                        catalog_number=row.get("catalog_number"),
                        title=row.get("title"),
                        artist=resolved_artist,
                        media_type=listing_media,
                        hits=hits,
                        require_catalog_token=False,
                    ),
                )
            candidate = preliminary.chosen or _unique_review_candidate(preliminary)
            if candidate is None:
                continue
            draft = _release_draft(client, candidate.discogs_id, release_cache)
            classification = classify_search_hits(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
                artist=resolved_artist,
                media_type=listing_media,
                hits=hits,
                discogs_artist_names=draft.artist_names,
            )
            if classification.chosen is None and not token:
                classification = _keep_usable_classification(
                    classification,
                    classify_search_hits(
                        catalog_number=row.get("catalog_number"),
                        title=row.get("title"),
                        artist=resolved_artist,
                        media_type=listing_media,
                        hits=hits,
                        discogs_artist_names=draft.artist_names,
                        require_catalog_token=False,
                    ),
                )
            if not unique_hit_can_auto_fill(
                classification,
                listing_artist=resolved_artist,
                listing_title=row.get("title"),
                release_artist_names=draft.artist_names,
                listing_catalog=catalog_token(
                    catalog_number=None,
                    title=row.get("title"),
                ),
            ):
                continue
            if not hit_fits_listing_year(row.get("title"), draft.release_year):
                continue
            if not listing_media_compatible(listing_media, draft.media_type):
                continue
            if not _pressing_agrees_with_listing(
                {
                    "title": row.get("title"),
                    "artist": row.get("artist"),
                    "catalog_number": None,
                },
                {
                    "display_title": draft.display_title,
                    "display_artist": draft.display_artist,
                    "catalog_number": draft.catalog_number,
                },
                matrix_on_discogs=printed_matrix_on_discogs(hits, token),
            ):
                continue
            if not _unique_shortlist_locks_identity(
                row,
                candidate,
                hits,
                draft.discogs_thumb_url,
                image_client,
            ):
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
            logger.warning(
                "identity promote skipped %s %s after Discogs HTTP error",
                row.get("marketplace"),
                row.get("listing_id"),
            )
            continue
        except Exception:
            logger.warning(
                "identity promote skipped %s %s",
                row.get("marketplace"),
                row.get("listing_id"),
            )


def _hash_shortlist_covers(
    hits: Sequence[SearchHit],
    *,
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    image_client: httpx.Client,
    cache: dict[str, int | None],
    listing_hashes: Sequence[int] = (),
    lookup_releases: bool = True,
    deadline: float | None = None,
) -> tuple[list[int | None], list[str | None], list[str]]:
    """Hash search thumbs and Discogs release images; pick the closest sleeve."""
    hashes: list[int | None] = []
    thumbs: list[str | None] = []
    sides: list[str] = []
    for hit in hits:
        if deadline is not None and time.monotonic() >= deadline:
            break
        urls: list[str] = []
        if hit.thumb_url:
            urls.append(hit.thumb_url)
        if lookup_releases:
            try:
                payload = client.get_release(hit.discogs_id)
                release_cache[hit.discogs_id] = map_release_payload(payload)
                for image in payload.get("images") or []:
                    url = str(image.get("uri") or image.get("uri150") or "").strip()
                    if url and url not in urls:
                        urls.append(url)
            except DiscogsRateLimitError:
                raise
            except Exception:
                draft_url = None
                try:
                    draft_url = _release_draft(
                        client,
                        hit.discogs_id,
                        release_cache,
                    ).discogs_thumb_url
                except Exception:
                    draft_url = None
                if draft_url and draft_url not in urls:
                    urls.append(draft_url)
        best_hash: int | None = None
        best_url = hit.thumb_url
        best_dist: int | None = None
        best_image: Any = None
        for url in urls:
            image = fetch_image(url, client=image_client)
            if image is None:
                hashed = hash_image_url(url, client=image_client, cache=cache)
                if hashed is None:
                    continue
                cover_set = (hashed,)
            else:
                cover_set = image_hashes(image)
            for hashed in cover_set:
                if listing_hashes:
                    dist = min(
                        hamming_distance(listing_hash, hashed)
                        for listing_hash in listing_hashes
                    )
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_hash = hashed
                        best_url = url
                        best_image = image
                elif best_hash is None:
                    best_hash = hashed
                    best_url = url
                    best_image = image
        hashes.append(best_hash)
        thumbs.append(best_url)
        sides.append(image_color_side(best_image) if best_image is not None else "neutral")
    return hashes, thumbs, sides


def _cover_search_formats(format_name: str | None) -> tuple[str | None, ...]:
    """One format per leftover photo pass. Extra formats belong to catno search."""
    return (format_name,) if format_name else (None,)


def _cover_hits_from_artist_search(
    row: dict[str, Any],
    *,
    client: DiscogsClient,
    search_cache: dict[str, tuple[SearchHit, ...]],
    stats: IdentityFillStats,
) -> tuple[SearchHit, ...]:
    """Discogs artist+album search used when title/catno shortlists miss."""
    artist = listing_search_artist(row.get("artist"), row.get("title"))
    if not artist:
        return ()
    format_name = discogs_search_format(_listing_media_for_row(row))
    hits: list[SearchHit] = []
    seen_ids: set[int] = set()
    searches: list[tuple[str, str | None, str | None]] = []
    for token in _distinctive_title_tokens(row.get("title"), artist)[:2]:
        query = f"{artist} {token}"
        searches.append((f"cover-title|{query.casefold()}", artist, query))
    wanted = listing_volume_number(row.get("title"))
    listing_title = str(row.get("title") or "")
    if wanted is not None:
        volume_query = f"{artist} Vol. {wanted}"
        searches.append((f"cover-vol|{volume_query.casefold()}", artist, volume_query))
        if re.search(r"之歌第|宇宙唱片|太空唱片|space\s+records?", listing_title):
            songbook = f"{artist} {_cjk_songbook_volume(wanted)}"
            searches.append((f"cover-songbook|{songbook.casefold()}", artist, songbook))
        else:
            space = _SPACE_RECORD_VOLUME.search(listing_title)
            if space:
                songbook = f"{artist} {_cjk_songbook_volume(int(space.group(1)))}"
                searches.append((f"cover-songbook|{songbook.casefold()}", artist, songbook))
    for hint in listing_label_hints(title=row.get("title"), label=row.get("label")):
        if hint == "space record" and re.search(r"之歌第", listing_title):
            continue
        hint_query = f"{artist} {hint}"
        searches.append((f"cover-label|{hint_query.casefold()}", artist, hint_query))
    if not re.search(r"之歌第", listing_title):
        searches.append((f"cover-artist|{artist.casefold()}", artist, None))
    for cache_key, search_artist_name, query in searches:
        for fmt in _cover_search_formats(format_name):
            keyed = f"{cache_key}|{fmt or ''}"
            if keyed not in search_cache:
                try:
                    search_cache[keyed] = client.search_releases(
                        artist=search_artist_name,
                        query=query,
                        format_name=fmt,
                    )
                except httpx.HTTPError:
                    search_cache[keyed] = ()
                stats.searched += 1
            for hit in search_cache[keyed]:
                if hit.discogs_id in seen_ids:
                    continue
                seen_ids.add(hit.discogs_id)
                hits.append(hit)
    return tuple(
        hit
        for hit in hits
        if artist_overlaps(
            listing_artist=artist,
            listing_title=row.get("title"),
            discogs_names=names_from_search_hit(hit),
        )
    )


def _persist_cover_hit(
    engine: Engine,
    *,
    row: dict[str, Any],
    chosen: SearchHit,
    hits: Sequence[SearchHit],
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
    require_title_agreement: bool = False,
) -> bool:
    """Assign the Discogs release whose sleeve matched the listing photo."""
    try:
        draft = _release_draft(client, chosen.discogs_id, release_cache)
    except DiscogsRateLimitError:
        raise
    except Exception:
        return False
    if not artist_overlaps(
        listing_artist=listing_search_artist(row.get("artist"), row.get("title")),
        listing_title=row.get("title"),
        discogs_names=draft.artist_names,
    ):
        return False
    if not listing_media_compatible(_listing_media_for_row(row), draft.media_type):
        return False
    hints = listing_label_hints(title=row.get("title"))
    agrees = _pressing_agrees_with_listing(
        {
            "title": row.get("title"),
            "artist": row.get("artist"),
            "catalog_number": None,
        },
        {
            "display_title": draft.display_title,
            "display_artist": draft.display_artist,
            "catalog_number": draft.catalog_number,
            "label_name": draft.label_name,
        },
    )
    if not agrees:
        if require_title_agreement or not hints:
            return False
        blob = " ".join(
            [
                str(draft.label_name or ""),
                str(draft.catalog_number or ""),
            ]
        ).casefold()
        if not any(
            hint in blob or (hint == "stereo sound" and "ssar" in blob)
            for hint in hints
        ):
            return False
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
            shortlist=shortlist_payload(tuple(hits)[:12]),
        )
    stats.filled_auto += 1
    stats.cover_matched += 1
    return True


def _hit_agrees_with_listing(row: dict[str, Any], hit: SearchHit) -> bool:
    """True when a Discogs hit names the listing catno or album."""
    names = names_from_search_hit(hit)
    return _pressing_agrees_with_listing(
        {
            "title": row.get("title"),
            "artist": row.get("artist"),
            "catalog_number": None,
        },
        {
            "display_title": hit.title,
            "display_artist": names[0] if names else None,
            "catalog_number": hit.catno,
            "labels": hit.labels,
            "label_name": " ".join(hit.labels),
        },
    )


def _fill_from_cover_hits(
    engine: Engine,
    *,
    row: dict[str, Any],
    hits: Sequence[SearchHit],
    listing_hashes: Sequence[int],
    hit_hashes: Sequence[int | None],
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
) -> bool:
    """Fill from Discogs hits that already name the listing album or catno."""
    agreed: list[SearchHit] = []
    agreed_hashes: list[int | None] = []
    for hit, hashed in zip(hits, hit_hashes):
        if not _hit_agrees_with_listing(row, hit):
            continue
        agreed.append(hit)
        agreed_hashes.append(hashed)
    if not agreed:
        hints = listing_label_hints(title=row.get("title"))
        if not hints or not listing_hashes:
            return False
        labeled: list[SearchHit] = []
        labeled_hashes: list[int | None] = []
        for hit, hashed in zip(hits, hit_hashes):
            if hashed is None:
                continue
            if not prefer_listing_label((hit,), title=row.get("title")):
                continue
            labeled.append(hit)
            labeled_hashes.append(hashed)
        chosen = choose_cover_hit_multi(
            listing_hashes,
            labeled,
            labeled_hashes,
            max_distance=COVER_MAX_DISTANCE,
            unique_gap=COVER_UNIQUE_GAP,
        )
        if chosen is None:
            return False
        return _persist_cover_hit(
            engine,
            row=row,
            chosen=chosen,
            hits=labeled,
            client=client,
            release_cache=release_cache,
            stats=stats,
            require_title_agreement=False,
        )
    if len(agreed) == 1:
        return _persist_cover_hit(
            engine,
            row=row,
            chosen=agreed[0],
            hits=agreed,
            client=client,
            release_cache=release_cache,
            stats=stats,
        )
    chosen = choose_cover_hit_multi(
        listing_hashes,
        agreed,
        agreed_hashes,
        max_distance=COVER_SHORTLIST_MAX_DISTANCE,
        unique_gap=COVER_SHORTLIST_UNIQUE_GAP,
    )
    if chosen is None:
        return False
    return _persist_cover_hit(
        engine,
        row=row,
        chosen=chosen,
        hits=agreed,
        client=client,
        release_cache=release_cache,
        stats=stats,
    )


def _persist_known_sleeve(
    engine: Engine,
    *,
    row: dict[str, Any],
    match: dict[str, Any],
    hits: Sequence[SearchHit],
    stats: IdentityFillStats,
) -> bool:
    """Reuse a warehouse pressing only when catno or album text agrees."""
    if not artist_overlaps(
        listing_artist=listing_search_artist(row.get("artist"), row.get("title")),
        listing_title=row.get("title"),
        discogs_names=(
            str(match.get("display_artist") or ""),
            str(match.get("display_title") or ""),
        ),
    ):
        return False
    if not listing_media_compatible(row.get("media_type"), match.get("media_type")):
        return False
    if listing_wants_original_pressing(
        str(row.get("title") or "")
    ) and is_modern_reissue_catalog(str(match.get("catalog_number") or "")):
        return False
    with engine.begin() as connection:
        _assign_pressing(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            pressing_id=int(match["id"]),
            match_basis="CATALOG_EXACT",
            manual=False,
        )
        _set_auction_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            status="filled_auto",
            source="discogs",
            thumb_url=str(match.get("discogs_thumb_url") or "") or None,
            shortlist=shortlist_payload(tuple(hits)[:12]) if hits else [],
        )
    stats.filled_auto += 1
    stats.cover_matched += 1
    stats.reused += 1
    return True


def _operator_album_family(
    hits: Sequence[SearchHit],
    *,
    title: str | None,
    media_type: str | None,
    artist: str | None = None,
) -> tuple[SearchHit, ...]:
    """Keep every pressing of the named album so the operator can pick."""
    family = [
        hit
        for hit in hits
        if (
            album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        )
        and not hit_bundles_other_album(title, hit.title)
        and artist_overlaps(
            listing_artist=artist,
            listing_title=title,
            discogs_names=names_from_search_hit(hit),
        )
    ]
    if not family:
        return ()
    claimed = extract_release_year(title)

    def _key(hit: SearchHit) -> tuple[int, int, int, int]:
        media_rank = (
            0 if listing_media_compatible(media_type, " ".join(hit.formats)) else 1
        )
        year_rank = 0 if hit_fits_listing_year(title, hit.year) else 1
        try:
            actual = int(str(hit.year).strip()[:4]) if hit.year else None
        except (TypeError, ValueError):
            actual = None
        if claimed is not None and actual is not None:
            year_value = abs(actual - claimed)
        else:
            year_value = actual if actual is not None else 9999
        formats = " ".join(hit.formats).casefold()
        wants_single = bool(
            re.search(r"\b7\s*[\"″]|シングル|\bsingle\b", title or "", re.IGNORECASE)
        )
        if "single" in formats or '7"' in formats:
            shape_rank = 0 if wants_single else 2
        elif "compilation" in formats:
            shape_rank = 1
        else:
            shape_rank = 0
        if re.search(r"splatter", title or "", re.IGNORECASE):
            if "picture" in formats:
                shape_rank = 1
            elif "limited" in formats or "numbered" in formats:
                shape_rank = -1
        if re.search(r"made\s+in\s+germany", title or "", re.IGNORECASE):
            return (year_rank, media_rank, shape_rank, year_value, hit.discogs_id)
        return (media_rank, shape_rank, year_rank, year_value, hit.discogs_id)

    return shortlist_format_options(sorted(family, key=_key), limit=12)


def _merge_cover_hits(*groups: Sequence[SearchHit]) -> tuple[SearchHit, ...]:
    merged: list[SearchHit] = []
    seen: set[int] = set()
    for group in groups:
        for hit in group:
            if hit.discogs_id in seen:
                continue
            seen.add(hit.discogs_id)
            merged.append(hit)
    return tuple(merged)


def _persist_review_shortlist(
    engine: Engine,
    *,
    row: dict[str, Any],
    hits: Sequence[SearchHit],
) -> bool:
    """Keep Need-a-decision on sleeves that belong to the listing photo or title."""
    refined = refine_hits_for_listing(
        tuple(hits)[:8],
        title=row.get("title"),
        media_type=_listing_media_for_row(row),
    )
    persist = refined or tuple(hits)[:8]
    if not persist:
        return False
    with engine.begin() as connection:
        _set_auction_identity(
            connection,
            marketplace=str(row["marketplace"]),
            listing_id=str(row["listing_id"]),
            status="needs_review",
            source="discogs",
            thumb_url=persist[0].thumb_url,
            shortlist=shortlist_payload(persist),
        )
    return True


def _cover_match_one_row(
    engine: Engine,
    row: dict[str, Any],
    *,
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    search_cache: dict[str, tuple[SearchHit, ...]],
    stats: IdentityFillStats,
    http: httpx.Client,
    cache: dict[str, int | None],
    known_hashes: Sequence[tuple[dict[str, Any], int]],
) -> bool:
    """Fill one leftover from title-named Discogs hits, then matching sleeves."""
    if is_job_lot(str(row.get("title") or "")):
        return False
    listing_image = fetch_image(str(row.get("image_url") or ""), client=http)
    listing_hashes = listing_cover_hashes(listing_image) if listing_image else ()
    raw_hits = row.get("discogs_shortlist") or []
    if isinstance(raw_hits, str):
        raw_hits = json.loads(raw_hits)
    existing = refine_hits_for_listing(
        parse_search_hits(raw_hits),
        title=row.get("title"),
        media_type=_listing_media_for_row(row),
    )[:12]
    search_hits = _cover_hits_from_artist_search(
        row,
        client=client,
        search_cache=search_cache,
        stats=stats,
    )
    merged = _merge_cover_hits(existing, search_hits)
    if not merged:
        if listing_hashes:
            match = _choose_known_sleeve(row, listing_hashes, known_hashes)
            if isinstance(match, dict):
                return _persist_known_sleeve(
                    engine,
                    row=row,
                    match=match,
                    hits=existing,
                    stats=stats,
                )
        return False
    hit_hashes, _thumbs, _sides = (
        _hash_shortlist_covers(
            merged,
            listing_hashes=listing_hashes,
            client=client,
            release_cache=release_cache,
            image_client=http,
            cache=cache,
        )
        if listing_hashes
        else ([None] * len(merged), [None] * len(merged), ["neutral"] * len(merged))
    )
    if _fill_from_cover_hits(
        engine,
        row=row,
        hits=merged,
        listing_hashes=listing_hashes,
        hit_hashes=hit_hashes,
        client=client,
        release_cache=release_cache,
        stats=stats,
    ):
        return True
    agreed_pairs = [
        (hit, hashed)
        for hit, hashed in zip(merged, hit_hashes)
        if _hit_agrees_with_listing(row, hit)
    ]
    agreed = tuple(hit for hit, _hashed in agreed_pairs)
    agreed_hashes = [hashed for _hit, hashed in agreed_pairs]
    if listing_hashes:
        tight = choose_cover_hit_multi(
            listing_hashes,
            merged,
            hit_hashes,
            max_distance=COVER_MAX_DISTANCE,
            unique_gap=COVER_UNIQUE_GAP,
        )
        if tight is not None and _persist_cover_hit(
            engine,
            row=row,
            chosen=tight,
            hits=merged,
            client=client,
            release_cache=release_cache,
            stats=stats,
            require_title_agreement=False,
        ):
            return True
        ranked_agreed = rank_cover_hits(
            listing_hashes,
            agreed,
            agreed_hashes,
            max_distance=COVER_SHORTLIST_MAX_DISTANCE,
        )
        if ranked_agreed and _persist_review_shortlist(
            engine, row=row, hits=ranked_agreed
        ):
            return True
        match = _choose_known_sleeve(row, listing_hashes, known_hashes)
        if isinstance(match, dict):
            return _persist_known_sleeve(
                engine,
                row=row,
                match=match,
                hits=merged,
                stats=stats,
            )
        return False
    if agreed:
        return _persist_review_shortlist(engine, row=row, hits=agreed)
    return False


def _choose_known_sleeve(
    row: dict[str, Any],
    listing_hashes: Sequence[int],
    known_hashes: Sequence[tuple[dict[str, Any], int]],
) -> dict[str, Any] | None:
    """Match a leftover photo to an already-identified Discogs sleeve."""
    artist = listing_search_artist(row.get("artist"), row.get("title"))
    narrowed = [
        (pressing, hashed)
        for pressing, hashed in known_hashes
        if artist_overlaps(
            listing_artist=artist,
            listing_title=row.get("title"),
            discogs_names=(
                str(pressing.get("display_artist") or ""),
                str(pressing.get("display_title") or ""),
            ),
        )
    ]
    if not narrowed:
        return None
    chosen = choose_cover_match_multi(
        listing_hashes,
        narrowed,
        max_distance=COVER_SHORTLIST_MAX_DISTANCE,
        unique_gap=COVER_SHORTLIST_UNIQUE_GAP,
    )
    if not isinstance(chosen, dict):
        return None
    if not _pressing_agrees_with_listing(row, chosen):
        return None
    return chosen


_TITLE_JUNK_COMPACTS = frozenset(
    {
        "lp",
        "vinyl",
        "cd",
        "cassette",
        "original",
        "hongkong",
        "record",
        "records",
        "gripsweat",
        "analog",
        "import",
        "pressing",
        "sealed",
        "mint",
        "obi",
        "japan",
        "taiwan",
        "malaysia",
        "singapore",
        "promo",
        "stereo",
        "album",
        "selftitled",
        "cheesecake",
        "cheesecakecover",
        "colombian",
        "german",
        "korean",
        "cantopop",
        "mandopop",
        "jpop",
        "used",
        "new",
        "exclusive",
        "limited",
        "edition",
        "black",
        "gift",
        "box",
        "set",
        "with",
        "insert",
        "poster",
        "nm",
        "vg",
    }
)


def _catalog_appears_in_title(title: str | None, catno: str | None) -> bool:
    """True when the pressing catno digits/letters are written in the listing."""
    folded_title = re.sub(r"[^A-Z0-9]", "", (title or "").upper())
    folded_cat = fold_catalog(catno)
    return bool(folded_cat) and len(folded_cat) >= 5 and folded_cat in folded_title


def _album_name_in_listing(title: str | None, display_title: str | None) -> bool:
    """True when a Discogs album spelling is inside the listing title."""
    return album_name_in_listing(title, display_title)


def _artist_only_album_with_extra_tokens(
    row: dict[str, Any],
    pressing: dict[str, Any],
) -> bool:
    """Self-titled Discogs rows must not steal listings that name another album."""
    artist = listing_search_artist(row.get("artist"), row.get("title")) or str(
        pressing.get("display_artist") or ""
    )
    album = str(pressing.get("display_title") or "")
    if " - " in album:
        album = album.split(" - ", 1)[-1]
    album_compact = _script_compact(album)
    artist_compact = _script_compact(artist)
    family_compact = _script_compact(pressing.get("display_artist"))
    if not album_compact or album_compact not in {artist_compact, family_compact}:
        return False
    leftover = _script_compact(row.get("title"))
    for junk in (artist_compact, family_compact, album_compact, *_TITLE_JUNK_COMPACTS):
        if junk:
            leftover = leftover.replace(junk, "")
    leftover = re.sub(r"\d+", "", leftover)
    return len(leftover) >= 4


def _pressing_agrees_with_listing(
    row: dict[str, Any],
    pressing: dict[str, Any],
    *,
    matrix_on_discogs: bool = True,
) -> bool:
    """A reused sleeve must share the listing catno or the album name."""
    title = str(row.get("title") or "")
    title_token = catalog_token(catalog_number=None, title=title)
    press_cat = pressing.get("catalog_number")
    catalog_hit = _catalog_appears_in_title(title, press_cat) or (
        bool(title_token)
        and bool(fold_catalog(press_cat))
        and catno_covers_listing_token(press_cat, title_token)
    )
    if title_token and not catalog_hit:
        if matrix_on_discogs or not _album_name_in_listing(
            title,
            pressing.get("display_title"),
        ):
            return False
    if (
        listing_wants_original_pressing(title)
        and is_modern_reissue_catalog(press_cat)
    ):
        return False
    hints = listing_label_hints(title=title)
    if hints:
        blob = " ".join(
            [
                str(pressing.get("label_name") or ""),
                str(pressing.get("catalog_number") or ""),
                *[str(item) for item in pressing.get("labels") or ()],
            ]
        ).casefold()
        matched = any(
            hint in blob or (hint == "stereo sound" and "ssar" in blob)
            for hint in hints
        )
        has_label_info = bool(
            str(pressing.get("label_name") or "").strip() or pressing.get("labels")
        )
        if "stereo sound" in hints and not matched:
            return False
        if has_label_info and not matched:
            return False
    if catalog_hit:
        return True
    if bare_best_hit_title(title) and fold_catalog(press_cat) == fold_catalog("28TR-2092"):
        return True
    if not _album_name_in_listing(title, pressing.get("display_title")):
        return False
    return not _artist_only_album_with_extra_tokens(row, pressing)


def _promote_cover_matches(
    engine: Engine,
    *,
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
    search_cache: dict[str, tuple[SearchHit, ...]] | None = None,
) -> None:
    """Fill leftovers whose listing photo matches a Discogs sleeve."""
    with engine.connect() as connection:
        review_rows = [
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
                        image_url,
                        discogs_shortlist
                    FROM warehouse.auction
                    WHERE identity_status = 'needs_review'
                      AND COALESCE(bulk_lot, false) IS NOT TRUE
                      AND COALESCE(media_type, '') NOT IN (
                          'MAGAZINE', 'PHOTO', 'PHOTOBOOK', 'PRINT', 'STAMP',
                          'SHEET_MUSIC', 'TOY'
                      )
                      AND jsonb_typeof(discogs_shortlist) = 'array'
                      AND jsonb_array_length(discogs_shortlist) BETWEEN 0 AND 12
                    ORDER BY marketplace, listing_id
                    """
                )
            ).mappings()
        ]
        review_rows = _rows_for_tracked_artists(engine, review_rows)
        unmatched_rows = [
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
                        image_url,
                        discogs_shortlist
                    FROM warehouse.auction
                    WHERE identity_status = 'unmatched'
                      AND COALESCE(bulk_lot, false) IS NOT TRUE
                      AND COALESCE(media_type, '') NOT IN (
                          'MAGAZINE', 'PHOTO', 'PHOTOBOOK', 'PRINT', 'STAMP',
                          'SHEET_MUSIC', 'TOY'
                      )
                    ORDER BY marketplace, listing_id
                    """
                )
            ).mappings()
        ]
        unmatched_rows = _rows_for_tracked_artists(engine, unmatched_rows)
        known_covers = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT DISTINCT ON (pressing.id)
                        pressing.id,
                        pressing.media_type,
                        pressing.release_year,
                        pressing.catalog_number,
                        auction.discogs_thumb_url,
                        family.display_artist,
                        family.display_title
                    FROM warehouse.pressing_identity AS pressing
                    JOIN warehouse.release_family AS family
                      ON family.id = pressing.release_family_id
                    JOIN warehouse.auction_pressing_assignment AS assignment
                      ON assignment.pressing_id = pressing.id
                    JOIN warehouse.auction AS auction
                      ON auction.marketplace = assignment.marketplace
                     AND auction.listing_id = assignment.listing_id
                    WHERE pressing.discogs_release_id IS NOT NULL
                      AND NULLIF(BTRIM(auction.discogs_thumb_url), '') IS NOT NULL
                    ORDER BY pressing.id
                    """
                )
            ).mappings()
        ]

    http = httpx.Client(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "auction-etl/1.0"},
    )
    cache: dict[str, int | None] = {}
    try:
        logger.info(
            "cover match start review=%s unmatched=%s known=%s",
            len(review_rows),
            len(unmatched_rows),
            len(known_covers),
        )
        known_hashes: list[tuple[dict[str, Any], int]] = []
        for pressing in known_covers:
            hashed = hash_image_url(
                str(pressing.get("discogs_thumb_url") or ""),
                client=http,
                cache=cache,
            )
            if hashed is not None:
                known_hashes.append((pressing, hashed))

        searches = search_cache if search_cache is not None else {}
        total = len(review_rows) + len(unmatched_rows)
        for index, row in enumerate((*review_rows, *unmatched_rows), start=1):
            try:
                _cover_match_one_row(
                    engine,
                    row,
                    client=client,
                    release_cache=release_cache,
                    search_cache=searches,
                    stats=stats,
                    http=http,
                    cache=cache,
                    known_hashes=known_hashes,
                )
            except DiscogsRateLimitError as error:
                stats.stopped_reason = str(error)
                break
            except httpx.HTTPError:
                logger.warning(
                    "cover match skipped %s %s after HTTP error",
                    row.get("marketplace"),
                    row.get("listing_id"),
                )
            if index == 1 or index % 25 == 0 or index == total:
                logger.info(
                    "cover match progress %s/%s matched=%s",
                    index,
                    total,
                    stats.cover_matched,
                )

        logger.info("cover match done matched=%s", stats.cover_matched)
    finally:
        http.close()


def _apply_known_pressings(connection: Connection) -> int:
    """Assign already-mapped pressings onto leftover listings with the same catno."""
    rows = connection.execute(
        text(
            """
            SELECT marketplace, listing_id, artist, title, catalog_number, media_type
            FROM warehouse.auction
            WHERE identity_status IN ('unmatched', 'needs_review')
              AND COALESCE(bulk_lot, false) IS NOT TRUE
            """
        )
    ).mappings().all()
    applied = 0
    for row in rows:
        title = str(row.get("title") or "")
        if is_job_lot(title):
            continue
        token = listing_identity_catalog(
            stored=row.get("catalog_number"),
            title=title,
            artist=row.get("artist"),
            media_type=row.get("media_type"),
        )
        if _reuse_local_pressing(connection, row=dict(row), token=token):
            applied += 1
    return applied


def _upsert_gripsweat_auctions(connection: Connection) -> int:
    """Persist Gripsweat-only sales so Discogs/catalog fill the whole review set."""
    ebay_ids = {
        str(listing_id)
        for listing_id in connection.execute(
            text(
                """
                SELECT listing_id
                FROM warehouse.auction
                WHERE marketplace = 'ebay'
                """
            )
        ).scalars()
    }
    inserted = 0
    for sale in connection.execute(
        text(
            """
            SELECT
                original_listing_id,
                gripsweat_item_id,
                gripsweat_url,
                source_name,
                configured_artist,
                title,
                raw_text,
                sold_price,
                currency,
                sold_at,
                image_url,
                first_seen_at
            FROM warehouse.gripsweat_sale
            """
        )
    ).mappings():
        listing_id = (
            str(sale.get("original_listing_id") or "").strip()
            or gripsweat_original_listing_id(sale.get("gripsweat_url"))
            or str(sale.get("gripsweat_item_id") or "").strip()
        )
        if not listing_id or listing_id in ebay_ids:
            continue
        title = parse_gripsweat_title(sale.get("title"), sale.get("raw_text"))
        if not title:
            continue
        details = classify_media_details(title)
        token = catalog_token(title=title)
        result = connection.execute(
            text(
                """
                INSERT INTO warehouse.auction (
                    marketplace, listing_id, auction_url, seller, artist, title,
                    media_type, catalog_number, bulk_lot, image_url,
                    final_price, gross_price, currency, ended_at, closing_at,
                    opening_at, auction_format, identity_status, identity_source
                )
                VALUES (
                    'gripsweat', :listing_id, :auction_url, :seller, :artist, :title,
                    :media_type, :catalog_number, CAST(:bulk_lot AS boolean), :image_url,
                    :final_price, :gross_price, :currency, :ended_at, :closing_at,
                    :opening_at, 'AUCTION', 'unmatched', 'listing'
                )
                ON CONFLICT ON CONSTRAINT uq_auction_marketplace_listing
                DO NOTHING
                """
            ),
            {
                "listing_id": listing_id,
                "auction_url": sale.get("gripsweat_url"),
                "seller": sale.get("source_name"),
                "artist": sale.get("configured_artist"),
                "title": title,
                "media_type": details.format,
                "catalog_number": token,
                "bulk_lot": bool(details.bulk_lot or is_job_lot(title)),
                "image_url": sale.get("image_url"),
                "final_price": sale.get("sold_price"),
                "gross_price": sale.get("sold_price"),
                "currency": str(sale.get("currency") or "").strip().upper() or None,
                "ended_at": sale.get("sold_at"),
                "closing_at": sale.get("sold_at"),
                "opening_at": sale.get("first_seen_at"),
            },
        )
        inserted += int(result.rowcount or 0)
    return inserted


def _backfill_missing_discogs_thumbs(engine: Engine) -> int:
    """Copy a sibling Discogs sleeve onto filled rows that lost their thumb."""
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE warehouse.auction AS auction
                SET discogs_thumb_url = sibling.thumb
                FROM warehouse.auction_pressing_assignment AS assignment
                JOIN LATERAL (
                    SELECT NULLIF(BTRIM(other.discogs_thumb_url), '') AS thumb
                    FROM warehouse.auction_pressing_assignment AS other_asg
                    JOIN warehouse.auction AS other
                      ON other.marketplace = other_asg.marketplace
                     AND other.listing_id = other_asg.listing_id
                    WHERE other_asg.pressing_id = assignment.pressing_id
                      AND NULLIF(BTRIM(other.discogs_thumb_url), '') IS NOT NULL
                    LIMIT 1
                ) AS sibling ON sibling.thumb IS NOT NULL
                WHERE assignment.marketplace = auction.marketplace
                  AND assignment.listing_id = auction.listing_id
                  AND auction.identity_status IN ('filled_auto', 'filled_manual')
                  AND (
                      auction.discogs_thumb_url IS NULL
                      OR BTRIM(auction.discogs_thumb_url) = ''
                  )
                """
            )
        )
        return int(result.rowcount or 0)


def _backfill_missing_matrices(
    engine: Engine,
    *,
    client: DiscogsClient,
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
) -> None:
    """Pull Discogs matrix identifiers onto pressings that were filled without them."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, discogs_release_id
                FROM warehouse.pressing_identity
                WHERE discogs_release_id IS NOT NULL
                  AND (matrix_number IS NULL OR BTRIM(matrix_number) = '')
                """
            )
        ).mappings().all()
    for row in rows:
        try:
            draft = _release_draft(client, int(row["discogs_release_id"]), release_cache)
        except DiscogsRateLimitError as error:
            stats.stopped_reason = str(error)
            break
        except Exception:
            continue
        matrix = (draft.matrix_number or "").strip()
        if not matrix:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE warehouse.pressing_identity
                    SET matrix_number = :matrix_number,
                        updated_at = now()
                    WHERE id = :id
                      AND (matrix_number IS NULL OR BTRIM(matrix_number) = '')
                    """
                ),
                {"matrix_number": matrix, "id": int(row["id"])},
            )


def _reuse_local_pressing(
    connection: Connection,
    *,
    row: dict[str, Any],
    token: str | None,
    image_client: httpx.Client | None = None,
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
                pressing.country,
                pressing.media_type,
                pressing.release_year,
                pressing.catalog_number,
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
    overlapped = [
        dict(match)
        for match in matches
        if artist_overlaps(
            listing_artist=row.get("artist"),
            listing_title=row.get("title"),
            discogs_names=(
                str(match.get("display_artist") or ""),
                str(match.get("display_title") or ""),
            ),
        )
        and listing_media_compatible(
            row.get("media_type"),
            match.get("media_type"),
        )
        and _pressing_agrees_with_listing(
            {
                "title": row.get("title"),
                "artist": row.get("artist"),
                "catalog_number": None,
            },
            {
                "display_title": match.get("display_title"),
                "display_artist": match.get("display_artist"),
                "catalog_number": match.get("catalog_number"),
            },
        )
        and (
            _catalog_locks_identity(
                row,
                SimpleNamespace(catno=match.get("catalog_number")),
            )
            or hit_fits_listing_year(row.get("title"), match.get("release_year"))
        )
        and not (
            listing_wants_original_pressing(str(row.get("title") or ""))
            and is_modern_reissue_catalog(str(match.get("catalog_number") or ""))
        )
    ]
    if not overlapped:
        return None
    preferred = listing_preferred_country(
        listing_title=row.get("title"),
        listing_artist=row.get("artist"),
    )
    if preferred:
        country_matches = [
            match
            for match in overlapped
            if preferred in (match.get("country") or "").casefold()
        ]
        ranked = country_matches or overlapped
    else:
        ranked = overlapped
    match = ranked[0]
    pressing_id = int(match["id"])
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
    if not (
        _catalog_locks_identity(
            row,
            SimpleNamespace(catno=match.get("catalog_number")),
        )
        or _photo_confirms_listing(
            row,
            str(thumb) if thumb else None,
            image_client,
        )
    ):
        return None
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
        thumb_url=str(thumb) if thumb else None,
        shortlist=None,
    )
    return pressing_id


def _load_leftover_identities(
    connection: Connection,
    *,
    marketplace: str | None,
) -> list[dict[str, Any]]:
    """Need-a-decision and unmatched music rows for leftover Discogs research."""
    sql = """
        SELECT
            a.marketplace,
            a.listing_id,
            a.artist,
            a.title,
            COALESCE(
                NULLIF(BTRIM(c.manual_catalog_number), ''),
                NULLIF(BTRIM(a.catalog_number), '')
            ) AS catalog_number,
            a.media_type,
            a.bulk_lot,
            a.image_url,
            a.identity_status,
            a.discogs_thumb_url,
            a.discogs_shortlist,
            d.description
        FROM warehouse.auction AS a
        LEFT JOIN warehouse.auction_collector AS c
          ON c.marketplace = a.marketplace
         AND c.listing_id = a.listing_id
         AND c.account_id IS NULL
        LEFT JOIN warehouse.auction_detail AS d
          ON d.marketplace = a.marketplace
         AND d.listing_id = a.listing_id
        WHERE a.identity_status IN ('unmatched', 'needs_review')
          AND COALESCE(a.bulk_lot, false) IS NOT TRUE
          AND (
            a.media_type IS NULL
            OR lower(BTRIM(a.media_type)) NOT IN (
                'magazine', 'photo', 'print', 'photobook', 'stamp', 'usb',
                'sheet_music', 'toy'
            )
          )
    """
    params: dict[str, Any] = {}
    if marketplace:
        sql += " AND a.marketplace = :marketplace"
        params["marketplace"] = marketplace
    sql += " ORDER BY a.marketplace, a.listing_id"
    rows = _rows_for_tracked_artists(
        connection,
        [dict(row) for row in connection.execute(text(sql), params).mappings()],
    )
    rows.sort(
        key=lambda row: (
            0 if leftover_unmatched_empty_shortlist(row) else 1,
            0 if leftover_printed_catalog_missing_discogs(row) else 1,
            0 if str(row.get("image_url") or "").strip()
            and "spacer.gif" not in str(row.get("image_url") or "")
            else 1,
            0
            if catalog_token(
                catalog_number=row.get("catalog_number"),
                title=row.get("title"),
            )
            else 1,
            str(row.get("marketplace") or ""),
            str(row.get("listing_id") or ""),
        )
    )
    return rows


def leftover_restore_shortlist(
    *,
    outcome: str,
    previous_status: str,
    previous_shortlist: Any,
    title: str | None,
    catalog_number: str | None,
    media_type: str | None = None,
) -> list[dict[str, Any]] | None:
    """Keep a previous Need-a-decision list only when it still covers the copy."""
    if outcome != "unmatched" or previous_status != "needs_review":
        return None
    raw = previous_shortlist or []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        return None
    hits = parse_search_hits(raw)
    if not hits:
        return None
    token = listing_identity_catalog(
        stored=catalog_number,
        title=title,
        media_type=media_type,
    )
    if token:
        covered = covering_hits_for_listing(
            hits,
            catalog_number=token,
            title=title,
            media_type=media_type,
        )
        if not covered:
            return None
        if not any(
            catno_locks_listing(hit.catno, token)
            or catno_covers_listing_token(hit.catno, token)
            for hit in covered
        ):
            return None
        hits = covered
    refined = refine_hits_for_listing(
        hits,
        title=title,
        media_type=media_type,
    )
    if not refined:
        return None
    if media_type and not any(
        listing_media_compatible(media_type, " ".join(hit.formats))
        for hit in refined
    ):
        return None
    return shortlist_payload(refined)


def leftover_printed_catalog_missing_discogs(row: dict[str, Any]) -> bool:
    """True when the sleeve/title catalog is real but Discogs has no exact hit."""
    status = str(row.get("identity_status") or "")
    if status not in {"unmatched", "needs_review"}:
        return False
    media = (_listing_media_for_row(row) or "").upper()
    if media in {
        "MAGAZINE",
        "PRINT",
        "PHOTOBOOK",
        "STAMP",
        "USB",
        "SHEET_MUSIC",
        "TOY",
    }:
        return False
    token = listing_identity_catalog(
        stored=row.get("catalog_number"),
        title=str(row.get("title") or ""),
        artist=row.get("artist"),
        media_type=row.get("media_type"),
    )
    if not token:
        return False
    raw = row.get("discogs_shortlist") or []
    if isinstance(raw, str):
        raw = json.loads(raw)
    hits = parse_search_hits(raw) if isinstance(raw, list) else ()
    if any(
        catno_locks_listing(hit.catno, token)
        or catno_covers_listing_token(hit.catno, token)
        for hit in hits
    ):
        return False
    prefix = catalog_letter_prefix(token)
    if prefix and any(catalog_letter_prefix(hit.catno) == prefix for hit in hits):
        return False
    return True


def leftover_unmatched_empty_shortlist(row: dict[str, Any]) -> bool:
    """Unmatched music with a searchable title and no Discogs candidates yet."""
    if str(row.get("identity_status") or "") != "unmatched":
        return False
    media = (_listing_media_for_row(row) or "").upper()
    if media in {
        "MAGAZINE",
        "PRINT",
        "PHOTOBOOK",
        "STAMP",
        "USB",
        "SHEET_MUSIC",
        "TOY",
    }:
        return False
    leftover = _listing_leftover_album_compact(str(row.get("title") or ""))
    if len(leftover) < 2:
        return False
    raw = row.get("discogs_shortlist") or []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, list) and raw:
        return False
    return True


def leftover_row_needs_research(row: dict[str, Any]) -> bool:
    """Re-search leftover Need-a-decision and unmatched rows across every media."""
    status = str(row.get("identity_status") or "")
    if status not in {"unmatched", "needs_review"}:
        return False
    title = str(row.get("title") or "")
    media = (_listing_media_for_row(row) or "").upper()
    if media in {
        "MAGAZINE",
        "PRINT",
        "PHOTOBOOK",
        "STAMP",
        "USB",
        "SHEET_MUSIC",
        "TOY",
    }:
        return False
    if leftover_printed_catalog_missing_discogs(row):
        return True
    if leftover_unmatched_empty_shortlist(row):
        return True
    if (
        media.startswith("CD")
        or "CASS" in media
        or media in {
            "MIXED_MEDIA",
            "SHM_CD",
            "SACD",
            "BLU_SPEC_CD",
            "DVD",
            "CD_BOX_SET",
            "EP_7_INCH",
            "SINGLE_12_INCH",
        }
        or listing_title_wants_seven_inch(title)
    ):
        return True
    if re.search(
        r"cassette|カセット|磁带|(?<![A-Za-z])cd(?![A-Za-z])|sacd|shm-?cd",
        title,
        re.IGNORECASE,
    ):
        return True
    token = listing_identity_catalog(
        stored=row.get("catalog_number"),
        title=title,
        artist=row.get("artist"),
        media_type=row.get("media_type"),
    )
    raw = row.get("discogs_shortlist") or []
    if isinstance(raw, str):
        raw = json.loads(raw)
    hits = parse_search_hits(raw) if isinstance(raw, list) else ()
    listing_media = _listing_media_for_row(row)
    if hits and not any(
        listing_media_compatible(listing_media, " ".join(hit.formats))
        for hit in hits
    ):
        return True
    if token and hits and not any(
        catno_locks_listing(hit.catno, token)
        or catno_covers_listing_token(hit.catno, token)
        for hit in hits
    ):
        prefix = catalog_letter_prefix(token)
        same_prefix = bool(
            prefix
            and any(catalog_letter_prefix(hit.catno) == prefix for hit in hits)
        )
        if not same_prefix:
            return True
    if token and is_modern_reissue_catalog(token):
        return True
    if title_claims_reissue(title):
        return True
    if status == "needs_review" and isinstance(raw, list) and len(raw) == 1:
        return True
    if (
        status == "needs_review"
        and isinstance(raw, list)
        and len(raw) >= 8
        and not listing_title_wants_seven_inch(title)
        and not media.startswith("CD")
        and "CASS" not in media
        and not token
    ):
        return False
    return True


def _research_leftover_identities(
    engine: Engine,
    *,
    client: DiscogsClient,
    search_cache: dict[str, tuple[SearchHit, ...]],
    release_cache: dict[int, PressingIdentityDraft],
    stats: IdentityFillStats,
    image_client: httpx.Client | None,
    marketplace: str | None,
    missing_printed_catalog: bool = False,
    photo_only: bool = False,
    unmatched_empty: bool = False,
    limit: int | None = None,
    deadline: float | None = None,
) -> None:
    """Comb leftover Need-a-decision and unmatched rows from Discogs."""
    with engine.connect() as connection:
        rows = _load_leftover_identities(connection, marketplace=marketplace)
        identified_pressings = _identified_pressing_rows(connection)
    # A refresh deadline has to start before this scan. Scoring every leftover
    # against every known pressing ignores the budget and holds Finalizing.
    if deadline is None:
        local_keys = {
            (str(row.get("marketplace") or ""), str(row.get("listing_id") or ""))
            for row in rows
            if _local_hits_cover_listing(
                row,
                _local_album_search_hits(row, identified_pressings),
            )
        }
        rows.sort(
            key=lambda row: (
                0
                if (
                    str(row.get("marketplace") or ""),
                    str(row.get("listing_id") or ""),
                )
                in local_keys
                else 1
            )
        )
    for row in rows:
        if stats.stopped_reason:
            break
        if deadline is not None and time.monotonic() >= deadline:
            stats.stopped_reason = (
                stats.stopped_reason or "ingest leftover budget"
            )
            logger.warning("Discogs leftover comb stopped: leftover budget")
            break
        if limit is not None and stats.leftover_researched >= limit:
            break
        if is_job_lot(str(row.get("title") or "")):
            continue
        image_url = str(row.get("image_url") or "")
        if photo_only and (
            not image_url.strip()
            or "spacer.gif" in image_url
            or "noimage" in image_url.lower()
        ):
            continue
        if missing_printed_catalog:
            if not leftover_printed_catalog_missing_discogs(row):
                continue
        elif unmatched_empty:
            if not leftover_unmatched_empty_shortlist(row):
                continue
        elif not leftover_row_needs_research(row):
            continue
        stats.leftover_researched += 1
        try:
            with engine.begin() as connection:
                outcome = _fill_one_row(
                    connection,
                    row=row,
                    client=client,
                    search_cache=search_cache,
                    release_cache=release_cache,
                    stats=stats,
                    image_client=image_client,
                    identified_pressings=identified_pressings,
                    fast_search=True,
                )
        except DiscogsRateLimitError as error:
            stats.stopped_reason = str(error)
            logger.warning("Discogs leftover comb stopped: rate limit")
            break
        except httpx.HTTPError:
            logger.warning(
                "leftover comb skipped %s %s after Discogs HTTP error",
                row.get("marketplace"),
                row.get("listing_id"),
            )
            stats.unmatched += 1
            continue
        except Exception:
            logger.warning(
                "leftover comb skipped %s %s",
                row.get("marketplace"),
                row.get("listing_id"),
            )
            stats.unmatched += 1
            continue
        restore = leftover_restore_shortlist(
            outcome=outcome,
            previous_status=str(row.get("identity_status") or ""),
            previous_shortlist=row.get("discogs_shortlist"),
            title=row.get("title"),
            catalog_number=row.get("catalog_number"),
            media_type=_listing_media_for_row(row),
        )
        if restore is not None:
            with engine.begin() as connection:
                _set_auction_identity(
                    connection,
                    marketplace=str(row["marketplace"]),
                    listing_id=str(row["listing_id"]),
                    status="needs_review",
                    source="discogs",
                    thumb_url=row.get("discogs_thumb_url"),
                    shortlist=restore,
                )
            outcome = "needs_review"
        if outcome == "filled_auto":
            stats.filled_auto += 1
        elif outcome == "needs_review":
            stats.needs_review += 1
        else:
            stats.unmatched += 1
        done = stats.leftover_researched
        if done == 1 or done % 25 == 0:
            logger.info(
                "leftover comb %s researched filled=%s review=%s unmatched=%s searches=%s",
                done,
                stats.filled_auto,
                stats.needs_review,
                stats.unmatched,
                stats.searched,
            )


def _load_candidates(
    connection: Connection,
    *,
    marketplace: str | None,
    limit: int | None,
    created_after: datetime | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            a.marketplace,
            a.listing_id,
            a.artist,
            a.title,
            COALESCE(
                NULLIF(BTRIM(c.manual_catalog_number), ''),
                NULLIF(BTRIM(a.catalog_number), '')
            ) AS catalog_number,
            a.media_type,
            a.bulk_lot,
            a.image_url
        FROM warehouse.auction AS a
        LEFT JOIN warehouse.auction_collector AS c
          ON c.marketplace = a.marketplace
         AND c.listing_id = a.listing_id
         AND c.account_id IS NULL
        WHERE a.identity_status = 'unmatched'
          AND a.discogs_shortlist_fetched_at IS NULL
          AND COALESCE(a.bulk_lot, false) IS NOT TRUE
          AND (
            a.media_type IS NULL
            OR lower(BTRIM(a.media_type)) NOT IN (
                'magazine', 'photo', 'print', 'photobook', 'stamp', 'usb',
                'sheet_music', 'toy'
            )
          )
    """
    params: dict[str, Any] = {}
    if marketplace:
        sql += " AND a.marketplace = :marketplace"
        params["marketplace"] = marketplace
    if created_after is not None:
        sql += " AND a.created_at >= :created_after"
        params["created_after"] = created_after
    sql += """
        ORDER BY
            CASE
                WHEN COALESCE(
                    NULLIF(BTRIM(c.manual_catalog_number), ''),
                    NULLIF(BTRIM(a.catalog_number), '')
                ) IS NOT NULL
                THEN 0
                ELSE 1
            END,
            a.marketplace,
            a.listing_id
    """
    rows = _rows_for_tracked_artists(
        connection,
        [dict(row) for row in connection.execute(text(sql), params).mappings()],
    )
    if limit is not None:
        rows = rows[: int(limit)]
    return rows


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
    result = connection.execute(
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
            WHERE COALESCE(
                    warehouse.auction_pressing_assignment.is_manual_override,
                    false
                ) IS NOT TRUE
               OR EXCLUDED.is_manual_override IS TRUE
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
    if int(result.rowcount or 0) == 0:
        return
    _copy_pressing_catalog_to_listing(
        connection,
        marketplace=marketplace,
        listing_id=listing_id,
        pressing_id=pressing_id,
    )


def _copy_pressing_catalog_to_listing(
    connection: Connection,
    *,
    marketplace: str,
    listing_id: str,
    pressing_id: int,
) -> None:
    facts = connection.execute(
        text(
            """
            SELECT
                auction.title,
                auction.media_type AS listing_media,
                pressing.catalog_number,
                pressing.media_type AS pressing_media,
                pressing.release_year
            FROM warehouse.pressing_identity AS pressing
            JOIN warehouse.auction AS auction
              ON auction.marketplace = :marketplace
             AND auction.listing_id = :listing_id
            WHERE pressing.id = :pressing_id
            """
        ),
        {
            "pressing_id": pressing_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    ).mappings().first()
    if facts is None:
        return
    catalog = str(facts.get("catalog_number") or "").strip()
    title = str(facts.get("title") or "")
    if not catalog:
        return
    if listing_wants_original_pressing(title) and is_modern_reissue_catalog(catalog):
        return
    if not listing_media_compatible(
        facts.get("listing_media"),
        facts.get("pressing_media"),
    ):
        return
    if not hit_fits_listing_year(title, facts.get("release_year")):
        return
    connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET catalog_number = COALESCE(NULLIF(BTRIM(catalog_number), ''), :catalog)
            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """
        ),
        {
            "catalog": catalog,
            "marketplace": marketplace,
            "listing_id": listing_id,
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
                discogs_thumb_url = CASE
                    WHEN :status IN ('unmatched', 'needs_review')
                    THEN :thumb_url
                    ELSE COALESCE(:thumb_url, discogs_thumb_url)
                END,
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
