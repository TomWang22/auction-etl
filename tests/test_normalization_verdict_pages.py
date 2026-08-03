"""Normalization and verdict Streamlit page tests."""

from __future__ import annotations

import ast
from pathlib import Path


READINESS_PAGE = Path(
    "app/pages/5_Normalization_Readiness.py"
)

VERDICT_PAGE = Path(
    "app/pages/6_Deterministic_Verdict_Rules.py"
)


def test_readiness_page_has_real_dashboard_sections() -> None:
    """The page exposes readiness, components, factors, and blockers."""
    source = READINESS_PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Normalization Readiness",
        "Structural completeness",
        "Readiness gates",
        "Component calculation",
        "Normalization factors",
        "Explicit blockers",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_verdict_page_uses_professional_terms() -> None:
    """The formal UI exposes professional market terminology."""
    source = VERDICT_PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Reissue Price Convergence",
        "First-Press Price Parity",
        "Reissue Price Crossover",
        "Persistent Reissue Displacement",
        "Market Noise",
        "Auction Impact",
        "Collector Significance Index",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_pages_have_complete_render_functions() -> None:
    """Both pages provide complete entry points."""
    readiness_tree = ast.parse(
        READINESS_PAGE.read_text(
            encoding="utf-8"
        )
    )

    verdict_tree = ast.parse(
        VERDICT_PAGE.read_text(
            encoding="utf-8"
        )
    )

    readiness_names = {
        node.name
        for node in readiness_tree.body
        if isinstance(node, ast.FunctionDef)
    }

    verdict_names = {
        node.name
        for node in verdict_tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert "main" in readiness_names
    assert "main" in verdict_names

    assert {
        "_render_rule_library",
        "_render_rule_editor",
        "_render_evaluation",
        "_render_audit",
    } <= verdict_names


def test_verdict_page_rejects_ai_assignment() -> None:
    """The UI states that rules are deterministic."""
    source = VERDICT_PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "No language model assigns these verdicts."
        in source
    )
