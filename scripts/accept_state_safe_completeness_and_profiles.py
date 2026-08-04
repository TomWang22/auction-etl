#!/usr/bin/env python3
"""Read-only acceptance for state-safe completeness workflows."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, Response, sync_playwright


OPTIONAL_RESOURCE_NAMES = frozenset(
    {
        "favicon.ico",
        "favicon.png",
        "apple-touch-icon.png",
        "apple-touch-icon-precomposed.png",
        "site.webmanifest",
        "manifest.json",
        "robots.txt",
    }
)


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


def _rendered_text(page: Page) -> str:
    """Return visible Streamlit application text."""
    container = page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first

    if container.count() == 0:
        return ""

    try:
        if not container.is_visible():
            return ""

        return (
            container.inner_text()
            or ""
        ).strip()
    except Exception:
        return ""


def _wait_for_root(page: Page, timeout_ms: int) -> None:
    """Wait for the root Streamlit application to hydrate."""
    container = page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first

    container.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    while time.monotonic() < deadline:
        if _rendered_text(page):
            return

        page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        "The Streamlit application root did not hydrate."
    )


def _wait_for_title(
    page: Page,
    expected_title: str,
    timeout_ms: int,
) -> None:
    """Wait for one page title in rendered application text."""
    deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    expected = expected_title.casefold()
    latest_text = ""

    while time.monotonic() < deadline:
        latest_text = _rendered_text(
            page
        )

        if expected in latest_text.casefold():
            return

        page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        f"{expected_title} did not render.\n"
        "Rendered application excerpt:\n"
        + latest_text[
            :4_000
        ]
    )


def _expand_sidebar(page: Page) -> None:
    """Expand the Streamlit sidebar when it is collapsed."""
    sidebar = page.locator(
        '[data-testid="stSidebar"]'
    ).first

    try:
        if (
            sidebar.count() > 0
            and sidebar.is_visible()
        ):
            return
    except Exception:
        pass

    controls = (
        page.locator(
            '[data-testid="stSidebarCollapsedControl"]'
        ).first,
        page.get_by_role(
            "button",
            name=re.compile(
                r"open sidebar|expand sidebar",
                re.IGNORECASE,
            ),
        ).first,
    )

    for control in controls:
        try:
            if (
                control.count() > 0
                and control.is_visible()
            ):
                control.click(
                    force=True
                )

                page.wait_for_timeout(
                    400
                )

                return
        except Exception:
            continue


def _anchor_diagnostics(
    anchors: Locator,
) -> list[dict[str, str]]:
    """Return actionable navigation-link diagnostics."""
    diagnostics: list[
        dict[str, str]
    ] = []

    for index in range(
        anchors.count()
    ):
        anchor = anchors.nth(
            index
        )

        try:
            diagnostics.append(
                {
                    "text":
                        (
                            anchor.inner_text()
                            or ""
                        ).strip(),
                    "aria_label":
                        (
                            anchor.get_attribute(
                                "aria-label"
                            )
                            or ""
                        ).strip(),
                    "href":
                        (
                            anchor.get_attribute(
                                "href"
                            )
                            or ""
                        ).strip(),
                    "visible":
                        str(
                            anchor.is_visible()
                        ),
                }
            )
        except Exception:
            continue

    return diagnostics


def _find_sidebar_link(
    page: Page,
    *,
    expected_title: str,
    route_tokens: tuple[str, ...],
) -> Locator:
    """Find the rendered Streamlit sidebar link for one page."""
    _expand_sidebar(
        page
    )

    role_link = page.get_by_role(
        "link",
        name=re.compile(
            re.escape(
                expected_title
            ),
            re.IGNORECASE,
        ),
    ).first

    try:
        if (
            role_link.count() > 0
            and role_link.is_visible()
        ):
            return role_link
    except Exception:
        pass

    sidebar = page.locator(
        '[data-testid="stSidebar"]'
    ).first

    anchors = (
        sidebar.locator(
            "a[href]"
        )
        if (
            sidebar.count() > 0
        )
        else page.locator(
            "a[href]"
        )
    )

    expected_words = {
        word
        for word in re.findall(
            r"[a-z0-9]+",
            expected_title.casefold(),
        )
        if len(
            word
        ) > 2
    }

    best_locator: Locator | None = None
    best_score = 0

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
            ).strip()

            text_value = (
                anchor.inner_text()
                or ""
            ).strip()

            aria_label = (
                anchor.get_attribute(
                    "aria-label"
                )
                or ""
            ).strip()

            visible = anchor.is_visible()
        except Exception:
            continue

        if not href or not visible:
            continue

        combined = (
            text_value
            + " "
            + aria_label
        ).casefold()

        href_folded = href.casefold()

        score = 0

        if (
            expected_title.casefold()
            in combined
        ):
            score += 100

        if (
            expected_words
            and expected_words.issubset(
                set(
                    re.findall(
                        r"[a-z0-9]+",
                        combined,
                    )
                )
            )
        ):
            score += 70

        for token in route_tokens:
            normalized_token = (
                token.casefold()
                .replace(
                    "-",
                    "_",
                )
            )

            normalized_href = (
                href_folded.replace(
                    "-",
                    "_",
                )
            )

            if (
                normalized_token
                in normalized_href
            ):
                score += 80

        if score > best_score:
            best_score = score
            best_locator = anchor

    if (
        best_locator is None
        or best_score <= 0
    ):
        raise RuntimeError(
            f"Sidebar link was not found: {expected_title}\n"
            "Rendered anchors:\n"
            + json.dumps(
                _anchor_diagnostics(
                    page.locator(
                        "a[href]"
                    )
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

    return best_locator


def open_sidebar_page(
    page: Page,
    *,
    expected_title: str,
    route_tokens: tuple[str, ...],
    timeout_ms: int,
) -> str:
    """Open one page through Streamlit's rendered SPA navigation."""
    link = _find_sidebar_link(
        page,
        expected_title=
            expected_title,
        route_tokens=
            route_tokens,
    )

    link.scroll_into_view_if_needed()

    link.click(
        force=True
    )

    page.wait_for_timeout(
        500
    )

    _wait_for_title(
        page,
        expected_title,
        timeout_ms,
    )

    return page.url


def _http_event(response: Response) -> dict[str, Any]:
    """Return structured HTTP failure information."""
    request = response.request

    return {
        "status":
            int(
                response.status
            ),
        "url":
            response.url,
        "method":
            request.method,
        "resource_type":
            request.resource_type,
    }


def _is_optional_http_error(
    event: dict[str, Any],
) -> bool:
    """Allow only known optional static-resource 404s."""
    if int(
        event.get(
            "status",
            0,
        )
    ) != 404:
        return False

    path = urlsplit(
        str(
            event.get(
                "url",
                "",
            )
        )
    ).path.casefold()

    resource_name = Path(
        path
    ).name.casefold()

    if "/_stcore/" in path:
        return False

    if resource_name in OPTIONAL_RESOURCE_NAMES:
        return True

    if resource_name.startswith(
        "favicon."
    ):
        return True

    if resource_name.startswith(
        "apple-touch-icon"
    ):
        return True

    return path.endswith(
        ".map"
    )


def _is_generic_resource_console_error(
    text_value: str,
) -> bool:
    """Return whether a console error lacks resource identity."""
    normalized = " ".join(
        str(
            text_value
        ).casefold().split()
    )

    return (
        "failed to load resource"
        in normalized
        and (
            "404"
            in normalized
            or "not found"
            in normalized
        )
    )


def _classify_console_errors(
    console_errors: list[dict[str, str]],
    *,
    blocking_http_errors: list[dict[str, Any]],
    non_blocking_http_errors: list[dict[str, Any]],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Correlate generic console errors with optional HTTP failures."""
    blocking: list[
        dict[str, str]
    ] = []

    non_blocking: list[
        dict[str, str]
    ] = []

    optional_only = (
        bool(
            non_blocking_http_errors
        )
        and not blocking_http_errors
    )

    for event in console_errors:
        if (
            optional_only
            and _is_generic_resource_console_error(
                event[
                    "text"
                ]
            )
        ):
            non_blocking.append(
                event
            )
        else:
            blocking.append(
                event
            )

    return (
        blocking,
        non_blocking,
    )


def main() -> int:
    """Run complete read-only browser acceptance."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_errors: list[
        dict[str, str]
    ] = []

    page_errors: list[str] = []

    http_errors: list[
        dict[str, Any]
    ] = []

    page_results: list[
        dict[str, Any]
    ] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width":
                    1_600,
                "height":
                    1_100,
            }
        )

        page = context.new_page()

        page.goto(
            args.url,
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )

        _wait_for_root(
            page,
            args.timeout_ms,
        )

        page.on(
            "console",
            lambda message: (
                console_errors.append(
                    {
                        "type":
                            message.type,
                        "text":
                            message.text,
                    }
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
                    _http_event(
                        response
                    )
                )
                if response.status >= 400
                else None
            ),
        )

        listing_url = open_sidebar_page(
            page,
            expected_title=
                "Listing Completeness Review",
            route_tokens=(
                "Listing_Completeness_Review",
                "10_Listing_Completeness_Review",
            ),
            timeout_ms=
                args.timeout_ms,
        )

        listing_selector = page.get_by_role(
            "combobox",
            name="Assigned auction listing",
        ).first

        listing_selector.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        listing_screenshot = (
            args.output_dir
            / "listing-completeness.png"
        )

        page.screenshot(
            path=str(
                listing_screenshot
            ),
            full_page=True,
        )

        page_results.append(
            {
                "page":
                    "Listing Completeness Review",
                "url":
                    listing_url,
                "navigation":
                    "Streamlit sidebar SPA link",
                "selector_visible":
                    True,
                "screenshot":
                    str(
                        listing_screenshot
                    ),
            }
        )

        profile_url = open_sidebar_page(
            page,
            expected_title=
                "Media Profile Administration",
            route_tokens=(
                "Media_Profile_Admin",
                "11_Media_Profile_Admin",
            ),
            timeout_ms=
                args.timeout_ms,
        )

        preview_button = page.get_by_role(
            "button",
            name="Preview media-profile changes",
        ).first

        preview_button.wait_for(
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

        page_results.append(
            {
                "page":
                    "Media Profile Administration",
                "url":
                    profile_url,
                "navigation":
                    "Streamlit sidebar SPA link",
                "preview_visible":
                    True,
                "screenshot":
                    str(
                        profile_screenshot
                    ),
            }
        )

        page.wait_for_timeout(
            750
        )

        browser.close()

    blocking_http_errors = [
        event
        for event in http_errors
        if not _is_optional_http_error(
            event
        )
    ]

    non_blocking_http_errors = [
        event
        for event in http_errors
        if _is_optional_http_error(
            event
        )
    ]

    (
        blocking_console_errors,
        non_blocking_console_errors,
    ) = _classify_console_errors(
        console_errors,
        blocking_http_errors=
            blocking_http_errors,
        non_blocking_http_errors=
            non_blocking_http_errors,
    )

    report = {
        "root_url":
            args.url,
        "navigation_mode":
            "root-first Streamlit sidebar SPA navigation",
        "pages":
            page_results,
        "console_errors":
            console_errors,
        "http_errors":
            http_errors,
        "blocking_console_errors":
            blocking_console_errors,
        "non_blocking_console_errors":
            non_blocking_console_errors,
        "blocking_http_errors":
            blocking_http_errors,
        "non_blocking_http_errors":
            non_blocking_http_errors,
        "page_errors":
            page_errors,
        "persistence_controls_clicked":
            0,
        "database_writes":
            0,
        "success":
            (
                len(
                    page_results
                )
                == 2
                and not blocking_console_errors
                and not blocking_http_errors
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
