"""Structural tests for the general Evidence Intake page."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/9_Evidence_Intake.py"
)


def test_page_is_general_and_compiles() -> None:
    """The page supports every exact pressing."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    ast.parse(
        source
    )

    assert "Exact-Pressing Evidence Intake" in source
    assert "MR2276" not in source
    assert "discover_packets(" in source
    assert "clone_packet(" in source
    assert "store_uploaded_evidence(" in source
    assert "stage_and_review(" in source


def test_page_never_applies_postgresql_mutations() -> None:
    """Evidence Intake stages packets but cannot invoke apply mode."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "--apply" not in source
    assert "confirmation_token" not in source
    assert "Database writes" in source

    tree = ast.parse(
        source
    )

    string_literals = {
        node.value
        for node in ast.walk(
            tree
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

    assert any(
        "never applies PostgreSQL mutations"
        in value
        for value in string_literals
    )


def test_page_requires_exact_pressing_confirmation() -> None:
    """Shared references require explicit scope confirmation."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "I verified that this evidence documents"
        in source
    )

    assert (
        "not merely one listing"
        in source
    )

    assert (
        "Unsupported components remain UNKNOWN"
        in source
    )
