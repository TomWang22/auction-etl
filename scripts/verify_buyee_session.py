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
from scripts.buyee_http_session import (
    BuyeeHttpSessionError,
    BuyeeHttpState,
    fetch_closed_watchlist,
)
from scripts.marketplace_access import (
    MarketplaceAccessState,
    MarketplacePageResult,
    classify_buyee_page,
)


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
MAINTENANCE_EXIT_CODE = 5
# BUYEE_VERIFIER_ACCESS_BLOCKED_CONTRACT_V2
# BUYEE_VERIFIER_MAINTENANCE_CONTRACT_V1


def default_storage_state_path() -> Path:
    """Return the storage state belonging to the active Buyee profile."""

    configured = (
        os.environ.get(
            "AUCTION_BUYEE_STORAGE_STATE",
            "",
        ).strip()
        or os.environ.get(
            "BUYEE_STORAGE_STATE_FILE",
            "",
        ).strip()
    )

    if configured:
        return Path(
            configured
        ).expanduser()

    profile_directory = os.environ.get(
        "AUCTION_BUYEE_PROFILE_DIR",
        "",
    ).strip()

    if profile_directory:
        return (
            Path(
                profile_directory
            ).expanduser()
            / ".auction-etl"
            / "private"
            / "buyee-storage-state.json"
        )

    railway_volume = os.environ.get(
        "RAILWAY_VOLUME_MOUNT_PATH",
        "",
    ).strip()

    if railway_volume:
        return (
            Path(
                railway_volume
            ).expanduser()
            / ".auction-etl"
            / "private"
            / "buyee-storage-state.json"
        )

    return (
        Path.home()
        / ".auction-etl"
        / "private"
        / "buyee-storage-state.json"
    )


def save_http_evidence(
    *,
    evidence_dir: Path,
    body: str,
    links: tuple[str, ...],
    suffix: str,
) -> None:
    """Save non-secret HTTP response evidence."""
    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        evidence_dir
        / f"buyee-{suffix}.html"
    ).write_text(
        body,
        encoding="utf-8",
    )

    (
        evidence_dir
        / "candidate-links.txt"
    ).write_text(
        "".join(
            f"{link}\n"
            for link in links
        ),
        encoding="utf-8",
    )


def verify_saved_http_session(
    *,
    storage_state_path: Path,
    status_file: Path,
    evidence_dir: Path,
) -> int | None:
    """Verify Buyee directly over HTTPS when saved state exists."""
    if not storage_state_path.is_file():
        return None

    try:
        result = fetch_closed_watchlist(
            storage_state_path=storage_state_path,
        )
    except BuyeeHttpSessionError as exc:
        write_json_atomic(
            status_file,
            status_payload(
                state="failed",
                message=(
                    "Buyee saved HTTPS session could not be used."
                ),
                evidence_dir=evidence_dir,
                error=str(exc),
            ),
        )

        print(
            "ERROR: Buyee saved HTTPS session failed: "
            + str(exc)
        )
        return 1

    if result.state is BuyeeHttpState.AUTHENTICATED:
        save_http_evidence(
            evidence_dir=evidence_dir,
            body=result.body,
            links=result.auction_links,
            suffix="verified-http",
        )

        write_json_atomic(
            status_file,
            status_payload(
                state="success",
                message=(
                    "Buyee authentication and closed watchlist "
                    "verified over HTTPS."
                ),
                evidence_dir=evidence_dir,
                candidate_count=len(
                    result.auction_links
                ),
                url=result.final_url,
            ),
        )

        print()
        print("Buyee HTTPS session verified")
        print("============================")
        print(
            f"URL          : {result.final_url}"
        )
        print(
            "Auction links: "
            f"{len(result.auction_links)}"
        )
        print(
            f"Evidence     : {evidence_dir}"
        )
        return 0

    if result.state is BuyeeHttpState.AUTHENTICATION_REQUIRED:
        save_http_evidence(
            evidence_dir=evidence_dir,
            body=result.body,
            links=(),
            suffix="authentication-required",
        )

        write_json_atomic(
            status_file,
            status_payload(
                state="authentication_required",
                message=(
                    "Buyee saved session requires authentication."
                ),
                evidence_dir=evidence_dir,
                url=result.final_url,
                error=result.state.value,
            ),
        )
        return 2

    if result.state is BuyeeHttpState.ACCESS_BLOCKED:
        save_http_evidence(
            evidence_dir=evidence_dir,
            body=result.body,
            links=(),
            suffix="access-blocked",
        )

        write_json_atomic(
            status_file,
            status_payload(
                state="access_blocked",
                message=(
                    "Buyee HTTPS access is blocked."
                ),
                evidence_dir=evidence_dir,
                url=result.final_url,
                error=result.state.value,
            ),
        )
        return ACCESS_BLOCKED_EXIT_CODE

    if result.state is BuyeeHttpState.MAINTENANCE:
        save_http_evidence(
            evidence_dir=evidence_dir,
            body=result.body,
            links=(),
            suffix="maintenance",
        )

        write_json_atomic(
            status_file,
            status_payload(
                state="maintenance",
                message=(
                    "Buyee maintenance was detected."
                ),
                evidence_dir=evidence_dir,
                url=result.final_url,
                error=result.state.value,
            ),
        )
        return MAINTENANCE_EXIT_CODE

    save_http_evidence(
        evidence_dir=evidence_dir,
        body=result.body,
        links=result.auction_links,
        suffix="indeterminate",
    )

    write_json_atomic(
        status_file,
        status_payload(
            state="failed",
            message=(
                "Buyee HTTPS session state was indeterminate."
            ),
            evidence_dir=evidence_dir,
            candidate_count=len(
                result.auction_links
            ),
            url=result.final_url,
            error=result.state.value,
        ),
    )

    return 1


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(
        description=(
            "Verify an authenticated Buyee closed-watchlist session."
        ),
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=default_storage_state_path(),
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


def persist_storage_state(
    context: BrowserContext,
    storage_state_path: Path,
) -> None:
    """Persist authenticated browser state atomically."""
    storage_state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = storage_state_path.with_suffix(
        storage_state_path.suffix + ".tmp"
    )

    context.storage_state(
        path=str(temporary_path),
    )

    os.chmod(
        temporary_path,
        0o600,
    )

    temporary_path.replace(
        storage_state_path,
    )



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



def marketplace_page_result(
    page: Page,
    status_code: int | None = None,
) -> MarketplacePageResult:
    """Classify the currently rendered Buyee page."""
    try:
        title = page.title().strip()
    except PlaywrightError:
        title = ""

    try:
        body = page.locator("body").inner_text(
            timeout=5_000
        )
    except PlaywrightError:
        try:
            body = page.content()
        except PlaywrightError:
            body = ""

    return classify_buyee_page(
        status_code=status_code,
        title=title,
        body=body,
    )


def navigation_status_for_page(
    *,
    page: Page,
    navigation_url: str | None,
    navigation_status: int | None,
) -> int | None:
    """Use an HTTP status only while it still belongs to this page URL."""
    if (
        navigation_url is None
        or page.url != navigation_url
    ):
        return None

    return navigation_status


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

    storage_state_path = (
        arguments.storage_state.expanduser().resolve()
    )

    http_verification = verify_saved_http_session(
        storage_state_path=storage_state_path,
        status_file=status_file,
        evidence_dir=evidence_dir,
    )

    if http_verification is not None:
        return http_verification

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

                initial_result = marketplace_page_result(
                    page
                )

                if (
                    initial_result.state
                    is MarketplaceAccessState.ACCESS_BLOCKED
                ):
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
                            message=initial_result.message,
                            evidence_dir=evidence_dir,
                            url=page.url,
                            error=initial_result.state.value,
                        ),
                    )

                    print(
                        "ERROR: "
                        + initial_result.message
                    )

                    return ACCESS_BLOCKED_EXIT_CODE

                if (
                    initial_result.state
                    is MarketplaceAccessState.MAINTENANCE
                ):
                    save_evidence(
                        page,
                        evidence_dir,
                        [],
                        "maintenance",
                    )

                    write_json_atomic(
                        status_file,
                        status_payload(
                            state="maintenance",
                            message=initial_result.message,
                            evidence_dir=evidence_dir,
                            url=page.url,
                            error=initial_result.state.value,
                        ),
                    )

                    print(
                        "NOTICE: "
                        + initial_result.message
                    )

                    return MAINTENANCE_EXIT_CODE

                navigation_status: int | None = None
                navigation_url: str | None = None

                try:
                    response = page.goto(
                        arguments.target_url,
                        wait_until="domcontentloaded",
                        timeout=navigation_timeout_ms(deadline),
                    )

                    navigation_status = (
                        response.status
                        if response is not None
                        else None
                    )
                    navigation_url = page.url
                except PlaywrightTimeoutError:
                    navigation_status = None
                    navigation_url = None

                target_seen_at: float | None = None
                last_navigation = 0.0

                while time.monotonic() < deadline:
                    page = current_page(context)

                    page_result = marketplace_page_result(
                        page,
                        navigation_status_for_page(
                            page=page,
                            navigation_url=navigation_url,
                            navigation_status=navigation_status,
                        ),
                    )

                    if (
                        page_result.state
                        is MarketplaceAccessState.ACCESS_BLOCKED
                    ):
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
                                message=page_result.message,
                                evidence_dir=evidence_dir,
                                url=page.url,
                                error=page_result.state.value,
                            ),
                        )

                        print(
                            "ERROR: "
                            + page_result.message
                        )

                        return ACCESS_BLOCKED_EXIT_CODE

                    if (
                        page_result.state
                        is MarketplaceAccessState.MAINTENANCE
                    ):
                        save_evidence(
                            page,
                            evidence_dir,
                            [],
                            "maintenance",
                        )

                        write_json_atomic(
                            status_file,
                            status_payload(
                                state="maintenance",
                                message=page_result.message,
                                evidence_dir=evidence_dir,
                                url=page.url,
                                error=page_result.state.value,
                            ),
                        )

                        print(
                            "NOTICE: "
                            + page_result.message
                        )

                        return MAINTENANCE_EXIT_CODE

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
                                response = page.goto(
                                    arguments.target_url,
                                    wait_until=(
                                        "domcontentloaded"
                                    ),
                                    timeout=navigation_timeout_ms(deadline),
                                )

                                navigation_status = (
                                    response.status
                                    if response is not None
                                    else None
                                )
                                navigation_url = page.url
                            except PlaywrightTimeoutError:
                                navigation_status = None
                                navigation_url = None

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
                        persist_storage_state(
                            context,
                            storage_state_path,
                        )

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
