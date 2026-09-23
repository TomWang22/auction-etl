"""Extract record-label names from listing text."""

from __future__ import annotations

import re


_LABEL_FIELD_RE = re.compile(
    r"(?:record\s+label|label|レーベル)"
    r"\s*[:：]\s*([^\n|]{2,80})",
    re.IGNORECASE,
)

# Longer names first so "Pony Canyon" wins over "Canyon".
KNOWN_RECORD_LABELS = (
    "Pony Canyon",
    "Nippon Columbia",
    "Nippon Crown",
    "Toshiba EMI",
    "CBS/Sony",
    "CBS Sony",
    "Warner Pioneer",
    "For Life",
    "Fun House",
    "Taurus",
    "Canyon",
    "Crown",
    "Victor",
    "Columbia",
    "King",
    "Toshiba",
    "Polydor",
    "Express",
    "Teichiku",
    "Philips",
    "Mercury",
    "Elektra",
    "Atlantic",
    "Warner",
    "Epic",
    "Alfa",
    "Invitation",
    "Moon",
    "Avex",
    "Sony",
    "JVC",
    "RVC",
    "BMG",
    "SMS",
    "Air",
    "Yen",
)


def _clean_label(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n:：|,;")
    return cleaned or None


def extract_record_label(text: str) -> str | None:
    """Return an explicit Label: field, else a known label token."""
    if not text or not text.strip():
        return None

    labeled = _LABEL_FIELD_RE.search(text)
    if labeled:
        return _clean_label(labeled.group(1))

    for name in KNOWN_RECORD_LABELS:
        pattern = (
            r"(?<![A-Za-z0-9])"
            + re.escape(name)
            + r"(?![A-Za-z0-9])"
        )
        if re.search(pattern, text, flags=re.IGNORECASE):
            return name

    return None
