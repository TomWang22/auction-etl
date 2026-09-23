import json
from pathlib import Path

from auction_etl.browser.manager import (
    BrowserManager,
    ebay_context_storage_state,
    is_ebay_storage_profile,
)


def test_manager_starts_empty():
    manager = BrowserManager()

    assert manager._contexts == {}


def test_is_ebay_storage_profile() -> None:
    assert is_ebay_storage_profile("ebay-public") is True
    assert is_ebay_storage_profile("ebay-owner") is True
    assert is_ebay_storage_profile("buyee") is False


def test_ebay_context_storage_state_drops_sensor_and_expired(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ebay-storage-state.json"
    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "nonsession",
                        "value": "keep",
                        "domain": ".ebay.com",
                        "path": "/",
                        "expires": -1,
                    },
                    {
                        "name": "ak_bmsc",
                        "value": "blocked",
                        "domain": ".ebay.com",
                        "path": "/",
                        "expires": 9_999_999_999,
                    },
                    {
                        "name": "oldsid",
                        "value": "expired",
                        "domain": ".ebay.com",
                        "path": "/",
                        "expires": 1,
                    },
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )

    state = ebay_context_storage_state(path)

    names = [cookie["name"] for cookie in state["cookies"]]
    assert names == ["nonsession"]


def test_replace_context_reuses_owned_browser(monkeypatch) -> None:
    manager = BrowserManager()
    closed: list[str] = []

    class Ctx:
        def close(self) -> None:
            closed.append("context")

    class Owned:
        def close(self) -> None:
            closed.append("browser")

    rebuilt = Ctx()

    def fake_context(profile: str) -> Ctx:
        assert profile == "ebay-public"
        manager._contexts[profile] = rebuilt
        return rebuilt

    owned = Owned()
    manager._contexts["ebay-public"] = Ctx()
    manager._owned_browsers.append(owned)
    monkeypatch.setattr(manager, "context", fake_context)

    result = manager.replace_context("ebay-public")

    assert closed == ["context"]
    assert manager._owned_browsers == [owned]
    assert result is rebuilt
    assert manager._contexts["ebay-public"] is rebuilt
