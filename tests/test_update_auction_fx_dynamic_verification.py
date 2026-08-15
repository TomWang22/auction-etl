"""Regression tests for dynamic auction FX verification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[
    1
]

FX_SCRIPT = (
    REPOSITORY_ROOT
    / "scripts"
    / "update_auction_fx.py"
)


def load_fx_module() -> Any:
    """Load the FX script without executing its CLI entry point."""

    spec = importlib.util.spec_from_file_location(
        "update_auction_fx_under_test",
        FX_SCRIPT,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RuntimeError(
            f"Could not load {FX_SCRIPT}."
        )

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[
        spec.name
    ] = module

    spec.loader.exec_module(
        module
    )

    return module


class FakeMappingsResult:
    """Provide the subset of SQLAlchemy result behavior used by the verifier."""

    def __init__(
        self,
        *,
        one_row: dict[str, object] | None = None,
        all_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self._one_row = one_row
        self._all_rows = all_rows

    def mappings(
        self,
    ) -> FakeMappingsResult:
        """Return this fake mapping result."""

        return self

    def one(
        self,
    ) -> dict[str, object]:
        """Return the configured single row."""

        if self._one_row is None:
            raise AssertionError(
                "No one-row result was configured."
            )

        return self._one_row

    def all(
        self,
    ) -> list[dict[str, object]]:
        """Return the configured row collection."""

        if self._all_rows is None:
            raise AssertionError(
                "No all-rows result was configured."
            )

        return self._all_rows


class FakeConnection:
    """Return deterministic query results without opening a database."""

    def __init__(
        self,
        *,
        totals: dict[str, object],
        marketplace_rows: list[dict[str, object]],
    ) -> None:
        self._results = [
            FakeMappingsResult(
                one_row=totals,
            ),
            FakeMappingsResult(
                all_rows=marketplace_rows,
            ),
        ]

    def execute(
        self,
        _statement: object,
    ) -> FakeMappingsResult:
        """Return the next configured fake result."""

        if not self._results:
            raise AssertionError(
                "verify_results() executed an unexpected query."
            )

        return self._results.pop(
            0
        )


def marketplace_row(
    marketplace: str,
    rows: int,
    *,
    fx_rates: int | None = None,
    final_prices_usd: int | None = None,
    gross_prices_usd: int | None = None,
    current_prices_usd: int = 0,
) -> dict[str, object]:
    """Build one marketplace coverage row."""

    return {
        "marketplace":
            marketplace,
        "rows":
            rows,
        "fx_rates":
            rows
            if fx_rates is None
            else fx_rates,
        "final_prices_usd":
            rows
            if final_prices_usd is None
            else final_prices_usd,
        "gross_prices_usd":
            rows
            if gross_prices_usd is None
            else gross_prices_usd,
        "current_prices_usd":
            current_prices_usd,
    }


def test_verify_results_accepts_dynamic_marketplace_row_counts() -> None:
    """Allow valid current row counts instead of historical 77/698 counts."""

    module = load_fx_module()

    connection = FakeConnection(
        totals={
            "total_rows":
                854,
            "unique_rows":
                854,
        },
        marketplace_rows=[
            marketplace_row(
                "buyee",
                138,
            ),
            marketplace_row(
                "ebay",
                716,
            ),
        ],
    )

    module.verify_results(
        connection
    )


def test_verify_results_rejects_incomplete_dynamic_fx_coverage() -> None:
    """Require conversion coverage to match the marketplace's own row count."""

    module = load_fx_module()

    connection = FakeConnection(
        totals={
            "total_rows":
                854,
            "unique_rows":
                854,
        },
        marketplace_rows=[
            marketplace_row(
                "buyee",
                138,
                fx_rates=137,
            ),
            marketplace_row(
                "ebay",
                716,
            ),
        ],
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"buyee: expected 138 fx_rates; "
            r"found 137\."
        ),
    ):
        module.verify_results(
            connection
        )


def test_verify_results_requires_each_expected_marketplace() -> None:
    """Reject a table that completely loses an expected marketplace."""

    module = load_fx_module()

    connection = FakeConnection(
        totals={
            "total_rows":
                716,
            "unique_rows":
                716,
        },
        marketplace_rows=[
            marketplace_row(
                "ebay",
                716,
            ),
        ],
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"Expected non-empty buyee marketplace data; "
            r"found no rows\."
        ),
    ):
        module.verify_results(
            connection
        )
