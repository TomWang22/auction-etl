from __future__ import annotations

import re

MEDIA_PATTERNS = {
    "DVD": [
        r"\bdvd\b",
    ],

    "LASERDISC": [
        r"laserdisc",
        r"\bld\b",
        r"レーザーディスク",
    ],

    "CD": [
        r"\bcd\b",
        r"\bshm-cd\b",
        r"\bsacd\b",
        r"\bblu-spec\b",
    ],

    "CASSETTE": [
        r"cassette",
        r"cassette tape",
        r"tape",
        r"カセット",
        r"磁带",
    ],

    "EP": [
        r"\bep\b",
        r'7"',
        r"7''",
        r"7-inch",
        r"7 inch",
        r"\b45\b",
        r"\b45rpm\b",
    ],

    "LP": [
        r"\blp\b",
        r"\b2lp\b",
        r"\b3lp\b",
        r"\bvinyl\b",
        r"\brecord\b",
        r'12"',
        r"12''",
        r"12-inch",
        r"12 inch",
        r"レコード",
        r"ＬＰ",
        r"黑胶",
        r"唱片",
    ],
}


def classify_media(title: str | None) -> str | None:
    if not title:
        return None

    text = title.lower()

    for media, patterns in MEDIA_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return media

    return None
