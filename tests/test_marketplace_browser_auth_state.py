"""Regression coverage for eBay browser storage-state handling."""

from __future__ import annotations

import base64
import json

import pytest

from auction_etl.services.marketplace_browser_runtime import MarketplaceBrowserRuntime


def encoded_state(domain: str = ".ebay.com") -> str:
    payload = {
        "cookies": [
            {
                "name": "sid",
                "value": "test",
                "domain": domain,
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }

    return base64.b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")


def test_ebay_profile_loads_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUCTION_EBAY_STORAGE_STATE_B64",
        encoded_state(),
    )

    state = MarketplaceBrowserRuntime._storage_state_for_profile(
        "facerecords"
    )

    assert state is not None
    assert state["cookies"][0]["domain"] == ".ebay.com"


def test_unrelated_profile_does_not_receive_ebay_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUCTION_EBAY_STORAGE_STATE_B64",
        encoded_state(),
    )

    assert (
        MarketplaceBrowserRuntime._storage_state_for_profile("buyee")
        is None
    )


def test_missing_secret_remains_explicitly_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "AUCTION_EBAY_STORAGE_STATE_B64",
        raising=False,
    )

    assert (
        MarketplaceBrowserRuntime._storage_state_for_profile("facerecords")
        is None
    )


def test_invalid_base64_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="valid base64"):
        MarketplaceBrowserRuntime._decode_ebay_storage_state(
            "not-base64!"
        )


def test_state_requires_ebay_cookie() -> None:
    with pytest.raises(RuntimeError, match="no eBay cookies"):
        MarketplaceBrowserRuntime._decode_ebay_storage_state(
            encoded_state(".example.com")
        )
