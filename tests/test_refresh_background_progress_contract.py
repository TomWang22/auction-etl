"""Production contracts for background refresh execution."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

OWNER = ROOT / "scripts" / "run_buyee_owner.py"
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"
CRAWLER = ROOT / "scripts" / "crawl_buyee_live_details.py"
UI = ROOT / "app" / "pages" / "3_Latest_Auction_Refresh.py"


def source(
    path: Path,
) -> str:
    """Read one repository source file."""

    return path.read_text(
        encoding="utf-8",
    )


def function_block(
    path: Path,
    name: str,
) -> str:
    """Return one top-level function source block."""

    value = source(
        path
    )
    tree = ast.parse(
        value,
        filename=str(path),
    )

    for node in tree.body:
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == name
        ):
            block = ast.get_source_segment(
                value,
                node,
            )

            assert block is not None
            return block

    raise AssertionError(
        f"Function not found: {name}"
    )


def test_buyee_owner_supports_cloud_headless_mode() -> None:
    """Persistent owner must honor the Railway headless setting."""
    value = source(
        OWNER
    )

    assert "launch_persistent_context(" in value
    assert "AUCTION_BUYEE_HEADLESS" in value
    assert "headless=headless" in value


def test_owner_health_still_proves_browser_liveness() -> None:
    """Headless status must not weaken the zombie-context guard."""

    value = source(
        OWNER
    )

    assert "_assert_context_alive" in value
    assert 'if command == "health":' in value
    assert "self._assert_context_alive()" in value
    assert 'context.on(' in value


def test_latest_refresh_does_not_force_all_buyee_details() -> None:
    "Refresh Chromium only for explicitly WAF-blocked Buyee details."

    value = source(
        RUNNER
    )

    production_detail_start = value.index(
        "if buyee_new_listing_ids:"
    )

    production_detail_end = value.index(
        "if buyee_available:",
        production_detail_start,
    )

    production_detail = value[
        production_detail_start:
        production_detail_end
    ]

    https_index = production_detail.index(
        '"scripts/crawl_buyee_http_details.py"'
    )

    waf_index = production_detail.index(
        '"AWS_WAF_CHALLENGE"',
        https_index,
    )

    owner_index = production_detail.index(
        '"scripts/run_buyee_owner_job.py"',
        waf_index,
    )

    crawl_index = production_detail.index(
        '"crawl_live_details"',
        owner_index,
    )

    refresh_index = production_detail.index(
        '"--refresh"',
        crawl_index,
    )

    https_primary_block = production_detail[
        https_index:
        waf_index
    ]

    waf_fallback_block = production_detail[
        waf_index:
    ]

    assert (
        "buyee_new_listing_ids"
        in value
    )

    assert (
        "buyee_listing_ids_after"
        in value
    )

    assert (
        "buyee_listing_ids_before"
        in value
    )

    assert (
        '"--listing-id"'
        in waf_fallback_block
    )

    assert (
        '"--refresh"'
        not in https_primary_block
    )

    assert (
        '"--refresh"'
        in waf_fallback_block
    )

    assert (
        production_detail.count(
            '"--refresh"'
        )
        == 1
    )

    assert (
        '"--apply"'
        in waf_fallback_block
    )

    assert (
        https_index
        < waf_index
        < owner_index
        < crawl_index
        < refresh_index
    )


def test_crawler_has_distinct_refresh_semantics() -> None:
    """Removing forced refresh must retain an explicit refresh path."""

    block = function_block(
        CRAWLER,
        "load_candidates",
    )

    assert "refresh" in block


def test_runner_persists_marketplace_progress() -> None:
    """Marketplace lifecycle events must reach the UI status file."""

    block = function_block(
        RUNNER,
        "emit_source_state",
    )

    assert "marketplace_states" in block
    assert "marketplace_timing" in block
    assert "write_json_atomic" in block
    assert "current_marketplace" in block


def test_latest_refresh_ui_renders_each_marketplace() -> None:
    """Refresh page exposes individual live marketplace states."""

    value = source(
        UI
    )

    assert "render_marketplace_progress" in value
    assert '("buyee", "Buyee")' in value
    assert '("ebay", "eBay")' in value
    assert '("gripsweat", "Gripsweat")' in value
    assert '"Waiting"' in value
    assert '"Running"' in value
    assert '"Complete"' in value


def test_running_refresh_is_polled_automatically() -> None:
    """Users must not manually reload status during a long refresh."""

    value = source(
        UI
    )

    assert "if job_running:" in value
    assert "time.sleep(" in value
    assert "st.rerun()" in value
