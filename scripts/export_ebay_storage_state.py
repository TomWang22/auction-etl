"""Export verified operator-established eBay browser state for Railway.

The command uses the dedicated local eBay Chrome profile, waits for explicit
operator confirmation, verifies that the configured eBay source is accessible,
and only then exports Playwright storage state.

The resulting JSON contains authentication material and must be treated as a
secret.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


DEFAULT_PROFILE_DIR = Path("profiles/chrome-cdp-facerecords")
DEFAULT_OUTPUT = (
    Path.home()
    / ".auction-etl"
    / "private"
    / "ebay-storage-state.json"
)
DEFAULT_CONFIG = Path("config/ebay_sources.json")
DEFAULT_SOURCE_NAME = "facerecords"
DEFAULT_HOME_URL = "https://www.ebay.com/"
DEFAULT_DEBUG_PORT = 9223
DEFAULT_DEBUG_TIMEOUT_SECONDS = 30
DEFAULT_NAVIGATION_TIMEOUT_SECONDS = 45.0
DEFAULT_RESULT_TIMEOUT_SECONDS = 30.0

ITEM_LINK_SELECTOR = 'a[href*="/itm/"]'

ACCESS_BLOCK_HTTP_STATUSES = frozenset(
    {
        401,
        403,
        429,
    }
)

ACCESS_BLOCK_TEXT = (
    "verify you are human",
    "please verify yourself",
    "complete the security check",
    "access denied",
    "press and hold",
    "pardon our interruption",
    "security measure",
)


class EbayStorageStateError(RuntimeError):
    """Report a safe eBay storage-state export failure."""


class EbayAuthenticationRequiredError(EbayStorageStateError):
    """Report an eBay sign-in redirect."""


class EbayAccessBlockedError(EbayStorageStateError):
    """Report an eBay access/security block."""


@dataclass(frozen=True, slots=True)
class SourceVerification:
    """Describe a successfully verified eBay source page."""

    requested_url: str
    final_url: str
    http_status: int | None
    item_link_count: int


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Verify an operator-established eBay session and export "
            "Playwright storage state. This command performs no database "
            "or Railway writes."
        )
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Dedicated local Chrome profile used for eBay.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Private Playwright storage-state JSON destination.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Configured eBay source JSON.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE_NAME,
        help="Configured eBay source name to verify.",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=DEFAULT_DEBUG_PORT,
        help="Local Chrome DevTools port.",
    )
    parser.add_argument(
        "--debug-timeout-seconds",
        type=int,
        default=DEFAULT_DEBUG_TIMEOUT_SECONDS,
        help="Maximum wait for the local Chrome DevTools endpoint.",
    )
    parser.add_argument(
        "--navigation-timeout-seconds",
        type=float,
        default=DEFAULT_NAVIGATION_TIMEOUT_SECONDS,
        help="Maximum source-page navigation time.",
    )
    parser.add_argument(
        "--result-timeout-seconds",
        type=float,
        default=DEFAULT_RESULT_TIMEOUT_SECONDS,
        help="Maximum wait for a real eBay item link.",
    )

    return parser.parse_args()


def is_ebay_host(host: str | None) -> bool:
    """Return whether a hostname belongs to ebay.com."""

    if host is None:
        return False

    normalized = host.strip().casefold().rstrip(".")

    return (
        normalized == "ebay.com"
        or normalized.endswith(".ebay.com")
    )


def require_ebay_url(url: str) -> str:
    """Return a validated HTTPS ebay.com URL."""

    normalized = url.strip()

    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise EbayStorageStateError(
            "The eBay URL is malformed."
        ) from exc

    if parsed.scheme.casefold() != "https":
        raise EbayStorageStateError(
            "The eBay URL must use HTTPS."
        )

    if not is_ebay_host(parsed.hostname):
        raise EbayStorageStateError(
            f"Refusing non-eBay URL: {normalized}"
        )

    if parsed.username is not None or parsed.password is not None:
        raise EbayStorageStateError(
            "Credentials must not be embedded in the eBay URL."
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise EbayStorageStateError(
            "The eBay URL contains an invalid port."
        ) from exc

    if port not in {None, 443}:
        raise EbayStorageStateError(
            "The eBay URL must use the standard HTTPS port."
        )

    return normalized


def configured_sources(payload: Any) -> list[dict[str, Any]]:
    """Return source mappings from supported configuration shapes."""

    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(
        payload.get("sources"),
        list,
    ):
        values = payload["sources"]
    elif isinstance(payload, dict):
        values = [payload]
    else:
        raise EbayStorageStateError(
            "Unsupported eBay source configuration structure."
        )

    sources = [
        value
        for value in values
        if isinstance(value, dict)
    ]

    if not sources:
        raise EbayStorageStateError(
            "The eBay source configuration contains no source objects."
        )

    return sources


def load_source_url(
    config_path: Path,
    source_name: str,
) -> str:
    """Load and validate one configured eBay source URL."""

    normalized_name = source_name.strip()

    if not normalized_name:
        raise EbayStorageStateError(
            "The configured source name must not be empty."
        )

    resolved_config = (
        config_path
        .expanduser()
        .resolve()
    )

    try:
        payload = json.loads(
            resolved_config.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as exc:
        raise EbayStorageStateError(
            f"eBay source configuration does not exist: {resolved_config}"
        ) from exc
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise EbayStorageStateError(
            f"Could not read eBay source configuration: {exc}"
        ) from exc

    matches = [
        source
        for source in configured_sources(payload)
        if str(
            source.get(
                "name",
                "",
            )
        ).strip() == normalized_name
    ]

    if len(matches) != 1:
        raise EbayStorageStateError(
            "Expected exactly one configured source named "
            f"{normalized_name!r}; found {len(matches)}."
        )

    selected = matches[0]

    if selected.get("enabled") is False:
        raise EbayStorageStateError(
            f"Configured eBay source {normalized_name!r} is disabled."
        )

    configured_url = selected.get("url")

    if not isinstance(configured_url, str):
        raise EbayStorageStateError(
            f"Configured eBay source {normalized_name!r} has no URL."
        )

    return require_ebay_url(
        configured_url
    )


def validate_debug_port(port: int) -> int:
    """Return a valid TCP port."""

    if not 1 <= port <= 65_535:
        raise EbayStorageStateError(
            "The Chrome debug port must be between 1 and 65535."
        )

    return port


def launch_chrome(
    *,
    profile_dir: Path,
    url: str,
    debug_port: int,
) -> subprocess.Popen[bytes]:
    """Launch the dedicated local Chrome profile."""

    resolved_profile = (
        profile_dir
        .expanduser()
        .resolve()
    )

    resolved_profile.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        [
            "pkill",
            "-f",
            str(resolved_profile),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)

    command = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={resolved_profile}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--new-window",
        url,
    ]

    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_debug_endpoint(
    *,
    debug_port: int,
    timeout_seconds: int,
) -> None:
    """Wait until Chrome exposes its DevTools endpoint."""

    if timeout_seconds <= 0:
        raise EbayStorageStateError(
            "Debug timeout must be greater than zero."
        )

    deadline = time.monotonic() + timeout_seconds
    endpoint = (
        f"http://127.0.0.1:{debug_port}/json/version"
    )

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                endpoint,
                timeout=2,
            ) as response:
                payload = json.load(response)

            if payload.get("webSocketDebuggerUrl"):
                return
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ):
            time.sleep(1)

    raise EbayStorageStateError(
        "Google Chrome DevTools endpoint did not become available."
    )


def connect_browser(
    *,
    playwright: Playwright,
    debug_port: int,
) -> Browser:
    """Connect Playwright to the dedicated Chrome process."""

    return playwright.chromium.connect_over_cdp(
        f"http://127.0.0.1:{debug_port}"
    )


def select_context(
    browser: Browser,
) -> BrowserContext:
    """Return Chrome's exposed browser context."""

    if not browser.contexts:
        raise EbayStorageStateError(
            "Chrome exposed no browser context."
        )

    return browser.contexts[0]


def select_page(
    context: BrowserContext,
) -> Page:
    """Return an existing page or create one."""

    if context.pages:
        return context.pages[0]

    return context.new_page()


def is_signin_url(url: str) -> bool:
    """Return whether an eBay URL represents authentication."""

    try:
        parsed = urlsplit(
            url.strip()
        )
    except ValueError:
        return False

    host = (
        parsed.hostname
        or ""
    ).casefold()

    path = parsed.path.casefold()

    return (
        host.startswith("signin.ebay.")
        or host.startswith("signin.")
        and ".ebay." in host
        or "/signin" in path
    )


def is_access_block_status(
    status: int | None,
) -> bool:
    """Return whether HTTP status indicates blocked access."""

    return (
        status is not None
        and status in ACCESS_BLOCK_HTTP_STATUSES
    )


def contains_access_block_text(
    html: str,
) -> bool:
    """Return whether page content contains a known access block."""

    normalized = html.casefold()

    return any(
        signal in normalized
        for signal in ACCESS_BLOCK_TEXT
    )


def page_http_status(
    response: Any,
) -> int | None:
    """Return an integer HTTP status when available."""

    if response is None:
        return None

    status = getattr(
        response,
        "status",
        None,
    )

    return (
        status
        if isinstance(status, int)
        else None
    )


def assert_page_not_blocked(
    page: Page,
    *,
    http_status: int | None,
) -> None:
    """Fail closed for authentication or access-block conditions."""

    final_url = page.url

    if is_signin_url(final_url):
        raise EbayAuthenticationRequiredError(
            "eBay redirected the verification session to sign-in."
        )

    if is_access_block_status(http_status):
        raise EbayAccessBlockedError(
            "eBay rejected the verification request "
            f"with HTTP {http_status}."
        )

    html = page.content()

    if contains_access_block_text(html):
        raise EbayAccessBlockedError(
            "eBay returned a security/access verification page."
        )


def verify_source_access(
    *,
    page: Page,
    source_url: str,
    navigation_timeout_seconds: float,
    result_timeout_seconds: float,
) -> SourceVerification:
    """Verify that the configured source exposes real listing links."""

    requested_url = require_ebay_url(
        source_url
    )

    if navigation_timeout_seconds <= 0:
        raise EbayStorageStateError(
            "Navigation timeout must be greater than zero."
        )

    if result_timeout_seconds <= 0:
        raise EbayStorageStateError(
            "Result timeout must be greater than zero."
        )

    navigation_timeout_ms = int(
        navigation_timeout_seconds * 1000
    )
    result_timeout_ms = int(
        result_timeout_seconds * 1000
    )

    print("EBAY_SOURCE_VERIFICATION_MODE=existing_operator_page", flush=True)
    response = None

    http_status = page_http_status(
        response
    )

    assert_page_not_blocked(
        page,
        http_status=http_status,
    )

    locator = page.locator(
        ITEM_LINK_SELECTOR
    )

    try:
        locator.first.wait_for(
            state="attached",
            timeout=result_timeout_ms,
        )
    except PlaywrightTimeoutError as exc:
        assert_page_not_blocked(
            page,
            http_status=http_status,
        )

        raise EbayStorageStateError(
            "The verified eBay source produced no real item links."
        ) from exc

    assert_page_not_blocked(
        page,
        http_status=http_status,
    )

    final_url = page.url

    try:
        parsed_final = urlsplit(
            final_url
        )
    except ValueError as exc:
        raise EbayStorageStateError(
            "eBay finished on a malformed URL."
        ) from exc

    if not is_ebay_host(
        parsed_final.hostname
    ):
        raise EbayAccessBlockedError(
            "eBay verification redirected outside ebay.com."
        )

    item_link_count = locator.count()

    if item_link_count < 1:
        raise EbayStorageStateError(
            "The verified eBay source contains zero item links."
        )

    return SourceVerification(
        requested_url=requested_url,
        final_url=final_url,
        http_status=http_status,
        item_link_count=item_link_count,
    )


def is_ebay_cookie(
    cookie: dict[str, Any],
) -> bool:
    """Return whether a cookie belongs to ebay.com."""

    domain = str(
        cookie.get(
            "domain",
            "",
        )
    ).strip().casefold()

    normalized = domain.lstrip(".")

    return (
        normalized == "ebay.com"
        or normalized.endswith(".ebay.com")
    )


def validate_storage_state(
    payload: Any,
) -> dict[str, Any]:
    """Validate exported Playwright state without exposing secrets."""

    if not isinstance(payload, dict):
        raise EbayStorageStateError(
            "Storage state must be a JSON object."
        )

    cookies = payload.get("cookies")
    origins = payload.get("origins", [])

    if not isinstance(cookies, list):
        raise EbayStorageStateError(
            "Storage state has an invalid cookies value."
        )

    if not isinstance(origins, list):
        raise EbayStorageStateError(
            "Storage state has an invalid origins value."
        )

    ebay_cookies = [
        cookie
        for cookie in cookies
        if (
            isinstance(cookie, dict)
            and is_ebay_cookie(cookie)
        )
    ]

    if not ebay_cookies:
        raise EbayStorageStateError(
            "Exported state contains no eBay cookies."
        )

    return payload


def persist_storage_state(
    *,
    context: BrowserContext,
    output_path: Path,
) -> tuple[Path, int, int]:
    """Persist validated Playwright state atomically."""

    resolved_output = (
        output_path
        .expanduser()
        .resolve()
    )

    resolved_output.parent.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    os.chmod(
        resolved_output.parent,
        0o700,
    )

    temporary = resolved_output.with_suffix(
        resolved_output.suffix + ".tmp"
    )

    try:
        context.storage_state(
            path=str(temporary),
        )

        os.chmod(
            temporary,
            0o600,
        )

        payload = json.loads(
            temporary.read_text(
                encoding="utf-8",
            )
        )

        validated = validate_storage_state(
            payload
        )

        cookies = validated["cookies"]

        ebay_domains = {
            str(
                cookie.get(
                    "domain",
                    "",
                )
            ).strip().casefold()
            for cookie in cookies
            if (
                isinstance(cookie, dict)
                and is_ebay_cookie(cookie)
            )
        }

        ebay_cookie_count = sum(
            1
            for cookie in cookies
            if (
                isinstance(cookie, dict)
                and is_ebay_cookie(cookie)
            )
        )

        temporary.replace(
            resolved_output
        )

        os.chmod(
            resolved_output,
            0o600,
        )

        return (
            resolved_output,
            ebay_cookie_count,
            len(ebay_domains),
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def export_verified_storage_state(
    *,
    context: BrowserContext,
    source_url: str,
    output_path: Path,
    navigation_timeout_seconds: float,
    result_timeout_seconds: float,
) -> tuple[
    SourceVerification,
    Path,
    int,
    int,
]:
    """Verify source access before persisting any authentication state."""

    page = select_page(
        context
    )

    verification = verify_source_access(
        page=page,
        source_url=source_url,
        navigation_timeout_seconds=navigation_timeout_seconds,
        result_timeout_seconds=result_timeout_seconds,
    )

    (
        resolved_output,
        ebay_cookie_count,
        ebay_domain_count,
    ) = persist_storage_state(
        context=context,
        output_path=output_path,
    )

    return (
        verification,
        resolved_output,
        ebay_cookie_count,
        ebay_domain_count,
    )


def require_operator_confirmation(
    *,
    source_name: str,
    source_url: str,
) -> None:
    """Require explicit confirmation before verification and export."""

    print()
    print(
        "Chrome is using the dedicated eBay operator profile."
    )
    print(
        "Establish or verify the legitimate eBay session manually in Chrome."
    )
    print(
        "Do not enter credentials into this terminal."
    )
    print()
    print(
        "After confirmation, this command will make one verification "
        "navigation to the configured source:"
    )
    print(
        f"  source={source_name}"
    )
    print(
        f"  url={source_url}"
    )
    print()
    print(
        "It will fail closed on sign-in, access blocks, or missing item links."
    )
    print(
        "Only a successful source verification permits storage-state export."
    )
    print()
    print(
        "When the browser session is ready, type EXPORT."
    )
    print(
        "Anything else aborts without exporting storage state."
    )
    print()

    confirmation = input(
        "Confirmation: "
    ).strip()

    if confirmation != "EXPORT":
        raise EbayStorageStateError(
            "Operator did not authorize source verification/export."
        )


def main() -> int:
    """Verify the eBay source and export operator-established browser state."""

    arguments = parse_arguments()

    chrome_process: subprocess.Popen[bytes] | None = None

    try:
        debug_port = validate_debug_port(
            arguments.debug_port
        )

        source_url = load_source_url(
            arguments.config,
            arguments.source,
        )

        chrome_process = launch_chrome(
            profile_dir=arguments.profile_dir,
            url=DEFAULT_HOME_URL,
            debug_port=debug_port,
        )

        wait_for_debug_endpoint(
            debug_port=debug_port,
            timeout_seconds=arguments.debug_timeout_seconds,
        )

        with sync_playwright() as playwright:
            browser = connect_browser(
                playwright=playwright,
                debug_port=debug_port,
            )

            try:
                context = select_context(
                    browser
                )

                require_operator_confirmation(
                    source_name=arguments.source,
                    source_url=source_url,
                )

                (
                    verification,
                    output_path,
                    ebay_cookie_count,
                    ebay_domain_count,
                ) = export_verified_storage_state(
                    context=context,
                    source_url=source_url,
                    output_path=arguments.output,
                    navigation_timeout_seconds=(
                        arguments.navigation_timeout_seconds
                    ),
                    result_timeout_seconds=(
                        arguments.result_timeout_seconds
                    ),
                )
            finally:
                browser.close()

        print()
        print("================ RESULT ================")
        print("EBAY_SOURCE_VERIFICATION=PASS")
        print(
            f"EBAY_ITEM_LINK_COUNT={verification.item_link_count}"
        )
        print(
            f"EBAY_HTTP_STATUS={verification.http_status}"
        )
        print("EBAY_STORAGE_STATE_EXPORT=PASS")
        print(f"OUTPUT={output_path}")
        print(
            f"EBAY_COOKIE_COUNT={ebay_cookie_count}"
        )
        print(
            f"EBAY_DOMAIN_COUNT={ebay_domain_count}"
        )
        print("COOKIE_NAMES_PRINTED=false")
        print("COOKIE_VALUES_PRINTED=false")
        print("FILE_MODE=0600")
        print("RAILWAY_WRITE=false")
        print("DEPLOY=false")
        print("REFRESH_TRIGGER=false")
        print("DATABASE_WRITE=false")
        print()
        print(
            "Treat the output file as authentication material."
        )

        return 0

    except (
        EbayStorageStateError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "EBAY_SOURCE_VERIFICATION_OR_EXPORT=FAILED",
            file=sys.stderr,
        )
        print(
            "RAILWAY_WRITE=false",
            file=sys.stderr,
        )
        print(
            "DEPLOY=false",
            file=sys.stderr,
        )
        print(
            "REFRESH_TRIGGER=false",
            file=sys.stderr,
        )
        print(
            "DATABASE_WRITE=false",
            file=sys.stderr,
        )

        return 1
    finally:
        if (
            chrome_process is not None
            and chrome_process.poll() is None
        ):
            chrome_process.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
