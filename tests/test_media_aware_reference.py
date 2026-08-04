"""Tests for the canonical media-aware reference service."""

from __future__ import annotations

import ast
import inspect

from auction_etl.services import media_aware_reference
from auction_etl.services.media_aware_reference import (
    ASSERTED_STATES,
    MEDIA_GROUPS,
    REFERENCE_ACTIONS,
    REFERENCE_STATES,
    apply_reference_changes,
    group_for_component,
    preview_reference_changes,
)


def test_reference_semantics_are_explicit() -> None:
    """Master states remain distinct and deterministic."""
    assert REFERENCE_ACTIONS == (
        "NO_CHANGE",
        "UPSERT",
        "DELETE",
    )

    assert REFERENCE_STATES == (
        "UNKNOWN",
        "REQUIRED",
        "NOT_INCLUDED",
    )

    assert ASSERTED_STATES == frozenset(
        {
            "REQUIRED",
            "NOT_INCLUDED",
        }
    )


def test_professional_media_groups_cover_all_profiles() -> None:
    """Every supported media profile has a tailored grouping."""
    assert {
        "LP",
        "CASSETTE",
        "CD",
        "CD_BOX_SET",
        "EP_7_INCH",
        "SINGLE_12_INCH",
        "LD",
        "DVD",
    } <= set(
        MEDIA_GROUPS
    )

    assert group_for_component(
        "LP",
        "OBI",
    ) == "Identity and packaging"

    assert group_for_component(
        "CASSETTE",
        "J_CARD",
    ) == "Primary packaging"

    assert group_for_component(
        "CD",
        "BOOKLET",
    ) == "Printed matter"


def test_profile_is_driven_by_database_applicability() -> None:
    """The service does not hardcode one universal worksheet."""
    source = inspect.getsource(
        media_aware_reference._profile_components
    )

    tree = ast.parse(
        source
    )

    literals = {
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
        "system.component_type"
        in literal
        for literal in literals
    )

    assert any(
        "applicable_media"
        in literal
        for literal in literals
    )


def test_preview_and_apply_are_separate_public_functions() -> None:
    """Mutation preview cannot silently become an apply."""
    preview_source = inspect.getsource(
        preview_reference_changes
    )

    apply_source = inspect.getsource(
        apply_reference_changes
    )

    assert "SERIALIZABLE" not in preview_source
    assert "SERIALIZABLE" in apply_source
    assert "confirmation_token" in apply_source
    assert "scope_confirmed" in apply_source
    assert "set_config" in apply_source


def test_apply_recomputes_preview_inside_transaction() -> None:
    """Confirmation tokens cannot apply stale client plans."""
    source = inspect.getsource(
        apply_reference_changes
    )

    tree = ast.parse(
        source
    )

    call_names = {
        node.func.id
        for node in ast.walk(
            tree
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

    assert "_preview_with_connection" in call_names

# nonrequired-quantity-storage-regression:start
def test_nonrequired_quantity_is_semantically_blank() -> None:
    """UNKNOWN and NOT_INCLUDED never expose storage quantities."""
    unknown = {
        "id": 1,
        "component_code": "LYRIC_SHEET",
        "variant_key": "",
        "variant_label": "Lyric card",
        "expectation_state": "UNKNOWN",
        "expected_quantity": 1,
        "evidence_source": None,
        "confidence": None,
        "notes": "Unresolved.",
    }

    projected = (
        media_aware_reference._current_projection(
            unknown
        )
    )

    editor_row = (
        media_aware_reference._editor_row_from_current(
            unknown,
            display_name="Lyric sheet",
            applicable=True,
            group="Printed matter",
        )
    )

    assert projected["expected_quantity"] is None
    assert editor_row["expected_quantity"] is None


def test_legacy_storage_quantity_satisfies_not_null_schema() -> None:
    """Non-required rows use an internal ignored storage sentinel."""
    base = {
        "component_code": "LYRIC_SHEET",
        "variant_key": "",
        "variant_label": "Lyric card",
        "expected_quantity": None,
        "evidence_source": None,
        "confidence": None,
        "notes": "Reviewed state.",
    }

    unknown_payload = (
        media_aware_reference._insert_payload(
            1,
            {
                **base,
                "expectation_state": "UNKNOWN",
            },
        )
    )

    absent_payload = (
        media_aware_reference._insert_payload(
            1,
            {
                **base,
                "expectation_state": "NOT_INCLUDED",
            },
        )
    )

    required_payload = (
        media_aware_reference._insert_payload(
            1,
            {
                **base,
                "expectation_state": "REQUIRED",
                "expected_quantity": 2,
            },
        )
    )

    assert unknown_payload["expected_quantity"] == 1
    assert absent_payload["expected_quantity"] == 1
    assert required_payload["expected_quantity"] == 2


def test_required_storage_quantity_cannot_be_blank() -> None:
    """A REQUIRED reference still needs a real reviewed quantity."""
    try:
        media_aware_reference._insert_payload(
            1,
            {
                "component_code": "LYRIC_SHEET",
                "variant_key": "",
                "variant_label": None,
                "expectation_state": "REQUIRED",
                "expected_quantity": None,
                "evidence_source": "CATALOG_SCAN",
                "confidence": "0.9900",
                "notes": None,
            },
        )
    except ValueError as error:
        assert "positive quantity" in str(
            error
        )
    else:
        raise AssertionError(
            "A blank REQUIRED quantity was accepted."
        )
# nonrequired-quantity-storage-regression:end
