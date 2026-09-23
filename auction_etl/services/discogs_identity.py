"""Pure Discogs identity matching: tokens, classification, release mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Sequence


IdentityStatus = Literal[
    "unmatched",
    "needs_review",
    "filled_auto",
    "filled_manual",
]

_CATALOG_IN_TEXT = re.compile(
    r"\b([A-Z]{1,5}[-\s]?\d{2,6}(?:[-/][A-Z0-9]{1,6})?)\b",
    re.IGNORECASE,
)
_DISCOGS_NUM_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_JP_CHAR = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class SearchHit:
    discogs_id: int
    title: str
    catno: str
    year: str | None
    country: str | None
    formats: tuple[str, ...]
    labels: tuple[str, ...]
    thumb_url: str | None
    uri: str | None


@dataclass(frozen=True)
class LabelChoice:
    discogs_label_id: int | None
    display_name: str
    catno: str


@dataclass(frozen=True)
class PressingIdentityDraft:
    discogs_release_id: int
    discogs_master_id: int | None
    discogs_uri: str | None
    discogs_thumb_url: str | None
    display_artist: str
    display_title: str
    artist_names: tuple[str, ...]
    label_name: str
    discogs_label_id: int | None
    labels: tuple[LabelChoice, ...]
    requires_label_choice: bool
    catalog_number: str
    matrix_number: str
    country: str
    region: str
    media_type: str
    format_detail: str
    disc_count: int | None
    release_year: int | None
    generation: str
    is_first_press: bool
    notes_hint: str | None
    component_expectations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Classification:
    status: IdentityStatus
    reason: str
    hits: tuple[SearchHit, ...]
    chosen: SearchHit | None


def fold_catalog(value: str | None) -> str:
    """Fold hyphens, spaces, and case so SOLL114 ≡ SOLL-114."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", value.upper())


def catalog_token(
    *,
    catalog_number: str | None = None,
    title: str | None = None,
) -> str | None:
    """Return a listing catalog token from the field or the title."""
    field = (catalog_number or "").strip()
    if field:
        folded = fold_catalog(field)
        if folded and not folded.isdigit():
            return field.upper()

    text = (title or "").strip()
    if not text:
        return None

    match = _CATALOG_IN_TEXT.search(text)
    if not match:
        return None

    candidate = match.group(1).strip().upper()
    folded = fold_catalog(candidate)
    if not folded or folded.isdigit():
        return None
    return candidate


def prefers_japan(
    *,
    listing_title: str | None,
    listing_artist: str | None,
) -> bool:
    """True when the listing is JP-titled or Japan-pressed."""
    blob = f"{listing_artist or ''} {listing_title or ''}"
    if _JP_CHAR.search(blob):
        return True
    return "japan" in blob.casefold()


def artist_overlaps(
    *,
    listing_artist: str | None,
    listing_title: str | None,
    discogs_names: Sequence[str],
) -> bool:
    """True when a Discogs artist or ANV token appears on the listing."""
    blob = f"{listing_artist or ''} {listing_title or ''}"
    blob_cf = blob.casefold()
    if not blob_cf.strip():
        return False

    for raw_name in discogs_names:
        cleaned = _clean_artist_name(raw_name)
        if not cleaned:
            continue
        if cleaned in blob or cleaned.casefold() in blob_cf:
            return True
        for token in _TOKEN_SPLIT.split(cleaned):
            if len(token) >= 4 and token.casefold() in blob_cf:
                return True
    return False


def parse_search_hits(raw_hits: Iterable[dict[str, Any]]) -> tuple[SearchHit, ...]:
    """Normalize Discogs search `results` rows."""
    parsed: list[SearchHit] = []
    for row in raw_hits:
        try:
            discogs_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if row.get("type") not in {None, "release"}:
            continue
        formats = row.get("format") or []
        labels = row.get("label") or []
        parsed.append(
            SearchHit(
                discogs_id=discogs_id,
                title=str(row.get("title") or ""),
                catno=str(row.get("catno") or ""),
                year=_optional_text(row.get("year")),
                country=_optional_text(row.get("country")),
                formats=tuple(str(item) for item in formats),
                labels=tuple(str(item) for item in labels),
                thumb_url=_optional_text(row.get("thumb") or row.get("cover_image")),
                uri=_optional_text(row.get("uri")),
            )
        )
    return tuple(parsed)


def names_from_search_hit(hit: SearchHit) -> tuple[str, ...]:
    """Best-effort artist names from a search title (`Artist - Title`)."""
    title = hit.title
    if " - " not in title:
        return (title,) if title else ()
    left = title.split(" - ", 1)[0]
    parts = [left]
    parts.extend(re.split(r"\s*/\s*|\s*&\s*", left))
    return tuple(_clean_artist_name(part) for part in parts if _clean_artist_name(part))


def filter_hits(
    hits: Sequence[SearchHit],
    *,
    token: str | None,
    media_type: str | None,
    prefer_japan: bool,
) -> tuple[SearchHit, ...]:
    """Keep vinyl/LP (or listing media) hits whose catno folds to the token."""
    wanted = fold_catalog(token)
    remaining = [
        hit
        for hit in hits
        if _keeps_media(hit.formats, media_type)
        and (not wanted or fold_catalog(hit.catno) == wanted)
    ]
    if prefer_japan:
        japan_only = [
            hit
            for hit in remaining
            if (hit.country or "").casefold() == "japan"
        ]
        if japan_only:
            remaining = japan_only
    return tuple(remaining)


def classify_search_hits(
    *,
    catalog_number: str | None,
    title: str | None,
    artist: str | None,
    media_type: str | None,
    hits: Sequence[SearchHit],
    discogs_artist_names: Sequence[str] | None = None,
) -> Classification:
    """Decide unmatched / needs_review / filled_auto from search hits."""
    token = catalog_token(catalog_number=catalog_number, title=title)
    if not token:
        return Classification(
            status="unmatched",
            reason="missing_catalog_token",
            hits=tuple(hits),
            chosen=None,
        )

    remaining = filter_hits(
        hits,
        token=token,
        media_type=media_type,
        prefer_japan=prefers_japan(
            listing_title=title,
            listing_artist=artist,
        ),
    )
    if not remaining:
        return Classification(
            status="unmatched",
            reason="empty_shortlist",
            hits=(),
            chosen=None,
        )
    if len(remaining) != 1:
        return Classification(
            status="needs_review",
            reason="ambiguous_hits",
            hits=remaining,
            chosen=None,
        )

    chosen = remaining[0]
    if fold_catalog(chosen.catno) != fold_catalog(token):
        return Classification(
            status="needs_review",
            reason="catno_mismatch",
            hits=remaining,
            chosen=None,
        )

    names = list(discogs_artist_names or ())
    names.extend(names_from_search_hit(chosen))
    if not artist_overlaps(
        listing_artist=artist,
        listing_title=title,
        discogs_names=names,
    ):
        return Classification(
            status="needs_review",
            reason="artist_mismatch",
            hits=remaining,
            chosen=None,
        )

    return Classification(
        status="filled_auto",
        reason="unique_catno_artist_vinyl",
        hits=remaining,
        chosen=chosen,
    )


def unique_hit_can_auto_fill(
    classification: Classification,
    *,
    listing_artist: str | None,
    listing_title: str | None,
    release_artist_names: Sequence[str],
) -> bool:
    """Promote a unique catno hit after Latin/ANV names are known from /releases/{id}."""
    if classification.status == "filled_auto":
        return True
    if classification.status != "needs_review":
        return False
    if classification.reason != "artist_mismatch":
        return False
    if len(classification.hits) != 1:
        return False
    return artist_overlaps(
        listing_artist=listing_artist,
        listing_title=listing_title,
        discogs_names=release_artist_names,
    )


def map_release_payload(payload: dict[str, Any]) -> PressingIdentityDraft:
    """Map GET /releases/{id} JSON onto local pressing identity fields."""
    labels = _label_entities(payload.get("labels") or [])
    primary = labels[0] if labels else LabelChoice(None, "", "")
    formats = payload.get("formats") or []
    media_type, format_detail, disc_count, generation = _map_formats(formats)
    country = str(payload.get("country") or "").strip()
    region = "Japan" if country.casefold() == "japan" else country
    artists = payload.get("artists") or []
    artist_names = tuple(
        name
        for artist in artists
        for name in (
            _clean_artist_name(artist.get("anv")),
            _clean_artist_name(artist.get("name")),
        )
        if name
    )
    display_artist = " / ".join(
        _clean_artist_name(artist.get("anv"))
        or _clean_artist_name(artist.get("name"))
        for artist in artists
        if _clean_artist_name(artist.get("anv"))
        or _clean_artist_name(artist.get("name"))
    )
    matrices = [
        str(item.get("value")).strip()
        for item in payload.get("identifiers") or []
        if str(item.get("type") or "").casefold().startswith("matrix")
        and str(item.get("value") or "").strip()
    ]
    year_raw = payload.get("year") or payload.get("released")
    release_year = _parse_year(year_raw)
    notes = _optional_text(payload.get("notes"))
    thumb = _optional_text(payload.get("thumb"))
    if not thumb:
        images = payload.get("images") or []
        if images:
            thumb = _optional_text(
                images[0].get("uri150") or images[0].get("uri")
            )

    return PressingIdentityDraft(
        discogs_release_id=int(payload["id"]),
        discogs_master_id=_optional_int(payload.get("master_id")),
        discogs_uri=_optional_text(payload.get("uri")),
        discogs_thumb_url=thumb,
        display_artist=display_artist,
        display_title=str(payload.get("title") or "").strip(),
        artist_names=artist_names,
        label_name=primary.display_name,
        discogs_label_id=primary.discogs_label_id,
        labels=labels,
        requires_label_choice=len(labels) > 1,
        catalog_number=primary.catno or str(
            (payload.get("labels") or [{}])[0].get("catno") or ""
        ).strip(),
        matrix_number=" / ".join(dict.fromkeys(matrices)),
        country=country,
        region=region,
        media_type=media_type,
        format_detail=format_detail,
        disc_count=disc_count,
        release_year=release_year,
        generation=generation,
        is_first_press=False,
        notes_hint=notes,
        component_expectations=(),
    )


def shortlist_payload(hits: Sequence[SearchHit]) -> list[dict[str, Any]]:
    """JSON-safe shortlist for warehouse.auction.discogs_shortlist."""
    return [
        {
            "id": hit.discogs_id,
            "title": hit.title,
            "catno": hit.catno,
            "year": hit.year,
            "country": hit.country,
            "format": list(hit.formats),
            "label": list(hit.labels),
            "thumb": hit.thumb_url,
            "uri": hit.uri,
        }
        for hit in hits
    ]


def _clean_artist_name(value: Any) -> str:
    if value is None:
        return ""
    cleaned = _DISCOGS_NUM_SUFFIX.sub("", str(value)).replace("*", "")
    return cleaned.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in {None, "", 0, "0"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_year(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    match = re.search(r"(19[4-9]\d|20[0-2]\d)", str(value))
    if not match:
        return None
    year = int(match.group(1))
    if 1800 <= year <= 2200:
        return year
    return None


def _keeps_media(formats: Sequence[str], listing_media: str | None) -> bool:
    fmt = {item.casefold() for item in formats}
    media = (listing_media or "").casefold()
    if "cd" in media and "vinyl" not in media and "lp" not in media:
        return "cd" in fmt
    if "cassette" in media or "tape" in media:
        return "cassette" in fmt or "tape" in fmt
    if not fmt:
        return True
    return bool(fmt & {"vinyl", "lp"})


def _label_entities(raw_labels: Sequence[dict[str, Any]]) -> tuple[LabelChoice, ...]:
    choices: list[LabelChoice] = []
    seen: set[tuple[int | None, str]] = set()
    for row in raw_labels:
        entity = str(row.get("entity_type_name") or "Label").strip()
        if entity and entity.casefold() != "label":
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        label_id = _optional_int(row.get("id"))
        key = (label_id, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        choices.append(
            LabelChoice(
                discogs_label_id=label_id,
                display_name=name,
                catno=str(row.get("catno") or "").strip(),
            )
        )
    return tuple(choices)


def _map_formats(
    formats: Sequence[dict[str, Any]],
) -> tuple[str, str, int | None, str]:
    if not formats:
        return "UNKNOWN", "", None, "UNKNOWN"

    primary = formats[0]
    name = str(primary.get("name") or "").strip()
    descriptions = [
        str(item).strip()
        for item in (primary.get("descriptions") or [])
        if str(item).strip()
    ]
    desc_fold = {item.casefold() for item in descriptions}
    generation = "UNKNOWN"
    if "promo" in desc_fold:
        generation = "PROMO"
    elif "reissue" in desc_fold:
        generation = "REISSUE"

    media_type = name
    if "lp" in desc_fold or name.casefold() == "vinyl":
        media_type = "LP" if "lp" in desc_fold else "Vinyl"

    qty = _optional_int(primary.get("qty"))
    detail_parts = [name, *descriptions]
    format_detail = ", ".join(part for part in detail_parts if part)
    return media_type, format_detail, qty, generation
