#!/usr/bin/env python3
"""Read-only browser acceptance for all eleven wizard stages."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


STAGES: tuple[tuple[int, str], ...] = (
    (1, "1. Exact pressing identity"),
    (2, "2. Assigned listings"),
    (3, "3. Evidence and attachments"),
    (4, "4. Shared completeness reference"),
    (5, "5. Listing component observations"),
    (6, "6. Condition normalization"),
    (7, "7. Analysis and market factors"),
    (8, "8. Exact-pressing comparable review"),
    (9, "9. Normalization readiness"),
    (10, "10. Eleven deterministic verdicts"),
    (11, "11. Audit and final report"),
)

WRITE_CONTROL_PATTERN = re.compile(
    r"Save|Apply|Register|Delete|Restore",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify all eleven Cohort Curation Wizard stages "
            "without clicking persistence controls."
        )
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8501",
        help="Collector Review base URL.",
    )

    parser.add_argument(
        "--catalog",
        default="MR2276",
        help="Catalog text expected in the selected cohort.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for screenshots and report.json.",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60_000,
        help="Default Playwright timeout.",
    )

    return parser.parse_args()


def wait_for_streamlit(
    page: Page,
    timeout_ms: int,
) -> None:
    """Wait for Streamlit hydration and a visible app container."""
    page.locator(
        '[data-testid="stAppViewContainer"]'
    ).wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    page.wait_for_function(
        """
        () => {
            const container = document.querySelector(
                '[data-testid="stAppViewContainer"]'
            );

            if (!container) {
                return false;
            }

            const text = container.innerText || '';

            return text.trim().length > 0;
        }
        """,
        timeout=timeout_ms,
    )


def open_wizard(
    page: Page,
    base_url: str,
    timeout_ms: int,
) -> None:
    """Open the wizard through its route or discovered navigation link."""
    normalized_base = base_url.rstrip("/")

    heading_pattern = re.compile(
        r"Cohort\s+Curation\s+Wizard",
        re.IGNORECASE,
    )

    def wizard_heading() -> Locator:
        return page.get_by_role(
            "heading",
            name=heading_pattern,
        ).first

    def wizard_is_visible(
        timeout: int = 5_000,
    ) -> bool:
        heading = wizard_heading()

        try:
            heading.wait_for(
                state="visible",
                timeout=timeout,
            )
        except PlaywrightTimeoutError:
            return False

        return True

    def absolute_url(
        href: str,
    ) -> str:
        normalized_href = href.strip()

        if normalized_href.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return normalized_href

        if normalized_href.startswith("/"):
            return (
                normalized_base
                + normalized_href
            )

        return (
            normalized_base
            + "/"
            + normalized_href.lstrip("./")
        )

    route_candidates = (
        normalized_base
        + "/Cohort_Curation_Wizard",
        normalized_base
        + "/8_Cohort_Curation_Wizard",
        normalized_base
        + "/Cohort_Curation_Wizard/",
        normalized_base
        + "/8_Cohort_Curation_Wizard/",
        normalized_base
        + "/Cohort%20Curation%20Wizard",
    )

    attempted_routes: list[str] = []

    for route in route_candidates:
        attempted_routes.append(
            route
        )

        page.goto(
            route,
            wait_until="domcontentloaded",
        )

        try:
            wait_for_streamlit(
                page,
                timeout_ms,
            )
        except PlaywrightTimeoutError:
            continue

        if wizard_is_visible():
            return

    page.goto(
        normalized_base,
        wait_until="domcontentloaded",
    )

    wait_for_streamlit(
        page,
        timeout_ms,
    )

    ensure_sidebar_visible(
        page,
        timeout_ms,
    )

    navigation_links = page.locator(
        '[data-testid="stSidebarNav"] a[href], '
        '[data-testid="stSidebar"] a[href], '
        'a[href]'
    )

    discovered_links: list[
        dict[str, str]
    ] = []

    matching_urls: list[str] = []

    for index in range(
        navigation_links.count()
    ):
        link = navigation_links.nth(
            index
        )

        try:
            text_value = (
                link.inner_text()
                or ""
            ).strip()

            href_value = (
                link.get_attribute(
                    "href"
                )
                or ""
            ).strip()

            aria_label = (
                link.get_attribute(
                    "aria-label"
                )
                or ""
            ).strip()
        except Exception:
            continue

        if not href_value:
            continue

        discovered_links.append(
            {
                "text":
                    text_value,
                "aria_label":
                    aria_label,
                "href":
                    href_value,
            }
        )

        combined = (
            text_value
            + " "
            + aria_label
            + " "
            + href_value
        ).casefold()

        normalized_combined = re.sub(
            r"[^a-z0-9]+",
            " ",
            combined,
        )

        required_tokens = (
            "cohort",
            "curation",
            "wizard",
        )

        if all(
            token in normalized_combined
            for token in required_tokens
        ):
            matching_urls.append(
                absolute_url(
                    href_value
                )
            )

    for route in dict.fromkeys(
        matching_urls
    ):
        attempted_routes.append(
            route
        )

        page.goto(
            route,
            wait_until="domcontentloaded",
        )

        try:
            wait_for_streamlit(
                page,
                timeout_ms,
            )
        except PlaywrightTimeoutError:
            continue

        if wizard_is_visible(
            timeout=15_000
        ):
            return

    accessible_links = (
        page.get_by_role(
            "link",
            name=heading_pattern,
        )
    )

    for index in range(
        accessible_links.count()
    ):
        link = accessible_links.nth(
            index
        )

        try:
            if not link.is_visible():
                continue

            link.click(
                force=True
            )

            wait_for_streamlit(
                page,
                timeout_ms,
            )
        except Exception:
            continue

        if wizard_is_visible(
            timeout=15_000
        ):
            return

    accessible_buttons = (
        page.get_by_role(
            "button",
            name=heading_pattern,
        )
    )

    for index in range(
        accessible_buttons.count()
    ):
        button = accessible_buttons.nth(
            index
        )

        try:
            if not button.is_visible():
                continue

            button.click(
                force=True
            )

            wait_for_streamlit(
                page,
                timeout_ms,
            )
        except Exception:
            continue

        if wizard_is_visible(
            timeout=15_000
        ):
            return

    exception_texts: list[str] = []

    exceptions = page.locator(
        '[data-testid="stException"]'
    )

    for index in range(
        exceptions.count()
    ):
        exception = exceptions.nth(
            index
        )

        try:
            text_value = (
                exception.inner_text()
                or ""
            ).strip()
        except Exception:
            continue

        if text_value:
            exception_texts.append(
                text_value
            )

    try:
        page.screenshot(
            path=(
                "/tmp/"
                "cohort-wizard-navigation-failure.png"
            ),
            full_page=True,
        )
    except Exception:
        pass

    rendered_text = _visible_app_text(
        page
    )

    raise RuntimeError(
        "Cohort Curation Wizard could not be opened.\n"
        "Current URL:\n"
        f"{page.url}\n\n"
        "Attempted routes:\n"
        + json.dumps(
            attempted_routes,
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nDiscovered navigation links:\n"
        + json.dumps(
            discovered_links,
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nVisible headings:\n"
        + json.dumps(
            _visible_heading_texts(
                page
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nStreamlit exceptions:\n"
        + json.dumps(
            exception_texts,
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nRendered application excerpt:\n"
        + rendered_text[:5000]
        + "\n\nFailure screenshot:\n"
        "/tmp/cohort-wizard-navigation-failure.png"
    )



def _first_visible(
    locator: Locator,
) -> Locator | None:
    """Return the first currently visible locator match."""
    for index in range(
        locator.count()
    ):
        candidate = locator.nth(
            index
        )

        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue

    return None


def ensure_sidebar_visible(
    page: Page,
    timeout_ms: int,
) -> None:
    """Expand the Streamlit sidebar when it is collapsed."""
    sidebar = page.locator(
        '[data-testid="stSidebar"]'
    ).first

    if sidebar.count() == 0:
        return

    if sidebar.is_visible():
        return

    controls = (
        page.locator(
            '[data-testid="stSidebarCollapsedControl"] button'
        ),
        page.locator(
            '[data-testid="stSidebarCollapsedControl"]'
        ),
        page.locator(
            '[data-testid="collapsedControl"] button'
        ),
        page.get_by_role(
            "button",
            name=re.compile(
                r"(open|expand|show).*sidebar",
                re.IGNORECASE,
            ),
        ),
    )

    for controls_locator in controls:
        control = _first_visible(
            controls_locator
        )

        if control is None:
            continue

        try:
            control.click(
                force=True
            )

            sidebar.wait_for(
                state="visible",
                timeout=timeout_ms,
            )

            return
        except Exception:
            continue


def _selectbox_diagnostics(
    page: Page,
) -> list[dict[str, str]]:
    """Describe visible comboboxes for actionable failures."""
    diagnostics: list[
        dict[str, str]
    ] = []

    comboboxes = page.get_by_role(
        "combobox"
    )

    for index in range(
        comboboxes.count()
    ):
        combobox = comboboxes.nth(
            index
        )

        try:
            visible = combobox.is_visible()
        except Exception:
            visible = False

        if not visible:
            continue

        container = combobox.locator(
            "xpath=ancestor::*"
            "[@data-testid='stSelectbox'][1]"
        )

        container_text = ""

        if container.count() > 0:
            try:
                container_text = (
                    container.first.inner_text()
                    or ""
                ).strip()
            except Exception:
                container_text = ""

        diagnostics.append(
            {
                "index":
                    str(index),
                "aria_label":
                    (
                        combobox.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ),
                "aria_labelledby":
                    (
                        combobox.get_attribute(
                            "aria-labelledby"
                        )
                        or ""
                    ),
                "value":
                    (
                        combobox.get_attribute(
                            "value"
                        )
                        or ""
                    ),
                "container_text":
                    container_text,
            }
        )

    return diagnostics


def _first_visible(
    locator: Locator,
) -> Locator | None:
    """Return the first currently visible locator match."""
    for index in range(
        locator.count()
    ):
        candidate = locator.nth(
            index
        )

        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue

    return None


def ensure_sidebar_visible(
    page: Page,
    timeout_ms: int,
) -> None:
    """Expand the Streamlit sidebar when it is collapsed."""
    sidebar = page.locator(
        '[data-testid="stSidebar"]'
    ).first

    if sidebar.count() == 0:
        return

    if sidebar.is_visible():
        return

    controls = (
        page.locator(
            '[data-testid="stSidebarCollapsedControl"] button'
        ),
        page.locator(
            '[data-testid="stSidebarCollapsedControl"]'
        ),
        page.locator(
            '[data-testid="collapsedControl"] button'
        ),
        page.get_by_role(
            "button",
            name=re.compile(
                r"(open|expand|show).*sidebar",
                re.IGNORECASE,
            ),
        ),
    )

    for controls_locator in controls:
        control = _first_visible(
            controls_locator
        )

        if control is None:
            continue

        try:
            control.click(
                force=True
            )

            sidebar.wait_for(
                state="visible",
                timeout=timeout_ms,
            )

            return
        except Exception:
            continue


def _selectbox_diagnostics(
    page: Page,
) -> list[dict[str, str]]:
    """Describe visible comboboxes for actionable failures."""
    diagnostics: list[
        dict[str, str]
    ] = []

    comboboxes = page.get_by_role(
        "combobox"
    )

    for index in range(
        comboboxes.count()
    ):
        combobox = comboboxes.nth(
            index
        )

        try:
            visible = combobox.is_visible()
        except Exception:
            visible = False

        if not visible:
            continue

        container = combobox.locator(
            "xpath=ancestor::*"
            "[@data-testid='stSelectbox'][1]"
        )

        container_text = ""

        if container.count() > 0:
            try:
                container_text = (
                    container.first.inner_text()
                    or ""
                ).strip()
            except Exception:
                container_text = ""

        diagnostics.append(
            {
                "index":
                    str(index),
                "aria_label":
                    (
                        combobox.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ),
                "aria_labelledby":
                    (
                        combobox.get_attribute(
                            "aria-labelledby"
                        )
                        or ""
                    ),
                "value":
                    (
                        combobox.get_attribute(
                            "value"
                        )
                        or ""
                    ),
                "container_text":
                    container_text,
            }
        )

    return diagnostics


def selectbox_container(
    page: Page,
    label: str,
    timeout_ms: int = 60_000,
) -> Locator:
    """Find a Streamlit selectbox across supported DOM layouts."""
    ensure_sidebar_visible(
        page,
        timeout_ms,
    )

    accessible = page.get_by_role(
        "combobox",
        name=re.compile(
            rf"^{re.escape(label)}$",
            re.IGNORECASE,
        ),
    )

    combobox = _first_visible(
        accessible
    )

    if combobox is not None:
        container = combobox.locator(
            "xpath=ancestor::*"
            "[@data-testid='stSelectbox'][1]"
        )

        if container.count() > 0:
            return container.first

        return combobox.locator(
            "xpath=.."
        )

    label_nodes = page.get_by_text(
        label,
        exact=True,
    )

    for index in range(
        label_nodes.count()
    ):
        label_node = label_nodes.nth(
            index
        )

        try:
            if not label_node.is_visible():
                continue
        except Exception:
            continue

        container = label_node.locator(
            "xpath=ancestor::*"
            "[@data-testid='stSelectbox'][1]"
        )

        if (
            container.count() > 0
            and _first_visible(
                container.locator(
                    '[role="combobox"]'
                )
            )
            is not None
        ):
            return container.first

    containers = page.locator(
        '[data-testid="stSelectbox"]'
    )

    for index in range(
        containers.count()
    ):
        container = containers.nth(
            index
        )

        try:
            if not container.is_visible():
                continue

            container_text = (
                container.inner_text()
                or ""
            )
        except Exception:
            continue

        if (
            label.casefold()
            in container_text.casefold()
        ):
            return container

    visible_comboboxes = [
        page.get_by_role(
            "combobox"
        ).nth(index)
        for index in range(
            page.get_by_role(
                "combobox"
            ).count()
        )
        if page.get_by_role(
            "combobox"
        ).nth(index).is_visible()
    ]

    fallback_index = {
        "Exact pressing cohort":
            0,
        "Wizard stage":
            1,
    }.get(label)

    if (
        fallback_index is not None
        and len(
            visible_comboboxes
        )
        > fallback_index
    ):
        fallback = visible_comboboxes[
            fallback_index
        ]

        container = fallback.locator(
            "xpath=ancestor::*"
            "[@data-testid='stSelectbox'][1]"
        )

        if container.count() > 0:
            return container.first

        return fallback.locator(
            "xpath=.."
        )

    diagnostics = json.dumps(
        _selectbox_diagnostics(
            page
        ),
        ensure_ascii=False,
        indent=2,
    )

    raise RuntimeError(
        f"Selectbox was not found: {label}\n"
        f"Visible comboboxes:\n{diagnostics}"
    )


def choose_selectbox_option(
    page: Page,
    *,
    label: str,
    option_pattern: re.Pattern[str],
    timeout_ms: int,
) -> str:
    """Choose one Streamlit selectbox option."""
    container = selectbox_container(
        page,
        label,
        timeout_ms,
    )

    combobox = _first_visible(
        container.locator(
            '[role="combobox"]'
        )
    )

    if combobox is None:
        if (
            container.get_attribute(
                "role"
            )
            == "combobox"
        ):
            combobox = container
        else:
            raise RuntimeError(
                f"Visible combobox was not found inside: {label}"
            )

    combobox.scroll_into_view_if_needed()

    combobox.click(
        force=True
    )

    page.wait_for_timeout(
        250
    )

    option = _first_visible(
        page.get_by_role(
            "option",
            name=option_pattern,
        )
    )

    if option is None:
        option = _first_visible(
            page.locator(
                '[role="option"]'
            ).filter(
                has_text=option_pattern,
            )
        )

    if option is None:
        visible_options = []

        options = page.locator(
            '[role="option"]'
        )

        for index in range(
            options.count()
        ):
            candidate = options.nth(
                index
            )

            if candidate.is_visible():
                visible_options.append(
                    (
                        candidate.inner_text()
                        or ""
                    ).strip()
                )

        raise RuntimeError(
            f"Option for {label!r} was not found. "
            f"Visible options: {visible_options}"
        )

    selected_text = (
        option.inner_text()
        or ""
    ).strip()

    option.click(
        force=True
    )

    page.wait_for_timeout(
        750
    )

    wait_for_streamlit(
        page,
        timeout_ms,
    )

    return selected_text




def visible_write_controls(
    page: Page,
) -> list[str]:
    """Return visible controls that could trigger persistence."""
    names: list[str] = []

    buttons = page.get_by_role(
        "button"
    )

    for index in range(
        buttons.count()
    ):
        button = buttons.nth(index)

        if not button.is_visible():
            continue

        label = (
            button.inner_text()
            or button.get_attribute(
                "aria-label"
            )
            or ""
        ).strip()

        if (
            label
            and WRITE_CONTROL_PATTERN.search(
                label
            )
        ):
            names.append(label)

    return sorted(
        set(names)
    )


def _stage_heading(
    page: Page,
    heading_text: str,
) -> Locator:
    """Return the expected wizard-stage heading."""
    return page.get_by_role(
        "heading",
        name=re.compile(
            re.escape(
                heading_text
            ),
            re.IGNORECASE,
        ),
    ).first


def _visible_navigation_button(
    page: Page,
    name_pattern: re.Pattern[str],
) -> Locator | None:
    """Return one visible wizard navigation button."""
    return _first_visible(
        page.get_by_role(
            "button",
            name=name_pattern,
        )
    )


def _visible_heading_texts(
    page: Page,
) -> list[str]:
    """Return visible page headings for actionable diagnostics."""
    headings = page.locator(
        "h1, h2, h3"
    )

    values: list[str] = []

    for index in range(
        headings.count()
    ):
        heading = headings.nth(
            index
        )

        try:
            if not heading.is_visible():
                continue

            text_value = (
                heading.inner_text()
                or ""
            ).strip()
        except Exception:
            continue

        if text_value:
            values.append(
                text_value
            )

    return values


def reset_to_first_stage(
    page: Page,
    timeout_ms: int,
) -> None:
    """Return a fresh wizard session to stage one."""
    deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    expected_heading = _stage_heading(
        page,
        STAGES[0][1],
    )

    while time.monotonic() < deadline:
        try:
            if (
                expected_heading.count() > 0
                and expected_heading.is_visible()
            ):
                return
        except Exception:
            pass

        previous_button = (
            _visible_navigation_button(
                page,
                re.compile(
                    r"Previous",
                    re.IGNORECASE,
                ),
            )
        )

        if previous_button is not None:
            try:
                if not previous_button.is_disabled():
                    previous_button.scroll_into_view_if_needed()
                    previous_button.click(
                        force=True
                    )

                    page.wait_for_timeout(
                        350
                    )

                    wait_for_streamlit(
                        page,
                        timeout_ms,
                    )

                    continue
            except Exception:
                pass

        page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        "Could not reset the wizard to stage one. "
        "Visible headings: "
        + json.dumps(
            _visible_heading_texts(
                page
            ),
            ensure_ascii=False,
        )
    )


def advance_to_next_stage(
    page: Page,
    *,
    expected_heading: str,
    timeout_ms: int,
) -> None:
    """Advance one stage using the wizard's Next control."""
    next_button = (
        _visible_navigation_button(
            page,
            re.compile(
                r"Next",
                re.IGNORECASE,
            ),
        )
    )

    if next_button is None:
        raise RuntimeError(
            "The visible Next control was not found. "
            "Visible headings: "
            + json.dumps(
                _visible_heading_texts(
                    page
                ),
                ensure_ascii=False,
            )
        )

    if next_button.is_disabled():
        raise RuntimeError(
            "The Next control is unexpectedly disabled."
        )

    next_button.scroll_into_view_if_needed()

    next_button.click(
        force=True
    )

    page.wait_for_timeout(
        350
    )

    wait_for_streamlit(
        page,
        timeout_ms,
    )

    heading = _stage_heading(
        page,
        expected_heading,
    )

    heading.wait_for(
        state="visible",
        timeout=timeout_ms,
    )


def stage_acceptance(
    page: Page,
    *,
    stage_number: int,
    heading_text: str,
    output_dir: Path,
    timeout_ms: int,
) -> dict[str, Any]:
    """Open and verify one wizard stage without persistence."""
    if stage_number == 1:
        navigation_action = (
            "Initial stage"
        )

        heading = _stage_heading(
            page,
            heading_text,
        )

        heading.wait_for(
            state="visible",
            timeout=timeout_ms,
        )
    else:
        navigation_action = (
            "Next control"
        )

        advance_to_next_stage(
            page,
            expected_heading=
                heading_text,
            timeout_ms=
                timeout_ms,
        )

        heading = _stage_heading(
            page,
            heading_text,
        )

    screenshot_path = (
        output_dir
        / f"stage-{stage_number:02d}.png"
    )

    page.screenshot(
        path=str(
            screenshot_path
        ),
        full_page=True,
    )

    return {
        "stage":
            stage_number,
        "expected_heading":
            heading_text,
        "selected_option":
            navigation_action,
        "heading_visible":
            heading.is_visible(),
        "write_controls_visible":
            visible_write_controls(
                page
            ),
        "screenshot":
            str(
                screenshot_path
            ),
    }



def _visible_app_text(
    page: Page,
) -> str:
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


def ensure_catalog_cohort_selected(
    page: Page,
    *,
    catalog: str,
    timeout_ms: int,
) -> str:
    """Select the cohort or verify the rendered default cohort."""
    reset_to_first_stage(
        page,
        timeout_ms,
    )

    try:
        selected = choose_selectbox_option(
            page,
            label="Exact pressing cohort",
            option_pattern=re.compile(
                re.escape(
                    catalog
                ),
                re.IGNORECASE,
            ),
            timeout_ms=timeout_ms,
        )
    except RuntimeError as selector_error:
        wait_for_streamlit(
            page,
            timeout_ms,
        )

        rendered_text = _visible_app_text(
            page
        )

        if (
            catalog.casefold()
            in rendered_text.casefold()
        ):
            return (
                "Default cohort confirmed in rendered "
                f"pressing identity: {catalog}"
            )

        excerpt = rendered_text[
            :4000
        ]

        raise RuntimeError(
            "The cohort selector was unavailable and the "
            f"rendered pressing identity did not contain {catalog!r}.\n"
            f"Selector error:\n{selector_error}\n"
            "Visible headings:\n"
            + json.dumps(
                _visible_heading_texts(
                    page
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\nRendered application excerpt:\n"
            + excerpt
        ) from selector_error

    if (
        catalog.casefold()
        not in selected.casefold()
    ):
        raise RuntimeError(
            "The selected cohort does not contain "
            f"catalog text {catalog!r}: {selected}"
        )

    reset_to_first_stage(
        page,
        timeout_ms,
    )

    return selected



OPTIONAL_ASSET_SUFFIXES = (
    "/favicon.ico",
    "/favicon.png",
    "/manifest.json",
    ".webmanifest",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".map",
)


def _console_event_payload(
    message: Any,
) -> dict[str, Any]:
    """Normalize one Playwright console event."""
    location = message.location or {}

    return {
        "type":
            str(message.type),
        "text":
            str(message.text),
        "url":
            str(
                location.get(
                    "url",
                    "",
                )
                or ""
            ),
        "line_number":
            location.get(
                "lineNumber"
            ),
        "column_number":
            location.get(
                "columnNumber"
            ),
    }


def _response_error_payload(
    response: Any,
) -> dict[str, Any]:
    """Normalize one failed HTTP response."""
    request = response.request

    return {
        "status":
            int(response.status),
        "status_text":
            str(response.status_text),
        "url":
            str(response.url),
        "resource_type":
            str(request.resource_type),
        "method":
            str(request.method),
    }


def _url_is_optional_asset(
    url: str,
) -> bool:
    """Return whether a URL is an optional static asset."""
    normalized = (
        str(url)
        .split("#", 1)[0]
        .split("?", 1)[0]
        .lower()
    )

    return any(
        normalized.endswith(
            suffix
        )
        for suffix in OPTIONAL_ASSET_SUFFIXES
    )


def _is_non_blocking_http_error(
    event: dict[str, Any],
) -> bool:
    """Allow only 404 failures for optional static assets."""
    try:
        status = int(
            event.get(
                "status",
                0,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return False

    if status != 404:
        return False

    resource_type = str(
        event.get(
            "resource_type",
            "",
        )
    ).lower()

    if resource_type in {
        "image",
        "font",
        "media",
    }:
        return True

    return _url_is_optional_asset(
        str(
            event.get(
                "url",
                "",
            )
        )
    )


def _classify_browser_errors(
    console_events: list[dict[str, Any]],
    http_errors: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Separate functional failures from optional asset failures."""
    non_blocking_http_errors = [
        event
        for event in http_errors
        if _is_non_blocking_http_error(
            event
        )
    ]

    blocking_http_errors = [
        event
        for event in http_errors
        if not _is_non_blocking_http_error(
            event
        )
    ]

    non_blocking_console_errors: list[
        dict[str, Any]
    ] = []

    blocking_console_errors: list[
        dict[str, Any]
    ] = []

    for event in console_events:
        text_value = str(
            event.get(
                "text",
                "",
            )
        )

        location_url = str(
            event.get(
                "url",
                "",
            )
        )

        missing_resource = (
            "failed to load resource"
            in text_value.lower()
        )

        optional_location = (
            bool(location_url)
            and _url_is_optional_asset(
                location_url
            )
        )

        optional_response_context = (
            bool(
                non_blocking_http_errors
            )
            and not blocking_http_errors
        )

        if (
            missing_resource
            and (
                optional_location
                or optional_response_context
            )
        ):
            non_blocking_console_errors.append(
                event
            )
        else:
            blocking_console_errors.append(
                event
            )

    return {
        "blocking_console_errors":
            blocking_console_errors,
        "non_blocking_console_errors":
            non_blocking_console_errors,
        "blocking_http_errors":
            blocking_http_errors,
        "non_blocking_http_errors":
            non_blocking_http_errors,
    }

def main() -> int:
    """Run the complete browser acceptance."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    console_events: list[
        dict[str, Any]
    ] = []

    http_errors: list[
        dict[str, Any]
    ] = []

    page_errors: list[str] = []
    stage_results: list[dict[str, Any]] = []

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

        page.set_default_timeout(
            args.timeout_ms
        )

        open_wizard(
            page,
            args.url,
            args.timeout_ms,
        )

        selected_cohort = ensure_catalog_cohort_selected(
            page,
            catalog=args.catalog,
            timeout_ms=args.timeout_ms,
        )

        def handle_console(
            message: Any,
        ) -> None:
            if message.type != "error":
                return

            console_events.append(
                _console_event_payload(
                    message
                )
            )

        def handle_response(
            response: Any,
        ) -> None:
            if int(response.status) < 400:
                return

            http_errors.append(
                _response_error_payload(
                    response
                )
            )

        page.on(
            "console",
            handle_console,
        )

        page.on(
            "response",
            handle_response,
        )

        page.on(
            "pageerror",
            lambda error: page_errors.append(
                str(error)
            ),
        )

        for (
            stage_number,
            heading_text,
        ) in STAGES:
            stage_results.append(
                stage_acceptance(
                    page,
                    stage_number=
                        stage_number,
                    heading_text=
                        heading_text,
                    output_dir=
                        args.output_dir,
                    timeout_ms=
                        args.timeout_ms,
                )
            )

        context.close()
        browser.close()

    classifications = _classify_browser_errors(
        console_events,
        http_errors,
    )

    successful_stages = sum(
        bool(
            result[
                "heading_visible"
            ]
        )
        for result in stage_results
    )

    blocking_console_errors = (
        classifications[
            "blocking_console_errors"
        ]
    )

    non_blocking_console_errors = (
        classifications[
            "non_blocking_console_errors"
        ]
    )

    blocking_http_errors = (
        classifications[
            "blocking_http_errors"
        ]
    )

    non_blocking_http_errors = (
        classifications[
            "non_blocking_http_errors"
        ]
    )

    report = {
        "url":
            args.url,
        "catalog":
            args.catalog,
        "selected_cohort":
            selected_cohort,
        "expected_stage_count":
            len(STAGES),
        "successful_stage_count":
            successful_stages,
        "stages":
            stage_results,
        "console_errors":
            [
                event["text"]
                for event in console_events
            ],
        "console_events":
            console_events,
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
        "save_buttons_clicked":
            0,
        "success":
            (
                successful_stages
                == len(STAGES)
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
        if report["success"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
