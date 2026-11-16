"""Headed Chrome stays headed but parks off the operator desktop by default."""

from __future__ import annotations

import os

from auction_etl.browser.defaults import (
    chrome_launch_window_args,
    chrome_window_position_arg,
)


def test_chrome_defaults_off_desktop(monkeypatch) -> None:
    monkeypatch.delenv("AUCTION_CHROME_VISIBLE", raising=False)
    monkeypatch.delenv("AUCTION_CHROME_WINDOW_POSITION", raising=False)
    assert chrome_window_position_arg() == "--window-position=-2400,-200"
    assert "--window-position=80,80" not in chrome_launch_window_args()
    assert chrome_window_position_arg() in chrome_launch_window_args()


def test_chrome_visible_flag_puts_window_on_desktop(monkeypatch) -> None:
    monkeypatch.setenv("AUCTION_CHROME_VISIBLE", "1")
    assert chrome_window_position_arg() == "--window-position=80,80"


def test_chrome_custom_position(monkeypatch) -> None:
    monkeypatch.delenv("AUCTION_CHROME_VISIBLE", raising=False)
    monkeypatch.setenv("AUCTION_CHROME_WINDOW_POSITION", "3200,40")
    assert chrome_window_position_arg() == "--window-position=3200,40"
