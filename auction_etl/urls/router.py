from __future__ import annotations

from urllib.parse import urlparse


def route_url(url: str) -> str:
    host = urlparse(url).netloc.lower()

    if "ebay." in host:
        return "ebay"

    if "buyee." in host:
        return "buyee"

    raise ValueError(f"Unsupported marketplace: {host}")
