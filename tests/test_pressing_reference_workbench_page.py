"""General pressing-reference workbench page tests."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/2_Completeness_Reference.py"
)


def test_page_has_general_workbench_tabs() -> None:
    """The page is not tied to one catalog number."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Pressing Reference Workbench",
        "Reference library",
        "Create pressing",
        "Completeness worksheet",
        "CSV and cloning",
        "Listing verdicts",
    )

    for fragment in required_fragments:
        assert fragment in source

    assert "MR2276" not in source


def test_page_supports_reference_transfer() -> None:
    """CSV import, export, and cloning are wired."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_calls = (
        "reference_csv_bytes(",
        "parse_reference_csv(",
        "import_reference_csv(",
        "clone_reference(",
    )

    for required_call in required_calls:
        assert required_call in source

    assert "Draft — force review" in source
    assert "Verified exact copy" in source


def test_page_exposes_deterministic_percentages() -> None:
    """Arithmetic scores and verdicts are visible."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Structural completeness %",
        "Damage-adjusted %",
        "No AI inference is used.",
        "structural_completeness_percent",
        "verification_percent",
        "condition_coverage_percent",
        "damage_adjusted_percent",
        "damage_penalty_percent",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_exposes_existing_collector_verdicts() -> None:
    """Existing analytics remain available in one panel."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Plushie / auction scores",
        "Emotional Damage",
        "Alerts",
        "Midfication",
        "Completeness premium",
        "Obi analytics",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_preserves_reference_and_observation_scope() -> None:
    """Shared expectations never become listing observations."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "Listing observations remain separate."
        in source
    )
    assert "save_reference_rows(" in source
    assert (
        "save_listing_observation_rows("
        not in source
    )


def test_page_compiles_structurally() -> None:
    """All workbench panels are full functions."""
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
        "_create_pressing_panel",
        "_reference_library_panel",
        "_worksheet_panel",
        "_transfer_panel",
        "_verdict_panel",
        "main",
    }

    assert required_functions <= function_names
