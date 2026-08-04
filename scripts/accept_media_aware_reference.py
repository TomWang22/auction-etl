#!/usr/bin/env python3
"""Read-only browser acceptance for every exact pressing profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright
from sqlalchemy import create_engine

from auction_etl.services.media_aware_reference import (
    list_pressings,
    load_media_profile,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify the canonical media-aware master-reference "
            "page for every exact pressing without writing."
        )
    )

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


def _app_text(
    page: Page,
) -> str:
    """Return rendered Streamlit application text."""
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


def _page_ready(
    page: Page,
) -> bool:
    """Return whether the canonical page has rendered."""
    text_value = _app_text(
        page
    ).casefold()

    return (
        "pressing completeness reference"
        in text_value
        and "exact pressing"
        in text_value
        and "master reference"
        in text_value
    )


def open_reference_page(
    page: Page,
    base_url: str,
    timeout_ms: int,
) -> str:
    """Open Page 2 using direct routes or sidebar links."""
    candidates = (
        "Completeness_Reference",
        "2_Completeness_Reference",
        "Pressing_Completeness_Reference",
    )

    diagnostics: list[
        dict[str, Any]
    ] = []

    for route in candidates:
        requested_url = urljoin(
            base_url.rstrip(
                "/"
            )
            + "/",
            route,
        )

        try:
            response = page.goto(
                requested_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            page.wait_for_timeout(
                800
            )

            diagnostics.append(
                {
                    "requested_url":
                        requested_url,
                    "final_url":
                        page.url,
                    "status":
                        (
                            response.status
                            if response
                            else None
                        ),
                    "ready":
                        _page_ready(
                            page
                        ),
                }
            )

            if _page_ready(
                page
            ):
                return page.url
        except Exception as error:
            diagnostics.append(
                {
                    "requested_url":
                        requested_url,
                    "error":
                        str(
                            error
                        ),
                }
            )

    page.goto(
        base_url,
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )

    page.wait_for_timeout(
        1_000
    )

    anchors = page.locator(
        "a[href]"
    )

    for index in range(
        anchors.count()
    ):
        anchor = anchors.nth(
            index
        )

        try:
            href = (
                anchor.get_attribute(
                    "href"
                )
                or ""
            )

            label = (
                anchor.inner_text()
                or anchor.get_attribute(
                    "aria-label"
                )
                or ""
            ).strip()
        except Exception:
            continue

        normalized = (
            label
            + " "
            + href
        ).casefold()

        if (
            "completeness reference"
            not in normalized
        ):
            continue

        page.goto(
            urljoin(
                base_url,
                href,
            ),
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        page.wait_for_timeout(
            800
        )

        if _page_ready(
            page
        ):
            return page.url

    raise RuntimeError(
        "Completeness Reference page could not be opened.\n"
        + json.dumps(
            diagnostics,
            ensure_ascii=False,
            indent=2,
        )
        + "\nRendered excerpt:\n"
        + _app_text(
            page
        )[:5000]
    )


def choose_pressing(
    page: Page,
    pressing_id: int,
    timeout_ms: int,
) -> str:
    """Select one exact pressing."""
    combobox = page.get_by_role(
        "combobox",
        name="Exact pressing",
    ).first

    combobox.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    combobox.click()

    option = page.get_by_role(
        "option",
        name=re.compile(
            rf"Pressing\s*#{pressing_id}\b",
            re.IGNORECASE,
        ),
    ).first

    option.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    selected_text = (
        option.inner_text()
        or ""
    ).strip()

    option.click()

    return selected_text


def main() -> int:
    """Run read-only acceptance for all exact pressings."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    database_url = os.environ.get(
        "DATABASE_URL",
        (
            "postgresql+psycopg://auction:auction"
            "@127.0.0.1:5544/auction_warehouse"
        ),
    )

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
    )

    pressings = list_pressings(
        engine
    )

    if not pressings:
        raise RuntimeError(
            "No exact pressings are available for acceptance."
        )

    expected_profiles = {
        int(
            pressing[
                "pressing_id"
            ]
        ):
            load_media_profile(
                engine,
                int(
                    pressing[
                        "pressing_id"
                    ]
                ),
            )
        for pressing in pressings
    }

    console_errors: list[
        str
    ] = []

    page_errors: list[
        str
    ] = []

    results: list[
        dict[str, Any]
    ] = []

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

        page_url = open_reference_page(
            page,
            args.url,
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

        for pressing in pressings:
            pressing_id = int(
                pressing[
                    "pressing_id"
                ]
            )

            profile = expected_profiles[
                pressing_id
            ]

            selected_option = choose_pressing(
                page,
                pressing_id,
                args.timeout_ms,
            )

            contract_text = (
                "PROFILE_CONTRACT "
                f"pressing_id={pressing_id} "
                f"media_type={pressing['media_type']} "
                "applicable_components="
                f"{profile['applicable_component_count']}"
            )

            page.get_by_text(
                contract_text,
                exact=True,
            ).wait_for(
                state="visible",
                timeout=args.timeout_ms,
            )

            preview_button = page.get_by_role(
                "button",
                name="Preview reviewed changes",
            ).first

            preview_button.wait_for(
                state="visible",
                timeout=args.timeout_ms,
            )

            screenshot = (
                args.output_dir
                / f"pressing-{pressing_id}.png"
            )

            page.screenshot(
                path=str(
                    screenshot
                ),
                full_page=True,
            )

            results.append(
                {
                    "pressing_id":
                        pressing_id,
                    "catalog_number":
                        pressing.get(
                            "catalog_number"
                        ),
                    "media_type":
                        pressing[
                            "media_type"
                        ],
                    "expected_component_count":
                        profile[
                            "applicable_component_count"
                        ],
                    "selected_option":
                        selected_option,
                    "profile_contract_visible":
                        True,
                    "preview_visible":
                        True,
                    "screenshot":
                        str(
                            screenshot
                        ),
                }
            )

        browser.close()

    success = (
        len(
            results
        )
        == len(
            pressings
        )
        and not console_errors
        and not page_errors
    )

    report = {
        "url":
            args.url,
        "page_url":
            page_url,
        "expected_pressing_count":
            len(
                pressings
            ),
        "successful_pressing_count":
            len(
                results
            ),
        "pressings":
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
            success,
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
        if success
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
