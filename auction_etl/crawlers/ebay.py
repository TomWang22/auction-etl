from __future__ import annotations

import time

from auction_etl.browser.session import BrowserSession
from auction_etl.parsers.ebay import parse_search


def crawl(url: str):
    session = BrowserSession()

    seen_ids = set()

    page_number = 1

    try:
        html = session.open(url)

        while html:
            print(f"\n===== Page {page_number} =====")

            listings = parse_search(html)

            print(f"Listings: {len(listings)}")

            for listing in listings:
                if listing["item_id"] in seen_ids:
                    continue

                seen_ids.add(listing["item_id"])
                yield listing

            print("😴 Sleeping 2 seconds...")
            time.sleep(2)

            html = session.next()

            page_number += 1

    finally:
        session.close()

    print(f"\nCollected {len(seen_ids)} unique listings.")
