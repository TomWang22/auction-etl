"""Regression tests for duplicate-column DataFrame unions."""

from __future__ import annotations

import pandas as pd

from auction_etl.reporting.main_review_integration import (
    _concat_unique_columns,
)


def test_concat_coalesces_duplicate_columns() -> None:
    """Duplicate columns must not break vertical concatenation."""
    native = pd.DataFrame(
        [
            [
                "ebay",
                "100",
                None,
                "Native title",
            ],
        ],
        columns=[
            "marketplace",
            "listing_id",
            "title",
            "title",
        ],
    )

    gripsweat = pd.DataFrame(
        [
            [
                "gripsweat",
                "200",
                "Gripsweat title",
            ],
        ],
        columns=[
            "marketplace",
            "listing_id",
            "title",
        ],
    )

    result = _concat_unique_columns(
        [
            native,
            gripsweat,
        ],
        ignore_index=True,
        sort=False,
    )

    assert result.columns.is_unique
    assert result["title"].tolist() == [
        "Native title",
        "Gripsweat title",
    ]


def test_concat_preserves_first_non_null_value() -> None:
    """Duplicate values must coalesce from left to right."""
    frame = pd.DataFrame(
        [
            [
                None,
                "secondary",
                "tertiary",
            ],
            [
                "primary",
                "secondary",
                None,
            ],
        ],
        columns=[
            "value",
            "value",
            "value",
        ],
    )

    result = _concat_unique_columns(
        [frame],
        ignore_index=True,
    )

    assert result.columns.tolist() == ["value"]
    assert result["value"].tolist() == [
        "secondary",
        "primary",
    ]
