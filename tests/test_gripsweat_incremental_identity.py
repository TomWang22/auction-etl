"""Gripsweat stable-identity incremental regression tests."""

from __future__ import annotations

from scripts.run_latest_auction_refresh import (
    _gripsweat_new_detail_item_ids,
)


def test_known_stable_key_cannot_reenter_detail_enrichment() -> None:
    """A changed secondary ID cannot make an existing stable key new."""

    rows = [
        {
            "gripsweat_item_key":
                "known-key",
            "gripsweat_item_id":
                "different-secondary-id",
        },
        {
            "gripsweat_item_key":
                "new-key",
            "gripsweat_item_id":
                "new-detail-id",
        },
    ]

    assert (
        _gripsweat_new_detail_item_ids(
            rows,
            {
                "new-key",
            },
        )
        == [
            "new-detail-id",
        ]
    )


def test_detail_ids_are_deduplicated_and_blank_ids_are_ignored() -> None:
    """Only usable IDs for explicitly new stable identities are returned."""

    rows = [
        {
            "gripsweat_item_key":
                "new-a",
            "gripsweat_item_id":
                "100",
        },
        {
            "gripsweat_item_key":
                "new-a",
            "gripsweat_item_id":
                "100",
        },
        {
            "gripsweat_item_key":
                "new-b",
            "gripsweat_item_id":
                "",
        },
        {
            "gripsweat_item_key":
                "known-c",
            "gripsweat_item_id":
                "300",
        },
    ]

    assert (
        _gripsweat_new_detail_item_ids(
            rows,
            {
                "new-a",
                "new-b",
            },
        )
        == [
            "100",
        ]
    )
