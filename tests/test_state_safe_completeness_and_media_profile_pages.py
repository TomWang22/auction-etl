"""Structural tests for the new pages and collector integration."""

from __future__ import annotations

import ast
from pathlib import Path


COMPLETENESS_PAGE = Path(
    "app/pages/10_Listing_Completeness_Review.py"
)

PROFILE_PAGE = Path(
    "app/pages/11_Media_Profile_Admin.py"
)

COLLECTOR_PAGE = Path(
    "app/collector_analytics_editor.py"
)


def test_listing_page_exposes_separate_deterministic_details() -> None:
    """Missing, unverified, contradiction, and damage remain separate."""
    source = COMPLETENESS_PAGE.read_text(
        encoding="utf-8"
    )

    required = (
        "Listing Completeness Review",
        "Required quantity shortfalls",
        "REQUIRED components lacking decisive observation",
        "Contradictory listing observations",
        "Explicit structured damage observations",
        "UNKNOWN and NOT_INCLUDED rows never add required units",
    )

    for fragment in required:
        assert fragment in source


def test_profile_page_is_configuration_not_evidence() -> None:
    """The profile page configures fields without creating claims."""
    source = PROFILE_PAGE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    semantic_text = " ".join(
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
    ).casefold()

    required_fragments = (
        "Media Profile Administration",
        "Preview media-profile changes",
        "Apply reviewed media profile",
        "Immutable media-profile audit history",
        "do not assert that any component is REQUIRED",
    )

    for fragment in required_fragments:
        assert (
            fragment.casefold()
            in semantic_text
        )

    assert (
        "pressing_component_expectation"
        not in source
    )


def test_collector_components_calls_state_safe_panel() -> None:
    """The existing collector review is connected."""
    source = COLLECTOR_PAGE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    definitions = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    assert (
        "_render_state_safe_master_comparison"
        in definitions
    )

    call_count = 0

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not isinstance(
            node.func,
            ast.Name,
        ):
            continue

        if (
            node.func.id
            == "_render_state_safe_master_comparison"
        ):
            call_count += 1

    assert call_count >= 1

    assert (
        "State-safe exact-pressing master comparison"
        in source
    )
