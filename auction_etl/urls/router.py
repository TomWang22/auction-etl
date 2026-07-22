from __future__ import annotations

from urllib.parse import urlparse


def route_url(url: str) -> tuple[str, str]:
    host = urlparse(url).netloc.lower()

    if "ebay." in host:
        return "ebay", host

    if "buyee." in host:
        return "buyee", host

    raise ValueError(f"Unsupported marketplace: {host}")
