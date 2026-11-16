"""Collection bills: split, match, and persist apart from listing postage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.collection_acquisition import effective_sale_type
from auction_etl.services.discogs_identity import fold_catalog

_CENTS = Decimal("0.01")
_EBAY_MARKETS = frozenset({"ebay", "gripsweat"})
_DISCOGS_MARKETS = frozenset({"discogs", "log"})


COLLECTION_BILL_DDL = """
CREATE TABLE IF NOT EXISTS warehouse.collection_bill (
    id bigserial PRIMARY KEY,
    account_id uuid NOT NULL,
    source varchar NOT NULL,
    external_order_id varchar,
    currency varchar NOT NULL,
    item_total numeric(18, 2),
    shipping_total numeric(18, 2),
    tax_total numeric(18, 2),
    fee_total numeric(18, 2),
    grand_total numeric(18, 2),
    raw_note text NOT NULL DEFAULT '',
    billed_on date,
    fulfillment_status varchar,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS collection_bill_account_source_order_idx
    ON warehouse.collection_bill (account_id, source, external_order_id)
    WHERE external_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS collection_bill_account_billed_idx
    ON warehouse.collection_bill (account_id, billed_on DESC);

CREATE TABLE IF NOT EXISTS warehouse.collection_bill_line (
    id bigserial PRIMARY KEY,
    bill_id bigint NOT NULL REFERENCES warehouse.collection_bill (id) ON DELETE CASCADE,
    account_id uuid NOT NULL,
    marketplace varchar NOT NULL,
    listing_id varchar NOT NULL,
    printed_id varchar,
    item_amount numeric(18, 2),
    shipping_amount numeric(18, 2),
    tax_amount numeric(18, 2),
    fee_amount numeric(18, 2),
    line_note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS collection_bill_line_copy_idx
    ON warehouse.collection_bill_line (account_id, marketplace, listing_id, created_at DESC);

CREATE INDEX IF NOT EXISTS collection_bill_line_bill_idx
    ON warehouse.collection_bill_line (bill_id);

CREATE INDEX IF NOT EXISTS collection_bill_line_printed_idx
    ON warehouse.collection_bill_line (account_id, printed_id);

CREATE INDEX IF NOT EXISTS auction_collector_account_purchased_date_idx
    ON warehouse.auction_collector (account_id, manual_purchased, manual_purchase_date DESC);

CREATE INDEX IF NOT EXISTS auction_collector_account_listing_idx
    ON warehouse.auction_collector (account_id, listing_id);

CREATE INDEX IF NOT EXISTS owned_copy_account_paid_idx
    ON warehouse.owned_copy (account_id, paid_on DESC);
"""


def allocate_package_charges(
    item_amounts: list[Decimal],
    shipping: Decimal,
    tax: Decimal,
    fees: Decimal = Decimal("0"),
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Split shared postage by item price. The last row takes the remainder."""

    if not item_amounts:
        return []
    weights = [amount if amount is not None else Decimal("0") for amount in item_amounts]
    ships = _weighted_parts(shipping, weights)
    taxes = _weighted_parts(tax, weights)
    fee_parts = _weighted_parts(fees, weights)
    return list(zip(ships, taxes, fee_parts, strict=True))


def _weighted_parts(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    count = len(weights)
    mass = sum(weights, Decimal("0"))
    if mass == 0:
        equal = (total / Decimal(count)).quantize(_CENTS) if count else Decimal("0")
        parts = [equal] * max(count - 1, 0)
        if count:
            parts.append(total - sum(parts, Decimal("0")))
        return parts
    parts: list[Decimal] = []
    running = Decimal("0")
    last = count - 1
    for index, weight in enumerate(weights):
        if index == last:
            parts.append(total - running)
            continue
        share = (total * weight / mass).quantize(_CENTS)
        parts.append(share)
        running += share
    return parts


def match_bill_to_shelf(
    *,
    printed_id: str,
    source: str,
    selected: dict[str, object] | None,
    rows: list[dict[str, object]],
    package: bool = False,
) -> dict[str, object] | None:
    """Find the shelf copy for a printed auction or item id. No catalog matching."""

    wanted = str(printed_id or "").strip()
    origin = str(source or "").strip().lower()
    if wanted.lower().startswith(("detail:", "package:")):
        wanted = ""
    if not wanted:
        if package:
            return None
        if selected is not None:
            market = str(selected.get("marketplace") or "").strip().lower()
            if origin == "ebay" and market not in _EBAY_MARKETS:
                return None
            if origin == "buyee" and market != "buyee":
                return None
        return selected
    for row in rows:
        listing = str(row.get("listing_id") or "").strip()
        market = str(row.get("marketplace") or "").strip().lower()
        if listing != wanted:
            continue
        if origin == "ebay" and market in _EBAY_MARKETS:
            return row
        if origin == "buyee" and market == "buyee":
            return row
        if origin == "discogs" and market in _DISCOGS_MARKETS:
            return row
        if origin and market == origin:
            return row
    if origin == "buyee" and not package:
        return selected
    return None


def match_record_city_bill_to_shelf(
    purchase: Any,
    rows: list[dict[str, object]],
) -> dict[str, object] | None:
    """Find the owned copy when the receipt line id is missing.

    Record City stores the shop line id. A pasted receipt still has the
    catalog and yen price. One unique catalog+price hits that copy. Two
    copies of the same catalog at the same price stay unmatched.
    """

    if str(getattr(purchase, "source", "") or "").strip().lower() != "recordcity":
        return None
    catalog = fold_catalog(getattr(purchase, "catalog_number", None))
    amount = _as_money(getattr(purchase, "paid_amount", None))
    if not catalog or amount is None:
        return None
    wanted_on = _purchase_day(getattr(purchase, "paid_on", None))
    wanted_on_text = wanted_on.isoformat() if wanted_on is not None else ""
    hits: list[dict[str, object]] = []
    dated: list[dict[str, object]] = []
    for row in rows:
        market = str(row.get("marketplace") or "").strip().lower()
        if market != "recordcity":
            continue
        if fold_catalog(str(row.get("catalog_number") or "")) != catalog:
            continue
        paid = _as_money(row.get("paid"))
        if paid != amount:
            continue
        hits.append(row)
        if wanted_on_text and _row_paid_on(row) == wanted_on_text:
            dated.append(row)
    if len(dated) == 1:
        return dated[0]
    if len(hits) == 1:
        return hits[0]
    return None


@dataclass(frozen=True)
class BillLine:
    """One shelf copy inside a collection bill."""

    marketplace: str
    listing_id: str
    printed_id: str
    item_amount: Decimal
    shipping_amount: Decimal
    tax_amount: Decimal
    fee_amount: Decimal
    line_note: str


def plan_collection_bill(
    *,
    account_id: str,
    source: str,
    external_order_id: str | None,
    currency: str,
    item_total: Decimal,
    shipping_total: Decimal,
    tax_total: Decimal,
    fee_total: Decimal,
    grand_total: Decimal,
    raw_note: str,
    fulfillment_status: str | None,
    lines: list[BillLine],
) -> tuple[dict[str, object], list[BillLine]]:
    """Check allocated lines sum to the package totals (one cent slack)."""

    ship = sum((line.shipping_amount for line in lines), Decimal("0"))
    tax = sum((line.tax_amount for line in lines), Decimal("0"))
    fees = sum((line.fee_amount for line in lines), Decimal("0"))
    slack = Decimal("0.01")
    if abs(ship - shipping_total) > slack:
        raise ValueError("Allocated shipping does not sum to the bill.")
    if abs(tax - tax_total) > slack:
        raise ValueError("Allocated tax does not sum to the bill.")
    if abs(fees - fee_total) > slack:
        raise ValueError("Allocated fees do not sum to the bill.")
    bill = {
        "account_id": account_id,
        "source": source,
        "external_order_id": external_order_id,
        "currency": currency,
        "item_total": item_total,
        "shipping_total": shipping_total,
        "tax_total": tax_total,
        "fee_total": fee_total,
        "grand_total": grand_total,
        "raw_note": raw_note,
        "fulfillment_status": fulfillment_status,
    }
    return bill, list(lines)


def package_bill_from_copies(
    *,
    account_id: str,
    source: str,
    order_id: str | None,
    currency: str,
    package_item: Decimal | None,
    package_shipping: Decimal | None,
    package_tax: Decimal | None,
    package_total: Decimal | None,
    raw_note: str,
    billed_on: object = None,
    fulfillment_status: str | None = "delivered",
    lines: list[BillLine],
) -> tuple[dict[str, object], list[BillLine]]:
    """Header is the combined totals card. Lines are each copy’s share."""

    item_total = package_item
    if item_total is None:
        item_total = sum((line.item_amount for line in lines), Decimal("0"))
    shipping_total = package_shipping
    if shipping_total is None:
        shipping_total = sum((line.shipping_amount for line in lines), Decimal("0"))
    tax_total = package_tax
    if tax_total is None:
        tax_total = sum((line.tax_amount for line in lines), Decimal("0"))
    fee_total = sum((line.fee_amount for line in lines), Decimal("0"))
    grand_total = package_total
    if grand_total is None:
        grand_total = item_total + shipping_total + tax_total + fee_total
    try:
        bill, written = plan_collection_bill(
            account_id=account_id,
            source=source,
            external_order_id=order_id,
            currency=currency,
            item_total=item_total,
            shipping_total=shipping_total,
            tax_total=tax_total,
            fee_total=fee_total,
            grand_total=grand_total,
            raw_note=raw_note,
            fulfillment_status=fulfillment_status,
            lines=lines,
        )
    except ValueError:
        # Buyee lots keep domestic on the copy and international on the card.
        # The printed package totals stay on the header.
        bill = {
            "account_id": account_id,
            "source": source,
            "external_order_id": order_id,
            "currency": currency,
            "item_total": item_total,
            "shipping_total": shipping_total,
            "tax_total": tax_total,
            "fee_total": fee_total,
            "grand_total": grand_total,
            "raw_note": raw_note,
            "fulfillment_status": fulfillment_status,
        }
        written = list(lines)
        bill["package_item"] = item_total
        bill["package_shipping"] = shipping_total
        bill["package_tax"] = tax_total
        bill["package_total"] = grand_total
    bill["billed_on"] = billed_on
    return bill, written


def preview_shelf_bills(
    purchases: list[Any],
    shelf_rows: list[dict[str, object]],
    selected: dict[str, object] | None,
) -> tuple[list[dict[str, object]], list[str]]:
    """Pair each parsed purchase with a shelf row. Unmatched ids are skipped."""

    package = len(purchases) > 1 or any(
        str(getattr(purchase, "external_id", "") or "").lower().startswith("package:")
        for purchase in purchases
    )
    matched: list[dict[str, object]] = []
    missed: list[str] = []
    for purchase in purchases:
        printed = str(getattr(purchase, "external_id", "") or "")
        source = str(getattr(purchase, "source", "") or "")
        hit = match_bill_to_shelf(
            printed_id=printed,
            source=source,
            selected=None if package else selected,
            rows=shelf_rows,
            package=package,
        )
        if hit is None:
            hit = match_ebay_history_card_to_shelf(purchase, shelf_rows)
        if hit is None:
            hit = match_record_city_bill_to_shelf(purchase, shelf_rows)
        if hit is None:
            if printed and not printed.lower().startswith("package:"):
                missed.append(printed)
            continue
        matched.append({"row": hit, "purchase": purchase})
    return matched, missed


def _purchase_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def order_copies_by_artist(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """One artist, then the next. The artist bought first comes first.

    Inside an artist, the oldest paid-on date comes first. A copy with no
    date stays at the end of that artist.
    """

    def paid(row: dict[str, object]) -> date | None:
        value = row.get("paid_on")
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()[:10]
        if text in {"", "NaT", "None", "nan", "NaN"}:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    oldest: dict[str, date] = {}
    decorated: list[tuple[str, date | None, int, dict[str, object]]] = []
    for index, row in enumerate(rows):
        section = str(row.get("section") or "").strip() or "Unknown"
        day = paid(row)
        decorated.append((section, day, index, row))
        if day is not None and (section not in oldest or day < oldest[section]):
            oldest[section] = day
    missing = date.max
    decorated.sort(
        key=lambda item: (
            oldest.get(item[0], missing),
            item[0].casefold(),
            item[1] or missing,
            item[2],
        )
    )
    return [item[3] for item in decorated]


def extracted_delivered_on(
    row: dict[str, object],
    purchases: list[Any],
) -> date | None:
    """Delivery date the current bill extracted for this listing."""

    listing = str(row.get("listing_id") or "").strip()
    if not listing:
        return None
    for purchase in purchases:
        external = str(getattr(purchase, "external_id", "") or "").strip()
        if external != listing:
            continue
        delivered = _purchase_day(getattr(purchase, "delivered_on", None))
        if delivered is not None:
            return delivered
    return None


def match_ebay_history_card_to_shelf(
    purchase: Any,
    rows: list[dict[str, object]],
) -> dict[str, object] | None:
    """Purchase history has the title and order number, not the item number.

    The listing may be gone. Match the unique shelf copy with the same
    paid-on date and the order total as item or landed.
    """

    printed = str(getattr(purchase, "external_id", "") or "")
    if str(getattr(purchase, "source", "") or "").strip().lower() != "ebay":
        return None
    if not _is_ebay_order_number(printed):
        return None
    paid_on = getattr(purchase, "paid_on", None)
    amount = getattr(purchase, "paid_amount", None)
    if paid_on is None or amount is None:
        return None
    wanted_on = (
        paid_on.isoformat() if isinstance(paid_on, date) else str(paid_on)[:10]
    )
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None
    hits: list[dict[str, object]] = []
    for row in rows:
        market = str(row.get("marketplace") or "").strip().lower()
        if market not in _EBAY_MARKETS:
            continue
        if _row_paid_on(row) != wanted_on:
            continue
        item = _as_money(row.get("paid"))
        landed = _row_landed(row)
        if item == amount or landed == amount:
            hits.append(row)
    if len(hits) == 1:
        return hits[0]
    return None


def _is_ebay_order_number(printed: str) -> bool:
    parts = printed.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 2
        and parts[0].isdigit()
        and parts[1].isdigit()
        and parts[2].isdigit()
    )


def _as_money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _row_paid_on(row: dict[str, object]) -> str:
    value = row.get("paid_on")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def _row_landed(row: dict[str, object]) -> Decimal | None:
    item = _as_money(row.get("paid"))
    if item is None:
        return None
    extra = Decimal("0")
    for key in ("shipping_amount", "tax_amount", "fee_amount"):
        part = _as_money(row.get(key))
        if part is not None:
            extra += part
    return item + extra


def bill_disagreements(purchase: Any, row: dict[str, object]) -> list[str]:
    """Date, seller, or item amount on the bill is not this shelf copy."""

    issues: list[str] = []
    bill_on = getattr(purchase, "paid_on", None)
    shelf_on = _row_date(row.get("paid_on"))
    if isinstance(bill_on, datetime):
        bill_on = bill_on.date()
    if isinstance(bill_on, date) and shelf_on is not None and bill_on != shelf_on:
        issues.append(
            f"Bill acquired {bill_on.isoformat()}, shelf says {shelf_on.isoformat()}."
        )
    bill_seller = str(getattr(purchase, "seller", "") or "").strip()
    shelf_seller = str(row.get("seller") or "").strip()
    if (
        bill_seller
        and shelf_seller
        and bill_seller.casefold() != shelf_seller.casefold()
    ):
        issues.append(f"Bill seller {bill_seller}, shelf {shelf_seller}.")
    bill_amount = getattr(purchase, "paid_amount", None)
    shelf_amount = _row_money(row.get("paid"))
    if (
        isinstance(bill_amount, Decimal)
        and shelf_amount is not None
        and abs(bill_amount - shelf_amount) > Decimal("0.01")
    ):
        issues.append(f"Bill item {bill_amount}, shelf {shelf_amount}.")
    return issues


def _row_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _row_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


_NO_POSTER_MEDIA = {
    "CD",
    "CD_BOX_SET",
    "CASSETTE",
    "CASSETTE_BOX_SET",
    "EP_7_INCH",
    "DVD",
    "LASERDISC",
    "MAGAZINE",
    "PHOTO",
}
_BOX_SET_MEDIA = frozenset(
    {"LP_BOX_SET", "CD_BOX_SET", "CASSETTE_BOX_SET", "BOX_SET"}
)
COLLECTION_MEDIA_LABELS = (
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
_COLLECTION_MEDIA_CODES = {
    "LP": "LP",
    "EP": "EP_7_INCH",
    "CD": "CD",
    "Cassette": "CASSETTE",
    "DVD": "DVD",
    "Laserdisc": "LASERDISC",
    "Box set": "LP_BOX_SET",
    "LP bulk lot": "LP_BULK_LOT",
    "EP bulk lot": "EP_BULK_LOT",
    "CD bulk lot": "CD_BULK_LOT",
    "Cassette bulk lot": "CASSETTE_BULK_LOT",
    "Mixed bulk lot": "MIXED_BULK_LOT",
    "Bulk lot": "BULK_LOT",
}
_COLLECTION_MEDIA_LABEL_FOR_CODE = {
    "LP": "LP",
    "VINYL": "LP",
    "SINGLE_12_INCH": "LP",
    "12_INCH_SINGLE": "LP",
    "EP_7_INCH": "EP",
    "CD": "CD",
    "SHM_CD": "CD",
    "SACD": "CD",
    "BLU_SPEC_CD": "CD",
    "CD_SINGLE_8CM": "CD",
    "CASSETTE": "Cassette",
    "DVD": "DVD",
    "LASERDISC": "Laserdisc",
    "VHS": "DVD",
    "LP_BULK_LOT": "LP bulk lot",
    "EP_BULK_LOT": "EP bulk lot",
    "CD_BULK_LOT": "CD bulk lot",
    "CASSETTE_BULK_LOT": "Cassette bulk lot",
    "MIXED_BULK_LOT": "Mixed bulk lot",
    "MAGAZINE_BULK_LOT": "Bulk lot",
    "BULK_LOT": "Bulk lot",
}
_BULK_LOT_MEDIA = frozenset(
    {
        "LP_BULK_LOT",
        "EP_BULK_LOT",
        "CD_BULK_LOT",
        "CASSETTE_BULK_LOT",
        "MIXED_BULK_LOT",
        "MAGAZINE_BULK_LOT",
        "BULK_LOT",
    }
)


def collection_media_code(
    label: object,
    stored: object = None,
) -> str | None:
    """Stored media code for the shelf form. Box set keeps a CD or cassette box."""

    text = str(label or "").strip()
    if text in {"", "Automatic / unset"}:
        return None
    if text == "Box set":
        kept = str(stored or "").strip()
        if kept.upper() in _BOX_SET_MEDIA:
            return kept
        return "LP_BOX_SET"
    return _COLLECTION_MEDIA_CODES.get(text)


def collection_media_label(code: object) -> str:
    """Shelf menu label for a stored media code."""

    text = str(code or "").strip()
    if not text:
        return "Automatic / unset"
    upper = text.upper()
    if upper in _BOX_SET_MEDIA:
        return "Box set"
    return _COLLECTION_MEDIA_LABEL_FOR_CODE.get(upper, "Automatic / unset")


def collection_bulk_lot(media: object) -> bool:
    """True for a pile of copies, not one pressing."""

    return str(media or "").strip().upper() in _BULK_LOT_MEDIA


def media_asks_disc_count(media: object) -> bool:
    """A single pressing asks how many discs. A bulk lot counts copies instead."""

    return not collection_bulk_lot(media)


def anatomy_gaps(row: dict[str, object]) -> list[str]:
    """Ingest fields still unset on this copy. Notes are not a gate."""

    gaps: list[str] = []
    region = str(row.get("manual_region") or row.get("region") or "").strip()
    media = str(row.get("manual_media_type") or row.get("media_type") or "").strip()
    if collection_bulk_lot(media):
        discs = row.get("manual_disc_count")
        if discs is None or _is_unset(discs):
            gaps.append("Lot count")
        else:
            try:
                if int(discs) <= 0:
                    gaps.append("Lot count")
            except (TypeError, ValueError):
                gaps.append("Lot count")
        if _is_unset(row.get("manual_condition_media") or row.get("condition_media")):
            gaps.append("Lot condition")
        if _is_unset(row.get("manual_verdict") or row.get("verdict")):
            gaps.append("Verdict")
        return gaps
    if _is_unset(media):
        gaps.append("Media type")
    if _is_unset(row.get("manual_catalog_number") or row.get("catalog_number")):
        gaps.append("Catalog")
    if _is_unset(region):
        gaps.append("Region")
    if media_asks_disc_count(media):
        discs = row.get("manual_disc_count")
        if discs is None or _is_unset(discs):
            gaps.append("Disc count")
        else:
            try:
                if int(discs) <= 0:
                    gaps.append("Disc count")
            except (TypeError, ValueError):
                gaps.append("Disc count")
    if _is_unset(row.get("manual_pressing_type")):
        gaps.append("Pressing type")
    if _is_unset(row.get("manual_condition_media") or row.get("condition_media")):
        gaps.append("Record")
    if _is_unset(row.get("manual_condition_cover") or row.get("condition_cover")):
        gaps.append("Jacket")
    if _is_unset(row.get("manual_verdict") or row.get("verdict")):
        gaps.append("Verdict")
    if region == "Japan" and _is_unset(_filled_value(row.get("manual_obi"), row.get("obi"))):
        gaps.append("Obi")
    if _is_unset(row.get("manual_insert_present")):
        gaps.append("Insert")
    poster_media = str(
        row.get("manual_media_type") or row.get("media_type") or ""
    ).upper()
    if poster_media not in _NO_POSTER_MEDIA and _is_unset(
        row.get("manual_poster_present")
    ):
        gaps.append("Poster")
    if _is_unset(row.get("manual_rental")):
        gaps.append("Rental")
    if _is_unset(row.get("manual_sealed")):
        gaps.append("Sealed")
    return gaps


def shelf_copy_filled(row: dict[str, object]) -> bool:
    """Record anatomy plus a sale type. Delivery date is not a gate."""

    if anatomy_gaps(row):
        return False
    return bool(
        effective_sale_type(
            marketplace=row.get("marketplace"),
            stored=row.get("stored_sale_type"),
            manual=row.get("sale_type"),
        )
    )


def billing_gaps(row: dict[str, object]) -> list[str]:
    """Paid is enough that in-process or delivered is fine. Charges may still be missing."""

    gaps: list[str] = []
    paid = row.get("paid") if "paid" in row else row.get("manual_purchase_price")
    if paid is None or str(paid).strip() in {"", "0", "0.0", "0.00"}:
        gaps.append("Paid")
    else:
        shipping = row.get("shipping_amount")
        tax = row.get("tax_amount")
        fees = row.get("fee_amount")
        note = str(row.get("billing_note") or row.get("line_note") or "")
        charges_missing = (
            _is_unset(shipping)
            and _is_unset(tax)
            and _is_unset(fees)
            and "Shipping" not in note
            and "Tax" not in note
        )
        if charges_missing and not row.get("confirmed_no_extra_charges"):
            gaps.extend(["Shipping", "Tax", "Fees"])
    if "sale_type" in row and not effective_sale_type(
        marketplace=row.get("marketplace"),
        stored=row.get("stored_sale_type"),
        manual=row.get("sale_type"),
    ):
        gaps.append("Sale type")
    return gaps


def _open_gap_count(row: dict[str, object]) -> int:
    """How much of the record is still unset. A filled copy scores zero."""

    gaps = len(anatomy_gaps(row))
    if not effective_sale_type(
        marketplace=row.get("marketplace"),
        stored=row.get("stored_sale_type"),
        manual=row.get("sale_type"),
    ):
        gaps += 1
    return gaps


def closest_unfilled_copy(
    rows: list[dict[str, object]],
    *,
    current: dict[str, object],
) -> dict[str, object] | None:
    """Nearest other shelf row that is still not filled.

    Distance is the row's place on the shelf. When two rows are the same
    distance away, the one with more gaps wins, then the row after this one.
    """

    current_key = (
        str(current.get("marketplace") or "").strip().lower(),
        str(current.get("listing_id") or "").strip(),
    )
    identities = [
        (
            str(row.get("marketplace") or "").strip().lower(),
            str(row.get("listing_id") or "").strip(),
        )
        for row in rows
    ]
    start = identities.index(current_key) if current_key in identities else -1
    best: dict[str, object] | None = None
    best_distance = 0
    best_gaps = 0
    best_index = -1
    for index, row in enumerate(rows):
        if identities[index] == current_key:
            continue
        if shelf_copy_filled(row):
            continue
        distance = abs(index - start)
        gaps = _open_gap_count(row)
        nearer = best is None or distance < best_distance
        emptier = (
            best is not None
            and distance == best_distance
            and gaps > best_gaps
        )
        following = (
            best is not None
            and distance == best_distance
            and gaps == best_gaps
            and index > start
            and best_index < start
        )
        if nearer or emptier or following:
            best = row
            best_distance = distance
            best_gaps = gaps
            best_index = index
    return best


def next_unfilled_copy(
    rows: list[dict[str, object]],
    *,
    after: dict[str, object] | None = None,
    filled: set[tuple[str, str]] | None = None,
) -> dict[str, object] | None:
    """Next shelf copy still missing shipping/tax, after the one just billed."""

    skipped = {
        (str(market or "").strip().lower(), str(listing or "").strip())
        for market, listing in (filled or set())
    }
    identities = [
        (
            str(row.get("marketplace") or "").strip().lower(),
            str(row.get("listing_id") or "").strip(),
        )
        for row in rows
    ]
    start = 0
    if after is not None:
        after_key = (
            str(after.get("marketplace") or "").strip().lower(),
            str(after.get("listing_id") or "").strip(),
        )
        if after_key in identities:
            start = identities.index(after_key) + 1
    count = len(rows)
    for offset in range(count):
        index = (start + offset) % count
        row = rows[index]
        if identities[index] in skipped:
            continue
        if billing_gaps(row):
            return row
    return None


def copy_charge_layout(
    *,
    paid: Decimal | None,
    shipping: Decimal | None,
    tax: Decimal | None,
    fees: Decimal | None,
    package_item: Decimal | None = None,
    package_shipping: Decimal | None = None,
    package_tax: Decimal | None = None,
    package_total: Decimal | None = None,
) -> dict[str, Decimal | bool | None]:
    """Item, extras, and landed. Paid that equals the order total is not the item."""

    item = paid
    extras = _sum_charges(shipping, tax, fees)
    if (
        paid is not None
        and package_total is not None
        and abs(paid - package_total) <= _CENTS
        and extras > 0
    ):
        if package_item is not None and abs(package_item - paid) > _CENTS:
            item = package_item
        else:
            item = paid - extras
    landed = _sum_charges(item, shipping, tax, fees)
    combined = False
    if (
        package_shipping is not None
        and shipping is not None
        and abs(package_shipping - shipping) > _CENTS
    ):
        combined = True
    elif (
        package_tax is not None
        and tax is not None
        and abs(package_tax - tax) > _CENTS
    ):
        combined = True
    return {
        "item": item,
        "shipping": shipping,
        "tax": tax,
        "fees": fees,
        "landed": landed,
        "combined": combined,
    }


def _sum_charges(*values: Decimal | None) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is None:
            continue
        total += value
    return total


def _filled_value(*values: object) -> object:
    """First real answer. False (No) counts; None / blank does not."""

    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _is_unset(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    text = str(value).strip()
    if not text:
        return True
    return text.casefold() in {
        "automatic / unset",
        "none",
        "nan",
        "<na>",
        "nat",
    }


def collection_bill_statements(ddl: str = COLLECTION_BILL_DDL) -> list[str]:
    """Split the additive DDL so each statement can run on its own."""

    return [part.strip() for part in ddl.split(";") if part.strip()]


def ensure_collection_bill_tables(engine: Engine) -> None:
    """Create billing tables and lookup indexes if this warehouse lacks them."""

    with engine.begin() as connection:
        for statement in collection_bill_statements():
            connection.execute(text(statement))


def persist_collection_bill(
    engine: Engine,
    *,
    account_id: str,
    source: str,
    external_order_id: str | None,
    currency: str,
    item_total: Decimal | None,
    shipping_total: Decimal | None,
    tax_total: Decimal | None,
    fee_total: Decimal | None,
    grand_total: Decimal | None,
    raw_note: str,
    fulfillment_status: str | None,
    lines: list[BillLine],
    billed_on: object = None,
) -> int:
    """Upsert one order and replace its copy lines. Returns the bill id."""

    plan_collection_bill(
        account_id=account_id,
        source=source,
        external_order_id=external_order_id,
        currency=currency,
        item_total=item_total or Decimal("0"),
        shipping_total=shipping_total or Decimal("0"),
        tax_total=tax_total or Decimal("0"),
        fee_total=fee_total or Decimal("0"),
        grand_total=grand_total or Decimal("0"),
        raw_note=raw_note,
        fulfillment_status=fulfillment_status,
        lines=lines,
    )
    account = str(UUID(str(account_id)))
    ensure_collection_bill_tables(engine)
    with engine.begin() as connection:
        return write_collection_bill(
            connection,
            account_id=account,
            source=source,
            external_order_id=external_order_id,
            currency=currency,
            item_total=item_total,
            shipping_total=shipping_total,
            tax_total=tax_total,
            fee_total=fee_total,
            grand_total=grand_total,
            raw_note=raw_note,
            fulfillment_status=fulfillment_status,
            lines=lines,
            billed_on=billed_on,
        )


def write_collection_bill(
    connection: Any,
    *,
    account_id: str,
    source: str,
    external_order_id: str | None,
    currency: str,
    item_total: Decimal | None,
    shipping_total: Decimal | None,
    tax_total: Decimal | None,
    fee_total: Decimal | None,
    grand_total: Decimal | None,
    raw_note: str,
    fulfillment_status: str | None,
    lines: list[BillLine],
    billed_on: object = None,
) -> int:
    """Insert or replace one bill and its copy lines on an open connection."""

    payload = {
        "account_id": account_id,
        "source": source,
        "external_order_id": external_order_id,
        "currency": currency,
        "item_total": item_total,
        "shipping_total": shipping_total,
        "tax_total": tax_total,
        "fee_total": fee_total,
        "grand_total": grand_total,
        "raw_note": raw_note,
        "billed_on": billed_on,
        "fulfillment_status": fulfillment_status,
    }
    if external_order_id:
        bill_id = connection.execute(
            text(
                """
                INSERT INTO warehouse.collection_bill (
                    account_id, source, external_order_id, currency,
                    item_total, shipping_total, tax_total, fee_total,
                    grand_total, raw_note, billed_on, fulfillment_status
                )
                VALUES (
                    CAST(:account_id AS uuid), :source, :external_order_id,
                    :currency, :item_total, :shipping_total, :tax_total,
                    :fee_total, :grand_total, :raw_note, :billed_on,
                    :fulfillment_status
                )
                ON CONFLICT (account_id, source, external_order_id)
                WHERE external_order_id IS NOT NULL
                DO UPDATE SET
                    currency = EXCLUDED.currency,
                    item_total = EXCLUDED.item_total,
                    shipping_total = EXCLUDED.shipping_total,
                    tax_total = EXCLUDED.tax_total,
                    fee_total = EXCLUDED.fee_total,
                    grand_total = EXCLUDED.grand_total,
                    raw_note = EXCLUDED.raw_note,
                    billed_on = EXCLUDED.billed_on,
                    fulfillment_status = EXCLUDED.fulfillment_status,
                    updated_at = now()
                RETURNING id
                """
            ),
            payload,
        ).scalar_one()
    else:
        bill_id = connection.execute(
            text(
                """
                INSERT INTO warehouse.collection_bill (
                    account_id, source, external_order_id, currency,
                    item_total, shipping_total, tax_total, fee_total,
                    grand_total, raw_note, billed_on, fulfillment_status
                )
                VALUES (
                    CAST(:account_id AS uuid), :source, NULL,
                    :currency, :item_total, :shipping_total, :tax_total,
                    :fee_total, :grand_total, :raw_note, :billed_on,
                    :fulfillment_status
                )
                RETURNING id
                """
            ),
            payload,
        ).scalar_one()
    connection.execute(
        text("DELETE FROM warehouse.collection_bill_line WHERE bill_id = :bill_id"),
        {"bill_id": bill_id},
    )
    for line in lines:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.collection_bill_line (
                    bill_id, account_id, marketplace, listing_id, printed_id,
                    item_amount, shipping_amount, tax_amount, fee_amount, line_note
                )
                VALUES (
                    :bill_id, CAST(:account_id AS uuid), :marketplace, :listing_id,
                    :printed_id, :item_amount, :shipping_amount, :tax_amount,
                    :fee_amount, :line_note
                )
                """
            ),
            {
                "bill_id": bill_id,
                "account_id": account_id,
                "marketplace": line.marketplace,
                "listing_id": line.listing_id,
                "printed_id": line.printed_id,
                "item_amount": line.item_amount,
                "shipping_amount": line.shipping_amount,
                "tax_amount": line.tax_amount,
                "fee_amount": line.fee_amount,
                "line_note": line.line_note,
            },
        )
    return int(bill_id)
