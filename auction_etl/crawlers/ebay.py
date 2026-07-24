from __future__ import annotations

from bs4 import BeautifulSoup

from auction_etl.browser.fetch import fetch


NEXT_SELECTORS = (
    "a[rel='next']",
    "a.pagination__next",
    "a[aria-label='Next page']",
)


def _next_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    for selector in NEXT_SELECTORS:
        link = soup.select_one(selector)
        if link and link.get("href"):
            return link["href"]

    return None


def crawl(
    url: str,
    profile: str = "anonymous",
):
    current = url

    while current:
        page = fetch(
            url=current,
            profile=profile,
        )

        yield page

        current = _next_url(page["html"])
