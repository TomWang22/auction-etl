from __future__ import annotations

import time

from bs4 import BeautifulSoup

from auction_etl.browser.manager import browser


class BrowserSession:
    def __init__(self, profile: str = "default"):
        self.context = browser.context(profile)
        self.page = self.context.new_page()

    def open(self, url: str) -> str:
        print(f"➡️ Opening {url}")

        self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=120_000,
        )

        while "/splashui/challenge" in self.page.url:
            print("⏳ Waiting for browser check...")
            time.sleep(2)

        return self.wait_for_results()

    def wait_for_results(self) -> str:
        previous = -1
        stable = 0

        while True:
            html = self.page.content()

            count = len(
                BeautifulSoup(html, "html.parser")
                .select("li.s-card[data-listingid]")
            )

            print(f"Listings detected: {count}")

            if count == previous:
                stable += 1
            else:
                stable = 0

            if stable >= 3:
                print(f"✅ Listings stabilized at {count}")
                return html

            previous = count
            time.sleep(1)

    def next(self) -> str | None:
        selectors = [
            'a[type="next"]',
            'a[rel="next"]',
            'a[aria-label*="next" i]',
            'a.pagination__next',
        ]

        for selector in selectors:
            locator = self.page.locator(selector)

            if locator.count() == 0:
                continue

            href = locator.first.get_attribute("href")

            if not href:
                continue

            print(f"➡️ Opening {href}")

            self.page.goto(
                href,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            while "/splashui/challenge" in self.page.url:
                print("⏳ Waiting for browser check...")
                time.sleep(2)

            return self.wait_for_results()

        return None

    def close(self):
        self.page.close()
