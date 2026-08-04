"""Cohort wizard browser acceptance command tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from scripts.accept_cohort_wizard import (
    STAGES,
    stage_acceptance,
)


SCRIPT = Path(
    "scripts/accept_cohort_wizard.py"
)


def test_acceptance_covers_exactly_eleven_stages() -> None:
    """Every wizard stage is included."""
    assert len(STAGES) == 11

    assert STAGES[0] == (
        1,
        "1. Exact pressing identity",
    )

    assert STAGES[-1] == (
        11,
        "11. Audit and final report",
    )


def test_stage_acceptance_only_reads_and_captures() -> None:
    """Stage acceptance never clicks a persistence control."""
    source = inspect.getsource(
        stage_acceptance
    )

    assert "screenshot" in source
    assert "heading_visible" in source
    assert "write_controls_visible" in source
    assert "Save" not in source
    assert "Apply approved" not in source


def test_script_reports_zero_clicked_save_buttons() -> None:
    """The report explicitly records zero persistence clicks."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert '"save_buttons_clicked":\n            0' in source


def test_script_has_complete_entry_point() -> None:
    """The command is directly executable."""
    tree = ast.parse(
        SCRIPT.read_text(
            encoding="utf-8"
        )
    )

    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert {
        "main",
        "open_wizard",
        "choose_selectbox_option",
        "stage_acceptance",
    } <= function_names

def test_selectbox_locator_supports_streamlit_sidebar_layouts() -> None:
    """The browser command handles current Streamlit sidebar DOMs."""
    import scripts.accept_cohort_wizard as acceptance

    sidebar_source = inspect.getsource(
        acceptance.ensure_sidebar_visible
    )

    locator_source = inspect.getsource(
        acceptance.selectbox_container
    )

    chooser_source = inspect.getsource(
        acceptance.choose_selectbox_option
    )

    assert "stSidebarCollapsedControl" in sidebar_source
    assert 'get_by_role(\n        "combobox"' in locator_source
    assert "ancestor::*" in locator_source
    assert "stSelectbox" in locator_source
    assert "Visible comboboxes" in locator_source
    assert "Exact pressing cohort" in locator_source
    assert "Wizard stage" in locator_source
    assert "scroll_into_view_if_needed" in chooser_source
    assert "force=True" in chooser_source

def test_stage_acceptance_uses_sequential_navigation() -> None:
    """Stages advance through the real Previous and Next controls."""
    import scripts.accept_cohort_wizard as acceptance

    stage_source = inspect.getsource(
        acceptance.stage_acceptance
    )

    reset_source = inspect.getsource(
        acceptance.reset_to_first_stage
    )

    next_source = inspect.getsource(
        acceptance.advance_to_next_stage
    )

    assert "advance_to_next_stage(" in stage_source
    assert "choose_selectbox_option(" not in stage_source
    assert "Previous" in reset_source
    assert "Next" in next_source
    assert "scroll_into_view_if_needed" in next_source
    assert "force=True" in next_source
    assert "expected_heading" in next_source

def test_catalog_selection_accepts_rendered_default_cohort() -> None:
    """A hidden sidebar is valid when the main identity proves the cohort."""
    import scripts.accept_cohort_wizard as acceptance

    selector_source = inspect.getsource(
        acceptance.ensure_catalog_cohort_selected
    )

    text_source = inspect.getsource(
        acceptance._visible_app_text
    )

    main_source = inspect.getsource(
        acceptance.main
    )

    assert "choose_selectbox_option(" in selector_source
    assert "_visible_app_text(" in selector_source
    assert "Default cohort confirmed" in selector_source
    assert "rendered pressing identity" in selector_source
    assert "stAppViewContainer" in text_source
    assert "ensure_catalog_cohort_selected(" in main_source


def test_optional_resource_404s_are_non_blocking() -> None:
    """Missing optional visual assets do not fail functional acceptance."""
    import scripts.accept_cohort_wizard as acceptance

    events = (
        {
            "status": 404,
            "url": "http://127.0.0.1:8501/favicon.ico",
            "resource_type": "other",
        },
        {
            "status": 404,
            "url": "http://127.0.0.1:8501/missing-image",
            "resource_type": "image",
        },
        {
            "status": 404,
            "url": "http://127.0.0.1:8501/app.js.map",
            "resource_type": "other",
        },
    )

    for event in events:
        assert acceptance._is_non_blocking_http_error(
            event
        )


def test_functional_resource_failures_remain_blocking() -> None:
    """Missing application code, styles, and data remain failures."""
    import scripts.accept_cohort_wizard as acceptance

    events = (
        {
            "status": 404,
            "url": "http://127.0.0.1:8501/app.js",
            "resource_type": "script",
        },
        {
            "status": 404,
            "url": "http://127.0.0.1:8501/app.css",
            "resource_type": "stylesheet",
        },
        {
            "status": 500,
            "url": "http://127.0.0.1:8501/api/report",
            "resource_type": "fetch",
        },
    )

    for event in events:
        assert not acceptance._is_non_blocking_http_error(
            event
        )


def test_diagnostics_start_after_wizard_navigation() -> None:
    """Speculative initial navigation noise is not part of stage checks."""
    import inspect

    import scripts.accept_cohort_wizard as acceptance

    main_source = inspect.getsource(
        acceptance.main
    )

    selection_position = main_source.index(
        "selected_cohort = ensure_catalog_cohort_selected("
    )

    listener_position = main_source.index(
        'page.on(\n            "console"'
    )

    assert selection_position < listener_position
    assert '"blocking_console_errors"' in main_source
    assert '"blocking_http_errors"' in main_source
    assert '"non_blocking_http_errors"' in main_source


def test_open_wizard_discovers_streamlit_page_routes() -> None:
    """Wizard navigation supports filename and sidebar routes."""
    import inspect

    import scripts.accept_cohort_wizard as acceptance

    route_source = inspect.getsource(
        acceptance.open_wizard
    )

    assert "/Cohort_Curation_Wizard" in route_source
    assert "/8_Cohort_Curation_Wizard" in route_source
    assert 'data-testid="stSidebarNav"' in route_source
    assert "a[href]" in route_source
    assert "discovered_links" in route_source
    assert "attempted_routes" in route_source
    assert "stException" in route_source
    assert "cohort-wizard-navigation-failure.png" in route_source
