"""Eleven-stage Cohort Curation Wizard page tests."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/8_Cohort_Curation_Wizard.py"
)


def test_page_exposes_all_eleven_stages() -> None:
    """The wizard presents every requested workflow stage."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "1. Exact pressing identity",
        "2. Assigned listings",
        "3. Evidence and attachments",
        "4. Shared completeness reference",
        "5. Listing component observations",
        "6. Condition normalization",
        "7. Analysis and market factors",
        "8. Exact-pressing comparable review",
        "9. Normalization readiness",
        "10. Eleven deterministic verdicts",
        "11. Audit and final report",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_keeps_workflow_on_one_page() -> None:
    """All eleven stages are implemented by local render functions."""
    tree = ast.parse(
        PAGE.read_text(
            encoding="utf-8"
        )
    )

    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    required_functions = {
        "main",
        "_stage_one",
        "_stage_two",
        "_stage_three",
        "_stage_four",
        "_stage_five",
        "_stage_six",
        "_stage_seven",
        "_stage_eight",
        "_stage_nine",
        "_stage_ten",
        "_stage_eleven",
        "_render_navigation",
    }

    assert required_functions <= function_names


def test_page_requires_reviewed_persistence() -> None:
    """Persistent changes require explicit user approval."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "I reviewed these shared pressing-reference changes.",
        "I reviewed these listing-only observations.",
        "I reviewed the preview and approve this atomic write.",
        "Apply reviewed reference changes",
        "Apply reviewed observation changes",
        "Apply approved cohort batch",
        "Save changed comparable decisions",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_evaluates_professional_baseline_rules() -> None:
    """The verdict stage is formal and deterministic."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "BASELINE_RULE_CODES" in source
    assert "Professional baseline rules" in source
    assert "Triggered professional verdicts" in source
    assert (
        "No professional baseline verdict"
        in source
    )


def test_page_rejects_ai_assigned_curation() -> None:
    """The page explains that stored decisions remain reviewed."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "No language model assigns component requirements"
        in source
    )
