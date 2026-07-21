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


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}

    def context(self, profile: str = "anonymous") -> BrowserContext:
        if profile in self._contexts:
            return self._contexts[profile]

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        kwargs = {
            "user_data_dir": str(profile_path(profile)),
            "channel": CHANNEL,
            "headless": HEADLESS,
            "viewport": VIEWPORT,
            "locale": LOCALE,
            "timezone_id": TIMEZONE,
            "color_scheme": COLOR_SCHEME,
        }

        if USER_AGENT is not None:
            kwargs["user_agent"] = USER_AGENT

        context = self._playwright.chromium.launch_persistent_context(**kwargs)

        self._contexts[profile] = context
        return context

    def close(self) -> None:
        for context in self._contexts.values():
            context.close()

        self._contexts.clear()

        if self._playwright:
            self._playwright.stop()
            self._playwright = None


browser = BrowserManager()
