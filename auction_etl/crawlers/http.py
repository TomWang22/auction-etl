import hashlib

import httpx


def fetch(url: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/138 Safari/537.36"
        )
    }

    response = httpx.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=30,
    )

    html = response.text

    return {
        "url": str(response.url),
        "status": response.status_code,
        "html": html,
        "sha256": hashlib.sha256(html.encode()).hexdigest(),
    }
