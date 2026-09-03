"""Browser runtime selection for marketplace collectors.

Railway workers use an ephemeral Chromium context. Local development keeps the
existing profile-backed browser manager. eBay can restore an operator-created
Playwright storage state from a secret environment variable.
"""

from __future__ import annotations

import atexit
import base64
import binascii
import gzip
import json
import os
from typing import Any, Literal, cast

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright


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

_EPHEMERAL_LAUNCH_TIMEOUT_MS = 20_000
_EPHEMERAL_DEFAULT_TIMEOUT_MS = 10_000
_EPHEMERAL_NAVIGATION_TIMEOUT_MS = 25_000
_EBAY_STORAGE_STATE_B64_ENV = "AUCTION_EBAY_STORAGE_STATE_B64"
_EBAY_PROFILE_NAMES_ENV = "AUCTION_EBAY_PROFILE_NAMES"
_DEFAULT_EBAY_PROFILE_NAMES = ("facerecords",)


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

        if value not in {"auto", "ephemeral", "managed"}:
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

    @staticmethod
    def _ebay_profile_names() -> set[str]:
        configured = os.environ.get(
            _EBAY_PROFILE_NAMES_ENV,
            "",
        ).strip()

        values = (
            configured.split(",")
            if configured
            else _DEFAULT_EBAY_PROFILE_NAMES
        )

        return {
            value.strip().casefold()
            for value in values
            if value.strip()
        }

    @classmethod
    def _is_ebay_profile(cls, profile: str) -> bool:
        return profile.strip().casefold() in cls._ebay_profile_names()

    @staticmethod
    def _decode_ebay_storage_state(
        encoded: str,
    ) -> dict[str, Any]:
        """Decode plain or gzip-compressed base64 Playwright state."""

        try:
            decoded_bytes = base64.b64decode(
                encoded,
                validate=True,
            )
        except binascii.Error as exc:
            raise RuntimeError(
                f"{_EBAY_STORAGE_STATE_B64_ENV} is not valid base64 UTF-8."
            ) from exc

        if decoded_bytes.startswith(
            b"\x1f\x8b"
        ):
            try:
                decoded_bytes = gzip.decompress(
                    decoded_bytes
                )
            except OSError as exc:
                raise RuntimeError(
                    f"{_EBAY_STORAGE_STATE_B64_ENV} contains invalid gzip data."
                ) from exc

        try:
            decoded = decoded_bytes.decode(
                "utf-8"
            )
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"{_EBAY_STORAGE_STATE_B64_ENV} is not valid base64 UTF-8."
            ) from exc

        try:
            payload = json.loads(
                decoded
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{_EBAY_STORAGE_STATE_B64_ENV} does not contain valid JSON."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                f"{_EBAY_STORAGE_STATE_B64_ENV} must decode to a JSON object."
            )

        cookies = payload.get(
            "cookies"
        )
        origins = payload.get(
            "origins",
            [],
        )

        if not isinstance(
            cookies,
            list,
        ) or not cookies:
            raise RuntimeError(
                "The configured eBay storage state contains no cookies."
            )

        if not isinstance(
            origins,
            list,
        ):
            raise RuntimeError(
                "The configured eBay storage state has an invalid origins value."
            )

        has_ebay_cookie = any(
            isinstance(
                cookie,
                dict,
            )
            and "ebay." in str(
                cookie.get(
                    "domain",
                    "",
                )
            ).casefold()
            for cookie in cookies
        )

        if not has_ebay_cookie:
            raise RuntimeError(
                "The configured eBay storage state contains no eBay cookies."
            )

        return payload

    @classmethod
    def _storage_state_for_profile(
        cls,
        profile: str,
    ) -> dict[str, Any] | None:
        if not cls._is_ebay_profile(profile):
            return None

        encoded = os.environ.get(
            _EBAY_STORAGE_STATE_B64_ENV,
            "",
        ).strip()

        if not encoded:
            return None

        return cls._decode_ebay_storage_state(encoded)

    def _effective_mode(self) -> Literal["ephemeral", "managed"]:
        configured = self._configured_mode()

        if configured == "ephemeral":
            return "ephemeral"

        if configured == "managed":
            return "managed"

        return "ephemeral" if self._railway_runtime() else "managed"

    def _ephemeral_context(self, profile: str) -> BrowserContext:
        if self._context is not None:
            return self._context

        print(
            "AUCTION_BROWSER_RUNTIME_PHASE "
            f"phase=storage_state_start profile={profile}",
            flush=True,
        )

        storage_state = self._storage_state_for_profile(profile)

        print(
            "AUCTION_BROWSER_RUNTIME_PHASE "
            f"phase=storage_state_ready profile={profile}",
            flush=True,
        )
        print(
            "AUCTION_BROWSER_RUNTIME_PHASE "
            f"phase=playwright_start profile={profile}",
            flush=True,
        )

        self._playwright = sync_playwright().start()

        print(
            "AUCTION_BROWSER_RUNTIME_PHASE "
            f"phase=playwright_ready profile={profile}",
            flush=True,
        )

        try:
            print(
                "AUCTION_BROWSER_RUNTIME_PHASE "
                f"phase=chromium_launch profile={profile}",
                flush=True,
            )

            self._browser = self._playwright.chromium.launch(
                headless=True,
                timeout=_EPHEMERAL_LAUNCH_TIMEOUT_MS,
                args=list(_CLOUD_CHROMIUM_ARGS),
            )

            print(
                "AUCTION_BROWSER_RUNTIME_PHASE "
                f"phase=chromium_ready profile={profile}",
                flush=True,
            )

            options: dict[str, Any] = {
                "locale": "en-US",
                "viewport": {
                    "width": 1440,
                    "height": 1000,
                },
            }

            if storage_state is not None:
                options["storage_state"] = storage_state

            print(
                "AUCTION_BROWSER_RUNTIME_PHASE "
                f"phase=context_create profile={profile}",
                flush=True,
            )

            self._context = self._browser.new_context(**options)

            self._context.set_default_timeout(
                _EPHEMERAL_DEFAULT_TIMEOUT_MS
            )
            self._context.set_default_navigation_timeout(
                _EPHEMERAL_NAVIGATION_TIMEOUT_MS
            )

            print(
                "AUCTION_BROWSER_RUNTIME_PHASE "
                f"phase=context_ready profile={profile}",
                flush=True,
            )
        except Exception:
            self.close()
            raise

        auth_state = (
            "loaded"
            if self._is_ebay_profile(profile) and storage_state is not None
            else "missing"
            if self._is_ebay_profile(profile)
            else "not_applicable"
        )

        print(
            "AUCTION_BROWSER_RUNTIME "
            f"mode=ephemeral profile={profile} "
            f"auth_state={auth_state}",
            flush=True,
        )

        return self._context

    def context(self, profile: str) -> BrowserContext:
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
