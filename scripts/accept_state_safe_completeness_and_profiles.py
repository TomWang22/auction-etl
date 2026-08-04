#!/usr/bin/env python3
"""Read-only acceptance for completeness and media-profile pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8501",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
    )

    return parser.parse_args()


def _text(
    page: Page,
) -> str:
    """Return rendered application text."""
    container = page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first

    if container.count() == 0:
        return ""

    try:
        return (
            container.inner_text()
            or ""
        ).strip()
    except Exception:
        return ""


def open_page(
    page: Page,
    base_url: str,
    routes: tuple[str, ...],
    expected_title: str,
    timeout_ms: int,
) -> str:
    """Open one Streamlit page using deterministic routes."""
    diagnostics = []

    for route in routes:
        target = urljoin(
            base_url.rstrip(
                "/"
            )
            + "/",
            route,
        )

        try:
            response = page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            page.wait_for_timeout(
                800
            )

            rendered = _text(
                page
            )

            diagnostics.append(
                {
                    "target":
                        target,
                    "status":
                        response.status
                        if response
                        else None,
                    "title_visible":
                        (
                            expected_title.casefold()
                            in rendered.casefold()
                        ),
                }
            )

            if (
                expected_title.casefold()
                in rendered.casefold()
            ):
                return page.url
        except Exception as error:
            diagnostics.append(
                {
                    "target":
                        target,
                    "error":
                        str(
                            error
                        ),
                }
            )

    raise RuntimeError(
        f"{expected_title} could not be opened.\n"
        + json.dumps(
            diagnostics,
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    """Run the complete read-only browser acceptance."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors = []
    page_errors = []
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width":
                    1600,
                "height":
                    1100,
            }
        )

        page = context.new_page()

        completeness_url = open_page(
            page,
            args.url,
            (
                "Listing_Completeness_Review",
                "10_Listing_Completeness_Review",
            ),
            "Listing Completeness Review",
            args.timeout_ms,
        )

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
            lambda error:
                page_errors.append(
                    str(
                        error
                    )
                ),
        )

        page.get_by_role(
            "combobox",
            name="Assigned auction listing",
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        completeness_screenshot = (
            args.output_dir
            / "listing-completeness.png"
        )

        page.screenshot(
            path=str(
                completeness_screenshot
            ),
            full_page=True,
        )

        results.append(
            {
                "page":
                    "Listing Completeness Review",
                "url":
                    completeness_url,
                "selector_visible":
                    True,
                "screenshot":
                    str(
                        completeness_screenshot
                    ),
            }
        )

        profile_url = open_page(
            page,
            args.url,
            (
                "Media_Profile_Admin",
                "11_Media_Profile_Admin",
            ),
            "Media Profile Administration",
            args.timeout_ms,
        )

        page.get_by_role(
            "button",
            name="Preview media-profile changes",
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        profile_screenshot = (
            args.output_dir
            / "media-profile-admin.png"
        )

        page.screenshot(
            path=str(
                profile_screenshot
            ),
            full_page=True,
        )

        results.append(
            {
                "page":
                    "Media Profile Administration",
                "url":
                    profile_url,
                "preview_visible":
                    True,
                "screenshot":
                    str(
                        profile_screenshot
                    ),
            }
        )

        browser.close()

    report = {
        "pages":
            results,
        "console_errors":
            console_errors,
        "page_errors":
            page_errors,
        "persistence_controls_clicked":
            0,
        "database_writes":
            0,
        "success":
            (
                len(
                    results
                )
                == 2
                and not console_errors
                and not page_errors
            ),
    }

    report_path = (
        args.output_dir
        / "report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    return (
        0
        if report[
            "success"
        ]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
