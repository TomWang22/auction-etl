"""Regression tests for the Buyee HTTPS-first production preflight."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"

HTTPS_VERIFIER = '"scripts/verify_buyee_session.py"'
STORAGE_STATE = '"/data/buyee-profile/.auction-etl/private/buyee-storage-state.json"'
OWNER_VERIFIER = '"scripts/run_buyee_owner_job.py"'
VERIFY_COMMAND = '"verify_closed_watchlist"'
AUTH_STATUS = "auth_status, _ = run_command("


def runner_source() -> str:
    """Load syntactically valid refresh-runner source."""
    source = RUNNER.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(RUNNER),
    )

    return source


def authentication_preflight_block() -> str:
    """Return the command block that determines Buyee availability."""
    source = runner_source()

    start = source.index(
        AUTH_STATUS,
    )

    end = source.index(
        'status["buyee_verifier_exit_code"]',
        start,
    )

    return source[start:end]


def test_buyee_preflight_uses_https_verifier() -> None:
    """Pass the effective runtime storage state to the HTTPS verifier."""

    block = authentication_preflight_block()
    source = runner_source()

    assert HTTPS_VERIFIER in block
    assert '"--storage-state"' in block
    assert "str(buyee_storage_state)" in block

    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert "AUCTION_BUYEE_STORAGE_STATE" in source
    assert "AUCTION_BUYEE_PROFILE_DIR" in source
    assert "configured_buyee_storage_state" in source
    assert "buyee_storage_state.parent.mkdir" in source


def test_buyee_preflight_does_not_use_owner_verification_job() -> None:
    """Avoid browser-owner response classification in the availability gate."""
    block = authentication_preflight_block()

    assert OWNER_VERIFIER not in block
    assert VERIFY_COMMAND not in block


def test_buyee_production_details_use_https_first_with_waf_fallback() -> None:
    """Use Chromium only for explicitly classified HTTPS WAF challenges."""

    source = runner_source()

    production_detail_start = source.index(
        "if buyee_new_listing_ids:"
    )

    production_detail_end = source.index(
        "if buyee_available:",
        production_detail_start,
    )

    production_detail = source[
        production_detail_start:
        production_detail_end
    ]

    https_index = production_detail.index(
        '"scripts/crawl_buyee_http_details.py"'
    )

    waf_index = production_detail.index(
        '"AWS_WAF_CHALLENGE"'
    )

    owner_index = production_detail.index(
        '"scripts/run_buyee_owner_job.py"',
        waf_index,
    )

    assert (
        https_index
        < waf_index
        < owner_index
    )

    assert (
        '"Apply new-only Buyee HTTPS "'
        in production_detail
    )

    assert (
        '"detail enrichment"'
        in production_detail
    )

    assert (
        "allow_failure=True"
        in production_detail
    )

    assert (
        "buyee_non_waf_failures"
        in production_detail
    )

    assert (
        "buyee_waf_listing_ids"
        in production_detail
    )

    assert (
        '"crawl_live_details"'
        in production_detail
    )

    assert (
        '"--socket-path"'
        in production_detail
    )

    assert (
        '"--apply"'
        in production_detail
    )

    assert (
        '"--refresh"'
        in production_detail
    )

    assert (
        '"--profile-dir"'
        in production_detail
    )

    assert (
        "Apply WAF-only Buyee browser "
        in production_detail
    )

def test_https_preflight_preserves_existing_exit_code_handling() -> None:
    """Keep authentication, timeout, access-block, and maintenance semantics."""
    source = runner_source()

    required_symbols = (
        "BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE",
        "BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE",
        "BUYEE_ACCESS_BLOCKED_EXIT_CODE",
        "BUYEE_MAINTENANCE_EXIT_CODE",
    )

    for symbol in required_symbols:
        assert symbol in source
