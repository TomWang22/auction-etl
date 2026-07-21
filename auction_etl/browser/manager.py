from __future__ import annotations

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from auction_etl.browser.profiles import profile_path


class BrowserManager:
    """
    Manage Playwright browser contexts keyed by profile name.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}

    def context(self, profile: str = "anonymous") -> BrowserContext:
        """
        Return a browser context for the requested profile.
        """

        if profile in self._contexts:
            return self._contexts[profile]

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        context = self._playwright.chromium.launch(
            channel="chrome",
            headless=True,
        ).new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
            java_script_enabled=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        )

        profile_path(profile)

        self._contexts[profile] = context

        return context

    def close(self) -> None:
        for context in self._contexts.values():
            context.close()

        self._contexts.clear()

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


browser = BrowserManager()
