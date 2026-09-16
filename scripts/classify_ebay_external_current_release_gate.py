#!/usr/bin/env python3
"""Classify a completed external eBay operator log without reacquiring."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TerminalState = Literal[
    "APPLIED",
    "NOOP_ZERO_NOVELTY",
]


class ClassificationError(RuntimeError):
    """Raised when the outer current-release gate cannot classify a log."""


@dataclass(frozen=True, slots=True)
class GateClassification:
    """One valid operator terminal for the current-release gate."""

    terminal_state: TerminalState
    operator_noop: bool
    new_identity_count: int


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse classification arguments. Never launches acquisition."""

    parser = argparse.ArgumentParser(
        description=(
            "Classify a completed external eBay operator log as APPLIED "
            "or NOOP_ZERO_NOVELTY without making another eBay request."
        )
    )
    parser.add_argument(
        "--operator-log",
        type=Path,
        default=os.environ.get("OPERATOR_LOG"),
        help=(
            "Completed operator log. Defaults to OPERATOR_LOG. "
            "Does not rerun headed acquisition."
        ),
    )
    arguments = parser.parse_args(argv)
    if arguments.operator_log is None:
        raise ClassificationError(
            "OPERATOR_LOG must point to the completed operator log."
        )
    arguments.operator_log = Path(
        arguments.operator_log
    ).expanduser().resolve()
    return arguments


def require_exact(
    text: str,
    expected: str,
) -> None:
    """Require one exact sentinel line."""

    for line in text.splitlines():
        if line == expected:
            return
    raise ClassificationError(
        "operator log missing required sentinel: "
        f"{expected}"
    )


def value_of(
    text: str,
    key: str,
) -> str:
    """Return the last value for one KEY= sentinel."""

    prefix = f"{key}="
    matches = [
        line[len(prefix):]
        for line in text.splitlines()
        if line.startswith(prefix)
    ]
    if not matches:
        return ""
    return matches[-1]


def classify_operator_log(
    text: str,
) -> GateClassification:
    """Return APPLIED or NOOP_ZERO_NOVELTY for one completed operator log."""

    if not text.strip():
        raise ClassificationError(
            "operator log is missing or empty."
        )

    require_exact(
        text,
        "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
    )

    raw_count = value_of(
        text,
        "NEW_IDENTITY_COUNT",
    )
    if not raw_count.isdigit():
        raise ClassificationError(
            "NEW_IDENTITY_COUNT is missing or invalid."
        )

    new_identity_count = int(raw_count)

    if new_identity_count > 0:
        require_exact(
            text,
            "STRUCTURED_EBAY_APPLY_RUN=true",
        )
        require_exact(
            text,
            "DATABASE_WRITE=true",
        )
        require_exact(
            text,
            "REAL_REFRESH_RUN=true",
        )
        return GateClassification(
            terminal_state="APPLIED",
            operator_noop=False,
            new_identity_count=new_identity_count,
        )

    require_exact(
        text,
        "NEW_IDENTITY_COUNT=0",
    )
    require_exact(
        text,
        "READY_FOR_STRUCTURED_EBAY_APPLY=false",
    )
    require_exact(
        text,
        "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true",
    )
    require_exact(
        text,
        "STRUCTURED_EBAY_APPLY_RUN=false",
    )
    require_exact(
        text,
        "DATABASE_WRITE=false",
    )
    require_exact(
        text,
        "REAL_REFRESH_RUN=false",
    )
    return GateClassification(
        terminal_state="NOOP_ZERO_NOVELTY",
        operator_noop=True,
        new_identity_count=0,
    )


def emit_gate_result(
    result: GateClassification,
) -> None:
    """Print the outer current-release RESULT block."""

    print()
    print("================ RESULT ================")
    print()
    print("EBAY_EXTERNAL_CURRENT_RELEASE_GATE=PASS")
    print(f"OPERATOR_TERMINAL_STATE={result.terminal_state}")
    print(f"OPERATOR_NOOP={str(result.operator_noop).lower()}")
    print(f"NEW_IDENTITY_COUNT={result.new_identity_count}")

    if result.operator_noop:
        print("STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true")
        print("STRUCTURED_EBAY_APPLY_RUN=false")
        print("DATABASE_WRITE=false")
        print("REAL_REFRESH_RUN=false")

    print("SOURCE_COMMIT_CREATED=false")
    print("GITHUB_PUSH_RUN=false")
    print("RAILWAY_CHANGE=false")
    print("VERCEL_CHANGE=false")
    print()
    print(
        "NEXT_ACTION=Do not reacquire this identical eBay window. "
        "Treat zero novelty as a successful no-op, then re-prove "
        "release alignment and clean worktree."
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Classify one completed operator log and exit non-zero on mismatch."""

    arguments = parse_arguments(argv)
    log_path = arguments.operator_log
    if not log_path.is_file() or log_path.stat().st_size < 1:
        raise ClassificationError(
            "operator log is missing or empty."
        )

    result = classify_operator_log(
        log_path.read_text(
            encoding="utf-8",
        )
    )
    emit_gate_result(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClassificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("EBAY_EXTERNAL_CURRENT_RELEASE_GATE=FAIL")
        raise SystemExit(1) from exc
