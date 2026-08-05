#!/usr/bin/env python3
"""Read-only browser acceptance for completeness history."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
import re
import time
from typing import Any


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


def _navigator_module():
    """Load the proven root-first Streamlit navigator."""
    path = Path(
        "scripts/accept_state_safe_completeness_and_profiles.py"
    ).resolve()

    specification = importlib.util.spec_from_file_location(
        "state_safe_completeness_navigator",
        path,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            "The proven Streamlit navigator could not be loaded."
        )

    module = importlib.util.module_from_spec(
        specification
    )

    sys.modules[
        specification.name
    ] = module

    specification.loader.exec_module(
        module
    )

    return module


def _assigned_listing_selector(
    page: Any,
    timeout_ms: int,
    output_dir: Path,
) -> Any:
    """Return the visible Streamlit assignment selector."""
    label_pattern = re.compile(
        r"Assigned\s+auction\s+listing",
        re.IGNORECASE,
    )

    deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    while time.monotonic() < deadline:
        preferred_candidates = (
            page.get_by_role(
                "combobox",
                name=label_pattern,
            ),
            page.locator(
                '[data-testid="stSelectbox"]'
            ).filter(
                has_text=label_pattern
            ).locator(
                '[role="combobox"]'
            ),
            page.locator(
                '[data-testid="stSelectbox"]'
            ).filter(
                has_text=label_pattern
            ).locator(
                'input[aria-autocomplete="list"]'
            ),
            page.locator(
                '[data-baseweb="select"]'
            ).filter(
                has_text=label_pattern
            ).locator(
                '[role="combobox"]'
            ),
        )

        for candidates in preferred_candidates:
            for index in range(
                candidates.count()
            ):
                candidate = candidates.nth(
                    index
                )

                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue

        all_candidates = page.locator(
            (
                '[role="combobox"], '
                'input[aria-autocomplete="list"]'
            )
        )

        for index in range(
            all_candidates.count()
        ):
            candidate = all_candidates.nth(
                index
            )

            try:
                if not candidate.is_visible():
                    continue

                aria_label = (
                    candidate.get_attribute(
                        "aria-label"
                    )
                    or ""
                )

                labelled_by = (
                    candidate.get_attribute(
                        "aria-labelledby"
                    )
                    or ""
                )

                value = (
                    candidate.get_attribute(
                        "value"
                    )
                    or ""
                )

                container = candidate.locator(
                    (
                        "xpath=ancestor::*"
                        "[@data-testid='stSelectbox'][1]"
                    )
                )

                container_text = ""

                if container.count() > 0:
                    container_text = (
                        container.inner_text()
                        or ""
                    ).strip()

                semantic_text = " ".join(
                    (
                        aria_label,
                        labelled_by,
                        value,
                        container_text,
                    )
                )

                if label_pattern.search(
                    semantic_text
                ):
                    return candidate
            except Exception:
                continue

        page.wait_for_timeout(
            250
        )

    combobox_diagnostics = []

    all_candidates = page.locator(
        (
            '[role="combobox"], '
            'input[aria-autocomplete="list"]'
        )
    )

    for index in range(
        all_candidates.count()
    ):
        candidate = all_candidates.nth(
            index
        )

        try:
            container = candidate.locator(
                (
                    "xpath=ancestor::*"
                    "[@data-testid='stSelectbox'][1]"
                )
            )

            container_text = ""

            if container.count() > 0:
                container_text = (
                    container.inner_text()
                    or ""
                ).strip()

            combobox_diagnostics.append(
                {
                    "index":
                        index,
                    "visible":
                        candidate.is_visible(),
                    "aria_label":
                        candidate.get_attribute(
                            "aria-label"
                        )
                        or "",
                    "aria_labelledby":
                        candidate.get_attribute(
                            "aria-labelledby"
                        )
                        or "",
                    "value":
                        candidate.get_attribute(
                            "value"
                        )
                        or "",
                    "container_text":
                        container_text,
                }
            )
        except Exception as error:
            combobox_diagnostics.append(
                {
                    "index":
                        index,
                    "error":
                        str(
                            error
                        ),
                }
            )

    heading_texts = []

    headings = page.locator(
        "h1, h2, h3"
    )

    for index in range(
        headings.count()
    ):
        heading = headings.nth(
            index
        )

        try:
            if heading.is_visible():
                text_value = (
                    heading.inner_text()
                    or ""
                ).strip()

                if text_value:
                    heading_texts.append(
                        text_value
                    )
        except Exception:
            continue

    application_excerpt = ""

    application = page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first

    try:
        if (
            application.count() > 0
            and application.is_visible()
        ):
            application_excerpt = (
                application.inner_text()
                or ""
            ).strip()[
                :6000
            ]
    except Exception:
        application_excerpt = ""

    diagnostic_screenshot = (
        output_dir
        / "assigned-listing-selector-timeout.png"
    )

    try:
        page.screenshot(
            path=str(
                diagnostic_screenshot
            ),
            full_page=True,
        )
    except Exception:
        pass

    raise RuntimeError(
        "Assigned auction listing selector was not rendered.\n"
        f"Current URL: {page.url}\n"
        "Visible headings:\n"
        + json.dumps(
            heading_texts,
            ensure_ascii=False,
            indent=2,
        )
        + "\nVisible comboboxes:\n"
        + json.dumps(
            combobox_diagnostics,
            ensure_ascii=False,
            indent=2,
        )
        + "\nRendered application excerpt:\n"
        + application_excerpt
        + "\nDiagnostic screenshot:\n"
        + str(
            diagnostic_screenshot
        )
    )


def main() -> int:
    """Run the read-only browser acceptance."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    module = _navigator_module()

    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[dict[str, object]] = []

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

        page.goto(
            args.url,
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )

        module._wait_for_root(
            page,
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

        page.on(
            "response",
            lambda response: (
                http_errors.append(
                    {
                        "status":
                            response.status,
                        "url":
                            response.url,
                        "resource_type":
                            response.request.resource_type,
                    }
                )
                if response.status >= 400
                else None
            ),
        )

        page_url = module.open_sidebar_page(
            page,
            expected_title=
                "Completeness Snapshot History",
            route_tokens=(
                "Completeness_History",
                "12_Completeness_History",
            ),
            timeout_ms=
                args.timeout_ms,
        )

        history_heading = page.get_by_role(
            "heading",
            name=re.compile(
                r"Completeness\s+Snapshot\s+History",
                re.IGNORECASE,
            ),
        ).first

        history_heading.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        selector = _assigned_listing_selector(
            page,
            args.timeout_ms,
            args.output_dir,
        )

        timeline_heading = page.get_by_role(
            "heading",
            name="Chronological change timeline",
        ).first

        timeline_heading.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        ledger_heading = page.get_by_role(
            "heading",
            name="Immutable snapshot ledger",
        ).first

        ledger_heading.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        screenshot = (
            args.output_dir
            / "completeness-history.png"
        )

        page.screenshot(
            path=str(
                screenshot
            ),
            full_page=True,
        )

        browser.close()

    report = {
        "root_url":
            args.url,
        "page_url":
            page_url,
        "selector_visible":
            True,
        "timeline_visible":
            True,
        "snapshot_ledger_visible":
            True,
        "screenshot":
            str(
                screenshot
            ),
        "console_errors":
            console_errors,
        "page_errors":
            page_errors,
        "http_errors":
            http_errors,
        "persistence_controls_clicked":
            0,
        "database_writes":
            0,
        "success":
            (
                not console_errors
                and not page_errors
                and not http_errors
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
