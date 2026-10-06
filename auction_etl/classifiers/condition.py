"""Map listing and Yahoo-auction condition text onto Goldmine-style grades."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


CONDITION_CODES = (
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
    # CD jewel case and disc, from the seller's own scale. S is sealed.
    "S",
    "A",
    "B",
    "C",
    "D",
)

_YAHOO_PHRASES = (
    ("close to unused", "NM"),
    ("no obvious damages/dirt", "VG+"),
    ("a little damaged/dirty", "VG"),
    ("in bad condition overall", "F"),
    ("damaged/dirty", "G"),
    ("unused", "NM"),
    ("used", "G+"),
)

_JP_MEDIA = (
    (r"未開封|新品|sealed", "M"),
    (r"極美品", "NM"),
    (r"美品", "EX"),
    (r"やや難|少し傷|軽微", "VG"),
    (r"傷あり|汚れあり|傷汚れ", "G"),
    (r"ジャンク", "P"),
)

# Longer steps first so EX- is not read as EX, and E- is not read as E.
_GRADE_WORD = (
    r"(?:VG\+\+|EX\+|EX-|E\+|E-|VG\+|G\+|NEAR MINT|MINT|NM|EX|VG|G|F|P|M|E)"
)
_COVER_HINT = re.compile(
    r"(?:sleeve\s+grading|jacket|cover|ジャケット|ジャケ|スリーブ)\s*[:：]\s*("
    + _GRADE_WORD
    + r")",
    re.IGNORECASE,
)
_MEDIA_HINT = re.compile(
    r"(?:record\s+grading|record\s+condition|media|disc|disk|盤質|盤面|レコード)\s*[:：]\s*("
    + _GRADE_WORD
    + r")",
    re.IGNORECASE,
)
_CD_CASE = re.compile(r"(?i)(?:ケース|case)\s*[:：]\s*([SABCD])(?![A-Za-z])")
_CD_DISC = re.compile(r"(?i)(?:ディスク|disc)\s*[:：]\s*([SABCD])(?![A-Za-z])")
_BARE_GRADE = re.compile(
    r"(?<![A-Z0-9])(NM|VG\+\+|VG\+|VG|EX\+|EX-|EX|G\+|SS|MINT)(?![A-Z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ConditionClassification:
    media_grade: str | None
    cover_grade: str | None


def classify_condition(*parts: str | None) -> ConditionClassification:
    """Grade media/cover from Yahoo phrases, Japanese cues, or Goldmine tokens."""
    blob = " ".join(
        unicodedata.normalize("NFKC", part)
        for part in parts
        if part and str(part).strip()
    )
    if not blob.strip():
        return ConditionClassification(None, None)

    case = _CD_CASE.search(blob)
    disc = _CD_DISC.search(blob)
    if case or disc:
        return ConditionClassification(
            disc.group(1).upper() if disc else None,
            case.group(1).upper() if case else None,
        )

    folded = blob.casefold()
    media = _from_yahoo(folded)
    cover = None

    media_hint = _MEDIA_HINT.search(blob)
    if media_hint:
        media = _canonical_grade(media_hint.group(1)) or media
    cover_hint = _COVER_HINT.search(blob)
    if cover_hint:
        cover = _canonical_grade(cover_hint.group(1))

    if media is None:
        for pattern, grade in _JP_MEDIA:
            if re.search(pattern, blob):
                media = grade
                break

    if media is None:
        bare = _BARE_GRADE.search(blob)
        if bare:
            media = _canonical_grade(bare.group(1))

    if cover is None and media is not None and _COVER_HINT.search(blob) is None:
        cover = media if media in CONDITION_CODES else None

    return ConditionClassification(media, cover)


def is_canonical_grade(value: str | None) -> bool:
    return (value or "").strip().upper() in CONDITION_CODES


def _from_yahoo(folded: str) -> str | None:
    for phrase, grade in _YAHOO_PHRASES:
        if phrase in folded:
            return grade
    if "長期保管" in folded:
        return "VG"
    return None


def _canonical_grade(raw: str) -> str | None:
    token = re.sub(r"\s+", " ", raw.strip().upper())
    aliases = {
        "MINT": "M",
        "NEAR MINT": "NM",
        "SS": "M",
    }
    token = aliases.get(token, token)
    return token if token in CONDITION_CODES else None
