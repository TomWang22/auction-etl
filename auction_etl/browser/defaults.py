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
# Playwright injects --no-sandbox into Chrome; that belongs on Railway
# Chromium only. Local headed Google Chrome must not carry the flag.
LOCAL_CHROME_IGNORE_DEFAULT_ARGS = (
    "--no-sandbox",
)


def chrome_window_position_arg() -> str:
    """Headed Chrome must stay headed; park it off the operator desktop by default.

    eBay and Buyee block true headless. Putting the window at 80,80 steals
    focus and flashes sold jackets into the UI. Off-desktop keeps headed
    cookies working without hijacking the collector's Space.

    Set ``AUCTION_CHROME_VISIBLE=1`` to force ``80,80`` when debugging a scrape.
    Optional ``AUCTION_CHROME_WINDOW_POSITION=x,y`` overrides the coordinates.
    """

    visible = (
        os.environ.get("AUCTION_CHROME_VISIBLE", "")
        .strip()
        .casefold()
        in {"1", "true", "yes", "on"}
    )
    if visible:
        return "--window-position=80,80"
    custom = os.environ.get("AUCTION_CHROME_WINDOW_POSITION", "").strip()
    if custom and "," in custom:
        return f"--window-position={custom}"
    # Far off the primary desktop on typical macOS layouts. Not -32000:
    # some Chrome builds ignore that sentinel; -2400 is enough to leave focus.
    return "--window-position=-2400,-200"


def chrome_launch_window_args() -> tuple[str, ...]:
    """Shared headed Chrome args for Buyee / eBay owners."""

    return (
        chrome_window_position_arg(),
        "--window-size=1200,900",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
    )
