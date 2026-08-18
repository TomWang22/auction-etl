"""Shared background-CDP support for authenticated Buyee browser access."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
)


CDP_URL_ENV = "AUCTION_BUYEE_CDP_URL"
BUYEE_PROFILE_ENV = "AUCTION_BUYEE_PROFILE"
DEFAULT_BUYEE_PROFILE = "buyee"


def buyee_cdp_url() -> str | None:
    """Return the configured local Buyee CDP endpoint."""

    value = os.environ.get(
        CDP_URL_ENV,
        "",
    ).strip()

    return value or None


def buyee_profile_name() -> str:
    """Return the production Buyee browser-profile name."""

    value = os.environ.get(
        BUYEE_PROFILE_ENV,
        DEFAULT_BUYEE_PROFILE,
    ).strip()

    return (
        value
        or DEFAULT_BUYEE_PROFILE
    )


def connect_buyee_cdp_context(
    playwright: Playwright,
    endpoint_url: str,
) -> tuple[Browser, BrowserContext]:
    """Connect to the existing background Chrome Buyee context."""

    browser = playwright.chromium.connect_over_cdp(
        endpoint_url
    )

    contexts = browser.contexts

    if len(contexts) != 1:
        raise RuntimeError(
            "Expected exactly one browser context from "
            f"Buyee CDP; found {len(contexts)}."
        )

    return (
        browser,
        contexts[0],
    )


def open_buyee_context(
    playwright: Playwright,
    *,
    profile_dir: Path,
    headless: bool,
    launch_options: dict[str, Any],
) -> tuple[
    BrowserContext,
    bool,
    Browser | None,
]:
    """Open Buyee via CDP when configured, otherwise launch locally."""

    endpoint_url = buyee_cdp_url()

    if endpoint_url is not None:
        browser, context = connect_buyee_cdp_context(
            playwright,
            endpoint_url,
        )

        return (
            context,
            False,
            browser,
        )

    options = dict(
        launch_options
    )

    options[
        "user_data_dir"
    ] = str(
        profile_dir
    )

    options[
        "headless"
    ] = headless

    context = (
        playwright.chromium
        .launch_persistent_context(
            **options
        )
    )

    return (
        context,
        True,
        None,
    )
