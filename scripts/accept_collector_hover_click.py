"""Accept the live Collector Review hover/click interaction."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    Frame,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8501"

CHROME_CANDIDATES = (
    Path(
        "/Applications/Google Chrome.app/"
        "Contents/MacOS/Google Chrome"
    ),
    Path(
        "/Applications/Google Chrome Canary.app/"
        "Contents/MacOS/Google Chrome Canary"
    ),
)


class AcceptanceError(RuntimeError):
    """Raised when the live UI contract is not satisfied."""


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the visible Collector Review "
            "AG Grid and row editor."
        )
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--headless",
        action="store_true",
    )
    parser.add_argument(
        "--keep-open-seconds",
        type=float,
        default=3.0,
    )

    return parser.parse_args()


def launch_browser(
    playwright: Playwright,
    *,
    headless: bool,
) -> Browser:
    """Launch installed Chrome or a Playwright fallback."""
    executable = next(
        (
            candidate
            for candidate in CHROME_CANDIDATES
            if candidate.is_file()
        ),
        None,
    )

    launch_arguments: dict[str, Any] = {
        "headless": headless,
        "slow_mo": 80 if not headless else 0,
        "args": [
            "--start-maximized",
        ],
    }

    if executable is not None:
        launch_arguments[
            "executable_path"
        ] = str(executable)

        return playwright.chromium.launch(
            **launch_arguments
        )

    try:
        return playwright.chromium.launch(
            channel="chrome",
            **launch_arguments,
        )
    except Exception:
        return playwright.chromium.launch(
            **launch_arguments
        )


def visible_row_in_frame(
    frame: Frame,
) -> Locator | None:
    """Return one visible center row from a visible component."""
    try:
        frame_element = (
            frame.frame_element()
        )

        if not frame_element.is_visible():
            return None

        bounds = (
            frame_element.bounding_box()
        )

        if (
            bounds is None
            or bounds["width"] < 200
            or bounds["height"] < 160
        ):
            return None

        root = frame.locator(
            ".ag-root-wrapper"
        ).first

        if (
            root.count() == 0
            or not root.is_visible()
        ):
            return None

        rows = frame.locator(
            ".ag-center-cols-container "
            ".ag-row"
        )

        row_count = min(
            rows.count(),
            20,
        )

        for index in range(
            row_count
        ):
            row = rows.nth(index)

            if row.is_visible():
                return row

    except Exception:
        return None

    return None


def find_visible_grid(
    page: Page,
    *,
    timeout_seconds: float = 120.0,
) -> tuple[Frame, Locator]:
    """Find the active-tab AG Grid, not a hidden tab iframe."""
    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    while (
        time.monotonic()
        < deadline
    ):
        for frame in page.frames:
            if frame == page.main_frame:
                continue

            row = visible_row_in_frame(
                frame
            )

            if row is not None:
                return frame, row

        page.wait_for_timeout(400)

    raise AcceptanceError(
        "No visible AG Grid row was found. "
        "Hidden inactive-tab grids were ignored."
    )


def visible_application_errors(
    page: Page,
) -> list[str]:
    """Return visible Streamlit error messages."""
    messages: list[str] = []

    selectors = (
        '[data-testid="stException"]',
        '[data-testid="stAlert"]',
    )

    for selector in selectors:
        locator = page.locator(
            selector
        )

        for index in range(
            locator.count()
        ):
            element = locator.nth(
                index
            )

            try:
                if not element.is_visible():
                    continue

                text = (
                    element.inner_text()
                    .strip()
                )

                lowered = text.lower()

                if (
                    "error" in lowered
                    or "exception" in lowered
                    or "traceback" in lowered
                    or "could not load" in lowered
                ):
                    messages.append(
                        text
                    )
            except Exception:
                continue

    return messages


def diagnostics_payload(
    page: Page,
    error: Exception,
    console_errors: list[str],
    page_errors: list[str],
) -> dict[str, Any]:
    """Create compact browser diagnostics."""


    if page.is_closed():
        return {
            "error": str(error),
            "url": "",
            "title": "",
            "body_preview": "",
            "console_errors": console_errors,
            "page_errors": page_errors,
            "visible_application_errors": [],
            "frames": [],
            "page_closed": True,
        }
    try:
        body_text = (
            page.locator("body")
            .inner_text(
                timeout=5_000
            )
        )
    except Exception:
        body_text = ""

    frame_details: list[
        dict[str, Any]
    ] = []

    for frame in page.frames:
        detail: dict[str, Any] = {
            "url": frame.url,
            "is_main": (
                frame
                == page.main_frame
            ),
        }

        try:
            element = (
                frame.frame_element()
            )
            detail["visible"] = (
                element.is_visible()
            )
            detail["bounds"] = (
                element.bounding_box()
            )
        except Exception:
            detail["visible"] = None
            detail["bounds"] = None

        try:
            detail["grid_roots"] = (
                frame.locator(
                    ".ag-root-wrapper"
                ).count()
            )
            detail["rows"] = (
                frame.locator(
                    ".ag-center-cols-container "
                    ".ag-row"
                ).count()
            )
        except Exception:
            detail["grid_roots"] = None
            detail["rows"] = None

        frame_details.append(
            detail
        )

    return {
        "error": str(error),
        "url": page.url,
        "title": page.title(),
        "body_preview":
            body_text[:10_000],
        "console_errors":
            console_errors,
        "page_errors":
            page_errors,
        "visible_application_errors":
            visible_application_errors(
                page
            ),
        "frames":
            frame_details,
    }


def choose_click_target(
    row: Locator,
) -> Locator:
    """Choose a visible non-link cell in one center row."""
    preferred_columns = (
        "Seller",
        "Auction type",
        "Opened",
        "Closed",
        "Added",
    )

    for column_name in preferred_columns:
        candidate = row.locator(
            (
                '.ag-cell[col-id="'
                + column_name
                + '"]'
            )
        ).first

        try:
            if (
                candidate.count()
                and candidate.is_visible()
            ):
                return candidate
        except Exception:
            continue

    cells = row.locator(
        ".ag-cell"
    )

    for index in range(
        cells.count()
    ):
        candidate = cells.nth(
            index
        )

        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue

    return row


def main() -> int:
    """Exercise the real active listing grid."""
    args = parse_args()

    args.evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=args.headless,
        )

        context = browser.new_context(
            no_viewport=not args.headless,
            viewport=(
                {
                    "width": 1600,
                    "height": 1000,
                }
                if args.headless
                else None
            ),
        )

        page = context.new_page()

        page.on(
            "console",
            lambda message: (
                console_errors.append(
                    message.text
                )
                if message.type == "error"
                else None
            ),
        )

        page.on(
            "pageerror",
            lambda error: (
                page_errors.append(
                    str(error)
                )
            ),
        )

        try:
            page.bring_to_front()

            page.goto(
                (
                    f"{args.base_url}/"
                    f"?hover_click_acceptance="
                    f"{int(time.time())}"
                ),
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=120_000,
            )

            page.get_by_text(
                "Auction Collector Review",
                exact=False,
            ).first.wait_for(
                state="visible",
                timeout=120_000,
            )

            page.get_by_text(
                "Search results",
                exact=True,
            ).wait_for(
                state="visible",
                timeout=120_000,
            )

            application_errors = (
                visible_application_errors(
                    page
                )
            )

            if application_errors:
                raise AcceptanceError(
                    "\n\n".join(
                        application_errors
                    )
                )

            grid_frame, first_row = (
                find_visible_grid(
                    page
                )
            )

            visible_checkboxes = (
                grid_frame.locator(
                    ".ag-selection-checkbox:"
                    "visible"
                ).count()
            )

            if visible_checkboxes:
                raise AcceptanceError(
                    "The active listing grid "
                    "still displays selection "
                    "checkboxes."
                )

            row_identity = (
                first_row.get_attribute(
                    "row-id"
                )
                or ""
            )

            first_row.hover()
            page.wait_for_timeout(400)

            row_classes = (
                first_row.get_attribute(
                    "class"
                )
                or ""
            )

            if (
                "ag-row-hover"
                not in row_classes
            ):
                raise AcceptanceError(
                    "Hover did not activate "
                    "full-row highlighting."
                )

            cursor = first_row.evaluate(
                (
                    "element => "
                    "getComputedStyle(element)"
                    ".cursor"
                )
            )

            if cursor != "pointer":
                raise AcceptanceError(
                    "Expected the row cursor "
                    f"to be 'pointer'; found "
                    f"{cursor!r}."
                )

            click_target = (
                choose_click_target(
                    first_row
                )
            )

            click_target.click()

            save_button = (
                page.get_by_role(
                    "button",
                    name=(
                        "Save collector record"
                    ),
                )
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

            application_errors = (
                visible_application_errors(
                    page
                )
            )

            if application_errors:
                raise AcceptanceError(
                    "\n\n".join(
                        application_errors
                    )
                )

            screenshot_path = (
                args.evidence_dir
                / (
                    "hover-click-"
                    "editor-open.png"
                )
            )

            page.screenshot(
                path=str(
                    screenshot_path
                ),
                full_page=True,
            )

            result = {
                "state": "success",
                "selected_row_identity":
                    row_identity,
                "visible_checkboxes":
                    visible_checkboxes,
                "cursor":
                    cursor,
                "screenshot":
                    str(
                        screenshot_path
                    ),
                "console_errors":
                    console_errors,
                "page_errors":
                    page_errors,
            }

            (
                args.evidence_dir
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

            print("✓ Visible listing grid located.")
            print("✓ Hidden tab grids were ignored.")
            print("✓ No selection checkboxes rendered.")
            print("✓ Full-row hover activated.")
            print("✓ Pointer cursor activated.")
            print("✓ Row click opened the editor.")

            if row_identity:
                print(
                    "✓ Selected row: "
                    f"{row_identity}"
                )

            print(
                "✓ Screenshot: "
                f"{screenshot_path}"
            )

            if (
                not args.headless
                and args.keep_open_seconds
                > 0
            ):
                page.wait_for_timeout(
                    int(
                        args.keep_open_seconds
                        * 1_000
                    )
                )

        except Exception as error:
            failure_directory = (
                args.evidence_dir
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

            diagnostics = (
                diagnostics_payload(
                    page,
                    error,
                    console_errors,
                    page_errors,
                )
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
                "Diagnostics: "
                f"{diagnostics_path}"
            ) from error

        finally:
            context.close()
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
