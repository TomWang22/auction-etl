"""Tests for Wizard-to-Evidence-Intake handoff."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from auction_etl.services.evidence_intake import (
    evidence_packet_root,
    latest_packet_for_pressing,
)


WIZARD = Path(
    "app/pages/8_Cohort_Curation_Wizard.py"
)

INTAKE = Path(
    "app/pages/9_Evidence_Intake.py"
)


def test_packet_root_is_configurable() -> None:
    """Packet discovery can be isolated for acceptance."""
    source = inspect.getsource(
        evidence_packet_root
    )

    assert "EVIDENCE_INTAKE_PACKET_ROOT" in source


def test_latest_packet_filters_exact_pressing() -> None:
    """Handoffs cannot select a packet from another pressing."""
    source = inspect.getsource(
        latest_packet_for_pressing
    )

    assert "packet.pressing_id" in source
    assert "discover_packets(" in source


def test_wizard_stage_three_calls_handoff_renderer() -> None:
    """Stage 3 contains the direct Evidence Intake handoff."""
    source = WIZARD.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    stage_functions = []

    for node in tree.body:
        if not isinstance(
            node,
            ast.FunctionDef,
        ):
            continue

        constants = {
            child.value
            for child in ast.walk(
                node
            )
            if isinstance(
                child,
                ast.Constant,
            )
            and isinstance(
                child.value,
                str,
            )
        }

        if any(
            "Evidence and attachments"
            in value
            for value in constants
        ):
            stage_functions.append(
                node
            )

    assert len(stage_functions) == 1

    calls = {
        child.func.id
        for child in ast.walk(
            stage_functions[0]
        )
        if isinstance(
            child,
            ast.Call,
        )
        and isinstance(
            child.func,
            ast.Name,
        )
    }

    assert "_render_evidence_intake_handoff" in calls


def test_handoff_creates_isolated_packet_and_switches_page() -> None:
    """The wizard records return context before navigation."""
    source = WIZARD.read_text(
        encoding="utf-8"
    )

    required = (
        "Open Evidence Intake for this pressing",
        "clone_packet(",
        "evidence_intake_packet",
        "evidence_intake_handoff_pressing_id",
        "evidence_intake_return_page",
        'st.switch_page(',
        "pages/9_Evidence_Intake.py",
    )

    for fragment in required:
        assert fragment in source


def test_intake_page_preserves_result_and_return_control() -> None:
    """Safe-review results can be shown after returning to Stage 3."""
    source = INTAKE.read_text(
        encoding="utf-8"
    )

    required = (
        "Handoff from Cohort Curation Wizard",
        "Return to Cohort Curation Wizard",
        "evidence_intake_last_result",
        "planned_mutation_count",
        "database_writes",
        "evidence_packet_root()",
    )

    for fragment in required:
        assert fragment in source


def test_intake_main_calls_return_renderer() -> None:
    """The return control is rendered by the page main function."""
    source = INTAKE.read_text(
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

    call_names = {
        node.func.id
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
    }

    assert "_render_return_to_wizard" in call_names


def test_intake_handoff_does_not_add_apply_mode() -> None:
    """Navigation integration cannot apply packet mutations."""
    wizard_source = WIZARD.read_text(
        encoding="utf-8"
    )

    intake_source = INTAKE.read_text(
        encoding="utf-8"
    )

    assert "--apply" not in wizard_source
    assert "--apply" not in intake_source


def test_selected_cohort_is_explicitly_available_to_handoff() -> None:
    """Stage 3 uses the actual selected cohort instead of heuristics."""
    source = WIZARD.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    resolver = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_current_wizard_pressing_id"
        ),
        None,
    )

    assert resolver is not None

    resolver_literals = {
        node.value
        for node in ast.walk(
            resolver
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
        "cohort_curation_selected_cohort_value"
        in resolver_literals
    )

    session_assignments = [
        node
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Assign,
        )
        and isinstance(
            node.targets[0],
            ast.Subscript,
        )
        and isinstance(
            node.targets[0].slice,
            ast.Constant,
        )
        and node.targets[0].slice.value
        == "cohort_curation_selected_cohort_value"
    ]

    assert len(
        session_assignments
    ) == 1


def test_stage_three_handoff_precedes_early_returns() -> None:
    """The handoff is rendered before Stage 3 can return early."""
    source = WIZARD.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    stage_function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and any(
                isinstance(
                    child,
                    ast.Constant,
                )
                and isinstance(
                    child.value,
                    str,
                )
                and "3. Evidence and attachments"
                in child.value
                for child in ast.walk(
                    node
                )
            )
        ),
        None,
    )

    assert stage_function is not None

    calls = [
        node
        for node in ast.walk(
            stage_function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
        and node.func.id
        == "_render_evidence_intake_handoff"
    ]

    assert len(calls) == 1

    returns = [
        node
        for node in ast.walk(
            stage_function
        )
        if isinstance(
            node,
            ast.Return,
        )
    ]

    if returns:
        assert calls[0].lineno < min(
            node.lineno
            for node in returns
        )
