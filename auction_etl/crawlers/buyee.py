from __future__ import annotations

import hashlib
import re

from auction_etl.browser.manager import browser


def crawl(
    url: str,
    profile: str = "anonymous",
):
    page = browser.context(profile).new_page()

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page_number = 1

        while True:
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=10000,
                )
            except Exception:
                page.wait_for_timeout(2000)

            html = page.content()

            item_ids = set(
                re.findall(
                    r'data-wid="([^"]+)"',
                    html,
                )
            )

            if not item_ids:
                break

            yield {
                "url": page.url,
                "status": 200,
                "html": html,
                "sha256": hashlib.sha256(
                    html.encode()
                ).hexdigest(),
            }

            page_number += 1

            try:
                with page.expect_navigation(
                    wait_until="domcontentloaded",
                    timeout=15000,
                ):
                    page.evaluate(
                        """
(page_number) => {
    const form = document.forms.historyform;

    if (!form)
        return;

    form.page.value = String(page_number);
    form.submit();
}
                        """,
                        page_number,
                    )
            except Exception:
                break

    finally:
        page.close()
