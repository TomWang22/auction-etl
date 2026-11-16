"""Package split, shelf matching, and collection bill rows."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from auction_etl.services.collection_billing import (
    COLLECTION_BILL_DDL,
    COLLECTION_MEDIA_LABELS,
    BillLine,
    allocate_package_charges,
    anatomy_gaps,
    bill_disagreements,
    billing_gaps,
    collection_bulk_lot,
    collection_media_code,
    collection_media_label,
    copy_charge_layout,
    match_bill_to_shelf,
    closest_unfilled_copy,
    media_asks_disc_count,
    next_unfilled_copy,
    package_bill_from_copies,
    plan_collection_bill,
    extracted_delivered_on,
    order_copies_by_artist,
    preview_shelf_bills,
    match_record_city_bill_to_shelf,
)


def test_ebay_three_item_combined_shipping_sums_to_the_order() -> None:
    shares = allocate_package_charges(
        [Decimal("120.50"), Decimal("120.50"), Decimal("91.00")],
        shipping=Decimal("54.00"),
        tax=Decimal("20.75"),
    )
    assert len(shares) == 3
    ship = sum((row[0] for row in shares), Decimal("0"))
    tax = sum((row[1] for row in shares), Decimal("0"))
    assert ship == Decimal("54.00")
    assert tax == Decimal("20.75")
    assert shares[0][0] == shares[1][0]
    assert shares[2][0] == Decimal("54.00") - shares[0][0] - shares[1][0]


SHELF = [
    {
        "marketplace": "gripsweat",
        "listing_id": "236601326474",
        "catalog_number": "2427329",
        "seller": "teresa-teng",
        "paid": Decimal("179.99"),
        "paid_on": date(2026, 10, 5),
    },
    {
        "marketplace": "ebay",
        "listing_id": "999",
        "catalog_number": "2427329",
        "seller": "ryanb714",
        "paid": Decimal("160.00"),
        "paid_on": date(2026, 9, 30),
    },
    {
        "marketplace": "buyee",
        "listing_id": "f1204890335",
        "catalog_number": "SOLL170",
        "seller": "Buyee",
        "paid": Decimal("110"),
        "paid_on": date(2026, 9, 1),
    },
]


def test_ebay_item_number_matches_gripsweat_not_another_catalog() -> None:
    hit = match_bill_to_shelf(
        printed_id="236601326474",
        source="ebay",
        selected=None,
        rows=SHELF,
    )
    assert hit is not None
    assert hit["marketplace"] == "gripsweat"


def test_ebay_totals_card_without_item_number_uses_selected_row() -> None:
    selected = SHELF[1]
    hit = match_bill_to_shelf(
        printed_id="detail:160:176.50",
        source="ebay",
        selected=selected,
        rows=SHELF,
    )
    assert hit is selected


def test_record_city_receipt_finds_the_owned_copy_by_catalog_and_price() -> None:
    """The shelf keeps the shop line id. The receipt still names the catalog."""

    shelf = [
        {
            "marketplace": "recordcity",
            "listing_id": "2503945",
            "catalog_number": "SOLL-170",
            "paid": Decimal("579"),
            "paid_on": date(2025, 7, 22),
        },
        {
            "marketplace": "recordcity",
            "listing_id": "2587198",
            "catalog_number": "SOLL-141",
            "paid": Decimal("580"),
            "paid_on": date(2025, 7, 22),
        },
        {
            "marketplace": "buyee",
            "listing_id": "f1204890335",
            "catalog_number": "SOLL-170",
            "paid": Decimal("440"),
            "paid_on": None,
        },
    ]
    purchase = SimpleNamespace(
        source="recordcity",
        external_id="SOLL170:2025-07-22:579.00",
        catalog_number="SOLL 170",
        paid_amount=Decimal("579"),
        paid_on=date(2025, 7, 22),
    )
    hit = match_record_city_bill_to_shelf(purchase, shelf)
    assert hit is not None
    assert hit["listing_id"] == "2503945"
    matched, missed = preview_shelf_bills([purchase], shelf, selected=None)
    assert missed == []
    assert matched[0]["row"]["listing_id"] == "2503945"


def test_two_record_city_copies_of_the_same_price_are_not_guessed() -> None:
    shelf = [
        {
            "marketplace": "recordcity",
            "listing_id": "1128270",
            "catalog_number": "06SH 62",
            "paid": Decimal("449"),
            "paid_on": date(2025, 8, 13),
        },
        {
            "marketplace": "recordcity",
            "listing_id": "3562387",
            "catalog_number": "06SH 62",
            "paid": Decimal("449"),
            "paid_on": date(2025, 8, 13),
        },
    ]
    purchase = SimpleNamespace(
        source="recordcity",
        external_id="missing",
        catalog_number="06SH-62",
        paid_amount=Decimal("449"),
        paid_on=date(2025, 8, 13),
    )
    assert match_record_city_bill_to_shelf(purchase, shelf) is None


def test_buyee_unmatched_package_line_does_not_use_selected_row() -> None:
    selected = SHELF[2]
    hit = match_bill_to_shelf(
        printed_id="missing-auction",
        source="buyee",
        selected=selected,
        rows=SHELF,
        package=True,
    )
    assert hit is None


def test_collection_bill_ddl_has_separate_line_table_and_lookup_indexes() -> None:
    sql = COLLECTION_BILL_DDL
    assert "warehouse.collection_bill" in sql
    assert "warehouse.collection_bill_line" in sql
    assert "fulfillment_status" in sql
    assert "account_id, listing_id" in sql
    assert "ON DELETE CASCADE" in sql
    script = Path("scripts/upgrade_collector_review_schema.py").read_text(encoding="utf-8")
    assert "COLLECTION_BILL_DDL" in script


def test_planned_bill_lines_sum_to_package_totals() -> None:
    shares = [
        BillLine("ebay", "1", "1", Decimal("120.50"), Decimal("19.61"), Decimal("7.53"), Decimal("0"), "n"),
        BillLine("ebay", "2", "2", Decimal("120.50"), Decimal("19.61"), Decimal("7.53"), Decimal("0"), "n"),
        BillLine("ebay", "3", "3", Decimal("91.00"), Decimal("14.78"), Decimal("5.69"), Decimal("0"), "n"),
    ]
    bill, lines = plan_collection_bill(
        account_id="acct",
        source="ebay",
        external_order_id="08-14198-02534",
        currency="USD",
        item_total=Decimal("332.00"),
        shipping_total=Decimal("54.00"),
        tax_total=Decimal("20.75"),
        fee_total=Decimal("0"),
        grand_total=Decimal("406.75"),
        raw_note="...",
        fulfillment_status="delivered",
        lines=shares,
    )
    assert sum(line.shipping_amount for line in lines) == Decimal("54.00")
    assert bill["grand_total"] == Decimal("406.75")


def test_combined_totals_card_is_the_package_header() -> None:
    copies = [
        BillLine(
            "gripsweat",
            "326150009894",
            "326150009894",
            Decimal("179.99"),
            Decimal("5.53"),
            Decimal("11.25"),
            Decimal("0"),
            "n",
        ),
        BillLine(
            "gripsweat",
            "326150109657",
            "326150109657",
            Decimal("159.99"),
            Decimal("4.91"),
            Decimal("10.00"),
            Decimal("0"),
            "n",
        ),
    ]
    bill, written = package_bill_from_copies(
        account_id="acct",
        source="ebay",
        order_id="20-14224-85378",
        currency="USD",
        package_item=Decimal("339.98"),
        package_shipping=Decimal("10.44"),
        package_tax=Decimal("21.25"),
        package_total=Decimal("371.67"),
        raw_note="2 items $339.98\nShipping $10.44\nTax* $21.25\nOrder total $371.67",
        billed_on=date(2026, 2, 14),
        lines=copies,
    )
    assert bill["external_order_id"] == "20-14224-85378"
    assert bill["item_total"] == Decimal("339.98")
    assert bill["shipping_total"] == Decimal("10.44")
    assert bill["tax_total"] == Decimal("21.25")
    assert bill["grand_total"] == Decimal("371.67")
    assert sum(line.shipping_amount for line in written) == Decimal("10.44")
    assert sum(line.item_amount for line in written) == Decimal("339.98")


def test_buyee_lot_keeps_printed_international_on_the_package_card() -> None:
    """Domestic on each copy is not the lot's Japan-to-you postage."""

    copies = [
        BillLine(
            "buyee",
            "f1204890335",
            "f1204890335",
            Decimal("440"),
            Decimal("880"),
            Decimal("0"),
            Decimal("800"),
            "Domestic shipping 880 JPY",
        ),
        BillLine(
            "buyee",
            "r1205744646",
            "r1205744646",
            Decimal("1001"),
            Decimal("880"),
            Decimal("0"),
            Decimal("800"),
            "Domestic shipping 880 JPY",
        ),
    ]
    bill, written = package_bill_from_copies(
        account_id="acct",
        source="buyee",
        order_id="package:f1204890335+r1205744646",
        currency="JPY",
        package_item=Decimal("1441"),
        package_shipping=Decimal("10176"),
        package_tax=Decimal("1105"),
        package_total=Decimal("28324"),
        raw_note="Items 1441 JPY\nShipping 10176 JPY\nTax 1105 JPY\nOrder total 28324 JPY",
        billed_on=date(2025, 8, 20),
        lines=copies,
    )
    assert bill["shipping_total"] == Decimal("10176")
    assert bill["tax_total"] == Decimal("1105")
    assert bill["grand_total"] == Decimal("28324")
    assert bill["item_total"] == Decimal("1441")
    assert sum(line.shipping_amount for line in written) == Decimal("1760")


def test_anatomy_gaps_cover_pressing_and_edition_not_notes() -> None:
    row = {
        "manual_region": "Hong Kong",
        "manual_condition_media": "EX",
        "manual_condition_cover": "EX",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_completeness_notes": "",
        "media_type": "LP",
    }
    gaps = anatomy_gaps(row)
    assert "Catalog" in gaps
    assert "Region" not in gaps
    assert "Disc count" in gaps
    assert "Pressing type" in gaps
    assert "Insert" in gaps
    assert "Poster" in gaps
    assert "Rental" in gaps
    assert "Sealed" in gaps
    assert "Record" not in gaps
    filled = {
        "manual_catalog_number": "2427374",
        "manual_region": "Hong Kong",
        "manual_disc_count": 1,
        "manual_pressing_type": "FIRST_PRESSING",
        "manual_condition_media": "EX",
        "manual_condition_cover": "EX",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_insert_present": True,
        "manual_poster_present": False,
        "manual_rental": False,
        "manual_sealed": False,
        "manual_completeness_notes": "",
        "media_type": "LP",
    }
    assert anatomy_gaps(filled) == []
    cd = dict(filled)
    cd["media_type"] = "CD"
    cd["manual_poster_present"] = None
    assert "Poster" not in anatomy_gaps(cd)


def test_shelf_media_types_are_the_formats_on_the_shelf() -> None:
    assert COLLECTION_MEDIA_LABELS == (
        "Automatic / unset",
        "LP",
        "EP",
        "CD",
        "Cassette",
        "DVD",
        "Laserdisc",
        "Box set",
        "LP bulk lot",
        "EP bulk lot",
        "CD bulk lot",
        "Cassette bulk lot",
        "Mixed bulk lot",
        "Bulk lot",
    )
    assert collection_media_code("EP") == "EP_7_INCH"
    assert collection_media_code("Box set") == "LP_BOX_SET"
    assert collection_media_code("Box set", stored="CD_BOX_SET") == "CD_BOX_SET"
    assert collection_media_code("Mixed bulk lot") == "MIXED_BULK_LOT"
    assert collection_media_code("LP bulk lot") == "LP_BULK_LOT"
    assert collection_media_label("EP_7_INCH") == "EP"
    assert collection_media_label("LASERDISC") == "Laserdisc"
    assert collection_media_label("CD_BOX_SET") == "Box set"
    assert collection_media_label("MIXED_BULK_LOT") == "Mixed bulk lot"
    assert collection_bulk_lot("MIXED_BULK_LOT") is True
    assert collection_bulk_lot("LP") is False
    assert media_asks_disc_count("LP") is True
    assert media_asks_disc_count("CD") is True
    assert media_asks_disc_count("LP_BOX_SET") is True
    assert media_asks_disc_count("LP_BULK_LOT") is False
    box = {
        "manual_catalog_number": "70AH 1141~3",
        "manual_region": "Japan",
        "manual_pressing_type": "FIRST_PRESSING",
        "manual_condition_media": "EX",
        "manual_condition_cover": "EX",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_insert_present": True,
        "manual_poster_present": False,
        "manual_rental": False,
        "manual_sealed": False,
        "manual_obi": False,
        "media_type": "LP_BOX_SET",
    }
    assert "Disc count" in anatomy_gaps(box)
    box["manual_disc_count"] = 3
    assert anatomy_gaps(box) == []
    laserdisc = dict(box)
    laserdisc["media_type"] = "LASERDISC"
    laserdisc["manual_disc_count"] = 1
    laserdisc["manual_poster_present"] = None
    assert "Disc count" not in anatomy_gaps(laserdisc)
    assert "Poster" not in anatomy_gaps(laserdisc)
    unset = {"manual_catalog_number": "SOLD-90"}
    assert "Media type" in anatomy_gaps(unset)
    pile = {
        "media_type": "MIXED_BULK_LOT",
        "manual_condition_media": "VG+",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_disc_count": 8,
    }
    assert anatomy_gaps(pile) == []
    empty_pile = {"media_type": "LP_BULK_LOT"}
    gaps = anatomy_gaps(empty_pile)
    assert "Catalog" not in gaps
    assert "Region" not in gaps
    assert "Pressing type" not in gaps
    assert "Insert" not in gaps
    assert "Poster" not in gaps
    assert "Obi" not in gaps
    assert "Lot count" in gaps
    assert "Lot condition" in gaps
    assert "Verdict" in gaps


def test_japan_unset_obi_is_a_gap_hong_kong_is_not() -> None:
    japan = {
        "manual_region": "Japan",
        "manual_media_type": "LP",
        "manual_obi": None,
        "manual_condition_media": "A",
        "manual_condition_cover": "A",
        "manual_verdict": "Buy",
    }
    hk = {
        "manual_region": "Hong Kong",
        "manual_media_type": "LP",
        "manual_obi": None,
        "manual_condition_media": "A",
        "manual_condition_cover": "A",
        "manual_verdict": "Buy",
    }
    assert "Obi" in anatomy_gaps(japan)
    assert "Obi" not in anatomy_gaps(hk)


def test_japan_obi_yes_or_no_counts_as_filled() -> None:
    """A Japan copy with no strip still has an answer. Only Automatic / unset is a gap."""

    base = {
        "manual_region": "Japan",
        "manual_catalog_number": "MR-3091",
        "manual_disc_count": 1,
        "manual_pressing_type": "PROMO_SAMPLE",
        "manual_condition_media": "VG+",
        "manual_condition_cover": "VG+",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_insert_present": True,
        "manual_poster_present": True,
        "manual_rental": False,
        "manual_sealed": False,
        "media_type": "LP",
    }
    assert "Obi" in anatomy_gaps({**base, "manual_obi": None})
    assert anatomy_gaps({**base, "manual_obi": False}) == []
    assert anatomy_gaps({**base, "manual_obi": True}) == []


def test_ebay_totals_card_does_not_overwrite_selected_buyee_copy() -> None:
    """An eBay card without an item number stays off a selected Buyee copy."""

    enka = {
        "marketplace": "buyee",
        "listing_id": "m1233352030",
        "paid": Decimal("102.40"),
        "paid_on": date(2025, 6, 30),
    }
    tokyo = {
        "marketplace": "ebay",
        "listing_id": "276699429249",
        "paid": Decimal("55.00"),
        "paid_on": date(2025, 6, 30),
    }
    hit = match_bill_to_shelf(
        printed_id="",
        source="ebay",
        selected=enka,
        rows=[enka, tokyo],
    )
    assert hit is None
    hit = match_bill_to_shelf(
        printed_id="276699429249",
        source="ebay",
        selected=enka,
        rows=[enka, tokyo],
    )
    assert hit is not None
    assert hit["listing_id"] == "276699429249"


def test_two_item_totals_card_does_not_use_selected_gripsweat_row() -> None:
    selected = SHELF[0]
    hit = match_bill_to_shelf(
        printed_id="package:2:339.98:371.67",
        source="ebay",
        selected=selected,
        rows=SHELF,
        package=True,
    )
    assert hit is None
    purchases = [SimpleNamespace(source="ebay", external_id="package:2:339.98:371.67")]
    matched, missed = preview_shelf_bills(purchases, SHELF, selected=selected)
    assert matched == []
    assert missed == []


def test_feb_ebay_order_is_not_the_oct_gripsweat_copy() -> None:
    purchase = SimpleNamespace(
        paid_on=date(2026, 2, 14),
        seller="professorsells",
        paid_amount=Decimal("196.46"),
    )
    clashes = bill_disagreements(purchase, SHELF[0])
    assert any("2026-02-14" in item and "2026-10-05" in item for item in clashes)
    assert any("professorsells" in item and "teresa-teng" in item for item in clashes)
    assert any("196.46" in item and "179.99" in item for item in clashes)


def test_one_known_item_on_combined_order_matches_gripsweat() -> None:
    shelf = [
        {
            "marketplace": "gripsweat",
            "listing_id": "326150009894",
            "seller": "teresa-teng",
            "paid": Decimal("179.99"),
            "paid_on": date(2026, 10, 5),
        }
    ]
    purchases = [
        SimpleNamespace(
            source="ebay",
            external_id="326150009894",
            paid_on=date(2026, 2, 14),
            seller="professorsells",
            paid_amount=Decimal("179.99"),
        )
    ]
    matched, missed = preview_shelf_bills(purchases, shelf, selected=shelf[0])
    assert len(matched) == 1
    assert matched[0]["row"]["listing_id"] == "326150009894"
    assert missed == []
    clashes = bill_disagreements(purchases[0], shelf[0])
    assert any("2026-02-14" in item and "2026-10-05" in item for item in clashes)


def test_ebay_history_order_number_matches_the_copy_by_date_and_landed() -> None:
    shelf = [
        {
            "marketplace": "ebay",
            "listing_id": "336089377666",
            "catalog_number": "OOAH-1021",
            "seller": "nakameshi",
            "paid": Decimal("157.00"),
            "paid_on": date(2025, 8, 8),
            "shipping_amount": Decimal("7.77"),
            "tax_amount": Decimal("9.81"),
            "fee_amount": None,
        },
        {
            "marketplace": "ebay",
            "listing_id": "127241444356",
            "catalog_number": "APT-208",
            "seller": "hanabi358",
            "paid": Decimal("93.00"),
            "paid_on": date(2025, 7, 31),
            "shipping_amount": None,
            "tax_amount": Decimal("5.81"),
            "fee_amount": None,
        },
    ]
    purchases = [
        SimpleNamespace(
            source="ebay",
            external_id="10-13426-54807",
            title="Momoe Legend Model Number 00AH 1021 5 CBS SONY",
            paid_on=date(2025, 8, 8),
            paid_amount=Decimal("174.58"),
        ),
        SimpleNamespace(
            source="ebay",
            external_id="09-13393-63262",
            title="Yamaguchi Momoe Legend Star LP 5-Disc Set, 60 Songs k5",
            paid_on=date(2025, 7, 31),
            paid_amount=Decimal("98.81"),
        ),
    ]
    matched, missed = preview_shelf_bills(purchases, shelf, selected=None)
    by_id = {pair["row"]["listing_id"]: pair["purchase"].title for pair in matched}
    assert by_id["336089377666"] == "Momoe Legend Model Number 00AH 1021 5 CBS SONY"
    assert "Legend Star" in by_id["127241444356"]
    assert missed == []


def test_preview_matches_one_gripsweat_row_and_skips_the_rest() -> None:
    purchases = [
        SimpleNamespace(source="ebay", external_id="236601326474"),
        SimpleNamespace(source="ebay", external_id="366150834599"),
        SimpleNamespace(source="ebay", external_id="236601327666"),
    ]
    matched, missed = preview_shelf_bills(purchases, SHELF, selected=SHELF[2])
    assert len(matched) == 1
    assert matched[0]["row"]["marketplace"] == "gripsweat"
    assert set(missed) == {"366150834599", "236601327666"}


def test_next_unfilled_copy_walks_past_the_one_just_billed() -> None:
    rows = [
        {
            "marketplace": "ebay",
            "listing_id": "376818029801",
            "paid": Decimal("80.00"),
            "shipping_amount": None,
            "tax_amount": None,
            "fee_amount": None,
            "billing_note": "",
        },
        {
            "marketplace": "ebay",
            "listing_id": "257284486279",
            "paid": Decimal("50.00"),
            "shipping_amount": None,
            "tax_amount": None,
            "fee_amount": None,
            "billing_note": "",
        },
        {
            "marketplace": "gripsweat",
            "listing_id": "326150009894",
            "paid": Decimal("179.99"),
            "shipping_amount": Decimal("5.53"),
            "tax_amount": Decimal("11.25"),
            "fee_amount": Decimal("0"),
            "billing_note": "Shipping 5.53 USD",
        },
    ]
    nxt = next_unfilled_copy(
        rows,
        after=rows[0],
        filled={("ebay", "376818029801")},
    )
    assert nxt is not None
    assert nxt["listing_id"] == "257284486279"
    done = next_unfilled_copy(
        rows,
        after=rows[1],
        filled={("ebay", "376818029801"), ("ebay", "257284486279")},
    )
    assert done is None


def test_next_unfilled_copy_wraps_to_the_first_open_row() -> None:
    rows = [
        {
            "marketplace": "ebay",
            "listing_id": "326240058248",
            "paid": Decimal("160.00"),
            "shipping_amount": None,
            "tax_amount": None,
            "fee_amount": None,
            "billing_note": "",
        },
        {
            "marketplace": "ebay",
            "listing_id": "376818029801",
            "paid": Decimal("80.00"),
            "shipping_amount": Decimal("20.00"),
            "tax_amount": Decimal("5.00"),
            "fee_amount": Decimal("0"),
            "billing_note": "Shipping 20 USD",
        },
        {
            "marketplace": "ebay",
            "listing_id": "336586954923",
            "paid": Decimal("110.72"),
            "shipping_amount": None,
            "tax_amount": None,
            "fee_amount": None,
            "billing_note": "",
        },
    ]
    nxt = next_unfilled_copy(
        rows,
        after=rows[2],
        filled={("ebay", "336586954923")},
    )
    assert nxt is not None
    assert nxt["listing_id"] == "326240058248"


def test_billing_gaps_treats_nan_charges_as_missing() -> None:
    assert billing_gaps(
        {
            "paid": Decimal("80.00"),
            "shipping_amount": float("nan"),
            "tax_amount": float("nan"),
            "fee_amount": float("nan"),
            "billing_note": "",
        }
    ) == ["Shipping", "Tax", "Fees"]


def test_blank_sale_type_is_a_billing_gap_until_labeled() -> None:
    from auction_etl.services.collection_billing import (
        effective_sale_type,
        shelf_copy_filled,
    )

    unlabeled = {
        "paid": Decimal("68.00"),
        "shipping_amount": Decimal("4.66"),
        "tax_amount": Decimal("4.25"),
        "fee_amount": Decimal("0"),
        "billing_note": "Shipping 4.66 USD",
        "marketplace": "ebay",
        "sale_type": "",
        "stored_sale_type": "",
        "manual_catalog_number": "CAL-04-1029",
        "manual_region": "Hong Kong",
        "manual_disc_count": 1,
        "manual_pressing_type": "Original",
        "manual_condition_media": "VG+",
        "manual_condition_cover": "VG+",
        "manual_verdict": "Keep",
        "manual_obi": False,
        "manual_insert_present": True,
        "manual_poster_present": False,
        "manual_rental": False,
        "manual_sealed": False,
    }
    assert "Sale type" in billing_gaps(unlabeled)
    assert shelf_copy_filled(unlabeled) is False
    labeled = {**unlabeled, "sale_type": "FIXED_PRICE_OBO"}
    assert "Sale type" not in billing_gaps(labeled)
    assert effective_sale_type(
        marketplace="buyee",
        stored="AUCTION",
        manual="",
    ) == "AUCTION"
    assert effective_sale_type(
        marketplace="gripsweat",
        stored="AUCTION",
        manual="",
    ) == "AUCTION"
    assert effective_sale_type(
        marketplace="gripsweat",
        stored="AUCTION",
        manual="FIXED_PRICE",
    ) == "FIXED_PRICE"


def test_one_item_card_does_not_stack_charges_on_the_order_total() -> None:
    layout = copy_charge_layout(
        paid=Decimal("110.72"),
        shipping=Decimal("4.47"),
        tax=Decimal("6.25"),
        fees=Decimal("0"),
        package_item=Decimal("100.00"),
        package_shipping=Decimal("4.47"),
        package_tax=Decimal("6.25"),
        package_total=Decimal("110.72"),
    )
    assert layout["item"] == Decimal("100.00")
    assert layout["shipping"] == Decimal("4.47")
    assert layout["tax"] == Decimal("6.25")
    assert layout["landed"] == Decimal("110.72")
    assert layout["combined"] is False


def test_combined_share_keeps_the_item_and_adds_the_share() -> None:
    layout = copy_charge_layout(
        paid=Decimal("179.99"),
        shipping=Decimal("5.53"),
        tax=Decimal("11.25"),
        fees=Decimal("0"),
        package_item=Decimal("339.98"),
        package_shipping=Decimal("10.44"),
        package_tax=Decimal("21.25"),
        package_total=Decimal("371.67"),
    )
    assert layout["item"] == Decimal("179.99")
    assert layout["landed"] == Decimal("196.77")
    assert layout["combined"] is True


def test_buyee_yen_header_is_not_a_combined_order_share() -> None:
    """USD item vs yen invoice totals is one copy, not a package split."""

    layout = copy_charge_layout(
        paid=Decimal("102.40"),
        shipping=Decimal("4630"),
        tax=Decimal("1852"),
        fees=Decimal("2200"),
        package_item=Decimal("15375"),
        package_shipping=Decimal("4630"),
        package_tax=Decimal("1852"),
        package_total=Decimal("23057"),
    )
    assert layout["combined"] is False
    assert layout["item"] == Decimal("102.40")


def test_standalone_item_plus_postage_when_paid_is_the_item() -> None:
    layout = copy_charge_layout(
        paid=Decimal("80.00"),
        shipping=Decimal("20.00"),
        tax=Decimal("5.00"),
        fees=Decimal("0"),
        package_item=Decimal("80.00"),
        package_shipping=Decimal("20.00"),
        package_tax=Decimal("5.00"),
        package_total=Decimal("105.00"),
    )
    assert layout["item"] == Decimal("80.00")
    assert layout["landed"] == Decimal("105.00")
    assert layout["combined"] is False


def _filled_copy(listing_id: str) -> dict:
    return {
        "marketplace": "gripsweat",
        "listing_id": listing_id,
        "sale_type": "AUCTION",
        "paid": Decimal("10.00"),
        "shipping_amount": Decimal("1.00"),
        "tax_amount": Decimal("1.00"),
        "fee_amount": Decimal("0"),
        "billing_note": "Shipping 1 USD",
        "manual_catalog_number": "MR-1",
        "manual_region": "Hong Kong",
        "manual_disc_count": 1,
        "manual_pressing_type": "FIRST_PRESSING",
        "manual_condition_media": "EX",
        "manual_condition_cover": "EX",
        "manual_verdict": "REFERENCE_ONLY",
        "manual_insert_present": True,
        "manual_poster_present": False,
        "manual_rental": False,
        "manual_sealed": False,
        "media_type": "LP",
    }


def _open_copy(listing_id: str) -> dict:
    return {
        "marketplace": "gripsweat",
        "listing_id": listing_id,
        "paid": Decimal("10.00"),
    }


def test_closest_unfilled_copy_is_the_nearest_open_row() -> None:
    current = _filled_copy("current")
    near = _open_copy("near")
    far = _open_copy("far")
    rows = [current, near, _filled_copy("done"), far]
    nxt = closest_unfilled_copy(rows, current=current)
    assert nxt is not None
    assert nxt["listing_id"] == "near"


def test_closest_unfilled_copy_prefers_the_emptier_row_at_the_same_distance() -> None:
    above = {
        **_filled_copy("above"),
        "sale_type": "",
        "stored_sale_type": "",
    }
    current = _filled_copy("current")
    below = _open_copy("below")
    rows = [above, current, below]
    nxt = closest_unfilled_copy(rows, current=current)
    assert nxt is not None
    assert nxt["listing_id"] == "below"


def test_closest_unfilled_copy_continues_downward_when_the_gaps_match() -> None:
    current = _filled_copy("current")
    rows = [_open_copy("above"), current, _open_copy("below")]
    nxt = closest_unfilled_copy(rows, current=current)
    assert nxt is not None
    assert nxt["listing_id"] == "below"


def test_closest_unfilled_copy_leaves_a_shelf_that_is_otherwise_filled() -> None:
    current = _open_copy("current")
    rows = [_filled_copy("done"), current, _filled_copy("also")]
    assert closest_unfilled_copy(rows, current=current) is None


def test_artists_follow_the_oldest_acquisition() -> None:
    rows = [
        {"section": "Anita Mui", "paid_on": "2024-12-04", "listing_id": "anita-later"},
        {"section": "Teresa Teng", "paid_on": "2025-01-16", "listing_id": "teng-new"},
        {"section": "Anita Mui", "paid_on": "2024-10-01", "listing_id": "anita-first"},
        {"section": "Teresa Teng", "paid_on": "2024-12-03", "listing_id": "teng-old"},
        {"section": "Teresa Teng", "paid_on": None, "listing_id": "teng-undated"},
    ]
    ordered = [row["listing_id"] for row in order_copies_by_artist(rows)]
    assert ordered == [
        "anita-first",
        "anita-later",
        "teng-old",
        "teng-new",
        "teng-undated",
    ]


def test_extracted_delivery_date_fills_a_copy_that_has_none() -> None:
    row = {"listing_id": "356335023487"}
    purchase = SimpleNamespace(
        external_id="356335023487",
        delivered_on=date(2024, 12, 13),
    )
    other = SimpleNamespace(
        external_id="111",
        delivered_on=date(2024, 1, 1),
    )
    assert extracted_delivered_on(row, [other, purchase]) == date(2024, 12, 13)
    assert extracted_delivered_on(row, [other]) is None
