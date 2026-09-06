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


def wait_for_authenticated_application(
    page: Page,
    *,
    timeout_seconds: float,
) -> None:
    """Wait until Collector Review is visible after authentication."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        title = page.get_by_text(
            "Auction Collector Review",
            exact=False,
        )

        if title.count():
            try:
                if title.first.is_visible():
                    return
            except Exception:
                pass

        page.wait_for_timeout(500)

    raise AcceptanceError(
        "Authenticated Collector Review did not become visible."
    )


def capture_authentication_state(
    *,
    base_url: str,
    storage_state: Path,
    timeout_seconds: float,
) -> int:
    """Capture a private browser state after interactive OIDC login."""
    storage_state.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=False,
        )

        context = browser.new_context(
            no_viewport=True,
        )

        page = context.new_page()

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

            page.get_by_text(
                "Search results",
                exact=True,
            ).wait_for(
                state="visible",
                timeout=120_000,
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

            save_button = page.get_by_role(
                "button",
                name="Save collector record",
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

            diagnostics = diagnostics_payload(
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
