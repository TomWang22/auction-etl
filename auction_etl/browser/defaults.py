from __future__ import annotations

import os

VIEWPORT = {
    "width": 1920,
    "height": 1080,
}

USER_AGENT = None

HEADLESS = (
    os.environ.get(
        "AUCTION_BROWSER_HEADLESS",
        "",
    )
    .strip()
    .casefold()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)
CHANNEL = None
LOCALE = "en-US"
TIMEZONE = "America/New_York"
COLOR_SCHEME = "light"
