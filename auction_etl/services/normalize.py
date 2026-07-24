from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from auction_etl.classifiers import classify_media_details
from auction_etl.models.staging import Listing


_YEAR_RE = re.compile(r"(?<!\d)(19[4-9]\d|20[0-2]\d)(?!\d)")
_CATALOG_PATTERNS = (
    re.compile(
        r"(?:catalog(?:ue)?(?:\s+number)?|cat\.?\s*no\.?|品番)"
        r"\s*[:#]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([A-Z]{1,5}[-\s]?\d{2,6}(?:[-/][A-Z0-9]{1,6})?)\b"
    ),
)
_LABEL_RE = re.compile(
    r"(?:record\s+label|label|レーベル)"
    r"\s*[:：]\s*([^\n|]{2,80})",
    re.IGNORECASE,
)
_MEDIA_GRADE_RE = re.compile(
    r"(?:record\s+grading|record\s+grade|disc|盤質|media)"
    r"\s*[:：]\s*([A-Z][A-Z0-9+\-/ ]{0,15})",
    re.IGNORECASE,
)
_SLEEVE_GRADE_RE = re.compile(
    r"(?:sleeve\s+grading|sleeve\s+grade|jacket|cover|ジャケット)"
    r"\s*[:：]\s*([A-Z][A-Z0-9+\-/ ]{0,15})",
    re.IGNORECASE,
)
_OBI_GRADE_RE = re.compile(
    r"(?:obi\s+grading|obi\s+grade|obi|帯)"
    r"\s*[:：]\s*([A-Z][A-Z0-9+\-/ ]{0,15}|NONE|NO|N/A)",
    re.IGNORECASE,
)
_COUNTRY_RE = re.compile(
    r"(?:country(?:\s+of\s+origin)?|press|pressed\s+in|製造国)"
    r"\s*[:：]\s*([^\n|]{2,60})",
    re.IGNORECASE,
)
_EDITION_RE = re.compile(
    r"(?:edition|pressing|press|盤)"
    r"\s*[:：]\s*([^\n|]{2,80})",
    re.IGNORECASE,
)

_NO_OBI_PATTERNS = (
    r"\bno\s+obi\b",
    r"\bobi\s*[:：]\s*(?:none|no|n/a)\b",
    r"\bwithout\s+obi\b",
    r"\bobi\s+not\s+included\b",
    r"帯なし",
    r"帯無",
)

_OBI_PATTERNS = (
    r"\bobi\b",
    r"帯付",
    r"帯付き",
    r"帯あり",
)

_COUNTRY_NAMES = (
    "Japan",
    "Hong Kong",
    "Taiwan",
    "Singapore",
    "Malaysia",
    "China",
    "United States",
    "USA",
    "United Kingdom",
    "UK",
    "Germany",
    "France",
    "South Korea",
    "Korea",
)


@dataclass(slots=True)
class NormalizeStats:
    scanned: int = 0
    changed: int = 0
    media_classified: int = 0
    catalog_numbers: int = 0
    labels: int = 0
    years: int = 0
    countries: int = 0
    media_grades: int = 0
    sleeve_grades: int = 0
    obi_values: int = 0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n:：|,;")
    return cleaned or None


def _payload_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""

    fragments: list[str] = []

    html = payload.get("html")
    if isinstance(html, str):
        fragments.append(
            BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        )

    for key, value in payload.items():
        if key == "html":
            continue

        if isinstance(value, (str, int, float, bool)):
            fragments.append(f"{key}: {value}")

    return "\n".join(fragments)


def _combined_text(listing: Listing) -> str:
    return "\n".join(
        value
        for value in (
            listing.title,
            listing.subtitle,
            listing.description,
            listing.condition_text,
            listing.sold_text,
            _payload_text(listing.payload),
        )
        if value
    )


def _extract_first(
    text: str,
    pattern: re.Pattern[str],
) -> str | None:
    match = pattern.search(text)
    return _clean(match.group(1)) if match else None


def _extract_catalog_number(text: str) -> str | None:
    for pattern in _CATALOG_PATTERNS:
        match = pattern.search(text)

        if match:
            candidate = _clean(match.group(1))

            if candidate and not candidate.isdigit():
                return candidate.upper()

    return None


def _extract_year(text: str) -> int | None:
    match = _YEAR_RE.search(text)
    return int(match.group(1)) if match else None


def _extract_country(text: str) -> str | None:
    explicit = _extract_first(text, _COUNTRY_RE)
    if explicit:
        return explicit

    lowered = text.casefold()

    for country in _COUNTRY_NAMES:
        if country.casefold() in lowered:
            return country

    return None


def _extract_obi(text: str) -> bool | None:
    for pattern in _NO_OBI_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    obi_grade = _extract_first(text, _OBI_GRADE_RE)

    if obi_grade:
        if obi_grade.casefold() in {"none", "no", "n/a"}:
            return False

        return True

    for pattern in _OBI_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return None


def _set_if_missing(
    listing: Listing,
    field: str,
    value: Any,
    force: bool,
) -> bool:
    if value is None:
        return False

    current = getattr(listing, field)

    if current is not None and not force:
        return False

    if current == value:
        return False

    setattr(listing, field, value)
    return True


def normalize_listing(
    listing: Listing,
    *,
    force: bool = False,
) -> dict[str, bool]:
    text = _combined_text(listing)

    media = classify_media_details(
        listing.title
    )

    extracted = {
        "format": media.format,
        "disc_count": media.disc_count,
        "catalog_number": _extract_catalog_number(text),
        "label": _extract_first(text, _LABEL_RE),
        "year": _extract_year(text),
        "country": _extract_country(text),
        "media_condition": _extract_first(text, _MEDIA_GRADE_RE),
        "sleeve_condition": _extract_first(text, _SLEEVE_GRADE_RE),
        "obi": _extract_obi(text),
        "edition": _extract_first(text, _EDITION_RE),
    }

    changes: dict[str, bool] = {}

    for field, value in extracted.items():
        changes[field] = _set_if_missing(
            listing,
            field,
            value,
            force,
        )

    normalized_payload = dict(listing.payload or {})
    normalized_payload["normalization"] = {
        "format": extracted["format"],
        "catalog_number": extracted["catalog_number"],
        "label": extracted["label"],
        "year": extracted["year"],
        "country": extracted["country"],
        "media_condition": extracted["media_condition"],
        "sleeve_condition": extracted["sleeve_condition"],
        "obi": extracted["obi"],
        "edition": extracted["edition"],
        "needs_review": any(
            value is None
            for value in (
                extracted["format"],
                extracted["catalog_number"],
                extracted["media_condition"],
                extracted["sleeve_condition"],
                extracted["obi"],
            )
        ),
    }

    if listing.payload != normalized_payload:
        listing.payload = normalized_payload
        changes["payload"] = True
    else:
        changes["payload"] = False

    return changes


def normalize_staging(
    session: Session,
    *,
    marketplace: str | None = None,
    force: bool = False,
) -> NormalizeStats:
    statement = select(Listing).order_by(Listing.id)

    if marketplace:
        statement = statement.where(
            Listing.marketplace == marketplace
        )

    stats = NormalizeStats()

    for listing in session.scalars(statement):
        stats.scanned += 1

        changes = normalize_listing(
            listing,
            force=force,
        )

        if any(changes.values()):
            stats.changed += 1

        stats.media_classified += int(changes.get("format", False))
        stats.catalog_numbers += int(
            changes.get("catalog_number", False)
        )
        stats.labels += int(changes.get("label", False))
        stats.years += int(changes.get("year", False))
        stats.countries += int(changes.get("country", False))
        stats.media_grades += int(
            changes.get("media_condition", False)
        )
        stats.sleeve_grades += int(
            changes.get("sleeve_condition", False)
        )
        stats.obi_values += int(changes.get("obi", False))

    session.commit()
    return stats
