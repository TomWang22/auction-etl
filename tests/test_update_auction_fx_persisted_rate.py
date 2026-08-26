"""Regression tests for cloud-safe persisted FX lookup."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update_auction_fx.py"


def load_module() -> Any:
    """Load the standalone FX script as a registered module."""
    module_name = (
        "update_auction_fx_persisted_rate_test"
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        SCRIPT,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to load {SCRIPT}."
        )

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[
        module_name
    ] = module

    try:
        spec.loader.exec_module(
            module
        )
    except Exception:
        sys.modules.pop(
            module_name,
            None,
        )
        raise

    return module


class FakeMappingsResult:
    """Minimal SQLAlchemy mappings result used by the loader."""

    def __init__(
        self,
        row: dict[str, object] | None,
    ) -> None:
        self._row = row

    def mappings(
        self,
    ) -> "FakeMappingsResult":
        return self

    def one_or_none(
        self,
    ) -> dict[str, object] | None:
        return self._row


class FakeConnection:
    """Return one persisted FX observation."""

    def __init__(
        self,
        row: dict[str, object] | None,
    ) -> None:
        self._row = row
        self.sql = ""

    def execute(
        self,
        statement: object,
    ) -> FakeMappingsResult:
        self.sql = str(
            statement
        )
        return FakeMappingsResult(
            self._row
        )


def test_load_persisted_rate_uses_warehouse() -> None:
    """Railway can reuse a rate already present in PostgreSQL."""
    module = load_module()
    connection = FakeConnection(
        {
            "fx_rate_to_usd":
                Decimal("0.00681234"),
            "fx_rate_date":
                date(2026, 8, 25),
            "usage_count":
                242,
        }
    )

    rate = module.load_persisted_rate(
        connection
    )

    assert rate is not None
    assert rate.rate == Decimal(
        "0.00681234"
    )
    assert rate.rate_date == date(
        2026,
        8,
        25,
    )
    assert rate.source == "warehouse.auction"
    assert "warehouse.auction" in connection.sql
    assert "fx_rate_to_usd > 0" in connection.sql


def test_load_persisted_rate_allows_empty_database() -> None:
    """An empty database falls through to the retained CSV path."""
    module = load_module()

    assert (
        module.load_persisted_rate(
            FakeConnection(
                None
            )
        )
        is None
    )
