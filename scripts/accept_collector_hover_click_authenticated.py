"""Accept the authenticated live Collector Review hover/click interaction."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from scripts.accept_collector_hover_click import (
    AcceptanceError,
    choose_click_target,
    diagnostics_payload,
    find_visible_grid,
    launch_browser,
    visible_application_errors,
)


DEFAULT_BASE_URL = "https://auction-scout-main-test.streamlit.app/"
STREAMLIT_APP_FRAME_SELECTOR = 'iframe[title="streamlitApp"]'
LOGIN_SCREEN_HEADING = "Collector Ledger"
LOGIN_BUTTON_NAME = "Sign in or create account"
AUTHENTICATED_APPLICATION_HEADING = "Review marketplace sales"
AUTHENTICATED_RESULTS_HEADING = "Search results"
SIGNED_IN_MARKER = "Signed in as"
LOG_OUT_BUTTON = "Log out"
FORBIDDEN_DIAGNOSTIC_KEYS = frozenset(
    {
        "cookie",
        "cookies",
        "localstorage",
        "storage_state",
        "authorization",
        "access_token",
        "password",
    }
)


def parse_arguments() -> argparse.Namespace:
    """Parse live authenticated acceptance options."""
    parser = argparse.ArgumentParser(
        description=(
            "Capture or reuse an authenticated Streamlit browser state "
            "and exercise Collector Review."
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
    )
    parser.add_argument(
        "--capture-auth-state",
        action="store_true",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
    )
    parser.add_argument(
        "--login-timeout-seconds",
        type=float,
        default=300.0,
    )
    return parser.parse_args()


def normalized_base_url(value: str) -> str:
    """Return one normalized application base URL."""
    value = value.strip()

    if not value.startswith(("https://", "http://")):
        raise SystemExit(
            "ERROR: --base-url must be an HTTP(S) URL."
        )

    return value.rstrip("/")


def _locator_is_visible(
    locator: Any,
) -> bool:
    """Return whether one Playwright locator currently shows a node."""
    try:
        if locator.count() < 1:
            return False

        return bool(
            locator.first.is_visible()
        )
    except Exception:
        return False


def application_scopes(
    page: Page,
) -> list[Any]:
    """Return Streamlit app iframe scopes, then pages, including popups."""
    pages: list[Any] = [
        page
    ]

    try:
        pages = list(
            page.context.pages
        )

        if page not in pages:
            pages.insert(
                0,
                page,
            )
    except Exception:
        pages = [
            page
        ]

    scopes: list[Any] = []
    seen: set[int] = set()

    for candidate in pages:
        marker = id(
            candidate
        )

        if marker in seen:
            continue

        seen.add(
            marker
        )

        try:
            scopes.append(
                candidate.frame_locator(
                    STREAMLIT_APP_FRAME_SELECTOR
                )
            )
        except Exception:
            pass

        scopes.append(
            candidate
        )

    return scopes


def scope_shows_login_screen(
    scope: Any,
) -> bool:
    """Return whether one browsing scope is the unauthenticated login shell."""
    heading = scope.get_by_role(
        "heading",
        name=LOGIN_SCREEN_HEADING,
        exact=False,
    )
    button = scope.get_by_role(
        "button",
        name=LOGIN_BUTTON_NAME,
        exact=False,
    )

    return (
        _locator_is_visible(
            heading
        )
        or _locator_is_visible(
            button
        )
    )


def scope_shows_authenticated_application(
    scope: Any,
) -> bool:
    """Return whether one browsing scope shows authenticated Collector Review."""
    if scope_shows_login_screen(
        scope
    ):
        return False

    logout = scope.get_by_role(
        "button",
        name=LOG_OUT_BUTTON,
        exact=False,
    )
    signed_in = scope.get_by_text(
        SIGNED_IN_MARKER,
        exact=False,
    )
    heading = scope.get_by_role(
        "heading",
        name=AUTHENTICATED_APPLICATION_HEADING,
        exact=False,
    )
    results_heading = scope.get_by_role(
        "heading",
        name=AUTHENTICATED_RESULTS_HEADING,
        exact=False,
    )
    results_text = scope.get_by_text(
        AUTHENTICATED_RESULTS_HEADING,
        exact=True,
    )

    has_results = (
        _locator_is_visible(
            results_heading
        )
        or _locator_is_visible(
            results_text
        )
    )

    return (
        _locator_is_visible(
            logout
        )
        or _locator_is_visible(
            signed_in
        )
        or (
            _locator_is_visible(
                heading
            )
            and has_results
        )
    )


def application_is_authenticated(
    page: Page,
) -> bool:
    """Return whether any app iframe or page is authenticated Collector Review."""
    return any(
        scope_shows_authenticated_application(
            scope
        )
        for scope in application_scopes(
            page
        )
    )


def wait_for_authenticated_application(
    page: Page,
    *,
    timeout_seconds: float,
) -> None:
    """Wait until authenticated Collector Review is visible in the app frame."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if application_is_authenticated(
            page
        ):
            return

        page.wait_for_timeout(
            500
        )

    raise AcceptanceError(
        "Authenticated Collector Review did not become visible."
    )


def wait_for_search_results(
    page: Page,
    *,
    timeout_seconds: float,
) -> None:
    """Wait until the authenticated Search results section is visible."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        for scope in application_scopes(
            page
        ):
            heading = scope.get_by_role(
                "heading",
                name=AUTHENTICATED_RESULTS_HEADING,
                exact=False,
            )
            text = scope.get_by_text(
                AUTHENTICATED_RESULTS_HEADING,
                exact=True,
            )

            if (
                _locator_is_visible(
                    heading
                )
                or _locator_is_visible(
                    text
                )
            ):
                return

        page.wait_for_timeout(
            500
        )

    raise AcceptanceError(
        "Authenticated Search results did not become visible."
    )


def first_visible_save_button(
    page: Page,
) -> Any:
    """Return the Save control from the app iframe or page without clicking it."""
    for scope in application_scopes(
        page
    ):
        button = scope.get_by_role(
            "button",
            name="Save collector record",
            exact=False,
        )

        if _locator_is_visible(
            button
        ):
            return button

    return page.get_by_role(
        "button",
        name="Save collector record",
    )


def _safe_title(
    target: Any,
) -> str:
    """Return a page or frame title without raising."""
    try:
        title = target.title()
    except Exception:
        title = getattr(
            target,
            "_title",
            "",
        )

    return str(
        title or ""
    )


def _visible_heading_names(
    scope: Any,
) -> list[str]:
    """Return visible heading names from one page, frame, or test double."""
    raw_headings = getattr(
        scope,
        "headings",
        None,
    )

    if raw_headings is not None:
        return [
            str(item)
            for item in raw_headings
            if str(item).strip()
        ]

    names: list[str] = []

    try:
        locator = scope.get_by_role(
            "heading"
        )
        count = locator.count()
    except Exception:
        return names

    for index in range(
        count
    ):
        item = locator.nth(
            index
        )

        try:
            if not item.is_visible():
                continue

            text = item.inner_text().strip()
        except Exception:
            continue

        if text:
            names.append(
                text
            )

    return names


def _sanitize_diagnostics(
    value: Any,
) -> Any:
    """Drop secret-bearing keys from diagnostic payloads."""
    if isinstance(
        value,
        dict,
    ):
        sanitized: dict[str, Any] = {}

        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_DIAGNOSTIC_KEYS:
                continue

            sanitized[str(key)] = _sanitize_diagnostics(
                item
            )

        return sanitized

    if isinstance(
        value,
        list,
    ):
        return [
            _sanitize_diagnostics(
                item
            )
            for item in value
        ]

    return value


def authentication_diagnostics_payload(
    page: Page,
    error: Exception,
    console_errors: list[str],
    page_errors: list[str],
) -> dict[str, Any]:
    """Create sanitized capture diagnostics including frames and popups."""
    try:
        payload = diagnostics_payload(
            page,
            error,
            console_errors,
            page_errors,
        )
    except Exception:
        payload = {
            "error": str(error),
            "url": str(
                getattr(
                    page,
                    "url",
                    "",
                )
                or ""
            ),
            "title": _safe_title(
                page
            ),
            "body_preview": "",
            "console_errors": console_errors,
            "page_errors": page_errors,
            "visible_application_errors": [],
            "frames": [],
        }

    pages_payload: list[dict[str, Any]] = []
    context_pages = [
        page
    ]

    try:
        context_pages = list(
            page.context.pages
        )
    except Exception:
        context_pages = [
            page
        ]

    for candidate in context_pages:
        pages_payload.append(
            {
                "url": str(
                    getattr(
                        candidate,
                        "url",
                        "",
                    )
                    or ""
                ),
                "title": _safe_title(
                    candidate
                ),
                "closed": bool(
                    getattr(
                        candidate,
                        "is_closed",
                        lambda: False,
                    )()
                ),
            }
        )

    frame_payload: list[dict[str, Any]] = []
    frames = list(
        getattr(
            page,
            "frames",
            [],
        )
    )
    iframe = None

    try:
        iframe = page.frame_locator(
            STREAMLIT_APP_FRAME_SELECTOR
        )
    except Exception:
        iframe = None

    diagnostic_scopes = [
        *frames,
    ]

    if iframe is not None:
        diagnostic_scopes.append(
            iframe
        )

    seen_urls: set[str] = set()

    for scope in diagnostic_scopes:
        url = str(
            getattr(
                scope,
                "url",
                "",
            )
            or ""
        )
        headings = _visible_heading_names(
            scope
        )
        marker = url + "|" + "|".join(
            headings
        )

        if marker in seen_urls:
            continue

        seen_urls.add(
            marker
        )
        frame_payload.append(
            {
                "url": url,
                "title": _safe_title(
                    scope
                ),
                "headings": headings,
            }
        )

    payload["pages"] = pages_payload
    payload["frames"] = frame_payload
    payload["login_screen_visible"] = any(
        scope_shows_login_screen(
            scope
        )
        for scope in application_scopes(
            page
        )
    )
    payload["authenticated"] = application_is_authenticated(
        page
    )

    return _sanitize_diagnostics(
        payload
    )


def write_authentication_failure_evidence(
    *,
    page: Page,
    error: Exception,
    evidence_dir: Path,
    console_errors: list[str],
    page_errors: list[str],
) -> Path:
    """Persist a screenshot and sanitized diagnostics for an auth timeout."""
    failure_directory = (
        evidence_dir
        / "failure"
    )
    failure_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    screenshot_path = (
        failure_directory
        / "failure.png"
    )

    try:
        if not page.is_closed():
            page.screenshot(
                path=str(
                    screenshot_path
                ),
                full_page=True,
            )
    except Exception:
        pass

    diagnostics = authentication_diagnostics_payload(
        page,
        error,
        console_errors,
        page_errors,
    )
    diagnostics["screenshot"] = str(
        screenshot_path
    )

    diagnostics_path = (
        failure_directory
        / "diagnostics.json"
    )
    diagnostics_path.write_text(
        json.dumps(
            diagnostics,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return diagnostics_path


def capture_authentication_state(
    *,
    base_url: str,
    storage_state: Path,
    timeout_seconds: float,
    evidence_dir: Path | None = None,
) -> int:
    """Capture a private browser state after interactive OIDC login."""
    storage_state.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    capture_evidence = evidence_dir or (
        storage_state.parent
        / "streamlit-auth-capture-evidence"
    )
    capture_evidence.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=False,
        )

        context = browser.new_context(
            no_viewport=True,
        )

        page = context.new_page()

        def attach_page_diagnostics(
            target: Page,
        ) -> None:
            target.on(
                "console",
                lambda message: (
                    console_errors.append(
                        message.text
                    )
                    if message.type == "error"
                    else None
                ),
            )
            target.on(
                "pageerror",
                lambda error: page_errors.append(
                    str(error)
                ),
            )

        attach_page_diagnostics(
            page
        )
        context.on(
            "page",
            attach_page_diagnostics,
        )

        try:
            page.goto(
                base_url,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            print(
                "Complete the normal Streamlit/OIDC login "
                "in the opened browser."
            )

            wait_for_authenticated_application(
                page,
                timeout_seconds=timeout_seconds,
            )

            context.storage_state(
                path=str(storage_state),
            )

        except Exception as error:
            diagnostics_path = (
                write_authentication_failure_evidence(
                    page=page,
                    error=error,
                    evidence_dir=capture_evidence,
                    console_errors=console_errors,
                    page_errors=page_errors,
                )
            )

            raise AcceptanceError(
                f"{error}\n"
                f"Diagnostics: {diagnostics_path}"
            ) from error

        finally:
            context.close()
            browser.close()

    storage_state.chmod(0o600)

    print("STREAMLIT_AUTH_STATE_CAPTURE=PASS")
    print("STREAMLIT_AUTH_STATE_MODE=0600")
    print("STREAMLIT_AUTH_STATE_CONTENT_PRINTED=false")

    return 0


def authenticated_context(
    *,
    browser: Any,
    storage_state: Path,
    headless: bool,
) -> BrowserContext:
    """Create a browser context from private authenticated state."""
    if not storage_state.is_file():
        raise SystemExit(
            "ERROR: authenticated Streamlit storage state is missing. "
            "Run with --capture-auth-state first."
        )

    return browser.new_context(
        storage_state=str(storage_state),
        no_viewport=not headless,
        viewport=(
            {
                "width": 1600,
                "height": 1000,
            }
            if headless
            else None
        ),
    )


def run_acceptance(
    *,
    base_url: str,
    storage_state: Path,
    evidence_dir: Path,
    headless: bool,
) -> int:
    """Exercise the authenticated live listing grid without saving."""
    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=headless,
        )

        context = authenticated_context(
            browser=browser,
            storage_state=storage_state,
            headless=headless,
        )

        page = context.new_page()

        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )

        page.on(
            "pageerror",
            lambda error: page_errors.append(
                str(error)
            ),
        )

        try:
            acceptance_url = (
                f"{base_url}/"
                f"?hover_click_acceptance={int(time.time())}"
            )

            page.goto(
                acceptance_url,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            wait_for_authenticated_application(
                page,
                timeout_seconds=120.0,
            )

            wait_for_search_results(
                page,
                timeout_seconds=120.0,
            )

            application_errors = visible_application_errors(
                page
            )

            if application_errors:
                raise AcceptanceError(
                    "\n\n".join(application_errors)
                )

            grid_frame, first_row = find_visible_grid(
                page,
                timeout_seconds=120.0,
            )

            visible_checkboxes = (
                grid_frame.locator(
                    ".ag-selection-checkbox:visible"
                ).count()
            )

            if visible_checkboxes:
                raise AcceptanceError(
                    "The active listing grid displays "
                    "selection checkboxes."
                )

            row_identity = (
                first_row.get_attribute("row-id")
                or ""
            )

            first_row.hover()
            page.wait_for_timeout(400)

            row_classes = (
                first_row.get_attribute("class")
                or ""
            )

            if "ag-row-hover" not in row_classes:
                raise AcceptanceError(
                    "Hover did not activate full-row highlighting."
                )

            cursor = first_row.evaluate(
                "element => getComputedStyle(element).cursor"
            )

            if cursor != "pointer":
                raise AcceptanceError(
                    "Expected row cursor 'pointer'; "
                    f"found {cursor!r}."
                )

            click_target = choose_click_target(
                first_row
            )

            click_target.click()

            save_button = first_visible_save_button(
                page
            )

            save_button.wait_for(
                state="attached",
                timeout=120_000,
            )

            save_button.scroll_into_view_if_needed()

            save_button.wait_for(
                state="visible",
                timeout=30_000,
            )

            application_errors = visible_application_errors(
                page
            )

            if application_errors:
                raise AcceptanceError(
                    "\n\n".join(application_errors)
                )

            screenshot_path = (
                evidence_dir
                / "authenticated-hover-click-editor-open.png"
            )

            page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

            result = {
                "state": "success",
                "authenticated": True,
                "selected_row_identity": row_identity,
                "visible_checkboxes": visible_checkboxes,
                "cursor": cursor,
                "save_button_clicked": False,
                "screenshot": str(screenshot_path),
                "console_errors": console_errors,
                "page_errors": page_errors,
            }

            (
                evidence_dir
                / "acceptance.json"
            ).write_text(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            print("STREAMLIT_AUTHENTICATED_SESSION=PASS")
            print("STREAMLIT_VISIBLE_GRID=PASS")
            print("STREAMLIT_SELECTION_CHECKBOXES_ABSENT=PASS")
            print("STREAMLIT_FULL_ROW_HOVER=PASS")
            print("STREAMLIT_POINTER_CURSOR=PASS")
            print("STREAMLIT_ROW_CLICK_EDITOR_OPEN=PASS")
            print("STREAMLIT_SAVE_BUTTON_CLICKED=false")
            print("STREAMLIT_LIVE_BROWSER_ACCEPTANCE=PASS")

        except Exception as error:
            failure_directory = (
                evidence_dir
                / "failure"
            )

            failure_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                page.screenshot(
                    path=str(
                        failure_directory
                        / "failure.png"
                    ),
                    full_page=True,
                )
            except Exception:
                pass

            diagnostics = authentication_diagnostics_payload(
                page,
                error,
                console_errors,
                page_errors,
            )

            diagnostics_path = (
                failure_directory
                / "diagnostics.json"
            )

            diagnostics_path.write_text(
                json.dumps(
                    diagnostics,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            raise AcceptanceError(
                f"{error}\n"
                f"Diagnostics: {diagnostics_path}"
            ) from error

        finally:
            context.close()
            browser.close()

    return 0


def main() -> int:
    """Capture authentication or run live authenticated acceptance."""
    arguments = parse_arguments()

    base_url = normalized_base_url(
        arguments.base_url
    )

    if arguments.capture_auth_state:
        return capture_authentication_state(
            base_url=base_url,
            storage_state=arguments.storage_state,
            timeout_seconds=arguments.login_timeout_seconds,
            evidence_dir=arguments.evidence_dir,
        )

    if arguments.evidence_dir is None:
        raise SystemExit(
            "ERROR: --evidence-dir is required "
            "unless --capture-auth-state is used."
        )

    return run_acceptance(
        base_url=base_url,
        storage_state=arguments.storage_state,
        evidence_dir=arguments.evidence_dir,
        headless=arguments.headless,
    )


if __name__ == "__main__":
    raise SystemExit(main())
