"""Normalization Workbench page tests."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/7_Normalization_Workbench.py"
)


def test_page_exposes_all_workflows() -> None:
    """The page supports references, bulk work, and reviews."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Normalization Workbench",
        "Prioritized normalization queue",
        "Pressing reference cohort",
        "Bulk condition normalization",
        "Bulk analysis and normalization factors",
        "Exact-pressing comparable review",
        "Normalization history",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_requires_reviewed_writes() -> None:
    """The interface does not auto-apply inferred values."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "apply=TRUE",
        "I reviewed this preview",
        "Apply approved batch",
        "No language model assigns",
        "does not invent expected components",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_has_complete_entry_point() -> None:
    """The Streamlit page has full render functions."""
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
        "_render_queue",
        "_render_reference_cohort",
        "_render_bulk_editor",
        "_render_comparable_review",
        "_render_history",
    }

    assert required_functions <= function_names
