"""Save toast labels prefer human subjects over listing ids."""

from __future__ import annotations

from app.collector_review_support import collector_save_subject


def test_bulk_lot_uses_platform_count_and_format() -> None:
    assert (
        collector_save_subject(
            marketplace="buyee",
            media_type="CASSETTE_BULK_LOT",
            disc_count=17,
            listing_id="l251811805",
            job_lot=True,
        )
        == "Buyee, 17 cassette lot"
    )


def test_mixed_lot_lists_formats() -> None:
    assert (
        collector_save_subject(
            marketplace="ebay",
            media_type="MIXED_BULK_LOT",
            lot_mix={"LP": 2, "Cassette": 3},
            listing_id="123",
        )
        == "eBay, 2 LP + 3 cassette lot"
    )


def test_single_prefers_matrix_then_catalog_then_title() -> None:
    assert (
        collector_save_subject(
            marketplace="buyee",
            media_type="LP",
            matrix="SH301",
            catalog="SOLL-114",
            title="山口百恵",
            listing_id="x",
        )
        == "Buyee, SH301"
    )
    assert (
        collector_save_subject(
            marketplace="gripsweat",
            media_type="CD",
            catalog="SRCL-3281",
            title="百恵辞典",
            listing_id="x",
        )
        == "Gripsweat, SRCL-3281"
    )
    assert (
        collector_save_subject(
            marketplace="buyee",
            media_type="LP",
            title="山口百恵 15才",
            listing_id="x",
        )
        == "Buyee, 山口百恵 15才"
    )
