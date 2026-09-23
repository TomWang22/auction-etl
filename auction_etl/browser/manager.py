from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from auction_etl.browser.defaults import (
    CHANNEL,
    COLOR_SCHEME,
    HEADLESS,
    LOCALE,
    TIMEZONE,
    USER_AGENT,
    VIEWPORT,
)
from auction_etl.browser.profiles import profile_path
from auction_etl.browser.buyee_cdp import (
    buyee_cdp_url,
    buyee_profile_name,
    connect_buyee_cdp_context,
)


VISIBLE_CHROME_ARGS = (
    "--window-position=80,80",
    "--window-size=1200,900",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-popup-blocking",
)
EBAY_STORAGE_STATE_ENV = "AUCTION_LOCAL_EBAY_STATE_FILE"
DEFAULT_EBAY_STORAGE_STATE = (
    Path.home() / ".auction-etl" / "private" / "ebay-storage-state.json"
)
EBAY_HOME_URL = "https://www.ebay.com/"
EBAY_SENSOR_COOKIE_NAMES = frozenset(
    {
        "_abck",
        "ak_bmsc",
        "bm_lso",
        "bm_s",
        "bm_so",
        "bm_sv",
        "bm_sz",
    }
)


def is_ebay_storage_profile(profile: str) -> bool:
    """Return whether this profile loads eBay from a storage-state jar."""
    name = profile.strip().casefold()
    return name.startswith("ebay") or name in {"ebay-public"}


def ebay_storage_state_path() -> Path | None:
    """Return the local eBay cookie jar used by the headed owner."""
    configured = os.environ.get(EBAY_STORAGE_STATE_ENV, "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else DEFAULT_EBAY_STORAGE_STATE
    )
    if path.is_file():
        return path
    return None


def ebay_context_storage_state(path: Path) -> dict[str, Any]:
    """Load the operator jar without expired or bot-manager 403 stamps."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        return payload

    now = time.time()
    kept: list[dict[str, Any]] = []
    dropped_sensor = 0
    dropped_expired = 0

    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        if name in EBAY_SENSOR_COOKIE_NAMES:
            dropped_sensor += 1
            continue
        expires = cookie.get("expires")
        if (
            isinstance(expires, (int, float))
            and 0 < expires < now
        ):
            dropped_expired += 1
            continue
        kept.append(cookie)

    print(
        "AUCTION_BROWSER_EBAY_STATE "
        f"kept={len(kept)} "
        f"sensor_dropped={dropped_sensor} "
        f"expired_dropped={dropped_expired}",
        flush=True,
    )
    return {
        **payload,
        "cookies": kept,
    }


def warmup_ebay_home(context: BrowserContext) -> None:
    """Establish a normal eBay home session before sold-search navigation."""
    page = context.new_page()
    try:
        prepare_ebay_search_tab(page)
    finally:
        try:
            page.close()
        except Exception:
            pass


def prepare_ebay_search_tab(page: Any, *, page_number: int | None = None) -> None:
    """Load ebay.com on this tab so sold-search is not a cold deep link."""
    suffix = (
        f" page={page_number}"
        if page_number is not None
        else ""
    )
    try:
        print(
            f"AUCTION_BROWSER_EBAY_HOME warmup=1{suffix}",
            flush=True,
        )
        page.goto(
            EBAY_HOME_URL,
            wait_until="commit",
            timeout=25_000,
        )
        try:
            page.wait_for_load_state(
                "domcontentloaded",
                timeout=8_000,
            )
        except Exception:
            pass
        page.wait_for_timeout(2_500)
        title = ""
        try:
            title = page.title()
        except Exception:
            pass
        print(
            "AUCTION_BROWSER_EBAY_HOME "
            f"title={(title or '')[:80]}{suffix}",
            flush=True,
        )
    except Exception as exc:
        print(
            "AUCTION_BROWSER_EBAY_HOME "
            f"warmup_nonfatal={type(exc).__name__}{suffix}",
            flush=True,
        )


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._borrowed_profiles: set[str] = set()
        self._cdp_browsers: dict[str, object] = {}
        self._owned_browsers: list[object] = []

    def context(self, profile: str = "anonymous") -> BrowserContext:
        if profile in self._contexts:
            return self._contexts[profile]

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        cdp_url = buyee_cdp_url()

        if (
            cdp_url is not None
            and profile == buyee_profile_name()
        ):
            cdp_browser, context = connect_buyee_cdp_context(
                self._playwright,
                cdp_url,
            )

            self._cdp_browsers[profile] = cdp_browser
            self._borrowed_profiles.add(profile)
            self._contexts[profile] = context

            return context

        ebay_state = ebay_storage_state_path()
        if (
            ebay_state is not None
            and profile != buyee_profile_name()
            and is_ebay_storage_profile(profile)
        ):
            if self._owned_browsers:
                owned_browser = self._owned_browsers[-1]
            else:
                owned_browser = self._playwright.chromium.launch(
                    channel="chrome",
                    headless=HEADLESS,
                    args=list(VISIBLE_CHROME_ARGS),
                )
                self._owned_browsers.append(owned_browser)
            context_options: dict[str, object] = {
                "storage_state": ebay_context_storage_state(ebay_state),
                "viewport": VIEWPORT,
                "locale": LOCALE,
                "timezone_id": TIMEZONE,
                "color_scheme": COLOR_SCHEME,
            }
            if USER_AGENT is not None:
                context_options["user_agent"] = USER_AGENT
            context = owned_browser.new_context(**context_options)
            self._contexts[profile] = context
            print(
                "AUCTION_BROWSER_EBAY "
                "cdp=false storage_state=true "
                "channel=chrome "
                f"profile={profile}",
                flush=True,
            )
            return context

        kwargs = {
            "user_data_dir": str(profile_path(profile)),
            "headless": HEADLESS,
            "channel": "chrome",
            "viewport": VIEWPORT,
            "locale": LOCALE,
            "timezone_id": TIMEZONE,
            "color_scheme": COLOR_SCHEME,
            "args": list(VISIBLE_CHROME_ARGS),
        }

        if USER_AGENT is not None:
            kwargs["user_agent"] = USER_AGENT

        if CHANNEL is not None:
            kwargs["channel"] = CHANNEL

        context = self._playwright.chromium.launch_persistent_context(
            **kwargs
        )

        self._contexts[profile] = context

        return context

    def replace_context(self, profile: str) -> BrowserContext:
        """Drop a poisoned context and rebuild it on the same Chrome process.

        Akamai stamps 403 cookies onto the live Playwright context. A new tab
        in that same context still sends them. Killing Chrome and launching
        another process is what turns a one-shot error page into a brick.
        """
        existing = self._contexts.pop(profile, None)
        self._borrowed_profiles.discard(profile)
        if existing is not None:
            try:
                existing.close()
            except Exception:
                pass

        print(
            "AUCTION_BROWSER_REPLACE_CONTEXT "
            f"profile={profile} reuse_browser=1",
            flush=True,
        )
        return self.context(profile)

    def close(self) -> None:
        for profile, context in self._contexts.items():
            if profile not in self._borrowed_profiles:
                context.close()

        self._contexts.clear()
        self._borrowed_profiles.clear()
        self._cdp_browsers.clear()

        for owned in self._owned_browsers:
            try:
                owned.close()
            except Exception:
                pass
        self._owned_browsers.clear()

        if self._playwright:
            self._playwright.stop()
            self._playwright = None


browser = BrowserManager()
