"""Three-source acceptance regression tests."""

from __future__ import annotations

from scripts.audit_three_source_acceptance import (
    acceptance_passes,
    parse_latest_source_states,
)


def test_final_source_state_wins() -> None:
    """A final done event supersedes earlier transient state."""

    states = parse_latest_source_states(
        "\n".join(
            (
                "AUCTION_SOURCE_STATE source=Buyee state=running",
                "AUCTION_SOURCE_STATE source=Buyee state=done",
                "AUCTION_SOURCE_STATE source=eBay state=running",
                "AUCTION_SOURCE_STATE source=eBay state=done",
                "AUCTION_SOURCE_STATE source=Gripsweat state=done",
            )
        )
    )

    assert states == {
        "buyee":
            "done",
        "ebay":
            "done",
        "gripsweat":
            "done",
    }


def test_zero_new_rows_is_valid_incremental_success() -> None:
    """Existing populated warehouses may pass without inserting new rows."""

    assert acceptance_passes(
        {
            "buyee":
                "done",
            "ebay":
                "done",
            "gripsweat":
                "done",
        },
        {
            "buyee":
                280,
            "ebay":
                767,
            "gripsweat":
                777,
        },
        {
            "auction":
                0,
            "gripsweat":
                0,
        },
    )


def test_missing_source_completion_fails() -> None:
    """Existing rows cannot fake current-run source completion."""

    assert not acceptance_passes(
        {
            "buyee":
                "done",
            "ebay":
                "done",
        },
        {
            "buyee":
                280,
            "ebay":
                767,
            "gripsweat":
                777,
        },
        {
            "auction":
                0,
            "gripsweat":
                0,
        },
    )


def test_duplicate_identity_group_fails() -> None:
    """Stable-identity duplication fails production acceptance."""

    assert not acceptance_passes(
        {
            "buyee":
                "done",
            "ebay":
                "done",
            "gripsweat":
                "done",
        },
        {
            "buyee":
                280,
            "ebay":
                767,
            "gripsweat":
                777,
        },
        {
            "auction":
                0,
            "gripsweat":
                1,
        },
    )
