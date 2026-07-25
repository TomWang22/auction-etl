"""Pure helpers for Auction Collector Review."""

from __future__ import annotations

import math
import re
from typing import Any


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


def derive_pressing_token(
    *,
    override: Any,
    catalog_number: Any,
    title: Any,
) -> str:
    """Resolve the best available pressing identity token."""
    for candidate in (
        override,
        catalog_number,
        title,
    ):
        token = normalize_pressing_token(
            candidate
        )

        if token:
            return token

    return ""


def derive_sale_type(
    *,
    manual_value: Any,
    title: Any,
    starting_price: Any,
    bid_count: Any,
    buyout_price: Any,
) -> str:
    """Classify the commercial sale format."""
    manual = clean_text(
        manual_value
    ).upper()

    if manual:
        return manual

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
