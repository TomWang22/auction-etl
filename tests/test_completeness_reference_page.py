"""Pressing completeness-reference page contracts."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/2_Completeness_Reference.py"
)


def test_reference_page_compiles_and_has_three_workflows() -> None:
    """Creation, reference editing, and previews are separate."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert "_render_create_pressing" in function_names
    assert "_render_reference_editor" in function_names
    assert "_render_assigned_listings" in function_names


def test_reference_page_exposes_detailed_component_fields() -> None:
    """The editor supports collector-grade component metadata."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Pressing Completeness Reference",
        "Create an exact pressing",
        "Pressing completeness reference",
        "Assigned listings and derived completeness",
        "component_code",
        "variant_key",
        "variant_label",
        "expectation_state",
        "expected_quantity",
        "evidence_source",
        "confidence",
        "notes",
        "Save verified pressing reference",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_reference_page_preserves_scope_separation() -> None:
    """Shared references are not listing observations."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "Listing observations remain separate."
        in source
    )
    assert (
        "save_reference_rows("
        in source
    )
    assert (
        "auction_component_observation"
        not in source
    )


def test_reference_page_supports_discogs_style_variants() -> None:
    """A component can carry edition-specific variant metadata."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "PINK_OBI" in source
    assert "FACTORY_SEALED" in source
    assert 'num_rows="dynamic"' in source
