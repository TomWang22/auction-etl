"""Post-refresh warehouse counts must never decrease, and exact eBay pages parse."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_latest_auction_refresh as refresh
from scripts.run_ebay_external_handoff import (
    parse_raw_page_id,
)


def warehouse_state(
    *,
    total_rows: int,
    buyee_rows: int,
    ebay_rows: int,
    gripsweat_rows: int,
) -> dict[str, int | str]:
    """Return protected warehouse counts for invariant checks."""

    return {
        "total_rows": total_rows,
        "buyee_rows": buyee_rows,
        "ebay_rows": ebay_rows,
        "gripsweat_rows": gripsweat_rows,
    }


def test_warehouse_counts_may_stay_or_increase() -> None:
    """Equal or larger marketplace counts are accepted after refresh."""

    refresh.reject_decreased_warehouse_counts(
        warehouse_state(
            total_rows=1226,
            buyee_rows=350,
            ebay_rows=876,
            gripsweat_rows=20,
        ),
        warehouse_state(
            total_rows=1246,
            buyee_rows=367,
            ebay_rows=879,
            gripsweat_rows=22,
        ),
    )


def test_warehouse_counts_reject_any_decrease() -> None:
    """A drop in any protected marketplace count fails the refresh."""

    baseline = warehouse_state(
        total_rows=1226,
        buyee_rows=350,
        ebay_rows=876,
        gripsweat_rows=20,
    )

    with pytest.raises(
        RuntimeError,
        match="Warehouse row count decreased.",
    ):
        refresh.reject_decreased_warehouse_counts(
            baseline,
            warehouse_state(
                total_rows=1225,
                buyee_rows=350,
                ebay_rows=876,
                gripsweat_rows=20,
            ),
        )

    with pytest.raises(
        RuntimeError,
        match="Buyee warehouse rows decreased.",
    ):
        refresh.reject_decreased_warehouse_counts(
            baseline,
            warehouse_state(
                total_rows=1226,
                buyee_rows=349,
                ebay_rows=876,
                gripsweat_rows=20,
            ),
        )

    with pytest.raises(
        RuntimeError,
        match="eBay warehouse rows decreased.",
    ):
        refresh.reject_decreased_warehouse_counts(
            baseline,
            warehouse_state(
                total_rows=1226,
                buyee_rows=350,
                ebay_rows=875,
                gripsweat_rows=20,
            ),
        )

    with pytest.raises(
        RuntimeError,
        match="Gripsweat warehouse rows decreased.",
    ):
        refresh.reject_decreased_warehouse_counts(
            baseline,
            warehouse_state(
                total_rows=1226,
                buyee_rows=350,
                ebay_rows=876,
                gripsweat_rows=19,
            ),
        )


def test_refresh_runner_uses_non_decreasing_count_guard() -> None:
    """The live runner must apply the count guard after the final snapshot."""

    source = inspect.getsource(refresh.main)

    assert "reject_decreased_warehouse_counts(" in source
    assert source.index("final_state = database_state(") < source.index(
        "reject_decreased_warehouse_counts("
    )


def test_importer_emits_one_exact_raw_page_id() -> None:
    """Handoff parsing accepts only the importer's exact raw-page line."""

    assert (
        refresh.parse_structured_ebay_raw_page_id(
            "✓ Raw Page       : 176\n"
        )
        == 176
    )
    assert parse_raw_page_id("✓ Raw Page       : 176\n") == 176

    with pytest.raises(
        RuntimeError,
        match="exactly one raw-page ID",
    ):
        refresh.parse_structured_ebay_raw_page_id(
            "✓ Raw Page       : 176\n"
            "✓ Raw Page       : 177\n"
        )


def test_exact_structured_raw_page_must_be_importer_owned() -> None:
    """Refresh by ID only proceeds for collector://ebay importer pages."""

    row = {
        "id": 176,
        "source": "ebay",
        "url": "collector://ebay/structured/176",
    }

    class Result:
        def fetchone(self) -> dict[str, object]:
            return row

    connection = SimpleNamespace(
        execute=lambda query, params: Result()
    )
    refresh.require_structured_ebay_raw_page(connection, 176)

    row["url"] = "https://www.ebay.com/sch/i.html"
    with pytest.raises(
        RuntimeError,
        match="collector://ebay/",
    ):
        refresh.require_structured_ebay_raw_page(connection, 176)


def test_exact_raw_page_handoff_parses_that_page_not_latest() -> None:
    """Exact-ID refresh must parse the importer page, not all eBay pages."""

    source = inspect.getsource(refresh.process_ebay_raw_pages)

    assert '"parse",' in source
    assert '"page",' in source
    assert "str(raw_page_id)" in source
    assert '"parse",\n            "latest"' not in source
    assert '"parse",\n            "source",\n            "ebay"' in source


def test_external_handoff_operator_requires_parsed_page_and_stable_rows() -> None:
    """Apply/refresh must prove the exact page parsed and eBay rows did not drop."""

    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_ebay_external_handoff.py"
    ).read_text(encoding="utf-8")

    assert "EXACT_STRUCTURED_RAW_PAGE_PARSED=true" in source
    assert "Exact structured eBay raw page was not marked parsed." in source
    assert "eBay warehouse row count decreased." in source
    assert "--ebay-structured-raw-page-id" in source
    assert "verify_no_ebay_browser_fallback(" in source
    assert "EBAY_BROWSER_FALLBACK_PROHIBITED=true" in source
