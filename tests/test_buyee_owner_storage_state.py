"""Regression tests for complete persistent-owner storage-state hydration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(
    __file__
).resolve().parents[1]

OWNER_PATH = (
    ROOT
    / "scripts"
    / "run_buyee_owner.py"
)

SPEC = importlib.util.spec_from_file_location(
    "_test_buyee_owner_storage_state",
    OWNER_PATH,
)

assert SPEC is not None
assert SPEC.loader is not None

OWNER = importlib.util.module_from_spec(
    SPEC
)

sys.modules[
    SPEC.name
] = OWNER

SPEC.loader.exec_module(
    OWNER
)


class FakePage:
    """Record one storage-state hydration page."""

    def __init__(
        self,
    ) -> None:
        self.init_script = ""
        self.goto_url = ""
        self.closed = False

    def add_init_script(
        self,
        *,
        script: str,
    ) -> None:
        self.init_script = script

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        assert wait_until == "commit"
        assert timeout == 30_000
        self.goto_url = url

    def evaluate(
        self,
        _expression: str,
        entries: list[dict[str, str]],
    ) -> int:
        return len(
            entries
        )

    def close(
        self,
    ) -> None:
        self.closed = True


class FakeContext:
    """Minimal BrowserContext contract needed by the hydrator."""

    def __init__(
        self,
    ) -> None:
        self.added_cookies: list[
            dict[str, Any]
        ] = []

        self.pages: list[
            FakePage
        ] = []

    def add_cookies(
        self,
        cookies: list[dict[str, Any]],
    ) -> None:
        self.added_cookies = cookies

    def cookies(
        self,
    ) -> list[dict[str, Any]]:
        return list(
            self.added_cookies
        )

    def new_page(
        self,
    ) -> FakePage:
        page = FakePage()

        self.pages.append(
            page
        )

        return page


def write_state(
    path: Path,
    *,
    local_storage: list[dict[str, object]],
) -> None:
    """Write one representative Playwright storage-state document."""

    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": "secret",
                        "domain": ".buyee.jp",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://buyee.jp",
                        "localStorage": local_storage,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_owner_hydrates_cookies_and_local_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Persistent owner must restore the same state used by BrowserContext."""

    state_path = (
        tmp_path
        / "storage-state.json"
    )

    write_state(
        state_path,
        local_storage=[
            {
                "name": "auth-one",
                "value": "value-one",
            },
            {
                "name": "auth-two",
                "value": "value-two",
            },
        ],
    )

    monkeypatch.setenv(
        "BUYEE_STORAGE_STATE_FILE",
        str(
            state_path
        ),
    )

    context = FakeContext()

    OWNER.seed_authenticated_storage_state(
        context,
        tmp_path,
    )

    assert len(
        context.added_cookies
    ) == 1

    assert len(
        context.pages
    ) == 1

    page = context.pages[0]

    assert (
        page.goto_url
        == "https://buyee.jp"
    )

    assert (
        "window.localStorage.setItem"
        in page.init_script
    )

    assert page.closed is True

    output = (
        capsys
        .readouterr()
        .out
    )

    assert (
        "BUYEE_OWNER_STORAGE_STATE_ORIGIN_COUNT=1"
        in output
    )

    assert (
        "BUYEE_OWNER_STORAGE_STATE_LOCAL_STORAGE_ENTRY_COUNT=2"
        in output
    )

    assert (
        "BUYEE_OWNER_CONTEXT_LOCAL_STORAGE_ENTRY_COUNT=2"
        in output
    )

    assert (
        "BUYEE_OWNER_STORAGE_STATE_SEEDED=true"
        in output
    )


def test_owner_rejects_non_string_local_storage_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed saved state must fail instead of silently partially hydrating."""

    state_path = (
        tmp_path
        / "storage-state.json"
    )

    write_state(
        state_path,
        local_storage=[
            {
                "name": "auth",
                "value": 123,
            }
        ],
    )

    monkeypatch.setenv(
        "BUYEE_STORAGE_STATE_FILE",
        str(
            state_path
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "localStorage names and values "
            "must be strings"
        ),
    ):
        OWNER.seed_authenticated_storage_state(
            FakeContext(),
            tmp_path,
        )


def test_owner_rejects_non_array_origins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Origins must match the Playwright storage-state schema."""

    state_path = (
        tmp_path
        / "storage-state.json"
    )

    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": "secret",
                        "domain": ".buyee.jp",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    }
                ],
                "origins": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "BUYEE_STORAGE_STATE_FILE",
        str(
            state_path
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "storage state origins must be an array"
        ),
    ):
        OWNER.seed_authenticated_storage_state(
            FakeContext(),
            tmp_path,
        )
