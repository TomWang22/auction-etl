from __future__ import annotations

from urllib.parse import urlparse


def classify(url: str) -> str:
    path = urlparse(url).path.lower()

    if "watch" in path:
        return "watchlist"

    if "search" in path:
        return "search"

    if "auction" in path:
        return "item"

    return "unknown"
