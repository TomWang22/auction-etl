"""Regression tests for Phase-D legacy relation classification."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
OWNER_BACKFILL = ROOT / "scripts" / "phase_d_owner_backfill.py"


def load_owner_backfill() -> ModuleType:
    """Load the owner-backfill implementation without invoking main()."""
    specification = importlib.util.spec_from_file_location(
        "phase_d_owner_backfill_relation_test",
        OWNER_BACKFILL,
    )

    if specification is None or specification.loader is None:
        raise AssertionError(
            "Could not load phase_d_owner_backfill.py."
        )

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    return module


def test_view_is_not_directly_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Derived views must not be treated as account-owned tables."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "v",
    )

    def unexpected_account_column_check(
        connection: object,
        relation: str,
    ) -> bool:
        raise AssertionError(
            "A view must not require an account_id column."
        )

    monkeypatch.setattr(
        module,
        "has_account_column",
        unexpected_account_column_check,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "system.new_auction_assignment_queue",
        )
        is False
    )


def test_materialized_view_is_not_directly_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Materialized views are also derived rather than updated in-place."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "m",
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "system.example_materialized_view",
        )
        is False
    )


def test_real_table_with_account_id_is_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Phase-D table with account_id remains directly backfilled."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "r",
    )
    monkeypatch.setattr(
        module,
        "has_account_column",
        lambda connection, relation: True,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "warehouse.auction_collector",
        )
        is True
    )


def test_partitioned_table_with_account_id_is_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partitioned tables follow the same Phase-D ownership contract."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "p",
    )
    monkeypatch.setattr(
        module,
        "has_account_column",
        lambda connection, relation: True,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "warehouse.example_partitioned_table",
        )
        is True
    )


def test_real_table_missing_account_id_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping views must never hide an actual migration gap."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "r",
    )
    monkeypatch.setattr(
        module,
        "has_account_column",
        lambda connection, relation: False,
    )

    with pytest.raises(
        RuntimeError,
        match="D1 account_id column missing",
    ):
        module.should_backfill_account_relation(
            object(),
            "warehouse.auction_collector",
        )


def test_missing_optional_relation_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent legacy relations remain optional across older snapshots."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: None,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "system.optional_legacy_relation",
        )
        is False
    )


def test_unknown_relation_kind_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected PostgreSQL relation types require explicit review."""
    module = load_owner_backfill()

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation: "f",
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported Phase D legacy relation type",
    ):
        module.should_backfill_account_relation(
            object(),
            "system.unexpected_relation",
        )

def test_immutable_audit_relation_is_not_directly_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable audit history must never be rewritten by owner backfill."""
    module = load_owner_backfill()

    assert (
        "system.auction_pressing_assignment_audit_event"
        in module.IMMUTABLE_LEGACY_ACCOUNT_RELATIONS
    )

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation_name: "r",
    )

    def unexpected_account_column_check(
        connection: object,
        relation_name: str,
    ) -> bool:
        raise AssertionError(
            "Immutable audit relations must be skipped before "
            "account-column mutation checks."
        )

    monkeypatch.setattr(
        module,
        "has_account_column",
        unexpected_account_column_check,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "system.auction_pressing_assignment_audit_event",
        )
        is False
    )

def test_completeness_snapshot_is_not_directly_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable completeness history must never be rewritten."""
    module = load_owner_backfill()

    assert (
        "system.listing_completeness_snapshot"
        in module.IMMUTABLE_LEGACY_ACCOUNT_RELATIONS
    )

    monkeypatch.setattr(
        module,
        "relation_kind",
        lambda connection, relation_name: "r",
    )

    def unexpected_account_column_check(
        connection: object,
        relation_name: str,
    ) -> bool:
        raise AssertionError(
            "Immutable completeness snapshots must be skipped "
            "before account-column mutation checks."
        )

    monkeypatch.setattr(
        module,
        "has_account_column",
        unexpected_account_column_check,
    )

    assert (
        module.should_backfill_account_relation(
            object(),
            "system.listing_completeness_snapshot",
        )
        is False
    )
