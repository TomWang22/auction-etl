"""Pure helpers for Auction Collector Review."""

from __future__ import annotations

import json
import importlib
import math
import re
from typing import Any

import pandas as pd

import auction_etl.services.discogs_identity as discogs_identity


NON_RECORD_MEDIA = frozenset(
    {
        "MAGAZINE",
        "PHOTO",
        "PHOTOBOOK",
        "PRINT",
        "STAMP",
        "USB",
        "DVD",
        "VHS",
        "LASERDISC",
        "SHEET_MUSIC",
        "TOY",
    }
)
MUSIC_RECORD_MEDIA = frozenset(
    {
        "LP",
        "LP_BOX_SET",
        "EP_7_INCH",
        "SINGLE_12_INCH",
        "12_INCH_SINGLE",
        "CD",
        "CD_BOX_SET",
        "CD_SINGLE_8CM",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
        "CASSETTE",
        "CASSETTE_BOX_SET",
        "REEL_TO_REEL",
        "MIXED_MEDIA",
        "VINYL",
    }
)
SCENE_MAIN_RECORDS = "Main records"
SCENE_MAGAZINES = "Magazines"
SCENE_PRINTS = "Prints & photobooks"
PAPER_MEDIA = frozenset(
    {
        "PHOTO",
        "PRINT",
        "PHOTOBOOK",
        "STAMP",
        "MAGAZINE",
    }
)
SCENE_ALL = "All listings"
SCENE_OPTIONS = (
    SCENE_MAIN_RECORDS,
    SCENE_MAGAZINES,
    SCENE_PRINTS,
    SCENE_ALL,
)
MEDIA_GROUP_ALL_MUSIC = "All music"
MEDIA_GROUP_LP = "LP"
MEDIA_GROUP_CD = "CD"
MEDIA_GROUP_CASSETTE = "Cassette"
MEDIA_GROUP_SEVEN = '7"'
MEDIA_GROUP_TWELVE = '12"'
MEDIA_GROUP_LOTS = "Lots"
MEDIA_GROUP_MAGAZINES = "Magazines"
MEDIA_GROUP_EVERYTHING = "Everything"
MEDIA_GROUP_OPTIONS = (
    MEDIA_GROUP_ALL_MUSIC,
    MEDIA_GROUP_LP,
    MEDIA_GROUP_CD,
    MEDIA_GROUP_CASSETTE,
    MEDIA_GROUP_SEVEN,
    MEDIA_GROUP_LOTS,
    MEDIA_GROUP_MAGAZINES,
    MEDIA_GROUP_EVERYTHING,
)
MEDIA_GROUPS_SKIP_SCENE = frozenset(
    {
        MEDIA_GROUP_LOTS,
        MEDIA_GROUP_MAGAZINES,
        MEDIA_GROUP_EVERYTHING,
    }
)
LP_MEDIA = frozenset(
    {
        "LP",
        "LP_BOX_SET",
        "SINGLE_12_INCH",
        "12_INCH_SINGLE",
    }
)
CD_MEDIA = frozenset(
    {
        "CD",
        "CD_BOX_SET",
        "CD_SINGLE_8CM",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
    }
)
CASSETTE_MEDIA = frozenset({"CASSETTE", "CASSETTE_BOX_SET"})
SEVEN_INCH_MEDIA = frozenset({"EP_7_INCH"})
TWELVE_INCH_MEDIA = frozenset({"SINGLE_12_INCH", "12_INCH_SINGLE"})
SOURCE_ORDER = ("Buyee", "eBay", "Gripsweat")
IDENTITY_ORDER = ("Filled", "Needs review", "Unmatched", "Lot")
MUSIC_IDENTITY_ORDER = ("Filled", "Needs review", "Unmatched")
IDENTITY_QUEUE_ALL = "All identities"
IDENTITY_QUEUE_OPTIONS = (IDENTITY_QUEUE_ALL, *IDENTITY_ORDER)
LOT_FORMAT_ALL = "All"
LOT_FORMAT_OPTIONS = (
    LOT_FORMAT_ALL,
    "LP",
    "Cassette",
    "CD",
    "EP",
    "Magazine",
    "Mixed",
)
BULK_LOT_MEDIA = {
    "LP_BULK_LOT": "LP bulk lot",
    "CD_BULK_LOT": "CD bulk lot",
    "EP_BULK_LOT": "EP bulk lot",
    "CASSETTE_BULK_LOT": "Cassette bulk lot",
    "MIXED_BULK_LOT": "Mixed bulk lot",
    "MAGAZINE_BULK_LOT": "Magazine bulk lot",
}
_LOT_FORMAT_MEDIA = {
    "LP": "LP_BULK_LOT",
    "CD": "CD_BULK_LOT",
    "EP": "EP_BULK_LOT",
    "Cassette": "CASSETTE_BULK_LOT",
    "Magazine": "MAGAZINE_BULK_LOT",
}

CATALOG_PATTERN = re.compile(
    r"""
    (?:
        [A-Z]{1,8}
        [\s._/-]*
        \d{2,8}
        (?:
            [\s._/-]+
            \d{1,5}
        )*
    )
    |
    (?:
        \d{6,12}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def review_media_slot(
    manual: Any,
    title: Any,
    stored: Any,
) -> str:
    """Media chip for one listing.

    A saved choice stays on that chip. Otherwise use the title, then the
    stored fact, so an LP that was just filled in is under LP.
    """
    saved = clean_text(manual)
    if saved:
        display = saved
    else:
        hint_media, _hint_catalog, _bulk = title_classification(title)
        display = hint_media or clean_text(stored) or ""
    if display.upper() == "VINYL":
        hint_media, _hint_catalog, _bulk = title_classification(title)
        display = hint_media or ""
    if display in TWELVE_INCH_MEDIA:
        return "LP"
    return display


def bulk_lot_media(value: Any) -> bool:
    """True for a generic pile or one format of bulk lot."""
    text = clean_text(value)
    return text == "BULK_LOT" or text in BULK_LOT_MEDIA


def bulk_lot_choice(lot_format: Any) -> str:
    """The media-type value for a lot of this format."""
    return _LOT_FORMAT_MEDIA.get(clean_text(lot_format), "BULK_LOT")


_LOT_MIX_FORMATS = ("LP", "EP", "CD", "Cassette")
_LOT_MIX_LINE = re.compile(r"(?i)^Lot mix:\s*(.+)$")
_LOT_MIX_COUNT = re.compile(
    r"(?ix)"
    r"(?<![A-Za-z0-9])(?P<label>lps?|eps?|cds?|cassettes?|カセット)"
    r"\s*(?P<count>\d{1,3})(?!\d)\s*(?:枚|本)"
    r"|"
    r"(?<![A-Za-z0-9])(?P<count2>\d{1,3})(?!\d)\s*(?:枚|本)?\s*(?:x|×)?\s*"
    r"(?P<label2>lps|eps|cds|cassettes|カセット)(?![A-Za-z0-9])"
)
_LOT_MIX_NOTE_COUNT = re.compile(
    r"(?i)(?P<label>lps?|eps?|cds?|cassettes?)\s+(?P<count>\d{1,3})(?!\d)"
)


def _lot_mix_label(raw: str) -> str:
    token = clean_text(raw).casefold()
    if token in {"lp", "lps"}:
        return "LP"
    if token in {"ep", "eps"}:
        return "EP"
    if token in {"cd", "cds"}:
        return "CD"
    if token in {"cassette", "cassettes", "カセット"}:
        return "Cassette"
    return ""


def _lot_mix_counts(pattern: re.Pattern[str], text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in pattern.finditer(text):
        label = _lot_mix_label(match.group("label") or match.groupdict().get("label2") or "")
        count = safe_int(match.group("count") or match.groupdict().get("count2"))
        if not label or not count:
            continue
        counts[label] = counts.get(label, 0) + int(count)
    return {name: counts[name] for name in _LOT_MIX_FORMATS if name in counts}


def lot_mix_from_title(title: Any) -> dict[str, int]:
    """Counts named in the title, such as LP 2 枚 and EP 2 枚."""
    return _lot_mix_counts(_LOT_MIX_COUNT, clean_text(title))


def lot_mix_line(counts: dict[str, int] | None) -> str:
    """The notes line the mixed-lot counts own."""
    if not counts:
        return ""
    parts = [
        f"{name} {int(counts[name])}"
        for name in _LOT_MIX_FORMATS
        if int(counts.get(name) or 0) > 0
    ]
    if not parts:
        return ""
    return "Lot mix: " + ", ".join(parts) + "."


def lot_mix_from_notes(notes: Any) -> dict[str, int]:
    """Read the lot-mix line back into format counts."""
    for line in clean_text(notes).splitlines():
        match = _LOT_MIX_LINE.match(line.strip())
        if not match:
            continue
        return _lot_mix_counts(_LOT_MIX_NOTE_COUNT, match.group(1))
    return {}


def notes_without_lot_mix(notes: Any) -> str:
    """Notes box text. The mixed-lot counts own their line."""
    kept = [
        line
        for line in clean_text(notes).splitlines()
        if not _LOT_MIX_LINE.match(line.strip())
    ]
    return "\n".join(kept).strip()


def notes_with_lot_mix(notes: Any, counts: dict[str, int] | None) -> str:
    """Keep one lot-mix line. Other notes stay as written."""
    body = notes_without_lot_mix(notes)
    line = lot_mix_line(counts)
    if not line:
        return body
    if not body:
        return line
    return f"{line}\n{body}"


def lot_count_noun(media: Any, lot_format: Any = None) -> str:
    """What to count in a pile. Only an LP lot is records."""
    kind = lot_format_name(media) or clean_text(lot_format)
    return {
        "LP": "Records",
        "CD": "CDs",
        "EP": "EPs",
        "Cassette": "Cassettes",
        "Magazine": "Magazines",
        "Mixed": "Pieces",
    }.get(kind, "Pieces")


def lot_format_name(media: Any) -> str:
    """LP, cassette, CD, EP, or magazine for a bulk lot. USB and VHS stay out."""
    text = clean_text(media)
    if text in BULK_LOT_MEDIA:
        label = BULK_LOT_MEDIA[text]
        if label == "Mixed bulk lot":
            return "Mixed"
        return label.replace(" bulk lot", "")
    slot = text.upper()
    if slot in LP_MEDIA or slot == "LP":
        return "LP"
    if slot in CD_MEDIA or slot == "CD":
        return "CD"
    if slot in CASSETTE_MEDIA or slot == "CASSETTE":
        return "Cassette"
    if slot in SEVEN_INCH_MEDIA or slot in {"EP", "EP_7_INCH"}:
        return "EP"
    if slot == "MAGAZINE":
        return "Magazine"
    return ""


def neighbor_listing_identity(
    identities: list[str],
    current: str,
) -> str | None:
    """The listing under this row. The one above, when this row is last."""
    return next_open_listing(identities, current, None)


def next_open_listing(
    identities: list[str],
    current: str,
    remaining: set[str] | None,
) -> str | None:
    """The next row still in this pile. Above, when nothing below is left."""
    ordered = [str(item) for item in identities]
    try:
        index = ordered.index(str(current))
    except ValueError:
        return None

    def still_open(item: str) -> bool:
        if item == str(current):
            return False
        if remaining is None:
            return True
        return item in remaining

    for item in ordered[index + 1 :]:
        if still_open(item):
            return item
    for item in reversed(ordered[:index]):
        if still_open(item):
            return item
    return None


def listing_stays_open(
    selected: str | None,
    *,
    in_filter: bool,
    in_sales: bool,
) -> bool:
    """Keep the editor open after Use this even when the pile no longer lists it."""
    if not selected:
        return False
    if in_filter:
        return True
    return in_sales


def review_lot_flag(title: Any, manual_bulk: Any) -> bool:
    """A saved lot choice wins. Otherwise the title, not a stale stored flag."""
    unset = is_missing(manual_bulk)
    if not unset:
        try:
            unset = bool(pd.isna(manual_bulk))
        except (TypeError, ValueError):
            unset = False
    _details, is_job_lot = _media_helpers()
    if unset:
        return bool(is_job_lot(clean_text(title)))
    return as_boolean(manual_bulk)


def _frame_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series([None] * len(frame), index=frame.index)


def place_review_media(frame: pd.DataFrame) -> pd.DataFrame:
    """Put each listing on the chip its format identifies, on every rerun."""
    if frame is None or frame.empty or "title" not in frame.columns:
        return frame
    saved = _frame_column(frame, "collector_manual_media_type")
    shared = _frame_column(frame, "manual_media_type")
    stored = _frame_column(frame, "effective_media_type")
    auction_media = _frame_column(frame, "media_type")
    manual_lots = _frame_column(frame, "manual_bulk_lot")
    media_display: list[str] = []
    job_lots: list[bool] = []
    lot_formats: list[str] = []
    for title, account_media, shared_media, effective, auction, manual_lot in zip(
        frame["title"],
        saved,
        shared,
        stored,
        auction_media,
        manual_lots,
        strict=True,
    ):
        chosen = clean_text(account_media) or clean_text(shared_media)
        fact = clean_text(effective) or clean_text(auction)
        lot = review_lot_flag(title, manual_lot)
        slot = review_media_slot(chosen, title, fact)
        mix = lot_mix_from_title(title)
        if lot and not chosen and len(mix) >= 2:
            slot = "MIXED_BULK_LOT"
        elif lot and not chosen:
            slot = bulk_lot_choice(lot_format_name(review_media_slot(None, title, fact)))
        media_display.append(slot)
        job_lots.append(lot)
        format_slot = review_media_slot(None, title, fact)
        if lot and len(mix) >= 2:
            lot_formats.append("Mixed")
        else:
            lot_formats.append(lot_format_name(format_slot) if lot else "")
    placed = frame.copy()
    placed["media_display"] = media_display
    placed["job_lot"] = job_lots
    placed["lot_format"] = lot_formats
    return placed


def title_classification(
    title: Any,
) -> tuple[str | None, str | None, bool]:
    """Media, catalog, and bulk hints taken from the listing title.

    Classifier imports stay inside this function so Streamlit can load this
    module while ``app.collector_review`` is still executing as ``__main__``.
    """
    text = clean_text(title)
    if not text:
        return None, None, False

    catalog_token, _fold, _junk = _catalog_helpers()
    classify_media_details, _is_job_lot = _media_helpers()
    details = classify_media_details(text)
    return (
        details.format,
        catalog_token(title=text),
        details.bulk_lot,
    )


def media_matches_scene(
    media_display: Any,
    scene: str,
) -> bool:
    """True when a listing belongs on the selected collection scene."""
    media = clean_text(media_display).upper()
    if scene == SCENE_MAGAZINES:
        return media == "MAGAZINE"
    if scene == SCENE_PRINTS:
        return media in {"PHOTOBOOK", "PRINT", "PHOTO"}
    if scene == SCENE_ALL:
        return True
    if scene == SCENE_MAIN_RECORDS:
        if media in NON_RECORD_MEDIA:
            return False
        return media in MUSIC_RECORD_MEDIA or not media
    return True


def media_matches_group(
    media_display: Any,
    group: str,
    *,
    job_lot: bool = False,
) -> bool:
    """True when a listing belongs on the selected media chip."""
    media = clean_text(media_display).upper()
    if group == MEDIA_GROUP_EVERYTHING:
        return True
    if group == MEDIA_GROUP_LOTS:
        return bool(job_lot)
    if group == MEDIA_GROUP_MAGAZINES:
        return media == "MAGAZINE"
    if job_lot:
        return False
    if group == MEDIA_GROUP_ALL_MUSIC:
        if media in NON_RECORD_MEDIA:
            return False
        return media in MUSIC_RECORD_MEDIA or not media
    if group == MEDIA_GROUP_LP:
        return media in LP_MEDIA
    if group == MEDIA_GROUP_CD:
        return media in CD_MEDIA
    if group == MEDIA_GROUP_CASSETTE:
        return media in CASSETTE_MEDIA
    if group == MEDIA_GROUP_SEVEN:
        return media in SEVEN_INCH_MEDIA
    if group == MEDIA_GROUP_TWELVE:
        return media in LP_MEDIA
    return True


def format_count(value: int) -> str:
    """Customer-facing integer with thousands separators."""
    return f"{int(value):,}"


def identity_mix_caption(
    filled: int,
    needs_review: int,
    unmatched: int,
    lots: int = 0,
) -> str:
    """Readable match mix for the current view."""
    music_total = filled + needs_review + unmatched
    if music_total <= 0 and lots <= 0:
        return "No listings in this view."
    if music_total <= 0:
        return f"{format_count(lots)} bulk lots ready for review"
    parts = [
        f"{format_count(filled)} matched ({filled * 100 // music_total}%)",
        f"{format_count(needs_review)} need a decision ({needs_review * 100 // music_total}%)",
        f"{format_count(unmatched)} unmatched ({unmatched * 100 // music_total}%)",
    ]
    if lots:
        parts.append(f"{format_count(lots)} lots parked")
    return " · ".join(parts)


IDENTIFIED_FORMATS = LP_MEDIA | CD_MEDIA | CASSETTE_MEDIA | SEVEN_INCH_MEDIA


def release_identified_locally(
    *,
    catalog: Any,
    media: Any,
    title: Any = None,
    job_lot: bool = False,
) -> bool:
    """A pressing Discogs does not list is still filled when the copy is named.

    The needed facts are a real catalog number and a specific format.
    A bulk lot stays a lot. A title with no catalog stays unmatched.
    """
    if job_lot:
        return False
    if clean_text(media).upper() not in IDENTIFIED_FORMATS:
        return False
    catalog_text = clean_text(catalog)
    if not catalog_text:
        return False
    return not discogs_identity.is_junk_catalog(
        catalog_text,
        title=clean_text(title) or None,
    )


def apply_local_identity(frame: pd.DataFrame) -> pd.DataFrame:
    """Show Unmatched as Filled when the listing already names the pressing."""
    if frame is None or frame.empty or "identity_status_display" not in frame.columns:
        return frame
    catalogs = _frame_column(frame, "catalog_display")
    if catalogs.map(clean_text).eq("").all():
        catalogs = _frame_column(frame, "effective_catalog_number")
    medias = _frame_column(frame, "media_display")
    titles = _frame_column(frame, "title")
    lots = _frame_column(frame, "job_lot")
    updated: list[str] = []
    for status, catalog, media, title, lot in zip(
        frame["identity_status_display"],
        catalogs,
        medias,
        titles,
        lots,
        strict=True,
    ):
        label = clean_text(status) or "Unmatched"
        if label == "Unmatched" and clean_text(media).upper() in PAPER_MEDIA:
            label = "Not a record"
        elif label == "Unmatched" and release_identified_locally(
            catalog=catalog,
            media=media,
            title=title,
            job_lot=as_boolean(lot),
        ):
            label = "Filled"
        updated.append(label)
    placed = frame.copy()
    placed["identity_status_display"] = updated
    return placed


def identity_matches_queue(
    display: str,
    queue: str,
    *,
    job_lot: bool = False,
) -> bool:
    """True when a listing belongs on the selected Discogs work pile."""
    selected = (queue or IDENTITY_QUEUE_ALL).strip() or IDENTITY_QUEUE_ALL
    if selected == IDENTITY_QUEUE_ALL:
        return True
    if selected == "Lot":
        return bool(job_lot)
    if job_lot:
        return False
    return (display or "Unmatched") == selected


def rows_kept_after_search(
    filtered: pd.DataFrame,
    queue: pd.DataFrame,
    *,
    previous_identities: list[str],
    selected_identity: str | None,
    pinned: set[str],
    identity_queue: str,
) -> tuple[pd.DataFrame, set[str]]:
    """Keep a searched sale on Unmatched after Discogs marks it Needs review.

    The search writes needs_review. That is a different pile, so the row
    would leave the table before a cover is chosen. A row that was already
    on this table, or the one open now, stays until the pile changes.
    """
    if identity_queue != "Unmatched" or queue is None or queue.empty:
        return filtered, set()
    if "identity_status_display" not in queue.columns:
        return filtered, set()

    identities = [
        listing_identity(marketplace, listing_id)
        for marketplace, listing_id in zip(
            queue["marketplace"],
            queue["listing_id"],
            strict=False,
        )
    ]
    by_identity = dict(zip(identities, queue.index, strict=False))
    identity_by_label = dict(zip(queue.index, identities, strict=False))
    visible = {
        listing_identity(marketplace, listing_id)
        for marketplace, listing_id in zip(
            filtered["marketplace"],
            filtered["listing_id"],
            strict=False,
        )
    } if filtered is not None and not filtered.empty else set()
    candidates = set(pinned)
    candidates.update(str(item) for item in previous_identities)
    if selected_identity:
        candidates.add(str(selected_identity))
    selected_index = by_identity.get(str(selected_identity or ""))
    if (
        selected_index is not None
        and "identity_status_changed_at" in queue.columns
        and clean_text(queue.at[selected_index, "identity_status_display"])
        == "Needs review"
    ):
        opened_at = pd.to_datetime(
            queue.at[selected_index, "identity_status_changed_at"],
            utc=True,
            errors="coerce",
        )
        if pd.notna(opened_at):
            changed = pd.to_datetime(
                queue["identity_status_changed_at"],
                utc=True,
                errors="coerce",
            )
            same_search = (changed - opened_at).abs() <= pd.Timedelta(seconds=90)
            for index in queue.index[same_search.fillna(False).to_numpy()]:
                if clean_text(queue.at[index, "identity_status_display"]) == "Needs review":
                    candidates.add(identity_by_label[index])
    keep_index: list[Any] = []
    next_pins: set[str] = set()
    for identity in candidates:
        index = by_identity.get(identity)
        if index is None:
            continue
        status = clean_text(queue.at[index, "identity_status_display"])
        if status != "Needs review":
            continue
        next_pins.add(identity)
        if identity not in visible:
            keep_index.append(index)
    if not keep_index:
        return filtered, next_pins
    extra = queue.loc[keep_index]
    combined = (
        extra.copy()
        if filtered is None or filtered.empty
        else pd.concat([filtered, extra])
    )
    if {"closing_display", "listing_id"}.issubset(combined.columns):
        combined = combined.sort_values(
            by=["closing_display", "listing_id"],
            ascending=[False, True],
            na_position="last",
        )
    # Both frames are numbered from zero. A repeated number makes
    # later row lookups return two values at once.
    return combined.reset_index(drop=True), next_pins


def marketplace_source_label(marketplace: Any) -> str:
    """Stable Buyee / eBay / Gripsweat label for unique-sale charts."""
    value = clean_text(marketplace).casefold()
    if value == "buyee":
        return "Buyee"
    if value == "ebay":
        return "eBay"
    if value == "gripsweat":
        return "Gripsweat"
    return clean_text(marketplace) or "Other"


def drop_overlapping_gripsweat_rows(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Keep eBay as the visible row when Gripsweat archived the same listing."""
    if dataframe.empty:
        return dataframe.copy()

    frame = dataframe.copy()
    marketplace = (
        frame["marketplace"]
        .map(clean_text)
        .str.casefold()
    )
    listing_id = frame["listing_id"].map(clean_text)
    ebay_ids = set(listing_id[marketplace == "ebay"])
    overlap = (marketplace == "gripsweat") & listing_id.isin(ebay_ids)
    return frame.loc[~overlap].copy()


def shortlist_preview_thumb(raw: Any) -> str:
    """First Discogs search-hit thumb so Review can compare sleeves."""
    for hit in _shortlist_rows(raw):
        thumb = clean_text(hit.get("thumb") or hit.get("cover_image"))
        if thumb:
            return thumb
    return ""


def shortlist_preview_label(raw: Any) -> str:
    """First Discogs search-hit label for unlabeled review rows."""
    hits = _shortlist_rows(raw)
    if not hits:
        return ""
    labels = hits[0].get("label") or []
    if isinstance(labels, str):
        return clean_text(labels)
    if isinstance(labels, list) and labels:
        return clean_text(labels[0])
    return ""


def _shortlist_rows(raw: Any) -> list[dict[str, Any]]:
    payload = raw
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except ValueError:
            return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def is_missing(value: Any) -> bool:
    """Return whether a scalar value represents missing data."""
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip().lower() in {
            "",
            "nan",
            "nat",
            "none",
            "null",
            "<na>",
        }

    if isinstance(value, float):
        return math.isnan(value)

    return False


def clean_text(value: Any) -> str:
    """Return normalized display text."""
    if is_missing(value):
        return ""

    return str(value).strip()


def safe_float(value: Any) -> float | None:
    """Convert a scalar value to float when possible."""
    if is_missing(value):
        return None

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if math.isnan(result):
        return None

    return result


def safe_int(value: Any) -> int | None:
    """Convert a scalar value to int when possible."""
    number = safe_float(value)

    if number is None:
        return None

    return int(number)


_MEDIA_FORM_ALIASES = {
    "SHM_CD": "CD",
    "SACD": "CD",
    "BLU_SPEC_CD": "CD",
    "7_INCH": "EP_7_INCH",
    "12_INCH_SINGLE": "SINGLE_12_INCH",
}


def _row_value(row: Any, name: str) -> Any:
    """Read a review column, including the collector_ alias."""
    for candidate in (name, f"collector_{name}"):
        if isinstance(row, pd.Series) and candidate not in row.index:
            continue
        try:
            value = row.get(candidate) if hasattr(row, "get") else row[candidate]
        except (KeyError, TypeError, AttributeError):
            continue
        if not is_missing(value):
            return value
    return None


def _option_choice(value: Any, options: tuple[str, ...]) -> str | None:
    """Map a stored fact onto a form option, skipping generic Vinyl."""
    text = clean_text(value)
    if not text or text == "Automatic / unset":
        return None
    mapped = _MEDIA_FORM_ALIASES.get(text.upper(), text)
    if mapped in options:
        return mapped
    return None


def condition_profile(media: str | None) -> dict[str, str]:
    """Grade labels for the format on the open form.

    A bulk lot is not one sleeve. A CD, a cassette, an LP, and a 7"
    each name their own parts so the same two dropdowns stay obvious.
    """
    shown = clean_text(media)
    letter_help = (
        "S through D is the shop scale: S sealed, A clean, "
        "B generally good, C a little worn, D heavily worn. "
        "Goldmine is M, NM, VG, G, F, and P. "
        "Use the scale this seller used."
    )
    if bulk_lot_media(shown):
        paper_lot = lot_format_name(shown) == "Magazine"
        return {
            "kind": "lot",
            "scale": "both" if paper_lot else "vinyl",
            "media_label": "Lot condition",
            "cover_label": "",
            "help": (
                "One grade for the whole pile of magazines."
                if paper_lot
                else (
                    "One grade for the whole pile. "
                    "These records are not one sleeve and one disc."
                )
            ),
            "caption": (
                "Several magazines in one sale. There is no single issue grade."
                if paper_lot
                else (
                    "Several records in one sale. "
                    "There is no single catalog, obi, or sleeve grade."
                )
            ),
            "insert_label": "Insert",
            "show_obi": "no",
            "show_poster": "no",
            "poster_label": "",
        }
    if shown in CD_MEDIA:
        return {
            "kind": "cd",
            "scale": "both",
            "media_label": "Disc",
            "cover_label": "Jewel case",
            "help": letter_help,
            "caption": (
                "A CD is a disc and a jewel case. The booklet is the insert. "
                "Sellers grade it on the shop scale or on Goldmine."
            ),
            "insert_label": "Booklet",
            "show_obi": "yes",
            "show_poster": "no",
            "poster_label": "",
        }
    if _is_cassette(shown):
        return {
            "kind": "cassette",
            "scale": "both",
            "media_label": "Tape",
            "cover_label": "Shell",
            "help": letter_help,
            "caption": (
                "A cassette is a tape and a shell. "
                "It includes a lyric card, not an obi or a poster. "
                "Sellers grade it on the shop scale or on Goldmine."
            ),
            "insert_label": "Lyric card",
            "show_obi": "no",
            "show_poster": "no",
            "poster_label": "",
        }
    if shown in PAPER_MEDIA:
        names = {
            "PHOTO": "photo",
            "PRINT": "print",
            "PHOTOBOOK": "photobook",
            "STAMP": "stamp",
            "MAGAZINE": "magazine",
        }
        piece = names.get(shown, "piece")
        return {
            "kind": "paper",
            "scale": "both",
            "media_label": "Condition",
            "cover_label": "",
            "help": "One grade for this piece. It is not a record.",
            "caption": f"A {piece} is not a record. One condition is enough.",
            "insert_label": "Insert",
            "show_obi": "no",
            "show_poster": "no",
            "poster_label": "",
        }
    if shown == "EP_7_INCH":
        return {
            "kind": "ep",
            "scale": "vinyl",
            "media_label": "Record",
            "cover_label": "Sleeve",
            "help": "",
            "caption": 'A 7" is a record and a sleeve. Obi is only on a Japanese pressing.',
            "insert_label": "Insert",
            "show_obi": "yes",
            "show_poster": "no",
            "poster_label": "",
        }
    if shown in {"LP", "SINGLE_12_INCH", "LP_BOX_SET"}:
        return {
            "kind": "lp",
            "scale": "vinyl",
            "media_label": "Record",
            "cover_label": "Jacket",
            "help": "",
            "caption": (
                "A Japanese LP can have an obi. "
                "An LP can have an insert and a poster or pin-up. "
                "A sealed copy can still be insert only, pin-up in the insert, "
                "or factory no insert."
            ),
            "insert_label": "Insert",
            "show_obi": "yes",
            "show_poster": "yes",
            "poster_label": "Poster / pin-up",
        }
    return {
        "kind": "other",
        "scale": "vinyl",
        "media_label": "Media condition",
        "cover_label": "Cover condition",
        "help": "",
        "caption": "",
        "insert_label": "Insert / lyric sheet",
        "show_obi": "yes",
        "show_poster": "yes",
        "poster_label": "Poster",
    }


_SHOP_GRADES = ("S", "A", "B", "C", "D")
_GOLDMINE_GRADES = (
    "M",
    "NM",
    "EX+",
    "EX",
    "EX-",
    "E+",
    "E",
    "E-",
    "VG++",
    "VG+",
    "VG",
    "G+",
    "G",
    "F",
    "P",
)


def condition_grade_options(scale: str) -> tuple[str, ...]:
    """Shop letters, Goldmine, or both. A cassette seller may use either."""
    if scale == "letter":
        grades = _SHOP_GRADES
    elif scale == "both":
        grades = _SHOP_GRADES + _GOLDMINE_GRADES
    else:
        grades = _GOLDMINE_GRADES
    return ("Automatic / unset",) + grades


SEALED_GRADE = "S"


def grades_when_sealed(options: tuple[str, ...]) -> tuple[str, ...]:
    """S means sealed. A Goldmine list does not already include that letter."""
    if SEALED_GRADE in options:
        return options
    if options and options[0] == "Automatic / unset":
        return (options[0], SEALED_GRADE, *options[1:])
    return (SEALED_GRADE, *options)


PINUP_INSERT_NOTE = "Pin-up is the insert."
INSERT_ONLY_NOTE = "Insert only."
FACTORY_NO_INSERT_NOTE = "Factory no insert."
MISSING_INSERT = "Missing the insert"
_INSERT_FACT_NOTES = (
    PINUP_INSERT_NOTE,
    INSERT_ONLY_NOTE,
    FACTORY_NO_INSERT_NOTE,
)


def notes_insert_fact(notes: Any) -> str:
    """The LP paper fact stored for this copy, if the form recorded one."""
    text = clean_text(notes)
    for line in text.splitlines():
        if line.strip() in _INSERT_FACT_NOTES:
            return line.strip()
    return ""


def notes_without_insert_fact(notes: Any) -> str:
    """Notes box text. The insert control owns the factory-paper line."""
    text = clean_text(notes)
    kept = [
        line
        for line in text.splitlines()
        if line.strip() not in _INSERT_FACT_NOTES
    ]
    return "\n".join(kept).strip()


def notes_with_insert_fact(notes: Any, fact: str | None) -> str:
    """Keep one paper fact. The other two come off so they cannot stack."""
    body = notes_without_insert_fact(notes)
    if not fact:
        return body
    if not body:
        return fact
    return f"{fact}\n{body}"


def notes_pinup_is_insert(notes: Any) -> bool:
    """True when this copy's pin-up is the insert, not a separate poster."""
    return notes_insert_fact(notes) == PINUP_INSERT_NOTE


def notes_without_pinup(notes: Any) -> str:
    """Notes box text, without the pin-up line the poster control owns."""
    return notes_without_insert_fact(notes)


def notes_with_pinup(notes: Any, include: bool) -> str:
    """Keep or drop the pin-up line. Other notes stay as the user wrote them."""
    return notes_with_insert_fact(notes, PINUP_INSERT_NOTE if include else None)


def _pack_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + ", and " + names[-1]


def factory_pack_sentence(obi: str, insert: str, poster: str) -> str:
    """What this LP came with from the factory, and what complete means.

    Sleeve and record are always part of the copy. The paper pack is one of:
    obi, insert, and a pin-up; obi and insert; insert only; a pin-up that is
    the insert; or factory no insert. Missing the insert is not a pack. It
    means the pressing included an insert and this copy does not have it.
    """
    obi_yes = obi == "Yes"
    obi_no = obi == "No"
    poster_yes = poster == "Pin-up is the poster"
    poster_no = poster == "No"
    with_copy = "with the sleeve and the record"

    if insert == "Insert only":
        return (
            "This pressing came with the insert only. "
            f"Complete means that sheet is here, {with_copy}. "
            "There is no obi and no pin-up."
        )
    if insert == "Pin-up is the insert":
        if obi_yes:
            return (
                "This pressing came with an obi and a pin-up that is the insert. "
                f"Complete means both are here, {with_copy}. "
                "There is no separate poster."
            )
        if obi_no:
            return (
                "This pressing came with a pin-up that is the insert. "
                f"Complete means that sheet is here, {with_copy}. "
                "There is no obi and no separate poster."
            )
        return (
            "This pressing came with a pin-up that is the insert. "
            f"Complete means that sheet is here, {with_copy}. "
            "Set obi if this copy has the Japanese strip. "
            "There is no separate poster."
        )
    if insert == "Factory no insert":
        came: list[str] = []
        needed: list[str] = []
        if obi_yes:
            came.append("an obi")
            needed.append("the obi")
        if poster_yes:
            came.append("a pin-up")
            needed.append("the pin-up")
        if came:
            verb = "is" if len(came) == 1 else "are"
            return (
                "This pressing never included an insert. "
                f"It came with {_pack_names(came)}. "
                f"Complete means {_pack_names(needed)} {verb} here, {with_copy}."
            )
        if poster_no:
            return (
                "This pressing never included an insert. "
                "Complete means the sleeve and the record. "
                "There is no obi and no pin-up."
                if obi_no
                else "This pressing never included an insert. "
                "Complete means the sleeve and the record. "
                "There is no pin-up. "
                "Set obi if this copy has the Japanese strip."
            )
        return (
            "This pressing never included an insert. "
            "Complete does not require one. "
            "There is no pin-up. "
            "Set obi if this copy has the Japanese strip."
        )
    if insert == "Yes":
        included = []
        if obi_yes:
            included.append("the obi")
        included.append("the insert")
        if poster_yes:
            included.append("the pin-up")
        absent: list[str] = []
        if obi_no:
            absent.append("no obi")
        if poster_no:
            absent.append("no pin-up")
        if len(included) == 1:
            lead = f"Complete means the insert is here, {with_copy}."
        else:
            lead = (
                f"Complete means {_pack_names(included)} are here, {with_copy}."
            )
        if absent:
            return lead + " This pressing has " + " and ".join(absent) + "."
        unset: list[str] = []
        if not obi_yes and not obi_no:
            unset.append("obi")
        if not poster_yes and not poster_no:
            unset.append("the pin-up")
        if unset:
            pronoun = "it" if len(unset) == 1 else "them"
            return (
                lead
                + f" Set {_pack_names(unset)} if this pressing came with {pronoun}."
            )
        return (
            "This pressing came with an obi, an insert, and a pin-up. " + lead
        )
    if insert in {MISSING_INSERT, "No"}:
        still = ""
        if obi_yes and poster_yes:
            still = " The obi and the pin-up can still be on this copy."
        elif obi_yes and poster_no:
            still = " The obi can still be on this copy. There is no pin-up."
        elif obi_no and poster_yes:
            still = " There is no obi. The pin-up can still be on this copy."
        elif obi_no and poster_no:
            still = " There is no obi and no pin-up."
        return (
            "This copy is missing the insert. The pressing included one, "
            "so this copy is not complete."
            + still
            + " Insert only means that sheet is here and it is all the factory included."
            + " Factory no insert means the pressing never included one."
        )
    return (
        "Complete is whatever this pressing came with. "
        "That can be an obi, an insert, and a pin-up. "
        "It can be an obi and an insert. "
        "It can be the insert only. "
        "It can be a pin-up that is the insert. "
        "It can be factory no insert. "
        "Missing the insert means the pressing included one and this copy does not have it."
    )


def automatic_media_type(row: Any, options: tuple[str, ...]) -> str | None:
    """Listing EP / LP / CD wins over a Discogs pressing stored as Vinyl."""
    if review_lot_flag(
        _row_value(row, "title"),
        _row_value(row, "manual_bulk_lot"),
    ):
        hint_media, _hint_catalog, _bulk = title_classification(
            _row_value(row, "title")
        )
        mix = lot_mix_from_title(_row_value(row, "title"))
        lot_code = (
            "MIXED_BULK_LOT"
            if len(mix) >= 2
            else bulk_lot_choice(lot_format_name(hint_media))
        )
        lot_choice = _option_choice(
            lot_code,
            options,
        )
        if lot_choice:
            return lot_choice
    for name in ("effective_media_type", "media_type"):
        choice = _option_choice(_row_value(row, name), options)
        if choice:
            return choice
    hint_media, _hint_catalog, _bulk = title_classification(
        _row_value(row, "title")
    )
    hinted = _option_choice(hint_media, options)
    if hinted:
        return hinted
    resolved = discogs_identity.effective_listing_media(
        clean_text(_row_value(row, "media_type"))
        or clean_text(_row_value(row, "effective_media_type"))
        or None,
        _row_value(row, "title"),
    )
    return _option_choice(resolved, options)


def automatic_catalog(row: Any) -> str:
    """Printed pressing number, then a Discogs or seller runout when it adds one."""
    stored = clean_text(_row_value(row, "effective_catalog_number"))
    matrix = clean_text(_row_value(row, "effective_matrix_number"))
    if not matrix:
        report = parse_seller_report(_row_value(row, "seller_report_text"))
        matrix = clean_text(report.get("matrix"))
    shown = display_matrix_catalog(
        stored_catalog=stored,
        stored_matrix=matrix,
        title=_row_value(row, "title"),
    )
    return shown or stored or matrix


def automatic_region(row: Any, options: tuple[str, ...]) -> str | None:
    return _option_choice(_row_value(row, "effective_region"), options)


def automatic_disc_count(row: Any) -> int:
    count = safe_int(_row_value(row, "effective_disc_count"))
    if count and count > 0:
        return count
    return 0


_PROMO_TEXT = re.compile(
    r"\bpromo\b|promotional|プロモ|見本|サンプル|white\s*label|\bsample\b",
    re.IGNORECASE,
)
_REISSUE_TEXT = re.compile(
    r"re-?issue|repress|再発|復刻",
    re.IGNORECASE,
)


def media_press_key(media_type: Any, format_detail: Any = None) -> str:
    """Group a 7\", LP, or CD with the other copies of that same format."""
    blob = f"{clean_text(media_type)} {clean_text(format_detail)}".casefold()
    if '7"' in blob or "7 inch" in blob or "ep_7_inch" in blob:
        return "EP_7_INCH"
    if "cassette" in blob:
        return "CASSETTE"
    if re.search(r"\bcd\b|shm", blob):
        return "CD"
    if "lp" in blob or "album" in blob:
        return "LP"
    return clean_text(media_type).upper() or "UNKNOWN"


def pressing_is_promo(
    generation: Any,
    format_detail: Any = None,
    title: Any = None,
) -> bool:
    if clean_text(generation).upper() == "PROMO":
        return True
    if _PROMO_TEXT.search(clean_text(format_detail)):
        return True
    return bool(_PROMO_TEXT.search(clean_text(title)))


def pressing_is_reissue(generation: Any, format_detail: Any = None) -> bool:
    if clean_text(generation).upper() == "REISSUE":
        return True
    return bool(_REISSUE_TEXT.search(clean_text(format_detail)))


def date_pressing_type(
    *,
    generation: Any,
    format_detail: Any,
    release_year: Any,
    earliest_year: Any,
    title: Any = None,
) -> str | None:
    """First pressing is the earliest release year. A later year is a later press.

    Promo / sample is the marketplace copy: the eBay or Buyee title says
    promo, プロモ, 見本, or サンプル. A Discogs format tag of Promo is not
    this copy, so a retail 7" stays a first pressing.
    A named reissue stays a later press even when it is the only copy stored.
    No year means the date is not established.
    """
    if _PROMO_TEXT.search(clean_text(title)):
        return "PROMO_SAMPLE"
    if pressing_is_reissue(generation, format_detail):
        return "REISSUE"
    if _identity_module().listing_names_audiophile_reissue(title):
        return "REISSUE"
    year = safe_int(release_year)
    # 2025 and 2026 are sale years on these listings, not press dates.
    if year is None or year >= 2025:
        return None
    earliest = safe_int(earliest_year)
    if earliest is None or year <= earliest:
        return "FIRST_PRESSING"
    return "REISSUE"


def pressing_type_label(value: Any, release_year: Any = None) -> str:
    """Plain label. A real press year is shown. A sale year such as 2026 is not."""
    year = safe_int(release_year)
    if year is not None and year >= 2025:
        year = None
    text = clean_text(value) or "Automatic / unset"
    if text == "FIRST_PRESSING":
        return f"First pressing ({year})" if year else "First pressing"
    if text == "REISSUE":
        return f"Later press ({year})" if year else "Later press"
    if text == "PROMO_SAMPLE":
        return "Promo / sample"
    if text == "STANDARD":
        return "Standard (release date unknown)"
    return text


def _has_mark(text: str, folded: str, mark: str) -> bool:
    if mark.isascii():
        return re.search(rf"\b{re.escape(mark.casefold())}\b", folded) is not None
    return mark in text


def _stated_flag(
    text: str,
    yes_marks: tuple[str, ...],
    no_marks: tuple[str, ...],
) -> bool | None:
    if not text.strip():
        return None
    folded = text.casefold()
    if any(_has_mark(text, folded, mark) for mark in no_marks):
        return False
    if any(_has_mark(text, folded, mark) for mark in yes_marks):
        return True
    return None


def stated_completeness(notes: Any, title: Any) -> dict[str, bool]:
    """Yes/No only when the pressing notes or the listing actually say so."""
    note_text = clean_text(notes)
    title_text = clean_text(title)
    both = f"{note_text}\n{title_text}"
    found: dict[str, bool] = {}
    obi = _stated_flag(
        both,
        ("obi", "帯"),
        ("no obi", "without obi", "obi missing", "帯なし", "帯無し"),
    )
    if obi is not None:
        found["obi"] = obi
    insert = _stated_flag(
        both,
        ("lyrics", "lyric", "insert", "歌詞"),
        ("no insert", "without insert", "no lyric", "missing lyric"),
    )
    if insert is not None:
        found["insert"] = insert
    poster = _stated_flag(
        both,
        ("poster", "ポスター", "pin-up", "pinup", "ピンナップ"),
        ("no poster", "without poster"),
    )
    if poster is not None:
        found["poster"] = poster
    sticker = _stated_flag(
        both,
        ("sticker", "ステッカー", "シール"),
        ("no sticker", "without sticker"),
    )
    if sticker is not None:
        found["sticker"] = sticker
    sealed = _stated_flag(
        title_text,
        ("sealed", "unopened", "未開封", "shrink", "シュリンク"),
        ("resealed", "not sealed"),
    )
    if sealed is not None:
        found["sealed"] = sealed
    rental = _stated_flag(
        title_text,
        ("rental", "レンタル"),
        ("not rental", "no rental"),
    )
    if rental is not None:
        found["rental"] = rental
    return found


# Seller sheets use these as different steps. E- is not E, and EX- is not EX.
_GRADE_TOKENS = (
    "VG++",
    "NM",
    "EX+",
    "EX-",
    "VG+",
    "G+",
    "E+",
    "E-",
    "EX",
    "VG",
    "M",
    "E",
    "G",
    "F",
    "P",
)
# A grade after the label means that part is present. NONE / なし means it is not.
_PART_ABSENT = re.compile(
    r"(?i)^(none|no|n/?a|なし|無し|無|欠|欠品)\b"
)
_PART_PRESENT = re.compile(
    r"(?i)^(yes|attached|あり|有り|付|付き|有)\b"
)
# Yahoo writes 帯：E-FMT with no space, so the value is only a grade, not the next label.
_GRADE_VALUE = (
    r"(?:VG\+\+|NM-|NM|EX\+|EX-|VG\+|G\+|E\+|E-|EX|VG|M-|M|E|G|F|P|"
    r"NONE|NO|YES|N/?A|なし|無し|欠品|欠|無)"
)
_OBI_VALUE = re.compile(
    rf"(?i)(?:\bobi(?:\s+grading|_grading)?\b|帯)\s*[:：]\s*({_GRADE_VALUE})"
)
_INSERT_VALUE = re.compile(
    rf"(?i)(?:insert(?:\s+grading)?|lyric\s*sheets?|lyrics|歌詞カード|歌詞)\s*(?:is|[:：])\s*({_GRADE_VALUE})"
)
_POSTER_VALUE = re.compile(
    rf"(?i)(?:poster(?:\s+grading)?|ポスター|ピンナップ|pin-?up)\s*[:：]\s*({_GRADE_VALUE})"
)
_COVER_GRADE = re.compile(
    rf"(?i)(?:sleeve\s+grading|jacket|cover|sleeve|ジャケット|ジャケ)\s*(?:is|[:：])\s*({_GRADE_VALUE})"
)
_MEDIA_GRADE = re.compile(
    rf"(?i)(?:record\s+grading|record\s+condition|record|disc|disk|盤質|盤面|盤)\s*(?:is|[:：])\s*({_GRADE_VALUE})"
)
_OBI_BARE_NO = re.compile(r"帯なし|帯無し|(?i:without obi|no obi)")
_OBI_BARE_YES = re.compile(r"帯付|帯付き|帯あり|帯有り")
# CDs are graded as a jewel case and a disc, on A / B / C, not the vinyl scale.
# The shop's own CD scale: S sealed, A clean, B generally good, C a little worn, D heavily worn.
_CD_CASE = re.compile(r"(?i)(?:ケース|case)\s*[:：]\s*([SABCD])(?![A-Za-z])")
_CD_DISC = re.compile(r"(?i)(?:ディスク|disc)\s*[:：]\s*([SABCD])(?![A-Za-z])")
_SIDE_GRADE = re.compile(
    rf"(?i)\bside\s*[ab12]\s*[:：]\s*({_GRADE_VALUE})(?!\w)"
)
_SIDE_LINE = re.compile(
    r"(?is)\bside\s*([ab12])\s*[:：]\s*(.+?)(?="
    r"\s*(?:\bside\s*[ab12]\s*[:：])|"
    r"\s*(?:\b(?:my grading|payment terms|shipping|matrix|run-?out|dead\s*wax|deadwax)\b)|"
    r"$)"
)
_RUNOUT_LINE = re.compile(
    r"(?im)^[ \t]*(?:matrix(?:\s*/\s*run-?out)?|run-?out|dead\s*wax|deadwax)"
    r"\s*[:：]\s*(.+?)\s*$"
)
_CD_INSERT_NO = re.compile(
    r"(?i)インサートなし|ブックレットなし|歌詞カードなし|リーフレットなし|no booklet|no leaflet|no insert"
)
_CD_INSERT_YES = re.compile(
    r"(?i)ブックレット|リーフレット|歌詞カード|booklet|leaflet|インサートに|insert discol"
)
_CD_LETTERS = frozenset({"S", "A", "B", "C", "D"})
_SELLER_COMMENT = re.compile(
    r"(?is)(?:seller\s+notes|comments?|コメント)\s*[:：]\s*(.+?)(?=(?:商品番号|jan)\s*[:：]|$)"
)


# A trailing comma is a pressing note (E-,ST), not part of the grade.
_GRADE_ALIASES = {
    "NM-": "NM",
    "M-": "M",
}


def _normalize_grade(raw: str) -> str | None:
    token = raw.upper().split("/")[0].strip().split()[0].split(",")[0]
    token = token.replace("＋", "+").replace("－", "-").replace("−", "-")
    if token in _GRADE_ALIASES:
        return _GRADE_ALIASES[token]
    for grade in _GRADE_TOKENS:
        if token == grade:
            return grade
    return None


def _part_presence(raw: str) -> bool | None:
    token = raw.strip().strip("“”\"'")
    if _PART_ABSENT.match(token):
        return False
    if _normalize_grade(token) or _PART_PRESENT.match(token):
        return True
    return None


def parse_seller_report(text: Any) -> dict[str, Any]:
    """Read a seller condition report. A lyric sheet is the insert.

    Facerecords states this on the eBay item page (Obi Grading, Sleeve
    Grading, Record Grading). The same shop states it in Japanese on Yahoo
    (帯, ジャケット, 盤), including the comment line under the translation.
    """
    body = clean_text(text)
    if not body:
        return {}
    found: dict[str, Any] = {}
    obi = _OBI_VALUE.search(body)
    if obi:
        presence = _part_presence(obi.group(1))
        if presence is not None:
            found["obi"] = presence
    insert = _INSERT_VALUE.search(body)
    if insert:
        presence = _part_presence(insert.group(1))
        if presence is not None:
            found["insert"] = presence
    poster = _POSTER_VALUE.search(body)
    if poster:
        presence = _part_presence(poster.group(1))
        if presence is not None:
            found["poster"] = presence
    jacket = _COVER_GRADE.search(body)
    if jacket:
        grade = _normalize_grade(jacket.group(1))
        if grade:
            found["cover"] = grade
    disc = _MEDIA_GRADE.search(body)
    if disc:
        grade = _normalize_grade(disc.group(1))
        if grade:
            found["media"] = grade
    comment = _SELLER_COMMENT.search(body)
    if comment:
        noted = stated_completeness("", comment.group(1))
        for key in ("obi", "insert", "poster", "rental", "sealed"):
            if key not in found and key in noted:
                found[key] = noted[key]
    case = _CD_CASE.search(body)
    if case and "cover" not in found:
        found["cover"] = case.group(1).upper()
    cd_disc = _CD_DISC.search(body)
    if cd_disc and "media" not in found:
        found["media"] = cd_disc.group(1).upper()
    if "obi" not in found:
        if _OBI_BARE_NO.search(body):
            found["obi"] = False
        elif _OBI_BARE_YES.search(body):
            found["obi"] = True
    if "insert" not in found:
        if _CD_INSERT_NO.search(body):
            found["insert"] = False
        elif _CD_INSERT_YES.search(body):
            found["insert"] = True
    for key, present in _parts_before_sheet(body).items():
        if key not in found:
            found[key] = present
    side_grades = [
        _normalize_grade(match.group(1))
        for match in _SIDE_GRADE.finditer(body)
    ]
    side_grades = [grade for grade in side_grades if grade]
    if "media" not in found and side_grades and len(set(side_grades)) == 1:
        found["media"] = side_grades[0]
    side_notes: list[str] = []
    for match in _SIDE_LINE.finditer(body):
        rest = re.sub(r"\s+", " ", match.group(2)).strip(" .,")
        grade = _normalize_grade(rest)
        token = rest.split()[0] if rest else ""
        if grade and rest.casefold() != token.casefold():
            side_notes.append(f"Side {match.group(1).upper()}: {rest}")
    if side_notes:
        found["side_notes"] = side_notes
    runout = _RUNOUT_LINE.search(body)
    if runout:
        etched = runout.group(1).strip(" .")
        if etched and _normalize_grade(etched) is None:
            found["matrix"] = etched
    return found


# A related-item title can say 帯付. The sheet is the labeled grade block.
_SHEET_START = re.compile(
    r"(?is)(?:condition details|コンディション詳細|"
    r"sleeve grading|obi grading|record grading|"
    r"record condition\s*[:：]|jacket\s*[:：]|"
    r"ジャケット\s*[:：]|盤質\s*[:：]|盤面\s*[:：]|帯\s*[:：]|"
    r"ケース\s*[:：]|ディスク\s*[:：]|(?<![A-Za-z])(?:case|disc)\s*[:：])"
)


def _parts_before_sheet(body: str) -> dict[str, bool]:
    """A short condition line such as *ORIGINAL OBI INSERT*, ahead of the grade sheet.

    The labeled grades already decided a part. This only fills a part the
    sheet did not mention. Used and Pre-Owned are not grades and not parts.
    """
    sheet = _SHEET_START.search(body)
    preamble = body[: sheet.start()] if sheet else body
    if not preamble.strip():
        return {}
    noted = stated_completeness("", preamble)
    return {key: noted[key] for key in ("obi", "insert", "poster") if key in noted}


def condition_sheet_text(text: Any) -> str | None:
    """The condition sheet from a listing page, when it states grades or parts."""
    body = clean_text(text)
    start = _SHEET_START.search(body) if body else None
    if start is None:
        return None
    sheet = body[start.start() : start.start() + 1800]
    report = parse_seller_report(sheet)
    if not any(key in report for key in ("cover", "media", "obi", "insert", "poster")):
        return None
    return sheet.strip()


def seller_condition_summary(text: Any) -> str:
    """Short line for the form. E- stays E-."""
    report = parse_seller_report(text)
    parts: list[str] = []
    cd_scale = report.get("cover") in _CD_LETTERS or report.get("media") in _CD_LETTERS
    if report.get("cover"):
        parts.append(
            f"{'Jewel case' if cd_scale else 'Jacket'} {report['cover']}"
        )
    if report.get("media"):
        parts.append(
            f"{'Disc' if cd_scale else 'Record'} {report['media']}"
        )
    if report.get("obi") is True:
        parts.append("with obi")
    elif report.get("obi") is False:
        parts.append("no obi")
    if report.get("insert") is True:
        parts.append("with booklet" if cd_scale else "with lyric sheet")
    elif report.get("insert") is False:
        parts.append("no booklet" if cd_scale else "no lyric sheet")
    return ", ".join(parts)


def catalog_reference(notes: Any, title: Any) -> dict[str, str]:
    """Which parts this catalog includes. A sticker belongs to a rental copy."""
    stated = stated_completeness(notes, title)
    included: list[str] = []
    if stated.get("obi"):
        included.append("obi")
    if stated.get("insert"):
        included.append("insert")
    poster = ""
    if stated.get("poster") is True:
        poster = "included"
        included.append("poster")
    elif included:
        poster = "not_included"
    if not included:
        return {"caption": "", "poster": poster}
    if len(included) == 1:
        names = included[0]
    else:
        names = ", ".join(included[:-1]) + " and " + included[-1]
    caption = f"This catalog includes {names}."
    if poster == "not_included":
        caption += " Poster is not part of it."
    caption += " Insert is the lyric sheet."
    caption += " A rental copy carries its own sticker."
    return {"caption": caption, "poster": poster}


def _is_seven_inch(media: Any) -> bool:
    return clean_text(media).upper() in {"EP_7_INCH", "7_INCH"}


def _is_cd(media: Any) -> bool:
    return clean_text(media).upper() in {
        "CD",
        "CD_BOX_SET",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
        "CD_SINGLE_8CM",
    }


def _sleeve_caption(
    caption: str,
    stated: dict[str, bool],
    report: dict[str, Any],
    media: Any,
    image: Any,
) -> str:
    """A pictured 7" sleeve is the lyric sheet, when the report did not already say so."""
    if stated.get("insert") is not True or report.get("insert") is True:
        return caption
    if not _is_seven_inch(media) or not clean_text(image):
        return caption
    blob = caption.casefold()
    if "lyric" in blob or "insert" in blob:
        return caption
    sentence = "The sleeve photo includes the lyric sheet"
    if not caption:
        return sentence + "."
    return caption.rstrip(".") + ". " + sentence + "."


def _is_cassette(media: Any) -> bool:
    text = clean_text(media)
    if text.casefold() in {"cassette", "cassette box set"}:
        return True
    return text.upper() in CASSETTE_MEDIA


def obi_for_region(region: Any) -> bool:
    """An obi is the strip on a Japanese pressing. Other markets do not have one."""
    return clean_text(region) == "Japan"


def obi_label_for_region(label: str, region: Any) -> str:
    """A Hong Kong, Taiwan, or other set region never counts as having an obi."""
    if obi_for_region(region):
        return label
    if clean_text(region) and clean_text(region) != "Automatic / unset":
        return "No"
    if label == "Yes":
        return "No"
    return label


def obi_value_for_region(value: bool | None, region: Any) -> bool | None:
    """Saving a non-Japanese pressing stores obi as No."""
    named = clean_text(region)
    if named and named != "Automatic / unset" and not obi_for_region(named):
        return False
    return value


def market_catalog_parts(parts: set[str], region: Any) -> set[str]:
    """Drop obi from a catalog list when this copy is not a Japanese pressing."""
    if obi_for_region(region) or "obi" not in parts:
        return parts
    if not clean_text(region) or clean_text(region) == "Automatic / unset":
        return parts
    return {name for name in parts if name != "obi"}


def _obi_only_in_japan(
    stated: dict[str, bool],
    region: Any,
    report: dict[str, Any] | None = None,
) -> None:
    """A Hong Kong or Taiwan copy does not carry an obi, even if the notes mention one."""
    if obi_for_region(region):
        return
    if not clean_text(region) or clean_text(region) == "Automatic / unset":
        return
    stated["obi"] = False
    if report is not None:
        report.pop("obi", None)


def _cassette_defaults(stated: dict[str, bool], media: Any) -> None:
    """A cassette includes the lyric card. It has no obi and no poster.

    A seller note that already says otherwise is left as stated.
    """
    if not _is_cassette(media):
        return
    if "obi" not in stated:
        stated["obi"] = False
    if "poster" not in stated:
        stated["poster"] = False
    if "insert" not in stated:
        stated["insert"] = True
    if "rental" not in stated:
        stated["rental"] = False
    if stated.get("rental") is not True and "sticker" not in stated:
        stated["sticker"] = False


def _cassette_caption(caption: str, media: Any) -> str:
    if not _is_cassette(media):
        return caption
    if "lyric card" in caption.casefold():
        return caption
    sentence = "A cassette includes a lyric card. Obi and poster are not part of it"
    if not caption:
        return sentence + "."
    return caption.rstrip(".") + ". " + sentence + "."


def _seven_inch_insert_from_sleeve(stated: dict[str, bool], media: Any, image: Any) -> None:
    """A pictured 7" sleeve includes the lyric sheet, unless the report says it does not."""
    if not _is_seven_inch(media) or not clean_text(image):
        return
    if stated.get("insert") is False:
        return
    stated["insert"] = True


RECENT_CHANGE_DAYS = 7


_ADJUSTED_FIELDS = (
    "manual_media_type",
    "manual_catalog_number",
    "manual_region",
    "manual_disc_count",
    "manual_pressing_type",
    "manual_pressing_group",
    "manual_condition_media",
    "manual_condition_cover",
    "manual_obi",
    "manual_insert_present",
    "manual_poster_present",
    "manual_sealed",
    "manual_completeness_notes",
    "manual_collector_notes",
    "manual_verdict",
    "manual_importance_score",
    "manual_bulk_lot",
)
PROGRESS_TOUCHED = "Touched"
PROGRESS_ADJUSTED = "Adjusted"
PROGRESS_PROCESSED = "Processed"
PROGRESS_NOT_DONE = "Not done"
LOT_PROGRESS_ALL = "All"


def _field_present(value: Any) -> bool:
    if is_missing(value):
        return False
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


def review_progress(row: Any) -> tuple[str, str, str]:
    """Glyph, filter name, and hover line for one listing.

    Touched is the default once a row has been opened or saved.
    Adjusted means a field was edited. Processed means the identity
    is filled. A blank row has not been touched.
    """
    getter = row.get if hasattr(row, "get") else lambda _name, default=None: default
    adjusted = any(_field_present(_row_value(row, name)) for name in _ADJUSTED_FIELDS)
    filled = clean_text(_row_value(row, "identity_status")) in {
        "filled_auto",
        "filled_manual",
    }
    touched = any(
        _field_present(getter(name))
        for name in (
            "collector_updated_at",
            "identity_status_changed_at",
            "identity_filled_at",
            "seller_report_updated_at",
        )
    )
    if filled:
        detail = "Processed. Edited" if adjusted else "Processed"
        return "✓", PROGRESS_PROCESSED, detail
    if adjusted:
        return "✎", PROGRESS_ADJUSTED, "Edited"
    if touched:
        return "●", PROGRESS_TOUCHED, "Touched"
    return "", "", ""


def recent_change_facts(
    stamps: list[tuple[str, Any]],
    *,
    now: Any = None,
) -> tuple[str, str, pd.Timestamp | None]:
    """The week mark, the hover line, and the latest change time."""
    moment = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if moment.tzinfo is None:
        moment = moment.tz_localize("UTC")
    else:
        moment = moment.tz_convert("UTC")
    latest = None
    label = ""
    for name, value in stamps:
        if is_missing(value):
            continue
        stamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(stamp):
            continue
        if latest is None or stamp > latest:
            latest = stamp
            label = name
    if latest is None or moment - latest > pd.Timedelta(days=RECENT_CHANGE_DAYS):
        return "", "", None
    shown = latest.strftime("%d %b %Y").lstrip("0")
    return "●", f"{label} {shown}", latest


def recent_change_mark(
    stamps: list[tuple[str, Any]],
    *,
    now: Any = None,
) -> tuple[str, str]:
    """A mark on a row that changed in the last week, and the date for the hover."""
    mark, detail, _when = recent_change_facts(stamps, now=now)
    return mark, detail


def _seal_and_rental(stated: dict[str, bool], report: dict[str, Any]) -> None:
    """Sealed is No unless the listing says so. A rental copy has its sticker."""
    if report.get("rental") is True:
        stated["rental"] = True
    if report.get("sealed") is True:
        stated["sealed"] = True
    if stated.get("rental") is True:
        stated["sticker"] = True
    if stated.get("sealed") is not True:
        stated["sealed"] = False


def _merge_report_parts(
    stated: dict[str, bool],
    report: dict[str, Any],
    media: Any,
    catalog_poster: str,
) -> tuple[dict[str, bool], str]:
    """Seller report wins for this copy. A poster the catalog never included stays unset."""
    for key in ("obi", "insert", "poster"):
        if key in report:
            stated[key] = bool(report[key])
    poster = catalog_poster
    if report.get("poster") is True:
        poster = "included"
    elif report.get("poster") is False and poster != "included":
        stated.pop("poster", None)
        if _is_seven_inch(media):
            poster = "not_included"
    elif _is_seven_inch(media) and poster != "included":
        poster = "not_included"
    return stated, poster


def _copy_caption(catalog_caption: str, report: dict[str, Any], media: Any) -> str:
    """Say what the catalog includes and what the seller report already answered."""
    parts: list[str] = []
    if catalog_caption:
        text = catalog_caption
        if report.get("poster") is True:
            text = text.replace(" Poster is not part of it.", "")
        parts.append(text.rstrip("."))
    elif _is_seven_inch(media) and report.get("poster") is not True:
        parts.append('Poster is not part of this 7" single')
        parts.append("Insert is the lyric sheet")
    blob = " ".join(parts).casefold()
    if report.get("obi") is False and "no obi" not in blob:
        parts.append("The seller report says there is no obi")
    elif report.get("obi") is True and "obi" not in blob:
        parts.append("The seller report includes an obi")
    if report.get("insert") is False and "lyric" not in blob and "booklet" not in blob:
        parts.append(
            "The seller report says there is no booklet"
            if _is_cd(media)
            else "The seller report says there is no lyric sheet"
        )
    elif report.get("insert") is True and "insert" not in blob and "lyric" not in blob:
        parts.append(
            "The seller report includes a booklet"
            if _is_cd(media)
            else "The seller report includes a lyric sheet"
        )
    if report.get("poster") is True and "poster" not in blob:
        parts.append("The seller report includes a poster")
    if not parts:
        return ""
    if not any("rental copy" in part for part in parts):
        parts.append("A rental copy carries its own sticker")
    return ". ".join(part.rstrip(".") for part in parts) + "."


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _positive_catalog_parts(notes: Any, title: Any, seller: Any) -> set[str]:
    """Parts the catalog includes. A missing part on one copy does not remove it."""
    stated = stated_completeness(notes, title)
    report = parse_seller_report(seller)
    parts: set[str] = set()
    for key in ("obi", "insert", "poster"):
        if stated.get(key) is True or report.get(key) is True:
            parts.add(key)
    return parts


def _disc_and_jacket(media: Any) -> list[str]:
    named = clean_text(media).upper()
    if named in CD_MEDIA:
        return ["jewel case", "disc"]
    if named in LP_MEDIA or named in SEVEN_INCH_MEDIA or named == "VINYL":
        return ["sleeve", "record"]
    return []


def copy_status_label(parts: set[str], stated: dict[str, bool]) -> str:
    """Complete, missing a catalog part, or the listing never said."""
    order = ("obi", "insert", "poster")
    labels = {"obi": "obi", "insert": "lyric sheet", "poster": "poster"}
    included = [key for key in order if key in parts]
    if not included:
        return ""
    missing = [labels[key] for key in included if stated.get(key) is False]
    unstated = [labels[key] for key in included if key not in stated]
    if not missing and not unstated:
        return "Complete"
    if missing and not unstated:
        return "Missing " + _join_names(missing)
    if unstated and not missing and len(unstated) == len(included):
        return "Not stated"
    bits: list[str] = []
    if missing:
        bits.append("Missing " + _join_names(missing))
    if unstated:
        phrase = _join_names(unstated) + " not stated"
        if not bits:
            phrase = phrase[:1].upper() + phrase[1:]
        bits.append(phrase)
    return "; ".join(bits)


def pressing_copy_caption(parts: set[str], stated: dict[str, bool], media: Any) -> str:
    """Catalog reference, then whether this copy has those parts."""
    extras = [name for name in ("obi", "insert", "poster") if name in parts]
    base = _disc_and_jacket(media)
    sentences: list[str] = []
    if extras:
        sentences.append("This catalog includes " + _join_names(extras))
    if base:
        verb = "is" if len(base) == 1 else "are"
        sentences.append("The " + _join_names(base) + f" {verb} part of it")
    if "insert" in parts:
        sentences.append(
            "Insert is the booklet" if _is_cd(media) else "Insert is the lyric sheet"
        )
    if extras and "poster" not in parts:
        sentences.append("Poster is not part of it")
    status = copy_status_label(parts, stated)
    if status == "Complete":
        sentences.append("This copy is complete")
    elif status == "Not stated":
        sentences.append("This listing does not say whether those parts are here")
    elif status.startswith("Missing ") and " not stated" not in status:
        sentences.append("This copy is missing " + status[len("Missing ") :])
    elif status:
        sentences.append(status[:1].upper() + status[1:])
    sentences.append("A rental copy carries its own sticker")
    return ". ".join(sentences) + "."


def apply_pressing_copy_facts(
    listings: pd.DataFrame,
    pressings: pd.DataFrame,
) -> pd.DataFrame:
    """Fill pressing type and completeness from the press date and notes."""
    frame = listings.copy()
    if frame.empty or pressings.empty or "pressing_id" not in frame.columns:
        return frame
    facts = pressings.copy()
    facts["pressing_id"] = [safe_int(value) for value in facts["id"]]
    facts["release_year_num"] = pd.to_numeric(facts["release_year"], errors="coerce")
    facts["media_key"] = [
        media_press_key(media, detail)
        for media, detail in zip(
            facts.get("media_type", pd.Series(dtype=str)),
            facts.get("format_detail", pd.Series(dtype=str)),
            strict=False,
        )
    ]
    facts["promo"] = [
        pressing_is_promo(generation, detail)
        for generation, detail in zip(
            facts.get("generation", pd.Series(dtype=str)),
            facts.get("format_detail", pd.Series(dtype=str)),
            strict=False,
        )
    ]
    facts["reissue"] = [
        pressing_is_reissue(generation, detail)
        for generation, detail in zip(
            facts.get("generation", pd.Series(dtype=str)),
            facts.get("format_detail", pd.Series(dtype=str)),
            strict=False,
        )
    ]
    eligible = facts[
        ~facts["promo"]
        & ~facts["reissue"]
        & facts["release_year_num"].notna()
        & facts["discogs_master_id"].notna()
    ]
    earliest: dict[tuple[Any, str], int] = {}
    if not eligible.empty:
        grouped = eligible.groupby(
            ["discogs_master_id", "media_key"],
            dropna=False,
        )["release_year_num"].min()
        for key, year in grouped.items():
            master_key = safe_int(key[0])
            if master_key is None:
                continue
            earliest[(master_key, str(key[1]))] = int(year)

    by_id = (
        facts.loc[facts["pressing_id"].map(lambda value: value is not None)]
        .set_index("pressing_id")
    )
    type_column = (
        "effective_pressing_type"
        if "effective_pressing_type" in frame.columns
        else None
    )
    completeness_columns = {
        "obi": "effective_obi",
        "insert": "effective_insert_present",
        "poster": "effective_poster_present",
        "sticker": "effective_sticker",
        "sealed": "effective_sealed",
        "rental": "effective_rental",
    }
    types: list[Any] = []
    stated_rows: list[dict[str, bool]] = []
    captions: list[str] = []
    statuses: list[str] = []
    poster_reference: list[str] = []
    cover_grades: list[Any] = []
    media_grades: list[Any] = []
    titles = frame["title"] if "title" in frame.columns else [""] * len(frame)
    seller_text = (
        frame["seller_report_text"]
        if "seller_report_text" in frame.columns
        else [""] * len(frame)
    )
    stored_media = (
        frame["media_type"] if "media_type" in frame.columns else [""] * len(frame)
    )
    if "effective_media_type" in frame.columns:
        media_values = [
            clean_text(effective) or clean_text(stored)
            for effective, stored in zip(
                frame["effective_media_type"],
                stored_media,
                strict=False,
            )
        ]
    else:
        media_values = stored_media
    images = frame["image_url"] if "image_url" in frame.columns else [""] * len(frame)
    regions = (
        frame["effective_region"]
        if "effective_region" in frame.columns
        else [""] * len(frame)
    )
    included_by_pressing: dict[int, set[str]] = {}
    for pressing_id, title, seller in zip(
        frame["pressing_id"],
        titles,
        seller_text,
        strict=False,
    ):
        pressing_key = safe_int(pressing_id)
        if pressing_key is None:
            continue
        notes = ""
        if pressing_key in by_id.index:
            fact = by_id.loc[pressing_key]
            if isinstance(fact, pd.DataFrame):
                fact = fact.iloc[0]
            notes = fact.get("notes")
        included_by_pressing.setdefault(pressing_key, set()).update(
            _positive_catalog_parts(notes, title, seller)
        )

    def _row_caption(
        pressing_key: int | None,
        stated: dict[str, bool],
        report: dict[str, Any],
        media: Any,
        image: Any,
        fallback: str,
        pressing_media: Any = "",
        region: Any = "",
    ) -> tuple[str, str]:
        parts = market_catalog_parts(
            (
                included_by_pressing.get(pressing_key, set())
                if pressing_key is not None
                else set()
            ),
            region,
        )
        named = clean_text(media) or clean_text(pressing_media)
        if parts:
            caption = pressing_copy_caption(parts, stated, named)
        else:
            caption = _copy_caption(fallback, report, media)
        caption = _cassette_caption(caption, named or media)
        return (
            _sleeve_caption(caption, stated, report, media, image),
            copy_status_label(parts, stated),
        )

    for pressing_id, title, current, seller, media, image, region in zip(
        frame["pressing_id"],
        titles,
        frame[type_column] if type_column else [None] * len(frame),
        seller_text,
        media_values,
        images,
        regions,
        strict=False,
    ):
        pressing_key = safe_int(pressing_id)
        fact = None
        if pressing_key is not None and pressing_key in by_id.index:
            fact = by_id.loc[pressing_key]
            if isinstance(fact, pd.DataFrame):
                fact = fact.iloc[0]
        if fact is None:
            types.append(current)
            stated = stated_completeness("", title)
            stated.pop("sticker", None)
            if stated.get("poster") is False:
                stated.pop("poster")
            reference = catalog_reference("", title)
            report = parse_seller_report(f"{title}\n{seller}")
            parts = (
                included_by_pressing.get(pressing_key, set())
                if pressing_key is not None
                else set()
            )
            poster_source = (
                ("included" if "poster" in parts else "not_included")
                if parts
                else reference["poster"]
            )
            stated, poster = _merge_report_parts(
                stated,
                report,
                media,
                poster_source,
            )
            _seven_inch_insert_from_sleeve(stated, media, image)
            _seal_and_rental(stated, report)
            _cassette_defaults(stated, media)
            _obi_only_in_japan(stated, region, report)
            stated_rows.append(stated)
            caption, status = _row_caption(
                pressing_key,
                stated,
                report,
                media,
                image,
                reference["caption"],
                region=region,
            )
            captions.append(caption)
            statuses.append(status)
            poster_reference.append(poster)
            cover_grades.append(report.get("cover"))
            media_grades.append(report.get("media"))
            continue
        master = safe_int(fact.get("discogs_master_id"))
        media_key = fact.get("media_key")
        earliest_year = None
        if master is not None:
            earliest_year = earliest.get((master, str(media_key)))
        listing_text = "\n".join(
            part
            for part in (clean_text(title), clean_text(seller))
            if part
        )
        decided = date_pressing_type(
            generation=fact.get("generation"),
            format_detail=fact.get("format_detail"),
            release_year=fact.get("release_year"),
            earliest_year=earliest_year,
            title=listing_text,
        )
        current_text = clean_text(current).upper()
        if decided and current_text in {"", "STANDARD"}:
            types.append(decided)
        else:
            types.append(current)
        stated = stated_completeness(fact.get("notes"), title)
        stated.pop("sticker", None)
        if stated.get("poster") is False:
            stated.pop("poster")
        report = parse_seller_report(f"{title}\n{seller}")
        reference = catalog_reference(fact.get("notes"), title)
        parts = included_by_pressing.get(pressing_key, set()) if pressing_key is not None else set()
        poster_source = (
            ("included" if "poster" in parts else "not_included")
            if parts
            else reference["poster"]
        )
        stated, poster = _merge_report_parts(
            stated,
            report,
            media,
            poster_source,
        )
        _seven_inch_insert_from_sleeve(stated, media, image)
        _seal_and_rental(stated, report)
        _cassette_defaults(
            stated,
            clean_text(media) or clean_text(fact.get("media_type")),
        )
        _obi_only_in_japan(stated, region, report)
        stated_rows.append(stated)
        caption, status = _row_caption(
            pressing_key,
            stated,
            report,
            clean_text(media) or clean_text(fact.get("media_type")),
            image,
            reference["caption"],
            fact.get("media_type"),
            region,
        )
        captions.append(caption)
        statuses.append(status)
        poster_reference.append(poster)
        cover_grades.append(report.get("cover"))
        media_grades.append(report.get("media"))
    if type_column:
        frame[type_column] = types
    for key, column in completeness_columns.items():
        if column not in frame.columns:
            continue
        filled = []
        for current, stated in zip(frame[column], stated_rows, strict=False):
            if is_missing(current) and key in stated:
                filled.append(stated[key])
            else:
                filled.append(current)
        frame[column] = filled
    if "effective_rental" in frame.columns and "effective_sticker" in frame.columns:
        frame["effective_sticker"] = [
            True
            if not is_missing(rental) and as_boolean(rental)
            else False
            if not is_missing(rental)
            else sticker
            for rental, sticker in zip(
                frame["effective_rental"],
                frame["effective_sticker"],
                strict=False,
            )
        ]
    frame["catalog_completeness"] = captions
    frame["catalog_poster"] = poster_reference
    frame["copy_status"] = statuses
    manual_for_grade = {
        "effective_condition_cover": "manual_condition_cover",
        "effective_condition_media": "manual_condition_media",
    }
    for column, grades in (
        ("effective_condition_cover", cover_grades),
        ("effective_condition_media", media_grades),
    ):
        if column not in frame.columns:
            continue
        manual_name = manual_for_grade[column]
        manuals = (
            frame[manual_name]
            if manual_name in frame.columns
            else [None] * len(frame)
        )
        frame[column] = [
            grade if grade and is_missing(manual) else current
            for current, grade, manual in zip(
                frame[column],
                grades,
                manuals,
                strict=False,
            )
        ]
    return frame


def automatic_pressing_type(row: Any, options: tuple[str, ...]) -> str | None:
    """STANDARD is the view default; show it only once a pressing is matched."""
    status = clean_text(_row_value(row, "identity_status")).lower()
    if status not in {"filled_auto", "filled_manual"} and is_missing(
        _row_value(row, "pressing_id")
    ):
        return None
    return _option_choice(_row_value(row, "effective_pressing_type"), options)


def automatic_sale_type(row: Any, options: tuple[str, ...]) -> str | None:
    for name in ("auction_format", "sale_type_display"):
        choice = _option_choice(_row_value(row, name), options)
        if choice and choice != "UNKNOWN":
            return choice
    return None


def automatic_pressing_group(row: Any) -> str:
    return clean_text(_row_value(row, "pressing_token"))


def form_choice(manual: Any, automatic: str | None, options: tuple[str, ...]) -> str | None:
    """Manual override when set; otherwise the known automatic fact."""
    chosen = _option_choice(manual, options)
    if chosen:
        return chosen
    if automatic in options:
        return automatic
    return None


def form_text(manual: Any, automatic: str) -> str:
    text = clean_text(manual)
    return text or automatic


def form_disc_count(manual: Any, automatic: int) -> int:
    count = safe_int(manual)
    if count and count > 0:
        return count
    return automatic


def form_flag(row: Any, manual_name: str, effective_name: str) -> Any:
    manual = _row_value(row, manual_name)
    if not is_missing(manual):
        return manual
    return _row_value(row, effective_name)


def keep_manual_choice(submitted: Any, automatic: str | None) -> str | None:
    """Leave NULL when the form is still showing the automatic fact."""
    if is_missing(submitted) or str(submitted) == "Automatic / unset":
        return None
    choice = str(submitted)
    if automatic and choice == automatic:
        return None
    return choice


def keep_manual_text(submitted: Any, automatic: str) -> str | None:
    text = clean_text(submitted)
    if not text:
        return None
    if automatic and text == automatic:
        return None
    return text


def keep_manual_count(submitted: Any, automatic: int) -> int | None:
    count = safe_int(submitted)
    if not count or count <= 0:
        return None
    if automatic and count == automatic:
        return None
    return count


def save_choice(
    submitted: Any,
    automatic: str | None,
    *,
    manual_already: bool,
) -> str | None:
    """Keep an existing override. Do not freeze a prefilled automatic fact."""
    if manual_already:
        if is_missing(submitted) or str(submitted) == "Automatic / unset":
            return None
        return str(submitted)
    return keep_manual_choice(submitted, automatic)


def save_text(submitted: Any, automatic: str, *, manual_already: bool) -> str | None:
    if manual_already:
        return clean_text(submitted) or None
    return keep_manual_text(submitted, automatic)


def save_count(submitted: Any, automatic: int, *, manual_already: bool) -> int | None:
    if manual_already:
        count = safe_int(submitted)
        if not count or count <= 0:
            return None
        return count
    return keep_manual_count(submitted, automatic)


def save_flag(
    submitted: bool | None,
    automatic: Any,
    *,
    manual_already: bool,
) -> bool | None:
    if manual_already:
        return submitted
    return keep_manual_flag(submitted, automatic)


def keep_manual_flag(submitted: bool | None, automatic: Any) -> bool | None:
    if submitted is None:
        return None
    if is_missing(automatic):
        return submitted
    if bool(submitted) == as_boolean(automatic):
        return None
    return submitted


def as_boolean(value: Any) -> bool:
    """Normalize common boolean representations."""
    if isinstance(value, bool):
        return value

    if is_missing(value):
        return False

    return str(value).strip().lower() in {
        "1",
        "true",
        "t",
        "yes",
        "y",
    }


def normalize_pressing_token(value: Any) -> str:
    """Normalize catalog or matrix text into a stable grouping token."""
    text = clean_text(value).upper()

    if not text:
        return ""

    tokens: list[str] = []

    for match in CATALOG_PATTERN.finditer(text):
        token = re.sub(
            r"[^A-Z0-9]",
            "",
            match.group(0).upper(),
        )

        if token.isdigit() and len(token) < 6:
            continue

        if token and token not in tokens:
            tokens.append(token)

    if tokens:
        return "|".join(tokens[:4])

    fallback = re.sub(
        r"[^A-Z0-9]",
        "",
        text,
    )

    if len(fallback) < 4:
        return ""

    return fallback[:80]


def _identity_module():
    """Load Discogs helpers, reloading if Streamlit cached a stale module."""
    module = discogs_identity
    extract = getattr(module, "extract_release_year", None)
    junk = getattr(module, "is_junk_catalog", None)
    artist_key = getattr(module, "canonical_artist_key", None)
    if (
        extract is None
        or junk is None
        or artist_key is None
        or not junk("SEP-23")
    ):
        module = importlib.reload(module)
        globals()["discogs_identity"] = module
    return module


def extract_release_year(title: Any) -> int | None:
    """Year of the copy for sale: 復刻 year when marked, else original 19xx年."""
    return _identity_module().extract_release_year(title)


def display_release_year(
    *,
    pressing_year: Any = None,
    title: Any = None,
    listing_year: Any = None,
) -> int | None:
    """Show the copy's year, not a leftover Discogs reissue year."""
    module = _identity_module()
    claimed = module.extract_release_year(title)
    stored: int | None = None
    for raw in (pressing_year, listing_year):
        try:
            if raw is None or str(raw).strip() == "":
                continue
            stored = int(str(raw).strip()[:4])
            break
        except (TypeError, ValueError):
            continue
    if claimed is None:
        if stored is not None and stored >= 2025:
            return None
        return stored
    if stored is None:
        return claimed
    if module.listing_wants_original_pressing(str(title or "")) and stored >= claimed + 8:
        return claimed
    return stored


def _catalog_helpers():
    """Load catalog helpers, reloading if Streamlit cached a stale module."""
    module = _identity_module()
    return module.catalog_token, module.fold_catalog, module.is_junk_catalog


def display_listing_catalog(*, stored: Any, title: Any) -> str:
    """Show a real catno; never an eBay sold date or price SKU."""
    module = _identity_module()
    catalog_token, _fold, is_junk_catalog = (
        module.catalog_token,
        module.fold_catalog,
        module.is_junk_catalog,
    )
    text = clean_text(title)
    stored_text = clean_text(stored)
    leftover_reissue = module.listing_wants_original_pressing(
        text
    ) and module.is_modern_reissue_catalog(stored_text)
    if (
        stored_text
        and not leftover_reissue
        and not is_junk_catalog(stored_text, title=text or None)
    ):
        return stored_text
    hint = catalog_token(title=text or None) or ""
    if hint and not is_junk_catalog(hint, title=text or None):
        return hint
    return ""


def display_matrix_catalog(
    *,
    stored_catalog: Any,
    stored_matrix: Any,
    title: Any,
) -> str:
    """Show catalog, then Discogs matrix runouts when they add information."""
    catalog = display_listing_catalog(stored=stored_catalog, title=title)
    matrix = clean_text(stored_matrix)
    if catalog and matrix:
        catalog_token, fold_catalog, _junk = _catalog_helpers()
        if fold_catalog(catalog) == fold_catalog(matrix):
            return catalog
        return f"{catalog} · {matrix}"
    return catalog or matrix


def _media_helpers():
    """Load media helpers, reloading if Streamlit cached a stale module."""
    import importlib

    import auction_etl.classifiers.media as module

    if not hasattr(module, "is_job_lot"):
        module = importlib.reload(module)
    return module.classify_media_details, module.is_job_lot


def derive_pressing_group_key(row: Any) -> str:
    """Group by Discogs pressing when known; else canonical artist + catalog."""
    if bool(row.get("job_lot")) and not str(row.get("pressing_override") or "").strip():
        return ""
    discogs = row.get("discogs_release_id")
    try:
        if discogs is not None and str(discogs).strip() not in {"", "nan", "None"}:
            return f"D{int(float(discogs))}"
    except (TypeError, ValueError):
        pass
    token = str(row.get("pressing_token") or "").strip()
    if not token:
        return ""
    artist = _identity_module().canonical_artist_key(
        str(row.get("artist_display") or "")
    )
    media = str(row.get("media_display") or "").strip().upper()
    return "|".join(part for part in (artist, media, token) if part)


def derive_pressing_token(
    *,
    override: Any,
    catalog_number: Any,
    title: Any,
) -> str:
    """Resolve a catalog token; never mint one from a title fragment.

    Discogs imports stay inside this function so Streamlit can load this
    module while ``app.collector_review`` is still executing as ``__main__``.
    """
    catalog_token, fold_catalog, _junk = _catalog_helpers()
    token = catalog_token(
        catalog_number=clean_text(override) or clean_text(catalog_number) or None,
        title=clean_text(title) or None,
    )
    return fold_catalog(token) if token else ""


def derive_sale_type(
    *,
    manual_value: Any,
    title: Any,
    starting_price: Any,
    bid_count: Any,
    buyout_price: Any,
    stored_format: Any = None,
) -> str:
    """Classify the commercial sale format."""
    manual = clean_text(
        manual_value
    ).upper()

    if manual:
        return manual

    stored = clean_text(
        stored_format
    ).upper().replace("-", "_").replace(" ", "_")

    if stored and stored not in {
        "UNKNOWN",
        "UNSPECIFIED",
        "NONE",
    }:
        return stored

    normalized_title = clean_text(
        title
    ).lower()

    bids = safe_int(
        bid_count
    ) or 0

    starting = safe_float(
        starting_price
    )

    buyout = safe_float(
        buyout_price
    )

    if re.search(
        r"\bobo\b|best offer|or best offer",
        normalized_title,
    ):
        return "FIXED_PRICE_OBO"

    if bids > 0 or starting is not None:
        return "AUCTION"

    if buyout is not None:
        return "FIXED_PRICE"

    return "UNKNOWN"

def _recorded_bid_count(frame: pd.DataFrame) -> pd.Series:
    if "bid_count" in frame.columns:
        return pd.to_numeric(frame["bid_count"], errors="coerce")
    if "bid_count_display" in frame.columns:
        return pd.to_numeric(frame["bid_count_display"], errors="coerce")
    return pd.Series(pd.NA, index=frame.index, dtype="Float64")


def _offer_group_key(frame: pd.DataFrame) -> pd.Series:
    """Same seller and pressing. A blank pressing does not glue rows together."""
    group_name = (
        "pressing_group_key"
        if "pressing_group_key" in frame.columns
        else "pressing_token"
    )
    tokens = (
        frame[group_name].map(clean_text)
        if group_name in frame.columns
        else pd.Series("", index=frame.index)
    )
    sellers = (
        frame["seller"].map(clean_text)
        if "seller" in frame.columns
        else pd.Series("", index=frame.index)
    )
    return sellers.str.casefold() + "\n" + tokens


def omit_no_bid_auctions(frame: pd.DataFrame) -> pd.DataFrame:
    """A recorded 0 bids is not a sale.

    A blank bid count is a fixed-price purchase or an unknown auction, so it
    stays. Relists with 0 bids still count: Cycles is how many times that
    seller offered the pressing, and Days to sell runs from the first no-bid
    offer that opened before the sale closed.
    """
    if frame.empty or "sale_type_display" not in frame.columns:
        return frame
    bids = _recorded_bid_count(frame)
    no_bid = bids.eq(0)
    held = int(no_bid.sum())
    offer_keys = _offer_group_key(frame)
    tokens = offer_keys.map(lambda key: key.split("\n", 1)[-1])
    cycles = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    days = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    if held and bool(tokens.ne("").any()):
        opened = pd.to_datetime(
            frame["opening_display"] if "opening_display" in frame.columns else None,
            utc=True,
            errors="coerce",
        )
        closed = pd.to_datetime(
            frame["closing_display"] if "closing_display" in frame.columns else None,
            utc=True,
            errors="coerce",
        )
        work = pd.DataFrame(
            {
                "token": offer_keys,
                "no_bid": no_bid,
                "opened": opened,
                "closed": closed,
            },
            index=frame.index,
        )
        work = work.loc[~work["token"].str.endswith("\n")]
        for _token, group in work.groupby("token", sort=False):
            failed_rows = group.loc[group["no_bid"]]
            if failed_rows.empty:
                continue
            cycle_count = int(len(group))
            failed_opens = failed_rows["opened"]
            for idx, row in group.iterrows():
                if bool(row["no_bid"]):
                    continue
                cycles.loc[idx] = cycle_count
                end = row["closed"]
                if pd.isna(end):
                    continue
                earlier = failed_opens[failed_opens.notna() & (failed_opens <= end)]
                if earlier.empty:
                    continue
                start = earlier.min()
                own_open = row["opened"]
                if pd.notna(own_open) and own_open <= end:
                    start = min(start, own_open)
                days.loc[idx] = int((end - start).total_seconds() // 86400)
    frame = frame.copy()
    frame["no_bid_auction"] = no_bid.to_numpy()
    frame["listing_cycles"] = cycles.astype("Int64")
    frame["days_to_sell"] = days.astype("Int64")
    frame["held_out_auctions"] = held
    return frame


def sales_without_no_bid_auctions(frame: pd.DataFrame) -> pd.DataFrame:
    """Listings that count as sales. An auction needs at least one bid."""
    if frame.empty or "no_bid_auction" not in frame.columns:
        return frame
    kept = frame.loc[~frame["no_bid_auction"].fillna(False).astype(bool)].copy()
    return kept.reset_index(drop=True)


def no_bid_auction_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """0-bid offers with no sale yet. A chain that sold is that sale's history.

    One row per seller and pressing. A fixed-price purchase is not in this
    pile, because a purchase does not record 0 bids.
    """
    if frame.empty or "no_bid_auction" not in frame.columns:
        return frame.iloc[0:0].copy()
    held = frame.loc[frame["no_bid_auction"].fillna(False).astype(bool)].copy()
    if held.empty:
        return held.reset_index(drop=True)
    offer_keys = _offer_group_key(frame)
    sale_keys = set(
        offer_keys.loc[~frame["no_bid_auction"].fillna(False).astype(bool)]
    )
    sale_keys.discard("\n")
    held_keys = offer_keys.loc[held.index]
    unsold_chain = ~held_keys.isin(sale_keys) | held_keys.str.endswith("\n")
    held = held.loc[unsold_chain].copy()
    if held.empty:
        return held.reset_index(drop=True)
    held_keys = held_keys.loc[held.index]
    grouped = held_keys.ne("") & ~held_keys.str.endswith("\n")
    if not bool(grouped.any()):
        return held.reset_index(drop=True)
    closed = pd.to_datetime(
        held["closing_display"] if "closing_display" in held.columns else None,
        utc=True,
        errors="coerce",
    )
    keep_indexes: list[Any] = list(held.index[~grouped])
    for _key, group in held.loc[grouped].groupby(held_keys.loc[grouped], sort=False):
        order = closed.loc[group.index]
        latest = order.idxmax() if order.notna().any() else group.index[-1]
        keep_indexes.append(latest)
        if "listing_cycles" in held.columns:
            held.loc[latest, "listing_cycles"] = int(len(group))
    return held.loc[keep_indexes].reset_index(drop=True)


def format_chart_bucket(media_display: Any, job_lot: bool = False) -> str:
    """Bucket a listing into the formats the review chart compares."""
    media = clean_text(media_display)
    if media in BULK_LOT_MEDIA:
        return BULK_LOT_MEDIA[media]
    if job_lot or media == "BULK_LOT":
        return "Bulk lot"
    if media_matches_group(media_display, MEDIA_GROUP_SEVEN):
        return '7"'
    if media_matches_group(media_display, MEDIA_GROUP_LP):
        return "LP"
    if media_matches_group(media_display, MEDIA_GROUP_CD):
        return "CD"
    if media_matches_group(media_display, MEDIA_GROUP_CASSETTE):
        return "Cassette"
    return "Other"


def auction_outcome_chart(
    sales: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    """Sales versus 0-bid auctions for 7\", LP, CD, and the other formats."""
    order = (
        '7"',
        "LP",
        "CD",
        "Cassette",
        "LP bulk lot",
        "CD bulk lot",
        "EP bulk lot",
        "Cassette bulk lot",
        "Mixed bulk lot",
        "Magazine bulk lot",
        "Bulk lot",
        "Other",
    )
    sales_counts = _format_bucket_counts(sales)
    history_counts = _format_bucket_counts(history)
    present = [
        name
        for name in order
        if int(sales_counts.get(name, 0)) or int(history_counts.get(name, 0))
    ]
    return pd.DataFrame(
        {
            "Format": present,
            "Sales": [int(sales_counts.get(name, 0)) for name in present],
            "0-bid auctions": [int(history_counts.get(name, 0)) for name in present],
        }
    )


def _format_bucket_counts(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="int64")
    media = (
        frame["media_display"]
        if "media_display" in frame.columns
        else pd.Series("", index=frame.index)
    )
    lots = (
        frame["job_lot"].fillna(False)
        if "job_lot" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    buckets = [
        format_chart_bucket(value, job_lot=bool(lot))
        for value, lot in zip(media, lots, strict=True)
    ]
    return pd.Series(buckets, dtype="object").value_counts()


def listing_identity(
    marketplace: Any,
    listing_id: Any,
) -> str:
    """Return a stable marketplace/listing identity."""
    return (
        f"{clean_text(marketplace).lower()}:"
        f"{clean_text(listing_id)}"
    )


def grid_row_identity(row: Any) -> str | None:
    """Read the listing identity from an AG Grid selected row."""
    if row is None:
        return None
    mapping = row
    if not isinstance(mapping, dict):
        try:
            mapping = dict(mapping)
        except (TypeError, ValueError):
            return None
    value = clean_text(mapping.get("__identity"))
    if value and ":" in value:
        return value
    marketplace = mapping.get("Marketplace", mapping.get("marketplace"))
    listing_id = mapping.get("Listing ID", mapping.get("listing_id"))
    identity = listing_identity(marketplace, listing_id)
    if identity in {"", ":"}:
        return None
    return identity


def _aggrid_event_data(response: Any) -> dict[str, Any] | None:
    """Return the AG Grid event payload, if this response has one."""
    event_data = getattr(response, "event_data", None)
    if event_data is None and isinstance(response, dict):
        event_data = response.get("event_data")
    if isinstance(event_data, dict):
        return event_data
    return None


def _event_row_identity(event_data: dict[str, Any]) -> str | None:
    """Read the clicked row from event data, including the row id."""
    payload = event_data.get("data")
    if not isinstance(payload, dict):
        node = event_data.get("node")
        if isinstance(node, dict):
            nested = node.get("data")
            if isinstance(nested, dict):
                payload = nested
            else:
                node_id = clean_text(node.get("id"))
                if ":" in node_id:
                    return node_id
                payload = None
    if not isinstance(payload, dict):
        return None
    return grid_row_identity(payload)


def _aggrid_selection_ids(response: Any) -> list[str]:
    """Row ids from AG Grid selection state (getRowId = listing identity)."""
    raw = getattr(response, "selected_rows_id", None)
    if raw is None and isinstance(response, dict):
        raw = response.get("selected_rows_id")
    if isinstance(raw, dict):
        raw = (
            raw.get("ids")
            or raw.get("rowIds")
            or raw.get("toggledNodes")
            or raw.get("rowSelection")
        )
    if raw is None:
        return []
    if isinstance(raw, str):
        value = clean_text(raw)
        return [value] if value else []
    if not isinstance(raw, (list, tuple)):
        return []
    return [value for value in (clean_text(item) for item in raw) if value]


def _grid_click_identity(response: Any) -> str | None:
    """Identity for a user click.

    Replacing row data under server_wins emits selectionChanged with
    source rowDataChanged and no selected row. That event must not
    replace the click Streamlit already stored.
    """
    event_data = _aggrid_event_data(response)
    if isinstance(event_data, dict):
        source = clean_text(event_data.get("source"))
        if source in {"rowDataChanged", "api"}:
            return None
        event_identity = _event_row_identity(event_data)
        if event_identity:
            return event_identity

    return _aggrid_selected_identity(response)


def _aggrid_selected_identity(response: Any) -> str | None:
    """Extract one stable identity from an AG Grid response."""
    event_data = _aggrid_event_data(response)
    if isinstance(event_data, dict):
        event_identity = _event_row_identity(event_data)
        if event_identity:
            return event_identity

    for identity in _aggrid_selection_ids(response):
        if ":" in identity:
            return identity

    selected_rows = getattr(response, "selected_rows", None)
    if selected_rows is None and isinstance(response, dict):
        selected_rows = response.get("selected_rows")

    if selected_rows is None:
        return None

    if isinstance(selected_rows, pd.DataFrame):
        if selected_rows.empty:
            return None
        return grid_row_identity(selected_rows.iloc[0])

    if isinstance(selected_rows, dict):
        return grid_row_identity(selected_rows)

    if isinstance(selected_rows, (list, tuple)):
        if not selected_rows:
            return None
        return grid_row_identity(selected_rows[0])

    try:
        selected_frame = pd.DataFrame(selected_rows)
    except (TypeError, ValueError):
        return None

    if selected_frame.empty:
        return None
    return grid_row_identity(selected_frame.iloc[0])


def listing_option_label(
    *,
    marketplace: Any,
    listing_id: Any,
    seller: Any,
    title: Any,
    title_limit: int = 96,
) -> str:
    """Return a concise searchable listing label."""
    clean_title = clean_text(
        title
    )
    clean_seller = clean_text(
        seller
    )

    if (
        title_limit > 1
        and len(clean_title) > title_limit
    ):
        clean_title = (
            clean_title[
                : title_limit - 1
            ].rstrip()
            + "…"
        )

    parts = [
        clean_text(
            marketplace
        ).upper()
        or "UNKNOWN",
        clean_text(
            listing_id
        )
        or "missing ID",
    ]

    if clean_seller:
        parts.append(
            clean_seller
        )

    if clean_title:
        parts.append(
            clean_title
        )

    return " · ".join(
        parts
    )
