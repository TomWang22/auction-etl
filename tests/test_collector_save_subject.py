"""Save toast labels prefer human subjects over listing ids."""

from __future__ import annotations

from app.collector_review_support import (
    collector_save_subject,
    prefer_review_title,
)


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


def test_final_toast_is_platform_pressing_title_matrix() -> None:
    assert (
        collector_save_subject(
            marketplace="buyee",
            media_type="LP",
            matrix="27AH 1112",
            catalog="27AH-1112",
            title="41199; [LP] テレサ・テン 女記者 Domestic Release",
            album_title="Teresa Teng - 女記者",
            listing_id="x",
        )
        == "Buyee (Teresa Teng - 女記者), 27AH 1112"
    )
    # Listing title must not win over the pressing/Discogs title.
    assert (
        collector_save_subject(
            marketplace="buyee",
            matrix="27AH 1112",
            title="TERESA TENG LP WITH OBI 41199736",
            album_title="Teresa Teng - 女記者",
        )
        == "Buyee (Teresa Teng - 女記者), 27AH 1112"
    )
    assert (
        collector_save_subject(
            marketplace="gripsweat",
            media_type="CD",
            catalog="SRCL-3281",
            album_title="Momoe Yamaguchi Dictionary",
            listing_id="x",
        )
        == "Gripsweat (Momoe Yamaguchi Dictionary), SRCL-3281"
    )
    assert (
        collector_save_subject(
            marketplace="buyee",
            media_type="LP",
            album_title="山口百恵 15才",
            listing_id="x",
        )
        == "Buyee (山口百恵 15才)"
    )


def test_prefer_review_title_picks_latin_when_available() -> None:
    assert (
        prefer_review_title(
            "テレサ・テン / 女記者",
            "Teresa Teng - Onna Kisha",
        )
        == "Teresa Teng - Onna Kisha"
    )
