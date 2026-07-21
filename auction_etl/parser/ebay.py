from __future__ import annotations

from bs4 import BeautifulSoup


def parse_search(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    rows = []

    for item in soup.select("li.s-item"):
        link = item.select_one("a.s-item__link")
        title = item.select_one(".s-item__title")
        price = item.select_one(".s-item__price")

        if not link or not title:
            continue

        rows.append(
            {
                "title": title.get_text(strip=True),
                "price": price.get_text(strip=True) if price else None,
                "url": link.get("href"),
            }
        )

    return rows
