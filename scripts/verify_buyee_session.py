"""Verify or establish an authenticated persistent Buyee session."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from auction_etl.browser.buyee_cdp import open_buyee_context


DEFAULT_TARGET_URL = (
    "https://buyee.jp/myorders/watchlist/closed"
)
AUCTION_LINK_PATTERN = re.compile(
    r"/item/jdirectitems/auction/",
    re.IGNORECASE,
)
AUTH_MARKERS = (
    "/signup/login",
    "/signup/twofactor",
    "/signin",
    "/login",
    "/captcha",
    "twofactor",
)


# BUYEE_VERIFIER_DEADLINE_CONTRACT_V1
MAX_NAVIGATION_TIMEOUT_MS = 15_000
VERIFICATION_TIMEOUT_EXIT_CODE = 3
ACCESS_BLOCKED_EXIT_CODE = 4
# BUYEE_VERIFIER_ACCESS_BLOCKED_CONTRACT_V2


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(
        description=(
            "Verify an authenticated Buyee closed-watchlist session."
        ),
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=root / "profiles" / "anonymous",
    )
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
    )
    parser.add_argument(
        "--status-file",
        type=Path,
        default=(
            root
            / "logs"
            / "latest-refresh"
            / "buyee-auth.json"
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--headless",
        action="store_true",
    )
    return parser.parse_args()


def write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def status_payload(
    *,
    state: str,
    message: str,
    evidence_dir: Path,
    candidate_count: int = 0,
    url: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Build a session-status payload."""
    return {
        "state": state,
        "message": message,
        "pid": os.getpid(),
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "evidence_dir": str(evidence_dir),
        "candidate_count": candidate_count,
        "url": url,
        "error": error,
    }


def current_page(context: BrowserContext) -> Page:
    """Return the newest open browser page."""
    pages = [
        page
        for page in context.pages
        if not page.is_closed()
    ]

    return pages[-1] if pages else context.new_page()


def is_authentication_url(url: str) -> bool:
    """Return whether a URL is an authentication page."""
    lowered = url.casefold()

    return any(marker in lowered for marker in AUTH_MARKERS)


def is_closed_watchlist(url: str) -> bool:
    """Return whether the closed watchlist is open."""
    return (
        "/myorders/watchlist/closed"
        in url.casefold()
    )



def navigation_timeout_ms(deadline: float) -> int:
    """Return a navigation timeout bounded by the verifier deadline."""
    remaining_seconds = max(
        0.0,
        deadline - time.monotonic(),
    )
    remaining_ms = max(
        1,
        int(remaining_seconds * 1_000),
    )

    return min(
        MAX_NAVIGATION_TIMEOUT_MS,
        remaining_ms,
    )



def access_block_reason(page: Page) -> str | None:
    """Return a stable reason for a rendered Buyee access-denied page."""
    try:
        title = page.title().strip()
    except Exception:
        title = ""

    try:
        document = page.content()
    except Exception:
        document = ""

    combined = (
        title
        + "\n"
        + document
    ).casefold()

    markers = (
        "403 forbidden",
        "access denied",
    )

    for blocked_marker in markers:
        if blocked_marker in combined:
            return blocked_marker

    return None


def auction_links(page: Page) -> list[str]:
    """Collect unique Buyee auction-detail links."""
    found: list[str] = []
    seen: set[str] = set()
    anchors = page.locator("a[href]")

    try:
        count = anchors.count()
    except PlaywrightError:
        return []

    for index in range(count):
        try:
            href = (
                anchors.nth(index).get_attribute("href")
                or ""
            )
        except PlaywrightError:
            continue

        if not AUCTION_LINK_PATTERN.search(href):
            continue

        if href.startswith("/"):
            href = f"https://buyee.jp{href}"

        if href in seen:
            continue

        seen.add(href)
        found.append(href)

    return found


def save_evidence(
    page: Page,
    evidence_dir: Path,
    links: list[str],
    suffix: str,
) -> None:
    """Save screenshot, HTML, and discovered links."""
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        page.screenshot(
            path=str(
                evidence_dir
                / f"buyee-{suffix}.png"
            ),
            full_page=True,
        )
    except PlaywrightError:
        pass

    try:
        html = page.content()
    except PlaywrightError:
        html = ""

    (
        evidence_dir
        / f"buyee-{suffix}.html"
    ).write_text(
        html,
        encoding="utf-8",
    )

    (
        evidence_dir
        / "candidate-links.txt"
    ).write_text(
        "".join(f"{link}\n" for link in links),
        encoding="utf-8",
    )


def scroll_page(page: Page) -> None:
    """Trigger lazy loading on the watchlist."""
    for _ in range(4):
        try:
            page.mouse.wheel(0, 1_500)
            page.wait_for_timeout(500)
        except PlaywrightError:
            return

    try:
        page.evaluate("window.scrollTo(0, 0)")
    except PlaywrightError:
        pass


def main() -> int:
    """Verify a reusable Buyee browser session."""
    arguments = parse_arguments()
    root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    profile_dir = (
        arguments.profile_dir.expanduser().resolve()
    )
    status_file = (
        arguments.status_file.expanduser().resolve()
    )
    evidence_dir = (
        arguments.evidence_dir.expanduser().resolve()
        if arguments.evidence_dir
        else (
            root
            / "logs"
            / "buyee"
            / f"ui-auth-{timestamp}"
        )
    )

    if not profile_dir.is_dir():
        write_json_atomic(
            status_file,
            status_payload(
                state="failed",
                message="Buyee profile is missing.",
                evidence_dir=evidence_dir,
                error=str(profile_dir),
            ),
        )
        return 1

    deadline = (
        time.monotonic()
        + arguments.timeout_minutes * 60
    )

    write_json_atomic(
        status_file,
        status_payload(
            state="running",
            message="Opening the Buyee profile.",
            evidence_dir=evidence_dir,
        ),
    )

    try:
        with sync_playwright() as playwright:
            context, owns_context, _cdp_browser = open_buyee_context(
                playwright,
                profile_dir=profile_dir,
                headless=arguments.headless,
                launch_options={
                    "viewport": {
                        "width": 1440,
                        "height": 1000,
                    },
                    "locale": "en-US",
                },
            )

            try:
                page = current_page(context)

                blocked_reason = access_block_reason(
                    page
                )

                if blocked_reason is not None:
                    blocked_message = (
                        "Buyee access was blocked before "
                        "authentication state could be determined."
                    )

                    save_evidence(
                        page,
                        evidence_dir,
                        [],
                        "access-blocked",
                    )

                    write_json_atomic(
                        status_file,
                        status_payload(
                            state="access_blocked",
                            message=blocked_message,
                            evidence_dir=evidence_dir,
                            url=page.url,
                            error=blocked_reason,
                        ),
                    )

                    print(
                        "ERROR: "
                        + blocked_message
                        + " "
                        + f"Reason: {blocked_reason}"
                    )

                    return ACCESS_BLOCKED_EXIT_CODE

                try:
                    page.goto(
                        arguments.target_url,
                        wait_until="domcontentloaded",
                        timeout=navigation_timeout_ms(deadline),
                    )
                except PlaywrightTimeoutError:
                    pass

                target_seen_at: float | None = None
                last_navigation = 0.0

                while time.monotonic() < deadline:
                    page = current_page(context)

                    blocked_reason = access_block_reason(
                        page
                    )

                    if blocked_reason is not None:
                        blocked_message = (
                            "Buyee access was blocked before "
                            "authentication state could be determined."
                        )

                        save_evidence(
                            page,
                            evidence_dir,
                            [],
                            "access-blocked",
                        )

                        write_json_atomic(
                            status_file,
                            status_payload(
                                state="access_blocked",
                                message=blocked_message,
                                evidence_dir=evidence_dir,
                                url=page.url,
                                error=blocked_reason,
                            ),
                        )

                        print(
                            "ERROR: "
                            + blocked_message
                            + " "
                            + f"Reason: {blocked_reason}"
                        )

                        return ACCESS_BLOCKED_EXIT_CODE

                    if page.is_closed():
                        raise RuntimeError(
                            "The Buyee browser was closed."
                        )

                    current_url = page.url

                    if is_authentication_url(current_url):
                        write_json_atomic(
                            status_file,
                            status_payload(
                                state=(
                                    "authentication_required"
                                    if arguments.headless
                                    else "running"
                                ),
                                message=(
                                    "Buyee login or two-factor "
                                    "verification is required."
                                ),
                                evidence_dir=evidence_dir,
                                url=current_url,
                            ),
                        )

                        if arguments.headless:
                            save_evidence(
                                page,
                                evidence_dir,
                                [],
                                "authentication-required",
                            )
                            return 2

                        page.wait_for_timeout(2_000)
                        continue

                    if not is_closed_watchlist(
                        current_url
                    ):
                        now = time.monotonic()

                        if now - last_navigation >= 5:
                            last_navigation = now

                            try:
                                page.goto(
                                    arguments.target_url,
                                    wait_until=(
                                        "domcontentloaded"
                                    ),
                                    timeout=navigation_timeout_ms(deadline),
                                )
                            except PlaywrightTimeoutError:
                                pass

                        page.wait_for_timeout(2_000)
                        continue

                    if target_seen_at is None:
                        target_seen_at = time.monotonic()

                    try:
                        page.wait_for_load_state(
                            "networkidle",
                            timeout=5_000,
                        )
                    except PlaywrightTimeoutError:
                        pass

                    scroll_page(page)
                    links = auction_links(page)

                    write_json_atomic(
                        status_file,
                        status_payload(
                            state="running",
                            message=(
                                "Closed watchlist reached; "
                                "checking auction links."
                            ),
                            evidence_dir=evidence_dir,
                            candidate_count=len(links),
                            url=current_url,
                        ),
                    )

                    if links:
                        save_evidence(
                            page,
                            evidence_dir,
                            links,
                            "verified",
                        )

                        write_json_atomic(
                            status_file,
                            status_payload(
                                state="success",
                                message=(
                                    "Buyee authentication and "
                                    "closed watchlist verified."
                                ),
                                evidence_dir=evidence_dir,
                                candidate_count=len(links),
                                url=current_url,
                            ),
                        )

                        print()
                        print("Buyee session verified")
                        print("======================")
                        print(f"URL          : {current_url}")
                        print(
                            f"Auction links: {len(links)}"
                        )
                        print(
                            f"Evidence     : {evidence_dir}"
                        )
                        return 0

                    if (
                        target_seen_at is not None
                        and time.monotonic()
                        - target_seen_at
                        > 120
                    ):
                        save_evidence(
                            page,
                            evidence_dir,
                            [],
                            "watchlist-without-items",
                        )
                        raise RuntimeError(
                            "Closed watchlist contained no "
                            "auction links for two minutes."
                        )

                    page.wait_for_timeout(3_000)

                timeout_message = (
                    "Buyee authentication verification timed out."
                )

                save_evidence(
                    page,
                    evidence_dir,
                    [],
                    "verification-timeout",
                )

                write_json_atomic(
                    status_file,
                    status_payload(
                        state="timeout",
                        message=timeout_message,
                        evidence_dir=evidence_dir,
                        url=page.url,
                        error=timeout_message,
                    ),
                )

                print(f"ERROR: {timeout_message}")
                return VERIFICATION_TIMEOUT_EXIT_CODE
            finally:
                if owns_context:
                    context.close()
    except Exception as exc:
        write_json_atomic(
            status_file,
            status_payload(
                state="failed",
                message="Buyee verification failed.",
                evidence_dir=evidence_dir,
                error=str(exc),
            ),
        )
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
