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
    """Keep production Buyee state inside the mounted Railway volume."""
    source = load_source(
        RUNNER
    )

    assert PERSISTENT_STATE in source
    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert DISPOSABLE_STATE not in source


def test_verifier_defaults_to_persistent_buyee_state() -> None:
    """Use persistent state when no explicit verifier path is supplied."""
    source = load_source(
        VERIFIER
    )

    assert PERSISTENT_STATE in source
    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert DISPOSABLE_STATE not in source


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
