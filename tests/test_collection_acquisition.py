"""Acquisition counts for My collection."""

from datetime import date

from auction_etl.services.collection_acquisition import (
    acquisition_breakdown,
    collection_package_label,
    default_delivered_on,
    default_sale_type,
    effective_sale_type,
)
from auction_etl.services.collection_import import ebay_delivered_on


def test_ebay_delivered_on_keeps_the_delivery_day() -> None:
    assert ebay_delivered_on(
        "Delivered on Mon, Oct 7, 2024\nPaid\nOct 1\nOrder total $165.14"
    ) == date(2024, 10, 7)
    assert ebay_delivered_on("Paid\nOct 1\nShipping $10.01") is None


def test_purchase_history_delivery_borrows_the_order_year() -> None:
    """History cards say 'Delivered on Mon, Aug 25' and keep the year on Order date."""

    assert ebay_delivered_on(
        "Delivered on Mon, Aug 25\nOrder date: Aug 18, 2025",
        paid_on=date(2025, 8, 18),
    ) == date(2025, 8, 25)
    assert ebay_delivered_on(
        "Delivered on Sat, Jan 4\nOrder date: Dec 28, 2024",
        paid_on=date(2024, 12, 28),
    ) == date(2025, 1, 4)


def test_acquisition_breakdown_counts_types_shops_and_artists() -> None:
    rows = [
        {
            "marketplace": "gripsweat",
            "artist_name": "Teresa Teng",
            "paid_on": date(2025, 1, 16),
            "sale_type": "",
            "stored_sale_type": "AUCTION",
        },
        {
            "marketplace": "ebay",
            "artist_name": "Teresa Teng",
            "paid_on": date(2024, 10, 1),
            "sale_type": "FIXED_PRICE_OBO",
            "stored_sale_type": "",
        },
        {
            "marketplace": "buyee",
            "artist_name": "Anita Mui",
            "paid_on": date(2024, 10, 14),
            "sale_type": "",
            "stored_sale_type": "AUCTION",
        },
        {
            "marketplace": "discogs",
            "artist_name": "Anita Mui",
            "paid_on": None,
            "sale_type": "FIXED_PRICE",
            "stored_sale_type": "",
        },
    ]
    summary = acquisition_breakdown(rows, grain="month")
    assert dict(summary["types"])["Auction"] == 2
    assert dict(summary["types"])["OBO"] == 1
    assert dict(summary["types"])["Fixed"] == 1
    assert dict(summary["types"])["Unlabeled"] == 0
    assert dict(summary["shops"])["eBay"] == 2
    assert dict(summary["shops"])["Buyee"] == 1
    assert dict(summary["shops"])["Discogs"] == 1
    assert summary["undated"] == 1
    assert ("2024-10", 2) in summary["periods"]
    assert ("2025-01", 1) in summary["periods"]
    assert dict(summary["artists"])["Teresa Teng"] == 2
    assert dict(summary["artists"])["Anita Mui"] == 2


def test_acquisition_folds_same_artist_spellings() -> None:
    """JP, EN, slash credits, and missing names are one artist bar."""

    rows = [
        {
            "marketplace": "buyee",
            "artist_name": "山口百恵",
            "paid_on": date(2025, 8, 1),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 2),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
        {
            "marketplace": "buyee",
            "artist_name": "山口百恵 / Momoe Yamaguchi",
            "paid_on": date(2025, 8, 3),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
        {
            "marketplace": "buyee",
            "artist_name": float("nan"),
            "album_title": "山口百恵 15才",
            "paid_on": date(2025, 8, 4),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
        {
            "marketplace": "ebay",
            "artist_name": "Teresa Teng",
            "paid_on": date(2025, 8, 5),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
        {
            "marketplace": "ebay",
            "artist_name": "テレサ・テン",
            "paid_on": date(2025, 8, 6),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
        },
    ]
    artists = dict(acquisition_breakdown(rows)["artists"])
    assert artists["Momoe Yamaguchi"] == 4
    assert artists["Teresa Teng"] == 2
    assert "nan" not in artists
    assert "山口百恵" not in artists


def test_acquisition_skips_unknown_section_when_artist_name_is_known() -> None:
    artists = dict(
        acquisition_breakdown(
            [
                {
                    "marketplace": "buyee",
                    "artist_section": "Unknown",
                    "artist_name": "山口百恵",
                    "paid_on": date(2025, 8, 1),
                    "sale_type": "AUCTION",
                    "stored_sale_type": "",
                }
            ]
        )["artists"]
    )
    assert artists == {"Momoe Yamaguchi": 1}


def test_collection_package_label_uses_media_discs_and_gatefold() -> None:
    assert collection_package_label({"manual_media_type": "EP_7_INCH"}) == "EP"
    assert collection_package_label(
        {"manual_media_type": "LP", "manual_disc_count": 1}
    ) == "Single sleeve LP"
    assert collection_package_label(
        {
            "manual_media_type": "LP",
            "manual_disc_count": 1,
            "format_detail": "Vinyl, LP, Album, Gatefold",
        }
    ) == "Single gatefold"
    assert collection_package_label(
        {"manual_media_type": "LP", "manual_disc_count": 2}
    ) == "Double LP gatefold"
    assert collection_package_label(
        {"manual_media_type": "LP", "manual_disc_count": 3}
    ) == "Trifold"
    assert collection_package_label(
        {"manual_media_type": "LP_BOX_SET", "manual_disc_count": 5}
    ) == "Box set"
    assert collection_package_label(
        {"manual_media_type": "LP", "manual_disc_count": 5}
    ) == "Box set"


def test_acquisition_breakdown_counts_record_packages() -> None:
    rows = [
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 1),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "EP_7_INCH",
            "manual_disc_count": 1,
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 2),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "LP",
            "manual_disc_count": 1,
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 3),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "LP",
            "manual_disc_count": 1,
            "format_detail": "Vinyl, LP, Album, Gatefold",
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 4),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "LP",
            "manual_disc_count": 2,
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 5),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "LP",
            "manual_disc_count": 3,
        },
        {
            "marketplace": "buyee",
            "artist_name": "Momoe Yamaguchi",
            "paid_on": date(2025, 8, 6),
            "sale_type": "AUCTION",
            "stored_sale_type": "",
            "manual_media_type": "LP_BOX_SET",
            "manual_disc_count": 5,
        },
    ]
    packages = dict(acquisition_breakdown(rows)["packages"])
    assert packages["EP"] == 1
    assert packages["Single sleeve LP"] == 1
    assert packages["Single gatefold"] == 1
    assert packages["Double LP gatefold"] == 1
    assert packages["Trifold"] == 1
    assert packages["Box set"] == 1


def test_acquisition_week_grain_uses_iso_weeks() -> None:
    summary = acquisition_breakdown(
        [
            {
                "marketplace": "ebay",
                "artist_name": "Teresa Teng",
                "paid_on": date(2024, 10, 1),
                "sale_type": "AUCTION",
                "stored_sale_type": "",
            }
        ],
        grain="week",
    )
    assert summary["periods"] == [("2024-W40", 1)]


def test_buyee_defaults_to_auction_unless_the_operator_overrides() -> None:
    assert default_sale_type("buyee") == "AUCTION"
    assert effective_sale_type(
        marketplace="buyee",
        stored="AUCTION",
        manual="",
    ) == "AUCTION"
    assert effective_sale_type(
        marketplace="buyee",
        stored="AUCTION",
        manual="FIXED_PRICE",
    ) == "FIXED_PRICE"


def test_record_city_defaults_to_fixed_price() -> None:
    assert default_sale_type("recordcity") == "FIXED_PRICE"
    assert effective_sale_type(
        marketplace="recordcity",
        stored="",
        manual="",
    ) == "FIXED_PRICE"


def test_missing_delivery_is_four_days_after_the_order() -> None:
    paid = date(2025, 8, 13)
    assert default_delivered_on("recordcity", paid, None) == date(2025, 8, 17)
    assert default_delivered_on("buyee", paid, None) == date(2025, 8, 17)
    assert default_delivered_on("buyee", paid, date(2025, 8, 20)) == date(2025, 8, 20)
    assert default_delivered_on("ebay", paid, None) is None
    assert default_delivered_on("buyee", None, None) is None
