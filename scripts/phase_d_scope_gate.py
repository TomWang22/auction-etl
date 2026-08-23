#!/usr/bin/env python3
"""Block enforcement while account-sensitive runtime files remain unscoped."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """Require zero ACCOUNT_SCOPE_REQUIRED findings."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("docs/ACCOUNT_SCOPING_MATRIX.generated.json"),
    )
    args = parser.parse_args()

    findings = json.loads(args.audit.read_text(encoding="utf-8"))
    required = [
        item
        for item in findings
        if item.get("classification") == "ACCOUNT_SCOPE_REQUIRED"
    ]

    if required:
        print(f"ACCOUNT_SCOPE_REQUIRED={len(required)}")
        for item in required:
            print(f"UNSCOPED={item.get('path')}")
        print("RESULT=PHASE_D_ENFORCEMENT_BLOCKED")
        return 3

    print("ACCOUNT_SCOPE_REQUIRED=0")
    print("RESULT=PHASE_D_SCOPE_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
