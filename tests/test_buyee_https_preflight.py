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
    """Determine Buyee availability through the HTTPS-first verifier."""
    block = authentication_preflight_block()
    source = runner_source()

    assert HTTPS_VERIFIER in block
    assert '"--storage-state"' in block
    assert "str(buyee_storage_state)" in block

    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert (
        "/data/buyee-profile/"
        ".auction-etl/private/"
        "buyee-storage-state.json"
        in source
    )


def test_buyee_preflight_does_not_use_owner_verification_job() -> None:
    """Avoid browser-owner response classification in the availability gate."""
    block = authentication_preflight_block()

    assert OWNER_VERIFIER not in block
    assert VERIFY_COMMAND not in block


def test_buyee_owner_remains_available_for_later_browser_operations() -> None:
    """Keep the persistent owner for detail enrichment when it is needed."""
    source = runner_source()

    assert '"scripts/ensure_buyee_owner.py"' in source
    assert OWNER_VERIFIER in source


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
