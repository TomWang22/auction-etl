from __future__ import annotations

from auction_etl.crawlers import buyee, ebay


def next_page(
    marketplace: str,
    html: str,
) -> str | None:
    if marketplace == "ebay":
        return ebay.next_page(html)

    if marketplace == "buyee":
        return buyee.next_page(html)

    raise ValueError(f"Unsupported marketplace: {marketplace}")
