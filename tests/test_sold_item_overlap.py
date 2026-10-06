"""Flag eBay completed/sold listing URLs that also exist on Gripsweat."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from auction_etl.services.sold_item_overlap import (
    apply_gripsweat_official_usd,
    flag_sold_item_overlaps,
    gripsweat_listing_id_from_row,
    listing_id_from_ebay_sold_url,
    parse_sold_card_date,
    sold_items_from_structured_artifact,
)


def test_listing_id_from_ebay_sold_url() -> None:
    """Completed/sold cards identify the sale by the itm URL."""

    assert (
        listing_id_from_ebay_sold_url(
            "https://www.ebay.com/itm/800679041850"
        )
        == "800679041850"
    )
    assert (
        listing_id_from_ebay_sold_url(
            "https://www.ebay.com/itm/800679041850?hash=item"
        )
        == "800679041850"
    )
    assert listing_id_from_ebay_sold_url("") == ""
    assert listing_id_from_ebay_sold_url("https://www.ebay.com/sch/i.html") == ""


def test_gripsweat_listing_id_comes_from_url_when_original_id_is_blank() -> None:
    """Most Gripsweat archive rows only carry the eBay id in /item/{id}/."""

    assert (
        gripsweat_listing_id_from_row(
            {
                "original_listing_id": None,
                "gripsweat_url": (
                    "https://gripsweat.com/item/800679041850/"
                    "teresa-teng-best-hit-4"
                ),
                "gripsweat_item_id": "800679041850",
            }
        )
        == "800679041850"
    )


def test_gripsweat_prefers_stored_original_listing_id() -> None:
    """A persisted original_listing_id wins over the URL slug."""

    assert (
        gripsweat_listing_id_from_row(
            {
                "original_listing_id": "111111111111",
                "gripsweat_url": "https://gripsweat.com/item/222222222222/x",
            }
        )
        == "111111111111"
    )


def test_sold_card_date_parses_ebay_ended_text() -> None:
    """Headed completed-search cards use 'Sold Mon D, YYYY'."""

    assert parse_sold_card_date("Sold Sep 18, 2026") == date(2026, 9, 18)
    assert parse_sold_card_date("Sold Sep 17, 2026") == date(2026, 9, 17)
    assert parse_sold_card_date("") is None


def test_overlap_is_flagged_and_missing_gripsweat_is_not_an_error() -> None:
    """Some Teresa Teng sold URLs overlap Gripsweat; many will not."""

    sold = sold_items_from_structured_artifact(
        {
            "listings": [
                {
                    "item_id": "800679041850",
                    "url": "https://www.ebay.com/itm/800679041850",
                    "title": "TERESA TENG Best Hit 4 Japan EP",
                    "price": "$99.99",
                    "ended": "Sold Sep 17, 2026",
                },
                {
                    "item_id": "307061206794",
                    "url": "https://www.ebay.com/itm/307061206794",
                    "title": "Teresa Teng Cassette",
                    "price": "$15.99",
                    "ended": "Sold Sep 18, 2026",
                },
            ]
        }
    )
    report = flag_sold_item_overlaps(
        sold,
        [
            {
                "original_listing_id": None,
                "gripsweat_url": (
                    "https://gripsweat.com/item/800679041850/"
                    "teresa-teng-best-hit-4"
                ),
                "title": "Gripsweat - TERESA TENG Best Hit 4",
                "sold_price": Decimal("99.99"),
                "sold_at": date(2026, 10, 17),
                "sold_at_text": None,
            }
        ],
    )

    assert [item.listing_id for item in report.ebay_only] == ["307061206794"]
    assert len(report.overlaps) == 1
    overlap = report.overlaps[0]
    assert overlap.listing_id == "800679041850"
    assert overlap.ebay_url == "https://www.ebay.com/itm/800679041850"
    assert "overlap" in overlap.flags
    assert "sold_date_mismatch" in overlap.flags
    assert "official_usd_from_gripsweat" in overlap.flags
    assert "sold_price_mismatch" not in overlap.flags
    assert overlap.official_usd == Decimal("99.99")
    assert overlap.ebay_currency is None


def test_compare_script_keeps_notes_out_of_git() -> None:
    """Overlap combing notes default to gitignored reports/."""

    from scripts.compare_ebay_sold_to_gripsweat import DEFAULT_OUTPUT

    assert DEFAULT_OUTPUT.parts[0] == "reports"


def test_warehouse_sold_url_uses_the_same_listing_identity() -> None:
    """Native warehouse eBay rows overlap Gripsweat by listing ID too."""

    from auction_etl.services.sold_item_overlap import (
        SoldItem,
        sold_item_from_warehouse_auction,
    )

    item = sold_item_from_warehouse_auction(
        {
            "listing_id": "800679041850",
            "auction_url": "https://www.ebay.com/itm/800679041850",
            "title": "TERESA TENG Best Hit 4",
            "final_price": Decimal("99.99"),
            "ended_at": date(2026, 9, 17),
        }
    )
    assert isinstance(item, SoldItem)
    assert item.listing_id == "800679041850"
    assert item.sold_on == date(2026, 9, 17)
    assert item.price == Decimal("99.99")


def test_confirmed_usd_price_mismatch_is_flagged_on_overlap() -> None:
    """Only confirmed USD eBay cards can disagree with Gripsweat USD."""

    sold = sold_items_from_structured_artifact(
        {
            "listings": [
                {
                    "item_id": "157347825387",
                    "url": "https://www.ebay.com/itm/157347825387",
                    "title": "10CDs Teresa Teng",
                    "price": "US $39.38 $43.27",
                    "ended": "Sold Sep 18, 2026",
                }
            ]
        }
    )
    report = flag_sold_item_overlaps(
        sold,
        [
            {
                "gripsweat_url": "https://gripsweat.com/item/157347825387/x",
                "sold_price": Decimal("43.27"),
                "currency": "USD",
                "sold_at": date(2026, 9, 18),
            }
        ],
    )

    assert report.overlaps[0].official_usd == Decimal("43.27")
    assert report.overlaps[0].flags == (
        "overlap",
        "official_usd_from_gripsweat",
        "sold_price_mismatch",
    )


def test_non_usd_ebay_card_uses_gripsweat_usd_as_official() -> None:
    """eBay local currency stays local; Gripsweat USD is the transaction-day USD."""

    sold = sold_items_from_structured_artifact(
        {
            "listings": [
                {
                    "item_id": "306985967180",
                    "url": "https://www.ebay.com/itm/306985967180",
                    "title": "Teresa Teng First Concert",
                    "price": "GBP 21.81",
                    "ended": "Sold Jun 13, 2026",
                }
            ]
        }
    )
    report = flag_sold_item_overlaps(
        sold,
        [
            {
                "gripsweat_url": "https://gripsweat.com/item/306985967180/x",
                "sold_price": Decimal("29.17"),
                "currency": "USD",
                "sold_at": date(2026, 6, 13),
            }
        ],
    )

    overlap = report.overlaps[0]
    assert overlap.ebay_currency == "GBP"
    assert overlap.ebay_price == Decimal("21.81")
    assert overlap.official_usd == Decimal("29.17")
    assert overlap.official_usd_date == date(2026, 6, 13)
    assert "official_usd_from_gripsweat" in overlap.flags
    assert "sold_price_mismatch" not in overlap.flags


def test_gripsweat_price_is_official_usd_even_when_tagged_gbp() -> None:
    """On eBay duplicates, Gripsweat's amount is the official transaction-day USD."""

    sold = sold_items_from_structured_artifact(
        {
            "listings": [
                {
                    "item_id": "187864786670",
                    "url": "https://www.ebay.com/itm/187864786670",
                    "title": "Teresa Teng box set",
                    "price": "$348.27",
                    "ended": "Sold Sep 1, 2026",
                }
            ]
        }
    )
    report = flag_sold_item_overlaps(
        sold,
        [
            {
                "gripsweat_url": "https://gripsweat.com/item/187864786670/x",
                "sold_price": Decimal("260.00"),
                "currency": "GBP",
                "sold_at": date(2026, 9, 1),
            }
        ],
    )

    overlap = report.overlaps[0]
    assert overlap.official_usd == Decimal("260.00")
    assert overlap.official_usd_date == date(2026, 9, 1)
    assert overlap.ebay_currency is None
    assert "official_usd_from_gripsweat" in overlap.flags
    assert "gripsweat_tagged_non_usd" in overlap.flags
    assert "sold_price_mismatch" not in overlap.flags

def test_apply_gripsweat_official_usd_is_reference_only() -> None:
    """Non-OBO eBay amounts stay the sale; Gripsweat is reference."""

    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "800679041850",
                "auction_format": "AUCTION",
                "currency": "GBP",
                "start_price": Decimal("99.99"),
                "final_price": Decimal("99.99"),
                "final_price_usd": Decimal("99.99"),
                "total_usd": Decimal("99.99"),
            },
            {
                "marketplace": "buyee",
                "listing_id": "k1244337001",
                "currency": "JPY",
                "final_price": Decimal("6255"),
                "final_price_usd": Decimal("42.10"),
                "total_usd": Decimal("42.10"),
            },
        ]
    )
    applied = apply_gripsweat_official_usd(
        frame,
        {
            "800679041850": {
                "sold_price": Decimal("229.00"),
                "currency": "USD",
                "sold_at": date(2026, 9, 17),
            }
        },
    )
    ebay = applied[applied["listing_id"] == "800679041850"].iloc[0]
    buyee = applied[applied["listing_id"] == "k1244337001"].iloc[0]
    assert ebay["final_price"] == Decimal("99.99")
    assert ebay["final_price_usd"] == Decimal("99.99")
    assert ebay["total_usd"] == Decimal("99.99")
    assert ebay["_gripsweat_usd_reference"] == Decimal("229.00")
    assert ebay["_official_usd_source"] == "gripsweat-reference"
    assert buyee["_official_usd_source"] != "gripsweat-reference"


def test_apply_gripsweat_fills_empty_obo_hammer_and_keeps_ebay_ask() -> None:
    """Gripsweat sold amount is the OBO hammer; eBay ask stays start_price."""

    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "135283544011",
                "auction_format": "FIXED_PRICE_OBO",
                "currency": "USD",
                "start_price": Decimal("299.99"),
                "final_price": None,
                "final_price_usd": None,
                "total_usd": None,
            }
        ]
    )
    applied = apply_gripsweat_official_usd(
        frame,
        {
            "135283544011": {
                "sold_price": Decimal("299.99"),
                "currency": "USD",
                "sold_at": date(2026, 9, 13),
            }
        },
    )
    row = applied.iloc[0]
    assert row["start_price"] == Decimal("299.99")
    assert row["final_price"] == Decimal("299.99")
    assert row["tax_amount"] == Decimal("18.75")
    assert row["gross_price"] == Decimal("318.74")
    assert row["_official_usd_source"] == "gripsweat-sold"


def test_apply_gripsweat_does_not_replace_accepted_obo_offer() -> None:
    """A stored accepted offer wins over a Gripsweat reprint of the ask."""

    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "377493856081",
                "auction_format": "FIXED_PRICE_OBO",
                "currency": "USD",
                "start_price": Decimal("50.00"),
                "final_price": Decimal("35.00"),
                "final_price_usd": Decimal("35.00"),
            }
        ]
    )
    applied = apply_gripsweat_official_usd(
        frame,
        {
            "377493856081": {
                "sold_price": Decimal("50.00"),
                "currency": "USD",
                "sold_at": date(2026, 9, 1),
            }
        },
    )
    row = applied.iloc[0]
    assert row["start_price"] == Decimal("50.00")
    assert row["final_price"] == Decimal("35.00")
    assert row["_gripsweat_usd_reference"] == Decimal("50.00")
    assert row["_official_usd_source"] == "gripsweat-reference"


def test_obo_hammer_uses_gripsweat_accepted_amount_not_the_ask() -> None:
    """Gripsweat prints the eBay ask, then the accepted Best Offer."""

    import pandas as pd

    from auction_etl.services.sold_item_overlap import official_usd_from_gripsweat_row

    raw = (
        "RARE 1980 Hong Kong TERESA TENG Hokkien Pop Greatest Hits LP VINYL "
        "$299.99 $229.00 (USD) Sep 13, 2026"
    )
    official = official_usd_from_gripsweat_row(
        {
            "sold_price": Decimal("299.99"),
            "currency": "USD",
            "sold_at": date(2026, 9, 13),
            "raw_text": raw,
        }
    )
    assert official is not None
    assert official[0] == Decimal("229.00")
    frame = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "135283544011",
                "auction_format": "FIXED_PRICE_OBO",
                "currency": "USD",
                "start_price": Decimal("299.99"),
                "final_price": Decimal("299.99"),
                "final_price_usd": Decimal("299.99"),
            },
            {
                "marketplace": "ebay",
                "listing_id": "bin-1",
                "auction_format": "FIXED_PRICE",
                "currency": "USD",
                "start_price": Decimal("80.00"),
                "final_price": Decimal("80.00"),
            },
        ]
    )
    applied = apply_gripsweat_official_usd(
        frame,
        {
            "135283544011": {
                "sold_price": Decimal("299.99"),
                "currency": "USD",
                "sold_at": date(2026, 9, 13),
                "raw_text": raw,
            },
            "bin-1": {
                "sold_price": Decimal("80.00"),
                "currency": "USD",
                "raw_text": "$90.00 $80.00 (USD)",
            },
        },
    )
    obo = applied[applied["listing_id"] == "135283544011"].iloc[0]
    bin_row = applied[applied["listing_id"] == "bin-1"].iloc[0]
    assert obo["start_price"] == Decimal("299.99")
    assert obo["final_price"] == Decimal("229.00")
    assert obo["tax_amount"] == Decimal("14.31")
    assert obo["gross_price"] == Decimal("243.31")
    assert obo["_official_usd_source"] == "gripsweat-sold"
    assert bin_row["final_price"] == Decimal("80.00")
    assert bin_row["_official_usd_source"] == "gripsweat-reference"


def test_apply_gripsweat_replaces_ask_stored_as_obo_hammer() -> None:
    """When eBay hammer is the ask, Gripsweat's different sold amount is the sale."""

    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "187864786670",
                "auction_format": "FIXED_PRICE_OBO",
                "currency": "USD",
                "start_price": Decimal("344.03"),
                "final_price": Decimal("344.42"),
                "final_price_usd": Decimal("344.42"),
            }
        ]
    )
    applied = apply_gripsweat_official_usd(
        frame,
        {
            "187864786670": {
                "sold_price": Decimal("260.00"),
                "currency": "GBP",
                "sold_at": date(2026, 9, 1),
            }
        },
    )
    row = applied.iloc[0]
    assert row["start_price"] == Decimal("344.03")
    assert row["final_price"] == Decimal("260.00")
    assert row["tax_amount"] == Decimal("16.25")
    assert row["gross_price"] == Decimal("276.25")
    assert row["_official_usd_source"] == "gripsweat-sold"
