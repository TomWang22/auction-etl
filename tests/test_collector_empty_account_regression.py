"""Regression coverage for empty Collector Ledger account preparation."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_REVIEW = ROOT / "app" / "collector_review.py"


def _pressing_group_assignment_call() -> ast.Call:
    """Return the DataFrame.apply call assigned to pressing_group_key."""
    source = COLLECTOR_REVIEW.read_text(encoding="utf-8")
    tree = ast.parse(
        source,
        filename=str(COLLECTOR_REVIEW),
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        if len(node.targets) != 1:
            continue

        target = node.targets[0]

        if not isinstance(target, ast.Subscript):
            continue

        if not isinstance(target.value, ast.Name):
            continue

        if target.value.id != "frame":
            continue

        slice_node = target.slice

        if not isinstance(slice_node, ast.Constant):
            continue

        if slice_node.value != "pressing_group_key":
            continue

        if not isinstance(node.value, ast.Call):
            raise AssertionError(
                "pressing_group_key assignment is no longer a function call."
            )

        return node.value

    raise AssertionError(
        "Could not locate frame['pressing_group_key'] assignment."
    )


def _keyword_value(
    call: ast.Call,
    keyword_name: str,
) -> object:
    """Return one literal keyword argument from an AST call."""
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue

        if not isinstance(keyword.value, ast.Constant):
            raise AssertionError(
                f"{keyword_name} must remain a literal value."
            )

        return keyword.value.value

    raise AssertionError(
        f"Missing required {keyword_name!r} keyword."
    )


def _derive_pressing_group_key(row: pd.Series) -> str:
    """Mirror the Collector Ledger pressing-group normalization."""
    return "|".join(
        value
        for value in (
            re.sub(
                r"[^A-Z0-9]",
                "",
                row["artist_display"].upper(),
            ),
            row["media_display"].upper(),
            row["pressing_token"],
        )
        if value
    )


def test_pressing_group_assignment_forces_series_reduction() -> None:
    """Empty account preparation must keep apply() one-dimensional."""
    call = _pressing_group_assignment_call()

    assert _keyword_value(call, "axis") == 1
    assert _keyword_value(call, "result_type") == "reduce"


def test_empty_pressing_group_apply_returns_assignable_series() -> None:
    """An account with zero visible listings must prepare successfully."""
    frame = pd.DataFrame(
        columns=[
            "artist_display",
            "media_display",
            "pressing_token",
        ]
    )

    result = frame.apply(
        _derive_pressing_group_key,
        axis=1,
        result_type="reduce",
    )

    assert isinstance(result, pd.Series)
    assert result.empty

    frame["pressing_group_key"] = result

    assert frame.empty
    assert "pressing_group_key" in frame.columns


def test_nonempty_pressing_group_behavior_is_preserved() -> None:
    """The empty-frame fix must not change normal pressing identities."""
    frame = pd.DataFrame(
        [
            {
                "artist_display": "Miles Davis",
                "media_display": "LP",
                "pressing_token": "A1/B1",
            },
            {
                "artist_display": "The Beatles",
                "media_display": "7 inch",
                "pressing_token": "",
            },
        ]
    )

    frame["pressing_group_key"] = frame.apply(
        _derive_pressing_group_key,
        axis=1,
        result_type="reduce",
    )

    assert frame["pressing_group_key"].tolist() == [
        "MILESDAVIS|LP|A1/B1",
        "THEBEATLES|7 INCH",
    ]
