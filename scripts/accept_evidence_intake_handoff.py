#!/usr/bin/env python3
"""Browser acceptance for Wizard-to-Evidence-Intake handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Locator,
    Page,
    sync_playwright,
)


WIZARD_ROUTES = (
    "/8_Cohort_Curation_Wizard",
    "/Cohort_Curation_Wizard",
    "/Cohort-Curation-Wizard",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify Wizard Stage 3 handoff, packet cloning, "
            "upload hashing, and return navigation."
        )
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8501",
    )

    parser.add_argument(
        "--catalog",
        default="MR2276",
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


def first_visible(
    locator: Locator,
) -> Locator | None:
    """Return the first visible locator."""
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


def wait_for_streamlit(
    page: Page,
    timeout_ms: int,
) -> None:
    """Wait until the Streamlit app is interactive."""
    page.locator(
        '[data-testid="stAppViewContainer"]'
    ).first.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    while time.monotonic() < deadline:
        running = page.locator(
            '[data-testid="stStatusWidget"]'
        )

        visible_running = False

        for index in range(
            running.count()
        ):
            try:
                if running.nth(
                    index
                ).is_visible():
                    visible_running = True
                    break
            except Exception:
                continue

        if not visible_running:
            return

        page.wait_for_timeout(
            200
        )

    raise RuntimeError(
        "Streamlit did not finish rendering."
    )


def open_wizard(
    page: Page,
    base_url: str,
    timeout_ms: int,
) -> str:
    """Open the wizard with the proven eleven-stage navigator."""
    import importlib.util
    import inspect
    import sys as runtime_sys

    navigator_path = (
        Path(
            "scripts/accept_cohort_wizard.py"
        ).resolve()
    )

    if not navigator_path.is_file():
        raise RuntimeError(
            "The proven Cohort Wizard navigator is missing: "
            f"{navigator_path}"
        )

    module_name = (
        "auction_etl_proven_cohort_wizard_acceptance"
    )

    specification = (
        importlib.util.spec_from_file_location(
            module_name,
            navigator_path,
        )
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            "The proven Cohort Wizard navigator could not "
            "be loaded."
        )

    module = importlib.util.module_from_spec(
        specification
    )

    runtime_sys.modules[
        module_name
    ] = module

    specification.loader.exec_module(
        module
    )

    delegate = getattr(
        module,
        "open_wizard",
        None,
    )

    if not callable(
        delegate
    ):
        raise RuntimeError(
            "The proven acceptance module does not expose "
            "open_wizard()."
        )

    signature = inspect.signature(
        delegate
    )

    known_arguments = {
        "page":
            page,
        "url":
            base_url,
        "base_url":
            base_url,
        "timeout_ms":
            timeout_ms,
    }

    keyword_arguments: dict[
        str,
        Any,
    ] = {}

    unsupported_required: list[str] = []

    for name, parameter in (
        signature.parameters.items()
    ):
        if name in known_arguments:
            keyword_arguments[
                name
            ] = known_arguments[
                name
            ]

            continue

        if (
            parameter.default
            is inspect.Parameter.empty
            and parameter.kind
            not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ):
            unsupported_required.append(
                name
            )

    if unsupported_required:
        raise RuntimeError(
            "Unsupported required parameters in the proven "
            "open_wizard() contract: "
            + ", ".join(
                unsupported_required
            )
        )

    navigation_result = delegate(
        **keyword_arguments
    )

    proven_wait = getattr(
        module,
        "wait_for_streamlit",
        None,
    )

    if callable(
        proven_wait
    ):
        proven_wait(
            page,
            timeout_ms,
        )
    else:
        wait_for_streamlit(
            page,
            timeout_ms,
        )

    hydration_deadline = (
        time.monotonic()
        + timeout_ms / 1000
    )

    last_rendered_text = ""

    while (
        time.monotonic()
        < hydration_deadline
    ):
        container = page.locator(
            '[data-testid="stAppViewContainer"]'
        ).first

        try:
            if (
                container.count() > 0
                and container.is_visible()
            ):
                last_rendered_text = (
                    container.inner_text()
                    or ""
                ).strip()
        except Exception:
            last_rendered_text = ""

        normalized_text = " ".join(
            last_rendered_text.casefold().split()
        )

        title_ready = (
            "cohort curation wizard"
            in normalized_text
        )

        stage_ready = (
            "exact pressing cohort"
            in normalized_text
            and (
                "exact pressing identity"
                in normalized_text
                or "assigned listings"
                in normalized_text
                or "evidence and attachments"
                in normalized_text
            )
        )

        if (
            title_ready
            or stage_ready
        ):
            if isinstance(
                navigation_result,
                str,
            ):
                return navigation_result

            return page.url

        page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        "The proven navigator completed, but the Cohort "
        "Curation Wizard did not finish rendering.\n"
        f"Current URL: {page.url}\n"
        "Rendered application excerpt:\n"
        + last_rendered_text[:4000]
    )


def select_catalog(
    page: Page,
    catalog: str,
    timeout_ms: int,
) -> str:
    """Select or verify the requested exact-pressing cohort."""
    combobox = first_visible(
        page.get_by_role(
            "combobox",
            name=re.compile(
                r"Exact pressing cohort",
                re.IGNORECASE,
            ),
        )
    )

    if combobox is not None:
        current_value = (
            combobox.input_value()
            or ""
        )

        if catalog.casefold() not in current_value.casefold():
            combobox.click()

            option = page.get_by_role(
                "option",
                name=re.compile(
                    re.escape(
                        catalog
                    ),
                    re.IGNORECASE,
                ),
            ).first

            option.wait_for(
                state="visible",
                timeout=timeout_ms,
            )

            option.click()

            wait_for_streamlit(
                page,
                timeout_ms,
            )

        value = (
            combobox.input_value()
            or ""
        )

        if catalog.casefold() in value.casefold():
            return value

    body_text = (
        page.locator(
            '[data-testid="stAppViewContainer"]'
        ).first.inner_text()
        or ""
    )

    if catalog.casefold() in body_text.casefold():
        return (
            "Rendered default cohort contains "
            + catalog
        )

    try:
        import importlib.util
        import inspect
        import sys as runtime_sys

        module_name = (
            "auction_etl_proven_cohort_wizard_acceptance"
        )

        module = runtime_sys.modules.get(
            module_name
        )

        if module is None:
            navigator_path = (
                Path(
                    "scripts/accept_cohort_wizard.py"
                ).resolve()
            )

            specification = (
                importlib.util.spec_from_file_location(
                    module_name,
                    navigator_path,
                )
            )

            if (
                specification is None
                or specification.loader is None
            ):
                raise RuntimeError(
                    "The proven cohort selector could "
                    "not be loaded."
                )

            module = (
                importlib.util.module_from_spec(
                    specification
                )
            )

            runtime_sys.modules[
                module_name
            ] = module

            specification.loader.exec_module(
                module
            )

        delegate = getattr(
            module,
            "ensure_catalog_cohort_selected",
            None,
        )

        if not callable(
            delegate
        ):
            raise RuntimeError(
                "The proven acceptance module does not "
                "expose ensure_catalog_cohort_selected()."
            )

        signature = inspect.signature(
            delegate
        )

        known_arguments = {
            "page":
                page,
            "catalog":
                catalog,
            "timeout_ms":
                timeout_ms,
        }

        keyword_arguments = {}
        unsupported_required = []

        for name, parameter in (
            signature.parameters.items()
        ):
            if name in known_arguments:
                keyword_arguments[
                    name
                ] = known_arguments[
                    name
                ]

                continue

            if (
                parameter.default
                is inspect.Parameter.empty
                and parameter.kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            ):
                unsupported_required.append(
                    name
                )

        if unsupported_required:
            raise RuntimeError(
                "Unsupported required proven-selector "
                "parameters: "
                + ", ".join(
                    unsupported_required
                )
            )

        selected = delegate(
            **keyword_arguments
        )

        selected_text = str(
            selected
            or ""
        ).strip()

        if (
            catalog.casefold()
            not in selected_text.casefold()
        ):
            raise RuntimeError(
                "The proven selector returned an "
                "unexpected cohort: "
                f"{selected_text!r}"
            )

        return selected_text
    except Exception as fallback_error:
        raise RuntimeError(
            "Exact pressing cohort "
            f"{catalog!r} was not selected. "
            "The proven default-cohort fallback also "
            f"failed: {fallback_error}"
        ) from fallback_error


def reset_to_stage_one(
    page: Page,
    timeout_ms: int,
) -> None:
    """Return the wizard to Stage 1."""
    stage_one = page.get_by_role(
        "heading",
        name=re.compile(
            r"1\.\s*Exact pressing identity",
            re.IGNORECASE,
        ),
    ).first

    for _ in range(
        12
    ):
        if (
            stage_one.count() > 0
            and stage_one.is_visible()
        ):
            return

        previous = first_visible(
            page.get_by_role(
                "button",
                name=re.compile(
                    r"Previous",
                    re.IGNORECASE,
                ),
            )
        )

        if previous is None:
            break

        previous.click(
            force=True
        )

        wait_for_streamlit(
            page,
            timeout_ms,
        )

    stage_one.wait_for(
        state="visible",
        timeout=timeout_ms,
    )


def advance_to_stage_three(
    page: Page,
    timeout_ms: int,
) -> None:
    """Advance sequentially to Stage 3."""
    reset_to_stage_one(
        page,
        timeout_ms,
    )

    for expected_heading in (
        r"2\.\s*Assigned listings",
        r"3\.\s*Evidence and attachments",
    ):
        next_button = first_visible(
            page.get_by_role(
                "button",
                name=re.compile(
                    r"Next",
                    re.IGNORECASE,
                ),
            )
        )

        if next_button is None:
            raise RuntimeError(
                "Wizard Next button was not found."
            )

        next_button.click(
            force=True
        )

        wait_for_streamlit(
            page,
            timeout_ms,
        )

        page.get_by_role(
            "heading",
            name=re.compile(
                expected_heading,
                re.IGNORECASE,
            ),
        ).first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )


def extract_working_packet(
    page: Page,
) -> Path:
    """Extract the active working packet path from rendered text."""
    text_value = (
        page.locator(
            '[data-testid="stAppViewContainer"]'
        ).first.inner_text()
        or ""
    )

    match = re.search(
        r"Working packet:\s*([^\n]+)",
        text_value,
        re.IGNORECASE,
    )

    if match is None:
        raise RuntimeError(
            "Working packet path was not rendered."
        )

    raw_path = (
        match.group(1)
        .strip()
        .strip("`")
    )

    path = Path(
        raw_path
    )

    if not path.is_absolute():
        path = (
            Path.cwd()
            / path
        )

    return path.resolve()


def safe_cleanup_packet(
    packet_path: Path,
) -> bool:
    """Delete only an isolated Evidence Intake working packet."""
    logs_root = (
        Path.cwd()
        / "logs"
    ).resolve()

    resolved = packet_path.resolve()

    try:
        relative = resolved.relative_to(
            logs_root
        )
    except ValueError:
        return False

    if not any(
        part.startswith(
            "evidence-intake-"
        )
        for part in relative.parts
    ):
        return False

    if resolved.is_dir():
        shutil.rmtree(
            resolved
        )

        parent = resolved.parent

        if (
            parent.is_dir()
            and not any(
                parent.iterdir()
            )
        ):
            parent.rmdir()

        return True

    return False


def main() -> int:
    """Run browser acceptance without staging or applying evidence."""
    args = parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    fixture_path = (
        args.output_dir
        / "upload-hash-fixture.txt"
    )

    fixture_payload = (
        b"Evidence Intake browser acceptance fixture.\n"
    )

    fixture_path.write_bytes(
        fixture_payload
    )

    expected_sha256 = hashlib.sha256(
        fixture_payload
    ).hexdigest()

    console_errors: list[str] = []
    page_errors: list[str] = []
    working_packet: Path | None = None
    packet_cleaned = False
    selected_cohort = ""
    wizard_url = ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width": 1600,
                "height": 1100,
            }
        )

        page = context.new_page()

        wizard_url = open_wizard(
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

        selected_cohort = select_catalog(
            page,
            args.catalog,
            args.timeout_ms,
        )

        advance_to_stage_three(
            page,
            args.timeout_ms,
        )

        stage_three_screenshot = (
            args.output_dir
            / "wizard-stage-03.png"
        )

        page.screenshot(
            path=str(
                stage_three_screenshot
            ),
            full_page=True,
        )

        handoff_button = page.get_by_role(
            "button",
            name=re.compile(
                r"Open Evidence Intake for this pressing",
                re.IGNORECASE,
            ),
        ).first

        try:
            handoff_button.wait_for(
                state="visible",
                timeout=args.timeout_ms,
            )
        except Exception as error:
            app_container = page.locator(
                '[data-testid="stAppViewContainer"]'
            ).first

            try:
                rendered_text = (
                    app_container.inner_text()
                    or ""
                ).strip()
            except Exception:
                rendered_text = ""

            visible_buttons: list[str] = []

            buttons = page.get_by_role(
                "button"
            )

            for index in range(
                buttons.count()
            ):
                button = buttons.nth(
                    index
                )

                try:
                    if not button.is_visible():
                        continue

                    label = (
                        button.inner_text()
                        or button.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).strip()
                except Exception:
                    continue

                if label:
                    visible_buttons.append(
                        label
                    )

            raise RuntimeError(
                "Evidence Intake handoff button was not rendered.\n"
                "Visible buttons:\n"
                + json.dumps(
                    visible_buttons,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\nRendered Stage 3 excerpt:\n"
                + rendered_text[:6000]
            ) from error

        handoff_button.click(
            force=True
        )

        wait_for_streamlit(
            page,
            args.timeout_ms,
        )

        page.get_by_role(
            "heading",
            name=re.compile(
                r"Exact-Pressing Evidence Intake",
                re.IGNORECASE,
            ),
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        handoff_text = page.get_by_text(
            re.compile(
                r"Handoff from Cohort Curation Wizard",
                re.IGNORECASE,
            )
        ).first

        handoff_text.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        working_packet = extract_working_packet(
            page
        )

        if not working_packet.is_dir():
            raise RuntimeError(
                "Handoff packet was not created: "
                f"{working_packet}"
            )

        file_input = page.locator(
            'input[type="file"]'
        ).first

        file_input.wait_for(
            state="attached",
            timeout=args.timeout_ms,
        )

        file_input.set_input_files(
            str(
                fixture_path
            )
        )

        wait_for_streamlit(
            page,
            args.timeout_ms,
        )

        digest_locator = page.get_by_text(
            expected_sha256,
            exact=True,
        ).first

        digest_locator.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        stage_button = page.get_by_role(
            "button",
            name=re.compile(
                r"Stage evidence and run safe review",
                re.IGNORECASE,
            ),
        ).first

        stage_button.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        intake_screenshot = (
            args.output_dir
            / "evidence-intake.png"
        )

        page.screenshot(
            path=str(
                intake_screenshot
            ),
            full_page=True,
        )

        return_button = page.get_by_role(
            "button",
            name=re.compile(
                r"Return to Cohort Curation Wizard",
                re.IGNORECASE,
            ),
        ).first

        return_button.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        return_button.click(
            force=True
        )

        wait_for_streamlit(
            page,
            args.timeout_ms,
        )

        page.get_by_role(
            "heading",
            name=re.compile(
                r"3\.\s*Evidence and attachments",
                re.IGNORECASE,
            ),
        ).first.wait_for(
            state="visible",
            timeout=args.timeout_ms,
        )

        returned_screenshot = (
            args.output_dir
            / "wizard-returned-stage-03.png"
        )

        page.screenshot(
            path=str(
                returned_screenshot
            ),
            full_page=True,
        )

        context.close()
        browser.close()

    if working_packet is not None:
        packet_cleaned = safe_cleanup_packet(
            working_packet
        )

    report: dict[str, Any] = {
        "url":
            args.url,
        "wizard_url":
            wizard_url,
        "catalog":
            args.catalog,
        "selected_cohort":
            selected_cohort,
        "handoff_visible":
            True,
        "working_packet_created":
            working_packet is not None,
        "working_packet":
            (
                str(
                    working_packet
                )
                if working_packet is not None
                else None
            ),
        "upload_sha256":
            expected_sha256,
        "upload_sha256_visible":
            True,
        "stage_button_visible":
            True,
        "stage_button_clicked":
            False,
        "return_navigation_passed":
            True,
        "packet_cleaned":
            packet_cleaned,
        "console_errors":
            console_errors,
        "page_errors":
            page_errors,
        "database_writes":
            0,
        "success":
            (
                working_packet is not None
                and packet_cleaned
                and not page_errors
                and not console_errors
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
        if report["success"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
