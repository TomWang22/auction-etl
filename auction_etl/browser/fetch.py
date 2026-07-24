from __future__ import annotations

import hashlib

from auction_etl.browser.manager import browser


def fetch(
    url: str,
    profile: str = "anonymous",
) -> dict:
    page = browser.context(profile).new_page()

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=10_000,
            )
        except Exception:
            page.wait_for_timeout(2000)

        html = page.content()

        return {
            "url": page.url,
            "status": response.status if response else 0,
            "html": html,
            "sha256": hashlib.sha256(html.encode()).hexdigest(),
        }

    finally:
        page.close()
