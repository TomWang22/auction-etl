from __future__ import annotations

from bs4 import BeautifulSoup


def next_page(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    selectors = (
        'a[rel="next"]',
        'a[aria-label="Go to next search page"]',
        'a[aria-label="Next page"]',
        'a.pagination__next',
        'a[type="next"]',
    )

    for selector in selectors:
        link = soup.select_one(selector)

        if link is None:
            continue

        href = link.get("href")

        if href:
            return href

    return None
