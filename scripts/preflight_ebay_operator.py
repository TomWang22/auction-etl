#!/usr/bin/env python3
"""Compact preflight: clean worktree plus GitHub/Railway/Vercel SHA alignment.

Pass-through flags include --expected-sha. Pytest smoke is never part of
this command; use scripts/verify_release_alignment.py for that gate.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from scripts.verify_release_alignment import (  # noqa: E402
    AlignmentError,
    main as verify_release_alignment_main,
)


def preflight_ebay_operator_alignment(
    argv: Sequence[str] | None = None,
) -> int:
    """Recheck release alignment without pytest or Chromium."""

    args = [
        argument
        for argument in list(argv or [])
        if argument not in {"--smoke", "--no-smoke"}
    ]
    print(
        "================ OPERATOR PREFLIGHT ================"
    )
    result = verify_release_alignment_main(
        [
            "--no-smoke",
            *args,
        ]
    )
    if result != 0:
        raise AlignmentError(
            "Release alignment returned a non-zero status."
        )
    print(
        "OPERATOR_PREFLIGHT_ALIGNMENT=PASS"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run compact operator preflight and fail closed on mismatch."""

    try:
        return preflight_ebay_operator_alignment(
            argv
        )
    except AlignmentError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "OPERATOR_PREFLIGHT_ALIGNMENT=FAIL",
            file=sys.stderr,
        )
        print(
            "RELEASE_ALIGNMENT=FAIL",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main(
            sys.argv[1:]
        )
    )
