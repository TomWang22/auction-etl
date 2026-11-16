"""One delivered copy dates the rest of its order."""

from datetime import date
from decimal import Decimal

from auction_etl.services.collection_import import ParsedPurchase
from auction_etl.services.collection_shelf import (
    LotCopy,
    inherit_lot_dates,
    lot_date_updates,
    lot_package_id,
    purchases_with_lot_paid_on,
    stamp_lot_dates,
)


def test_a_delivered_copy_dates_the_rest_of_its_order() -> None:
    order_id = "package:a+b+c"
    updates = lot_date_updates(
        [
            LotCopy("gripsweat", "a", order_id, date(2026, 2, 9), None),
            LotCopy(
                "gripsweat",
                "b",
                order_id,
                date(2026, 2, 4),
                date(2026, 2, 9),
            ),
            LotCopy("gripsweat", "c", order_id, date(2026, 2, 9), None),
            LotCopy("ebay", "solo", "20-11111-11111", date(2026, 1, 1), None),
        ]
    )
    assert {
        (copy.listing_id, copy.paid_on, copy.delivered_on) for copy in updates
    } == {
        ("a", date(2026, 2, 4), date(2026, 2, 9)),
        ("c", date(2026, 2, 4), date(2026, 2, 9)),
    }


def test_disagreeing_delivery_dates_are_left_alone() -> None:
    updates = lot_date_updates(
        [
            LotCopy("ebay", "a", "20-1", date(2026, 1, 1), date(2026, 1, 8)),
            LotCopy("ebay", "b", "20-1", date(2026, 1, 2), date(2026, 1, 9)),
            LotCopy("ebay", "c", "20-1", date(2026, 1, 3), None),
        ]
    )
    assert updates == []


def test_disagreeing_order_dates_still_share_the_delivery_date() -> None:
    updates = lot_date_updates(
        [
            LotCopy("ebay", "a", "20-1", date(2026, 1, 1), date(2026, 1, 8)),
            LotCopy("ebay", "b", "20-1", date(2026, 1, 2), date(2026, 1, 8)),
            LotCopy("ebay", "c", "20-1", date(2026, 1, 3), None),
        ]
    )
    assert len(updates) == 1
    assert updates[0].listing_id == "c"
    assert updates[0].paid_on == date(2026, 1, 3)
    assert updates[0].delivered_on == date(2026, 1, 8)


def test_a_paid_copy_dates_the_rest_of_its_order_before_delivery() -> None:
    """One combined Buyee lot shares the order date even if nothing is delivered yet."""

    order_id = "package:a+b+c"
    updates = lot_date_updates(
        [
            LotCopy("buyee", "a", order_id, date(2026, 9, 8), None),
            LotCopy("buyee", "b", order_id, None, None),
            LotCopy("buyee", "c", order_id, None, None),
            LotCopy("buyee", "solo", "package:z", None, None),
        ]
    )
    assert {
        (copy.listing_id, copy.paid_on, copy.delivered_on) for copy in updates
    } == {
        ("b", date(2026, 9, 8), None),
        ("c", date(2026, 9, 8), None),
    }


def test_incoming_copies_inherit_the_lot_paid_on() -> None:
    order_id = "package:a+b"
    dated = _purchase("a", order_id, date(2026, 9, 8), None)
    waiting = _purchase("b", order_id, None, None)
    inherited = inherit_lot_dates((waiting, dated))
    by_id = {purchase.external_id: purchase for purchase in inherited}
    assert by_id["a"].paid_on == date(2026, 9, 8)
    assert by_id["b"].paid_on == date(2026, 9, 8)
    assert by_id["b"].delivered_on is None


def test_lot_package_id_is_sorted_auction_ids() -> None:
    assert lot_package_id(["r1202755562", "e1202459064"]) == (
        "package:e1202459064+r1202755562"
    )


def test_bill_date_fills_an_undated_lot() -> None:
    """A combined order with no paid-on still takes the bill's billed-on date."""

    order_id = "package:a+b+c"
    updates = lot_date_updates(
        [
            LotCopy("buyee", "a", order_id, None, None),
            LotCopy("buyee", "b", order_id, None, None),
            LotCopy("buyee", "c", order_id, None, None),
        ],
        billed_on_by_order={order_id: date(2026, 9, 30)},
    )
    assert {
        (copy.listing_id, copy.paid_on) for copy in updates
    } == {
        ("a", date(2026, 9, 30)),
        ("b", date(2026, 9, 30)),
        ("c", date(2026, 9, 30)),
    }


def test_purchases_with_lot_paid_on_fills_a_single_copy() -> None:
    """A one-auction Buyee bill still takes the order date typed on intake."""

    purchase = _purchase("d1195885358", "package:d1195885358", None, None)
    dated = purchases_with_lot_paid_on((purchase,), paid_on=date(2026, 10, 1))
    assert dated[0].paid_on == date(2026, 10, 1)


def test_stamp_lot_dates_covers_a_single_copy() -> None:
    stamped = stamp_lot_dates(
        [LotCopy("buyee", "d1195885358", "package:d1195885358", None, None)],
        paid_on=date(2026, 10, 1),
    )
    assert len(stamped) == 1
    assert stamped[0].paid_on == date(2026, 10, 1)
    assert stamped[0].delivered_on is None


def test_purchases_with_lot_paid_on_fill_blank_editor_rows() -> None:
    order_id = "package:a+b"
    blank = _purchase("a", order_id, None, None)
    also_blank = _purchase("b", order_id, None, None)
    dated = purchases_with_lot_paid_on(
        (blank, also_blank),
        paid_on=date(2026, 9, 8),
    )
    assert {row.paid_on for row in dated} == {date(2026, 9, 8)}


def test_stamp_lot_dates_covers_the_whole_order() -> None:
    copies = [
        LotCopy("buyee", "a", "package:a+b+c", None, None),
        LotCopy("buyee", "b", "package:a+b+c", None, None),
        LotCopy("buyee", "c", "package:a+b+c", None, None),
    ]
    stamped = stamp_lot_dates(copies, paid_on=date(2026, 9, 8))
    assert {copy.listing_id for copy in stamped} == {"a", "b", "c"}
    assert {copy.paid_on for copy in stamped} == {date(2026, 9, 8)}


def test_stamp_lot_dates_subset_is_only_when_explicit() -> None:
    copies = [
        LotCopy("buyee", "a", "package:a+b+c", None, None),
        LotCopy("buyee", "b", "package:a+b+c", None, None),
        LotCopy("buyee", "c", "package:a+b+c", None, None),
    ]
    whole = stamp_lot_dates(
        copies, paid_on=date(2026, 9, 8), selected_ids=["a", "b"]
    )
    assert {copy.listing_id for copy in whole} == {"a", "b", "c"}
    subset = stamp_lot_dates(
        copies,
        paid_on=date(2026, 9, 8),
        selected_ids=["a", "b"],
        explicit=True,
    )
    assert {copy.listing_id for copy in subset} == {"a", "b"}


def test_incoming_copies_inherit_the_delivered_sibling() -> None:
    order_id = "20-14224-85378"
    dated = _purchase("b", order_id, date(2026, 2, 4), date(2026, 2, 9))
    waiting = _purchase("a", order_id, date(2026, 2, 9), None)
    other = _purchase("z", "20-99999-99999", date(2026, 3, 1), None)
    inherited = inherit_lot_dates((waiting, dated, other))
    by_id = {purchase.external_id: purchase for purchase in inherited}
    assert by_id["a"].paid_on == date(2026, 2, 4)
    assert by_id["a"].delivered_on == date(2026, 2, 9)
    assert by_id["b"].paid_on == date(2026, 2, 4)
    assert by_id["z"].delivered_on is None


def _purchase(
    external_id: str,
    order_id: str,
    paid_on: date | None,
    delivered_on: date | None,
) -> ParsedPurchase:
    return ParsedPurchase(
        source="ebay",
        external_id=external_id,
        title=external_id,
        seller="seller",
        paid_amount=Decimal("10.00"),
        paid_currency="USD",
        paid_on=paid_on,
        catalog_number=None,
        order_id=order_id,
        delivered_on=delivered_on,
    )
