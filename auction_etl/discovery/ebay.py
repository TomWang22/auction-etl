from __future__ import annotations

from urllib.parse import quote

from auction_etl.browser.fetch import fetch


def search(
    keyword: str,
    profile: str = "ebay",
) -> dict:
    url = (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={quote(keyword)}"
    )

    return fetch(
        url,
        profile=profile,
    )
