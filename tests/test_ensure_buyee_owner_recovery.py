"""Regression coverage for Buyee owner ensure teardown recovery."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, Callable

import pytest


ROOT = Path(
    __file__
).resolve().parents[1]

ENSURE_SCRIPT = (
    ROOT
    / "scripts"
    / "ensure_buyee_owner.py"
)


def load_main() -> Callable[[], Any]:
    """Load ensure main without executing its CLI entry point."""

    namespace = runpy.run_path(
        str(
            ENSURE_SCRIPT
        )
    )

    return namespace[
        "main"
    ]


def test_transient_unrecognized_owner_is_retried() -> None:
    """A shutting-down unhealthy owner gets a bounded retry."""

    main = load_main()
    calls = 0
    waits = 0

    error_message = (
        main.__globals__[
            "OWNER_SOCKET_UNRECOGNIZED_ERROR"
        ]
    )

    def fake_main_once() -> str:
        nonlocal calls

        calls += 1

        if calls < 3:
            raise RuntimeError(
                error_message
            )

        return "recovered"

    def fake_wait() -> None:
        nonlocal waits
        waits += 1

    main.__globals__[
        "_main_once"
    ] = fake_main_once

    main.__globals__[
        "_wait_before_owner_retry"
    ] = fake_wait

    assert (
        main()
        == "recovered"
    )
    assert calls == 3
    assert waits == 2


def test_unrelated_runtime_error_is_not_retried() -> None:
    """Only the known owner teardown race is retried."""

    main = load_main()
    calls = 0
    waits = 0

    def fake_main_once() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(
            "different failure"
        )

    def fake_wait() -> None:
        nonlocal waits
        waits += 1

    main.__globals__[
        "_main_once"
    ] = fake_main_once

    main.__globals__[
        "_wait_before_owner_retry"
    ] = fake_wait

    with pytest.raises(
        RuntimeError,
        match="different failure",
    ):
        main()

    assert calls == 1
    assert waits == 0


def test_unrecognized_owner_retry_is_bounded() -> None:
    """A genuinely occupied socket still fails after the retry budget."""

    main = load_main()
    calls = 0
    waits = 0

    error_message = (
        main.__globals__[
            "OWNER_SOCKET_UNRECOGNIZED_ERROR"
        ]
    )

    main.__globals__[
        "OWNER_SOCKET_RECOVERY_RETRIES"
    ] = 2

    def fake_main_once() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(
            error_message
        )

    def fake_wait() -> None:
        nonlocal waits
        waits += 1

    main.__globals__[
        "_main_once"
    ] = fake_main_once

    main.__globals__[
        "_wait_before_owner_retry"
    ] = fake_wait

    with pytest.raises(
        RuntimeError,
        match=(
            "unrecognized live service"
        ),
    ):
        main()

    assert calls == 3
    assert waits == 2
