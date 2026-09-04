#!/usr/bin/env python3
"""Validate one existing eBay browser profile without false clearance success."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from auction_etl.browser.defaults import (
    CHANNEL,
    COLOR_SCHEME,
    LOCALE,
    TIMEZONE,
    USER_AGENT,
    VIEWPORT,
)
from auction_etl.browser.profiles import profile_root


BLOCKED_HTTP_STATUSES = frozenset(
    {
        401,
        403,
        429,
    }
)

ITEM_LINK_SELECTOR = 'a[href*="/itm/"]'

EBAY_HOST_PATTERN = re.compile(
    r"(?:^|\.)ebay\.(?:com|co\.uk)$",
    re.IGNORECASE,
)

GENERIC_ERROR_MARKERS = (
    "something went wrong on our end",
    "please go back and try again",
)

CHALLENGE_TEXT_MARKERS = (
    "verify you are human",
    "please verify yourself",
    "complete the security check",
    "press and hold",
    "captcha",
)

CHALLENGE_SELECTORS = (
    "iframe[src*='captcha' i]",
    "iframe[title*='captcha' i]",
    "form[action*='captcha' i]",
    "[data-testid*='captcha' i]",
    "[aria-label*='captcha' i]",
)

SIGNIN_SELECTORS = (
    "input[name='userid']",
    "input[name='pass']",
    "input[type='password']",
    "form[action*='signin' i]",
)


class BootstrapState(StrEnum):
    """Terminal or human-action state for one rendered eBay page."""

    AVAILABLE = "available"
    HUMAN_AUTH_REQUIRED = "human_auth_required"
    HUMAN_CHALLENGE_REQUIRED = "human_challenge_required"
    ACCESS_BLOCKED = "access_blocked"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class PageSnapshot:
    """Evidence used to classify one rendered eBay page."""

    state: BootstrapState
    http_status: int | None
    url: str
    title: str
    item_link_count: int
    visible_challenge: bool
    visible_signin: bool


def parse_args() -> argparse.Namespace:
    """Parse one bounded manual profile-validation request."""

    parser = argparse.ArgumentParser(
        description=(
            "Open one existing eBay persistent profile. "
            "Interactive human action is offered only when a real "
            "sign-in or verification page is visible."
        )
    )

    parser.add_argument(
        "--profile",
        default="facerecords",
    )

    parser.add_argument(
        "--url",
        required=True,
    )

    return parser.parse_args()


def normalize_text(value: str) -> str:
    """Normalize rendered page text for deterministic classification."""

    return " ".join(
        value.casefold().split()
    )


def is_signin_url(value: str) -> bool:
    """Return whether an eBay URL is a sign-in endpoint."""

    parsed = urlparse(value)

    hostname = (
        parsed.hostname
        or ""
    ).casefold()

    path = parsed.path.casefold()

    if not EBAY_HOST_PATTERN.search(
        hostname
    ):
        return False

    return (
        "signin" in hostname
        or "/signin" in path
    )


def existing_profile_directory(
    name: str,
) -> Path:
    """Return one named profile path without creating that profile."""

    normalized = name.strip()

    if not normalized:
        raise ValueError(
            "Browser profile name must not be empty."
        )

    if normalized in {
        ".",
        "..",
    }:
        raise ValueError(
            "Browser profile name is invalid."
        )

    if Path(normalized).name != normalized:
        raise ValueError(
            "Browser profile name must not contain path separators."
        )

    return (
        profile_root()
        / normalized
    )


def classify_snapshot(
    *,
    http_status: int | None,
    url: str,
    title: str,
    body: str,
    item_link_count: int,
    visible_challenge: bool,
    visible_signin: bool,
) -> BootstrapState:
    """Classify one page while giving access errors precedence."""

    normalized_title = normalize_text(
        title
    )

    normalized_body = normalize_text(
        body
    )

    generic_error = (
        normalized_title
        == "error page | ebay"
        or all(
            marker in normalized_body
            for marker in GENERIC_ERROR_MARKERS
        )
    )

    if generic_error:
        return BootstrapState.ACCESS_BLOCKED

    textual_challenge = (
        item_link_count == 0
        and any(
            marker in normalized_title
            or marker in normalized_body
            for marker in CHALLENGE_TEXT_MARKERS
        )
    )

    challenge_present = (
        visible_challenge
        or textual_challenge
    )

    signin_present = (
        visible_signin
        or is_signin_url(
            url
        )
    )

    if http_status in BLOCKED_HTTP_STATUSES:
        if challenge_present:
            return BootstrapState.HUMAN_CHALLENGE_REQUIRED

        if signin_present:
            return BootstrapState.HUMAN_AUTH_REQUIRED

        return BootstrapState.ACCESS_BLOCKED

    if challenge_present:
        return BootstrapState.HUMAN_CHALLENGE_REQUIRED

    if signin_present:
        return BootstrapState.HUMAN_AUTH_REQUIRED

    if (
        http_status is not None
        and 200 <= http_status < 400
        and item_link_count > 0
    ):
        return BootstrapState.AVAILABLE

    if (
        http_status is None
        and item_link_count > 0
    ):
        return BootstrapState.AVAILABLE

    return BootstrapState.UNKNOWN_ERROR


def visible_selector_present(
    page: Any,
    selectors: tuple[str, ...],
) -> bool:
    """Return whether any candidate human-action control is visible."""

    for selector in selectors:
        try:
            locator = page.locator(
                selector
            )

            if (
                locator.count() > 0
                and locator.first.is_visible()
            ):
                return True

        except PlaywrightError:
            continue

    return False


def inspect_page(
    page: Any,
    *,
    http_status: int | None,
) -> PageSnapshot:
    """Capture and classify the current rendered page."""

    try:
        title = page.title()
    except PlaywrightError:
        title = ""

    try:
        body = page.locator(
            "body"
        ).inner_text(
            timeout=5_000
        )
    except PlaywrightError:
        body = ""

    try:
        item_link_count = page.locator(
            ITEM_LINK_SELECTOR
        ).count()
    except PlaywrightError:
        item_link_count = 0

    visible_challenge = visible_selector_present(
        page,
        CHALLENGE_SELECTORS,
    )

    visible_signin = visible_selector_present(
        page,
        SIGNIN_SELECTORS,
    )

    state = classify_snapshot(
        http_status=http_status,
        url=page.url,
        title=title,
        body=body,
        item_link_count=item_link_count,
        visible_challenge=visible_challenge,
        visible_signin=visible_signin,
    )

    return PageSnapshot(
        state=state,
        http_status=http_status,
        url=page.url,
        title=title,
        item_link_count=item_link_count,
        visible_challenge=visible_challenge,
        visible_signin=visible_signin,
    )


def emit_snapshot(
    prefix: str,
    snapshot: PageSnapshot,
) -> None:
    """Print stable evidence for one classification."""

    print(
        f"{prefix}_STATE={snapshot.state.value}"
    )

    print(
        f"{prefix}_HTTP_STATUS="
        f"{snapshot.http_status if snapshot.http_status is not None else 'NONE'}"
    )

    print(
        f"{prefix}_URL={snapshot.url}"
    )

    print(
        f"{prefix}_TITLE={snapshot.title!r}"
    )

    print(
        f"{prefix}_ITEM_LINK_COUNT={snapshot.item_link_count}"
    )

    print(
        f"{prefix}_VISIBLE_CHALLENGE="
        f"{str(snapshot.visible_challenge).lower()}"
    )

    print(
        f"{prefix}_VISIBLE_SIGNIN="
        f"{str(snapshot.visible_signin).lower()}"
    )


def persistent_context_options(
    profile_dir: Path,
) -> dict[str, object]:
    """Use the same browser identity defaults as normal managed acquisition."""

    options: dict[str, object] = {
        "user_data_dir": str(
            profile_dir
        ),
        "headless": False,
        "viewport": dict(
            VIEWPORT
        ),
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
        "color_scheme": COLOR_SCHEME,
    }

    if USER_AGENT is not None:
        options[
            "user_agent"
        ] = USER_AGENT

    if CHANNEL is not None:
        options[
            "channel"
        ] = CHANNEL

    return options


def terminal_exit_for_state(
    state: BootstrapState,
) -> int:
    """Return the stable non-success exit code for one final state."""

    if state is BootstrapState.HUMAN_AUTH_REQUIRED:
        return 21

    if state in {
        BootstrapState.HUMAN_CHALLENGE_REQUIRED,
        BootstrapState.ACCESS_BLOCKED,
    }:
        return 20

    return 22


def main() -> int:
    """Perform at most one human clearance interaction and prove results."""

    args = parse_args()

    try:
        user_data_dir = existing_profile_directory(
            args.profile
        ).expanduser().resolve()
    except ValueError as error:
        print(
            f"ERROR: {error}"
        )
        print(
            "EBAY_PROFILE_REPLACEMENT_AUTOMATIC=false"
        )
        return 23

    if not user_data_dir.is_dir():
        print(
            "ERROR: existing eBay profile directory does not exist: "
            f"{user_data_dir}"
        )
        print(
            "EBAY_PROFILE_REPLACEMENT_AUTOMATIC=false"
        )
        return 23

    try:
        next(
            user_data_dir.iterdir()
        )
    except StopIteration:
        print(
            "ERROR: existing eBay profile directory is empty: "
            f"{user_data_dir}"
        )
        print(
            "EBAY_PROFILE_REPLACEMENT_AUTOMATIC=false"
        )
        return 23

    print(
        f"Profile directory: {user_data_dir}"
    )

    print(
        "EBAY_PROFILE_REPLACEMENT_AUTOMATIC=false"
    )

    print(
        "CAPTCHA_INTERACTION_AUTOMATED=false"
    )

    print(
        "AUTOMATIC_RETRY=false"
    )

    print()

    with sync_playwright() as playwright:
        context = (
            playwright.chromium
            .launch_persistent_context(
                **persistent_context_options(
                    user_data_dir
                )
            )
        )

        try:
            page = (
                context.pages[0]
                if context.pages
                else context.new_page()
            )

            try:
                response = page.goto(
                    args.url,
                    wait_until="domcontentloaded",
                    timeout=120_000,
                )
            except PlaywrightError as error:
                print(
                    "ERROR: initial eBay navigation failed: "
                    f"{error}"
                )
                print(
                    "EBAY_PROFILE_ACCESS_VALIDATED=false"
                )
                return 22

            initial_status = (
                response.status
                if response is not None
                else None
            )

            page.wait_for_timeout(
                2_000
            )

            initial = inspect_page(
                page,
                http_status=initial_status,
            )

            emit_snapshot(
                "INITIAL",
                initial,
            )

            if initial.state is BootstrapState.AVAILABLE:
                print()
                print(
                    "EBAY_PROFILE_ACCESS_VALIDATED=PASS"
                )
                print(
                    "MANUAL_CLEARANCE_REQUIRED=false"
                )
                return 0

            if initial.state is BootstrapState.ACCESS_BLOCKED:
                print()
                print(
                    "ERROR: eBay returned a terminal access/error page."
                )
                print(
                    "MANUAL_CLEARANCE_OFFERED=false"
                )
                print(
                    "EBAY_PROFILE_ACCESS_VALIDATED=false"
                )
                return 20

            if initial.state is BootstrapState.UNKNOWN_ERROR:
                print()
                print(
                    "ERROR: eBay did not return a normal results page "
                    "or an actionable sign-in/verification page."
                )
                print(
                    "MANUAL_CLEARANCE_OFFERED=false"
                )
                print(
                    "EBAY_PROFILE_ACCESS_VALIDATED=false"
                )
                return 22

            print()
            print(
                "A real eBay sign-in or verification page is visible."
            )
            print(
                "Complete it yourself in the browser."
            )
            print(
                "No CAPTCHA interaction is automated."
            )
            print(
                "Do not press Enter unless a normal eBay results page "
                "with listing cards is visibly present."
            )
            print(
                "Press Ctrl-C instead if eBay shows an error page."
            )
            print()

            input(
                "Press Enter only after normal eBay results are visible..."
            )

            page.wait_for_timeout(
                1_000
            )

            final = inspect_page(
                page,
                http_status=None,
            )

            emit_snapshot(
                "FINAL",
                final,
            )

            if final.state is BootstrapState.AVAILABLE:
                print()
                print(
                    "EBAY_PROFILE_ACCESS_VALIDATED=PASS"
                )
                print(
                    "MANUAL_CLEARANCE_COMPLETED=PASS"
                )
                print(
                    "The persistent profile was validated against "
                    "a rendered eBay results page."
                )
                return 0

            print()
            print(
                "EBAY_PROFILE_ACCESS_VALIDATED=false"
            )

            if final.state is BootstrapState.ACCESS_BLOCKED:
                print(
                    "ERROR: eBay still shows an access/error page."
                )

            elif final.state is BootstrapState.HUMAN_AUTH_REQUIRED:
                print(
                    "ERROR: eBay authentication is still required."
                )

            elif final.state is BootstrapState.HUMAN_CHALLENGE_REQUIRED:
                print(
                    "ERROR: eBay verification is still required."
                )

            else:
                print(
                    "ERROR: a normal eBay results page was not proven."
                )

            return terminal_exit_for_state(
                final.state
            )

        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
