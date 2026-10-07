"""Pure Discogs identity matching: tokens, classification, release mapping."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Iterable, Literal, Mapping, Sequence

from auction_etl.services.cjk_text import fold_hanzi


IdentityStatus = Literal[
    "unmatched",
    "needs_review",
    "filled_auto",
    "filled_manual",
]

_CATALOG_IN_TEXT = re.compile(
    r"\b([A-Z]{1,5}[-\s]?\d{2,6}(?:[-/][A-Z0-9]{1,6})?[A-Z]?)\b",
    re.IGNORECASE,
)
_INCH_AFTER_CATALOG = re.compile(
    r"""^[\s]*["'′″インチ]|^[\s]*inch\b""",
    re.IGNORECASE,
)
_PREFIXED_CATALOG_IN_TEXT = re.compile(
    r"\b(\d{1,2}[A-Z]{2,4}[-\s]?\d{2,5}(?:[A-Z])?)\b",
    re.IGNORECASE,
)
_POLYGRAM_SPACED = re.compile(
    r"\b(\d{3})\s+(\d{3})-(\d)\b",
)
_POLYGRAM_MASHED = re.compile(
    r"\b(8\d{2})(\d{3})(\d)\b",
)
_EPIC_JAPAN = re.compile(
    r"\b(\d{2,3}P)[- ]?(\d{3,4})\b",
    re.IGNORECASE,
)
_TAURUS_DOUBLE = re.compile(
    r"\b(\d{2}TR)[- ]?(\d{4})(\d{2})\b",
    re.IGNORECASE,
)
_CATALOG_RANGE_IN_TEXT = re.compile(
    r"\b([A-Z]{2,6}[-\s]?\d{2,6})[~／/](\d{1,4})\b",
    re.IGNORECASE,
)
_CD_STYLE_CATALOG = re.compile(
    r"\b(\d{1,2}CD[- ]?\d{3,5}[A-Z]?)\b",
    re.IGNORECASE,
)
_POLYDOR_JP_CD = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]\d{2}[A-Z])[- ]*(\d{4,6})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_LISTING_LABEL_HINTS = (
    (re.compile(r"stereo\s*sound|ステレオサウンド|ssar-", re.IGNORECASE), "stereo sound"),
    (re.compile(r"(?:taiwan\s+)?space\s+records?|太空唱片|宇宙唱片|yeu\s*jow", re.IGNORECASE), "space record"),
    (re.compile(r"taurus|トーラス", re.IGNORECASE), "taurus"),
    (re.compile(r"polygram|ポリグラム", re.IGNORECASE), "polygram"),
    (re.compile(r"polydor|ポリドール", re.IGNORECASE), "polydor"),
    (re.compile(r"kolin|歌林", re.IGNORECASE), "kolin"),
    (re.compile(r"kuopin", re.IGNORECASE), "kuopin"),
    (re.compile(r"toshiba|東芝", re.IGNORECASE), "toshiba"),
    (re.compile(r"cbs/?sony|ソニー", re.IGNORECASE), "sony"),
    (re.compile(r"life records", re.IGNORECASE), "life records"),
    (re.compile(r"sun\s*light", re.IGNORECASE), "sun light"),
)
_AUDIOPHILE_REISSUE = re.compile(
    r"stereo\s*sound|ステレオサウンド|(?<![A-Z])ssar-|mobile fidelity|\bmofi\b|"
    r"45\s*rpm.{0,50}\bnumbered\b|\bnumbered\b.{0,50}45\s*rpm|"
    r"180\s*g(?:ram)?s?\b|\bnew\s+vinyl\b",
    re.IGNORECASE,
)
_PRESSING_45 = re.compile(r"45\s*rpm", re.IGNORECASE)
_PRESSING_NUMBERED = re.compile(
    r"\bnumbered\b|ナンバリング|编号|編號",
    re.IGNORECASE,
)
_FALSE_LETTER_PREFIXES = frozenset(
    {
        "UP",
        "OF",
        "TO",
        "IN",
        "MY",
        "THE",
        "FOR",
        "AND",
        "OR",
        "ON",
        "AT",
        "BY",
        "NO",
        "SO",
        "AS",
        "BE",
        "WE",
        "IT",
        "IS",
        "ME",
        "US",
        "AN",
        "SIZE",
        "BEST",
        "NEW",
        "ALL",
        "OLD",
        "VOL",
        "SET",
        "BOX",
        "PCS",
        "USB",
        "PRICE",
        "YEN",
        "BID",
        "BIDS",
        "ITEM",
        "SKU",
        "SALE",
        "COST",
        "PLUS",
        "CODE",
        "PAGE",
        "COPY",
        "SONG",
        "SONGS",
        "DISC",
        "THEIR",
        "ALBUM",
        "TENG",
        "TT",
    }
)
_MEDIA_SIZE_CATALOG = re.compile(
    r"^(LP|EP|CD|DVD|LD|VHS|MCS|TAPE|VINYL|STAMP|USB|POSTER)[-\s]?"
    r"(?:7|8|10|12|33|45|78)$",
    re.IGNORECASE,
)
_DECADE_CATALOG = re.compile(
    r"^[A-Z]{2,12}[-\s]?(?:(?:19[4-9]\d|20[0-2]\d)S|[6-9]0S)$",
    re.IGNORECASE,
)
_DIRTY_ARTIST = re.compile(r"\d{8,}|[【\[]")
_BARCODE_ARTIST_PREFIX = re.compile(r"^\d{8,14}\s*[;:／/,]\s*")
_JAN_BARCODE = re.compile(r"\b(?:45|49)\d{11}\b")
_TRAILING_LETTER_SKU = re.compile(
    r"^\d?[A-Z]{2,8}\d{2,8}[A-Z]{2,}$",
    re.IGNORECASE,
)
_BRACKET_INVENTORY_SKU = re.compile(
    r"^\d{3,6}[A-Z]{2,4}$",
    re.IGNORECASE,
)
_YEAR_DIGITS = re.compile(r"^(?:19[4-9]\d|20[0-2]\d)$")
_POLY_SPACED = re.compile(
    r"\b(2[3-4]\d{2})(?:\s+|-)(\d{3})\b",
)
_POLY_FOUR_THREE = re.compile(
    r"\b([1-9]\d{3})\s+(\d{3})\b",
)
_POLY_MASHED = re.compile(
    r"\b(2[3-4]\d{2})(\d{3})\b",
)
_POLY_WRONG_HYPHEN = re.compile(
    r"\b(2[3-4]\d{2})(\d{2})-(\d)\b",
)
_MEDIA_YEAR_CATALOG = re.compile(
    r"^(LP|EP|CD|DVD|LD|VHS|MCS|TAPE|VINYL|STAMP|USB|POSTER)[-\s]?"
    r"(?:19[4-9]\d|20[0-2]\d)$",
    re.IGNORECASE,
)
_SPACE_YEAR_CATALOG = re.compile(
    r"^[A-Z]{2,8}\s+(?:19[4-9]\d|20[0-2]\d)$",
    re.IGNORECASE,
)
_MONTH_DAY_CATALOG = re.compile(
    r"^(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"-?(?:0?[1-9]|[12]\d|3[01])$",
    re.IGNORECASE,
)
_LETTER_NUMBER_CATALOG = re.compile(
    r"^([A-Z0-9]*[A-Z])(\d+)$",
)
_DISCOGS_NUM_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_RANGE_CATNO_TAIL = re.compile(r"[~～〜/](\d{1,4})\s*$")
_JP_CHAR = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_KANA = re.compile(r"[\u3040-\u30ff]")
_JP_ARTIST_HINT = re.compile(r"山口百恵|百恵|テレサ|中森明菜|明菜")
_CINEPOLY_LP = re.compile(r"\bLP[- ]?(\d{4,5})\b", re.IGNORECASE)
_CAPITAL_ARTISTS_CAL = re.compile(
    r"\bCAL[- ]?0?4[- ](\d{4})\b",
    re.IGNORECASE,
)
_ANITA_HINT = re.compile(
    r"anita|mui|梅艷芳|梅艳芳|cinepoly",
    re.IGNORECASE,
)
_MOMOE_HINT = re.compile(r"momoe|yamaguchi|山口百恵|百恵", re.IGNORECASE)
_TERESA_HINT = re.compile(
    r"teresa|teng|テレサ|鄧麗君|邓丽君",
    re.IGNORECASE,
)
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)
_LOT_HINT = re.compile(
    r"まとめ|大量|約\s*\d+\s*枚|\d{2,}\s*本|used cds|job lot|ジャンク|"
    r"\blot\b|など|ほか|箱売り",
    re.IGNORECASE,
)
_KNOWN_CATALOG_PREFIX = re.compile(
    r"^(?:"
    r"TACL|TATL|POCH|PCCA|PCJA|UPCY|UICZ|UICY|UPJY|MR|MRZ|"
    r"SOLL|SOLS|SOLB|SOLI|SOLJ|TRUE|DCT|WPCV|AMCM|SRCL|SR|TASL|CRQ|TDL|"
    r"28TT|28TR|07TR|06SH|07SH|04SH|18TR|28MX|32TX|34TX|35TX|35CX|38TT|60DH|"
    r"H32P|H50P|CS|MHCL|KRS|C28A|\d{2}AH|POCH|PROT|UPCY|PKDA|GSR|"
    r"YS|CDU|DR|LFLP|AWK|"
    r"817|2427"
    r")",
    re.IGNORECASE,
)


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


def _catalog_text(value: Any) -> str:
    """Coerce warehouse/pandas catalog values to text. NaN is empty."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value != value:
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "<na>", "nat"}:
        return ""
    return text


def primary_catalog(value: str | None) -> str:
    """Strip Discogs range tails so TACL-2395~6 ≡ TACL-2395."""
    raw = re.sub(r"\s+", " ", _catalog_text(value))
    if not raw:
        return ""
    return _RANGE_CATNO_TAIL.sub("", raw).strip()


def fold_catalog(value: str | None) -> str:
    """Fold hyphens, spaces, range tails, and case so SOLL114 ≡ SOLL-114."""
    primary = primary_catalog(value)
    if not primary:
        return ""
    return _NON_ALNUM.sub("", primary.upper())


def catalog_letter_prefix(value: str | None) -> str | None:
    """Letter prefix of a known catno so 38TT-1120 and 38TT-1145 share 38TT."""
    folded = fold_catalog(value)
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if not letter:
        return None
    prefix = letter.group(1)
    if len(prefix) < 3:
        return None
    return prefix


def catalog_number_distance(left: str | None, right: str | None) -> int:
    """Absolute numeric distance when two catnos share a letter prefix."""
    left_match = _LETTER_NUMBER_CATALOG.fullmatch(fold_catalog(left))
    right_match = _LETTER_NUMBER_CATALOG.fullmatch(fold_catalog(right))
    if not left_match or not right_match:
        return 10_000
    if left_match.group(1) != right_match.group(1):
        return 10_000
    try:
        return abs(int(left_match.group(2)) - int(right_match.group(2)))
    except ValueError:
        return 10_000


def catalog_identity_key(value: str | None) -> str:
    """Fold a catno while keeping 2CD/3CD range digits (MHCL10910 ≠ MHCL109)."""
    raw = re.sub(r"\s+", "", (value or "").strip().upper())
    if not raw:
        return ""
    raw = raw.replace("～", "~").replace("〜", "~").replace("／", "/")
    return _NON_ALNUM.sub("", raw)


def catalog_has_range(value: str | None) -> bool:
    """True when the catno names a 2CD/3CD range, not only the first disc."""
    raw = str(value or "").strip()
    if not raw:
        return False
    return bool(_RANGE_CATNO_TAIL.search(raw) or _CATALOG_RANGE_IN_TEXT.search(raw))


def catno_locks_listing(
    hit_catno: str | None,
    listing_token: str | None,
) -> bool:
    """True when Discogs is the printed copy, including 2CD/3CD ranges."""
    if not catalog_identity_key(hit_catno) or not catalog_identity_key(listing_token):
        return False
    if catalog_identity_key(hit_catno) == catalog_identity_key(listing_token):
        return True
    if not catno_covers_listing_token(hit_catno, listing_token):
        return False
    listing_range = catalog_has_range(listing_token)
    hit_range = catalog_has_range(hit_catno)
    if listing_range and not hit_range:
        return False
    if hit_range and not listing_range:
        return True
    return False


def catalog_search_variants(token: str | None) -> tuple[str, ...]:
    """Catno spellings Discogs may store: DR-1944, DR1944, MHCL-109~10."""
    raw = (token or "").strip()
    if not raw:
        return ()
    folded = fold_catalog(raw)
    variants = [raw]
    if folded and folded not in variants:
        variants.append(folded)
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if letter:
        hyphen = f"{letter.group(1)}-{letter.group(2)}"
        spaced = f"{letter.group(1)} {letter.group(2)}"
        for item in (hyphen, spaced):
            if item not in variants:
                variants.append(item)
    ranged = _CATALOG_RANGE_IN_TEXT.search(raw)
    if ranged:
        head = re.sub(r"\s+", "-", ranged.group(1).upper())
        pair = f"{head}~{ranged.group(2)}"
        slash = f"{head}/{ranged.group(2)}"
        for item in (pair, slash, head):
            if item not in variants:
                variants.append(item)
    return tuple(variants)


def printed_matrix_on_discogs(
    hits: Sequence[SearchHit],
    token: str | None,
) -> bool:
    """True when some Discogs catno is the matrix printed on the listing."""
    if not token:
        return False
    return any(
        catno_locks_listing(hit.catno, token)
        or catno_covers_listing_token(hit.catno, token)
        for hit in hits
    )


def unique_release_for_missing_matrix(
    hits: Sequence[SearchHit],
    *,
    title: str | None,
    media_type: str | None,
    token: str | None,
) -> SearchHit | None:
    """The one release the title names, when the printed matrix is not on Discogs.

    KRS 3012 is not a Discogs catno for ビッグヒット4. The title still names
    that release. A nearby number such as KRS 3021 stays a different album.
    """
    if not token or printed_matrix_on_discogs(hits, token):
        return None
    if known_album_phrase(title) is None:
        return None
    named = [
        hit
        for hit in hits
        if listing_media_compatible(media_type, " ".join(hit.formats))
        and (
            album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
        )
    ]
    if not named:
        return None
    album_keys = {_release_album_key(hit) for hit in named if _release_album_key(hit)}
    if len(album_keys) != 1:
        return None
    catnos = {fold_catalog(hit.catno) for hit in named if hit.catno}
    if len(named) != 1 and len(catnos) != 1:
        return None
    edition = _prefer_listing_edition(named, title)
    return edition[0] if edition else None


def catno_covers_listing_token(hit_catno: str | None, listing_token: str | None) -> bool:
    """True when a Discogs catno is the listing token or a ~10 / /5 sibling."""
    hit = fold_catalog(hit_catno)
    token = fold_catalog(listing_token)
    if not hit or not token:
        return False
    if hit == token:
        return True
    extra_hit = hit[len(token) :] if hit.startswith(token) else ""
    extra_token = token[len(hit) :] if token.startswith(hit) else ""
    if extra_hit and re.fullmatch(r"\d{1,3}", extra_hit):
        return True
    if extra_token and re.fullmatch(r"\d{1,3}", extra_token):
        return True
    return False


def covering_hits_for_listing(
    hits: Sequence[SearchHit],
    *,
    catalog_number: str | None = None,
    title: str | None = None,
    media_type: str | None = None,
    artist: str | None = None,
) -> tuple[SearchHit, ...]:
    """Keep catno hits plus same-album rows in other formats.

    Unprinted stored catalogs only lock when they fit this listing's media.
    """
    token = listing_identity_catalog(
        stored=catalog_number,
        title=title,
        artist=artist,
        media_type=media_type,
        infer=False,
    )
    if not token:
        return tuple(hits)
    locked = tuple(
        hit
        for hit in hits
        if catno_locks_listing(hit.catno, token)
        or catno_covers_listing_token(hit.catno, token)
    )
    extras = tuple(
        hit
        for hit in hits
        if album_name_in_listing(title, hit.title)
    )
    if not extras:
        return locked
    seen: set[int] = set()
    combined: list[SearchHit] = []
    for hit in (*locked, *extras):
        if hit.discogs_id in seen:
            continue
        seen.add(hit.discogs_id)
        combined.append(hit)
    return tuple(combined)


_TITLE_YEAR = re.compile(r"(?<![A-Za-z0-9])(19[4-9]\d|20[0-2]\d)(?![A-Za-z0-9])")
_TITLE_YEAR_NEN = re.compile(r"(?<![A-Za-z0-9])(19[4-9]\d|20[0-2]\d)年")
_CONCERT_TIMESTAMP = re.compile(
    r"(?:19[4-9]\d|20[0-2]\d)\.\d{1,2}\.\d{1,2}"
    r"|(?:19[4-9]\d|20[0-2]\d)\s*(?:NHK|live\b|concert\b|コンサート)",
    re.IGNORECASE,
)
_REISSUE_MARK = re.compile(
    r"復刻|再発|reissue|repress|リイシュー",
    re.IGNORECASE,
)
_ANALOG_COPY = re.compile(
    r"\blp\b|レコード|アナログ盤|アナログ|帯付|帯付き|\bvinyl\b",
    re.IGNORECASE,
)
_CD_COPY = re.compile(
    r"\bcd\b|年版\s*cd|cd版|ディスク",
    re.IGNORECASE,
)
_MODERN_REISSUE_PREFIX = re.compile(
    r"^(?:UPJY|UPCY|UPBH|UICY|UICZ|MHCL|PROT)",
    re.IGNORECASE,
)


def title_claims_reissue(title: str | None) -> bool:
    """True when the seller named a reissue / 復刻盤, not the original year."""
    return bool(_REISSUE_MARK.search(str(title or "")))


def extract_release_year(title: object) -> int | None:
    """Year of the copy for sale: 復刻 year when marked, else original 19xx年."""
    text = _CONCERT_TIMESTAMP.sub(" ", str(title or "").strip())
    if not text:
        return None
    years = [int(match.group(1)) for match in _TITLE_YEAR.finditer(text)]
    if not years:
        return None
    if title_claims_reissue(text):
        modern = [year for year in years if year >= 2000]
        return modern[0] if modern else years[-1]
    nens = [int(match.group(1)) for match in _TITLE_YEAR_NEN.finditer(text)]
    if nens:
        vintage = [year for year in nens if year < 2000]
        return vintage[0] if vintage else nens[0]
    vintage = [year for year in years if year < 2000]
    return vintage[0] if vintage else years[0]


def listing_names_audiophile_reissue(title: str | None) -> bool:
    """True when the seller named a Stereo Sound / MoFi-style repress."""
    return bool(_AUDIOPHILE_REISSUE.search(str(title or "")))


def listing_wants_original_pressing(title: str | None) -> bool:
    """Vintage analog copy, not a named 2010s Universal/MHCL reissue.

    LP / レコード / 帯付 listings without 復刻 or UPJY in the title are treated
    as original-era copies even when the seller omitted 1975年. A table photo
    of a vinyl is not enough to pick a 2020 repress.
    """
    if (
        title_claims_reissue(title)
        or listing_names_modern_reissue_catalog(title)
        or listing_names_audiophile_reissue(title)
    ):
        return False
    text = str(title or "")
    if _CD_COPY.search(text) and not _ANALOG_COPY.search(text):
        return False
    year = extract_release_year(title)
    if year is not None:
        return year <= 1999
    return bool(_ANALOG_COPY.search(text))


def is_modern_reissue_catalog(value: str | None) -> bool:
    """Universal/MHCL catalogs that reprint 1970s titles in the 2010s."""
    return bool(_MODERN_REISSUE_PREFIX.match(primary_catalog(value)))


def listing_names_modern_reissue_catalog(title: str | None) -> bool:
    """True when the seller printed a Universal/MHCL/PROT catno on the listing."""
    text = str(title or "")
    ranged = _CATALOG_RANGE_IN_TEXT.search(text)
    if ranged and is_modern_reissue_catalog(ranged.group(1)):
        return True
    return any(
        is_modern_reissue_catalog(match.group(1))
        for match in _CATALOG_IN_TEXT.finditer(text)
    )


def hit_is_modern_reissue(hit: SearchHit) -> bool:
    """True for 2010s Universal/MHCL catalogs or 2000+ Discogs years."""
    if is_modern_reissue_catalog(hit.catno):
        return True
    year = str(hit.year or "").strip()[:4]
    if not year:
        return False
    try:
        return int(year) >= 2000
    except ValueError:
        return False


def hit_fits_listing_year(
    title: str | None,
    year: object,
) -> bool:
    """Reject a 2019 reissue for a 1975年 original, and vice versa."""
    try:
        actual = int(str(year).strip()[:4]) if year is not None and str(year).strip() else None
    except (TypeError, ValueError):
        actual = None
    if (
        listing_wants_original_pressing(title)
        and actual is not None
        and actual >= 2000
    ):
        return False
    claimed = extract_release_year(title)
    if claimed is None or actual is None:
        return True
    if claimed >= 2000 and actual < 2000:
        return False
    if claimed >= 2000:
        return abs(actual - claimed) <= 5
    if (
        title_claims_reissue(title)
        or listing_names_modern_reissue_catalog(title)
        or listing_names_audiophile_reissue(title)
    ):
        return abs(actual - claimed) <= 2 or actual >= 2000
    if claimed <= 1999 and actual >= claimed + 8:
        return False
    return True


def media_family(value: str | None) -> str:
    """Collapse listing/pressing/format blobs to cd, vinyl, cassette, or other."""
    media = (value or "").casefold()
    if not media.strip():
        return "unknown"
    compact = re.sub(r"[\s,]+", "_", media)
    if compact.startswith("cd") or compact in {
        "mixed_media",
        "shm_cd",
        "sacd",
        "blu_spec_cd",
    }:
        return "cd"
    if "cd" in media and "vinyl" not in media and "lp" not in media:
        return "cd"
    if compact.startswith("cassette") or "tape" in media:
        return "cassette"
    if compact.startswith("dvd"):
        return "dvd"
    if "laserdisc" in media:
        return "laserdisc"
    if compact in {
        "print",
        "photobook",
        "magazine",
        "stamp",
        "sheet_music",
        "usb",
        "toy",
    }:
        return "other"
    return "vinyl"


def vinyl_shape(value: str | None) -> str:
    """Distinguish 7\", 12\" singles, and LPs inside the vinyl family."""
    media = (value or "").casefold()
    if media in {"ep_7_inch", "7_inch"} or '7"' in media:
        return "seven"
    if media in {"single_12_inch", "12_inch_single"} or "maxi" in media:
        return "twelve"
    if '12"' in media and "lp" not in media and "album" not in media:
        return "twelve"
    if media.startswith("lp") or media in {"album", "lp_box_set"}:
        return "lp"
    if re.search(r"\blp\b", media) or re.search(r"\balbum\b", media):
        return "lp"
    return "vinyl"


def discogs_format_label(formats: Sequence[str] | None) -> str:
    """Operator-facing LP / EP / CD label for a Discogs format list."""
    items = [str(item).strip() for item in (formats or ()) if str(item).strip()]
    if not items:
        return ""
    blob = " ".join(items)
    family = media_family(blob)
    shape = vinyl_shape(blob)
    folded = blob.casefold()
    edition_mark = (
        " · Promo"
        if re.search(r"\bpromo\b|white\s*label|見本", folded)
        else ""
    )
    if family == "cd":
        return f"CD{edition_mark}"
    if family == "cassette":
        return f"Cassette{edition_mark}"
    if family == "dvd":
        return f"DVD{edition_mark}"
    if family == "laserdisc":
        return f"Laserdisc{edition_mark}"
    if shape == "seven":
        seven = 'EP / 7"' if re.search(r"\bep\b", folded) else '7"'
        return f"{seven}{edition_mark}"
    if shape == "twelve":
        return f'12"{edition_mark}'
    if shape == "lp":
        return f"LP{edition_mark}"
    if family == "vinyl":
        return f"Vinyl{edition_mark}"
    return f"{items[0]}{edition_mark}"


def visible_shortlist_hits(
    hits: Sequence[dict[str, Any]],
    title: str | None = None,
) -> list[dict[str, Any]]:
    """Drop duplicate cards; keep a Promo row when it is the only difference.

    A named album such as 星願 drops a generic ベスト・セレクション.
    A title that names two records drops the one the sleeve did not confirm.
    """
    named = known_album_phrase(title) if title else None
    known_catno = (
        inferred_release_catalog(title=title, artist=None, media_type=None)
        if title
        else None
    )
    named_keys = {
        _script_compact(spelling)
        for spelling in ((named,) if named else ())
    }
    if named:
        named_keys.update(
            _script_compact(spelling)
            for spelling in equivalent_title_spellings(named)
        )
    named_keys.discard("")
    seen_ids: set[int] = set()
    seen_keys: set[tuple[str, str]] = set()
    visible: list[dict[str, Any]] = []
    for hit in hits:
        hit_title = str(hit.get("title") or "")
        if title and listing_names_other_work(title, hit_title):
            continue
        if known_catno and catno_locks_listing(str(hit.get("catno") or ""), known_catno):
            pass
        elif named_keys:
            compact = _script_compact(hit_title)
            if not any(key in compact for key in named_keys):
                continue
        try:
            release_id = int(hit.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if release_id in seen_ids:
            continue
        formats = hit.get("format") or ()
        if isinstance(formats, str):
            formats = [formats]
        label = discogs_format_label(
            [str(item) for item in formats if str(item).strip()]
        )
        key = (
            fold_catalog(str(hit.get("catno") or "")) or str(release_id),
            label,
        )
        if key in seen_keys:
            continue
        seen_ids.add(release_id)
        seen_keys.add(key)
        visible.append(dict(hit))
    return visible


def shortlist_option_shape(formats: Sequence[str] | None) -> str:
    """LP vs 7\" vs CD vs cassette, ignoring Promo/reissue marks."""
    blob = " ".join(str(item) for item in (formats or ()) if str(item).strip())
    family = media_family(blob)
    if family != "vinyl":
        return family
    return vinyl_shape(blob)


def listing_format_label(media_type: str | None) -> str:
    """Operator-facing LP / EP / CD label for a listing media type."""
    media = (media_type or "").strip()
    if not media:
        return ""
    compact = media.casefold().replace(" ", "_")
    if compact in {"ep_7_inch", "7_inch"}:
        return 'EP / 7"'
    if compact in {"single_12_inch", "12_inch_single"}:
        return '12"'
    if compact.startswith("cd"):
        return "CD"
    if compact.startswith("lp"):
        return "LP"
    if compact.startswith("cassette"):
        return "Cassette"
    return media.replace("_", " ")


_TITLE_SEVEN_OR_EP = re.compile(
    r"""7\s*["'′″]|7inch|7インチ|(?<![A-Za-z])EP(?![A-Za-z])"""
    r"|シングル盤|シングルレコード|シングル(?![・･]?コレクション)",
    re.IGNORECASE,
)
_TITLE_ALBUM_LOCK = re.compile(
    r"\blp\b|12\s*\"|アルバム|2枚組|3枚組|全集|セレクション",
    re.IGNORECASE,
)
_TITLE_QUOTED_WORK = re.compile(r"[「『]([^」』]{2,24})[」』]")
_TITLE_VINYL_WORD = re.compile(r"レコード|vinyl|analog|アナログ", re.IGNORECASE)
_SEVEN_INCH_TITLE_MARKS = (
    "禁じられた遊び",
    "つぐない",
    "空港",
    "コーヒールンバ",
    "戀愛有苦也有樂",
    "恋爱有苦也有乐",
    "ひと夏の経験",
    "いい日旅立ち",
    "秋桜",
    "横須賀ストーリー",
    "さよならの向う側",
    "さよならの向こう側",
    "kinjirareta asobi",
    "tugunai",
    "tsugunai",
)


_TITLE_CD = re.compile(
    r"(?<![A-Za-z])cds?\b|ＣＤ|コンパクトディスク|shm-?cd|sacd",
    re.IGNORECASE,
)
_TITLE_CASSETTE = re.compile(r"cassette|カセット|磁带", re.IGNORECASE)


def listing_title_wants_seven_inch(title: str | None) -> bool:
    """True when the listing names a 7\" / EP / quoted single, not an LP."""
    text = title or ""
    if _TITLE_SEVEN_OR_EP.search(text) and not re.search(
        r"\blp\b|12\s*\"",
        text,
        re.IGNORECASE,
    ):
        return True
    if _TITLE_ALBUM_LOCK.search(text):
        return False
    folded = text.casefold()
    named = any(mark in text or mark in folded for mark in _SEVEN_INCH_TITLE_MARKS)
    if not named:
        return False
    quoted = _TITLE_QUOTED_WORK.search(text)
    return bool(quoted or _TITLE_VINYL_WORD.search(text) or "直筆サイン" in text)


def effective_listing_media(media_type: str | None, title: str | None = None) -> str | None:
    """Prefer a title that names CD, cassette, or 7\" over a stale LP classifier."""
    if listing_title_wants_seven_inch(title):
        return "EP_7_INCH"
    text = title or ""
    media = (media_type or "").upper()
    if media in {"EP_7_INCH", "7_INCH"} and _TITLE_ALBUM_LOCK.search(text):
        return "LP"
    if _TITLE_CASSETTE.search(text) and not _TITLE_ALBUM_LOCK.search(text):
        return "CASSETTE"
    if _TITLE_CD.search(text) and not re.search(r"\blp\b", text, re.IGNORECASE):
        if media.startswith("CD") or media in {"SHM_CD", "SACD", "BLU_SPEC_CD", "MIXED_MEDIA"}:
            return media_type
        return "CD"
    return media_type


def listing_media_compatible(
    listing_media: str | None,
    other_media: str | None,
) -> bool:
    """Keep LP listings off CD pressings, and 7\"/12\" singles off albums."""
    left = media_family(listing_media)
    right = media_family(other_media)
    if left == "unknown" or right == "unknown":
        return True
    if left != right:
        return False
    if left != "vinyl":
        return True
    left_shape = vinyl_shape(listing_media)
    right_shape = vinyl_shape(other_media)
    if left_shape == "vinyl" or right_shape == "vinyl":
        return True
    return left_shape == right_shape


def is_junk_catalog(value: str | None, *, title: str | None = None) -> bool:
    """True for media+year, name+year, or lot SKU tokens that are not catnos."""
    raw = re.sub(r"\s+", " ", _catalog_text(value))
    if not raw:
        return True
    if _MEDIA_YEAR_CATALOG.fullmatch(raw):
        return True
    if _MEDIA_SIZE_CATALOG.fullmatch(raw):
        return True
    if _SPACE_YEAR_CATALOG.fullmatch(raw) or _DECADE_CATALOG.fullmatch(raw):
        return True
    folded = fold_catalog(raw)
    if re.fullmatch(r"(?:19[4-9]\d|20[0-2]\d)", folded):
        return True
    if folded.startswith("PRICE"):
        return True
    if _format_inventory_sku(raw, title):
        return True
    if _MONTH_DAY_CATALOG.fullmatch(folded) or _MONTH_DAY_CATALOG.fullmatch(
        re.sub(r"\s+", "", raw)
    ):
        return True
    if _TRAILING_LETTER_SKU.fullmatch(folded):
        return True
    if _BRACKET_INVENTORY_SKU.fullmatch(folded):
        return True
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if letter and not _known_catalog_prefix(raw) and (
        letter.group(1) in _FALSE_LETTER_PREFIXES
        or _YEAR_DIGITS.fullmatch(letter.group(2))
        or _is_false_letter_catalog(raw)
        or (
            len(letter.group(1)) >= 3
            and re.fullmatch(r"[7-9]\d", letter.group(2))
        )
    ):
        return True
    if re.fullmatch(r"[A-Z]\d{2}[A-Z]", folded):
        return True
    if (
        title
        and letter
        and letter.group(2) in {"7", "8", "10", "12", "45"}
        and re.search(
            rf"""(?:^|[\s]){re.escape(letter.group(2))}\s*["'′″インチinch]""",
            title,
            re.IGNORECASE,
        )
        and not _known_catalog_prefix(raw)
    ):
        return True
    if re.fullmatch(r"[A-Z]\d{2,3}", folded) and not _known_catalog_prefix(raw):
        return True
    if (
        letter
        and len(letter.group(2)) <= 2
        and not _known_catalog_prefix(raw)
    ):
        return True
    if title and _LOT_HINT.search(title) and not _known_catalog_prefix(raw):
        return True
    if (
        title
        and re.search(r"写真|スチール", title)
        and re.fullmatch(r"P\d{3,5}", folded)
        and not _known_catalog_prefix(raw)
    ):
        return True
    if (
        title
        and re.search(r"musicwall", title, re.IGNORECASE)
        and letter
        and letter.group(1) == "LP"
    ):
        return True
    return False


def _format_inventory_sku(value: str, title: str | None) -> bool:
    """Buyee codes such as LP0847 are stock numbers, not the pressing catalog.

    A hyphenated label number (Cinepoly LP-3973) stays. The same digits are
    dropped only when the listing title opens with the glued stock code.
    """
    folded = fold_catalog(value) or ""
    if not re.fullmatch(r"(?:LP|CD|EP)\d{3,5}", folded):
        return False
    if re.fullmatch(r"(?:LP|CD|EP)\d{3,5}", (value or "").strip(), re.IGNORECASE):
        return True
    if title and re.match(
        rf"^(?:LP|CD|EP)\s*{re.escape(folded[2:])}(?!\d)",
        title.strip(),
        re.IGNORECASE,
    ):
        return True
    return False


def _known_catalog_prefix(value: str) -> bool:
    """True for a printed catno, including letter+4-digit tokens like KP-8142."""
    raw = (value or "").strip()
    if not raw:
        return False
    folded = fold_catalog(raw) or raw
    if _KNOWN_CATALOG_PREFIX.match(folded):
        return True
    if _poly_from_text(raw):
        return True
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if not letter:
        return False
    prefix = letter.group(1)
    digits = letter.group(2)
    if prefix in _FALSE_LETTER_PREFIXES or _is_false_letter_catalog(raw):
        return False
    if _YEAR_DIGITS.fullmatch(digits):
        return False
    if 2 <= len(prefix) <= 5 and len(digits) >= 4:
        return True
    return False


def _poly_from_text(text: str) -> str | None:
    """Philips/Polydor international catnos display as '2427 333', never 242733-3."""
    match = _POLY_SPACED.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    match = _POLY_WRONG_HYPHEN.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}{match.group(3)}"

    match = _POLY_MASHED.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    match = _POLY_FOUR_THREE.search(text)
    if match and not re.fullmatch(r"(?:19[4-9]\d|20[0-2]\d)", match.group(1)):
        return f"{match.group(1)} {match.group(2)}"

    return None


def _polygram_from_text(text: str) -> str | None:
    match = _POLYGRAM_SPACED.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}-{match.group(3)}"

    match = _POLYGRAM_MASHED.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}-{match.group(3)}"

    return None


def _taurus_double_from_text(text: str) -> str | None:
    """2LP mash 18TR205960 is Discogs 18TR-2059~2060."""
    match = _TAURUS_DOUBLE.search(text)
    if not match:
        return None
    prefix = match.group(1).upper()
    head = match.group(2)
    tail = match.group(3)
    expanded = f"{head[:-len(tail)]}{tail}" if len(head) >= len(tail) else tail
    return f"{prefix}-{head}~{expanded}"


def _is_false_letter_catalog(candidate: str) -> bool:
    folded = fold_catalog(candidate)
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if not letter:
        return False
    prefix = letter.group(1)
    digits = letter.group(2)
    if prefix in _FALSE_LETTER_PREFIXES:
        return True
    return prefix in {"UP", "IN", "L"} and digits in {"7", "10", "11", "12", "45"}


def _is_inch_format_catalog(match: re.Match[str], text: str) -> bool:
    """True when 'WOMAN 12'' is a 12-inch format, not a catno."""
    folded = fold_catalog(match.group(1))
    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if not letter or letter.group(2) not in {"7", "8", "10", "12", "45"}:
        return False
    return bool(_INCH_AFTER_CATALOG.match(text[match.end() :]))


def display_catalog(value: str | None) -> str | None:
    """Canonical catalog display: spaced 4+3 poly, PREFIX-NUMBER otherwise."""
    raw = re.sub(r"\s+", " ", (value or "").strip().upper())
    if not raw or is_junk_catalog(raw):
        return None

    poly = _poly_from_text(raw)
    if poly:
        return poly

    polygram = _polygram_from_text(raw)
    if polygram:
        return polygram

    taurus = _taurus_double_from_text(raw)
    if taurus:
        return taurus

    folded = fold_catalog(raw)
    if re.fullmatch(r"2[3-4]\d{5}", folded):
        return f"{folded[:4]} {folded[4:]}"
    capital = re.fullmatch(r"CAL04(\d{4})", folded)
    if capital:
        return f"CAL-04-{capital.group(1)}"

    letter = _LETTER_NUMBER_CATALOG.fullmatch(folded)
    if letter:
        return f"{letter.group(1)}-{letter.group(2)}"

    return raw


def catalog_token(
    *,
    catalog_number: str | None = None,
    title: str | None = None,
) -> str | None:
    """Return a listing catalog token from the field or the title."""
    field = _catalog_text(catalog_number)
    text = _catalog_text(title) if title is not None else ""
    field_candidates: list[str] = []
    title_candidates: list[str] = []

    def _add(bucket: list[str], candidate: str | None) -> None:
        if not candidate or is_junk_catalog(candidate, title=text):
            return
        folded_title = re.sub(r"[^A-Z0-9]", "", text.upper())
        in_title = bool(fold_catalog(candidate)) and fold_catalog(candidate) in folded_title
        if (
            listing_wants_original_pressing(text)
            and is_modern_reissue_catalog(candidate)
            and not in_title
            and not re.search(
                r"\bcd\b|シーディー|コンパクトディスク",
                text,
                re.IGNORECASE,
            )
        ):
            return
        ranged = _CATALOG_RANGE_IN_TEXT.search(str(candidate))
        if ranged:
            head = display_catalog(ranged.group(1)) or re.sub(
                r"\s+", "-", ranged.group(1).upper()
            )
            canonical = f"{head}~{ranged.group(2)}"
        else:
            canonical = display_catalog(candidate)
        if canonical:
            side = re.fullmatch(
                r"([A-Z]{2,5}-\d{2,5})-([A-D])",
                canonical,
            )
            if side and _known_catalog_prefix(side.group(1)):
                canonical = side.group(1)
        if canonical and canonical not in bucket:
            bucket.append(canonical)

    field_poly = _poly_from_text(field) if field else None
    if field_poly:
        return field_poly
    _add(field_candidates, field)

    if text:
        _add(title_candidates, _poly_from_text(text))
        _add(title_candidates, _polygram_from_text(text))
        _add(title_candidates, _taurus_double_from_text(text))
        ranged = _CATALOG_RANGE_IN_TEXT.search(text)
        if ranged:
            head = re.sub(r"\s+", "-", ranged.group(1).upper())
            _add(title_candidates, f"{head}~{ranged.group(2)}")
        epic = _EPIC_JAPAN.search(text)
        if epic:
            _add(title_candidates, f"{epic.group(1).upper()}-{epic.group(2)}")
        cd_style = _CD_STYLE_CATALOG.search(text)
        if cd_style:
            _add(title_candidates, cd_style.group(1))
        polydor_cd = _POLYDOR_JP_CD.search(text)
        if polydor_cd:
            _add(
                title_candidates,
                f"{polydor_cd.group(1)}-{polydor_cd.group(2)}",
            )
        prefixed = _PREFIXED_CATALOG_IN_TEXT.search(text)
        if prefixed:
            _add(title_candidates, prefixed.group(1))
        capital = _CAPITAL_ARTISTS_CAL.search(text)
        if capital:
            _add(title_candidates, f"CAL-04-{capital.group(1)}")
        if _ANITA_HINT.search(text):
            cinepoly = _CINEPOLY_LP.search(text)
            if cinepoly:
                _add(title_candidates, f"LP-{cinepoly.group(1)}")
        for match in _CATALOG_IN_TEXT.finditer(text):
            candidate = match.group(1).strip().upper()
            if _is_false_letter_catalog(candidate) or _is_inch_format_catalog(
                match, text
            ):
                continue
            _add(title_candidates, candidate)

    known_title = [item for item in title_candidates if _known_catalog_prefix(item)]
    if known_title:
        chosen = known_title[0]
    else:
        known_field = [item for item in field_candidates if _known_catalog_prefix(item)]
        if known_field:
            chosen = known_field[0]
        elif title_candidates:
            chosen = title_candidates[0]
        else:
            chosen = field_candidates[0] if field_candidates else None
    return _drop_false_artist_catalog(chosen, text)


def catalog_printed_on_listing(token: str | None, title: str | None) -> bool:
    """True when the listing title actually contains this catalog token."""
    folded = fold_catalog(token)
    if not folded:
        return False
    compact_title = re.sub(r"[^A-Z0-9]", "", str(title or "").upper())
    return folded in compact_title


_SEVEN_INCH_STORED_PREFIX = re.compile(
    r"^(?:0[467]SH|07TR|07DX|SOLB|KRS|DR\d{3,4})",
    re.IGNORECASE,
)
_CD_STORED_PREFIX = re.compile(
    r"^(?:PODH|POCH|PCCA|PCJA|TACL|CSCL|SRCL|MHCL|UPCY|UICY|UICZ|"
    r"H32P|H50P|32DH|35DH|60DH|DCT|DQCL|CDO|CDU)",
    re.IGNORECASE,
)
_CASSETTE_STORED_PREFIX = re.compile(
    r"^(?:POSH|TATL|25KH|38KH|28CX)",
    re.IGNORECASE,
)


def _stored_catalog_family(stored: str) -> str:
    """Guess LP / 7\" / CD / cassette from a known Japanese catalog prefix."""
    folded = (fold_catalog(stored) or stored).upper()
    if _SEVEN_INCH_STORED_PREFIX.match(folded):
        return "seven"
    if _CD_STORED_PREFIX.match(folded):
        return "cd"
    if _CASSETTE_STORED_PREFIX.match(folded):
        return "cassette"
    return "lp"


def stored_catalog_fits_listing(
    stored: str | None,
    *,
    title: str | None,
    media_type: str | None = None,
) -> bool:
    """True when a stored catno is safe to search for this copy.

    Printed numbers always count. Unprinted ones only count when the prefix
    matches the listing media, so a leftover 7\" 06SH cannot lock an LP, but
    an operator-entered MR3166 on a vinyl listing still can.
    """
    stored = _catalog_text(stored) or None
    if not stored or is_junk_catalog(stored, title=title):
        return False
    if catalog_printed_on_listing(stored, title):
        return True
    if not _known_catalog_prefix(stored):
        return False
    family = _stored_catalog_family(stored)
    listing_media = effective_listing_media(media_type, title) or media_type
    listing_family = media_family(listing_media)
    listing_shape = vinyl_shape(listing_media)
    if listing_title_wants_seven_inch(title) or listing_shape == "seven":
        return family == "seven"
    if listing_family == "cd":
        return family == "cd"
    if listing_family == "cassette":
        return family == "cassette"
    if listing_family == "vinyl" or listing_shape in {"lp", "vinyl"}:
        return family == "lp"
    return family == "lp"


_BAD_SLASH_LEAD = frozenset(
    {
        "枚組",
        "サイズ",
        "カセット",
        "カセットテープ",
        "レコード",
        "アルバム",
        "ボックス",
        "セット",
    }
)
_SLASH_NOISE_WORDS = _BAD_SLASH_LEAD | {
    "美品",
    "極美品",
    "新品",
    "未開封",
    "未開封品",
    "国内正規",
    "国内正規品",
    "正規品",
    "未使用",
    "未使用品",
    "中古",
    "中古品",
    "帯付",
    "帯付き",
    "帯あり",
    "並品",
    "良品",
    "新同",
    "良好",
    "ライブ盤",
    "アナログ盤",
    "国内盤",
    "日本盤",
    "台湾盤",
    "香港盤",
    "見本盤",
    "見本品",
    "プロモ",
    "サンプル",
    "ポスター",
    "ステッカー",
}
_MEDIA_SLASH_PREFIX = re.compile(
    r"^(?:lps?|eps?|cds?|dvds?|lds?|vhs|mcs|tape|vinyl|records?|"
    r"cassette|アナログ|7\"?|12\"?)+",
    re.IGNORECASE,
)
_PLACE_ONLY = re.compile(
    r"^(?:台湾|台灣|臺灣|香港|日本|韓国|韓國|中国|中國|美国|美國|"
    r"taiwan|hong\s*kong|japan|korea)$",
    re.IGNORECASE,
)
_STOCK_THEN_PLACE = re.compile(
    r"^(?:LP|CD|EP)\d{3,5}[☆★*]?\s*"
    r"(?:台湾|台灣|臺灣|香港|日本|韓国|韓國|中国|中國|美国|美國|"
    r"taiwan|hong\s*kong|japan|korea)$",
    re.IGNORECASE,
)


def _slash_title_parts(title: str | None) -> list[str]:
    cleaned = _SKU_LEAD.sub("", (title or "").strip())
    cleaned = _TAG_LEAD.sub("", cleaned)
    return [
        re.sub(r"\s+", " ", part).strip(" ;:-")
        for part in re.split(r"[/／]", cleaned)
        if part.strip()
    ]


def _slash_part_is_noise(part: str) -> bool:
    """True for LP美品 / 帯付 segments that are not a performer name."""
    if not part or _VA_LEAD.match(part):
        return True
    stripped = part.strip()
    if _PLACE_ONLY.fullmatch(stripped) or _STOCK_THEN_PLACE.fullmatch(stripped):
        return True
    if _MEDIA_SLASH_LEAD.fullmatch(part):
        return True
    compact = re.sub(r"[\s・]+", "", part)
    compact = _MEDIA_SLASH_PREFIX.sub("", compact)
    for junk in sorted(_SLASH_NOISE_WORDS, key=len, reverse=True):
        compact = compact.replace(junk, "")
    return not compact


def _artist_from_slash_part(lead: str) -> str | None:
    if not lead or _VA_LEAD.match(lead):
        return None
    stripped = lead.strip()
    if _PLACE_ONLY.fullmatch(stripped) or _STOCK_THEN_PLACE.fullmatch(stripped):
        return None
    names = _CJK_LEAD_NAME.findall(lead.replace("・", ""))
    names = [
        name
        for name in names
        if name not in _SLASH_NOISE_WORDS
        and not _is_known_album_title(name)
        and not _PLACE_ONLY.fullmatch(name)
    ]
    if names:
        return names[-1]
    if _DIRTY_LEAD.search(lead):
        return None
    if _is_known_album_title(lead):
        return None
    return lead


def _slash_lead_artist(title: str | None) -> str | None:
    """Artist named before the album `/` on a Buyee-style title."""
    for part in _slash_title_parts(title):
        if _slash_part_is_noise(part) or _is_known_album_title(part):
            continue
        found = _artist_from_slash_part(part)
        if found:
            return found
    return None


def _name_before_slash(
    title: str | None,
    latin: str,
    local_names: tuple[str, ...],
) -> bool:
    """True when the tracked name is in the title head before the album slash."""
    parts = [
        part
        for part in _slash_title_parts(title)
        if not _slash_part_is_noise(part)
    ]
    if not parts:
        return False
    head = parts[0]
    return latin.casefold() in head.casefold() or any(name in head for name in local_names)


def _tracked_name_is_lead(
    artist: str | None,
    title: str | None,
    latin: str,
    local_names: tuple[str, ...],
) -> bool:
    """True when the tracked name is the listing artist, not a 検) name-drop."""
    field = artist or ""

    def _names_in(blob: str | None) -> bool:
        folded = (blob or "").casefold()
        if not folded:
            return False
        if latin.casefold() in folded:
            return True
        return any(name.casefold() in folded for name in local_names)

    in_field = _names_in(field)
    before_slash = _name_before_slash(title, latin, local_names)
    lead = _slash_lead_artist(title)
    if in_field or before_slash:
        if before_slash:
            return True
        if lead is None:
            return True
        if _names_in(lead):
            return True
        if _is_known_album_title(lead):
            return True
        person = _artist_from_slash_part(lead)
        person_key = re.sub(r"[\s・]", "", person or "")
        if (
            person
            and person not in _SLASH_NOISE_WORDS
            and not _slash_part_is_noise(person)
            and _CJK_LEAD_NAME.fullmatch(person_key)
            and not _names_in(person)
        ):
            return False
        if _JP_CHAR.search(lead) and not in_field:
            return False
        return True
    if lead is not None:
        return _names_in(lead)
    head = (title or "")[:56]
    return _names_in(head)


def search_artist(artist: str | None, title: str | None = None) -> str | None:
    """Latin Discogs artist query; drop barcodes and map tracked CJK names."""
    for latin, local_names in (
        ("Teresa Teng", ("テレサ", "テレサ・テン", "鄧麗君", "邓丽君", "teresa", "deng lijun")),
        ("Momoe Yamaguchi", ("山口百恵", "山口百惠", "百恵", "momoe", "yamaguchi")),
        ("Akina Nakamori", ("中森明菜", "明菜", "nakamori")),
        ("Anita Mui", ("梅艷芳", "梅艳芳", "anita mui")),
    ):
        if _tracked_name_is_lead(artist, title, latin, local_names):
            return latin

    lead = _slash_lead_artist(title)
    if lead and _JP_CHAR.search(lead):
        return None

    cleaned = _BARCODE_ARTIST_PREFIX.sub("", (artist or "").strip())
    cleaned = re.sub(r"[【\[].*?[】\]]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ;/-")
    if not cleaned or cleaned.isdigit() or len(cleaned) > 40:
        return None
    if _DIRTY_ARTIST.search(cleaned):
        return None
    return cleaned


_EBAY_ARTIST_MEDIA = re.compile(
    r"""(?ix)
    ^(.+?)
    \s+(?:lp|ep|cd|vinyl|cassette|tape|record)s?
    (?:\s+original)?
    (?:\s+(?:hong\s+kong|taiwan|cantonese|cantopop|korean|columbian))?
    (?:\s+pressing)?
    (?:\s+\d{4})?
    \s*$
    """
)
_EBAY_ARTIST_HEAD = re.compile(
    r"""(?ix)
    ^(the\s+[A-Z][A-Za-z'.]+|[A-Z][A-Za-z'.]+(?:\s+[A-Z][A-Za-z'.]+)?)
    \b
    """
)
_EBAY_MEDIA_WORD = re.compile(
    r"\b(?:lp|ep|cd|vinyl|cassette|tape|records?)\b",
    re.IGNORECASE,
)
_BAD_EXTRACTED_ARTIST = re.compile(
    r"soundtrack|various|varios|artistas|exitos|éxitos|disco\s+del|vol\.?\s*\d",
    re.IGNORECASE,
)
_ALBUM_THIRD_WORDS = frozenset(
    {
        "still",
        "dearest",
        "best",
        "live",
        "greatest",
        "hits",
        "collection",
        "original",
        "concert",
        "soundtrack",
        "vol",
        "volume",
        "part",
        "legend",
        "selected",
        "selection",
    }
)
_SKU_LEAD = re.compile(r"^\d{6,}[;:]?\s*")
_TAG_LEAD = re.compile(r"^[【\[(（][^】\]\)）]{0,24}[】\]\)）]\s*")
_SLASH_LEAD_ARTIST = re.compile(
    r"^([^/／\n]{2,30}?)\s*[/／]"
)
_MEDIA_SLASH_LEAD = re.compile(
    r"^(?:lps?|eps?|cds?|dvds?|lds?|vhs|mcs|tape|vinyl|records?|"
    r"cassette|アナログ|7\"?|12\"?)$",
    re.IGNORECASE,
)
_VA_LEAD = re.compile(
    r"^(?:v\.?a\.?|various|オムニバス|ヴァリアス)\b",
    re.IGNORECASE,
)
_CJK_LEAD_NAME = re.compile(r"[\u3040-\u9fff]{2,12}")
_DIRTY_LEAD = re.compile(r"\d{5,}|[【\[】\]]")


def listing_search_artist(
    artist: str | None,
    title: str | None = None,
) -> str | None:
    """Artist Discogs should search: tracked CJK names, then English title heads."""
    known = search_artist(artist, title)
    if known:
        return known
    english = artist_from_english_title(title)
    if english:
        return english
    lead = _slash_lead_artist(title)
    if lead and _JP_CHAR.search(lead) and 2 <= len(lead) <= 30:
        return lead
    return None


def artist_from_english_title(title: str | None) -> str | None:
    """Kenny Bee Lp / The Police … LP → artist head. Skip CJK and compilations."""
    raw = (title or "").strip()
    if not raw or re.search(r"[\u3040-\u9fff]", raw):
        return None
    if _BAD_EXTRACTED_ARTIST.search(raw):
        return None
    match = _EBAY_ARTIST_MEDIA.match(raw)
    if match:
        head = re.sub(r"\s+", " ", match.group(1)).strip(" -/")
        words = head.split()
        if (
            head
            and 4 <= len(head) <= 40
            and 1 <= len(words) <= 3
            and not _BAD_EXTRACTED_ARTIST.search(head)
        ):
            if (
                len(words) == 3
                and words[-1].casefold() in _ALBUM_THIRD_WORDS
            ):
                head = " ".join(words[:2])
            return head
    if not _EBAY_MEDIA_WORD.search(raw):
        return None
    head_match = _EBAY_ARTIST_HEAD.match(raw)
    if not head_match:
        return None
    head = re.sub(r"\s+", " ", head_match.group(1)).strip(" -/")
    if not head or len(head) < 4 or len(head) > 40:
        return None
    return head


def listing_barcode(title: str | None) -> str | None:
    """Return a JAN/EAN barcode from a Buyee-style title prefix."""
    match = _JAN_BARCODE.search(title or "")
    return match.group(0) if match else None


def prefers_japan(
    *,
    listing_title: str | None,
    listing_artist: str | None,
) -> bool:
    """True for kana / 日本盤 listings, not Anita Hong Kong originals."""
    blob = f"{listing_artist or ''} {listing_title or ''}"
    fold = blob.casefold()
    if _ANITA_HINT.search(blob) and not (
        "japan" in fold or "日本" in blob or "国内盤" in blob
    ):
        return False
    if "japan" in fold or "日本" in blob or "国内盤" in blob:
        return True
    if _KANA.search(blob) or _JP_ARTIST_HINT.search(blob):
        return True
    return False


def listing_preferred_country(
    *,
    listing_title: str | None,
    listing_artist: str | None,
) -> str | None:
    """Japan for kana/日本盤, Hong Kong/Taiwan/Korea when the listing says so."""
    blob = f"{listing_artist or ''} {listing_title or ''}"
    fold = blob.casefold()
    if "taiwan" in fold or "台灣" in blob or "台湾" in blob:
        return "taiwan"
    if _ANITA_HINT.search(blob) and not (
        "japan" in fold or "日本" in blob or "国内盤" in blob
    ):
        if "korea" in fold:
            return "south korea"
        return "hong kong"
    if prefers_japan(
        listing_title=listing_title,
        listing_artist=listing_artist,
    ):
        return "japan"
    if "hong kong" in fold or "香港" in blob:
        return "hong kong"
    return None


def _drop_false_artist_catalog(token: str | None, title: str | None) -> str | None:
    """Drop CBS YS- codes on Teresa listings and MusicWall LP SKUs."""
    if not token:
        return None
    blob = title or ""
    folded = (fold_catalog(token) or token).upper()
    if folded.startswith("YS") and _TERESA_HINT.search(blob) and not _MOMOE_HINT.search(
        blob
    ):
        return None
    if folded.startswith("LP") and re.search(r"musicwall", blob, re.IGNORECASE):
        return None
    return token


_ANITA_ALBUM_CATNOS = (
    (re.compile(r"妖女|將冰山劈開|evil girl", re.IGNORECASE), "CAL-04-1039"),
    (re.compile(r"壞女孩|坏女孩|bad girl", re.IGNORECASE), "CAL-04-1029"),
    (re.compile(r"淑女", re.IGNORECASE), "CAL-04-1079"),
    (re.compile(r"飛躍舞台|jump stage", re.IGNORECASE), "CAL-04-1013"),
    (re.compile(r"似水流年", re.IGNORECASE), "CAL-04-1019"),
    (re.compile(r"夢裡共醉|梦里共醉", re.IGNORECASE), "CAL-04-1069"),
    (re.compile(r"似火探戈|oh no[! ]?oh yes", re.IGNORECASE), "CAL-04-1047"),
    (re.compile(r"烈焰紅唇|烈燄紅唇|plastic love|flaming(?: red)? lips", re.IGNORECASE), "CAL-04-1056"),
    (re.compile(r"再展光華|in concert\s*87", re.IGNORECASE), "CAL-04-1060"),
    (re.compile(r"夏日耀光華|in concert\s*'?90", re.IGNORECASE), "CAL-04-1103"),
    (re.compile(r"in brasil", re.IGNORECASE), "CAL-04-1087"),
    (re.compile(r"國語專輯|百變梅艷芳\s*烈焰", re.IGNORECASE), "RR-164"),
)
_TERESA_COMPILATION = re.compile(
    r"ベスト|best of|\bhits\b|全曲集|カラオケ|super selection|セレクション",
    re.IGNORECASE,
)
_TERESA_ALBUM_CATNOS = (
    (
        re.compile(r"夜来香|夜來香"),
        re.compile(r"何日君再来|何日君再來"),
        "MR 3166",
    ),
    (
        re.compile(r"夜の乗客"),
        re.compile(r"女の生きがい|女のいきがい"),
        "MR 3036",
    ),
)


def inferred_release_catalog(
    *,
    title: str | None,
    artist: str | None = None,
    media_type: str | None = None,
) -> str | None:
    """Map well-known album titles to the Discogs catalog when the listing has none."""
    blob = f"{artist or ''} {title or ''}"
    fold = blob.casefold()
    media = (media_type or "").casefold()
    if "germany" in fold or "netherlands" in fold or "malaysia" in fold:
        return None
    if "korea" in fold:
        if re.search(r"in brasil", fold):
            return "SZPR-096"
        return None
    if media.startswith("ep") or "7_inch" in media or "12_inch" in media:
        if _MOMOE_HINT.search(blob) and re.search(
            r"さよならの向う側|sayonara no mukougawa|31st single|31th single",
            blob,
            re.IGNORECASE,
        ):
            return "07SH-834"
        if _TERESA_HINT.search(blob) and "つぐない" in blob:
            return "07TR-1056"
        if _TERESA_HINT.search(blob) and re.search(r"best hit\s*4", blob, re.IGNORECASE):
            return "KRS-3021"
        if _ANITA_HINT.search(blob) and re.search(
            r"再展光華|in concert\s*87",
            blob,
            re.IGNORECASE,
        ):
            return "CAL-04-1060"
        if _ANITA_HINT.search(blob) and re.search(
            r"夏日耀光華|in concert\s*'?90",
            blob,
            re.IGNORECASE,
        ):
            return "CAL-04-1103"
        return None
    if not media.startswith("lp") and media not in {"", "vinyl"}:
        return None
    if _TERESA_HINT.search(blob) and not _TERESA_COMPILATION.search(blob):
        if re.search(r"\bcd\b|カセット|cassette|podh|posh", blob, re.IGNORECASE):
            return None
        for lead, couple, catno in _TERESA_ALBUM_CATNOS:
            if lead.search(blob) and couple.search(blob):
                return catno
    if not _ANITA_HINT.search(blob):
        return None
    if re.search(r"\blady\b", fold) and "1989" in blob:
        return "CAL-04-1079"
    for pattern, catno in _ANITA_ALBUM_CATNOS:
        if pattern.search(blob):
            if catno == "RR-164" and "taiwan" not in fold and "台灣" not in blob and "台湾" not in blob:
                continue
            if catno != "RR-164" and ("taiwan" in fold or "台灣" in blob or "台湾" in blob):
                continue
            return catno
    return None


def listing_identity_catalog(
    *,
    stored: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    media_type: str | None = None,
    infer: bool = True,
) -> str | None:
    """Printed title catno, then a stored catno that fits this copy, then inference."""
    stored = _catalog_text(stored) or None
    printed = catalog_token(catalog_number=None, title=title)
    if printed:
        return printed
    if stored_catalog_fits_listing(
        stored,
        title=title,
        media_type=media_type,
    ):
        token = catalog_token(catalog_number=stored, title=title)
        if token:
            return token
    if not infer:
        return None
    return inferred_release_catalog(
        title=title,
        artist=artist,
        media_type=effective_listing_media(media_type, title) or media_type,
    )


_ARTIST_ALIASES = (
    (("teresa teng",), ("テレサ", "テレサ・テン", "鄧麗君", "邓丽君")),
    (("momoe yamaguchi",), ("山口百恵", "山口百惠", "百恵", "百惠")),
    (("akina nakamori",), ("中森明菜", "明菜")),
    (("anita mui",), ("梅艷芳", "梅艳芳")),
)
_ARTIST_EQUIVALENCE_GROUPS = (
    (
        "Teresa Teng",
        "Teresa Tang",
        "Deng Lijun",
        "Deng Li Jun",
        "Teng Li Chun",
        "Teng Li-Chun",
        "テレサ",
        "テレサテン",
        "テレサ・テン",
        "鄧麗君",
        "邓丽君",
    ),
    (
        "Momoe Yamaguchi",
        "Yamaguchi Momoe",
        "Momoe",
        "山口百恵",
        "山口百惠",
        "百恵",
        "百惠",
    ),
    (
        "Anita Mui",
        "Mui Yim Fong",
        "Anita Mui Yim-Fong",
        "梅艷芳",
        "梅艳芳",
        "梅艶芳",
    ),
    (
        "Akina Nakamori",
        "Nakamori Akina",
        "中森明菜",
        "明菜",
    ),
)
_TITLE_EQUIVALENCE_GROUPS = (
    ("甜蜜蜜", "Tian Mi Mi", "TianMiMi"),
    ("酒醉的探戈", "酒酔的探戈", "Jiu Zui De Tan Ge"),
    ("一個小心願", "一个小心愿", "A Small Wish"),
    ("難忘的一天", "难忘的一天", "Nan Wang De Yi Tian"),
    ("淡淡幽情", "Dan Dan You Qing", "Dandan Youqing"),
    ("夜来香", "夜來香", "Ye Lai Xiang"),
    ("難忘初戀的情人", "难忘初恋的情人", "Unforgettable First Love"),
    (
        "赤色梅艷芳",
        "赤色梅艳芳",
        "Red Anita",
        "White&Black Splatter",
        "White & Black Splatter",
    ),
    ("別れの予感", "Premonition of Farewell", "Wakare no Yokan"),
    ("生誕70年ベスト", "70th Anniversary Best Album", "70th Anniversary", "生誕70年", "没後30年"),
    ("再會吧！十七歲", "space record vol 11", "之歌第十一集"),
    ("25週年", "25周年", "廿五周年"),
    ("何日君再来", "何日君再來", "He Ri Jun Zai Lai"),
    ("時の流れに身をまかせ", "时の流れに身をまかせ", "Toki no Nagare ni Mi wo Makase"),
    (
        "つぐない",
        "償還",
        "偿还",
        "Tsugunai",
        "Tugunai",
        "Waratte Kanpai",
        "笑って乾杯",
        "笑ってかんぱい",
    ),
    ("ビッグヒット4", "Big Hit4", "Big Hit 4", "BIG HIT4"),
    ("Best Hit 4", "Best Hit4", "BEST HIT 4"),
    ("夜のフェリーボート", "夜のフェリーポート", "赤坂たそがれ"),
    ("秋桜", "Cosmos"),
    (
        "いい日旅立ち",
        "Iihi Tabidachi",
        "IIHI DABIDACHI",
        "Ii Hi Tabidachi",
        "leaving on a good day",
    ),
    (
        "唇をうばう前に",
        "Before You Put Your Lips On",
        "Fantasy Of Love",
    ),
    ("矢切の渡し", "Yagiri no Watashi"),
    ("空港", "Kuko"),
    ("15才", "15歳", "15 sai", "15 years old"),
    ("さよならの向う側", "さよならの向こう側", "Sayonara no Mukougawa"),
    ("禁じられた遊び", "Kinjirareta Asobi"),
    ("似水流年", "Si Shui Liu Nian"),
    ("你可知道我愛誰", "你可知道我爱谁", "Ni Ke Zhi Dao Wo Ai Shui"),
    ("夜の乗客", "Yoru no Jokaku", "Yoru No Jokyaku", "Night Passenger"),
    ("女の生きがい", "女のいきがい", "Onna no Ikigai"),
    ("影視名曲精選", "影视名曲精选", "Movie Hits"),
    ("我只在乎你", "我只在乎尓", "Wo Zhi Zai Hu Ni"),
    ("星願", "星愿", "Xing Yuan"),
    ("妖女", "Evil Girl"),
    ("壞女孩", "坏女孩", "Bad Girl"),
    ("飛躍舞台", "飞跃舞台", "Jump Stage"),
    ("烈焰紅唇", "烈焰红唇", "烈燄紅唇", "烈燄红唇", "Flaming Red Lips", "Flaming Lips"),
    ("スーパーセレクション", "Super Selection"),
    ("オリジナルベストカラオケ", "Original Best Karaoke"),
    ("愛之世界", "With Love From", "With Love From Teresa Teng"),
    ("水上人", "Shuishang Ren", "Shui Shang Ren"),
    ("横須賀ストーリー", "横须贺ストーリー", "Yokosuka Story"),
    ("Again 百恵", "Again百恵"),
    ("ラストコンサート", "ラスト・コンサート", "Last Concert"),
    ("ファーストコンサート", "ファースト・コンサート", "First Concert"),
    ("百恵ライブ", "Momoe Live", "Momoe Festival"),
    ("永遠的情懷", "永遠的情懐", "永远的情怀"),
    ("島國情歌第六集", "島國情歌六", "島国情歌第六集", "小城故事"),
    ("島國之情歌第七集", "島國情歌第七集", "假如我是真的"),
    (
        "現場錄音珍藏版",
        "Encore Live",
        "Encore",
        "01/1982",
        "1982年1月9",
    ),
    ("ベスト10", "ベスト・10", "Best 10"),
    ("Golden Best", "Golden☆Best", "ゴールデン☆ベスト", "ゴールデンベスト"),
    ("ベスト20", "ベスト・20", "Best 20"),
    ("まごころ", "Anata Magokoro"),
    ("One & Only", "One and Only", "NHK Live"),
    ("漫步人生路", "A Stroll Through Life"),
    ("愛人", "Mistress", "Aijin", "Ai Jin", "あいじん"),
)


@lru_cache(maxsize=16384)
def _script_compact(value: str | None) -> str:
    """Lowercase alnum/kana/hanzi key; Traditional Hanzi folds to Simplified."""
    folded = fold_hanzi(unicodedata.normalize("NFKC", value or ""))
    return re.sub(r"[^a-z0-9\u3040-\u9fff]+", "", folded.casefold())


def _equivalence_lookup(groups: tuple[tuple[str, ...], ...]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for group in groups:
        canon = _script_compact(group[0])
        if not canon:
            continue
        for alias in group:
            key = _script_compact(alias)
            if key:
                lookup[key] = canon
    return lookup


_ARTIST_CANON = _equivalence_lookup(_ARTIST_EQUIVALENCE_GROUPS)
_TITLE_CANON = _equivalence_lookup(_TITLE_EQUIVALENCE_GROUPS)
_ARTIST_CANON_BY_LENGTH = tuple(
    alias for alias in sorted(_ARTIST_CANON, key=len, reverse=True) if alias
)
_TITLE_CANON_BY_LENGTH = tuple(
    sorted(_TITLE_CANON.items(), key=lambda item: -len(item[0]))
)


def equivalent_title_spellings(phrase: str | None) -> tuple[str, ...]:
    """Other written forms of one work, including the spelling Discogs uses."""
    target = _script_compact(phrase)
    if not target:
        return ()
    for group in _TITLE_EQUIVALENCE_GROUPS:
        if target not in {_script_compact(item) for item in group}:
            continue
        spellings: list[str] = []
        for item in group:
            if _script_compact(item) == target or item in spellings:
                continue
            spellings.append(item)
        return tuple(spellings)
    return ()


@lru_cache(maxsize=16384)
def apply_title_aliases(compact: str) -> str:
    """Rewrite known album spellings (kana vs kanji, pinyin) to one compact form."""
    if not compact:
        return ""
    rewritten = compact
    for alias, canon in _TITLE_CANON_BY_LENGTH:
        if len(alias) < 4 or alias not in rewritten:
            continue
        if alias != canon and canon in rewritten:
            rewritten = rewritten.replace(alias, "")
            continue
        rewritten = rewritten.replace(alias, canon)
    return rewritten


_TRACK_NAMED_ALBUMS = (
    (
        ("夜来香", "夜來香"),
        ("何日君再来", "何日君再來"),
        ("華麗なる熱唱",),
    ),
)


def _expand_track_named_albums(compact: str) -> str:
    """Buyee names hit songs; Discogs names the Polydor album those songs are on."""
    extra = compact
    for leads, couples, albums in _TRACK_NAMED_ALBUMS:
        lead_keys = tuple(_script_compact(lead) or lead for lead in leads)
        couple_keys = tuple(_script_compact(couple) or couple for couple in couples)
        album_keys = tuple(_script_compact(album) or album for album in albums)
        has_leads = any(lead in compact for lead in lead_keys)
        has_couples = any(couple in compact for couple in couple_keys)
        has_album = any(album in compact for album in album_keys)
        if has_leads and has_couples:
            for album in album_keys:
                if album not in extra:
                    extra += album
        if has_album:
            for lead in lead_keys:
                if lead not in extra:
                    extra += lead
            for couple in couple_keys:
                if couple not in extra:
                    extra += couple
    return extra


_ALBUM_GENERIC_TAILS = (
    "アルバム",
    "album",
    "大全集",
    "全集",
    "コレクション",
    "collection",
)
_LISTING_GEO_STEMS = frozenset(
    {
        "hongkong",
        "taiwan",
        "japan",
        "china",
        "chinese",
        "singapore",
        "malaysia",
        "indonesia",
        "korea",
        "korean",
        "香港",
        "日本",
        "中国",
        "中國",
        "台灣",
        "台湾",
    }
)
_WEAK_ALBUM_STEMS = frozenset(
    {
        "ベスト",
        "ヒット",
        "best",
        "hits",
        "thebest",
        "bestof",
        "greatesthits",
        "album",
        "アルバム",
        "collection",
        "コレクション",
        *_LISTING_GEO_STEMS,
    }
)


def bare_best_hit_title(title: str | None) -> bool:
    """ベスト・ヒット with no album word, year, or printed catalog.

    Sellers use that short name for both the 1976 Polydor LP and Original
    Best Hits. The sleeve decides which one it is.
    """
    text = str(title or "")
    folded = _script_compact(text).replace("・", "")
    if "ベストヒット" not in folded and "besthit" not in folded:
        return False
    if "アルバム" in folded or "album" in folded:
        return False
    if "オリジナル" in folded or "original" in folded:
        return False
    if re.search(r"mr\s*-?\s*3037|28\s*tr\s*-?\s*2092", text, re.IGNORECASE):
        return False
    if re.search(r"['’]\s*\d{2}|\b(?:19|20)\d{2}\b", text):
        return False
    return True


def best_hit_album_title(value: str | None) -> bool:
    """The Polydor ベスト・ヒット・アルバム, not Original Best Hits."""
    folded = _script_compact(value).replace("・", "")
    return "ベストヒットアルバム" in folded or "besthitsalbum" in folded or "besthitalbum" in folded


def _album_stems(compact: str) -> tuple[str, ...]:
    """Drop generic アルバム/collection tails so ベストヒット matches the LP."""
    variants = [compact, compact.replace("・", "")]
    stems: list[str] = []
    for variant in variants:
        stripped = variant
        if stripped and stripped not in stems:
            stems.append(stripped)
        changed = True
        while changed:
            changed = False
            stripped = stripped.rstrip("・")
            for tail in _ALBUM_GENERIC_TAILS:
                if stripped.endswith(tail) and len(stripped) > len(tail) + 2:
                    stripped = stripped[: -len(tail)].rstrip("・")
                    if stripped and stripped not in stems:
                        stems.append(stripped)
                    changed = True
                    break
    return tuple(stems)


def _strip_leading_artist_compact(compact: str) -> str:
    """Drop a Discogs artist prefix so 鄧麗君 15週年 matches a 15週年 listing."""
    if not compact:
        return compact
    for alias in _ARTIST_CANON_BY_LENGTH:
        if compact.startswith(alias) and len(compact) > len(alias) + 1:
            remainder = compact[len(alias) :]
            if remainder:
                return remainder
    return compact


_LISTING_ALBUM_JUNK = (
    "cbssony",
    "gripsweat",
    "japanese",
    "inserts",
    "insert",
    "records",
    "record",
    "cassette",
    "vinyl",
    "album",
    "japan",
    "sony",
    "cbs",
    "idol",
    "obi",
    "plus",
    "lp",
    "cd",
    "ep",
    "vg",
    "nm",
    "with",
    "original",
    "analog",
    "stereo",
    "mint",
    "used",
    "promo",
    "sealed",
    "chinese",
    "songs",
    "sunlight",
    "limited",
    "edition",
    "sealed",
    "taiwan",
    "early",
    "recording",
    "insert",
    "180g",
    "hongkong",
    "china",
    "chinese",
    "singapore",
    "malaysia",
    "indonesia",
    "korea",
    "korean",
)


@lru_cache(maxsize=16384)
def _piece_is_artist_name(piece: str) -> bool:
    """True when a compact album string is only the performer, not a work title."""
    if not piece:
        return True
    if piece in _ARTIST_CANON:
        return True
    stripped = piece
    for alias in _ARTIST_CANON_BY_LENGTH:
        if alias in stripped:
            stripped = stripped.replace(alias, "")
    return not stripped


_SELF_TITLED = re.compile(r"self\s*[- ]?titled|同名", re.IGNORECASE)


def listing_is_self_titled(title: str | None) -> bool:
    """True when the seller means the album is named after the artist."""
    return bool(_SELF_TITLED.search(title or ""))


def artist_local_name(artist: str | None) -> str | None:
    """CJK name Discogs uses for a self-titled Anita / Teresa / Momoe album."""
    key = canonical_artist_key(artist)
    if not key:
        return None
    for latin, local_names in _ARTIST_ALIASES:
        names = (latin[0], *local_names)
        if any(canonical_artist_key(name) == key for name in names):
            return local_names[0]
    return None


def _self_titled_album_matches(title: str | None, display_title: str | None) -> bool:
    """梅艷芳 matches a self-titled listing. The later album titled Anita does not."""
    if not listing_is_self_titled(title):
        return False
    listing = _script_compact(title)
    album = str(display_title or "")
    if " - " in album:
        left, right = album.split(" - ", 1)
        if _piece_is_artist_name(_script_compact(left)):
            album = right
    sides = [album]
    for side in sides:
        for part in re.split(r"\s*=\s*", side):
            key = _script_compact(part)
            if not key or key not in _ARTIST_CANON:
                continue
            canon = _ARTIST_CANON[key]
            if any(
                alias in listing and _ARTIST_CANON.get(alias) == canon
                for alias in _ARTIST_CANON
            ):
                return True
    return False


def _known_album_match_keys() -> tuple[tuple[str, str], ...]:
    """Compact album spellings, longest-match order, built once."""
    entries: list[tuple[str, str]] = []
    for group in _TITLE_EQUIVALENCE_GROUPS:
        canon = _script_compact(group[0])
        if not canon or _piece_is_artist_name(canon):
            continue
        for alias in group:
            key = _script_compact(alias)
            if len(key) >= 2:
                entries.append((key, group[0]))
    return tuple(entries)


_KNOWN_ALBUM_KEYS = _known_album_match_keys()


@lru_cache(maxsize=4096)
def _compact_contains_album_key(compact: str, key: str) -> bool:
    """True when the album key is present and not a prefix of a longer number.

    ``best10`` is inside ``best100``. That is The Best 100, not Best 10.
    """
    start = 0
    while True:
        index = compact.find(key, start)
        if index < 0:
            return False
        after = compact[index + len(key) : index + len(key) + 1]
        if after.isdigit() and key[-1:].isdigit():
            start = index + 1
            continue
        return True


def known_album_phrase(title: str | None) -> str | None:
    """Album spelling to send Discogs, ignoring seller junk and a cut-off last character."""
    compact = _script_compact(title)
    if not compact:
        return None
    best_key = ""
    best_phrase = ""
    for key, phrase in _KNOWN_ALBUM_KEYS:
        if _compact_contains_album_key(compact, key) and len(key) > len(best_key):
            best_key = key
            best_phrase = phrase
    if best_phrase:
        return best_phrase
    for key, phrase in _KNOWN_ALBUM_KEYS:
        if len(key) >= 5 and _compact_contains_album_key(compact, key[:-1]):
            return phrase
    return None


def hit_bundles_other_album(listing_title: str | None, display_title: str | None) -> bool:
    """A sleeve titled 別れの予感 is not the cassingle that also names 時の流れ."""
    named = known_album_phrase(listing_title)
    if not named:
        return False
    named_key = _script_compact(named)
    compact = apply_title_aliases(_script_compact(display_title))
    if not named_key or not compact:
        return False
    for group in _TITLE_EQUIVALENCE_GROUPS:
        canon = _script_compact(group[0])
        if not canon or canon == named_key or len(canon) < 3:
            continue
        if canon in compact:
            return True
    return False


def listing_names_specific_album(title: str | None) -> bool:
    """True when the listing names a work, not just the artist or Stereo Sound."""
    if listing_is_self_titled(title):
        return True
    if known_album_phrase(title):
        return True
    text = title or ""
    if re.search(r"巨星名曲\s*\d", text):
        return True
    if re.search(r"made\s+in\s+germany", text, re.IGNORECASE) and re.search(
        r"teresa|鄧麗君|邓丽君",
        text,
        re.IGNORECASE,
    ):
        return True
    return bool(re.search(r"greatest\s+hits", text, re.IGNORECASE))


def _piece_is_artist_fragment(piece: str, listing_compact: str) -> bool:
    """anita is inside Anita Mui. That is the artist, not the album titled Anita."""
    if not piece or _piece_is_artist_name(piece):
        return False
    for alias in _ARTIST_CANON:
        if len(alias) <= len(piece) or piece not in alias or alias not in listing_compact:
            continue
        remainder = listing_compact.replace(alias, "", 1)
        if piece not in remainder:
            return True
    return False


def _discogs_album_is_artist_only(display_title: str | None) -> bool:
    album = str(display_title or "")
    if " - " in album:
        album = album.split(" - ", 1)[-1]
    return _piece_is_artist_name(apply_title_aliases(_script_compact(album)))


_LISTING_ALBUM_JUNK_BY_LENGTH = tuple(
    sorted(_LISTING_ALBUM_JUNK, key=len, reverse=True)
)


def _listing_leftover_album_compact(title: str | None) -> str:
    leftover = _script_compact(title)
    for alias in _ARTIST_CANON_BY_LENGTH:
        leftover = leftover.replace(alias, "")
    for junk in _LISTING_ALBUM_JUNK_BY_LENGTH:
        leftover = leftover.replace(junk, "")
    return re.sub(r"\d+", "", leftover)


_SECOND_TITLE_NOISE = (
    "ファーストプレス",
    "ライナーノーツ",
    "歌詞カード",
    "ポスター",
    "シュリンク",
    "ジャケット",
    "オリジナル",
    "プロモ盤",
    "白ラベル",
    "見本品",
    "見本盤",
    "国内盤",
    "帯付き",
    "帯付",
    "美盤",
    "美品",
    "インサート",
    "レコード",
    "アナログレコード",
    "アナログ盤",
    "アナログ",
    "ブックレット",
    "見開き",
    "カラーポート",
    "未開封",
    "未使用",
    "新品",
    "カセットテープ",
    "ポリドール",
    "黑膠唱片",
    "黒膠唱片",
    "黑胶唱片",
    "サンプル",
    "ライナー",
)


def listing_names_other_work(title: str | None, matched_title: str | None) -> bool:
    """True when the listing names a second work beside the matched album.

    ``愛をあなたに ふるさとはどこですか`` is two records. Matching the second
    name must not ignore the first.
    """
    album = str(matched_title or "")
    if " - " in album:
        album = album.split(" - ", 1)[-1]
    text = str(title or "")
    if re.search(r"7\s*inch|7inch|\bep\b|シングル|single", text, re.IGNORECASE):
        return False
    album_key = _script_compact(album)
    if len(re.findall(r"[\u3040-\u9fff]", album_key)) < 4:
        return False
    listing_key = _script_compact(text)
    album_parts = [
        _script_compact(part)
        for part in re.split(r"[/／]", album)
        if _script_compact(part)
    ]
    if album_key not in listing_key and not any(part in listing_key for part in album_parts):
        return False
    leftover = _listing_leftover_album_compact(title)
    for key in (album_key, *(re.sub(r"\d+", "", key) for key in (album_key, *album_parts))):
        if key and key in leftover:
            leftover = leftover.replace(key, "")
    for noise in _SECOND_TITLE_NOISE:
        leftover = leftover.replace(_script_compact(noise), "")
    if re.search(r"第[0-9一二三四五六七八九十]+集|全集|特輯|紀念|精選|選集", leftover):
        return False
    phrases = re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]{4,16}", leftover)
    if len(phrases) != 1:
        return False
    # 女のいきがい is the same title as 女の生きがい. A second album shares no words.
    compared = album_key + "".join(album_parts)
    phrase = phrases[0]
    grams = {phrase[index : index + 2] for index in range(len(phrase) - 1)}
    return not any(
        compared[index : index + 2] in grams for index in range(len(compared) - 1)
    )


def concert_program_key(text: str | None) -> str | None:
    """First Concert / Last Concert, including Discogs Part II / 後編 titles."""
    compact = apply_title_aliases(_script_compact(text))
    if "ファーストコンサート" in compact or "firstconcert" in compact:
        return "firstconcert"
    if "ラストコンサート" in compact or "lastconcert" in compact:
        return "lastconcert"
    return None


def concert_program_related(
    listing_title: str | None,
    discogs_title: str | None,
) -> bool:
    """Part II / 後編 is the same concert program when the listing omits the part."""
    left = concert_program_key(listing_title)
    right = concert_program_key(discogs_title)
    return bool(left and left == right)


def album_name_in_listing(title: str | None, display_title: str | None) -> bool:
    """True when a Discogs album spelling is inside the listing title."""
    if bare_best_hit_title(title) and best_hit_album_title(display_title):
        return False
    listing = _expand_track_named_albums(apply_title_aliases(_script_compact(title)))
    listing_plain = listing.replace("・", "")
    leftover = _listing_leftover_album_compact(title)
    named_album = known_album_phrase(title)
    if not listing and not named_album:
        return False
    if (
        named_album
        and _discogs_album_is_artist_only(display_title)
        and not listing_is_self_titled(title)
    ):
        return False
    if (
        re.search(r"made\s+in\s+germany", title or "", re.IGNORECASE)
        and re.search(r"teresa|鄧麗君|邓丽君", title or "", re.IGNORECASE)
        and re.search(r"25\s*[週周]年|廿五周年", display_title or "")
    ):
        return True
    if named_album:
        named_key = _script_compact(named_album)
        album_side = apply_title_aliases(_script_compact(display_title))
        if (
            named_key
            and named_key in album_side
            and not _volume_blocks_album_match(title, display_title)
        ):
            return True
    if _self_titled_album_matches(title, display_title):
        return True
    if _discogs_album_is_artist_only(display_title):
        listing_cf = (title or "").casefold()
        if listing_names_specific_album(title):
            return False
        if "stereo sound" in listing_cf or re.search(r"\bssar-?\d+", listing_cf):
            return True
        return len(leftover) < 4
    album = str(display_title or "")
    candidates: list[str] = []
    if " - " in album:
        left, right = album.split(" - ", 1)
        left_clean = re.sub(r"[（(][^）)]*[）)]", " ", left).replace("*", " ")
        left_bits = [
            bit
            for bit in re.split(r"\s*=\s*", left_clean)
            if _script_compact(bit)
        ] or [left]
        left_keys = [
            apply_title_aliases(_script_compact(bit)) for bit in left_bits
        ]
        matched_canons = {
            canon
            for alias, canon in _ARTIST_CANON.items()
            if any(key == canon or key == alias for key in left_keys)
        }
        artist_aliases = [
            alias
            for alias, canon in _ARTIST_CANON.items()
            if canon in matched_canons
        ]

        def _credit_is_artist(key: str) -> bool:
            if _piece_is_artist_name(key):
                return True
            return any(key and key in alias and len(alias) > len(key) for alias in artist_aliases)

        left_is_artist = bool(left_keys) and all(_credit_is_artist(key) for key in left_keys)
        if left_is_artist:
            candidates.append(right)
        else:
            candidates.extend([album, left, right])
    else:
        candidates.append(album)
    expanded: list[str] = []
    for part in candidates:
        expanded.append(part)
        expanded.extend(re.split(r"\s*=\s*", part))
    candidates = expanded
    candidates.extend(
        re.sub(r"[（(][^）)]+[）)]", "", part) for part in list(candidates)
    )
    candidates.extend(
        piece
        for part in list(candidates)
        for piece in re.split(r"[~〜]+", part)
        if piece.strip()
    )
    candidates.extend(
        piece
        for part in list(candidates)
        for piece in re.split(r"[-－]", part)
        if piece.strip()
    )
    candidates.extend(
        piece.strip()
        for part in list(candidates)
        for piece in re.split(r"[/／]", part)
        if 2 <= len(_script_compact(piece)) <= 16
    )
    for candidate in candidates:
        compact = apply_title_aliases(_script_compact(candidate))
        if not compact:
            continue
        if _piece_is_artist_name(compact):
            continue
        pieces = [compact]
        remainder = _strip_leading_artist_compact(compact)
        if remainder != compact:
            pieces.append(remainder)
        for piece in pieces:
            if named_album:
                named_key = _script_compact(named_album)
                folded_piece = apply_title_aliases(piece)
                listed_album = known_album_phrase(piece)
                listed_key = _script_compact(listed_album) if listed_album else ""
                piece_names_this_album = bool(named_key) and named_key in folded_piece
                piece_names_another_listed_album = bool(
                    listed_key and listed_key in listing
                )
                if named_key and not (
                    piece_names_this_album or piece_names_another_listed_album
                ):
                    continue
            if _piece_is_artist_name(piece):
                continue
            if _piece_is_artist_fragment(piece, listing):
                continue
            has_cjk = bool(re.search(r"[\u3040-\u9fff]", piece))
            if len(piece) < (2 if has_cjk else 4):
                continue
            latin = re.sub(r"[^a-z0-9]+", "", piece)
            geo_piece = piece in _LISTING_GEO_STEMS or latin in _LISTING_GEO_STEMS
            if geo_piece:
                if named_album:
                    continue
                if leftover and (
                    piece in leftover or (len(latin) >= 2 and latin in leftover)
                ):
                    if not _volume_blocks_album_match(title, display_title):
                        return True
                continue
            if piece in leftover or piece.replace("・", "") in leftover:
                if not _volume_blocks_album_match(title, display_title):
                    return True
            if leftover and len(latin) >= 5 and latin in leftover:
                if not _volume_blocks_album_match(title, display_title):
                    return True
            if piece in listing or piece.replace("・", "") in listing_plain:
                if not _volume_blocks_album_match(title, display_title):
                    return True
        has_cjk = bool(re.search(r"[\u3040-\u9fff]", compact))
        if len(compact) < (2 if has_cjk else 4):
            continue
        for stem in _album_stems(remainder or compact):
            if _piece_is_artist_name(stem):
                continue
            stem_cjk = bool(re.search(r"[\u3040-\u9fff]", stem))
            min_len = 4 if stem_cjk else 8
            plain = stem.replace("・", "")
            if (
                len(plain) >= min_len
                and plain not in _WEAK_ALBUM_STEMS
                and not _piece_is_artist_name(plain)
                and (stem in listing or plain in listing_plain)
                and not _volume_blocks_album_match(title, display_title)
            ):
                return True
        listing_key = canonical_title_key(title)
        album_key = canonical_title_key(candidate)
        if (
            listing_key
            and album_key
            and listing_key == album_key
            and len(listing_key) >= 8
            and listing_key not in {"greatesthits", "thebest", "bestof"}
        ):
            return True
    return _album_volume_agrees(title, display_title)


def _volume_blocks_album_match(title: str | None, display_title: str | None) -> bool:
    """Vol. 16 / 之歌第十六集 is not the unnumbered 鄧麗君之歌 compilation."""
    wanted = listing_volume_number(title)
    if wanted is None:
        return False
    actual = listing_volume_number(display_title)
    if actual is not None and actual != wanted:
        return True
    return actual is None and is_generic_songbook_album(display_title)


def _songbook_volume_allows_hit(title: str | None, hit: SearchHit) -> bool:
    """Yeu Jow vol 16 is often titled 戀愛的路多麼甜, with 第十六集 only in Discogs search."""
    if not re.search(r"之歌第", title or ""):
        return False
    wanted = listing_volume_number(title)
    if wanted is None:
        return False
    actual = listing_volume_number(hit.title)
    if actual is not None and actual != wanted:
        return False
    if is_generic_songbook_album(hit.title):
        return actual == wanted
    return True


def _album_volume_agrees(title: str | None, display_title: str | None) -> bool:
    """Same series: Space Record vol 11 sits with 鄧麗君之歌, Best Vol. 4 with Best."""
    listing_cf = (title or "").casefold()
    album_text = display_title or ""
    album_cf = album_text.casefold()
    if re.search(r"space\s+records?", listing_cf) and (
        "之歌第" in album_text or "宇宙" in album_text
    ):
        listing_vol = listing_volume_number(title)
        album_vol = listing_volume_number(display_title)
        if listing_vol is None or album_vol is None or listing_vol == album_vol:
            return True
    listing_vol = listing_volume_number(title)
    album_vol = listing_volume_number(display_title)
    if listing_vol is None or listing_vol != album_vol:
        return False
    if re.search(r"\bbest\b", listing_cf) and re.search(r"\bbest\b", album_cf):
        return True
    if "stereo sound" in listing_cf:
        return True
    return False


def shortlist_agrees_with_listing(
    title: str | None,
    shortlist: Sequence[Any],
    token: str | None = None,
) -> bool:
    """True when a stored card is this copy's catno or album name."""
    if not shortlist:
        return False
    for hit in shortlist:
        if isinstance(hit, SearchHit):
            display = hit.title
            catno = hit.catno
        elif isinstance(hit, dict):
            display = str(hit.get("title") or "")
            catno = str(hit.get("catno") or "")
        else:
            display = str(getattr(hit, "title", "") or "")
            catno = str(getattr(hit, "catno", "") or "")
        if token and catno_locks_listing(catno, token):
            return True
        if display and album_name_in_listing(title, display):
            return True
        if display and _songbook_volume_allows_hit(
            title,
            SearchHit(
                discogs_id=0,
                title=display,
                catno=catno,
                year=None,
                country=None,
                formats=(),
                labels=(),
                thumb_url=None,
                uri=None,
            ),
        ):
            return True
    return False


def canonical_artist_key(value: str | None) -> str:
    """English / kana / Hanzi / pinyin artist names collapse to one family key."""
    compact = _script_compact(value)
    if not compact:
        return ""
    return _ARTIST_CANON.get(compact, compact)


def canonical_title_key(value: str | None) -> str:
    """Album title key across English, Japanese, Canto/Mandarin, and pinyin."""
    text = (value or "").strip()
    if " - " in text:
        left, right = text.split(" - ", 1)
        if canonical_artist_key(left) or len(left) <= 48:
            text = right
    compact = _script_compact(text)
    if not compact:
        return ""
    mapped = _TITLE_CANON.get(compact)
    if mapped:
        return mapped[:32]
    contained = [
        (compact.find(alias), -len(alias), canon)
        for alias, canon in _TITLE_CANON.items()
        if len(alias) >= 4 and alias in compact
    ]
    if contained:
        contained.sort()
        return contained[0][2][:32]
    return compact[:32]


def _is_known_album_title(value: str | None) -> bool:
    compact = _script_compact(value)
    if compact and compact in _TITLE_CANON:
        return True
    stripped = re.sub(
        r"(?:lp|ep|cd|dvd|vinyl|cassette|tape)$",
        "",
        compact or "",
        flags=re.IGNORECASE,
    )
    return bool(stripped) and stripped in _TITLE_CANON


def _is_known_artist_name(value: str | None) -> bool:
    compact = _script_compact(value)
    return bool(compact) and compact in _ARTIST_CANON


def artist_overlaps(
    *,
    listing_artist: str | None,
    listing_title: str | None,
    discogs_names: Sequence[str],
) -> bool:
    """True when a Discogs artist or ANV token appears on the listing."""
    blob = f"{listing_artist or ''} {listing_title or ''}"
    blob_cf = blob.casefold()
    blob_fold = fold_hanzi(blob)
    listing_artist_key = canonical_artist_key(listing_artist) or canonical_artist_key(
        listing_search_artist(listing_artist, listing_title)
    )
    if not blob_cf.strip():
        return False
    tracked_artist = bool(listing_artist_key) and listing_artist_key in set(
        _ARTIST_CANON.values()
    )
    if tracked_artist:
        # "Rebirth" in the title is the album, not proof the artist is Rebirth (10).
        for raw_name in discogs_names:
            cleaned = _clean_artist_name(raw_name)
            if not cleaned:
                continue
            if canonical_artist_key(cleaned) == listing_artist_key:
                return True
            compact = _script_compact(cleaned)
            if any(
                alias in compact and _ARTIST_CANON.get(alias) == listing_artist_key
                for alias in _ARTIST_CANON
            ):
                return True
        return False

    for raw_name in discogs_names:
        cleaned = _clean_artist_name(raw_name)
        if not cleaned:
            continue
        if listing_artist_key and canonical_artist_key(cleaned) == listing_artist_key:
            return True
        if cleaned in blob or cleaned.casefold() in blob_cf:
            return True
        if fold_hanzi(cleaned) in blob_fold:
            return True
        for token in _TOKEN_SPLIT.split(cleaned):
            if len(token) >= 4 and token.casefold() in blob_cf:
                return True
    names_joined = " ".join(
        _clean_artist_name(name) or ""
        for name in discogs_names
    )
    names_cf = names_joined.casefold()
    for latin_names, local_names in _ARTIST_ALIASES:
        discogs_hit = any(latin in names_cf for latin in latin_names) or any(
            local in names_joined for local in local_names
        )
        listing_hit = any(latin in blob_cf for latin in latin_names) or any(
            local in blob for local in local_names
        )
        if discogs_hit and listing_hit:
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
                thumb_url=_optional_text(row.get("cover_image") or row.get("thumb")),
                uri=_optional_text(row.get("uri")),
            )
        )
    return tuple(parsed)


_SEARCH_ARTIST_ALIASES: dict[str, tuple[str, ...]] = {
    "teresa teng": ("Teresa Teng", "テレサ・テン", "テレサテン", "鄧麗君", "邓丽君"),
    "momoe yamaguchi": ("Momoe Yamaguchi", "山口百恵", "山口百惠"),
    "anita mui": ("Anita Mui", "梅艷芳", "梅艳芳"),
    "akina nakamori": ("Akina Nakamori", "中森明菜"),
}


def release_belongs_to_artist(hit: SearchHit, artist_name: str | None) -> bool:
    """True when this Discogs row is the listing artist, not another name on the same prefix."""
    if not artist_name:
        return True
    aliases = _SEARCH_ARTIST_ALIASES.get(artist_name.casefold(), (artist_name,))
    title = hit.title or ""
    folded = title.casefold()
    return any(alias.casefold() in folded for alias in aliases)


def names_from_search_hit(hit: SearchHit) -> tuple[str, ...]:
    """Best-effort artist names from a search title (`Artist - Title`)."""
    title = hit.title
    if " - " not in title:
        return (title,) if title else ()
    left = title.split(" - ", 1)[0]
    parts = [left]
    parts.extend(re.split(r"\s*/\s*|\s*&\s*", left))
    return tuple(_clean_artist_name(part) for part in parts if _clean_artist_name(part))


_CATALOG_STEM_WORDS = frozenset(
    {
        "album",
        "best",
        "blue",
        "disc",
        "folk",
        "gold",
        "hits",
        "japan",
        "jazz",
        "live",
        "love",
        "obi",
        "pop",
        "promo",
        "rock",
        "soul",
        "vinyl",
    }
)


def query_looks_like_catalog(value: str | None) -> bool:
    """True for a typed pressing number, not an album name."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or len(text) > 32 or len(text.split()) > 2:
        return False
    compact = re.sub(r"[\s\-]", "", text)
    if not 4 <= len(compact) <= 16:
        return False
    return bool(re.search(r"\d", compact) and re.search(r"[A-Za-z]", compact))


def query_is_catalog_stem(value: str | None) -> bool:
    """True for a sleeve prefix such as SSAR. Discogs files that on the catno, not the title."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or " " in text:
        return False
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters.casefold() != text.casefold() or letters.casefold() in _CATALOG_STEM_WORDS:
        return False
    return 3 <= len(letters) <= 8


def user_search_format(media_type: str | None) -> str | None:
    """Discogs format for a typed search. An LP search asks for LPs."""
    label = listing_format_label(media_type)
    if label == "LP":
        return "LP"
    if label == 'EP / 7"':
        return '7"'
    if label == '12"':
        return '12"'
    return discogs_search_format(media_type)


def _label_catno_for_query(payload: Mapping[str, Any], typed: str) -> str | None:
    """Label catalog that is the number the user typed.

    Discogs search often returns a soundtrack with a blank catno. The number
    is on the release label, as with 樂風 LFLP 269.
    """
    for label in payload.get("labels") or []:
        if not isinstance(label, Mapping):
            continue
        catno = str(label.get("catno") or "").strip()
        if catno and catno_locks_listing(catno, typed):
            return catno
    return None


def _confirm_typed_catalog_hits(
    client: Any,
    hits: Sequence[SearchHit],
    typed: str,
) -> list[SearchHit]:
    """Keep rows whose release label is this catalog.

    A catno search can match a Various soundtrack the listing artist only
    appears on. Those search rows omit catno, so the release label decides.
    """
    confirmed: list[SearchHit] = []
    fetches = 0
    getter = getattr(client, "get_release", None)
    for hit in hits:
        if catno_locks_listing(hit.catno, typed):
            confirmed.append(hit)
            continue
        if getter is None or fetches >= 15:
            continue
        fetches += 1
        try:
            payload = getter(hit.discogs_id)
        except Exception as exc:
            if exc.__class__.__name__ == "DiscogsRateLimitError":
                raise
            continue
        if not isinstance(payload, Mapping):
            continue
        catno = _label_catno_for_query(payload, typed)
        if catno:
            confirmed.append(replace(hit, catno=catno))
    return confirmed


def search_user_catalog(
    client: Any,
    *,
    artist: str | None,
    title: str | None,
    query: str,
    listing_media: str | None,
) -> list[dict[str, Any]]:
    """Search Discogs for the catalog or album the user typed.

    Same-format releases come first. A catalog that only exists in another
    format is still returned, so the user can override the listing media.
    A typed catalog is also searched with no artist, because Discogs files
    some copies under Appearances: the soundtrack artist is Various, and
    the listing artist is only a track credit.
    """
    typed = re.sub(r"\s+", " ", str(query or "")).strip()
    if len(typed) < 2:
        return []
    artist_name = listing_search_artist(artist, title)
    format_name = user_search_format(listing_media)
    # Capital Artists files 烈焰紅唇 as 梅艷芳, catno CAL-04-1056.
    # The album name is not on that LP, so a title search never returns it.
    known_catno = None
    if known_album_phrase(typed):
        known_catno = inferred_release_catalog(
            title=typed,
            artist=artist,
            media_type=listing_media,
        )
        if known_catno is None and known_album_phrase(title) == known_album_phrase(typed):
            known_catno = inferred_release_catalog(
                title=title,
                artist=artist,
                media_type=listing_media,
            )
    found: list[SearchHit] = []
    if known_catno:
        found.extend(
            client.search_releases(
                catno=known_catno,
                format_name=None,
            )
        )
    if query_looks_like_catalog(typed):
        found.extend(
            client.search_releases(
                catno=typed,
                artist=artist_name,
                format_name=format_name,
            )
        )
        if not found:
            found.extend(
                client.search_releases(
                    catno=typed,
                    artist=artist_name,
                    format_name=None,
                )
            )
        # Artist + catalog misses a soundtrack filed under Various.
        # LFLP 269 is 彩雲飛, credited to 左宏元, with Teresa Teng on a track.
        if not any(catno_locks_listing(hit.catno, typed) for hit in found):
            bare = client.search_releases(
                catno=typed,
                artist=None,
                format_name=None,
            )
            found.extend(_confirm_typed_catalog_hits(client, bare, typed))
    else:
        # SSAR is a catalog prefix. title=SSAR matches unrelated words
        # and never the Stereo Sound LPs the Discogs site returns for ssar.
        if query_is_catalog_stem(typed):
            # A prefix such as SSAR is a whole series. Stay on this artist.
            found.extend(
                client.search_releases(
                    catno=typed,
                    artist=artist_name,
                    format_name=None,
                )
            )
            found.extend(
                client.search_releases(
                    query=typed,
                    artist=artist_name,
                    format_name=None,
                )
            )
        # One spelling is not the whole album. 淡淡幽情 and Dan Dan You Qing
        # are the same record, and Discogs files them under either name.
        # A stem such as SSAR already came back from the catalog search.
        spellings = [] if found and query_is_catalog_stem(typed) else [typed]
        for extra in equivalent_title_spellings(typed):
            if extra not in spellings:
                spellings.append(extra)
        for spelling in spellings[:4]:
            found.extend(
                client.search_releases(
                    artist=artist_name,
                    title=spelling,
                    format_name=None,
                )
            )
        if not found:
            for spelling in spellings[:4]:
                words = f"{artist_name or ''} {spelling}".strip()
                found.extend(
                    client.search_releases(
                        query=words[:100],
                        format_name=None,
                    )
                )
    typed_catalog = query_looks_like_catalog(typed)
    if artist_name:
        found = [
            hit
            for hit in found
            if (
                typed_catalog and catno_locks_listing(hit.catno, typed)
            )
            or release_belongs_to_artist(hit, artist_name)
        ]
    ordered: list[SearchHit] = []
    seen: set[int] = set()
    catalog_match: list[SearchHit] = []
    compatible: list[SearchHit] = []
    other: list[SearchHit] = []
    stem = re.sub(r"[^A-Z]", "", typed.upper()) if query_is_catalog_stem(typed) else ""
    for hit in found:
        if hit.discogs_id in seen:
            continue
        seen.add(hit.discogs_id)
        same_format = listing_media_compatible(listing_media, " ".join(hit.formats))
        catno_key = fold_catalog(hit.catno)
        if known_catno and catno_locks_listing(hit.catno, known_catno) and same_format:
            catalog_match.append(hit)
        elif typed_catalog and catno_locks_listing(hit.catno, typed) and same_format:
            catalog_match.append(hit)
        elif stem and catno_key.startswith(stem) and same_format:
            catalog_match.append(hit)
        elif same_format:
            compatible.append(hit)
        else:
            other.append(hit)
    ordered.extend(catalog_match)
    ordered.extend(compatible)
    ordered.extend(other)
    return shortlist_payload(ordered)


def discogs_search_format(media_type: str | None) -> str | None:
    """Return the Discogs format filter, or None when the listing is not a record."""
    media = (media_type or "").casefold()
    if media in {
        "magazine",
        "photo",
        "print",
        "photobook",
        "stamp",
        "usb",
        "sheet_music",
        "toy",
    }:
        return None
    if media in {"ep_7_inch", "7_inch"}:
        return "7\""
    if media in {"single_12_inch", "12_inch_single"}:
        return "12\""
    if media.startswith("cassette") or "tape" in media:
        return "Cassette"
    if (
        media.startswith("cd")
        or media in {"mixed_media", "shm_cd", "sacd", "blu_spec_cd"}
    ):
        return "CD"
    if media.startswith("dvd"):
        return "DVD"
    if "laserdisc" in media:
        return "Laserdisc"
    return "Vinyl"


def filter_hits(
    hits: Sequence[SearchHit],
    *,
    token: str | None,
    media_type: str | None,
    prefer_japan: bool = False,
    prefer_country: str | None = None,
) -> tuple[SearchHit, ...]:
    """Keep vinyl/LP (or listing media) hits whose catno folds to the token."""
    wanted = fold_catalog(token)
    remaining = [
        hit
        for hit in hits
        if _keeps_media(hit.formats, media_type)
        and (not wanted or fold_catalog(hit.catno) == wanted)
    ]
    country = (prefer_country or ("japan" if prefer_japan else None) or "").casefold()
    if country:
        country_only = [
            hit
            for hit in remaining
            if country in (hit.country or "").casefold()
        ]
        if country_only:
            remaining = country_only
    return tuple(remaining)


_PROMO_HINT = re.compile(
    r"見本盤|見本品|プロモ|white\s*label|\bpromo\b|\bsample\b",
    re.IGNORECASE,
)


def listing_is_promo(title: str | None) -> bool:
    """True when the seller marked this copy プロモ, 見本, or promo."""
    return bool(_PROMO_HINT.search(str(title or "")))


def original_pressing_for_promo_copy(
    title: str | None,
    *,
    listing_media: str | None,
    current_catalog: str | None,
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """A promo copy of an original stays on that catalog, not a later repress.

    プロモ / 見本 on a Taurus-era title is the original catalog (28TR-2145),
    not the Universal UPJY reprint. A title that itself prints the reissue
    catalog is left where the seller put it.
    """
    if not listing_is_promo(title) or not listing_wants_original_pressing(title):
        return None
    if not is_modern_reissue_catalog(current_catalog):
        return None
    listing_shape = vinyl_shape(listing_media)
    fitting: list[Mapping[str, Any]] = []
    for row in candidates:
        catalog = str(row.get("catalog_number") or "")
        if is_modern_reissue_catalog(catalog):
            continue
        if not album_name_in_listing(title, str(row.get("display_title") or "")):
            continue
        if not listing_media_compatible(listing_media, str(row.get("media_type") or "")):
            continue
        # A bare "Vinyl" row is often a 7". An LP promo stays on an LP.
        if listing_shape in {"lp", "seven", "twelve"} and vinyl_shape(
            str(row.get("media_type") or "")
        ) != listing_shape:
            continue
        fitting.append(row)
    if not fitting:
        return None

    def _rank(row: Mapping[str, Any]) -> tuple[int, int, int, int]:
        generation = str(row.get("generation") or "").upper()
        promo_rank = 0 if generation == "PROMO" else 1
        shape = vinyl_shape(str(row.get("media_type") or ""))
        shape_rank = 0 if listing_shape == shape else 1
        try:
            year_rank = int(row.get("release_year"))
        except (TypeError, ValueError):
            year_rank = 9999
        try:
            ident = int(row.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        return (promo_rank, shape_rank, year_rank, ident)

    return min(fitting, key=_rank)


def _format_blob(hit: SearchHit) -> str:
    return " ".join(hit.formats).casefold()


def _prefer_listing_edition(
    hits: Sequence[SearchHit],
    title: str | None,
) -> tuple[SearchHit, ...]:
    """Prefer promo hits for 見本盤 listings, retail otherwise."""
    if not hits:
        return ()
    if _PROMO_HINT.search(title or ""):
        promo = tuple(
            hit
            for hit in hits
            if "promo" in _format_blob(hit) or "white label" in _format_blob(hit)
        )
        if promo:
            return promo
        return tuple(hits)
    retail = tuple(
        hit
        for hit in hits
        if "promo" not in _format_blob(hit) and "white label" not in _format_blob(hit)
    )
    selected = retail or tuple(hits)
    token = catalog_token(catalog_number=None, title=title)
    if token and catalog_has_range(token):
        ranged = tuple(hit for hit in selected if catalog_has_range(hit.catno))
        if ranged:
            return ranged
    return selected


def _title_search_edition_lock(
    chosen: SearchHit,
    ordered: Sequence[SearchHit],
    *,
    title: str | None,
    artist: str | None,
) -> bool:
    """True when promo or preferred country uniquely names this Discogs copy."""
    edition = _prefer_listing_edition(ordered, title)
    if (
        edition
        and chosen.discogs_id == edition[0].discogs_id
        and len(edition) < len(tuple(ordered))
        and (
            len(edition) == 1
            or _unique_shortlist_catno(edition)
            or bool(_PROMO_HINT.search(title or ""))
        )
    ):
        return True
    country = listing_preferred_country(
        listing_title=title,
        listing_artist=artist,
    )
    if not country:
        return False
    matching = [
        hit
        for hit in ordered
        if (hit.country or "").casefold() == country.casefold()
    ]
    return (
        bool(matching)
        and chosen.discogs_id == matching[0].discogs_id
        and (len(matching) == 1 or _unique_shortlist_catno(matching))
    )


def _release_album_key(hit: SearchHit) -> str:
    """Folded album title after the Discogs `Artist - Title` split."""
    return canonical_title_key(hit.title)


def _choose_title_search_hit(
    hits: Sequence[SearchHit],
    title: str | None = None,
) -> SearchHit | None:
    """Auto-pick a unique hit, listing-title album, shared catno, or majority."""
    if not hits:
        return None
    listing_key = canonical_title_key(title)
    if listing_key and len(listing_key) >= 4:
        matched = [
            hit
            for hit in hits
            if canonical_title_key(hit.title) == listing_key
            or album_name_in_listing(title, hit.title)
        ]
        if matched:
            return matched[0]
    if len(hits) == 1 and album_name_in_listing(title, hits[0].title):
        return hits[0]
    counts = Counter(
        fold_catalog(hit.catno) for hit in hits if fold_catalog(hit.catno)
    )
    if counts:
        top, count = counts.most_common(1)[0]
        if count >= 2:
            cluster = [hit for hit in hits if fold_catalog(hit.catno) == top]
            return cluster[0]
    keys = Counter(
        _release_album_key(hit) for hit in hits if _release_album_key(hit)
    )
    if not keys:
        return None
    top_key, count = keys.most_common(1)[0]
    if count * 2 < len(hits) or count < 2:
        return None
    cluster = [hit for hit in hits if _release_album_key(hit) == top_key]
    return cluster[0]


def listing_label_hints(
    *,
    title: str | None,
    label: str | None = None,
) -> tuple[str, ...]:
    """Label tokens mentioned on the listing, used to break same-album shortlists."""
    blob = f"{title or ''} {label or ''}"
    found: list[str] = []
    for pattern, hint in _LISTING_LABEL_HINTS:
        if pattern.search(blob) and hint not in found:
            found.append(hint)
    return tuple(found)


def _is_twelve_inch(hit: SearchHit) -> bool:
    formats = " ".join(hit.formats)
    blob = formats.casefold()
    if "lp" in blob or "album" in blob:
        return False
    return (
        "12\"" in formats
        or "12'" in blob
        or "12”" in blob
        or "12 inch" in blob
        or "maxi" in blob
    )


def _is_seven_inch(hit: SearchHit) -> bool:
    if catalog_implies_seven_inch(hit.catno):
        return True
    if _is_twelve_inch(hit):
        return False
    formats = " ".join(hit.formats)
    blob = formats.casefold()
    sized = (
        "7\"" in formats
        or "7'" in blob
        or "7”" in blob
        or "7 inch" in blob
        or (
            "single" in blob
            and "12" not in blob
            and "maxi" not in blob
        )
    )
    return sized and "lp" not in blob and "album" not in blob


def catalog_implies_seven_inch(catno: str | None) -> bool:
    """Polydor DR-1944 and 07SH-style prefixes are 7\" even when Discogs says LP."""
    folded = (fold_catalog(catno) or "").upper()
    return bool(folded and _SEVEN_INCH_STORED_PREFIX.match(folded))


def catalog_fits_listing_media(
    catno: str | None,
    listing_media: str | None,
    title: str | None = None,
) -> bool:
    """Drop 7\" catalogs from LP/CD shortlists unless the listing is a single."""
    media = effective_listing_media(listing_media, title)
    if not catalog_implies_seven_inch(catno):
        return True
    if listing_title_wants_seven_inch(title) or vinyl_shape(media) == "seven":
        return True
    return False


def prefer_listing_shape(
    hits: Sequence[SearchHit],
    media_type: str | None,
    title: str | None = None,
) -> tuple[SearchHit, ...]:
    """Keep LP hits off 7\"/12\" singles, and singles on their own diameter."""
    if not hits:
        return ()
    media_type = effective_listing_media(media_type, title)
    media = (media_type or "").casefold()
    family = media_family(media_type)
    wants_seven = listing_title_wants_seven_inch(title) or media in {
        "ep_7_inch",
        "7_inch",
    }

    def _hit_family(hit: SearchHit) -> str:
        return media_family(" ".join(hit.formats))

    if wants_seven:
        return tuple(hit for hit in hits if _is_seven_inch(hit))
    if media in {"single_12_inch", "12_inch_single"}:
        return tuple(hit for hit in hits if _is_twelve_inch(hit))
    if family == "cd":
        return tuple(hit for hit in hits if _hit_family(hit) == "cd")
    if media.startswith("lp"):
        return tuple(
            hit
            for hit in hits
            if not _is_seven_inch(hit)
            and not _is_twelve_inch(hit)
            and _hit_family(hit) != "cd"
        )
    if family == "vinyl":
        return tuple(hit for hit in hits if _hit_family(hit) != "cd")
    return tuple(hits)


_LABEL_FAMILIES = {
    "polydor": frozenset({"polydor", "polygram", "ポリドール", "ポリグラム"}),
    "polygram": frozenset({"polydor", "polygram", "ポリドール", "ポリグラム"}),
}


def _hit_has_listing_label(hit: SearchHit, hints: Sequence[str]) -> bool:
    blob = " ".join((hit.catno, *hit.labels)).casefold()
    for hint in hints:
        aliases = _LABEL_FAMILIES.get(hint, (hint,))
        if any(alias in blob for alias in aliases):
            return True
        if hint == "stereo sound" and "ssar" in blob:
            return True
        if hint == "space record" and (
            "awk" in blob or "yeu jow" in blob or "宇宙" in blob or "太空" in blob
        ):
            return True
    return False


def prefer_listing_label(
    hits: Sequence[SearchHit],
    *,
    title: str | None,
    label: str | None = None,
) -> tuple[SearchHit, ...]:
    """Keep shortlist rows whose Discogs label matches the listing."""
    if not hits:
        return ()
    hints = listing_label_hints(title=title, label=label)
    if not hints:
        return tuple(hits)
    matched = tuple(
        hit
        for hit in hits
        if _hit_has_listing_label(hit, hints)
    )
    return matched


def prefer_listing_year(
    hits: Sequence[SearchHit],
    title: str | None,
) -> tuple[SearchHit, ...]:
    """Drop Discogs years that cannot be the copy described in the title."""
    if not hits:
        return ()
    matched = tuple(
        hit for hit in hits if hit_fits_listing_year(title, hit.year)
    )
    return matched


def prefer_listing_generation(
    hits: Sequence[SearchHit],
    title: str | None,
) -> tuple[SearchHit, ...]:
    """Keep original-era pressings first; do not offer only a 2010s repress."""
    if not hits:
        return ()
    if listing_names_modern_reissue_catalog(title) or title_claims_reissue(title):
        modern = tuple(hit for hit in hits if hit_is_modern_reissue(hit))
        return modern or tuple(hits)
    if not listing_wants_original_pressing(title):
        return tuple(hits)
    vintage = tuple(hit for hit in hits if not hit_is_modern_reissue(hit))
    modern = tuple(hit for hit in hits if hit_is_modern_reissue(hit))
    if vintage:
        return vintage + modern
    return ()


_VOLUME_PHRASE = re.compile(r"\bvol(?:ume)?\.?\s*(\d{1,2})\b", re.IGNORECASE)
_NAMED_SERIES_VOLUME = re.compile(r"巨星名曲\s*(\d{1,2})")
_CJK_SERIES_VOLUME = re.compile(r"第([0-9]{1,2}|[一二三四五六七八九十]{1,3})集")
_CJK_PAREN_VOLUME = re.compile(
    r"[（(]([0-9]{1,2}|[一二三四五六七八九十]{1,3})[）)]"
)
_GENERIC_SONGBOOK_ALBUM = re.compile(
    r"^(?:鄧麗君|邓丽君)?之歌[0-9一二三四五六七八九十]*$"
)
_CJK_NUMERALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _cjk_numeral_value(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if token in _CJK_NUMERALS:
        return _CJK_NUMERALS[token]
    if token.startswith("十") and len(token) == 2:
        ones = _CJK_NUMERALS.get(token[1])
        return 10 + ones if ones else None
    return None


def is_generic_songbook_album(display_title: str | None) -> bool:
    """True for unnumbered 鄧麗君之歌, not 戀愛的路多麼甜 / 之歌第十六集."""
    album = str(display_title or "")
    if " - " in album:
        album = album.split(" - ", 1)[-1]
    album = re.sub(r"[（(][^）)]+[）)]", "", album)
    compact = _script_compact(album)
    return bool(compact) and bool(_GENERIC_SONGBOOK_ALBUM.fullmatch(compact))


def listing_volume_number(title: str | None) -> int | None:
    """Best Vol. 4 / 巨星名曲23 / 之歌第十一集 in a listing or Discogs title."""
    text = str(title or "")
    match = _VOLUME_PHRASE.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    match = _NAMED_SERIES_VOLUME.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    match = _CJK_SERIES_VOLUME.search(text)
    if match:
        return _cjk_numeral_value(match.group(1))
    match = _CJK_PAREN_VOLUME.search(text)
    if match:
        return _cjk_numeral_value(match.group(1))
    return None


def _hit_format_blob(hit: SearchHit) -> str:
    return " ".join(hit.formats).casefold()


def prefer_listing_pressing_marks(
    hits: Sequence[SearchHit],
    title: str | None,
) -> tuple[SearchHit, ...]:
    """Keep 45 RPM numbered pressings when the listing names that edition."""
    if not hits:
        return ()
    text = title or ""
    want_45 = bool(_PRESSING_45.search(text))
    want_numbered = bool(_PRESSING_NUMBERED.search(text))
    if not want_45 and not want_numbered:
        return tuple(hits)
    matched = tuple(
        hit for hit in hits if hit_matches_pressing_marks(hit, title)
    )
    return matched or tuple(hits)


def hit_matches_pressing_marks(hit: SearchHit, title: str | None) -> bool:
    """True when the Discogs row carries 45 RPM / numbered if the listing did."""
    text = title or ""
    want_45 = bool(_PRESSING_45.search(text))
    want_numbered = bool(_PRESSING_NUMBERED.search(text))
    if not want_45 and not want_numbered:
        return True
    blob = _hit_format_blob(hit)
    if want_45 and "45" not in blob:
        return False
    if want_numbered and "numbered" not in blob:
        return False
    return True


def shortlist_format_options(
    hits: Sequence[SearchHit],
    *,
    limit: int = 8,
) -> tuple[SearchHit, ...]:
    """Keep LP/CD/cassette options visible instead of eight same-format rows."""
    picked: list[SearchHit] = []
    seen_ids: set[int] = set()
    seen_pair: set[tuple[str, str]] = set()
    seen_family: set[str] = set()

    def _consider(hit: SearchHit, *, new_family_only: bool) -> None:
        if hit.discogs_id in seen_ids or len(picked) >= limit:
            return
        label = discogs_format_label(hit.formats)
        pair = (fold_catalog(hit.catno) or str(hit.discogs_id), label)
        if pair in seen_pair:
            return
        if new_family_only and label in seen_family:
            return
        seen_ids.add(hit.discogs_id)
        seen_pair.add(pair)
        seen_family.add(label)
        picked.append(hit)

    for hit in hits:
        _consider(hit, new_family_only=True)
    for hit in hits:
        _consider(hit, new_family_only=False)
    return tuple(picked)


def _identity_shortlist_key(
    hit: SearchHit,
    *,
    title: str | None,
    media_type: str | None,
    catalog_number: str | None = None,
) -> tuple[int, int, int, int, int, int, str, str]:
    token = catalog_token(catalog_number=catalog_number, title=title)
    catno_match = 0 if token and (
        catno_locks_listing(hit.catno, token)
        or catno_covers_listing_token(hit.catno, token)
    ) else 1
    listing_prefix = catalog_letter_prefix(token)
    hit_prefix = catalog_letter_prefix(hit.catno)
    prefix_match = 0 if listing_prefix and listing_prefix == hit_prefix else 1
    media_rank = 0 if listing_media_compatible(media_type, " ".join(hit.formats)) else 1
    year_rank = 0 if hit_fits_listing_year(title, hit.year) else 1
    if media_family(media_type) != "cd":
        media_rank, year_rank = year_rank, media_rank
    claimed = extract_release_year(title)
    try:
        actual = int(str(hit.year).strip()[:4]) if hit.year not in {None, ""} else None
    except (TypeError, ValueError):
        actual = None
    if claimed is not None and actual is not None:
        year_delta = abs(actual - claimed)
    else:
        year_delta = 50
    return (
        catno_match,
        prefix_match,
        catalog_number_distance(token, hit.catno),
        0 if hit_matches_pressing_marks(hit, title) else 1,
        media_rank,
        year_rank,
        year_delta,
        discogs_format_label(hit.formats),
        hit.catno or "",
    )


def prefer_listing_volume(
    hits: Sequence[SearchHit],
    title: str | None,
) -> tuple[SearchHit, ...]:
    """Keep Vol. 4 hits off Vol. 5/6 when the listing numbered the copy."""
    wanted = listing_volume_number(title)
    if wanted is None or not hits:
        return tuple(hits)
    numbered = tuple(
        hit for hit in hits if listing_volume_number(hit.title) == wanted
    )
    if numbered:
        return numbered
    if _NAMED_SERIES_VOLUME.search(title or ""):
        return ()
    if _CJK_SERIES_VOLUME.search(title or ""):
        return tuple(
            hit
            for hit in hits
            if listing_volume_number(hit.title) in {None, wanted}
            and not is_generic_songbook_album(hit.title)
        )
    unnumbered = tuple(
        hit for hit in hits if listing_volume_number(hit.title) is None
    )
    return unnumbered


def refine_hits_for_listing(
    hits: Sequence[SearchHit],
    *,
    title: str | None,
    media_type: str | None,
    label: str | None = None,
) -> tuple[SearchHit, ...]:
    """Narrow a Discogs shortlist using listing media, year, volume, and label."""
    remaining = prefer_listing_shape(hits, media_type, title=title)
    remaining = prefer_listing_pressing_marks(remaining, title)
    remaining = prefer_listing_year(remaining, title)
    remaining = prefer_listing_generation(remaining, title)
    remaining = prefer_listing_volume(remaining, title)
    return prefer_listing_label(
        remaining,
        title=title,
        label=label,
    )


def _unique_shortlist_catno(hits: Sequence[SearchHit]) -> bool:
    """True when every Discogs card is the same catalog number (or a single release)."""
    catnos = {
        fold_catalog(hit.catno)
        for hit in hits
        if str(hit.catno or "").strip()
    }
    if not catnos:
        return len({hit.discogs_id for hit in hits}) <= 1
    return len(catnos) <= 1


def _same_album_or_catalog_hits(
    hits: Sequence[SearchHit],
    *,
    artist: str | None,
    title: str | None,
    token: str | None,
) -> list[SearchHit]:
    """Keep same-album rows and any hit whose catno is this listing's copy."""
    matched: list[SearchHit] = []
    for hit in hits:
        if not artist_overlaps(
            listing_artist=artist,
            listing_title=title,
            discogs_names=names_from_search_hit(hit),
        ):
            continue
        locked = bool(
            token
            and (
                catno_locks_listing(hit.catno, token)
                or catno_covers_listing_token(hit.catno, token)
            )
        )
        if (
            locked
            or album_name_in_listing(title, hit.title)
            or concert_program_related(title, hit.title)
            or _songbook_volume_allows_hit(title, hit)
        ):
            matched.append(hit)
    return matched


def classify_search_hits(
    *,
    catalog_number: str | None,
    title: str | None,
    artist: str | None,
    media_type: str | None,
    hits: Sequence[SearchHit],
    discogs_artist_names: Sequence[str] | None = None,
    require_catalog_token: bool = True,
) -> Classification:
    """Decide unmatched / needs_review / filled_auto from search hits."""
    token = listing_identity_catalog(
        stored=catalog_number,
        title=title,
        artist=artist,
        media_type=media_type,
        infer=False,
    )
    media_type = effective_listing_media(media_type, title)
    prefer_country = listing_preferred_country(
        listing_title=title,
        listing_artist=artist,
    )
    if not token or not require_catalog_token:
        media_hits = filter_hits(
            hits,
            token=None,
            media_type=media_type,
            prefer_country=prefer_country,
        )
        remaining = refine_hits_for_listing(
            media_hits,
            title=title,
            media_type=media_type,
        )
        same_album = _same_album_or_catalog_hits(
            hits,
            artist=artist,
            title=title,
            token=token,
        )
        if not same_album:
            artist_hits = [
                hit
                for hit in hits
                if artist_overlaps(
                    listing_artist=artist,
                    listing_title=title,
                    discogs_names=names_from_search_hit(hit),
                )
            ]
            if artist_hits:
                return Classification(
                    status="unmatched",
                    reason="empty_shortlist",
                    hits=(),
                    chosen=None,
                )
            if str(artist or "").strip():
                return Classification(
                    status="unmatched",
                    reason="artist_mismatch",
                    hits=(),
                    chosen=None,
                )
            return Classification(
                status="unmatched",
                reason="missing_catalog_token",
                hits=(),
                chosen=None,
            )
        if not remaining:
            ranked = shortlist_format_options(
                sorted(
                    same_album,
                    key=lambda hit: _identity_shortlist_key(
                        hit,
                        title=title,
                        media_type=media_type,
                        catalog_number=token,
                    ),
                )
            )
            has_mismatch = any(
                not listing_media_compatible(media_type, " ".join(hit.formats))
                for hit in ranked
            )
            return Classification(
                status="needs_review",
                reason="media_mismatch" if has_mismatch else "title_search",
                hits=ranked,
                chosen=None,
            )
        edition = _prefer_listing_edition(remaining, title)
        chosen = _choose_title_search_hit(
            sorted(
                edition,
                key=lambda hit: _identity_shortlist_key(
                    hit,
                    title=title,
                    media_type=media_type,
                    catalog_number=token,
                ),
            ),
            title=title,
        )
        media_ids = {hit.discogs_id for hit in media_hits}
        generation_album = prefer_listing_generation(same_album, title)
        year_album = tuple(
            hit
            for hit in (generation_album or same_album)
            if hit_fits_listing_year(title, hit.year)
        )
        ranked = sorted(
            year_album or generation_album or same_album,
            key=lambda hit: _identity_shortlist_key(
                hit,
                title=title,
                media_type=media_type,
                catalog_number=token,
            ),
        )
        lead: list[SearchHit] = []
        if chosen is not None and chosen in ranked and ranked:
            chosen_prefix = _identity_shortlist_key(
                chosen,
                title=title,
                media_type=media_type,
                catalog_number=token,
            )[1]
            best_prefix = _identity_shortlist_key(
                ranked[0],
                title=title,
                media_type=media_type,
                catalog_number=token,
            )[1]
            if chosen_prefix <= best_prefix:
                lead = [chosen]
        ordered = shortlist_format_options(
            [
                *lead,
                *[hit for hit in ranked if hit not in lead],
            ]
        )
        if chosen is not None and chosen.discogs_id in media_ids:
            option_shapes = {shortlist_option_shape(hit.formats) for hit in ordered}
            if len(option_shapes) > 1:
                return Classification(
                    status="needs_review",
                    reason="title_search",
                    hits=ordered,
                    chosen=None,
                )
            locked_choice = (
                (
                    token
                    and (
                        catno_locks_listing(chosen.catno, token)
                        or catno_covers_listing_token(chosen.catno, token)
                    )
                )
                or (
                    not token
                    and (
                        _unique_shortlist_catno(ordered)
                        or _title_search_edition_lock(
                            chosen,
                            ordered,
                            title=title,
                            artist=artist,
                        )
                    )
                )
            )
            if (
                ordered
                and chosen.discogs_id == ordered[0].discogs_id
                and locked_choice
            ):
                return Classification(
                    status="filled_auto",
                    reason="title_search",
                    hits=ordered,
                    chosen=chosen,
                )
            return Classification(
                status="needs_review",
                reason="title_search",
                hits=ordered,
                chosen=None,
            )
        return Classification(
            status="needs_review",
            reason="title_search" if chosen is None else "media_mismatch",
            hits=ordered,
            chosen=None,
        )

    same_album = _same_album_or_catalog_hits(
        hits,
        artist=artist,
        title=title,
        token=token,
    )
    extra_album = [
        hit
        for hit in same_album
        if not catno_locks_listing(hit.catno, token)
        and not catno_covers_listing_token(hit.catno, token)
    ]
    if extra_album:
        ranked = shortlist_format_options(
            sorted(
                same_album,
                key=lambda hit: _identity_shortlist_key(
                    hit,
                    title=title,
                    media_type=media_type,
                    catalog_number=token,
                ),
            )
        )
        titled = unique_release_for_missing_matrix(
            ranked,
            title=title,
            media_type=media_type,
            token=token,
        )
        if titled is not None:
            ordered = (titled, *[hit for hit in ranked if hit.discogs_id != titled.discogs_id])
            return Classification(
                status="filled_auto",
                reason="title_search",
                hits=ordered,
                chosen=titled,
            )
        has_mismatch = any(
            not listing_media_compatible(media_type, " ".join(hit.formats))
            for hit in ranked
        )
        return Classification(
            status="needs_review",
            reason="media_mismatch" if has_mismatch else "title_search",
            hits=ranked,
            chosen=None,
        )

    remaining = filter_hits(
        hits,
        token=token,
        media_type=media_type,
        prefer_country=prefer_country,
    )
    if not remaining:
        remaining = filter_hits(
            hits,
            token=None,
            media_type=media_type,
            prefer_country=prefer_country,
        )
        if remaining:
            return Classification(
                status="needs_review",
                reason="catno_mismatch",
                hits=shortlist_format_options(remaining),
                chosen=None,
            )
    if not remaining:
        remaining = filter_hits(
            hits,
            token=token,
            media_type="any",
            prefer_country=prefer_country,
        )
        if remaining:
            return Classification(
                status="needs_review",
                reason="media_mismatch",
                hits=shortlist_format_options(remaining),
                chosen=None,
            )
        return Classification(
            status="unmatched",
            reason="empty_shortlist",
            hits=(),
            chosen=None,
        )
    remaining = refine_hits_for_listing(
        remaining,
        title=title,
        media_type=media_type,
    )
    if not remaining:
        return Classification(
            status="unmatched",
            reason="empty_shortlist",
            hits=(),
            chosen=None,
        )
    overlapped = tuple(
        hit
        for hit in remaining
        if artist_overlaps(
            listing_artist=artist,
            listing_title=title,
            discogs_names=(
                *tuple(discogs_artist_names or ()),
                *names_from_search_hit(hit),
            ),
        )
    )
    if len(remaining) != 1:
        same_catno = {fold_catalog(hit.catno) for hit in overlapped if hit.catno}
        album_keys = {
            _release_album_key(hit)
            for hit in overlapped
            if _release_album_key(hit)
        }
        if overlapped and (len(overlapped) == 1 or len(same_catno) == 1):
            if len(same_catno) == 1 and len(overlapped) > 1:
                remaining = tuple(_prefer_listing_edition(overlapped, title)[:1])
            else:
                remaining = overlapped
        elif overlapped and len(album_keys) == 1:
            remaining = tuple(_prefer_listing_edition(overlapped, title)[:1])
        else:
            return Classification(
                status="needs_review",
                reason="ambiguous_hits",
                hits=remaining,
                chosen=None,
            )

    chosen = remaining[0]
    if not catno_locks_listing(chosen.catno, token):
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
    listing_catalog: str | None = None,
) -> bool:
    """Promote a unique hit when artists overlap, or a catno uniquely locks it."""
    hits = tuple(classification.hits or ())
    hit = classification.chosen or (hits[0] if hits else None)
    token = catalog_token(
        catalog_number=listing_catalog,
        title=listing_title,
    )
    catno_lock = bool(
        hit and token and catno_locks_listing(hit.catno, token)
    )
    overlapped = artist_overlaps(
        listing_artist=listing_artist,
        listing_title=listing_title,
        discogs_names=release_artist_names,
    )
    if not overlapped:
        if not catno_lock:
            return False
        if listing_search_artist(listing_artist, listing_title):
            return False
    if classification.status == "filled_auto":
        return True
    if classification.status != "needs_review":
        return False
    album_keys = {
        _release_album_key(item) for item in hits if _release_album_key(item)
    }
    same_album = 2 <= len(hits) <= 12 and len(album_keys) == 1
    option_shapes = {shortlist_option_shape(item.formats) for item in hits}
    if len(option_shapes) > 1:
        return False
    if len(hits) != 1 and not (
        same_album
        and _unique_shortlist_catno(hits)
        and classification.reason in {"title_search", "ambiguous_hits"}
    ):
        return False
    if hit is None:
        return False
    if catno_lock:
        return True
    if classification.reason not in {
        "artist_mismatch",
        "title_search",
        "ambiguous_hits",
    }:
        return False
    if classification.reason == "title_search":
        if (
            token
            and _known_catalog_prefix(token)
            and not catno_locks_listing(hit.catno, token)
            and unique_release_for_missing_matrix(
                hits,
                title=listing_title,
                media_type=None,
                token=token,
            )
            is None
        ):
            return False
    return True


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
    images = payload.get("images") or []
    primary_image = None
    if images:
        primary_image = _optional_text(
            images[0].get("uri")
        ) or _optional_text(
            images[0].get("uri150")
        )
    thumb = primary_image or _optional_text(payload.get("thumb"))

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


def cover_fields_from_release(payload: dict[str, Any]) -> dict[str, Any]:
    """Cover URL and record-label names from a Discogs release payload."""
    draft = map_release_payload(payload)
    names: list[str] = []
    for choice in draft.labels:
        name = (choice.display_name or "").strip()
        if name and name not in names:
            names.append(name)
    if not names and (draft.label_name or "").strip():
        names.append(draft.label_name.strip())
    return {
        "thumb": draft.discogs_thumb_url or "",
        "label": names,
    }


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


_LEADING_QTY = re.compile(r"^(\d+)\s*[x×]\s*", re.IGNORECASE)
_ONE_DISC_FORMATS = {
    "vinyl",
    "cd",
    "cassette",
    "dvd",
    "dvd-video",
    "blu-ray",
    "shellac",
    "flexi-disc",
}


def _disc_count_from_format(primary: dict[str, Any]) -> int | None:
    """Release qty when Discogs sent it. Otherwise 2×Vinyl, or one disc."""
    qty = _optional_int(primary.get("qty"))
    if qty:
        return qty
    name = str(primary.get("name") or "").strip()
    match = _LEADING_QTY.match(name)
    if match:
        return int(match.group(1))
    if name.casefold() in _ONE_DISC_FORMATS:
        return 1
    return None


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
    if "dvd" in media:
        return "dvd" in fmt
    if "laserdisc" in media:
        return "laserdisc" in fmt
    if not fmt:
        return True
    if (listing_media or "").casefold() == "any":
        return True
    return listing_media_compatible(listing_media, " ".join(formats))


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
    folded_name = name.casefold()
    joined = " ".join(descriptions)
    if folded_name == "cd":
        media_type = "CD"
    elif folded_name == "cassette":
        media_type = "CASSETTE"
    elif folded_name in {"dvd", "dvd-video"}:
        media_type = "DVD"
    elif any(
        token in desc_fold or token in joined
        for token in ('7"', "7 inch", "7'")
    ) and "lp" not in desc_fold and "album" not in desc_fold:
        media_type = "EP_7_INCH"
    elif (
        "maxi-single" in desc_fold
        or "maxi" in desc_fold
        or '12"' in joined
        or "12 inch" in joined.casefold()
    ) and "lp" not in desc_fold and "album" not in desc_fold:
        media_type = "SINGLE_12_INCH"
    elif "lp" in desc_fold or "album" in desc_fold:
        media_type = "LP"
    elif folded_name == "vinyl":
        media_type = "LP"

    qty = _disc_count_from_format(primary)
    detail_parts = [name, *descriptions]
    format_detail = ", ".join(part for part in detail_parts if part)
    return media_type, format_detail, qty, generation
