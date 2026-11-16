"""Service modules reload only when files change."""

from __future__ import annotations

import importlib
from types import ModuleType

import auction_etl.streamlit_reload as reload_mod


def test_reload_modules_if_changed_skips_unchanged(monkeypatch) -> None:
    calls: list[ModuleType] = []

    def fake_reload(module: ModuleType) -> ModuleType:
        calls.append(module)
        return module

    monkeypatch.setattr(importlib, "reload", fake_reload)
    sample = reload_mod
    cache_key = "_auction_etl_test_reload_once"
    # Prime stamp.
    assert reload_mod.reload_modules_if_changed((sample,), cache_key=cache_key) is True
    calls.clear()
    assert reload_mod.reload_modules_if_changed((sample,), cache_key=cache_key) is False
    assert calls == []
