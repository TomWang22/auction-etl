from __future__ import annotations

from auction_etl.crawlers import buyee, ebay


def crawl(
    marketplace: str,
    url: str,
    profile: str,
):
    if marketplace == "ebay":
        yield from ebay.crawl(
            url=url,
            profile=profile,
        )
        return

    if marketplace == "buyee":
        yield from buyee.crawl(
            url=url,
            profile=profile,
        )
        return

    raise ValueError(
        f"Unsupported marketplace: {marketplace}"
    )
