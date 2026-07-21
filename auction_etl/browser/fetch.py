import hashlib

from .manager import browser


def fetch(url: str) -> dict:
    page = browser.context.new_page()

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        page.wait_for_timeout(3000)

        html = page.content()

        return {
            "url": page.url,
            "status": response.status if response else 0,
            "html": html,
            "sha256": hashlib.sha256(html.encode()).hexdigest(),
        }

    finally:
        page.close()
