"""Regression coverage for the eBay subprocess watchdog."""

from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[1]

WATCHDOG = (
    REPOSITORY_ROOT
    / "scripts"
    / "run_with_process_watchdog.py"
)

REFRESH = (
    REPOSITORY_ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)


def test_watchdog_preserves_successful_exit() -> None:
    """A healthy command must complete without watchdog interference."""

    result = subprocess.run(
        [
            sys.executable,
            str(WATCHDOG),
            "--timeout-seconds",
            "5",
            "--kill-grace-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            'print("WATCHDOG_CHILD_OK")',
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert "WATCHDOG_CHILD_OK" in result.stdout
    assert "PROCESS_WATCHDOG_TIMEOUT=" not in result.stderr


def test_watchdog_stops_hung_command() -> None:
    """A command exceeding the wall-clock deadline must exit as 124."""

    started = time.monotonic()

    result = subprocess.run(
        [
            sys.executable,
            str(WATCHDOG),
            "--timeout-seconds",
            "0.2",
            "--kill-grace-seconds",
            "0.2",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    elapsed = (
        time.monotonic()
        - started
    )

    assert result.returncode == 124
    assert elapsed < 5
    assert "PROCESS_WATCHDOG_TIMEOUT=" in result.stderr
    assert (
        "PROCESS_WATCHDOG_TERMINATED_PROCESS_GROUP=true"
        in result.stderr
    )


def test_production_ebay_crawl_uses_outer_watchdog() -> None:
    """The production refresh must wrap the eBay crawler process."""

    source = REFRESH.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(REFRESH),
    )

    command_lists = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.List)
            and any(
                isinstance(
                    element,
                    ast.Constant,
                )
                and element.value
                == "scripts/crawl_ebay_sources.py"
                for element in node.elts
            )
        )
    ]

    assert len(command_lists) == 1

    command = command_lists[0]

    values: list[str] = []

    for element in command.elts:
        if isinstance(
            element,
            ast.Constant,
        ) and isinstance(
            element.value,
            str,
        ):
            values.append(
                element.value
            )
            continue

        if (
            isinstance(
                element,
                ast.Attribute,
            )
            and isinstance(
                element.value,
                ast.Name,
            )
            and element.value.id == "sys"
            and element.attr == "executable"
        ):
            values.append(
                "<sys.executable>"
            )

    expected = [
        "<sys.executable>",
        "scripts/run_with_process_watchdog.py",
        "--timeout-seconds",
        "600",
        "--kill-grace-seconds",
        "10",
        "--",
        "<sys.executable>",
        "scripts/crawl_ebay_sources.py",
    ]

    start = values.index(
        "<sys.executable>"
    )

    assert (
        values[
            start:
            start + len(expected)
        ]
        == expected
    )
