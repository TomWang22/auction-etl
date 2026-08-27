"""Regression tests for strict all-source refresh mode."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"


def runner_source() -> str:
    """Return syntactically valid runner source."""
    source = RUNNER.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(RUNNER),
    )

    return source


def test_runner_exposes_require_all_sources() -> None:
    """Expose a strict final acceptance mode."""
    assert (
        '"--require-all-sources"'
        in runner_source()
    )


def test_strict_mode_rejects_unavailable_buyee() -> None:
    """Do not call a final run successful without Buyee."""
    assert (
        "Required source Buyee is unavailable"
        in runner_source()
    )


def test_strict_mode_rejects_unavailable_ebay() -> None:
    """Do not call a final run successful without eBay."""
    assert (
        "Required source eBay is unavailable"
        in runner_source()
    )


def test_degraded_mode_is_still_present() -> None:
    """Preserve normal partial-source refresh behavior."""
    source = runner_source()

    assert (
        "Continuing eBay and Gripsweat refreshes."
        in source
    )
    assert (
        "Continuing Gripsweat refresh."
        in source
    )
