"""Database identity contracts for the auction FX updater."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "update_auction_fx.py"


class FakeResult:
    """Minimal SQLAlchemy result used by identity tests."""

    def __init__(
        self,
        row: dict[str, str],
    ) -> None:
        self.row = row

    def mappings(self) -> FakeResult:
        return self

    def one(self) -> dict[str, str]:
        return self.row


class FakeConnection:
    """Minimal connection exposing the identity query contract."""

    def __init__(
        self,
        *,
        database_name: str,
        database_user: str,
    ) -> None:
        self.row = {
            "database_name": database_name,
            "database_user": database_user,
        }

    def execute(
        self,
        _statement: object,
    ) -> FakeResult:
        return FakeResult(self.row)


def load_module() -> ModuleType:
    """Load the FX updater without executing its CLI."""
    spec = importlib.util.spec_from_file_location(
        "update_auction_fx_staging_identity_test",
        MODULE_PATH,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)

    # dataclasses resolves postponed annotations through sys.modules.
    sys.modules[spec.name] = module

    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise

    return module


def test_default_identity_preserves_local_guard() -> None:
    """The existing local database remains the safe default."""
    module = load_module()

    module.verify_database(
        FakeConnection(
            database_name="auction_warehouse",
            database_user="auction",
        )
    )


def test_default_identity_rejects_neon() -> None:
    """Neon must never be accepted without explicit authorization."""
    module = load_module()

    with pytest.raises(
        RuntimeError,
        match="Refusing to update database",
    ):
        module.verify_database(
            FakeConnection(
                database_name="neondb",
                database_user="neondb_owner",
            )
        )


def test_explicit_neon_identity_is_allowed() -> None:
    """Validated staging can authorize its exact database identity."""
    module = load_module()

    module.verify_database(
        FakeConnection(
            database_name="neondb",
            database_user="neondb_owner",
        ),
        expected_database_name="neondb",
        expected_database_user="neondb_owner",
    )


def test_explicit_identity_rejects_wrong_user() -> None:
    """Database name alone is insufficient authorization."""
    module = load_module()

    with pytest.raises(
        RuntimeError,
        match="Refusing to update as database user",
    ):
        module.verify_database(
            FakeConnection(
                database_name="neondb",
                database_user="unexpected_owner",
            ),
            expected_database_name="neondb",
            expected_database_user="neondb_owner",
        )


def test_identity_arguments_follow_worker_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker environment propagates the staging identity."""
    module = load_module()

    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "neondb",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "neondb_owner",
    )

    arguments = module.parse_arguments([])

    assert arguments.expected_database_name == "neondb"
    assert arguments.expected_database_user == "neondb_owner"
