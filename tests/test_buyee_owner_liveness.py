"""Regression coverage for Buyee owner browser liveness."""

from __future__ import annotations

import runpy
import threading
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
OWNER_SCRIPT = ROOT / "scripts" / "run_buyee_owner.py"

NAMESPACE = runpy.run_path(
    str(OWNER_SCRIPT)
)

BuyeeOwner = NAMESPACE["BuyeeOwner"]
OWNER_PROTOCOL_VERSION = NAMESPACE[
    "OWNER_PROTOCOL_VERSION"
]


class FakePage:
    """Minimal Playwright page double."""

    def __init__(
        self,
        *,
        alive: bool,
    ) -> None:
        self.alive = alive
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def evaluate(
        self,
        _expression: str,
    ) -> bool:
        if not self.alive:
            raise RuntimeError(
                "browser context is closed"
            )

        return True

    def close(self) -> None:
        self.closed = True


class FakeContext:
    """Minimal persistent-context double."""

    def __init__(
        self,
        *,
        page: FakePage | None,
        new_page_alive: bool = True,
    ) -> None:
        self._page = page
        self._new_page_alive = (
            new_page_alive
        )

    @property
    def pages(self) -> list[FakePage]:
        if self._page is None:
            return []

        return [
            self._page
        ]

    def new_page(self) -> FakePage:
        page = FakePage(
            alive=self._new_page_alive
        )
        self._page = page
        return page


def make_owner(
    tmp_path: Path,
    context: FakeContext,
) -> Any:
    profile = (
        tmp_path
        / "profile"
    )
    profile.mkdir()

    return BuyeeOwner(
        playwright=object(),
        context=context,
        profile_dir=profile,
        executable=tmp_path / "chrome",
        stop_event=threading.Event(),
    )


def health_request() -> dict[str, object]:
    return {
        "protocol_version": (
            OWNER_PROTOCOL_VERSION
        ),
        "command": "health",
        "payload": {
            "arguments": [],
            "environment": {},
        },
    }


def test_health_requires_live_browser_round_trip(
    tmp_path: Path,
) -> None:
    owner = make_owner(
        tmp_path,
        FakeContext(
            page=FakePage(
                alive=True
            )
        ),
    )

    response = owner.handle(
        health_request()
    )

    assert response["ok"] is True
    assert not owner._stop_event.is_set()


def test_dead_browser_health_stops_zombie_owner(
    tmp_path: Path,
) -> None:
    owner = make_owner(
        tmp_path,
        FakeContext(
            page=FakePage(
                alive=False
            )
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="browser context is closed",
    ):
        owner.handle(
            health_request()
        )

    assert owner._stop_event.is_set()


def test_empty_live_context_can_be_probed(
    tmp_path: Path,
) -> None:
    context = FakeContext(
        page=None,
        new_page_alive=True,
    )

    owner = make_owner(
        tmp_path,
        context,
    )

    response = owner.handle(
        health_request()
    )

    assert response["ok"] is True
    assert context.pages[0].closed is True
    assert not owner._stop_event.is_set()
