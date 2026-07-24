from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser


_JAPANESE_DATE_RE = re.compile(
    r"(?P<year>\d{4})"
    r"[年/-]"
    r"(?P<month>\d{1,2})"
    r"[月/-]"
    r"(?P<day>\d{1,2})"
    r"(?:日)?"
    r"(?:\s+"
    r"(?P<hour>\d{1,2})"
    r"[:時]"
    r"(?P<minute>\d{1,2})?"
    r"(?:分)?"
    r")?"
)

_NOISE_RE = re.compile(
    r"\b(?:ended|sold|completed|auction ended|end time|終了日時|終了時間)\b"
    r"\s*[:：]?\s*",
    re.IGNORECASE,
)


def _timezone_for_marketplace(
    marketplace: str,
) -> ZoneInfo:
    if marketplace == "buyee":
        return ZoneInfo("Asia/Tokyo")

    return ZoneInfo("UTC")


def _clean(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = _NOISE_RE.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_ended_at(
    value: str | None,
    marketplace: str,
) -> datetime | None:
    if not value:
        return None

    text = _clean(value)

    if not text:
        return None

    timezone = _timezone_for_marketplace(
        marketplace
    )

    japanese_match = _JAPANESE_DATE_RE.search(
        text
    )

    if japanese_match:
        parts = japanese_match.groupdict()

        parsed = datetime(
            year=int(parts["year"]),
            month=int(parts["month"]),
            day=int(parts["day"]),
            hour=int(parts["hour"] or 0),
            minute=int(parts["minute"] or 0),
            tzinfo=timezone,
        )

        return parsed.astimezone(
            ZoneInfo("UTC")
        )

    try:
        parsed = date_parser.parse(
            text,
            fuzzy=True,
        )
    except (
        OverflowError,
        TypeError,
        ValueError,
    ):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone
        )

    return parsed.astimezone(
        ZoneInfo("UTC")
    )
