"""Regression tests for persistent Buyee storage-state placement."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"
VERIFIER = ROOT / "scripts" / "verify_buyee_session.py"
HTTP_CRAWLER = ROOT / "scripts" / "crawl_buyee_http.py"

PERSISTENT_STATE = (
    "/data/buyee-profile/"
    ".auction-etl/private/"
    "buyee-storage-state.json"
)

DISPOSABLE_STATE = (
    "/data/private/"
    "buyee-storage-state.json"
)


def load_source(path: Path) -> str:
    """Load syntactically valid Python source."""
    source = path.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(path),
    )

    return source


def test_runner_uses_persistent_buyee_state() -> None:
    """Derive persistent state from the effective Buyee runtime profile."""

    source = load_source(
        RUNNER
    )

    assert "AUCTION_BUYEE_STORAGE_STATE" in source
    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert "AUCTION_BUYEE_PROFILE_DIR" in source
    assert "configured_buyee_storage_state" in source

    assert (
        "buyee_storage_state.parent.mkdir"
        in source
    )

    assert (
        "str(buyee_storage_state)"
        in source
    )


def test_verifier_defaults_to_persistent_buyee_state() -> None:
    """Resolve verifier state from explicit, profile, or Railway runtime paths."""

    source = load_source(
        VERIFIER
    )

    assert "AUCTION_BUYEE_STORAGE_STATE" in source
    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert "AUCTION_BUYEE_PROFILE_DIR" in source
    assert "RAILWAY_VOLUME_MOUNT_PATH" in source
    assert "buyee-storage-state.json" in source


def test_http_crawler_defaults_to_persistent_buyee_state() -> None:
    """Keep direct HTTPS crawling on the same persistent state file."""
    source = load_source(
        HTTP_CRAWLER
    )

    assert PERSISTENT_STATE in source
    assert DISPOSABLE_STATE not in source


def test_persistent_state_is_inside_railway_volume_mount() -> None:
    """Keep the state beneath the configured persistent mount."""
    mount = Path(
        "/data/buyee-profile"
    )

    state = Path(
        PERSISTENT_STATE
    )

    assert state.is_relative_to(
        mount
    )
