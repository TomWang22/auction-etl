"""Offline regression checks for the local headed eBay browser owner."""

from __future__ import annotations

from pathlib import Path

from auction_etl.browser.ebay_owner import forwarded_environment
from scripts.ensure_ebay_owner import owner_process_environment


ROOT = Path(__file__).resolve().parents[1]


def test_forwarded_environment_keeps_local_ebay_state() -> None:
    environment = {
        "DATABASE_URL": "postgresql://example",
        "AUCTION_LOCAL_EBAY_STATE_FILE": "/tmp/ebay-state.json",
        "AUCTION_EBAY_OWNER_SOCKET": "/tmp/ebay-owner.sock",
        "AUCTION_EBAY_LOCAL_AUTO_HANDOFF": "1",
        "UNRELATED_SECRET": "do-not-forward",
    }

    assert forwarded_environment(environment) == {
        "DATABASE_URL": "postgresql://example",
        "AUCTION_LOCAL_EBAY_STATE_FILE": "/tmp/ebay-state.json",
        "AUCTION_EBAY_LOCAL_AUTO_HANDOFF": "1",
    }


def test_owner_server_stays_headed_offscreen_and_has_no_cdp() -> None:
    source = (
        ROOT
        / "scripts"
        / "run_ebay_owner.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "connect_over_cdp" not in source
    assert "--remote-debugging-port" not in source
    assert "channel=" not in source
    assert 'channel="chrome"' not in source
    assert "launch_persistent_context" not in source
    assert "chromium.launch(" in source
    assert "headless=False" in source
    assert "--window-position=-32000,-32000" in source
    assert "browser=self._browser" in source
    assert "storage_state=" in source
    assert "browser.new_context(" not in source
    assert "stealth" not in source.casefold()
    assert "captcha" not in source.casefold()
    assert "retry" not in source.casefold()


def test_owner_protocol_is_high_level_only() -> None:
    source = (
        ROOT
        / "scripts"
        / "run_ebay_owner.py"
    ).read_text(
        encoding="utf-8"
    )

    for command in (
        "health",
        "acquire_structured",
        "shutdown",
    ):
        assert command in source

    assert "remote_locator" not in source
    assert "remote_page" not in source


def test_ensure_owner_rejects_cloud_and_daemonizes() -> None:
    source = (
        ROOT
        / "scripts"
        / "ensure_ebay_owner.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "cloud_runtime_detected" in source
    assert "--background" in source
    assert "start_new_session=True" in source
    assert "connect_over_cdp" not in source
    assert "RAILWAY" in source or "cloud_runtime_detected" in source


def test_owner_process_environment_drops_ambient_database_configuration() -> None:
    environment = {
        "DATABASE_URL": "postgresql://auction:secret@127.0.0.1/db",
        "AUCTION_EXPECTED_DATABASE_NAME": "auction_warehouse",
        "AUCTION_EXPECTED_DATABASE_USER": "auction",
        "PGHOST": "127.0.0.1",
        "PGPORT": "5544",
        "PGUSER": "auction",
        "PGPASSWORD": "secret",
        "AUCTION_LOCAL_EBAY_STATE_FILE": "/tmp/ebay-state.json",
        "PLAYWRIGHT_BROWSERS_PATH": "/tmp/playwright",
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/example",
    }

    assert owner_process_environment(
        environment
    ) == {
        "AUCTION_LOCAL_EBAY_STATE_FILE": "/tmp/ebay-state.json",
        "PLAYWRIGHT_BROWSERS_PATH": "/tmp/playwright",
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/example",
    }


def test_acquire_script_can_use_owner_socket_without_launching_chromium() -> None:
    source = (
        ROOT
        / "scripts"
        / "acquire_ebay_structured.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "--owner-socket" in source
    assert "acquire_page_via_owner" in source
    assert "cloud_runtime_detected" in source
    assert "stealth" not in source.casefold()
    assert "crawl_ebay_sources.py" not in source
