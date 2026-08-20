"""Database identity safety contracts for the live refresh runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_latest_auction_refresh.py"


def load_runner() -> ModuleType:
    """Load the refresh runner without executing its CLI."""
    spec = importlib.util.spec_from_file_location(
        "run_latest_auction_refresh_identity_test",
        MODULE_PATH,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def valid_state(
    *,
    database_name: str,
    database_user: str,
) -> dict[str, int | str]:
    """Return a state satisfying every non-identity invariant."""
    return {
        "database_name": database_name,
        "database_user": database_user,
        "total_rows": 1,
        "unique_rows": 1,
        "buyee_rows": 1,
        "ebay_rows": 0,
        "gripsweat_rows": 0,
        "collector_rows": 1,
        "effective_rows": 1,
        "review_rows": 1,
        "duplicate_groups": 0,
    }


def test_default_identity_preserves_local_production_guard() -> None:
    """Existing local execution remains restricted by default."""
    runner = load_runner()

    runner.verify_state(
        valid_state(
            database_name="auction_warehouse",
            database_user="auction",
        )
    )


def test_default_identity_rejects_neon_database() -> None:
    """Neon cannot bypass the local identity guard implicitly."""
    runner = load_runner()

    with pytest.raises(
        RuntimeError,
        match="Unexpected database name",
    ):
        runner.verify_state(
            valid_state(
                database_name="neondb",
                database_user="neondb_owner",
            )
        )


def test_explicit_neon_identity_is_allowed() -> None:
    """A validated staging deployment can authorize its exact identity."""
    runner = load_runner()

    runner.verify_state(
        valid_state(
            database_name="neondb",
            database_user="neondb_owner",
        ),
        expected_database_name="neondb",
        expected_database_user="neondb_owner",
    )


def test_identity_arguments_use_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent workers can forward explicit staging identity."""
    runner = load_runner()

    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "neondb",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "neondb_owner",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_latest_auction_refresh.py"],
    )

    arguments = runner.parse_arguments()

    assert arguments.expected_database_name == "neondb"
    assert arguments.expected_database_user == "neondb_owner"
