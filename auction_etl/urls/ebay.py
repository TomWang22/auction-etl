from __future__ import annotations

from urllib.parse import urlparse


def classify(url: str) -> str:
    path = urlparse(url).path

    if "/itm/" in path:
        return "item"

    if "/sch/" in path:
        return "search"

    return "unknown"
