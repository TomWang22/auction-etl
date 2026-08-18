from __future__ import annotations

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


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._borrowed_profiles: set[str] = set()
        self._cdp_browsers: dict[str, object] = {}

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

        kwargs = {
            "user_data_dir": str(profile_path(profile)),
            "headless": HEADLESS,
            "viewport": VIEWPORT,
            "locale": LOCALE,
            "timezone_id": TIMEZONE,
            "color_scheme": COLOR_SCHEME,
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

    def close(self) -> None:
        for profile, context in self._contexts.items():
            if profile not in self._borrowed_profiles:
                context.close()

        self._contexts.clear()
        self._borrowed_profiles.clear()
        self._cdp_browsers.clear()

        if self._playwright:
            self._playwright.stop()
            self._playwright = None


browser = BrowserManager()
