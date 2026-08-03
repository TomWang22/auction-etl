"""Evidence registry and bulk observation page tests."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/3_Evidence_and_Bulk_Observations.py"
)


def test_page_has_two_general_workflows() -> None:
    """Registry and bulk import are independent workflows."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "Evidence-source registry" in source
    assert "Bulk observations" in source
    assert "MR2276" not in source


def test_page_requires_preview_and_confirmation() -> None:
    """Bulk imports cannot bypass review."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "preview_bulk_observations(",
        "existing_conflicts",
        "overwrite",
        "I reviewed the parsed observations",
        "Apply bulk observations atomically",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_exposes_registry_crud() -> None:
    """Evidence sources can be reused and disabled."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "save_evidence_source(" in source
    assert "set_evidence_source_active(" in source
    assert "Default confidence" in source


def test_page_compiles_structurally() -> None:
    """The page uses full rendering functions."""
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

    assert "_render_registry" in function_names
    assert "_render_bulk_import" in function_names
    assert "main" in function_names
