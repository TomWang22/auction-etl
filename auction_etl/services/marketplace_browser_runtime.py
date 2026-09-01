"""Browser runtime selection for marketplace collectors.

Railway workers use an ephemeral Chromium context. Local development keeps the
existing profile-backed browser manager so interactive workflows remain
unchanged.
"""

from __future__ import annotations

import atexit
import os
from typing import Literal, cast

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    sync_playwright,
)


BrowserMode = Literal["auto", "ephemeral", "managed"]

_RAILWAY_ENVIRONMENT_KEYS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_REPLICA_ID",
)

_CLOUD_CHROMIUM_ARGS = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
)

_EPHEMERAL_LAUNCH_TIMEOUT_MS = 60_000


class MarketplaceBrowserRuntime:
    """Expose the legacy ``browser.context(profile)`` interface safely."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        atexit.register(self.close)

    @staticmethod
    def _configured_mode() -> BrowserMode:
        value = os.environ.get(
            "AUCTION_MARKETPLACE_BROWSER_MODE",
            "auto",
        ).strip().casefold()

        if value not in {
            "auto",
            "ephemeral",
            "managed",
        }:
            raise RuntimeError(
                "AUCTION_MARKETPLACE_BROWSER_MODE must be one of "
                "'auto', 'ephemeral', or 'managed'."
            )

        return cast(BrowserMode, value)

    @staticmethod
    def _railway_runtime() -> bool:
        return any(
            os.environ.get(key, "").strip()
            for key in _RAILWAY_ENVIRONMENT_KEYS
        )

    def _effective_mode(self) -> Literal["ephemeral", "managed"]:
        configured = self._configured_mode()

        if configured == "ephemeral":
            return "ephemeral"

        if configured == "managed":
            return "managed"

        return (
            "ephemeral"
            if self._railway_runtime()
            else "managed"
        )

    def _ephemeral_context(
        self,
        profile: str,
    ) -> BrowserContext:
        if self._context is not None:
            return self._context

        self._playwright = sync_playwright().start()

        try:
            self._browser = self._playwright.chromium.launch(
                headless=True,
                timeout=_EPHEMERAL_LAUNCH_TIMEOUT_MS,
                args=list(_CLOUD_CHROMIUM_ARGS),
            )
            self._context = self._browser.new_context(
                locale="en-US",
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
            )
        except Exception:
            self.close()
            raise

        print(
            "AUCTION_BROWSER_RUNTIME "
            f"mode=ephemeral profile={profile}",
            flush=True,
        )

        return self._context

    def context(
        self,
        profile: str,
    ) -> BrowserContext:
        """Return a marketplace browser context for this process."""
        mode = self._effective_mode()

        if mode == "managed":
            from auction_etl.browser.manager import browser as managed_browser

            print(
                "AUCTION_BROWSER_RUNTIME "
                f"mode=managed profile={profile}",
                flush=True,
            )
            return managed_browser.context(profile)

        return self._ephemeral_context(profile)

    def close(self) -> None:
        """Release only resources owned by the ephemeral runtime."""
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            finally:
                self._context = None

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            finally:
                self._playwright = None


browser = MarketplaceBrowserRuntime()
