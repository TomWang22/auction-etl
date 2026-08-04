"""Structural tests for Evidence Intake browser acceptance."""

from __future__ import annotations

import ast
from pathlib import Path


SCRIPT = Path(
    "scripts/accept_evidence_intake_handoff.py"
)


def test_acceptance_script_compiles() -> None:
    """The browser command is valid Python."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    ast.parse(
        source
    )


def test_acceptance_covers_complete_handoff() -> None:
    """The command verifies navigation, hashing, and return."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "Open Evidence Intake for this pressing",
        "Exact-Pressing Evidence Intake",
        "Handoff from Cohort Curation Wizard",
        "input[type=\"file\"]",
        "hashlib.sha256",
        "Stage evidence and run safe review",
        "Return to Cohort Curation Wizard",
        "packet_cleaned",
    )

    for fragment in required:
        assert fragment in source


def test_acceptance_never_clicks_staging_control() -> None:
    """Browser acceptance remains evidence- and database-safe."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert '"stage_button_clicked":\n            False' in source
    assert "stage_button.click(" not in source
    assert '"database_writes":\n            0' in source
    assert "safe_cleanup_packet(" in source


def test_acceptance_supports_streamlit_route_variants() -> None:
    """Numeric and non-numeric multipage routes are supported."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert "/8_Cohort_Curation_Wizard" in source
    assert "/Cohort_Curation_Wizard" in source
    assert "get_by_role(" in source


def test_route_discovery_uses_real_sidebar_hrefs() -> None:
    """Acceptance reuses the proven eleven-stage navigator."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    open_wizard = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "open_wizard"
        ),
        None,
    )

    assert open_wizard is not None

    string_literals = {
        node.value
        for node in ast.walk(
            open_wizard
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    assert (
        "scripts/accept_cohort_wizard.py"
        in string_literals
    )

    call_names: set[str] = set()

    for node in ast.walk(
        open_wizard
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if isinstance(
            node.func,
            ast.Name,
        ):
            call_names.add(
                node.func.id
            )
        elif isinstance(
            node.func,
            ast.Attribute,
        ):
            call_names.add(
                node.func.attr
            )

    assert "spec_from_file_location" in call_names
    assert "signature" in call_names
    assert "exec_module" in call_names


def test_route_discovery_accepts_unique_stage_controls() -> None:
    """Navigation waits for actual Streamlit wizard hydration."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    open_wizard = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "open_wizard"
        ),
        None,
    )

    assert open_wizard is not None

    assigned_names: set[str] = set()

    for node in ast.walk(
        open_wizard
    ):
        targets = []

        if isinstance(
            node,
            ast.Assign,
        ):
            targets = list(
                node.targets
            )
        elif isinstance(
            node,
            ast.AnnAssign,
        ):
            targets = [
                node.target
            ]

        for target in targets:
            if isinstance(
                target,
                ast.Name,
            ):
                assigned_names.add(
                    target.id
                )

    assert "hydration_deadline" in assigned_names
    assert "last_rendered_text" in assigned_names

    string_literals = {
        node.value
        for node in ast.walk(
            open_wizard
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    required_fragments = (
        "cohort curation wizard",
        "exact pressing cohort",
        "exact pressing identity",
        "evidence and attachments",
    )

    for fragment in required_fragments:
        assert fragment in string_literals


def test_browser_error_listeners_attach_after_navigation() -> None:
    """Route probes cannot pollute functional browser diagnostics."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    main_function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "main"
        ),
        None,
    )

    assert main_function is not None

    open_calls = [
        node
        for node in ast.walk(
            main_function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
        and node.func.id == "open_wizard"
    ]

    assert len(open_calls) == 1

    listener_calls: dict[
        str,
        ast.Call,
    ] = {}

    for node in ast.walk(
        main_function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not isinstance(
            node.func,
            ast.Attribute,
        ):
            continue

        if node.func.attr != "on":
            continue

        if not node.args:
            continue

        event_argument = node.args[0]

        if not isinstance(
            event_argument,
            ast.Constant,
        ):
            continue

        if not isinstance(
            event_argument.value,
            str,
        ):
            continue

        listener_calls[
            event_argument.value
        ] = node

    assert "console" in listener_calls
    assert "pageerror" in listener_calls

    navigation_line = int(
        open_calls[0].lineno
    )

    assert navigation_line < int(
        listener_calls[
            "console"
        ].lineno
    )

    assert navigation_line < int(
        listener_calls[
            "pageerror"
        ].lineno
    )



def test_handoff_wait_has_actionable_diagnostics() -> None:
    """Missing handoff controls report Stage 3 state."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    main_function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "main"
        ),
        None,
    )

    assert main_function is not None

    matching_tries = []

    for node in ast.walk(
        main_function
    ):
        if not isinstance(
            node,
            ast.Try,
        ):
            continue

        contains_handoff_wait = any(
            isinstance(
                child,
                ast.Call,
            )
            and isinstance(
                child.func,
                ast.Attribute,
            )
            and child.func.attr == "wait_for"
            and isinstance(
                child.func.value,
                ast.Name,
            )
            and child.func.value.id
            == "handoff_button"
            for child in ast.walk(
                node
            )
        )

        if contains_handoff_wait:
            matching_tries.append(
                node
            )

    assert len(matching_tries) == 1

    literals = {
        node.value
        for node in ast.walk(
            matching_tries[0]
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    required_fragments = (
        "Evidence Intake handoff button was not rendered.",
        "Visible buttons:",
        "Rendered Stage 3 excerpt:",
    )

    for fragment in required_fragments:
        assert any(
            fragment in literal
            for literal in literals
        )



def test_catalog_selection_uses_proven_default_fallback() -> None:
    """Hidden or unavailable selectors use the proven fallback."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    select_catalog = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "select_catalog"
        ),
        None,
    )

    assert select_catalog is not None

    string_literals = {
        node.value
        for node in ast.walk(
            select_catalog
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    assert (
        "ensure_catalog_cohort_selected"
        in string_literals
    )

    assert (
        "scripts/accept_cohort_wizard.py"
        in string_literals
    )

    call_names = set()

    for node in ast.walk(
        select_catalog
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if isinstance(
            node.func,
            ast.Name,
        ):
            call_names.add(
                node.func.id
            )
        elif isinstance(
            node.func,
            ast.Attribute,
        ):
            call_names.add(
                node.func.attr
            )

    assert "signature" in call_names
    assert "exec_module" in call_names

    return_statements = [
        node
        for node in ast.walk(
            select_catalog
        )
        if isinstance(
            node,
            ast.Return,
        )
    ]

    assert return_statements
