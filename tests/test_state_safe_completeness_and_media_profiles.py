"""Tests for state-safe completeness and media profiles."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from auction_etl.services import media_aware_reference
from auction_etl.services.media_profile_admin import (
    apply_profile_changes,
    preview_profile_changes,
)
from auction_etl.services.state_safe_completeness import (
    ABSENT_STATES,
    PRESENT_STATES,
    VALID_STATUSES,
    evaluate_listing,
)


MIGRATION_UP = Path(
    "alembic/versions/"
    "f9d6a2c4e781_media_profiles_and_state_safe_completeness_up.sql"
)


def test_migration_installs_authoritative_profile_registry() -> None:
    """The registry and immutable audit history are installed."""
    source = MIGRATION_UP.read_text(
        encoding="utf-8"
    )

    required = (
        "system.media_profile_component",
        "system.media_profile_audit_event",
        "capture_media_profile_audit",
        "media_profile_component_audit",
        "applicable_media",
        "interface configuration, not collector evidence",
    )

    for fragment in required:
        assert fragment in source


def test_state_safe_evaluation_has_professional_statuses() -> None:
    """Listing evaluation exposes every required state."""
    assert {
        "COMPLETE",
        "INCOMPLETE",
        "INSUFFICIENT_OBSERVATION",
        "NO_VERIFIED_REFERENCE",
        "NO_PRESSING_ASSIGNMENT",
        "FACTORY_SEALED_EXCEPTION",
    } <= VALID_STATUSES

    assert "PRESENT" in PRESENT_STATES
    assert "ABSENT" in ABSENT_STATES


def test_only_required_master_rows_enter_arithmetic() -> None:
    """The evaluator filters by REQUIRED before quantity use."""
    source = inspect.getsource(
        evaluate_listing
    )

    assert (
        '== "REQUIRED"'
        in source
    )

    assert (
        "required_rows"
        in source
    )

    assert (
        "ignored_reference_rows"
        in source
    )


def test_profile_admin_uses_two_phase_serializable_apply() -> None:
    """Profile configuration has separate preview and apply."""
    preview_source = inspect.getsource(
        preview_profile_changes
    )

    apply_source = inspect.getsource(
        apply_profile_changes
    )

    assert "SERIALIZABLE" not in preview_source
    assert "SERIALIZABLE" in apply_source
    assert "confirmation_token" in apply_source
    assert "_preview_with_connection" in apply_source
    assert "set_config" in apply_source


def test_master_reference_reads_authoritative_registry() -> None:
    """The canonical reference service uses the new profile table."""
    source = inspect.getsource(
        media_aware_reference._profile_components
    )

    assert (
        "system.media_profile_component"
        in source
    )

    assert (
        "profile.field_group"
        in source
    )

    assert (
        "profile.sort_order"
        in source
    )


def test_no_state_safe_service_writes_observations() -> None:
    """Listing evaluation remains read-only."""
    source = inspect.getsource(
        evaluate_listing
    )

    tree = ast.parse(
        source
    )

    called_attributes = {
        node.func.attr
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
    }

    assert "insert" not in called_attributes
    assert "update" not in called_attributes
    assert "delete" not in called_attributes
