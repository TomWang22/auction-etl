"""Offline regression checks for the Buyee internal owner architecture."""

from __future__ import annotations

from pathlib import Path

from auction_etl.browser.buyee_owner import forwarded_environment


ROOT = Path(__file__).resolve().parents[1]


def test_forwarded_environment_drops_cdp_transport() -> None:
    environment = {
        "DATABASE_URL": "postgresql://example",
        "AUCTION_BUYEE_PROFILE": "buyee",
        "AUCTION_BUYEE_OWNER_SOCKET": "/tmp/owner.sock",
        "AUCTION_BUYEE_CDP_URL": "http://127.0.0.1:9334",
        "UNRELATED_SECRET": "do-not-forward",
    }

    assert forwarded_environment(environment) == {
        "DATABASE_URL": "postgresql://example",
        "AUCTION_BUYEE_PROFILE": "buyee",
    }


def test_runner_uses_internal_owner_for_buyee_browser_jobs() -> None:
    """Use HTTPS preflight and one runtime-resolved persistent Buyee state."""

    source = (
        ROOT
        / "scripts"
        / "run_latest_auction_refresh.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "scripts/ensure_buyee_owner.py" in source
    assert "scripts/run_buyee_owner_job.py" in source
    assert "scripts/verify_buyee_session.py" in source

    assert '"--storage-state"' in source
    assert "str(buyee_storage_state)" in source

    assert "BUYEE_STORAGE_STATE_FILE" in source
    assert "AUCTION_BUYEE_STORAGE_STATE" in source
    assert "AUCTION_BUYEE_PROFILE_DIR" in source
    assert "configured_buyee_storage_state" in source


def test_owner_server_has_no_cdp_transport() -> None:
    source = (
        ROOT
        / "scripts"
        / "run_buyee_owner.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "connect_over_cdp" not in source
    assert "--remote-debugging-port" not in source
    assert "launch_persistent_context" in source
    assert "headless=headless" in source
    assert '"headless": False' in source
    assert "--window-position=-32000,-32000" in source


def test_owner_protocol_is_high_level_only() -> None:
    source = (
        ROOT
        / "scripts"
        / "run_buyee_owner.py"
    ).read_text(
        encoding="utf-8"
    )

    for command in (
        "health",
        "verify_closed_watchlist",
        "crawl_closed_watchlist",
        "crawl_live_details",
    ):
        assert command in source

    assert "remote_locator" not in source
    assert "remote_page" not in source
