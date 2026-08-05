#!/usr/bin/env python3
"""Read-only browser acceptance for New Auction Intake."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    """Parse browser-acceptance arguments."""
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
        default=30000,
    )

    return parser.parse_args()


def _wait_for_root(
    page: Page,
    url: str,
    timeout_ms: int,
) -> None:
    """Open the Streamlit root and wait for hydration."""
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )

    page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first.wait_for(
        state="visible",
        timeout=timeout_ms,
    )


def _open_sidebar_page(
    page: Page,
    *,
    base_url: str,
    page_name: str,
    timeout_ms: int,
) -> str:
    """Open one rendered Streamlit sidebar route."""
    _wait_for_root(
        page,
        base_url,
        timeout_ms,
    )

    collapsed = page.locator(
        '[data-testid="stSidebarCollapsedControl"]'
    )

    if (
        collapsed.count() > 0
        and collapsed.first.is_visible()
    ):
        collapsed.first.click()

    anchors = page.locator(
        "a[href]"
    )

    candidates: list[
        tuple[Any, str]
    ] = []

    pattern = re.compile(
        page_name,
        re.IGNORECASE,
    )

    for index in range(
        anchors.count()
    ):
        anchor = anchors.nth(
            index
        )

        try:
            text_value = (
                anchor.inner_text()
                or ""
            ).strip()

            aria_label = (
                anchor.get_attribute(
                    "aria-label"
                )
                or ""
            )

            href = (
                anchor.get_attribute(
                    "href"
                )
                or ""
            )

            if pattern.search(
                " ".join(
                    (
                        text_value,
                        aria_label,
                        href,
                    )
                )
            ):
                candidates.append(
                    (
                        anchor,
                        href,
                    )
                )
        except Exception:
            continue

    if len(
        candidates
    ) != 1:
        raise RuntimeError(
            "New Auction Intake sidebar link was not uniquely found."
        )

    anchor, href = candidates[0]

    anchor.scroll_into_view_if_needed()
    anchor.click()

    page.get_by_role(
        "heading",
        name=re.compile(
            r"New Auction Intake",
            re.IGNORECASE,
        ),
    ).first.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    return urljoin(
        base_url,
        href,
    )


def main() -> int:
    """Run read-only UI acceptance."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[dict[str, Any]] = []

    screenshot_path = (
        args.output_dir
        / "new-auction-intake.png"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width":
                    1600,
                "height":
                    1200,
            }
        )

        page = context.new_page()

        page_url = _open_sidebar_page(
            page,
            base_url=args.url,
            page_name="New Auction Intake",
            timeout_ms=args.timeout_ms,
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
                        "method":
                            response.request.method,
                        "resource_type":
                            response.request.resource_type,
                    }
                )
                if response.status >= 400
                else None
            ),
        )

        queue_metric = page.get_by_text(
            re.compile(
                r"Unassigned auctions",
                re.IGNORECASE,
            )
        ).first

        queue_metric.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        queue_selector = page.get_by_role(
            "combobox",
            name=re.compile(
                r"Auction waiting for assignment",
                re.IGNORECASE,
            ),
        ).first

        queue_selector.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        alerts_tab = page.get_by_role(
            "tab",
            name=re.compile(
                r"Completeness Alerts",
                re.IGNORECASE,
            ),
        ).first

        cohorts_tab = page.get_by_role(
            "tab",
            name=re.compile(
                r"Cohort Reporting",
                re.IGNORECASE,
            ),
        ).first

        audit_tab = page.get_by_role(
            "tab",
            name=re.compile(
                r"Assignment Audit",
                re.IGNORECASE,
            ),
        ).first

        for tab in (
            alerts_tab,
            cohorts_tab,
            audit_tab,
        ):
            tab.wait_for(
                state="visible",
                timeout=args.timeout_ms,
            )

        alerts_tab.click()

        page.get_by_text(
            re.compile(
                r"Current alerts",
                re.IGNORECASE,
            )
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        cohorts_tab.click()

        page.get_by_text(
            re.compile(
                r"latest immutable snapshot",
                re.IGNORECASE,
            )
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        audit_tab.click()

        page.get_by_text(
            re.compile(
                r"Assignment audit history is immutable",
                re.IGNORECASE,
            )
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        page.screenshot(
            path=str(
                screenshot_path
            ),
            full_page=True,
        )

        browser.close()

    report = {
        "root_url":
            args.url,
        "page_url":
            page_url,
        "queue_metric_visible":
            True,
        "queue_selector_visible":
            True,
        "alerts_visible":
            True,
        "cohort_summary_visible":
            True,
        "assignment_audit_visible":
            True,
        "persistence_controls_clicked":
            0,
        "console_errors":
            console_errors,
        "page_errors":
            page_errors,
        "http_errors":
            http_errors,
        "screenshot":
            str(
                screenshot_path
            ),
        "database_writes":
            0,
    }

    report[
        "success"
    ] = (
        not console_errors
        and not page_errors
        and not http_errors
    )

    (
        args.output_dir
        / "report.json"
    ).write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
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
