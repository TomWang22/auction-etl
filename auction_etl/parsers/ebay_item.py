"""Read the eBay item-page About this item specifics.

Search cards only keep Used or Pre-Owned. The sleeve, obi, and record
grades, and the seller note, are on the item page.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

# Labels the review form already understands. Condition Used is not one of them.
_REPORT_LABELS = {
    "seller notes": "Seller Notes",
    "sleeve grading": "Sleeve Grading",
    "cover condition": "Sleeve Grading",
    "obi grading": "Obi Grading",
    "obi condition": "Obi Grading",
    "record grading": "Record Grading",
    "record condition": "Record Condition",
    "vinyl condition": "Record Grading",
    "jacket": "Jacket",
    "insert grading": "Insert",
    "insert": "Insert",
    "lyric sheet": "Insert",
    "lyrics": "Insert",
    "poster": "Poster",
}
_REPORT_ORDER = (
    "Seller Notes",
    "Sleeve Grading",
    "Jacket",
    "Obi Grading",
    "Record Grading",
    "Record Condition",
    "Insert",
    "Poster",
)
_SKIP_WHEN_PRESENT = {
    "Jacket": "Sleeve Grading",
    "Record Condition": "Record Grading",
}
_KNOWN_LABELS = frozenset(
    set(_REPORT_LABELS)
    | {
        "condition",
        "material",
        "format",
        "release title",
        "speed",
        "record label",
        "catalog number",
        "record size",
        "country of origin",
        "type",
        "artist",
        "number of discs",
        "genre",
        "case type",
        "unique item id",
    }
)
_JSON_VALUE = re.compile(
    r'"name"\s*:\s*"(?P<name>(?:\\.|[^"\\])*)"\s*,\s*"value"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"'
)
_JSON_VALUES = re.compile(
    r'"name"\s*:\s*"(?P<name>(?:\\.|[^"\\])*)"\s*,\s*"values"\s*:\s*\[\s*"(?P<value>(?:\\.|[^"\\])*)"'
)


def _clean(value: str | None) -> str:
    text = (value or "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _label_key(value: str) -> str:
    return _clean(value).casefold().rstrip(":")


def _unescape(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return _clean(value)
    return _clean(decoded if isinstance(decoded, str) else value)


def _remember(found: dict[str, str], label: str, value: str) -> None:
    key = _label_key(label)
    text = _clean(value).strip("“”\"'")
    if key == "condition":
        stored = "condition"
    elif key in _REPORT_LABELS:
        stored = _REPORT_LABELS[key].casefold()
    else:
        return
    if not text:
        return
    found.setdefault(stored, text)


def _pairs_from_dom(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for block in soup.select(".ux-labels-values"):
        label_node = block.select_one(".ux-labels-values__labels")
        value_node = block.select_one(".ux-labels-values__values")
        if label_node is None or value_node is None:
            continue
        _remember(
            found,
            label_node.get_text(" ", strip=True),
            value_node.get_text(" ", strip=True),
        )
    for term in soup.select("dl dt"):
        value_node = term.find_next_sibling("dd")
        if value_node is None:
            continue
        _remember(
            found,
            term.get_text(" ", strip=True),
            value_node.get_text(" ", strip=True),
        )
    return found


def _pairs_from_json(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for pattern in (_JSON_VALUE, _JSON_VALUES):
        for match in pattern.finditer(html):
            _remember(
                found,
                _unescape(match.group("name")),
                _unescape(match.group("value")),
            )
    return found


def _pairs_from_lines(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [
        _clean(line)
        for line in soup.get_text("\n").splitlines()
        if _clean(line)
    ]
    found: dict[str, str] = {}
    index = 0
    while index < len(lines) - 1:
        key = _label_key(lines[index])
        value = lines[index + 1]
        if key in _KNOWN_LABELS and _label_key(value) not in _KNOWN_LABELS:
            _remember(found, key, value)
            index += 2
            continue
        index += 1
    return found


def parse_item_specifics(html: str) -> dict[str, str]:
    """Label/value pairs from About this item. Keys are lowercase labels."""
    if not html or not html.strip():
        return {}
    found = _pairs_from_dom(html)
    if not any(key in found for key in _REPORT_LABELS):
        for key, value in _pairs_from_json(html).items():
            found.setdefault(key, value)
    if not any(key in found for key in _REPORT_LABELS):
        for key, value in _pairs_from_lines(html).items():
            found.setdefault(key, value)
    return found


def item_specifics_report(pairs: dict[str, str]) -> str:
    """Seller-report text. Used and Pre-Owned are left out."""
    lines: list[str] = []
    seen: set[str] = set()
    for canonical in _REPORT_ORDER:
        preferred = _SKIP_WHEN_PRESENT.get(canonical)
        if preferred and preferred.casefold() in pairs:
            continue
        value = pairs.get(canonical.casefold())
        if not value or canonical in seen:
            continue
        seen.add(canonical)
        lines.append(f"{canonical}: {value}")
    return "\n".join(lines)


def specifics_from_html(html: str) -> dict[str, Any]:
    """The stored condition sheet, plus the eBay Condition word when present."""
    pairs = parse_item_specifics(html)
    report = item_specifics_report(pairs)
    return {
        "pairs": pairs,
        "report": report,
        "condition": pairs.get("condition") or "",
        "seller_notes": pairs.get("seller notes") or "",
    }
