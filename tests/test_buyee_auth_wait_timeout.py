"""Regression tests for bounded Buyee authentication waiting."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


TARGET = Path("scripts/crawl_buyee_live_details.py")


def load_module(path: Path) -> ModuleType:
    """Load the crawler as a temporary importable module."""

    module_name = "crawl_buyee_live_details_timeout_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load crawler module.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return module


class FakeClock:
    """Deterministic monotonic clock."""

    def __init__(self) -> None:
        self.current = 100.0

    def monotonic(self) -> float:
        return self.current

    def advance_ms(self, milliseconds: int) -> None:
        self.current += milliseconds / 1_000


class FakeLocator:
    """Locator reporting no authenticated auction links."""

    def count(self) -> int:
        return 0


class FakePage:
    """Page whose navigation consumes exactly its timeout."""

    def __init__(
        self,
        clock: FakeClock,
        module: ModuleType,
    ) -> None:
        self.clock = clock
        self.module = module
        self.url = "https://example.invalid/"
        self.goto_timeouts: list[int] = []
        self.wait_timeouts: list[int] = []

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        del url
        del wait_until

        self.goto_timeouts.append(timeout)
        self.clock.advance_ms(timeout)

        raise self.module.PlaywrightTimeoutError(
            "synthetic timeout"
        )

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_timeouts.append(timeout)
        self.clock.advance_ms(timeout)

    def locator(self, selector: str) -> FakeLocator:
        del selector
        return FakeLocator()


class FakeContext:
    """Context containing exactly one fake page."""

    def __init__(self, page: FakePage) -> None:
        self.pages = [page]

    def new_page(self) -> FakePage:
        raise AssertionError(
            "new_page() should not be needed."
        )


def test_auth_wait_respects_global_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Navigation may not outlive the global unattended timeout."""

    module = load_module(TARGET)
    clock = FakeClock()
    page = FakePage(
        clock=clock,
        module=module,
    )
    context = FakeContext(page)

    monkeypatch.setattr(
        module.time,
        "monotonic",
        clock.monotonic,
    )
    monkeypatch.setattr(
        module,
        "authentication_required",
        lambda _url: False,
    )

    with pytest.raises(
        RuntimeError,
        match=r"^Timed out waiting for authenticated Buyee access\.$",
    ):
        module.wait_for_authenticated_profile(
            context,
            headed=False,
            timeout_seconds=3.0,
            navigation_timeout_seconds=45.0,
        )

    elapsed = clock.current - 100.0

    assert 3.0 <= elapsed <= 3.01
    assert page.goto_timeouts
    assert max(page.goto_timeouts) <= 3_000
    assert all(
        timeout > 0
        for timeout in page.goto_timeouts
    )
    assert page.wait_timeouts == []
