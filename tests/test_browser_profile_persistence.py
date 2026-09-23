"""Tests for persistent browser-profile paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from auction_etl.browser.profiles import (
    profile_path,
    profile_root,
)


def test_profile_root_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use configured persistent storage."""
    expected = tmp_path / "profiles"

    monkeypatch.setenv(
        "AUCTION_BROWSER_PROFILE_ROOT",
        str(expected),
    )

    assert profile_root() == expected
    assert expected.is_dir()


def test_named_profile_uses_configured_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Place eBay profiles beneath persistent storage."""
    root = tmp_path / "profiles"

    monkeypatch.setenv(
        "AUCTION_BROWSER_PROFILE_ROOT",
        str(root),
    )

    path = profile_path(
        "facerecords"
    )

    assert path == root / "facerecords"
    assert path.is_dir()


def test_ebay_local_crawl_uses_installed_chrome_matching_storage_state() -> None:
    """Installed Chrome plus a home handshake, not a new Chrome per 403."""
    source = (
        Path(__file__).resolve().parents[1]
        / "auction_etl"
        / "browser"
        / "manager.py"
    ).read_text(encoding="utf-8")

    ebay_start = source.index("ebay_state = ebay_storage_state_path()")
    ebay_end = source.index("kwargs = {", ebay_start)
    ebay_block = source[ebay_start:ebay_end]

    assert "--window-position=-32000,-32000" not in source
    assert 'channel="chrome"' in ebay_block
    assert "storage_state" in ebay_block
    assert "ebay_context_storage_state(" in ebay_block
    assert "self._owned_browsers[-1]" in ebay_block
    assert "https://www.ebay.com/" in source
    assert "reuse_browser=1" in source
    assert "connect_buyee_cdp_context" in source
    assert "stealth" not in source.casefold()


def test_ebay_local_crawl_uses_storage_state_not_cdp() -> None:
    """eBay 403s CDP Chrome; local artist crawls must reuse the owner storage-state."""
    root = Path(__file__).resolve().parents[1]
    manager = (root / "auction_etl" / "browser" / "manager.py").read_text(
        encoding="utf-8"
    )
    runner = (root / "scripts" / "run_latest_auction_refresh.py").read_text(
        encoding="utf-8"
    )

    assert "AUCTION_LOCAL_EBAY_STATE_FILE" in manager
    assert "storage_state" in manager
    assert "AUCTION_EBAY_CDP_URL" not in manager
    assert "ensure_hidden_chrome.py" not in runner
    assert "AUCTION_LOCAL_EBAY_STATE_FILE" in runner


@pytest.mark.parametrize(
    "name",
    (
        "",
        " ",
        ".",
        "..",
        "../escape",
        "nested/profile",
    ),
)
def test_profile_path_rejects_unsafe_names(
    name: str,
) -> None:
    """Keep profile names inside the configured root."""
    with pytest.raises(
        ValueError
    ):
        profile_path(
            name
        )
