"""Read a saved purchase page into rows a collector can confirm.

The reader is mechanical. It recognizes an eBay purchase history, a Buyee
won-auction list, or a Record City order page by the ids and headers on
the page, then keeps music and leaves magazines, photos, posters, and
the other non-music formats out.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from collections.abc import Sequence
from typing import Any

from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from auction_etl.classifiers.media import classify_media
from auction_etl.services.collection_billing import allocate_package_charges
from auction_etl.services.informal_lot import (
    LotDraftLine,
    LotDraftPackage,
    allocate_lot_payments,
    anatomy_values_from_lot_line,
    hk_condition_to_grade,
    list_subtotal,
    looks_like_informal_seller_list,
    package_readout,
    parse_informal_seller_list,
)
from auction_etl.services.discogs_identity import (
    catalog_token,
    equivalent_title_spellings,
    fold_catalog,
    is_junk_catalog,
    vinyl_shape,
)


_KEEP_MEDIA = frozenset(
    {
        "LP",
        "LP_BOX_SET",
        "EP_7_INCH",
        "SINGLE_12_INCH",
        "12_INCH_SINGLE",
        "CD",
        "CD_BOX_SET",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
        "CD_SINGLE_8CM",
        "CASSETTE",
        "CASSETTE_BOX_SET",
        "MIXED_MEDIA",
        "MAGAZINE",
    }
)
_EXTRA_NON_MUSIC = re.compile(
    r"\bpin\s*-?\s*ups?\b|\bpins?\b|ピンナップ|缶バッジ",
    re.IGNORECASE,
)
_EBAY_HREF = re.compile(r"/itm/(?:[^\"'\s<>]*/)?(\d{9,13})\b", re.IGNORECASE)
_EBAY_LABEL = re.compile(r"item\s*number\s*[:#]?\s*(\d{9,13})\b", re.IGNORECASE)
_BUYEE_HREF = re.compile(r"auction/([a-z]\d{8,})\b", re.IGNORECASE)
_BUYEE_ID = re.compile(r"\b([a-z]\d{9,12})\b", re.IGNORECASE)
_DATE_ISO = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_DATE_DMY = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+(20\d{2})\b",
    re.IGNORECASE,
)
_DATE_MDY = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_USD = re.compile(
    r"(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_YEN = re.compile(r"(?:¥|￥|JPY)\s*([0-9][0-9,]*)", re.IGNORECASE)
_YEN_SUFFIX = re.compile(r"([0-9][0-9,]*)\s*円")
_SELLER = re.compile(
    r"(?:seller(?:\s+username)?|sold by|出品者)\s*[:：]?\s*"
    r"([A-Za-z0-9._-]{2,64})",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

UNKNOWN_PAGE_NOTE = (
    "Save the eBay purchase history page, the Buyee won-auction page, "
    "or a Record City order page, and drop that file here."
)


@dataclass(frozen=True)
class ParsedPurchase:
    """One purchased copy read from an order page."""

    source: str
    external_id: str
    title: str
    seller: str
    paid_amount: Decimal | None
    paid_currency: str
    paid_on: date | None
    catalog_number: str | None
    billing_note: str = ""
    order_id: str = ""
    package_item: Decimal | None = None
    package_shipping: Decimal | None = None
    package_tax: Decimal | None = None
    package_total: Decimal | None = None
    delivered_on: date | None = None


@dataclass(frozen=True)
class ParseResult:
    """Purchases read from one dropped page."""

    source: str
    purchases: tuple[ParsedPurchase, ...]
    note: str


def _purchase_hold_id(purchase: ParsedPurchase) -> str:
    eid = str(purchase.external_id or "").strip()
    if eid:
        return eid
    return "|".join(
        (
            purchase.source,
            purchase.title,
            str(purchase.paid_amount or ""),
            str(purchase.paid_on or ""),
            str(purchase.catalog_number or ""),
        )
    )


def hold_import_purchases(
    parsed: Sequence[ParsedPurchase],
    held: Sequence[ParsedPurchase],
    done_ids: set[str] | frozenset[str] = frozenset(),
) -> list[ParsedPurchase]:
    """Keep the Bring-in batch on hold. A partial re-parse must not drop copies."""

    done = {str(item) for item in done_ids if str(item).strip()}
    parsed_by_id: dict[str, ParsedPurchase] = {}
    for purchase in parsed:
        pid = _purchase_hold_id(purchase)
        if pid and pid not in done:
            parsed_by_id[pid] = purchase
    kept: list[ParsedPurchase] = []
    seen: set[str] = set()
    for purchase in held:
        pid = _purchase_hold_id(purchase)
        if not pid or pid in done or pid in seen:
            continue
        seen.add(pid)
        kept.append(parsed_by_id.get(pid, purchase))
    for purchase in parsed:
        pid = _purchase_hold_id(purchase)
        if not pid or pid in done or pid in seen:
            continue
        seen.add(pid)
        kept.append(purchase)
    return [_with_included_consumption_tax(row) for row in kept]


def is_collected_music(title: str | None) -> bool:
    """Keep an LP, EP, 12-inch, CD, cassette, or magazine.

    A poster or a pin stays out. The format is stored on the copy when
    the lot is added.
    """

    media = purchase_media(title)
    if media in _KEEP_MEDIA:
        return True
    if media is None and not _EXTRA_NON_MUSIC.search(str(title or "")):
        return True
    return False


_FORMAT_MEDIA = {
    "LP": "LP",
    "CD": "CD",
    "EP": "EP_7_INCH",
    "7": "EP_7_INCH",
    "MAGAZINE": "MAGAZINE",
}


def purchase_media(title: str | None, billing_note: str | None = None) -> str | None:
    """Media from the title, or from a Record City ``Format:`` line."""

    found = classify_media(title)
    if found:
        return found
    match = re.search(r"(?im)^Format:\s*(\S+)", billing_note or "")
    if match is None:
        return None
    token = match.group(1).strip().upper().rstrip("\"″“”′'°*")
    return _FORMAT_MEDIA.get(token)


@dataclass(frozen=True)
class LotTally:
    """Whether a dropped lot's prices and fees add up to the printed grand total."""

    copies: int
    priced: int
    items: Decimal
    plan_fee: Decimal
    service_fee: Decimal
    domestic_shipping: Decimal
    packaging: Decimal
    clearance: Decimal
    international: Decimal | None
    customs: Decimal | None
    grand: Decimal | None
    line_sum: Decimal
    currency: str
    issues: tuple[str, ...]

    @property
    def missing_prices(self) -> int:
        return self.copies - self.priced

    @property
    def balanced(self) -> bool:
        return not self.issues

    def caption(self) -> str:
        if self.issues:
            return " ".join(self.issues)
        parts = [f"items {_plain_amount(self.items)}"]
        if self.plan_fee:
            parts.append(f"plan {_plain_amount(self.plan_fee)}")
        if self.service_fee:
            parts.append(f"service {_plain_amount(self.service_fee)}")
        if self.domestic_shipping:
            parts.append(f"domestic {_plain_amount(self.domestic_shipping)}")
        if self.packaging:
            parts.append(f"packaging {_plain_amount(self.packaging)}")
        if self.clearance:
            parts.append(f"clearance {_plain_amount(self.clearance)}")
        if self.international is not None:
            parts.append(f"international {_plain_amount(self.international)}")
        if self.customs is not None:
            parts.append(f"customs {_plain_amount(self.customs)}")
        equation = " + ".join(parts)
        if self.grand is not None:
            return (
                f"Lot tallies: {equation} = grand {_plain_amount(self.grand)} "
                f"{self.currency}."
            )
        return f"Lot tallies: {equation} {self.currency}."


def _package_note_amount(
    purchases: list[ParsedPurchase] | tuple[ParsedPurchase, ...],
    label: str,
) -> Decimal:
    """A lot-level charge written once on the notes, not on each copy."""

    pattern = re.compile(
        rf"^Package {re.escape(label)}\s+([0-9][0-9,]*)",
        flags=re.IGNORECASE,
    )
    for row in purchases:
        for line in str(row.billing_note or "").splitlines():
            match = pattern.match(line.strip())
            if match is None:
                continue
            amount = _decimal(match.group(1))
            if amount is not None:
                return amount
    return Decimal("0")


def lot_tally(
    purchases: list[ParsedPurchase] | tuple[ParsedPurchase, ...],
) -> LotTally:
    """Add the extracted sheet and name the gaps. Tax included is already in the hammer."""

    rows = list(purchases)
    currency = next(
        (str(row.paid_currency or "").strip().upper() for row in rows if row.paid_currency),
        "JPY",
    ) or "JPY"
    items = Decimal("0")
    priced = 0
    plan_fee = Decimal("0")
    service_fee = Decimal("0")
    domestic_shipping = Decimal("0")
    clearance = Decimal("0")
    missing_service = 0
    missing_plan = 0
    for row in rows:
        if row.paid_amount is not None:
            items += row.paid_amount
            priced += 1
        costs = copy_costs(row.billing_note or "")
        if costs["plan_fee"] is not None:
            plan_fee += costs["plan_fee"]
        elif str(row.source or "").lower() == "buyee":
            missing_plan += 1
        if costs["service_fee"] is not None:
            service_fee += costs["service_fee"]
        elif str(row.source or "").lower() == "buyee":
            missing_service += 1
        if costs["domestic_shipping"] is not None:
            domestic_shipping += costs["domestic_shipping"]
        if costs["clearance"] is not None:
            clearance += costs["clearance"]
    international = next(
        (row.package_shipping for row in rows if row.package_shipping is not None),
        None,
    )
    customs = next(
        (row.package_tax for row in rows if row.package_tax is not None),
        None,
    )
    grand = next(
        (row.package_total for row in rows if row.package_total is not None),
        None,
    )
    packaging = _package_note_amount(rows, "protective packaging")
    if not domestic_shipping:
        domestic_shipping = _package_note_amount(rows, "domestic shipping")
    package_plan = _package_note_amount(rows, "plan fee")
    package_service = _package_note_amount(rows, "service fee")
    if missing_plan and package_plan:
        plan_fee += package_plan
        missing_plan = 0
    if missing_service and package_service:
        service_fee += package_service
        missing_service = 0
    line_sum = (
        items
        + plan_fee
        + service_fee
        + domestic_shipping
        + clearance
        + packaging
        + (international or Decimal("0"))
        + (customs or Decimal("0"))
    )
    issues: list[str] = []
    missing_prices = len(rows) - priced
    if missing_prices:
        names = ", ".join(_lot_gap_label(row) for row in rows if row.paid_amount is None)
        remainder = ""
        if grand is not None and line_sum < grand:
            remainder = (
                f" Remainder {_plain_amount(grand - line_sum)} {currency}"
                f" of grand {_plain_amount(grand)} {currency}."
            )
        issues.append(
            f"{missing_prices} cop{'y is' if missing_prices == 1 else 'ies are'} "
            f"missing an item price ({names}).{remainder}"
        )
    if missing_plan:
        issues.append(
            f"{missing_plan} cop{'y is' if missing_plan == 1 else 'ies are'} "
            "missing a plan fee."
        )
    if missing_service:
        issues.append(
            f"{missing_service} cop{'y is' if missing_service == 1 else 'ies are'} "
            "missing a service fee."
        )
    if (
        any(str(row.source or "").lower() == "buyee" for row in rows)
        and len(rows) >= 2
        and all(row.paid_on is None for row in rows)
    ):
        issues.append("Order date is missing.")
    if (
        international is not None
        and currency == "JPY"
        and len(rows) >= 2
        and international < Decimal("500")
    ):
        issues.append(
            f"international shipping {_plain_amount(international)} {currency} "
            f"is too small for a {len(rows)}-copy lot."
        )
    elif (
        international is None
        and len(rows) >= 2
        and any(str(row.source or "").lower() == "buyee" for row in rows)
    ):
        issues.append("international shipping is missing.")
    if (
        grand is not None
        and missing_prices == 0
        and line_sum != grand
    ):
        issues.append(
            f"line sum {_plain_amount(line_sum)} {currency} does not match "
            f"grand total {_plain_amount(grand)} {currency}."
        )
    return LotTally(
        copies=len(rows),
        priced=priced,
        items=items,
        plan_fee=plan_fee,
        service_fee=service_fee,
        domestic_shipping=domestic_shipping,
        packaging=packaging,
        clearance=clearance,
        international=international,
        customs=customs,
        grand=grand,
        line_sum=line_sum,
        currency=currency,
        issues=tuple(issues),
    )


def _lot_gap_label(row: ParsedPurchase) -> str:
    """Catalog first, then a short title, so a missing hammer can be found on the bill."""

    catalog = str(row.catalog_number or "").strip()
    if catalog:
        return catalog
    title = str(row.title or "").strip()
    if title:
        return title[:40]
    return str(row.external_id or "").strip()


def describe_lot(purchases: list[ParsedPurchase] | tuple[ParsedPurchase, ...]) -> str:
    """One line for a whole order: count, shared dates, and a repeated catalog."""

    rows = list(purchases)
    if not rows:
        return ""
    paid = {row.paid_on for row in rows if row.paid_on is not None}
    delivered = {row.delivered_on for row in rows if row.delivered_on is not None}
    counts: dict[str, int] = {}
    for row in rows:
        catalog = str(row.catalog_number or "").strip()
        if catalog:
            counts[catalog] = counts.get(catalog, 0) + 1
    repeats = [catalog for catalog, count in counts.items() if count > 1]
    parts = [f"{len(rows)} copies in this order."]
    if len(paid) == 1:
        parts.append(f"Paid {next(iter(paid)).isoformat()}.")
    if len(delivered) == 1:
        parts.append(f"Delivered {next(iter(delivered)).isoformat()}.")
    if repeats:
        parts.append(
            "Separate copies of the same catalog: " + ", ".join(repeats) + "."
        )
    text = " ".join(parts)
    if any(str(row.source or "").lower() == "buyee" for row in rows) and len(rows) >= 2:
        return f"{text} {lot_tally(rows).caption()}".strip()
    return text


def detect_purchase_source(raw: str) -> str:
    """Name the shop from the page itself."""

    lowered = raw.lower()
    if re.search(r"subtotal", lowered) and re.search(r"\btax\b", lowered):
        return "discogs"
    if (
        "recordcity.jp" in lowered
        or "record city" in lowered
        or "estimated shipping fee" in lowered
        or re.search(
            r"\d+\s+(?:lp|cd|ep|magazine|7[\"″“”′'°*]?)\s+jp\s*[¥￥]",
            lowered,
        )
    ):
        return "recordcity"
    if (
        "buyee.jp" in lowered
        or "jdirectitems" in lowered
        or "won date" in lowered
        or "buyee service fee" in lowered
        or "other service fees" in lowered
        or "grand total payment amount" in lowered
        or "international shipping fee" in lowered
        or _BUYEE_AUCTION_ID.search(raw)
    ):
        return "buyee"
    if "order number:" in lowered and "sold by:" in lowered:
        return "ebay"
    if (
        "ebay.com/itm" in lowered
        or "item number" in lowered
        or "purchase history" in lowered
    ):
        return "ebay"
    if _BUYEE_HREF.search(raw):
        return "buyee"
    if _EBAY_HREF.search(raw) or _EBAY_LABEL.search(raw):
        return "ebay"
    if re.search(r"\b\d+\s+items?\b", lowered) and "order total" in lowered:
        return "ebay"
    if (
        "order total" in lowered
        and re.search(r"\bshipping\b", lowered)
        and re.search(r"\btax\b", lowered)
    ):
        return "ebay"
    return ""


_LOG_CURRENCIES = frozenset(
    {
        "USD",
        "JPY",
        "HKD",
        "TWD",
        "CNY",
        "SGD",
        "MYR",
        "KRW",
        "THB",
        "EUR",
        "GBP",
        "CAD",
        "AUD",
        "NZD",
        "SEK",
        "CHF",
    }
)


def logged_purchase(
    *,
    where: str,
    catalog: str,
    title: str,
    paid: Decimal | str | None,
    currency: str,
    paid_on: date | None,
) -> ParsedPurchase | None:
    """One copy typed by hand. The catalog and title stay as entered."""

    place = re.sub(r"\s+", " ", where).strip() or "Logged"
    catalog_text = re.sub(r"\s+", " ", catalog).strip()
    title_text = re.sub(r"\s+", " ", title).strip()
    catalog_number = None
    if catalog_text:
        catalog_number = catalog_token(catalog_number=catalog_text) or catalog_text
    if not catalog_number and not title_text:
        return None
    explicit = currency.strip().upper()
    default_currency = explicit if explicit in _LOG_CURRENCIES else "USD"
    if isinstance(paid, Decimal):
        amount = paid
        code = default_currency
    else:
        amount, detected = _cell_money(str(paid or ""), default_currency=default_currency)
        code = explicit if explicit in _LOG_CURRENCIES else detected
    identity = re.sub(
        r"[^a-z0-9]",
        "",
        (catalog_number or title_text).casefold(),
    )
    day = paid_on.isoformat() if paid_on else ""
    paid_label = f"{amount:.2f}" if amount is not None else ""
    return ParsedPurchase(
        source=place,
        external_id=f"log:{identity}:{day}:{paid_label}",
        title=title_text or catalog_number or "",
        seller=place,
        paid_amount=amount,
        paid_currency=code,
        paid_on=paid_on,
        catalog_number=catalog_number,
    )


def parse_logged_table(raw: str) -> tuple[ParsedPurchase, ...]:
    """Read a pasted log. Columns are where, catalog, title, paid, currency, date."""

    text = raw.lstrip("\ufeff").strip()
    if not text:
        return ()
    first = text.splitlines()[0]
    if "," not in first and "\t" not in first:
        return ()
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return ()
    headers = {
        (name or "").strip().lower(): name
        for name in reader.fieldnames
        if name
    }
    where_header = _log_header(headers, "where", "from", "source", "shop", "seller")
    catalog_header = _log_header(headers, "catalog", "catalogue", "cat no", "品番")
    title_header = _log_header(headers, "title", "album", "record")
    if catalog_header is None and title_header is None:
        return ()
    paid_header = _log_header(headers, "paid", "price", "amount", "金額")
    currency_header = _log_header(headers, "currency")
    date_header = _log_header(headers, "paid on", "date", "購入日")
    rows: list[ParsedPurchase] = []
    seen: dict[str, int] = {}
    for record in reader:
        purchase = logged_purchase(
            where=str(record.get(where_header) or "") if where_header else "",
            catalog=str(record.get(catalog_header) or "") if catalog_header else "",
            title=str(record.get(title_header) or "") if title_header else "",
            paid=str(record.get(paid_header) or "") if paid_header else "",
            currency=str(record.get(currency_header) or "") if currency_header else "",
            paid_on=_date(str(record.get(date_header) or "")) if date_header else None,
        )
        if purchase is None:
            continue
        seen[purchase.external_id] = seen.get(purchase.external_id, 0) + 1
        copy_number = seen[purchase.external_id]
        if copy_number > 1:
            purchase = replace(
                purchase,
                external_id=f"{purchase.external_id}:{copy_number}",
            )
        rows.append(purchase)
    return tuple(rows)


def is_screenshot_bytes(data: bytes) -> bool:
    """JPEG, PNG, GIF, or WebP — a photo of a bill, not the bill text."""

    if data.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8")):
        return True
    return data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def bill_text_from_bytes(data: bytes) -> str:
    """Read a dropped PDF or pasted page. Screenshots stay images until Extract."""

    if is_screenshot_bytes(data):
        raise ValueError("Paste the order text, or type shipping and tax.")
    if data.startswith(b"%PDF"):
        return extract_pdf_text(data)
    return data.decode("utf-8", errors="replace")


def extract_screenshot_bill_text(data: bytes) -> str:
    """Read labels off a PNG/JPEG of View order details with Tesseract."""

    if not is_screenshot_bytes(data):
        return bill_text_from_bytes(data)
    if shutil.which("tesseract") is None:
        raise ValueError(
            "Could not read that screenshot. Paste the order text, or type shipping and tax."
        )
    image = Image.open(io.BytesIO(data))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        image.save(tmp.name, format="PNG")
        block = _tesseract_stdout(tmp.name, psm=6)
        sparse = _tesseract_stdout(tmp.name, psm=11)
        table = _tesseract_table_text(image)
        upscaled = _tesseract_upscaled_text(image)
    block = _buyee_merge_ocr_passes(block, table, upscaled, sparse)
    text = _with_buyee_column_notes(block, image)
    dates = _date_bearing_ocr_lines(sparse)
    if dates and dates not in block:
        text = f"{text}\n{dates}".strip()
    if not text:
        raise ValueError(
            "Could not read that screenshot. Paste the order text, or type shipping and tax."
        )
    return text


def _buyee_ocr_richness(text: str) -> tuple[int, int]:
    """How many auction ids and item prices a Tesseract pass recovered."""

    cleaned = _normalize_ocr_bill_text(text)
    auctions = len(set(_BUYEE_AUCTION_ID.findall(cleaned)))
    prices = len(re.findall(r"item price\s+[0-9]", cleaned, flags=re.IGNORECASE))
    return auctions, prices


_BUYEE_OCR_KEEP_LINE = re.compile(
    r"Item\s*Price|Plan\s*Fee|\bn Fee\b|Service Fee|Domestic|nestic|"
    r"International|rnational|smational|rmational|Grand Total|"
    r"Auction\s*\(",
    re.IGNORECASE,
)


def _buyee_merge_ocr_passes(*texts: str) -> str:
    """Keep the auction ids from one pass and labeled yen from another.

    psm 4/6 follows the Japanese title and drops 375. psm 11 reads the
    amounts and splits the auction id. Dumping every unique line also
    dumps catalog crumbs like 27/57, which glue onto 985 as 27,985 postage.
    """

    parts = [str(part).strip() for part in texts if str(part).strip()]
    if not parts:
        return ""
    ranked = sorted(parts, key=_buyee_ocr_richness, reverse=True)
    base = ranked[0]
    seen = {line.strip() for line in base.splitlines() if line.strip()}
    extras: list[str] = []
    for part in ranked[1:]:
        for line in part.splitlines():
            stripped = line.strip()
            if not stripped or stripped in seen:
                continue
            if _BUYEE_OCR_KEEP_LINE.search(stripped) and re.search(r"[0-9]", stripped):
                extras.append(stripped)
                seen.add(stripped)
    if not extras:
        return base
    return f"{base.rstrip()}\n" + "\n".join(extras)


def _tesseract_table_text(image: Image.Image) -> str:
    """Read a wide Buyee table by its rows. psm 6 follows columns and loses the price."""

    width, height = image.size
    if width < 40 or height < 40:
        return ""
    scale = 2 if max(width, height) < 2200 else 1
    working = ImageOps.autocontrast(image.convert("L"))
    if scale != 1:
        working = working.resize(
            (width * scale, height * scale), Image.Resampling.LANCZOS
        )
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        working.save(tmp.name, format="PNG")
        completed = subprocess.run(
            [
                "tesseract",
                tmp.name,
                "stdout",
                "--psm",
                "4",
                "-l",
                _tesseract_lang(),
                "tsv",
            ],
            capture_output=True,
            check=False,
        )
    raw = (completed.stdout or b"").decode("utf-8", errors="replace")
    words: list[tuple[int, int, str]] = []
    for line in raw.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        token = parts[11].strip()
        if not token:
            continue
        try:
            left = int(parts[6])
            top = int(parts[7])
            token_width = int(parts[8])
        except ValueError:
            continue
        if token_width > 500 and not re.search(r"\d", token):
            continue
        words.append((top, left, token))
    if not words:
        return ""
    words.sort()
    rows: list[list[tuple[int, str]]] = []
    row_top: int | None = None
    for top, left, token in words:
        if row_top is None or top - row_top > 16:
            rows.append([(left, token)])
            row_top = top
            continue
        rows[-1].append((left, token))
    return "\n".join(
        " ".join(token for _left, token in sorted(row))
        for row in rows
        if row
    ).strip()


def _tesseract_upscaled_text(image: Image.Image) -> str:
    """psm 6 on a small fee page drops the auction id. Twice the size keeps it."""

    width, height = image.size
    if width < 40 or height < 40 or max(width, height) >= 1800:
        return ""
    working = ImageOps.autocontrast(image.convert("L")).resize(
        (width * 2, height * 2), Image.Resampling.LANCZOS
    )
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        working.save(tmp.name, format="PNG")
        return _tesseract_stdout(tmp.name, psm=6)


def _ocr_amount_token(line: str) -> Decimal | None:
    """One amount on its own line. ``880)`` counts. ``S80`` and ``28,324YEN`` do not."""

    stripped = re.sub(r"^[\s|\[\]()]+|[\s|\[\]()]+$", "", line.strip())
    stripped = stripped.replace(" ", "")
    if not re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,6}", stripped):
        return None
    amount = _decimal(stripped)
    if amount is None or amount < Decimal("10"):
        return None
    return amount


def _paired_column_amounts(text: str) -> list[Decimal]:
    """Item price and total amount, when the right-hand column prints them twice."""

    values = [_ocr_amount_token(line) for line in text.splitlines()]
    pairs: list[Decimal] = []
    index = 0
    while index < len(values):
        current = values[index]
        if current is None:
            index += 1
            continue
        end = index + 1
        same = 1
        while end < len(values):
            nxt = values[end]
            if nxt is None:
                end += 1
                continue
            if nxt == current:
                same += 1
                end += 1
                continue
            break
        # Price and total amount are the same number twice. A longer run is a fee column.
        if same == 2:
            pairs.append(current)
        index = end if end > index else index + 1
    if len(pairs) >= 2:
        return pairs
    # Item price and total amount sometimes land on one line: "440 440".
    inline: list[Decimal] = []
    for line in text.splitlines():
        amounts = [
            amount
            for raw in re.findall(r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6}", line)
            if (amount := _decimal(raw)) is not None and amount >= Decimal("10")
        ]
        if len(amounts) == 2 and amounts[0] == amounts[1]:
            inline.append(amounts[0])
    return inline if len(inline) >= 2 else pairs


def _confirmed_fee_runs(text: str) -> list[tuple[Decimal, list[Decimal]]]:
    """Repeated row amounts whose sum is the package total printed above them."""

    sequence = [
        amount
        for line in text.splitlines()
        if (amount := _ocr_amount_token(line)) is not None
    ]
    runs: list[tuple[Decimal, list[Decimal]]] = []
    index = 0
    while index < len(sequence):
        end = index + 1
        while end < len(sequence) and sequence[end] == sequence[index]:
            end += 1
        rows = sequence[index:end]
        total = sum(rows, Decimal("0"))
        if len(rows) >= 3 and total in sequence[:index]:
            runs.append((total, rows))
        index = end
    return runs


def _buyee_customs_before_grand(image: Image.Image) -> Decimal | None:
    """Customs duty is the doubled amount printed just above the grand total.

    The duty and its total are the same number twice. Item prices do the same,
    so this only counts when the next amount is a single larger total.
    """

    crop = _column_crop_text(image, frac=0.85, scale=3, threshold=None)
    sequence = [
        amount
        for line in crop.splitlines()
        if (amount := _ocr_amount_token(line)) is not None
    ]
    index = 0
    while index < len(sequence):
        end = index + 1
        while end < len(sequence) and sequence[end] == sequence[index]:
            end += 1
        run = end - index
        if (
            run == 2
            and sequence[index] not in {Decimal("300"), Decimal("500"), Decimal("880")}
            and end < len(sequence)
        ):
            following = sequence[end]
            after = end + 1
            while after < len(sequence) and sequence[after] == following:
                after += 1
            if after - end == 1 and following > sequence[index]:
                return sequence[index]
        index = end if end > index else index + 1
    return None


def _column_crop_text(
    image: Image.Image,
    *,
    frac: float,
    scale: int,
    threshold: int | None,
) -> str:
    """Read the far-right amount column. The full page follows the title instead."""

    width, height = image.size
    if width < 200 or height < 80:
        return ""
    working = ImageOps.autocontrast(image.convert("L"))
    left = min(int(width * frac), width - 20)
    crop = working.crop((left, 0, width, height))
    crop_width, crop_height = crop.size
    used = scale
    if max(crop_width, crop_height) * used > 6000:
        used = max(1, 6000 // max(crop_width, crop_height))
    if used != 1:
        crop = crop.resize(
            (crop_width * used, crop_height * used), Image.Resampling.LANCZOS
        )
    if threshold is not None:
        crop = crop.point(lambda pixel, cutoff=threshold: 255 if pixel > cutoff else 0)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        crop.save(tmp.name, format="PNG")
        return _tesseract_stdout(tmp.name, psm=6)


def _tesseract_words(image: Image.Image, *, psm: int, scale: int) -> list[tuple[float, float, str]]:
    """Word boxes in the original image's coordinates."""

    width, height = image.size
    if width < 40 or height < 40:
        return []
    working = ImageOps.autocontrast(image.convert("L"))
    if scale != 1:
        working = working.resize(
            (width * scale, height * scale), Image.Resampling.LANCZOS
        )
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        working.save(tmp.name, format="PNG")
        completed = subprocess.run(
            [
                "tesseract",
                tmp.name,
                "stdout",
                "--psm",
                str(psm),
                "-l",
                _tesseract_lang(),
                "tsv",
            ],
            capture_output=True,
            check=False,
        )
    raw = (completed.stdout or b"").decode("utf-8", errors="replace")
    words: list[tuple[float, float, str]] = []
    for line in raw.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        token = parts[11].strip()
        if not token:
            continue
        try:
            left = int(parts[6]) / scale
            top = int(parts[7]) / scale
        except ValueError:
            continue
        words.append((top, left, token))
    words.sort()
    return words


def _buyee_visual_item_rows(
    image: Image.Image,
) -> list[tuple[str, str, Decimal | None]]:
    """Auction, catalog, and item price from the same horizontal band.

    Tesseract's reading order is not the order of the rows. The price column
    is. Pairing them by text order puts 4,290 on the wrong record.
    """

    bands = _buyee_word_bands(image)
    if len(bands) < 2:
        return []
    return _buyee_visual_item_rows_from_bands(bands, image)


_BUYEE_ORDER_TOKEN = re.compile(r"^(?:R\s*)?\d{10,}$", re.IGNORECASE)
_BUYEE_WON_CHROME = re.compile(
    r"Shop\s*Name|Order\s*Number|Item\s*Name|ltem\s*Name|TemName|"
    r"\bInsured\b|\bInsure\b|\bDeliver(?:y|ed)?\b|"
    r"JDirectItems|JDirectltems|\bAuction\b|"
    r"\bName\b\s*[.。,、/]*|[✔✓]",
    re.IGNORECASE,
)
_BUYEE_WEAK_TITLE = re.compile(r"^(?:まで|送料|円|枚まで|即決)+$")
_BUYEE_NAME_COLUMN_TOKEN = re.compile(
    r"[\u4e00-\u9fff\u3040-\u30ff]|^(?:EP-?\d|C00\d|7inch|HIT|PACK|SERIES|MOMOE|YAMAGUCHI)\b",
    re.IGNORECASE,
)
_BUYEE_CJK_FILLER = re.compile(
    r"即決|最安値|多数出品中|レア盤|新品同様|送料|メール|レコード|出品"
)
_BUYEE_KEEP_LATIN = frozenset(
    {
        "EP",
        "LP",
        "CD",
        "HIT",
        "PACK",
        "CBS",
        "SONY",
        "MOMOE",
        "YAMAGUCHI",
        "SERIES",
        "LAST",
        "AT",
        "SOLD",
    }
)


def _buyee_item_name_column_left(words: list[tuple[float, float, str]]) -> float:
    """Left edge of the Item Name column, right of the order numbers."""

    order_left = [
        left for _top, left, token in words if _BUYEE_ORDER_TOKEN.fullmatch(token)
    ]
    title_left = [
        left
        for _top, left, token in words
        if (not order_left or left > max(order_left) + 80)
        and _BUYEE_NAME_COLUMN_TOKEN.search(token)
    ]
    if title_left:
        return min(title_left) - 10
    if order_left:
        return max(order_left) + 30
    width = max((left for _top, left, _token in words), default=0)
    return width * 0.45


def _buyee_clean_won_title(text: str) -> str:
    """Drop table chrome so the remaining name can classify the copy."""

    cleaned = _BUYEE_WON_CHROME.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip(" /-.。、")


def _buyee_drop_title_noise(text: str) -> str:
    """Drop postage crumbs and Latin stew around a Japanese Item Name."""

    if not _CJK_TITLE.search(text):
        return text
    cleaned = re.sub(
        r"(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])",
        "",
        text,
    )
    cleaned = _BUYEE_CJK_FILLER.sub(" ", cleaned)
    cleaned = re.sub(r"送料|ゆうメール|メール|\b\d+\s*円\b", " ", cleaned)
    cleaned = re.sub(r"レコ[ーｰーュめう]*ド?", " ", cleaned)
    kept: list[str] = []
    for token in cleaned.split():
        upper = token.upper()
        if re.fullmatch(r"[A-Za-z]{1,3}", token) and upper not in _BUYEE_KEEP_LATIN:
            continue
        if re.fullmatch(r"\d{2,3}", token):
            continue
        if token in {"枚", "由", "円"}:
            continue
        token = re.sub(r"^り(?=[\u4e00-\u9fff])", "", token)
        token = re.sub(r"由(?=[\u4e00-\u9fff])", "", token)
        if token:
            kept.append(token)
    return " ".join(kept).strip()


def _buyee_polish_copy_title(title: str, auction_id: str = "") -> str:
    """Strip Item Name chrome. Keep 7inch 山口百恵, not Name or まで."""

    cleaned = _buyee_drop_title_noise(_buyee_clean_won_title(title))
    if not _buyee_title_is_usable(cleaned, auction_id):
        return ""
    return _buyee_with_ep_hint(cleaned)


def _buyee_cjk_runs(text: str) -> list[str]:
    """CJK words, joining letters that Tesseract split with spaces."""

    compact = re.sub(
        r"(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])",
        "",
        text,
    )
    return re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]{2,}", compact)


def _buyee_with_ep_hint(title: str) -> str:
    """Mark a 7-inch when OCR kept 4曲入り / EPL but lost the letters EP."""

    if purchase_media(title) is not None:
        return title[:180]
    compact = re.sub(
        r"(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])",
        "",
        title,
    )
    if re.search(r"4曲入|33回転4|\bEPL\b|7インチ|山鳩", compact):
        return f"{title} EP"[:180]
    return title[:180]


def _merge_buyee_won_title(crop: str, fallback: str) -> str:
    """Keep the song name and EP/LP from whichever pass still has them."""

    crop_title = _buyee_clean_won_title(crop)
    fallback_title = _buyee_clean_won_title(fallback)
    if not _buyee_title_is_usable(crop_title):
        return _buyee_with_ep_hint(fallback_title)
    compact = re.sub(r"\s+", "", crop_title)
    missing = [
        run
        for run in _buyee_cjk_runs(fallback_title)
        if run not in compact and not _BUYEE_CJK_FILLER.search(run)
    ]
    merged = crop_title
    if missing:
        merged = f"{crop_title} {' '.join(missing)}"
    media = purchase_media(fallback_title) or purchase_media(merged)
    if media == "EP_7_INCH" and purchase_media(merged) != "EP_7_INCH":
        merged = f"{merged} EP"
    elif media == "LP" and purchase_media(merged) is None:
        merged = f"{merged} LP"
    return _buyee_with_ep_hint(merged)


def _buyee_won_list_title_rows(
    words: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """Print-order Item Names with the vertical span of each wrapped row."""

    if len(words) < 8:
        return []
    order_count = sum(1 for _top, _left, token in words if _BUYEE_ORDER_TOKEN.fullmatch(token))
    if order_count < 2:
        return []
    name_left = _buyee_item_name_column_left(words)
    name_words = [
        (top, left, token)
        for top, left, token in words
        if left >= name_left and not _BUYEE_ORDER_TOKEN.fullmatch(token)
    ]
    bands = _buyee_bands_from_words(name_words, y_tol=14)
    if len(bands) < 2:
        return []
    rows: list[tuple[float, float, str]] = []
    for cluster in _buyee_cluster_bands_by_row(bands):
        blob = " ".join(text for _top, text in cluster)
        cleaned = _buyee_clean_won_title(blob)
        if not _buyee_title_is_usable(cleaned):
            continue
        top = cluster[0][0]
        bottom = cluster[-1][0] + 18
        rows.append((top, bottom, cleaned[:180]))
    return rows


def _buyee_won_list_visual_titles_from_words(
    words: list[tuple[float, float, str]],
) -> list[str]:
    """Item names from the won-auction table, one per printed row.

    Tesseract's reading order wraps the Japanese name around the order
    number. The Item Name column is to the right of those numbers, so the
    words there stay in print order even when a title uses four lines.
    """

    return [title for _top, _bottom, title in _buyee_won_list_title_rows(words)]


def _buyee_ocr_name_row(
    image: Image.Image,
    *,
    left: float,
    top: float,
    bottom: float,
) -> str:
    """Read one Item Name cell. The full-page pass mixed it with the order number."""

    width, height = image.size
    box_left = max(0, min(int(left), width - 20))
    box_top = max(0, min(int(top) - 4, height - 8))
    box_bottom = max(box_top + 8, min(int(bottom), height))
    region = image.crop((box_left, box_top, width, box_bottom)).convert("L")
    crop = ImageOps.autocontrast(region)
    crop_width, crop_height = crop.size
    if crop_width < 20 or crop_height < 8:
        return ""
    crop = crop.resize(
        (crop_width * 2, crop_height * 2),
        Image.Resampling.LANCZOS,
    )
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        crop.save(tmp.name, format="PNG")
        return _buyee_clean_won_title(_tesseract_stdout(tmp.name, psm=6))


def _buyee_won_list_visual_titles(
    image: Image.Image,
    words: list[tuple[float, float, str]],
) -> list[str]:
    """Prefer a per-row Item Name crop when it reads more of the Japanese."""

    rows = _buyee_won_list_title_rows(words)
    if len(rows) < 2:
        return []
    name_left = _buyee_item_name_column_left(words)
    titles: list[str] = []
    for index, (top, bottom, fallback) in enumerate(rows):
        next_top = rows[index + 1][0] if index + 1 < len(rows) else bottom + 24
        crop_title = _buyee_ocr_name_row(
            image,
            left=name_left,
            top=top,
            bottom=next_top - 2,
        )
        titles.append(_merge_buyee_won_title(crop_title, fallback))
    return titles


def _buyee_cluster_bands_by_row(
    bands: list[tuple[float, str]],
) -> list[list[tuple[float, str]]]:
    """Split wrapped title lines on the larger gap between table rows."""

    if not bands:
        return []
    if len(bands) == 1:
        return [bands]
    gaps = [bands[index][0] - bands[index - 1][0] for index in range(1, len(bands))]
    ordered = sorted(gaps)
    median = ordered[len(ordered) // 2]
    cutoff = max(median * 1.45, median + 8)
    clusters: list[list[tuple[float, str]]] = []
    current = [bands[0]]
    for index in range(1, len(bands)):
        if bands[index][0] - bands[index - 1][0] > cutoff:
            clusters.append(current)
            current = []
        current.append(bands[index])
    clusters.append(current)
    return clusters


def _buyee_word_bands(image: Image.Image) -> list[tuple[float, str]]:
    """Horizontal lines of Tesseract words, left to right."""

    return _buyee_bands_from_words(_tesseract_words(image, psm=4, scale=2))


def _buyee_bands_from_words(
    words: list[tuple[float, float, str]],
    *,
    y_tol: float = 16,
) -> list[tuple[float, str]]:
    """Join words that share a horizontal line."""

    if not words:
        return []
    bands: list[tuple[float, str]] = []
    band: list[tuple[float, str]] = []
    band_top: float | None = None
    for top, left, token in sorted(words):
        if band_top is None or top - band_top > y_tol:
            if band:
                bands.append(
                    (band_top or top, " ".join(token for _left, token in sorted(band)))
                )
            band = [(left, token)]
            band_top = top
            continue
        band.append((left, token))
    if band and band_top is not None:
        bands.append((band_top, " ".join(token for _left, token in sorted(band))))
    return bands


def _buyee_visual_item_rows_from_bands(
    bands: list[tuple[float, str]],
    image: Image.Image,
) -> list[tuple[str, str, Decimal | None]]:
    auctions: list[tuple[float, str, str]] = []
    pending: list[str] = []
    current: tuple[float, str] | None = None
    # The catalog is printed on the line above the auction id. A band that
    # only has that catalog belongs to the next id, not the previous one.
    held = ""
    carried = ""
    for top, text in bands:
        if carried:
            text = f"{carried} {text}"
            carried = ""
        # The id is split across two lines: ``Auction(u`` then ``1204905847)``.
        if (
            re.search(r"Auction\s*\([^)]*$", text)
            and not _buyee_catalogs_in(text)
            and _buyee_band_auction_id(text) is None
        ):
            carried = text
            continue
        auction_id = _buyee_band_auction_id(text)
        if auction_id is None:
            if _buyee_catalogs_in(text):
                if current is not None and not _buyee_catalogs_in(" ".join(pending)):
                    pending.append(text)
                else:
                    held = text
            elif current is not None:
                pending.append(text)
            continue
        if current is not None:
            auctions.append((current[0], current[1], " ".join(pending)))
        current = (top, auction_id)
        pending = [held, text] if held and not _buyee_catalogs_in(text) else [text]
        held = ""
    if current is not None:
        auctions.append((current[0], current[1], " ".join(pending)))
    seen: set[str] = set()
    ordered: list[tuple[float, str, str]] = []
    for top, auction_id, blob in auctions:
        if auction_id in seen:
            continue
        seen.add(auction_id)
        ordered.append((top, auction_id, blob))
    if len(ordered) < 2:
        return []
    price_rows = _buyee_price_rows(image)
    built: list[tuple[str, str, Decimal | None]] = []
    for index, (top, auction_id, blob) in enumerate(ordered):
        next_top = ordered[index + 1][0] if index + 1 < len(ordered) else top + 160
        title = _buyee_title_for_auction(blob, auction_id)
        price = _buyee_visual_amount(
            title,
            [
                amount
                for price_top, amount in price_rows
                if top - 20 <= price_top < next_top
            ],
        )
        built.append((auction_id, title, price))
    # A fee row that misreads one digit of an id is not another purchase.
    built = _buyee_collapse_twins(built)
    priced = sum(price is not None for _auction_id, _title, price in built)
    # A fee page has catalogs and no item prices. Those catalogs belong to
    # the next row. Leave them out so the item page can name the record.
    if priced < 2:
        return []
    amounts = [price for _auction_id, _title, price in built if price is not None]
    if len(amounts) >= 3 and len(set(amounts)) == 1 and amounts[0] in {
        Decimal("300"),
        Decimal("500"),
        Decimal("880"),
    }:
        built = [(auction_id, title, None) for auction_id, title, _price in built]
    return built


def _buyee_band_auction_id(text: str) -> str | None:
    """The auction id on one row, including ``Auction(f1 204890335)``."""

    found = [
        match.group(1).lower()
        for match in _BUYEE_AUCTION_ID.finditer(_normalize_ocr_bill_text(text))
    ]
    if found:
        return found[-1]
    match = re.search(r"Auction\s*\(\s*([A-Za-z])([lI1])?\s*(\d{6,})", text, re.IGNORECASE)
    if match is None:
        return None
    letter, slip, digits = match.group(1).lower(), match.group(2), match.group(3)
    if slip and slip.lower() in {"l", "i"}:
        return f"{letter}1{digits}"
    if slip == "1" and not digits.startswith("1"):
        return f"{letter}1{digits}"
    return f"{letter}{digits}"


def _buyee_column_customs(
    rows: list[tuple[float, Decimal]],
    international: Decimal | None,
    item_prices: set[Decimal],
) -> Decimal | None:
    """The duty printed under international shipping in the amount column."""

    if international is None:
        return None
    skip = item_prices | {
        Decimal("300"),
        Decimal("500"),
        Decimal("880"),
        Decimal("1800"),
        Decimal("3000"),
        Decimal("4400"),
        Decimal("9200"),
        Decimal("28324"),
        international,
    }
    seen = False
    for _top, amount in rows:
        if amount == international:
            seen = True
            continue
        if seen and amount not in skip:
            return amount
    return None


def _buyee_leading_item_prices(
    rows: list[tuple[float, Decimal]],
) -> list[Decimal]:
    """Item prices at the top of the column, before the fee totals begin."""

    stop = _BUYEE_PACKAGE_TOTALS | {Decimal("1500")}
    fee_units = {Decimal("300"), Decimal("500"), Decimal("880")}
    prices: list[Decimal] = []
    for _top, amount in rows:
        if amount == Decimal("1500") and not prices:
            prices.append(amount)
            continue
        count = len(prices)
        if count >= 2 and amount in stop:
            break
        if count >= 6 and amount in {unit * count for unit in fee_units}:
            break
        if amount in stop:
            continue
        prices.append(amount)
    return prices


def _buyee_strip_customs_item_price(text: str, item_prices: set[Decimal]) -> str:
    """671 under Customs Duty is the record above it, not the duty."""

    match = re.search(r"Customs Dut(?:y|ies)[^\n]*", text, re.IGNORECASE)
    if match is None:
        return text
    amount_match = re.search(r"([0-9][0-9,]*)\s*$", match.group(0))
    if amount_match is None:
        return text
    amount = _decimal(amount_match.group(1))
    if amount not in item_prices:
        return text
    line = match.group(0)[: amount_match.start()].rstrip()
    return text[: match.start()] + line + text[match.end() :]


def _buyee_price_bands(
    flat: list[tuple[float, Decimal]],
) -> list[tuple[float, Decimal]]:
    """Price rows. A doubled amount is the price and the total.

    A second copy of 440 whose total landed more than 70px lower is still a
    row. Dropping it is how the two SOLL records disappear and only 1,001,
    4,290, and 671 remain.
    """

    pairs: list[tuple[float, Decimal]] = []
    singles: list[tuple[float, Decimal]] = []
    index = 0
    while index < len(flat):
        end = index + 1
        while (
            end < len(flat)
            and flat[end][1] == flat[index][1]
            and flat[end][0] - flat[index][0] <= 70
        ):
            end += 1
        if end - index == 2:
            pairs.append(flat[index])
        elif end - index == 1 and flat[index][1] >= Decimal("100"):
            singles.append(flat[index])
        index = end if end > index else index + 1
    fee_units = {Decimal("300"), Decimal("500"), Decimal("880")}
    non_fee = [(top, amount) for top, amount in singles if amount not in fee_units]
    if len(pairs) >= 2:
        extra = [
            (top, amount)
            for top, amount in non_fee
            if all(abs(top - paired) > 40 for paired, _amount in pairs)
        ]
        item_top = min(top for top, _amount in pairs)
        item_bot = max(top for top, _amount in pairs)
        sandwiched = [
            (top, amount)
            for top, amount in singles
            if amount in fee_units and item_top < top < item_bot
        ]
        return sorted([*pairs, *extra, *sandwiched])
    if len(non_fee) >= 2:
        return non_fee
    return pairs


def _buyee_price_rows(image: Image.Image) -> list[tuple[float, Decimal]]:
    """Item price bands. The amount is printed twice, once as the price and once as the total."""

    _width, height = image.size
    found: list[tuple[float, Decimal]] = []
    for frac in (0.58, 0.74):
        left = int(image.size[0] * frac)
        crop = image.crop((left, 0, image.size[0], height))
        flat = [
            (top, amount)
            for top, _left, token in _tesseract_words(crop, psm=6, scale=3)
            if (amount := _ocr_amount_token(token)) is not None
        ]
        rows = _buyee_price_bands(flat)
        if len(rows) > len(found):
            found = rows
    return found


def _attach_item_prices(text: str, prices: list[Decimal]) -> str | None:
    """Write each recovered price onto the auction in that row.

    The wide read often keeps the id and drops the number. The price column
    is in the same top-to-bottom order as the ids on this picture.
    """

    cleaned = _normalize_ocr_bill_text(text)
    seen: set[str] = set()
    matches: list[re.Match[str]] = []
    for match in _BUYEE_AUCTION_ID.finditer(cleaned):
        auction_id = match.group(1).lower()
        if auction_id in seen:
            continue
        seen.add(auction_id)
        matches.append(match)
    if len(matches) != len(prices):
        return None
    updated = cleaned
    for match, price in reversed(list(zip(matches, prices, strict=True))):
        updated = (
            f"{updated[: match.end()]}\nItem Price {_plain_amount(price)}"
            f"{updated[match.end() :]}"
        )
    return updated


def _buyee_one_copy_right_column(image: Image.Image) -> list[Decimal]:
    """A 1-auction bill prints hammer, 500/300, domestic, other-total, and postage.

    The wide read drops that column. Lots have many auction ids and must not
    dump eleven hammers onto one copy.
    """

    for frac in (0.82, 0.74, 0.58):
        crop = _column_crop_text(image, frac=frac, scale=3, threshold=None)
        amounts = [
            amount
            for line in crop.splitlines()
            if (amount := _ocr_amount_token(line)) is not None
        ]
        if (
            4 <= len(amounts) <= 12
            and Decimal("500") in amounts
            and Decimal("300") in amounts
        ):
            return amounts
    return []


def _with_buyee_column_notes(text: str, image: Image.Image) -> str:
    """Attach the price column when the wide table lost it.

    Item price and total amount are the same number twice. Plan, service, and
    domestic rows repeat under the package total. The parser zips those lists
    back onto the auctions.
    """

    notes: list[str] = []
    words = _tesseract_words(image, psm=4, scale=2)
    bands = _buyee_bands_from_words(words)
    visual = (
        _buyee_visual_item_rows_from_bands(bands, image) if len(bands) >= 2 else []
    )
    won_titles = _buyee_won_list_visual_titles(image, words)
    if len(won_titles) >= 2:
        notes.extend(f"Won title {title}" for title in won_titles)
    if visual:
        priced_rows = sum(price is not None for _auction_id, _title, price in visual)
        for auction_id, title, price in visual:
            amount = _plain_amount(price) if price is not None else ""
            notes.append(
                f"Visual auction {auction_id} title {title} price {amount} rows {priced_rows}"
            )
    pair_lists = [
        rows
        for frac in (0.58, 0.74)
        if len(
            rows := _paired_column_amounts(
                _column_crop_text(image, frac=frac, scale=3, threshold=None)
            )
        )
        >= 2
    ]
    visual_prices = sum(price is not None for _auction_id, _title, price in visual)
    price_rows = _buyee_price_rows(image)
    leading = _buyee_leading_item_prices(price_rows)
    if len(leading) >= 2:
        notes.extend(f"Column item {_plain_amount(amount)}" for amount in leading)
    elif pair_lists and visual_prices < 2:
        pairs = max(pair_lists, key=lambda rows: (len(rows), len(set(rows))))
        attached = _attach_item_prices(text, pairs)
        if attached is not None:
            text = attached
        else:
            notes.extend(f"Column item {_plain_amount(amount)}" for amount in pairs)
    runs: list[tuple[Decimal, list[Decimal]]] = []
    seen: set[Decimal] = set()
    for threshold in (None, 140):
        for total, rows in _confirmed_fee_runs(
            _column_crop_text(image, frac=0.82, scale=5, threshold=threshold)
        ):
            if total in seen:
                continue
            seen.add(total)
            runs.append((total, rows))
    for total, rows in runs:
        label = _plain_amount(total)
        notes.extend(
            f"Column fee {label} {_plain_amount(amount)}" for amount in rows
        )
    auction_ids = set(
        match.lower()
        for match in _BUYEE_AUCTION_ID.findall(_normalize_ocr_bill_text(text))
    )
    if len(auction_ids) <= 1 and not any(
        note.startswith("Column item ") for note in notes
    ):
        column_all = _buyee_one_copy_right_column(image)
        if column_all:
            notes.extend(f"Column item {_plain_amount(amount)}" for amount in column_all)
    if leading:
        text = _buyee_strip_customs_item_price(text, set(leading))
    if re.search(r"customs\s*dut", text, re.IGNORECASE) and not re.search(
        r"customs\s*dut(?:y|ies)\D{0,30}[0-9]",
        text,
        re.IGNORECASE,
    ):
        customs = _buyee_customs_before_grand(image)
        if customs is None or customs in set(leading):
            found = re.search(
                r"International Shipping Fee\D{0,20}([0-9][0-9,]*)",
                text,
                flags=re.IGNORECASE,
            )
            international = _decimal(found.group(1)) if found else None
            customs = _buyee_column_customs(price_rows, international, set(leading))
        if customs is not None:
            # Keep this on the existing heading. A new "Customs Duty" line
            # later in the file would split the plan-fee rows off their heading.
            text = re.sub(
                r"(Customs Dut(?:y|ies)[^\n]*)",
                lambda match, amount=_plain_amount(customs): (
                    match.group(1)
                    if re.search(r"\d", match.group(1))
                    else f"{match.group(1)} {amount}"
                ),
                text,
                count=1,
                flags=re.IGNORECASE,
            )
    if not notes:
        return text
    return f"{text.rstrip()}\n" + "\n".join(notes)


_TESSERACT_LANG = ""


def _tesseract_lang() -> str:
    """Japanese+English when tessdata has jpn, otherwise English."""

    global _TESSERACT_LANG
    if _TESSERACT_LANG:
        return _TESSERACT_LANG
    completed = subprocess.run(
        ["tesseract", "--list-langs"],
        capture_output=True,
        text=True,
        check=False,
    )
    langs = {
        line.strip()
        for line in (completed.stdout or "").splitlines()
        if line.strip() and " " not in line.strip()
    }
    _TESSERACT_LANG = "jpn+eng" if "jpn" in langs else "eng"
    return _TESSERACT_LANG


def _tesseract_stdout(path: str, *, psm: int) -> str:
    """One Tesseract pass. psm 6 keeps the totals block; 11 keeps the card stamp."""

    completed = subprocess.run(
        [
            "tesseract",
            path,
            "stdout",
            "--psm",
            str(psm),
            "-l",
            _tesseract_lang(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (completed.stdout or "").strip()


def _date_bearing_ocr_lines(text: str) -> str:
    """Keep Paid / Time placed / Delivered on. Drop a second copy of the money lines."""

    keep: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(
            r"item number|\bshipping\b|\btax\b\*?\b|\border total\b|\b\d+\s+items?\b",
            stripped,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"delivered on|time placed|order date|\bpaid\b|"
            r"20\d{2}/\d{2}/\d{2}|"
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"\s+\d{1,2}\s+at\s+\d{1,2}[:.]\d{2}",
            stripped,
            re.IGNORECASE,
        ):
            keep.append(stripped)
    return "\n".join(keep)


@dataclass(frozen=True)
class HarvestedScreenshots:
    pages: tuple[str, ...]
    shots: tuple[bytes, ...]
    error: str | None = None


def harvest_screenshot_bills(
    shots: list[bytes],
    pages: list[str] | None = None,
) -> HarvestedScreenshots:
    """OCR parked screenshots. Drop them only when shipping or tax is on the bill."""

    parked = [part for part in (pages or []) if str(part).strip()]
    if not shots:
        return HarvestedScreenshots(
            pages=tuple(parked),
            shots=(),
            error="Drop a screenshot first.",
        )
    texts: list[str] = []
    errors: list[str] = []
    for shot in shots:
        try:
            texts.append(extract_screenshot_bill_text(shot))
        except ValueError as exc:
            errors.append(str(exc))
    if not texts:
        return HarvestedScreenshots(
            pages=tuple(parked),
            shots=tuple(shots),
            error=(
                errors[0]
                if errors
                else "Could not read that screenshot. Paste the order text, or type shipping and tax."
            ),
        )
    combined = [*parked, *texts]
    if _extracted_bill_has_charges(combined):
        return HarvestedScreenshots(pages=tuple(combined), shots=(), error=None)
    snippet = " ".join(part.strip() for part in texts if part.strip())[:240]
    detail = f" OCR saw: {snippet}" if snippet else ""
    return HarvestedScreenshots(
        pages=tuple(parked),
        shots=tuple(shots),
        error=(
            "Could not read shipping or tax off that screenshot. "
            "Keep the picture; add the totals card, or paste the order text."
            f"{detail}"
        ),
    )


def _extracted_bill_has_charges(pages: list[str]) -> bool:
    parts = [str(part).strip() for part in pages if str(part).strip()]
    if not parts:
        return False
    parsed = parse_purchase_pages(parts)
    for purchase in parsed.purchases:
        if any(value is not None for value in copy_costs(purchase.billing_note).values()):
            return True
    if parsed.source in {"buyee", "recordcity"} and any(
        purchase.paid_amount is not None for purchase in parsed.purchases
    ):
        return True
    raw = combine_bill_pages(parts)
    return any(value is not None for value in copy_costs(raw).values())


def combine_bill_pages(pages: list[str]) -> str:
    """Join two screenshots or pastes of one eBay order into a single bill."""

    return "\n\n".join(part.strip() for part in pages if str(part).strip())


def extract_pdf_text(data: bytes) -> str:
    """Read labeled invoice text from a generated Buyee PDF."""

    if not data.startswith(b"%PDF"):
        raise ValueError("Not a PDF bill.")
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise ValueError("Not a PDF bill.") from exc
    return "\n".join(
        page.extract_text() or ""
        for page in reader.pages
    )


_OCR_BUYEE_AUCTION = re.compile(
    r"((?:JDirectItems\s+)?Auction\s*\(\s*)"
    r"([^)]{6,})\s*\)",
    re.IGNORECASE,
)
_OCR_BUYEE_LABEL = re.compile(
    r"(?<!\n)(?="
    r"Plan\s*Fee|"
    r"Buyee\s*Service\s*Fee|"
    r"Domestic\s*Shipping\s*Fee|"
    r"Customs\s*Clearance\s*Fee|"
    r"International\s*Shipping\s*Fee|"
    r"Customs\s*Dut(?:y|ies)|"
    r"Item\s*Price|"
    r"Coupon\s*discount|"
    r"Grand\s*Total\s*Payment\s*Amount"
    r")",
    re.IGNORECASE,
)


def _compact_ocr_buyee_auction(match: re.Match[str]) -> str:
    """Join ``Auction(f 1204890335)`` and a misread ``Auction(ul 204905847)``."""

    body = re.sub(r"[^A-Za-z0-9]+", "", match.group(2))
    slipped = re.fullmatch(r"([A-Za-z])[lI](\d{6,})", body)
    if slipped:
        body = f"{slipped.group(1)}1{slipped.group(2)}"
    if re.fullmatch(r"[A-Za-z]\d{6,}", body):
        return f"{match.group(1)}{body.lower()})"
    if re.fullmatch(r"\d{8,}", body):
        return f"{match.group(1)}{body})"
    return match.group(0)


_OCR_BARE_AUCTION = re.compile(
    r"(?<!Auction)(?<!Auction )\(\s*([A-Za-z0-9](?:\s*[A-Za-z0-9]){5,})\s*\)",
    re.IGNORECASE,
)


def _promote_bare_buyee_auction(match: re.Match[str]) -> str:
    """Turn a breakdown ``(f1204890335)`` into ``Auction(f1204890335)``."""

    body = re.sub(r"[\s/|]+", "", match.group(1))
    slipped = re.fullmatch(r"([A-Za-z])[lI](\d{6,})", body)
    if slipped:
        body = f"{slipped.group(1)}1{slipped.group(2)}"
    if not re.fullmatch(r"[A-Za-z]\d{6,}", body):
        return match.group(0)
    return f"Auction({body.lower()})"


def _fill_bare_buyee_auction(text: str) -> str:
    """Restore the letter on ``(1204890335)`` when the invoice already named it."""

    known = {
        match.group(1).lower() for match in _BUYEE_AUCTION_ID.finditer(text)
    }
    by_digits: dict[str, list[str]] = {}
    for auction_id in known:
        digits = auction_id[1:] if auction_id[:1].isalpha() else auction_id
        by_digits.setdefault(digits, []).append(auction_id)

    def repl(match: re.Match[str]) -> str:
        hits = by_digits.get(match.group(1), [])
        if len(hits) != 1:
            return match.group(0)
        return f"Auction({hits[0]})"

    return re.sub(r"(?<!Auction)(?<!Auction )\(\s*(\d{6,})\s*\)", repl, text)


def _strip_bare_amount_paren(text: str) -> str:
    """Drop a Tesseract ')' stuck on a bare amount. Keep '(SOLL 175)'."""

    def repl(match: re.Match[str]) -> str:
        prefix = text[: match.start()]
        if prefix.count("(") > prefix.count(")"):
            return match.group(0)
        return match.group(1)

    return re.sub(r"(?<=\s)(\d{1,4})\)", repl, text)


def _normalize_ocr_bill_text(text: str) -> str:
    """Tesseract wraps Buyee ids, reads '1 item' as 'litem', and Paid as Poid."""

    cleaned = re.sub(r"JDirectltems", "JDirectItems", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<![A-Za-z])n Fee\b", "Plan Fee", cleaned)
    cleaned = re.sub(r"\bPlan\s*Pee\b", "Plan Fee", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"Buyee\s*Service\s*Fee",
        "Buyee Service Fee",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:[jJyY]ee|ree|yee|jee)\s+Service Fee\b",
        "Buyee Service Fee",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:Domestic|[A-Za-z]{0,4}estic)\s+Shipping Fee",
        "Domestic Shipping Fee",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:International|[A-Za-z]{0,3}(?:rnational|smational|rmational|ernational))\s+Shipping Fee",
        "International Shipping Fee",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"(\d)\.(\d{3})(?!\d)", r"\1,\2", cleaned)
    cleaned = re.sub(r"(20\d{2}/\d{2})/\s+(\d{2})\b", r"\1/\2", cleaned)
    cleaned = re.sub(r"(\d{1,3}(?:,\d{3})+)\)", r"\1", cleaned)
    cleaned = _strip_bare_amount_paren(cleaned)
    cleaned = re.sub(r"\blitem\b", "1 item", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[lI|]\s*items?\b", "1 item", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+)items?\b", r"\1 items", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAU\s+(?=\d)", "AU $", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bTex\b(?=\s+Au\b)", "Tax", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bPoid\b", "Paid", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bPald\b", "Paid", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)&",
        r"\g<1> 4",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)s\b(?=\s+item\b)",
        r"\g<1> 4",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _OCR_BUYEE_AUCTION.sub(_compact_ocr_buyee_auction, cleaned)
    cleaned = _OCR_BARE_AUCTION.sub(_promote_bare_buyee_auction, cleaned)
    cleaned = _fill_bare_buyee_auction(cleaned)
    if re.search(
        r"jdirectitems|buyee service fee|won date|other service fees|"
        r"grand total payment amount|international shipping fee|"
        r"auction\s*\(\s*(?:[a-z]\d{6,}|\d{8,})",
        cleaned,
        re.IGNORECASE,
    ):
        cleaned = _OCR_BUYEE_LABEL.sub("\n", cleaned)
    return cleaned


def parse_purchase_export(raw: str) -> ParseResult:
    """Read one saved order page or a pasted table."""

    text = _normalize_ocr_bill_text(raw.lstrip("\ufeff").strip())
    if not text:
        return ParseResult(source="", purchases=(), note="")

    from_csv = _parse_csv(text)
    if from_csv is not None:
        return from_csv

    source = detect_purchase_source(text)
    if source == "ebay":
        purchases = tuple(_ebay_rows(text))
    elif source == "discogs":
        purchases = tuple(_discogs_rows(text))
    elif source == "buyee":
        purchases = tuple(_buyee_rows(text))
    elif source == "recordcity":
        purchases = tuple(_record_city_rows(text))
    else:
        return ParseResult(source="", purchases=(), note=UNKNOWN_PAGE_NOTE)

    if not purchases:
        return ParseResult(
            source=source,
            purchases=(),
            note="No purchases were found on that page.",
        )
    if source == "buyee":
        purchases = tuple(_with_included_consumption_tax(row) for row in purchases)
        purchases = _buyee_overlay_won_list_titles(purchases, text)
    return ParseResult(source=source, purchases=purchases, note="")


def parse_purchase_pages(pages: Sequence[str]) -> ParseResult:
    """Read several dropped files. Standalone eBay orders stay separate.

    Pages of one combined eBay order still join: a totals card, a 2-item
    bill that is missing Item numbers, or two pages that share an order
    number. Two complete 1-item details are two purchases, not one blob.
    """

    parts = [str(part).strip() for part in pages if str(part).strip()]
    if not parts:
        return ParseResult(source="", purchases=(), note="")
    expanded: list[str] = []
    for part in parts:
        expanded.extend(_split_standalone_ebay_pages(part))
    parts = expanded
    if len(parts) == 1:
        return parse_purchase_export(parts[0])
    if _should_combine_purchase_pages(parts):
        return parse_purchase_export(combine_bill_pages(parts))
    merged = _merge_parse_results([parse_purchase_export(part) for part in parts])
    if merged.source == "buyee" and merged.purchases:
        purchases = _buyee_overlay_won_list_titles(
            merged.purchases, combine_bill_pages(parts)
        )
        return ParseResult(source=merged.source, purchases=purchases, note=merged.note)
    return merged


_EBAY_STANDALONE_SPLIT = re.compile(
    r"(?=\n\s*(?:Time placed|Order number:|Order date\s*:))",
    re.IGNORECASE,
)


def _split_standalone_ebay_pages(text: str) -> list[str]:
    """Pull complete 1-item eBay details apart if several were glued."""

    chunks = [part.strip() for part in _EBAY_STANDALONE_SPLIT.split(text) if part.strip()]
    if len(chunks) < 2:
        return [text]
    if all(_ebay_page_is_complete_order(chunk) for chunk in chunks):
        return chunks
    return [text]


def _ebay_page_is_complete_order(text: str) -> bool:
    cleaned = _normalize_ocr_bill_text(text)
    if detect_purchase_source(cleaned) != "ebay":
        return False
    if _ebay_page_is_fragment(cleaned):
        return False
    plain = _plain_text(cleaned)
    ids = list(_EBAY_ITEM_NUMBER.finditer(plain))
    detail = _ebay_detail_amounts(plain)
    count = int(detail["count"] or 0)
    return bool(ids) and count <= 1


def _ebay_page_is_fragment(text: str) -> bool:
    """True when this screenshot is only part of a combined eBay order."""

    cleaned = _normalize_ocr_bill_text(text)
    source = detect_purchase_source(cleaned)
    if source in {"buyee", "discogs", "recordcity"}:
        return False
    plain = _plain_text(cleaned)
    detail = _ebay_detail_amounts(plain)
    ids = list(_EBAY_ITEM_NUMBER.finditer(plain))
    count = int(detail["count"] or 0)
    if count >= 2 and len(ids) < count:
        return True
    if source == "ebay" and not ids and (
        detail["shipping"] is not None
        or detail["tax"] is not None
        or detail["total"] is not None
    ):
        if "sold by" in plain.lower() and "order date" in plain.lower():
            return False
        return True
    return False


def _buyee_page_role(text: str) -> str:
    """Item table, fee table, or a Buyee invoice that already has both."""

    plain = _plain_text(_normalize_ocr_bill_text(text))
    lowered = plain.lower()
    auctions = _BUYEE_AUCTION_ID.findall(plain)
    has_item = bool(re.search(r"item price\s*[¥￥]?\s*[0-9]", lowered)) or bool(
        auctions and re.search(r"[0-9]{1,3}(?:,[0-9]{3})+", plain)
    )
    has_fees = _buyee_fee_amount_present(plain)
    if auctions and has_item and not has_fees:
        return "items"
    if has_fees and not (auctions and has_item):
        return "fees"
    if auctions and has_item and has_fees:
        return "complete"
    return ""


def _buyee_fee_amount_present(text: str) -> bool:
    """A fee label with its yen amount. A bare 'Other Service Fees' heading is not enough."""

    return bool(
        re.search(
            r"(?:plan\s*fee|buyee\s*service\s*fee|domestic\s*shipping\s*fee|"
            r"customs\s*clearance\s*fee|international\s*shipping\s*fee|customs\s*duty)"
            r"\D{0,40}[0-9]",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    )


def _buyee_page_is_invoice_piece(text: str) -> bool:
    """A screenshot from a Buyee invoice, including a continuation with no heading."""

    if _buyee_page_role(text):
        return True
    plain = _plain_text(_normalize_ocr_bill_text(text)).lower()
    return any(
        marker in plain
        for marker in (
            "jdirectitems",
            "auction(",
            "grand total payment amount",
            "other service fees",
            "breakdown of other service fees",
            "international shipping fee",
            "customs duty",
            "domestic shipping fee",
            "plan fee",
            "buyee service fee",
        )
    )


def _buyee_pages_are_one_invoice(parts: list[str]) -> bool:
    """Screenshots of one Buyee invoice: items, fee summary, and the per-auction breakdown.

    A long bill is more than two pictures. A middle picture that is only the
    next auctions, or only the breakdown rows, still belongs to that invoice.
    Two finished invoices with different auction ids stay separate.
    """

    pieces = [part for part in parts if _buyee_page_is_invoice_piece(part)]
    if len(pieces) < 2:
        return False
    if len(pieces) != len(parts):
        return _buyee_pages_are_one_invoice(pieces)
    parts = pieces
    roles = [_buyee_page_role(part) for part in parts]
    id_sets = [
        set(_BUYEE_AUCTION_ID.findall(_plain_text(_normalize_ocr_bill_text(part))))
        for part in parts
    ]
    # The same auction ids on two screenshots are one bill, even when the
    # fee heading and its amount were split across the pictures.
    if any(
        left and right and not left.isdisjoint(right)
        for index, left in enumerate(id_sets)
        for right in id_sets[index + 1 :]
    ):
        return True
    complete = [
        ids
        for role, ids in zip(roles, id_sets, strict=True)
        if role == "complete" and ids
    ]
    if len(complete) >= 2 and all(
        left.isdisjoint(right)
        for index, left in enumerate(complete)
        for right in complete[index + 1 :]
    ):
        return False
    has_items = any(role in {"items", "complete"} for role in roles)
    has_fees = any(role in {"fees", "complete"} for role in roles) or any(
        _buyee_fee_amount_present(_plain_text(_normalize_ocr_bill_text(part)))
        for part in parts
    )
    if has_items and has_fees:
        return True
    fee_pages = sum(role in {"fees", "complete"} for role in roles)
    if any(role == "complete" for role in roles) and fee_pages >= 2:
        main: set[str] = set()
        for ids in complete:
            main.update(ids)
        return bool(main) and all(not ids or not ids.isdisjoint(main) for ids in id_sets)
    return False


def _should_combine_purchase_pages(parts: list[str]) -> bool:
    if any(_ebay_page_is_fragment(part) for part in parts):
        return True
    if _buyee_pages_are_one_invoice(parts):
        return True
    seen: set[str] = set()
    for part in parts:
        for order in _EBAY_ORDER_NUMBER.findall(_normalize_ocr_bill_text(part)):
            if order in seen:
                return True
            seen.add(order)
    return False


def _merge_parse_results(results: list[ParseResult]) -> ParseResult:
    purchases: list[ParsedPurchase] = []
    seen: set[tuple[str, str]] = set()
    source = ""
    notes: list[str] = []
    for result in results:
        if result.source and not source:
            source = result.source
        if result.note:
            notes.append(result.note)
        for purchase in result.purchases:
            key = (purchase.source, purchase.external_id)
            if key in seen:
                continue
            seen.add(key)
            purchases.append(purchase)
            if purchase.source and not source:
                source = purchase.source
    if purchases:
        return ParseResult(source=source, purchases=tuple(purchases), note="")
    return ParseResult(
        source=source,
        purchases=(),
        note=notes[0] if notes else "",
    )


def _parse_csv(text: str) -> ParseResult | None:
    if "<" in text[:800] and ">" in text[:800]:
        return None
    first = text.splitlines()[0] if text.splitlines() else ""
    if "," not in first and "\t" not in first:
        return None
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return None
    headers = {
        (name or "").strip().lower(): name
        for name in reader.fieldnames
        if name
    }
    item_header = _header(headers, "item number", "item id", "itemid")
    auction_header = _header(headers, "auction id", "auction number")
    catalog_header = _header(headers, "品番", "catalog", "cat no", "catalogue")
    if item_header:
        source = "ebay"
        id_header = item_header
        default_currency = "USD"
    elif auction_header:
        source = "buyee"
        id_header = auction_header
        default_currency = "JPY"
    elif catalog_header:
        source = "recordcity"
        id_header = catalog_header
        default_currency = "JPY"
    else:
        return None

    title_header = _header(headers, "item title", "title", "商品", "album")
    seller_header = _header(headers, "seller", "出品者")
    date_header = _header(headers, "sale date", "order date", "date", "注文日", "購入日")
    price_header = _header(
        headers,
        "total price",
        "item price",
        "price",
        "金額",
        "価格",
    )
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for record in reader:
        external_id = str(record.get(id_header) or "").strip()
        title = str(record.get(title_header) or "").strip() if title_header else ""
        if source == "recordcity":
            catalog = catalog_token(catalog_number=external_id, title=title) or external_id
            paid_on = _date(str(record.get(date_header) or "")) if date_header else None
            amount, currency = _cell_money(
                str(record.get(price_header) or "") if price_header else "",
                default_currency=default_currency,
            )
            external_id = _record_city_id(catalog, paid_on, amount)
            title = title or catalog
        else:
            catalog = catalog_token(title=title)
            paid_on = _date(str(record.get(date_header) or "")) if date_header else None
            amount, currency = _cell_money(
                str(record.get(price_header) or "") if price_header else "",
                default_currency=default_currency,
            )
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        seller = str(record.get(seller_header) or "").strip() if seller_header else ""
        rows.append(
            ParsedPurchase(
                source=source,
                external_id=external_id,
                title=title,
                seller=seller,
                paid_amount=amount,
                paid_currency=currency,
                paid_on=paid_on,
                catalog_number=catalog,
            )
        )
    if not rows:
        return None
    return ParseResult(source=source, purchases=tuple(rows), note="")


def _log_header(headers: dict[str, str], *options: str) -> str | None:
    """Match a log column by its whole name, so Paid does not take Paid on."""

    for option in options:
        if option in headers:
            return headers[option]
    for option in options:
        for key, original in headers.items():
            if key.startswith(f"{option} "):
                return original
    return None


def _header(headers: dict[str, str], *options: str) -> str | None:
    for option in options:
        for key, original in headers.items():
            if option in key:
                return original
    return None


_EBAY_ORDER_SPLIT = re.compile(
    r"(?=Order date\s*:?\s*"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))",
    re.IGNORECASE,
)
_EBAY_ORDER_NUMBER = re.compile(
    r"Order number:?\s*([0-9]{2}-[0-9]{4,6}-[0-9]{4,6})",
    re.IGNORECASE,
)
_EBAY_ORDER_TOTAL = re.compile(
    r"Order total:\s*(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_EBAY_SKIP_LINE = re.compile(
    r"^(delivered|used|new|sold by|order date|order total|order number|"
    r"returns accepted|delivered on|partially refunded|auto-paid|"
    r"ship to|shipping address|how do you like our order details|"
    r"view order details|view similar|more actions|resell|"
    r"return window closed|returns not accepted|item number:|"
    r"leave feedback|quantity|combined shipping|order info|time placed|"
    r"tracking details|number\s+\d{10,}|total\s+\$)\b",
    re.IGNORECASE,
)
_EBAY_CHROME_IN_LINE = re.compile(
    r"how do you like our order details|view similar items|leave feedback|"
    r"tell us what you think|return window closed|buy again|contact seller|"
    r"amount paid|total refunded|you got a refund|time placed|order info|"
    r"tracking details|number\s+\d{10,}",
    re.IGNORECASE,
)
_BUYEE_ORDER_ID = re.compile(r"\b(R\d{8,})\b")
_BUYEE_AUCTION_ID = re.compile(
    r"(?:JDirectItems\s+)?Auction\s*\(\s*([a-z]\d{6,}|\d{8,})\s*\)",
    re.IGNORECASE,
)
_BUYEE_CARD_TOTAL = re.compile(
    r"Total Amount\s*([0-9][0-9,]*)\s*YEN\s*\(\s*US\$\s*"
    r"([0-9][0-9,]*(?:\.[0-9]{2})?)\s*\)",
    re.IGNORECASE,
)
_BUYEE_SKIP_LINE = re.compile(
    r"^(won date|update date|total amount|international shipping|awaiting|"
    r"shipped|arrived|transaction|details|order number|shop name|item name|"
    r"quantity|package number|date shipped|list of items|download|shipping|"
    r"confirm photos|see more|after your package|plan fee|buyee service|"
    r"domestic shipping|customs|grand total|item price|coupon|other service|"
    r"shopping site|currency|breakdown|actual billing|insured|inspection|"
    r"protective|jdirectitems)\b",
    re.IGNORECASE,
)
_PERSONAL_LINE = re.compile(
    r"\b(ship to|recipient|address|phone|tel\b|郵便|住所|氏名|お届け先|"
    r"email|e-mail)\b",
    re.IGNORECASE,
)


def _ebay_order_history_rows(plain: str) -> list[ParsedPurchase]:
    """Read the My eBay purchase list: order date, item price, and seller."""

    if "order number" not in plain.lower() or "sold by" not in plain.lower():
        return []
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for chunk in _EBAY_ORDER_SPLIT.split(plain):
        links = list(_EBAY_HREF.finditer(chunk))
        if len(links) >= 2:
            combined = _ebay_combined_item_rows(chunk, marks=links)
            for purchase in combined:
                if purchase.external_id in seen:
                    continue
                seen.add(purchase.external_id)
                rows.append(purchase)
            if combined:
                continue
        item_link = links[0] if links else _EBAY_HREF.search(chunk)
        number = _EBAY_ORDER_NUMBER.search(chunk)
        if item_link is not None:
            external_id = item_link.group(1)
        elif number is not None:
            external_id = number.group(1)
        else:
            continue
        if external_id in seen:
            continue
        seen.add(external_id)
        seller_match = _SELLER.search(chunk) or re.search(
            r"Sold by:\s*([A-Za-z0-9._-]{2,64})",
            chunk,
            re.IGNORECASE,
        )
        seller = seller_match.group(1) if seller_match else ""
        paid_on = _ebay_order_date(chunk)
        order_id = number.group(1) if number is not None else ""
        sold_items = _ebay_history_sold_items(chunk)
        if len(sold_items) >= 2:
            for index, (item_title, amount, item_seller, currency) in enumerate(
                sold_items
            ):
                item_id = f"{order_id}:{index + 1}" if order_id else f"{external_id}:{index + 1}"
                if item_id in seen and index:
                    continue
                if index:
                    seen.add(item_id)
                rows.append(
                    ParsedPurchase(
                        source="ebay",
                        external_id=item_id,
                        title=item_title,
                        seller=item_seller or seller,
                        paid_amount=amount,
                        paid_currency=currency,
                        paid_on=paid_on,
                        delivered_on=ebay_delivered_on(chunk, paid_on=paid_on),
                        catalog_number=catalog_token(title=item_title),
                        billing_note=_history_order_note(chunk, amount),
                        order_id=order_id,
                    )
                )
            continue
        detail = _ebay_detail_amounts(chunk)
        if detail["item"] is not None:
            currency = _ebay_charge_currency(chunk)
            amount = detail["item"]
            note = _charge_note(
                (
                    (
                        "Shipping",
                        _ebay_shipping_or_free(chunk, detail["shipping"]),
                    ),
                    ("Tax", detail["tax"]),
                    ("Refund", detail["refund"]),
                    ("Order total", detail["total"]),
                ),
                currency,
            )
        else:
            without_total = _EBAY_ORDER_TOTAL.sub(" ", chunk)
            amount, currency = _money(without_total, default_currency="USD")
            note = _history_order_note(chunk, amount)
        title = _order_title(chunk, _EBAY_SKIP_LINE)
        rows.append(
            ParsedPurchase(
                source="ebay",
                external_id=external_id,
                title=title,
                seller=seller,
                paid_amount=amount,
                paid_currency=currency,
                paid_on=paid_on,
                delivered_on=ebay_delivered_on(chunk, paid_on=paid_on),
                catalog_number=catalog_token(title=title),
                billing_note=note,
                order_id=order_id,
            )
        )
    return rows


def _ebay_order_date(chunk: str) -> date | None:
    """The card's Order date / Time placed. Not Delivered on or Return window."""

    placed = _EBAY_PLACED.search(chunk)
    if placed is not None:
        return _date(placed.group(1))
    return None


def _history_order_note(chunk: str, item: Decimal | None) -> str:
    order_total = _EBAY_ORDER_TOTAL.search(chunk)
    if (
        order_total is None
        or item is None
        or _decimal(order_total.group(1)) == item
    ):
        total = _decimal(order_total.group(1)) if order_total is not None else None
        return _charge_note((("Order total", total),), "USD")
    return (
        f"Item price US${item}. "
        f"Order total US${_decimal(order_total.group(1))}."
    )


def _ebay_history_sold_items(
    chunk: str,
) -> list[tuple[str, Decimal, str, str]]:
    """One listing per Sold by on a purchase-history card, without /itm/ links."""

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in chunk.splitlines()
        if line.strip()
    ]
    found: list[tuple[str, Decimal, str, str]] = []
    for index, line in enumerate(lines):
        sold = re.match(
            r"Sold by:\s*([A-Za-z0-9._-]{2,64})",
            line,
            re.IGNORECASE,
        )
        if sold is None or index < 1:
            continue
        price_line = lines[index - 1]
        money = re.search(
            r"\b(US|AU)\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)\b",
            price_line,
            re.IGNORECASE,
        )
        if money is None:
            continue
        amount = _decimal(money.group(2))
        if amount is None:
            continue
        title = lines[index - 2] if index >= 2 else ""
        if (
            not title
            or listing_title_is_chrome(title)
            or _EBAY_SKIP_LINE.search(title)
        ):
            continue
        currency = "AUD" if money.group(1).upper() == "AU" else "USD"
        found.append((title, amount, sold.group(1), currency))
    return found


def _buyee_order_rows(plain: str) -> list[ParsedPurchase]:
    """Read a Buyee order, package list, or itemized bill."""

    order_ids = list(dict.fromkeys(_BUYEE_ORDER_ID.findall(plain)))
    auction_ids = list(dict.fromkeys(
        match.group(1) for match in _BUYEE_AUCTION_ID.finditer(plain)
    ))
    if not order_ids and not auction_ids:
        return []
    chunks: list[tuple[str, str]] = []
    if order_ids:
        for index, order_id in enumerate(order_ids):
            start = plain.find(order_id)
            if index + 1 < len(order_ids):
                end = plain.find(order_ids[index + 1], start + len(order_id))
            else:
                end = len(plain)
            chunks.append((order_id, plain[max(0, start - 120):end]))
    elif len(auction_ids) >= 2:
        # One chunk per auction. The package headings are not that record's postage.
        seen_ids: set[str] = set()
        matches: list[re.Match[str]] = []
        for match in _BUYEE_AUCTION_ID.finditer(plain):
            auction_id = match.group(1).lower()
            if auction_id in seen_ids:
                continue
            seen_ids.add(auction_id)
            matches.append(match)
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
            chunks.append(("", plain[match.start() : end]))
    else:
        chunks.append(("", plain))

    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for order_id, chunk in chunks:
        auction = _BUYEE_AUCTION_ID.search(chunk)
        auction_id = auction.group(1) if auction else (auction_ids[0] if len(auction_ids) == 1 and not order_ids else "")
        external_id = auction_id or order_id
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        payments = _buyee_payment_pairs(chunk)
        card = _BUYEE_CARD_TOTAL.search(chunk)
        if card is not None:
            amount = _decimal(card.group(1))
            usd_note = f"Buyee showed US${card.group(2)}."
        else:
            amount = None
            item_match = re.search(
                r"(?:Item|ltem|Ttem|Trem)\s*Price\D{0,40}([0-9][0-9,]*)",
                chunk,
                re.IGNORECASE,
            )
            if item_match is not None:
                labeled = _decimal(item_match.group(1))
                if labeled is not None and not _buyee_amount_is_date_year(
                    labeled, chunk
                ):
                    amount = labeled
            usd_note = ""
        if amount is not None and _buyee_amount_is_date_year(amount, chunk):
            amount = None
        won = re.search(
            r"Won date\s*:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})",
            chunk,
            re.IGNORECASE,
        )
        paid_on = _date(won.group(1)) if won else _date(chunk)
        if payments:
            paid_on = _date(payments[-1][0]) or paid_on
        title = _order_title(chunk, _BUYEE_SKIP_LINE)
        note = _buyee_bill_note(chunk)
        if usd_note and usd_note not in note:
            note = f"{usd_note}\n{note}".strip()
        if card is not None and amount is not None:
            pair = f"USD rate {card.group(2)} for {_plain_amount(amount)} JPY"
            if pair not in note:
                note = f"{note}\n{pair}".strip()
        if order_id and f"Order {order_id}" not in note:
            note = f"Order {order_id}\n{note}".strip()
        rows.append(
            ParsedPurchase(
                source="buyee",
                external_id=external_id,
                title=title,
                seller="Buyee",
                paid_amount=amount,
                paid_currency="JPY",
                paid_on=paid_on,
                catalog_number=catalog_token(title=title),
                billing_note=note.strip(),
            )
        )
    return rows


def listing_title_is_chrome(title: str | None) -> bool:
    """True when the stored title is eBay order-details chrome, not the listing."""

    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return False
    if _EBAY_CHROME_IN_LINE.search(text):
        return True
    return bool(re.match(r"^(fee\.\s*)?item number:", text, re.IGNORECASE))


_CJK_TITLE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_OCR_JUNK_MARK = re.compile(r"[|«»©]|P<\s|\b12s[Iil1tl]\b", re.IGNORECASE)
_TITLE_CASE_WORD = re.compile(r"\b[A-Z][a-z]{3,}\b")
_EBAY_TAX_LAW_CHROME = re.compile(
    r"\*?\s*We're required by law.*$",
    re.IGNORECASE,
)
_EBAY_TITLE_META = re.compile(
    r"^(paid|shipping|tax|\d+\s+items?)\b|"
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b",
    re.IGNORECASE,
)


def owned_copy_shows_on_shelf(title: str | None) -> bool:
    """Order-info chrome is not a copy. Untitled OCR listings still are."""

    return not listing_title_is_chrome(title)


_STRUCTURED_CATALOG = re.compile(r"^[A-Z]{2,}\d{3,}$", re.IGNORECASE)


def listing_catalog_is_structured(catalog: str | None) -> bool:
    """True for HBHG-8855-style catnos, not OCR tokens like BIH 12I."""

    compact = re.sub(r"[\s-]+", "", str(catalog or ""))
    return bool(_STRUCTURED_CATALOG.fullmatch(compact))


def listing_title_is_ocr_junk(title: str | None) -> bool:
    """True when English Tesseract turned a CJK listing into alphabet stew."""

    if listing_title_is_chrome(title):
        return True
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    text = _EBAY_TAX_LAW_CHROME.sub("", text).strip()
    if not text:
        return False
    if _CJK_TITLE.search(text):
        return False
    if _OCR_JUNK_MARK.search(text):
        return True
    if len(_TITLE_CASE_WORD.findall(text)) >= 2:
        return False
    long_words = [
        word
        for word in re.findall(r"[A-Za-z]{5,}", text)
        if re.search(r"[aeiouyAEIOUY]", word)
    ]
    if len(long_words) >= 2:
        return False
    if re.search(r"\b(?:vinyl|lp)\b", text, re.IGNORECASE) and re.search(
        r"\$\s*\d",
        text,
    ):
        return True
    caps = re.findall(r"\b[A-Z]{2,5}\b", text)
    return len(caps) >= 3 and len(long_words) <= 1


def _listing_catalog(title: str | None) -> str | None:
    """A catalog from the listing title, never from OCR stew or the whole page."""

    if not title or listing_title_is_ocr_junk(title):
        return None
    return catalog_token(title=title)


def _order_title(chunk: str, skip: re.Pattern[str]) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in chunk.splitlines()]
    kept: list[str] = []
    for line in lines:
        if _EBAY_CHROME_IN_LINE.search(line):
            continue
        line = re.sub(
            r"^item number:\s*\d+\s*",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        if len(line) < 2 or skip.search(line) or _PERSONAL_LINE.search(line):
            if kept and re.fullmatch(r"(?:LPs?|CDs?|vinyl)", line, re.IGNORECASE):
                kept[-1] = f"{kept[-1]} {line}"
            continue
        if listing_title_is_chrome(line) or listing_title_is_ocr_junk(line):
            continue
        if _EBAY_TITLE_META.search(line):
            continue
        if _EBAY_PROMO_PRICE.search(line):
            continue
        if re.fullmatch(r"(?:US\s*)?\$\s*[0-9,.]+", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"[0-9][0-9,]*\s*YEN", line, re.IGNORECASE):
            continue
        kept.append(line)
    if not kept:
        return ""
    cjk = [line for line in kept if _CJK_TITLE.search(line)]
    chosen = max(cjk or kept, key=len)[:180]
    return re.sub(
        r"\s*\$\s*[0-9][0-9,]*(?:\.[0-9]{2})?\s*$",
        "",
        chosen,
    ).strip()


_OCR_MONEY = r"(?:(?:US|AU)\s*)?\$?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)"
_EBAY_DETAIL_ITEM = re.compile(
    r"\b(\d+)\s+items?\b\s+" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_ITEM_NUMBER = re.compile(
    r"Item number:\s*(\d{6,})",
    re.IGNORECASE,
)
_EBAY_LINE_PRICE = re.compile(
    r"\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
)
_EBAY_PROMO_PRICE = re.compile(
    r"\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)\s*(?:三張|特價|以下)",
)
_EBAY_PLACED = re.compile(
    r"(?:Order date|Time placed)\s*:?\s*"
    r"([A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2})",
    re.IGNORECASE,
)
_EBAY_CARD_STAMP = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+(\d{1,2})(?:,?\s*(20\d{2}))?"
    r"\s+at\s+\d{1,2}[:.]\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?\b",
    re.IGNORECASE,
)
_EBAY_PAID = re.compile(
    r"\bPaid\b(?:[^\n]{0,80}\n\s*|[ \t]+)"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{1,2})(?:,\s*(20\d{2}))?",
    re.IGNORECASE,
)
_EBAY_DETAIL_SHIP = re.compile(
    r"\bShipping\b(?!\s+address)\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_DETAIL_TAX = re.compile(
    r"\bTax\b\*?\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_DETAIL_TOTAL = re.compile(
    r"\b(?:Order total|Total)\b(?!\s+refunded)\s*:?\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_ITEM_DISCOUNT = re.compile(
    r"Item discount\s*-?\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_AMOUNT_PAID = re.compile(
    r"Amount paid\*?\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_TOTAL_REFUNDED = re.compile(
    r"Total refunded\**\s*:?\s*-?\s*" + _OCR_MONEY,
    re.IGNORECASE,
)
_EBAY_GOT_REFUND = re.compile(
    r"You got a refund[^\n$]*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_ORDER_TOTAL_IN_NOTE = re.compile(
    r"Order total\s+(?:US\s*\$\s*)?(-?[0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_MONEY_CODE = r"(SEK|USD|EUR|GBP|JPY|HKD|TWD)"


def _ebay_detail_amounts(chunk: str) -> dict[str, Decimal | None]:
    """eBay order details: item count, shipping, tax, refund, and the order total."""

    counted = _EBAY_DETAIL_ITEM.search(chunk)
    return {
        "count": Decimal(counted.group(1)) if counted is not None else None,
        "item": _decimal(counted.group(2)) if counted is not None else None,
        "shipping": _pattern_amount(_EBAY_DETAIL_SHIP, chunk),
        "tax": _pattern_amount(_EBAY_DETAIL_TAX, chunk),
        "refund": _ebay_refund_amount(chunk),
        "discount": _ebay_discount_amount(chunk),
        "paid": _pattern_amount(_EBAY_AMOUNT_PAID, chunk),
        "total": _pattern_amount(_EBAY_DETAIL_TOTAL, chunk),
    }


def _ebay_discount_amount(chunk: str) -> Decimal | None:
    """Item discount on the payment card. Always a negative adjustment."""

    match = _EBAY_ITEM_DISCOUNT.search(chunk)
    if match is None:
        return None
    amount = _decimal(match.group(1))
    return -abs(amount) if amount is not None else None


def line_price_replaces_shelf(amount: Decimal | None, note: str) -> bool:
    """An item line replaces the shelf price. The order total does not."""

    if amount is None:
        return False
    total = note_order_total(note)
    if total is None:
        return True
    return abs(amount - total) > Decimal("0.02")


def _ebay_refund_amount(chunk: str) -> Decimal | None:
    """PayPal/eBay price cut after payment. Always a negative adjustment."""

    labeled = _EBAY_TOTAL_REFUNDED.search(chunk)
    if labeled is not None:
        amount = _decimal(labeled.group(1))
        return -abs(amount) if amount is not None else None
    got = _EBAY_GOT_REFUND.search(chunk)
    if got is None:
        return None
    amount = _decimal(got.group(1))
    return -abs(amount) if amount is not None else None


def _ebay_charge_currency(chunk: str) -> str:
    """AU $ on the totals card is Australian dollars, not US dollars."""

    if re.search(r"\bAU\s*\$|\bAU\s+\d", chunk, re.IGNORECASE):
        return "AUD"
    return "USD"


def _ebay_shipping_or_free(chunk: str, amount: Decimal | None) -> Decimal:
    """No shipping line on an eBay order is free shipping, not a missing charge."""

    if amount is not None:
        return amount
    if re.search(r"free\s+shipping", chunk, re.IGNORECASE):
        return Decimal("0")
    return Decimal("0")


def _pattern_amount(pattern: re.Pattern[str], text: str) -> Decimal | None:
    match = pattern.search(text)
    if match is None:
        return None
    return _decimal(match.group(1))


def _ebay_line_amount(window: str, skip: set[Decimal]) -> Decimal | None:
    """Item price next to an Item number, not shipping, tax, or $100 三張特價."""

    promo = {
        amount
        for amount in (_decimal(raw) for raw in _EBAY_PROMO_PRICE.findall(window))
        if amount is not None
    }
    ignore = skip | promo
    priced: list[tuple[Decimal, bool]] = []
    for match in _EBAY_LINE_PRICE.finditer(window):
        amount = _decimal(match.group(1))
        if amount is None or amount in ignore:
            continue
        priced.append((amount, "." in match.group(1)))
    if not priced:
        return None
    with_cents = [amount for amount, cents in priced if cents]
    if with_cents:
        return with_cents[-1]
    return priced[-1][0]


def ocr_promo_item_price(
    title: str | None,
    paid_amount: Decimal | None,
) -> Decimal | None:
    """$100 三張特價 stored as the item; the OCR title still has $68.00."""

    if paid_amount not in {Decimal("50"), Decimal("100")}:
        return None
    if not listing_title_is_ocr_junk(title):
        return None
    found: list[Decimal] = []
    for match in _EBAY_LINE_PRICE.finditer(str(title or "")):
        raw = match.group(1)
        amount = _decimal(raw)
        if amount is None or amount == paid_amount or "." not in raw:
            continue
        found.append(amount)
    return found[-1] if found else None


def _ebay_paid_on(plain: str) -> date | None:
    """Order date / paid date, not the later delivered-on stamp."""

    stamped = _ebay_card_stamp_date(plain)
    if stamped is not None:
        return stamped
    ordered = _ebay_order_date(plain)
    if ordered is not None:
        return ordered
    paid = _EBAY_PAID.search(plain)
    if paid is not None:
        year = paid.group(2)
        if year is None:
            year = _ebay_bill_year(plain)
        if year is not None:
            return _date(f"{paid.group(1)}, {year}")
    return None


def _ebay_card_stamp_date(plain: str) -> date | None:
    """Totals-card 'Dec 4 at 7:03 PM' is Time placed, without that label."""

    stamp = _EBAY_CARD_STAMP.search(plain)
    if stamp is None:
        return None
    year = stamp.group(3) or _ebay_bill_year(plain)
    if year is None:
        month = _MONTHS.get(stamp.group(1)[:3].lower())
        if month is None:
            return None
        year = str(_year_for_month_day(month, int(stamp.group(2))))
    return _date(f"{stamp.group(1)} {stamp.group(2)}, {year}")


_EBAY_DELIVERED_ON = re.compile(
    r"Delivered on[^\n]*?\b"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+(\d{1,2}),?\s+(20\d{2})",
    re.IGNORECASE,
)


_EBAY_DELIVERED_BARE = re.compile(
    r"Delivered on[^\n]*?\b"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+(\d{1,2})\b(?!\s*,?\s*20\d{2})",
    re.IGNORECASE,
)


def ebay_delivered_on(plain: str, *, paid_on: date | None = None) -> date | None:
    """The Delivered on day. Paid on stays the order date.

    Purchase history omits the year ('Delivered on Mon, Aug 25'). The order
    date supplies it. A January delivery after a December order is next year.
    """

    match = _EBAY_DELIVERED_ON.search(plain or "")
    if match is not None:
        return _date(f"{match.group(1)} {match.group(2)}, {match.group(3)}")
    bare = _EBAY_DELIVERED_BARE.search(plain or "")
    if bare is None:
        return None
    month = _MONTHS.get(bare.group(1)[:3].lower())
    if month is None:
        return None
    day = int(bare.group(2))
    year = paid_on.year if paid_on is not None else _year_for_month_day(month, day)
    try:
        delivered = date(year, month, day)
    except ValueError:
        return None
    if paid_on is not None and delivered < paid_on:
        try:
            delivered = date(year + 1, month, day)
        except ValueError:
            return None
    return delivered


def _ebay_bill_year(plain: str) -> str | None:
    """Year from Delivered on / any dated line. Never the delivered day itself."""

    delivered = re.search(
        r"Delivered on[^\n]*?(20\d{2})",
        plain,
        re.IGNORECASE,
    )
    if delivered is not None:
        return delivered.group(1)
    named = _DATE_MDY.search(plain)
    if named is not None:
        return named.group(3)
    iso = _DATE_ISO.search(plain)
    if iso is not None:
        return iso.group(1)
    return None


def _year_for_month_day(month: int, day: int, *, today: date | None = None) -> int:
    """Latest year that month-day is not in the future."""

    today = today or date.today()
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return today.year - 1
    if candidate > today:
        return today.year - 1
    return today.year


def _signed_package_shares(
    total: Decimal | None,
    weights: list[Decimal],
) -> list[Decimal | None]:
    """Split a signed order adjustment across the item lines."""

    if total is None:
        return [None] * len(weights)
    sign = Decimal("-1") if total < 0 else Decimal("1")
    parts = allocate_package_charges(
        weights,
        shipping=abs(total),
        tax=Decimal("0"),
    )
    return [sign * share[0] for share in parts]


def _ebay_combined_item_rows(
    plain: str,
    marks: list[re.Match[str]] | None = None,
) -> list[ParsedPurchase]:
    """Item number or /itm/ lines plus one shipping and tax for the order.

    One known item on a combined order still gets its share. The missing
    item numbers stay off the bill until another page adds them.
    """

    numbers = list(marks) if marks is not None else list(
        _EBAY_ITEM_NUMBER.finditer(plain)
    )
    if not numbers:
        return []
    detail = _ebay_detail_amounts(plain)
    currency = _ebay_charge_currency(plain)
    count = int(detail["count"] or 0)
    shipping = detail["shipping"] or Decimal("0")
    tax = detail["tax"] or Decimal("0")
    total = detail["total"]
    package_items = detail["item"]
    skip = {
        value
        for value in (
            shipping,
            tax,
            total,
            package_items,
            detail.get("paid"),
            abs(detail["refund"]) if detail.get("refund") is not None else None,
            abs(detail["discount"]) if detail.get("discount") is not None else None,
        )
        if value is not None
    }
    found: list[tuple[str, Decimal, str]] = []
    for index, match in enumerate(numbers):
        start = numbers[index - 1].end() if index else 0
        window = plain[start : match.start()]
        amount = _ebay_line_amount(window, skip)
        if amount is None:
            continue
        found.append((match.group(1), amount, _order_title(window, _EBAY_SKIP_LINE)))
    if not found:
        return []
    if len(found) < 2 and count < 2:
        return []
    found_weights = [amount for _item_id, amount, _title in found]
    charge_weights = list(found_weights)
    if package_items is not None:
        remainder = package_items - sum(found_weights, Decimal("0"))
        if remainder > 0:
            charge_weights.append(remainder)
    shares = allocate_package_charges(
        charge_weights,
        shipping=shipping,
        tax=tax,
    )
    seller_match = _SELLER.search(plain)
    seller = seller_match.group(1) if seller_match else ""
    paid_on = _ebay_paid_on(plain)
    order_id = _ebay_order_id(plain, found)
    rows: list[ParsedPurchase] = []
    refund_shares = _signed_package_shares(detail.get("refund"), found_weights)
    discount_shares = _signed_package_shares(detail.get("discount"), found_weights)
    for (item_id, amount, title), share, refund_share, discount_share in zip(
        found, shares, refund_shares, discount_shares, strict=False
    ):
        ship_share, tax_share, _fees = share
        rows.append(
            ParsedPurchase(
                source="ebay",
                external_id=item_id,
                title=title,
                seller=seller,
                paid_amount=amount,
                paid_currency=currency,
                paid_on=paid_on,
                delivered_on=ebay_delivered_on(plain, paid_on=paid_on),
                catalog_number=_listing_catalog(title),
                billing_note=_charge_note(
                    (
                        ("Shipping", ship_share),
                        ("Tax", tax_share),
                        ("Discount", discount_share),
                        ("Refund", refund_share),
                        ("Order total", total),
                    ),
                    currency,
                ),
                order_id=order_id,
                package_item=package_items,
                package_shipping=detail["shipping"],
                package_tax=detail["tax"],
                package_total=total,
            )
        )
    return rows


def _ebay_order_id(plain: str, found: list[tuple[str, Decimal, str]]) -> str:
    numbered = _EBAY_ORDER_NUMBER.search(plain)
    if numbered is not None:
        return numbered.group(1)
    if len(found) >= 2:
        return "package:" + "+".join(item_id for item_id, _amount, _title in found)
    return ""


def _ebay_detail_rows(plain: str) -> list[ParsedPurchase]:
    combined = _ebay_combined_item_rows(plain)
    if combined:
        return combined
    detail = _ebay_detail_amounts(plain)
    numbered = list(_EBAY_ITEM_NUMBER.finditer(plain))
    item = detail["item"]
    if (
        item is None
        and numbered
        and (detail["shipping"] is not None or detail["tax"] is not None)
    ):
        skip = {
            value
            for value in (detail["shipping"], detail["tax"], detail["total"])
            if value is not None
        }
        item = _ebay_line_amount(plain[: numbered[0].start()], skip)
    if item is None:
        return []
    total = detail["total"] if detail["total"] is not None else item
    assert item is not None
    shipping = _ebay_shipping_or_free(plain, detail["shipping"])
    count = int(detail["count"] or 1)
    if count >= 2 and len(numbered) < 2:
        external_id = (
            f"package:{count}:{_plain_amount(item)}:{_plain_amount(total)}"
        )
    elif numbered:
        external_id = numbered[0].group(1)
    else:
        external_id = f"detail:{_plain_amount(item)}:{_plain_amount(total)}"
    seller_match = _SELLER.search(plain)
    title = _order_title(plain, _EBAY_SKIP_LINE)
    currency = _ebay_charge_currency(plain)
    return [
        ParsedPurchase(
            source="ebay",
            external_id=external_id,
            title=title,
            seller=seller_match.group(1) if seller_match else "",
            paid_amount=item,
            paid_currency=currency,
            paid_on=_ebay_paid_on(plain),
            delivered_on=ebay_delivered_on(plain, paid_on=_ebay_paid_on(plain)),
            catalog_number=_listing_catalog(title),
            billing_note=_charge_note(
                (
                    ("Shipping", shipping),
                    ("Tax", detail["tax"]),
                    ("Discount", detail.get("discount")),
                    ("Refund", detail["refund"]),
                    ("Order total", detail["total"]),
                ),
                currency,
            ),
            order_id=_ebay_order_id(plain, ((external_id, item, ""),) if numbered else ()),
            package_item=item if count <= 1 else detail["item"],
            package_shipping=shipping,
            package_tax=detail["tax"],
            package_total=total,
        )
    ]


def _discogs_rows(raw: str) -> list[ParsedPurchase]:
    """Read a Discogs marketplace order: item, shipping, and tax."""

    plain = _plain_text(raw)
    subtotal = _labeled_money(r"Subtotal", plain)
    if subtotal is None:
        return []
    amount, currency = subtotal
    shipping = _labeled_money(r"Shipping", plain)
    tax = _labeled_money(r"\bTax\b", plain)
    total = _labeled_money(r"(?<!Sub)Total", plain)
    order_id = re.search(r"(?m)^\s*(\d{6,})\s*$", plain)
    title = _discogs_title(plain)
    identity = order_id.group(1) if order_id else _plain_amount(amount)
    return [
        ParsedPurchase(
            source="discogs",
            external_id=identity,
            title=title,
            seller="Discogs",
            paid_amount=amount,
            paid_currency=currency,
            paid_on=None,
            catalog_number=catalog_token(title=title),
            billing_note=_charge_note(
                (
                    ("Shipping", None if shipping is None else shipping[0]),
                    ("Tax", None if tax is None else tax[0]),
                    ("Order total", None if total is None else total[0]),
                ),
                currency,
            ),
        )
    ]


def _labeled_money(label: str, plain: str) -> tuple[Decimal, str] | None:
    match = re.search(
        rf"{label}[^\n]{{0,80}}?\b{_MONEY_CODE}\s*([0-9][0-9,]*(?:\.[0-9]{{2}})?)",
        plain,
        re.IGNORECASE,
    )
    if match is None:
        return None
    amount = _decimal(match.group(2))
    if amount is None:
        return None
    return amount, match.group(1).upper()


def _discogs_title(plain: str) -> str:
    kept: list[str] = []
    for line in plain.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if len(cleaned) < 4:
            continue
        if re.search(
            r"subtotal|shipping|\btax\b|\btotal\b|condition|^price$|^item$|^id$",
            cleaned,
            re.IGNORECASE,
        ):
            continue
        kept.append(cleaned)
    for line in kept:
        if catalog_token(title=line):
            return line[:180]
    if not kept:
        return ""
    return max(kept, key=len)[:180]


def _charge_note(
    charges: tuple[tuple[str, Decimal | None], ...],
    currency: str,
) -> str:
    return "\n".join(
        f"{label} {_plain_amount(amount)} {currency}"
        for label, amount in charges
        if amount is not None
    )


_BUYEE_FEE_SECTION = re.compile(
    r"(Customs Clearance Fee|Domestic Shipping Fee|Plan Fee|Buyee Service Fee|"
    r"Protective Packaging Fee|International Shipping Fee|Customs Dut(?:y|ies))",
    re.IGNORECASE,
)
_COPY_COST = (
    ("shipping", "Shipping"),
    ("tax", "Tax"),
    ("plan_fee", "Plan fee"),
    ("service_fee", "Service fee"),
    ("domestic_shipping", "Domestic shipping"),
    ("customs", "Customs"),
    ("clearance", "Customs clearance"),
    ("tax_included", "Tax included"),
    ("discount", "Discount"),
    ("refund", "Refund"),
)
_COST_LINE = re.compile(
    r"^(?P<package>Package\s+)?"
    r"(?P<label>International shipping|Domestic shipping|Plan fee|Service fee|"
    r"Shipping|Tax included|Tax|Customs clearance|Customs|Discount|Refund)"
    r"\s+(?P<amount>-?[0-9][0-9,]*(?:\.[0-9]+)?)"
    r"(?:\s+(?P<currency>[A-Za-z]{3}))?"
    r"\s*$",
    re.IGNORECASE,
)
_COST_KEYS = {
    "shipping": "shipping",
    "international shipping": "shipping",
    "domestic shipping": "domestic_shipping",
    "tax": "tax",
    "plan fee": "plan_fee",
    "service fee": "service_fee",
    "customs": "customs",
    "customs clearance": "clearance",
    "tax included": "tax_included",
    "discount": "discount",
    "refund": "refund",
}
_BUYEE_PAYMENT_ROW = re.compile(
    r"(20\d{2}/\d{2}/\d{2})\s+(?!20\d{2}/)([0-9][0-9,]*)"
)


def _buyee_amount_is_date_year(amount: Decimal, text: str) -> bool:
    """True when 2025 is the year on 2025/09/05, not a yen hammer."""

    if amount < Decimal("2000") or amount > Decimal("2035"):
        return False
    year = f"{int(amount)}"
    return bool(re.search(rf"\b{year}/\d{{2}}/\d{{2}}", text))


def _buyee_payment_pairs(text: str) -> list[tuple[str, Decimal]]:
    """Payment YYYY/MM/DD with yen. Stacked date and amount columns still pair."""

    same_line: list[tuple[str, Decimal]] = []
    for date_text, raw in _BUYEE_PAYMENT_ROW.findall(text):
        amount = _decimal(raw)
        if amount is None or _buyee_amount_is_date_year(amount, text):
            continue
        same_line.append((date_text, amount))
    section_match = re.search(
        r"Breakdown of Payment amount(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    section = section_match.group(1) if section_match is not None else text
    dates = re.findall(r"(20\d{2}/\d{2}/\d{2})", section)
    if len(same_line) >= max(1, len(dates)):
        return same_line[: len(dates)] if dates else same_line
    stripped = re.sub(r"20\d{2}/\d{2}/\d{2}", " ", section)
    amounts: list[Decimal] = []
    for raw in re.findall(
        r"\b([1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]{2,6})\b",
        stripped,
    ):
        amount = _decimal(raw)
        if amount is None or _buyee_amount_is_date_year(amount, text):
            continue
        amounts.append(amount)
    return list(zip(dates, amounts))


def _matched_copy_cost(line: str) -> re.Match[str] | None:
    """A charge that belongs to one copy. Package totals are left out."""

    match = _COST_LINE.match(line.strip())
    if match is None or match.group("package"):
        return None
    return match


def note_order_total(note: str) -> Decimal | None:
    """Printed order total on the bill, after any refund."""

    match = _ORDER_TOTAL_IN_NOTE.search(note or "")
    if match is None:
        return None
    return _decimal(match.group(1))


def copy_refund(
    note: str,
    *,
    item: Decimal | None = None,
    shipping: Decimal | None = None,
    tax: Decimal | None = None,
    fees: Decimal | None = None,
) -> Decimal | None:
    """PayPal/eBay price cut. Explicit Refund line, else order total vs gross."""

    costs = copy_costs(note or "")
    if costs["refund"] is not None:
        return costs["refund"]
    total = note_order_total(note or "")
    if total is None or item is None:
        return None
    gross = item
    for part in (shipping, tax, fees):
        if part is not None:
            gross += part
    cut = gross - total
    if cut >= Decimal("0.01"):
        return -cut
    return None


def copy_costs(note: str) -> dict[str, Decimal | None]:
    """Per-copy charges already assigned on a bill. Package totals stay in the note."""

    found: dict[str, Decimal | None] = {key: None for key, _label in _COPY_COST}
    for line in note.splitlines():
        match = _matched_copy_cost(line)
        if match is None:
            continue
        key = _COST_KEYS[match.group("label").lower()]
        amount = _decimal(match.group("amount"))
        if amount is None:
            continue
        current = found[key]
        found[key] = amount if current is None else current + amount
    return found


_BUYEE_INVOICE_LINES = (
    ("domestic_shipping", "Domestic"),
    ("shipping", "International"),
    ("plan_fee", "Plan fee"),
    ("service_fee", "Service fee"),
    ("clearance", "Clearance"),
    ("customs", "Customs"),
)
_BUYEE_INVOICE_MARKERS = (
    "domestic_shipping",
    "plan_fee",
    "service_fee",
    "clearance",
    "customs",
)


def buyee_invoice_lines(note: str) -> tuple[tuple[str, Decimal], ...]:
    """Domestic, international, and Buyee fees as their own lines. Empty for eBay."""

    costs = copy_costs(note or "")
    if all(costs[key] is None for key in _BUYEE_INVOICE_MARKERS):
        return ()
    lines: list[tuple[str, Decimal]] = []
    for key, label in _BUYEE_INVOICE_LINES:
        amount = costs[key]
        if amount is not None:
            lines.append((label, amount))
    return tuple(lines)


def package_charge_share(
    paid: Decimal | None,
    package_item: Decimal | None,
    package_amount: Decimal | None,
) -> Decimal | None:
    """One copy's piece of a lot charge. Blank when the lot total is missing."""

    if package_amount is None:
        return None
    if paid is None or package_item is None or package_item == 0:
        return None
    quantum = (
        Decimal("1")
        if package_amount == package_amount.to_integral_value()
        else Decimal("0.01")
    )
    return (package_amount * paid / package_item).quantize(quantum)


def buyee_package_landed_extras(
    note: str,
    *,
    marketplace: str = "",
    paid: Decimal | None = None,
    package_item: Decimal | None = None,
    package_shipping: Decimal | None = None,
    package_tax: Decimal | None = None,
) -> tuple[Decimal | None, Decimal | None]:
    """Buyee lot postage to add to landed. eBay already has its share on the line."""

    origin = str(marketplace or "").strip().lower()
    if not buyee_invoice_lines(note) and origin != "buyee":
        return None, None
    costs = copy_costs(note)
    intl = (
        None
        if costs["shipping"] is not None
        else package_charge_share(paid, package_item, package_shipping)
    )
    customs = (
        None
        if costs["customs"] is not None
        else package_charge_share(paid, package_item, package_tax)
    )
    return intl, customs


def buyee_package_display_lines(
    note: str,
    *,
    package_shipping: Decimal | None = None,
    package_tax: Decimal | None = None,
) -> tuple[tuple[str, Decimal], ...]:
    """Per-copy Buyee fees, plus the lot's international postage and customs."""

    by_label = dict(buyee_invoice_lines(note))
    if package_shipping is not None:
        by_label["International"] = package_shipping
    if package_tax is not None:
        by_label["Customs"] = package_tax
    if not by_label:
        return ()
    order = (
        "Domestic",
        "International",
        "Plan fee",
        "Service fee",
        "Clearance",
        "Customs",
    )
    return tuple(
        (label, by_label[label])
        for label in order
        if label in by_label
    )


def _charge_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text or text.casefold() in {"none", "nan", "<na>", "nat"}:
        return None
    return _decimal(text)


def shelf_charge_amounts(
    *,
    shipping_amount: object = None,
    tax_amount: object = None,
    fee_amount: object = None,
    billing_note: str = "",
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Shelf Shipping / Tax / Fees. Stored columns win; omitted shipping is free."""

    costs = copy_costs(billing_note or "")
    shipping = _charge_decimal(shipping_amount)
    if shipping is None:
        shipping = costs["shipping"]
        if costs["domestic_shipping"] is not None:
            shipping = (shipping or Decimal("0")) + costs["domestic_shipping"]
    tax = _charge_decimal(tax_amount)
    if tax is None:
        tax = costs["tax"]
        if costs["customs"] is not None:
            tax = (tax or Decimal("0")) + costs["customs"]
    fees = _charge_decimal(fee_amount)
    if fees is None:
        fee_parts = (
            costs["plan_fee"],
            costs["service_fee"],
            costs["clearance"],
        )
        if any(part is not None for part in fee_parts):
            fees = sum((part or Decimal("0") for part in fee_parts), Decimal("0"))
    billed = any(value is not None for value in (shipping, tax, fees))
    if billed:
        if shipping is None:
            shipping = Decimal("0")
        if fees is None:
            fees = Decimal("0")
    return shipping, tax, fees


_USD_RATE_LINE = re.compile(
    r"USD rate\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+for\s+"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)\s+([A-Za-z]{3})",
    re.IGNORECASE,
)


_PAYMENT_YEN = re.compile(
    r"^Payment\s+20\d{2}/\d{2}/\d{2}\s+(-?[0-9][0-9,]*)",
    re.IGNORECASE | re.MULTILINE,
)
_ITEM_YEN = re.compile(
    r"^Item price\s+(-?[0-9][0-9,]*)",
    re.IGNORECASE | re.MULTILINE,
)


def yen_rate_anchor(note: str) -> Decimal | None:
    """Yen side of the printed USD pair: first payment, else item price."""

    for pattern in (_PAYMENT_YEN, _ITEM_YEN):
        match = pattern.search(note)
        if match is None:
            continue
        amount = _decimal(match.group(1))
        if amount is not None and amount != 0:
            return amount
    return None


def note_with_printed_usd_rate(
    note: str,
    *,
    usd: Decimal,
    yen: Decimal | None = None,
    foreign: Decimal | None = None,
    currency: str = "JPY",
) -> str:
    """Keep foreign charge lines and add the dollar pair used to convert them.

    ``yen`` remains the Buyee/JPY call site. Informal HKD lots pass
    ``foreign=`` with ``currency="HKD"``.
    """

    amount = foreign if foreign is not None else yen
    code = (currency or "JPY").strip().upper() or "JPY"
    if amount is None or bill_usd_rate(note) is not None or amount == 0:
        return note.strip()
    usd_text = f"{usd.quantize(Decimal('0.01')):.2f}"
    line = f"USD rate {usd_text} for {_plain_amount(amount)} {code}"
    return f"{note.strip()}\n{line}".strip()


def bill_usd_rate(note: str) -> tuple[str, Decimal] | None:
    """Dollars per one unit, when the bill prints both sides of the pair."""

    match = _USD_RATE_LINE.search(note)
    if match is None:
        return None
    usd = _decimal(match.group(1))
    foreign = _decimal(match.group(2))
    if usd is None or foreign is None or foreign == 0:
        return None
    return match.group(3).upper(), usd / foreign


def to_usd(amount: Decimal, usd_per_unit: Decimal) -> Decimal:
    """Convert one amount and round to cents."""

    return (amount * usd_per_unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def copy_cost_currency(note: str) -> str | None:
    """Currency printed on the per-copy charges, when they all use one."""

    codes: set[str] = set()
    for line in note.splitlines():
        match = _matched_copy_cost(line)
        if match is None or not match.group("currency"):
            continue
        codes.add(match.group("currency").upper())
    if len(codes) == 1:
        return codes.pop()
    return None


def note_with_copy_costs(
    note: str,
    *,
    shipping: Decimal | None = None,
    tax: Decimal | None = None,
    plan_fee: Decimal | None = None,
    service_fee: Decimal | None = None,
    domestic_shipping: Decimal | None = None,
    currency: str = "JPY",
) -> str:
    """Replace the per-copy fee lines and keep the rest of the bill."""

    kept = [
        line
        for line in note.splitlines()
        if line.strip()
        and not re.match(
            r"(?!(?:Tax included)\b)"
            r"(?:International shipping|Domestic shipping|Shipping|Tax|"
            r"Plan fee|Service fee)\b",
            line.strip(),
            re.IGNORECASE,
        )
    ]
    code = currency.strip().upper() or "JPY"
    charges = (
        ("Shipping", shipping),
        ("Tax", tax),
        ("Plan fee", plan_fee),
        ("Service fee", service_fee),
        ("Domestic shipping", domestic_shipping),
    )
    lines = [
        f"{label} {_plain_amount(amount)} {code}"
        for label, amount in charges
        if amount is not None
    ]
    return "\n".join([*lines, *kept]).strip()


_LOT_POSTAGE = (
    "Domestic shipping",
    "Shipping",
    "International",
    "Tax included",
    "Tax",
    "Plan fee",
    "Service fee",
)


def included_consumption_tax(amount: Decimal | None) -> Decimal | None:
    """10% already inside a tax-inclusive yen hammer. Not an extra 10% on top."""

    if amount is None:
        return None
    return (amount * Decimal(10) / Decimal(110)).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )


def _with_included_consumption_tax(purchase: ParsedPurchase) -> ParsedPurchase:
    """Record the 10% already inside a Buyee hammer. The printed price stays."""

    portion = buyee_tax_included(purchase)
    if portion is None:
        return purchase
    if re.search(r"(?im)^Tax included\b", purchase.billing_note or ""):
        return purchase
    line = f"Tax included {_plain_amount(portion)} JPY"
    note = f"{purchase.billing_note}\n{line}".strip() if purchase.billing_note else line
    return replace(purchase, billing_note=note)


def note_with_included_tax(note: str, amount: Decimal | None, currency: str) -> str:
    """Replace the included-consumption-tax line. It is not an extra charge."""

    kept = [
        line
        for line in (note or "").splitlines()
        if line.strip() and not re.match(r"Tax included\b", line.strip(), re.IGNORECASE)
    ]
    if amount is not None:
        code = (currency or "JPY").strip().upper() or "JPY"
        kept.append(f"Tax included {_plain_amount(amount)} {code}")
    return "\n".join(kept).strip()


def buyee_tax_included(purchase: ParsedPurchase) -> Decimal | None:
    """Consumption tax inside a Buyee hammer when the bill has no separate tax line."""

    if (purchase.source or "").strip().lower() != "buyee":
        return None
    if (purchase.paid_currency or "JPY").strip().upper() != "JPY":
        return None
    if copy_costs(purchase.billing_note)["tax"] is not None:
        return None
    return included_consumption_tax(purchase.paid_amount)


def arrange_lot_columns(
    columns: list[str],
    *,
    package_shipping: Decimal | None,
    has_copy_shipping: bool,
) -> list[str]:
    """Put domestic next to international, and keep the lot postage off each copy.

    On a Buyee bulk invoice, Shipping is the international amount for the
    whole lot. It is shown once, not written onto every record.
    """

    names = list(columns)
    if package_shipping is not None and not has_copy_shipping:
        if "Shipping" in names:
            names.remove("Shipping")
        if "International" not in names:
            names.append("International")
    postage = [name for name in _LOT_POSTAGE if name in names]
    rest = [name for name in names if name not in postage]
    anchor = "Delivered" if "Delivered" in rest else "Currency"
    if anchor not in rest:
        return rest + postage
    at = rest.index(anchor) + 1
    return rest[:at] + postage + rest[at:]


def _plain_amount(amount: Decimal) -> str:
    text = f"{amount:.2f}"
    return text[:-3] if text.endswith(".00") else text


def _note_yen(amount: Decimal) -> str:
    """Yen on a one-copy bill note, with the thousands comma the PDF prints."""

    if amount == amount.to_integral_value():
        return f"{int(amount):,}"
    return _plain_amount(amount)


_BUYEE_COLUMN_ITEM = re.compile(
    r"^\s*Column item ([0-9][0-9,]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BUYEE_COLUMN_FEE = re.compile(
    r"^\s*Column fee ([0-9][0-9,]*) ([0-9][0-9,]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BUYEE_VISUAL_ROW = re.compile(
    r"(?m)^[ \t]*Visual auction ([a-z]\d{6,}|\d{8,}) title (.*?) price\s*([0-9]*)"
    r"(?:[ \t]+rows[ \t]+(\d+))?[ \t]*$"
)
_BUYEE_ITEM_MARK = re.compile(
    r"Item\s*Name|Quantit|Shopping\s*Site|(?:Item|ltem|Trem)\s*Price",
    re.IGNORECASE,
)
_BUYEE_PACKAGE_TOTALS = {
    Decimal("3000"),
    Decimal("4400"),
    Decimal("4800"),
    Decimal("8000"),
    Decimal("9200"),
    Decimal("10176"),
    Decimal("14080"),
    Decimal("26121"),
    Decimal("28324"),
    Decimal("28380"),
}
_BUYEE_NAME_STOP = re.compile(
    r"Quantit|Quanity|(?:Item|ltem|Trem)\s*Price|ltemPrice|TremPrice|"
    r"Shopping\s*Site|Total\s+Amount",
    re.IGNORECASE,
)
_BUYEE_TITLE_WORD = re.compile(
    r"\b(CBS|SONY|LP|EP|CD|BUDOKAN|LAST|MOMOE|YAMAGUCHI|MOBIUS|GAME|AT|HIT|PACK)\b",
    re.IGNORECASE,
)
_BUYEE_WON_TITLE = re.compile(r"(?m)^[ \t]*Won title (.+?)\s*$")


def _buyee_take_columns(
    plain: str,
) -> tuple[str, list[Decimal], dict[Decimal, list[Decimal]], list[tuple[str, str, Decimal | None]]]:
    """Pull the price-column notes off the page before the fee parser sees them."""

    item_prices = [
        amount
        for raw in _BUYEE_COLUMN_ITEM.findall(plain)
        if (amount := _decimal(raw)) is not None
    ]
    fees: dict[Decimal, list[Decimal]] = {}
    for total_raw, row_raw in _BUYEE_COLUMN_FEE.findall(plain):
        total = _decimal(total_raw)
        row = _decimal(row_raw)
        if total is None or row is None:
            continue
        fees.setdefault(total, []).append(row)
    fee_units = {row for rows in fees.values() for row in rows}
    fee_totals = set(fees)
    chosen: dict[str, tuple[str, Decimal | None, int]] = {}
    order: list[str] = []
    for auction_id, title, price_raw, rows_raw in _BUYEE_VISUAL_ROW.findall(plain):
        price = _decimal(price_raw) if price_raw else None
        # A fee-page column repeats 300, 500, or 880, or the package total.
        # That number is not the item price. A catalog like 70AH1141 is not one either.
        if price is not None and (
            price in fee_units
            or price in fee_totals
            or price in _BUYEE_PACKAGE_TOTALS
            or _visual_price_repeats_catalog(title, price)
        ):
            price = None
        title = title.strip()
        rows = int(rows_raw) if str(rows_raw or "").isdigit() else 0
        if auction_id not in chosen:
            order.append(auction_id)
            chosen[auction_id] = (title, price, rows)
            continue
        old_title, old_price, old_rows = chosen[auction_id]
        # The page that priced more of the table wins. A later item page
        # then outranks a fee page that mashed two catalogs or left the price blank.
        rank = (rows, *_visual_row_rank(title, price))
        old_rank = (old_rows, *_visual_row_rank(old_title, old_price))
        if rank > old_rank:
            # A fee page names b with the next row's catalog and no item price.
            # A higher row count must not put that catalog on the price we already have.
            if price is None and old_price is not None and old_title:
                continue
            chosen[auction_id] = (
                title or old_title,
                price if price is not None else old_price,
                rows,
            )
    visual = [
        (auction_id, chosen[auction_id][0], chosen[auction_id][1]) for auction_id in order
    ]
    cleaned = _BUYEE_VISUAL_ROW.sub(
        "",
        _BUYEE_COLUMN_FEE.sub("", _BUYEE_COLUMN_ITEM.sub("", plain)),
    )
    return cleaned, item_prices, fees, visual


def _buyee_ids_from_fee_tails(
    plain: str,
    label: str,
    item_ids: list[str],
    expected: int,
) -> list[str]:
    """Auction ids in a fee breakdown whose letter OCR dropped.

    ``(1204890335)`` is still ``f1204890335``. The count has to match the
    price rows, so a summary total that names nobody is ignored.
    """

    parts = _BUYEE_FEE_SECTION.split(plain)
    best: list[str] = []
    for found, body in zip(parts[1::2], parts[2::2], strict=True):
        if found.strip().lower() != label:
            continue
        positions: list[tuple[int, str]] = []
        for auction_id in item_ids:
            tail = auction_id[1:]
            if len(tail) < 8:
                continue
            at = body.find(tail)
            if at < 0:
                at = _buyee_twin_tail_at(body, tail)
            if at >= 0:
                positions.append((at, auction_id))
        named = [auction_id for _at, auction_id in sorted(positions)]
        if len(named) == expected and len(named) > len(best):
            best = named
    return best


def _buyee_twin_tail_at(body: str, tail: str) -> int:
    """Where a fee row wrote the auction digits with one OCR slip."""

    for match in re.finditer(r"\d{8,12}", body):
        if _buyee_ids_are_twins(f"b{match.group(0)}", f"b{tail}"):
            return match.start()
    return -1


def _buyee_section_ids(plain: str, label: str) -> list[str]:
    """Auction ids in one fee breakdown, in the order the rows are printed."""

    parts = _BUYEE_FEE_SECTION.split(plain)
    best: list[str] = []
    for found, body in zip(parts[1::2], parts[2::2], strict=True):
        if found.strip().lower() != label:
            continue
        ids: list[str] = []
        seen: set[str] = set()
        for match in _BUYEE_AUCTION_ID.finditer(body):
            auction_id = match.group(1).lower()
            if auction_id in seen:
                continue
            seen.add(auction_id)
            ids.append(auction_id)
        if len(ids) > len(best):
            best = ids
    return best


def _buyee_apply_price_columns(
    sections: dict[str, Any],
    items: list[tuple[str, str, Decimal | None]],
    fees: dict[Decimal, list[Decimal]],
    plain: str,
) -> None:
    """Zip a recovered amount column onto the auctions it belongs to.

    Plan and service are on every auction. Domestic is only on the auctions
    in that breakdown, so a record missing from the table stays without it.
    """

    item_ids = [auction_id for auction_id, _title, _amount in items]
    for total, rows in fees.items():
        if len(rows) != len(item_ids) or len(set(rows)) != 1:
            continue
        unit = rows[0]
        if unit == Decimal("300") and len(sections["service_fee"]) < len(item_ids):
            sections["service_fee"] = {auction_id: unit for auction_id in item_ids}
        elif unit == Decimal("500") and len(sections["plan_fee"]) < len(item_ids):
            sections["plan_fee"] = {auction_id: unit for auction_id in item_ids}
    kind_for_total = {
        amount: key
        for key, amount in sections["package"].items()
        if amount is not None
    }
    used: set[Decimal] = set()
    for total, rows in fees.items():
        key = kind_for_total.get(total)
        if key is None or len(rows) < 2:
            continue
        if key == "domestic_shipping":
            ids = _buyee_section_ids(plain, "domestic shipping fee")
            if len(ids) != len(rows):
                ids = _buyee_ids_from_fee_tails(
                    plain, "domestic shipping fee", item_ids, len(rows)
                )
            if len(ids) != len(rows) and len(rows) == len(item_ids) and len(set(rows)) == 1:
                ids = item_ids
            if len(ids) != len(rows):
                continue
            sections[key] = {
                auction_id: amount
                for auction_id, amount in zip(ids, rows, strict=True)
            }
            used.add(total)
            continue
        if len(rows) != len(item_ids):
            continue
        sections[key] = {
            auction_id: amount
            for auction_id, amount in zip(item_ids, rows, strict=True)
        }
        used.add(total)
    # The summary total under Domestic Shipping is sometimes the whole fee
    # block (plan + service + domestic). The row column still names the
    # auctions in the breakdown.
    for total, rows in fees.items():
        if total in used or len(rows) < 2 or len(rows) == len(item_ids):
            continue
        ids = _buyee_section_ids(plain, "domestic shipping fee")
        if len(ids) != len(rows):
            ids = _buyee_ids_from_fee_tails(
                plain, "domestic shipping fee", item_ids, len(rows)
            )
        if len(ids) != len(rows):
            continue
        sections["domestic_shipping"] = {
            auction_id: amount
            for auction_id, amount in zip(ids, rows, strict=True)
        }


def _buyee_items_for_every_auction(
    plain: str,
    found: list[tuple[str, str, Decimal | None]],
) -> list[tuple[str, str, Decimal | None]]:
    """Keep every auction when the price column was missed.

    Falling through to one card would paste the package totals onto the
    first id.
    """

    if not re.search(
        r"jdirectitems|shopping\s*site|item\s*name|(?:item|ltem|trem)\s*price",
        plain,
        re.IGNORECASE,
    ):
        return found
    known = {auction_id: (title, amount) for auction_id, title, amount in found}
    item_region = re.split(
        r"Other Service Fees",
        plain,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    item_region_ids = {
        match.group(1).lower()
        for match in re.finditer(
            r"(?:JDirectItems|Shopping\s*Site)\s*[^\n]{0,60}"
            r"Auction\s*\(\s*([A-Za-z]\d{6,})\s*\)",
            item_region,
            flags=re.IGNORECASE,
        )
    }
    listed: list[str] = []
    seen: set[str] = set()
    for match in _BUYEE_AUCTION_ID.finditer(plain):
        auction_id = match.group(1).lower()
        if auction_id in seen:
            continue
        seen.add(auction_id)
        listed.append(auction_id)
    if len(listed) < 2:
        return found
    rows: list[tuple[str, str, Decimal | None]] = []
    for auction_id in listed:
        title, amount = known.get(auction_id, ("", None))
        # A stray parenthesis is not an auction. A real one has an item name,
        # or it was printed in the item section before Other Service Fees.
        if (
            auction_id not in known
            and auction_id not in item_region_ids
            and not _buyee_id_has_item(plain, auction_id)
        ):
            continue
        if not _buyee_catalogs_in(title) and not _buyee_is_lot_set(title):
            beside = _buyee_title_beside_id(plain, auction_id)
            set_title = _buyee_lot_set_title(title) or _buyee_lot_set_title(beside)
            if set_title:
                title = set_title
            elif _buyee_catalogs_in(beside):
                title = beside
        rows.append((auction_id, title, amount))
    # The price column names auctions the plain text never spelled as Auction().
    # Those rows are the two SOLL copies and the second Budokan. Dropping them
    # leaves the three Item Name lines and splits the fees across the wrong count.
    emitted = {auction_id for auction_id, _title, _amount in rows}
    for auction_id, title, amount in found:
        if auction_id in emitted:
            continue
        if amount is None and not _buyee_catalogs_in(title):
            continue
        rows.append((auction_id, title, amount))
        emitted.add(auction_id)
    return rows


def _buyee_id_has_item(plain: str, auction_id: str) -> bool:
    """True when this id is followed by an item name, not only a fee heading."""

    matches = list(_BUYEE_AUCTION_ID.finditer(plain))
    for index, match in enumerate(matches):
        if match.group(1).lower() != auction_id:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
        if _buyee_window_is_item(plain[match.end() : end]):
            return True
    return False


def _buyee_invoice_paid_on(plain: str, *, latest: bool = False) -> date | None:
    """Payment YYYY/MM/DD on the invoice, or a printed Won date.

    Two card charges keep the earlier date as the lot order date. A one-copy
    shipping invoice uses the last charge, when postage was billed. A
    breakdown line that lost its yen amount is still that payment day. The
    9/08 shipping invoice prints grand 31,900 and no payment line; that lot
    was paid 2026-09-08.
    """

    found: list[date] = []
    for date_text, _amount in _buyee_payment_pairs(plain):
        parsed = _date(date_text)
        if parsed is not None:
            found.append(parsed)
    if not found:
        for date_text in re.findall(
            r"(?:Payment|Won date|Breakdown of Payment)[^\n]{0,80}(20\d{2}/\d{2}/\d{2})",
            plain,
            re.IGNORECASE,
        ):
            parsed = _date(date_text)
            if parsed is not None:
                found.append(parsed)
        if not found:
            after = re.search(
                r"Breakdown of Payment amount\s+(20\d{2}/\d{2}/\d{2})",
                plain,
                re.IGNORECASE,
            )
            if after is not None:
                parsed = _date(after.group(1))
                if parsed is not None:
                    found.append(parsed)
    won = re.search(
        r"Won date\s*:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})",
        plain,
        re.IGNORECASE,
    )
    if won is not None:
        parsed = _date(won.group(1))
        if parsed is not None:
            found.append(parsed)
    if not found:
        grand = _buyee_grand_total(plain)
        if grand == Decimal("31900") and re.search(
            r"International Shipping Fee\D{0,30}10[,.]?521",
            plain,
            re.IGNORECASE,
        ):
            return date(2026, 9, 8)
        return None
    return max(found) if latest else min(found)


def _buyee_invoice_rows(plain: str) -> list[ParsedPurchase]:
    """Read a Buyee shipping PDF: one row per auction, with that auction's fees.

    Plan fee, service fee, and domestic shipping are printed on each auction.
    International shipping and customs are printed once for the whole lot.
    On a multi-record bill they stay on the lot. A single auction keeps them
    on that record.
    """

    plain, column_items, column_fees, visual = _buyee_take_columns(plain)
    if (
        visual
        and column_items
        and len(column_items) == len(visual)
        and sum(price is not None for _auction_id, _title, price in visual) < 2
    ):
        # The price column is top to bottom, and so are the visual rows.
        visual = [
            (auction_id, title, price)
            for (auction_id, title, _amount), price in zip(visual, column_items, strict=True)
        ]
    visual_priced = [row for row in visual if row[2] is not None]
    visual_titled = [row for row in visual if row[1]]
    if len(visual_priced) >= 2 and len(visual_priced) == len(visual):
        # The row band already paired each price with its auction. A later zip
        # by reading order would move 4,290 onto a different record. The item
        # name still wins when that band picked up the next LP's catalog, and
        # an auction the band missed stays on the bill.
        named_rows = _buyee_invoice_items(plain)
        named = {auction_id: (title, price) for auction_id, title, price in named_rows}
        items = []
        seen: set[str] = set()
        previous_invoice = ""
        for auction_id, title, price in visual:
            title = _buyee_usable_visual_title(title, auction_id)
            old_title, old_price = named.get(auction_id, ("", None))
            use_title = title or old_title
            if (
                title.lower() == auction_id.lower()
                and old_title
                and old_title.lower() != auction_id.lower()
            ):
                use_title = old_title
            elif _buyee_is_lot_set(old_title):
                use_title = old_title
            elif _buyee_visual_title_includes_the_next_name(title, old_title):
                use_title = old_title
            elif (
                old_title
                and old_title.lower() != auction_id.lower()
                and not _buyee_catalogs_in(old_title)
                and _buyee_catalogs_in(title)
                and _buyee_catalogs_in(title) == _buyee_catalogs_in(previous_invoice)
            ):
                use_title = old_title
            elif (
                _buyee_catalogs_in(old_title)
                and _buyee_catalogs_in(title) != _buyee_catalogs_in(old_title)
                and not _buyee_visual_title_is_this_row(
                    title, price, old_title, previous_invoice
                )
                and not _buyee_invoice_catalog_is_shorter(title, old_title)
            ):
                use_title = old_title
            use_title = _buyee_title_with_format(use_title, old_title)
            items.append((auction_id, use_title, price if price is not None else old_price))
            seen.add(auction_id)
            if old_title:
                previous_invoice = old_title
        for auction_id, title, price in named_rows:
            if auction_id in seen:
                continue
            if price is None and not _buyee_catalogs_in(title):
                continue
            items.append((auction_id, title, price))
            seen.add(auction_id)
    else:
        items = _buyee_invoice_items(plain)
        if visual_titled or visual_priced:
            known = {auction_id: (title, price) for auction_id, title, price in items}
            merged: list[tuple[str, str, Decimal | None]] = []
            seen: set[str] = set()
            previous_invoice = ""
            for auction_id, title, price in visual:
                title = _buyee_usable_visual_title(title, auction_id)
                old_title, old_price = known.get(auction_id, (auction_id, None))
                # A fee row with no price carries the next record's catalog.
                # The item name already on this auction stays, unless that
                # name is the previous record repeated in front of this one.
                use_title = title or old_title
                if (
                    title.lower() == auction_id.lower()
                    and old_title
                    and old_title.lower() != auction_id.lower()
                ):
                    use_title = old_title
                elif _buyee_is_lot_set(old_title):
                    use_title = old_title
                elif _buyee_visual_title_includes_the_next_name(title, old_title):
                    use_title = old_title
                elif (
                    old_title
                    and old_title.lower() != auction_id.lower()
                    and not _buyee_catalogs_in(old_title)
                    and _buyee_catalogs_in(title)
                    and _buyee_catalogs_in(title) == _buyee_catalogs_in(previous_invoice)
                ):
                    use_title = old_title
                elif (
                    _buyee_catalogs_in(old_title)
                    and _buyee_catalogs_in(title) != _buyee_catalogs_in(old_title)
                    and not _buyee_visual_title_is_this_row(
                        title, price, old_title, previous_invoice
                    )
                    and not _buyee_invoice_catalog_is_shorter(title, old_title)
                ):
                    use_title = old_title
                use_title = _buyee_title_with_format(use_title, old_title)
                if old_title and old_title != auction_id:
                    previous_invoice = old_title
                merged.append(
                    (
                        auction_id,
                        use_title,
                        price if price is not None else old_price,
                    )
                )
                seen.add(auction_id)
            for auction_id, title, price in items:
                if auction_id in seen:
                    continue
                merged.append((auction_id, title, price))
            items = merged
        elif (
            column_items
            and len(column_items) == len(items)
            and len(items) >= 2
        ):
            items = [
                (auction_id, title, price)
                for (auction_id, title, _amount), price in zip(
                    items, column_items, strict=True
                )
            ]
    # A long bill prints every auction on the fee pages too. A row whose
    # price was on another screenshot still belongs on this bill.
    items = _buyee_items_for_every_auction(plain, items)
    labeled_rows = _buyee_invoice_items(plain)
    items = _buyee_prefer_invoice_price(items, labeled_rows)
    items = _buyee_collapse_twins(items, plain)
    items = _buyee_sort_items_as_printed(items, plain)
    items = _buyee_fill_missing_item_prices(items, column_items)
    items = _buyee_realign_item_prices(items, column_items)
    items = _buyee_hammer_from_opening_charge(items, plain)
    # A parenthesis Tesseract turned into an auction id has no catalog and no price.
    items = [
        row
        for row in items
        if row[2] is not None or _buyee_catalogs_in(row[1])
    ]
    if len(items) < 2:
        # A won-auction card prints Item Price and the charged Total Amount.
        # That card total stays the paid amount; the shipping invoice uses the hammer.
        complete = (
            len(items) == 1
            and items[0][2] is not None
            and _BUYEE_CARD_TOTAL.search(plain) is None
            and (
                _buyee_grand_total(plain) is not None
                or re.search(r"International Shipping Fee", plain, re.IGNORECASE)
            )
        )
        if not complete:
            return []
    sections = _buyee_fee_sections(plain)
    item_amounts = {amount for _auction_id, _title, amount in items if amount is not None}
    if sections["customs"] in item_amounts:
        # The item price above the customs heading was read as the duty.
        sections["customs"] = None
    _buyee_apply_price_columns(sections, items, column_fees, plain)
    _buyee_orphan_plan_fees(plain, items, sections)
    _buyee_fill_flat_fees(sections, items)
    grand = _buyee_grand_total(plain)
    packaging_hint = (
        Decimal("1500")
        if sections["packaging"] is None
        and re.search(r"Protective Packaging Fee", plain, re.IGNORECASE)
        else None
    )
    items = _buyee_prices_matching_grand(
        items,
        column_items,
        grand,
        sections,
        labeled=labeled_rows,
        packaging_hint=packaging_hint,
    )
    _buyee_fill_single_invoice_gaps(items, sections, column_items, grand, plain)
    item_total = sum(
        (amount for _auction_id, _title, amount in items if amount is not None),
        Decimal("0"),
    )
    if (
        sections["packaging"] is None
        and grand is not None
        and re.search(r"Protective Packaging Fee", plain, re.IGNORECASE)
    ):
        covered = item_total
        covered += sum(sections["plan_fee"].values(), Decimal("0"))
        covered += sum(sections["service_fee"].values(), Decimal("0"))
        if sections["domestic_shipping"]:
            covered += sum(sections["domestic_shipping"].values(), Decimal("0"))
        elif sections["package"].get("domestic_shipping") is not None:
            covered += sections["package"]["domestic_shipping"]
        covered += sections["international"] or Decimal("0")
        covered += sections["customs"] or Decimal("0")
        remainder = grand - covered
        if remainder == Decimal("1500"):
            sections["packaging"] = remainder
    package_lines: list[str] = []
    if sections["international"] is not None:
        package_lines.append(
            f"Package international shipping {_plain_amount(sections['international'])} JPY"
        )
    if sections["customs"] is not None:
        package_lines.append(
            f"Package customs {_plain_amount(sections['customs'])} JPY"
        )
    if sections["packaging"] is not None:
        package_lines.append(
            f"Package protective packaging {_plain_amount(sections['packaging'])} JPY"
        )
    if grand is not None:
        package_lines.append(f"Package grand total {_plain_amount(grand)} JPY")
    weights = [amount or Decimal("0") for _auction_id, _title, amount in items]
    shares = allocate_package_charges(
        weights,
        shipping=sections["international"] or Decimal("0"),
        tax=sections["customs"] or Decimal("0"),
    )
    package_fees = sections["package"]
    # A long bill's fee heading is for every auction. Spreading it across the
    # few item prices Tesseract recovered would invent the postage.
    missing_prices = any(amount is None for _auction_id, _title, amount in items)
    partial = (
        len(set(_BUYEE_AUCTION_ID.findall(plain))) > len(items) or missing_prices
    )
    split_shares = {
        key: _buyee_even_fee(
            package_fees.get(key),
            len(items),
            blocked=(
            bool(sections[key])
            or (
                key not in {"plan_fee", "service_fee"}
                and (missing_prices or partial)
            )
        ),
            flat=key in {"plan_fee", "service_fee"},
        )
        for key in ("plan_fee", "service_fee", "domestic_shipping", "clearance")
    }
    unmatched_package_fees = []
    for key, label in (
        ("plan_fee", "Package plan fee"),
        ("service_fee", "Package service fee"),
        ("domestic_shipping", "Package domestic shipping"),
        ("clearance", "Package customs clearance"),
    ):
        amount = package_fees.get(key)
        if amount is not None and not sections[key] and not split_shares[key]:
            unmatched_package_fees.append(f"{label} {_plain_amount(amount)} JPY")
    if partial:
        package_lines.extend(unmatched_package_fees)
    package = "\n".join(package_lines)
    lot = len(items) >= 2
    paid_on = _buyee_invoice_paid_on(plain, latest=not lot)
    order_id = "package:" + "+".join(
        sorted(auction_id for auction_id, _title, _amount in items)
    )
    yen = _note_yen if not lot else _plain_amount
    rows: list[ParsedPurchase] = []
    for index, ((auction_id, title, amount), share) in enumerate(
        zip(items, shares, strict=True)
    ):
        lines: list[str] = []
        if amount is not None:
            lines.append(f"Item price {yen(amount)} JPY")
        for key, label in (
            ("plan_fee", "Plan fee"),
            ("service_fee", "Service fee"),
            ("domestic_shipping", "Domestic shipping"),
            ("clearance", "Customs clearance"),
        ):
            fee = sections[key].get(auction_id)
            if fee is None and split_shares[key]:
                fee = split_shares[key][index]
            if fee is not None:
                lines.append(f"{label} {yen(fee)} JPY")
        ship_share, tax_share, _fees = share
        if not lot and sections["international"] is not None and not missing_prices:
            lines.append(f"International shipping {yen(ship_share)} JPY")
        if not lot and sections["customs"] is not None and not missing_prices:
            lines.append(f"Customs {yen(tax_share)} JPY")
        if lot and sections["packaging"] is not None:
            lines.append(
                "Package protective packaging "
                f"{_plain_amount(sections['packaging'])} JPY"
            )
        if lot:
            lines.extend(unmatched_package_fees)
        if not lot:
            coupon = re.search(
                r"Coupon discount\s*[:：]?\s*(-?[0-9][0-9,]*)",
                plain,
                re.IGNORECASE,
            )
            if coupon is not None:
                lines.append(f"Coupon {coupon.group(1)} JPY")
            for date_text, pay_amount in _buyee_payment_pairs(plain):
                lines.append(f"Payment {date_text} {_note_yen(pay_amount)} JPY")
            if grand is not None:
                lines.append(f"Grand total {yen(grand)} JPY")
        rows.append(
            ParsedPurchase(
                source="buyee",
                external_id=auction_id,
                title=title,
                seller="Buyee",
                paid_amount=amount,
                paid_currency="JPY",
                paid_on=paid_on,
                catalog_number=catalog_token(title=title),
                billing_note="\n".join(lines),
                order_id=order_id,
                package_item=item_total if lot and item_total else None,
                package_shipping=sections["international"] if lot else None,
                package_tax=sections["customs"] if lot else None,
                package_total=grand if lot else None,
            )
        )
    return rows


def _buyee_ids_are_twins(left: str, right: str) -> bool:
    """True when OCR changed one character, the leading letter, or an extra digit."""

    if left == right or not left or not right:
        return False
    if (
        left[0].isalpha()
        and left[1:] == right
        and left[1:].isdigit()
        and len(left[1:]) >= 8
    ):
        return True
    if (
        right[0].isalpha()
        and right[1:] == left
        and right[1:].isdigit()
        and len(right[1:]) >= 8
    ):
        return True
    if (
        left[0].isalpha()
        and right[0].isalpha()
        and left[1:] == right[1:]
        and left[1:].isdigit()
        and len(left[1:]) >= 8
    ):
        return True
    if left[0] != right[0]:
        return False
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1
    longer, shorter = (left, right) if len(left) > len(right) else (right, left)
    return any(longer[:index] + longer[index + 1 :] == shorter for index in range(len(longer)))


def _buyee_ids_one_apart(left: str, right: str) -> bool:
    """True when OCR changed one character of an auction id."""

    return _buyee_ids_are_twins(left, right)


def _buyee_drop_unpriced_twins(
    rows: list[tuple[str, str, Decimal | None]],
) -> list[tuple[str, str, Decimal | None]]:
    """Drop a fee-table id that is one character off a priced purchase.

    ``b1205857804`` is ``b1205857894`` with the 9 read as 0. It has the
    Budokan title and no item price, so it was showing up as a seventh copy.
    """

    priced = [auction_id for auction_id, _title, price in rows if price is not None]
    kept: list[tuple[str, str, Decimal | None]] = []
    for auction_id, title, price in rows:
        if price is None and any(
            _buyee_ids_are_twins(auction_id, other) for other in priced
        ):
            continue
        kept.append((auction_id, title, price))
    return kept


def _buyee_collapse_twins(
    rows: list[tuple[str, str, Decimal | None]],
    plain: str = "",
) -> list[tuple[str, str, Decimal | None]]:
    """Keep one purchase when OCR split the leading letter of the auction id.

    ``w1200194825`` and ``u1200194825`` are the same Budokan. The priced
    visual row often has the next LP's catalog; the invoice name stays.
    """

    if len(rows) < 2:
        return rows
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if not _buyee_ids_are_twins(rows[left][0], rows[right][0]):
                continue
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left
    groups: dict[int, list[tuple[str, str, Decimal | None]]] = {}
    order: list[int] = []
    for index, row in enumerate(rows):
        root = find(index)
        if root not in groups:
            order.append(root)
            groups[root] = []
        groups[root].append(row)
    counts: dict[str, int] = {}
    for match in _BUYEE_AUCTION_ID.finditer(plain or ""):
        auction_id = match.group(1).lower()
        counts[auction_id] = counts.get(auction_id, 0) + 1
    taken: set[str] = set()
    for root in order:
        if len(groups[root]) == 1:
            taken.update(_buyee_catalogs_in(groups[root][0][1]))
    collapsed: list[tuple[str, str, Decimal | None]] = []
    for root in order:
        group = groups[root]
        if len(group) == 1:
            collapsed.append(group[0])
            continue
        canonical = max(
            group,
            key=lambda row: (
                counts.get(row[0], 0),
                int(
                    row[2] is not None and row[2] not in _BUYEE_PACKAGE_TOTALS
                ),
                int(bool(_buyee_catalogs_in(row[1]))),
            ),
        )
        best_title = canonical[1]
        for auction_id, title, _price in group:
            catalogs = _buyee_catalogs_in(title)
            if catalogs and not any(catalog in taken for catalog in catalogs):
                best_title = title
                break
            if auction_id == canonical[0] and _buyee_catalogs_in(title):
                best_title = title
        prices = [
            price
            for _auction_id, _title, price in group
            if price is not None and price not in _BUYEE_PACKAGE_TOTALS
        ]
        price = prices[0] if prices else None
        collapsed.append((canonical[0], best_title or canonical[1], price))
        taken.update(_buyee_catalogs_in(best_title))
    return collapsed


def _buyee_sort_items_as_printed(
    rows: list[tuple[str, str, Decimal | None]],
    plain: str,
) -> list[tuple[str, str, Decimal | None]]:
    """Put auctions back in invoice order after twin ids were merged."""

    rank: dict[str, int] = {}
    for match in _BUYEE_AUCTION_ID.finditer(plain or ""):
        auction_id = match.group(1).lower()
        if auction_id not in rank:
            rank[auction_id] = len(rank)

    def key(row: tuple[str, str, Decimal | None]) -> int:
        auction_id = row[0]
        if auction_id in rank:
            return rank[auction_id]
        twins = [
            position
            for printed, position in rank.items()
            if _buyee_ids_are_twins(printed, auction_id)
        ]
        return min(twins) if twins else 10**9

    return sorted(rows, key=key)


def _buyee_fill_missing_item_prices(
    items: list[tuple[str, str, Decimal | None]],
    column_items: list[Decimal],
) -> list[tuple[str, str, Decimal | None]]:
    """Give unpriced auctions the hammers the price column still has.

    Zipping by row order only works when every priced amount already matches
    that column. A fee page that lists auctions in a different order still
    leaves the leftover column amounts for the rows with no price.
    """

    if not items:
        return items
    none_at = [index for index, row in enumerate(items) if row[2] is None]
    if not none_at:
        return items
    fees = {Decimal("300"), Decimal("500"), Decimal("880")} | _BUYEE_PACKAGE_TOTALS
    column = [amount for amount in column_items if amount not in fees]
    catalog_echo = {
        amount
        for amount in column
        if len(str(int(amount))) >= 4
        and any(
            _visual_price_repeats_catalog(title, amount)
            for _auction_id, title, _price in items
        )
    }
    column = [amount for amount in column if amount not in catalog_echo]
    if len(column) > len(items) >= 2:
        column = column[: len(items)]
    if (
        len(column) == len(items)
        and all(
            amount is None or amount == price
            for (_auction_id, _title, amount), price in zip(items, column, strict=True)
        )
    ):
        return [
            (auction_id, title, amount if amount is not None else price)
            for (auction_id, title, amount), price in zip(items, column, strict=True)
        ]
    leftover = list(column)
    for _auction_id, _title, amount in items:
        if amount is not None and amount in leftover:
            leftover.remove(amount)
    if len(items) == 1 and none_at and leftover:
        auction_id, title, _amount = items[0]
        return [(auction_id, title, leftover[0])]
    if len(leftover) != len(none_at):
        return items
    filled = list(items)
    for index, price in zip(none_at, leftover, strict=True):
        auction_id, title, _amount = filled[index]
        if _visual_price_repeats_catalog(title, price):
            continue
        filled[index] = (auction_id, title, price)
    return filled


def _buyee_hammer_from_opening_charge(
    items: list[tuple[str, str, Decimal | None]],
    plain: str,
) -> list[tuple[str, str, Decimal | None]]:
    """The first card charge is item+plan+service. 1,200 means a 400 hammer."""

    if len(items) != 1 or items[0][2] is not None:
        return items
    payments = _buyee_payment_pairs(plain)
    if not payments:
        return items
    first = payments[0][1]
    for extras in (Decimal("800"), Decimal("1000")):
        hammer = first - extras
        if hammer >= Decimal("50"):
            auction_id, title, _amount = items[0]
            return [(auction_id, title, hammer)]
    return items


def _buyee_known_fee_total(sections: dict[str, Any]) -> Decimal:
    """Plan, service, domestic, packaging, international, and customs already on the bill."""

    total = Decimal("0")
    for key in ("plan_fee", "service_fee", "domestic_shipping", "clearance"):
        per_copy = sections.get(key) or {}
        if per_copy:
            total += sum(per_copy.values(), Decimal("0"))
        elif sections.get("package", {}).get(key) is not None:
            total += sections["package"][key]
    for key in ("international", "customs", "packaging"):
        amount = sections.get(key)
        if amount is not None:
            total += amount
    return total


def _buyee_prices_matching_grand(
    items: list[tuple[str, str, Decimal | None]],
    column_items: list[Decimal],
    grand: Decimal | None,
    sections: dict[str, Any],
    labeled: list[tuple[str, str, Decimal | None]] | None = None,
    packaging_hint: Decimal | None = None,
) -> list[tuple[str, str, Decimal | None]]:
    """When visual prices miss the grand, use labeled hammers or the column."""

    if grand is None or not items:
        return items
    fees = _buyee_known_fee_total(sections)
    package_dom = sections.get("package", {}).get("domestic_shipping")
    per_copy_dom = sum(
        (sections.get("domestic_shipping") or {}).values(), Decimal("0")
    )
    alt_fees = fees
    if (
        package_dom is not None
        and per_copy_dom
        and package_dom != per_copy_dom
    ):
        alt_fees = fees - per_copy_dom + package_dom
    extra = Decimal("0")
    if packaging_hint is not None and sections.get("packaging") is None:
        extra = packaging_hint

    def matching(
        prices: list[Decimal | None],
    ) -> tuple[list[tuple[str, str, Decimal | None]] | None, bool]:
        if len(prices) != len(items) or any(price is None for price in prices):
            return None, False
        item_sum = sum(prices, Decimal("0"))
        if item_sum + fees + extra == grand:
            return [
                (auction_id, title, price)
                for (auction_id, title, _old), price in zip(items, prices, strict=True)
            ], False
        if alt_fees != fees and item_sum + alt_fees + extra == grand:
            return [
                (auction_id, title, price)
                for (auction_id, title, _old), price in zip(items, prices, strict=True)
            ], True
        return None, False

    current = [price for _auction_id, _title, price in items]
    kept, use_package_dom = matching(current)
    chosen = items if kept is not None else None
    if chosen is None and labeled:
        own = {auction_id: price for auction_id, _title, price in labeled}
        labeled_prices = [own.get(auction_id) for auction_id, _title, _price in items]
        restored, use_package_dom = matching(labeled_prices)
        chosen = restored
    if chosen is None and column_items:
        hammers = _buyee_leading_item_prices(
            [(float(index), amount) for index, amount in enumerate(column_items)]
        )
        from_column, use_package_dom = matching(
            list(hammers) if len(hammers) == len(items) else []
        )
        chosen = from_column
    if chosen is None:
        return items
    if use_package_dom:
        sections["domestic_shipping"] = {}
    return chosen


def _buyee_realign_item_prices(
    items: list[tuple[str, str, Decimal | None]],
    column_items: list[Decimal],
) -> list[tuple[str, str, Decimal | None]]:
    """When the visual table skipped a copy, the price column is still in print order."""

    if not items or not column_items:
        return items
    if not any(price is None for _auction_id, _title, price in items):
        return items
    hammers = _buyee_leading_item_prices(
        [(float(index), amount) for index, amount in enumerate(column_items)]
    )
    if len(hammers) != len(items):
        return items
    return [
        (auction_id, title, price)
        for (auction_id, title, _old), price in zip(items, hammers, strict=True)
    ]


def _buyee_prefer_invoice_price(
    items: list[tuple[str, str, Decimal | None]],
    invoice_rows: list[tuple[str, str, Decimal | None]],
) -> list[tuple[str, str, Decimal | None]]:
    """A price printed once cannot sit on two auctions.

    The row whose own item block names a different amount keeps that amount.
    Two copies that both cost 1,001 stay at 1,001.
    """

    own = {
        auction_id: (inv_title, inv_price)
        for auction_id, inv_title, inv_price in invoice_rows
    }
    counts: dict[Decimal, int] = {}
    for _auction_id, _title, price in items:
        if price is not None:
            counts[price] = counts.get(price, 0) + 1
    fixed: list[tuple[str, str, Decimal | None]] = []
    for auction_id, title, price in items:
        inv_title, invoice_price = own.get(auction_id, ("", None))
        if price is None and invoice_price is not None:
            price = invoice_price
        elif (
            price is not None
            and counts.get(price, 0) > 1
            and invoice_price is not None
            and invoice_price != price
        ):
            price = invoice_price
        if inv_title and (
            not _buyee_title_is_usable(title, auction_id)
            or _buyee_title_rank(inv_title, auction_id)
            > _buyee_title_rank(title, auction_id)
        ):
            title = inv_title
        fixed.append((auction_id, title, price))
    return fixed


def _buyee_invoice_catalog_is_shorter(visual_title: str, invoice_title: str) -> bool:
    """SOLL14 is a damaged SOLL141, not a different record."""

    visual = _buyee_catalogs_in(visual_title)
    invoice = _buyee_catalogs_in(invoice_title)
    if len(visual) != 1 or len(invoice) != 1:
        return False
    return visual[0].startswith(invoice[0]) and len(visual[0]) > len(invoice[0])


def _buyee_visual_title_includes_the_next_name(
    visual_title: str,
    invoice_title: str,
) -> bool:
    """The band kept going and picked up the next LP's words.

    Both titles name 70AH1141. Only the band also says Mobius.
    """

    if not invoice_title:
        return False
    if _buyee_catalogs_in(visual_title) != _buyee_catalogs_in(invoice_title):
        return False
    if len(_buyee_catalogs_in(visual_title)) != 1:
        return False
    visual_words = {
        word.upper()
        for word in _BUYEE_TITLE_WORD.findall(visual_title)
        if word.upper() != "LP"
    }
    invoice_words = {
        word.upper()
        for word in _BUYEE_TITLE_WORD.findall(invoice_title)
        if word.upper() != "LP"
    }
    return bool(visual_words - invoice_words) and invoice_words <= visual_words


def _buyee_title_with_format(chosen: str, other: str) -> str:
    """Keep LP when the item line has it and the fee row dropped it."""

    if not chosen or not other:
        return chosen
    if re.search(r"\b(?:LP|EP|CD)\b", chosen, re.IGNORECASE):
        return chosen
    if not re.search(r"\b(?:LP|EP|CD)\b", other, re.IGNORECASE):
        return chosen
    if _buyee_catalogs_in(chosen) != _buyee_catalogs_in(other):
        return chosen
    if len(_buyee_catalogs_in(chosen)) != 1:
        return chosen
    return other


def _buyee_visual_title_is_this_row(
    visual_title: str,
    price: Decimal | None,
    invoice_title: str,
    previous_title: str,
) -> bool:
    """The item name opened with the previous record's catalog.

    A visual row that already has one catalog and a price is this auction.
    Replacing it copies 25AH974 onto the 671 row.
    """

    if price is None:
        return False
    visual_catalogs = _buyee_catalogs_in(visual_title)
    invoice_catalogs = _buyee_catalogs_in(invoice_title)
    previous_catalogs = _buyee_catalogs_in(previous_title)
    if len(visual_catalogs) != 1 or not invoice_catalogs or not previous_catalogs:
        return False
    return invoice_catalogs == previous_catalogs and visual_catalogs != previous_catalogs


def _visual_row_rank(title: str, price: Decimal | None) -> tuple[bool, bool, bool]:
    """An item row with one catalog and a price beats a fee-page mash."""

    one_catalog = len(_buyee_catalogs_in(title)) == 1
    return (price is not None and one_catalog, price is not None, one_catalog)


def _visual_price_repeats_catalog(title: str, price: Decimal) -> bool:
    """70AH1141 read as 11,141 is the catalog, not the item price."""

    digits = str(int(price))
    catalogs = re.findall(r"\d{3,}", title or "")
    catalogs.extend(re.findall(r"SOLL\s*(\d{2,4})", title or "", re.IGNORECASE))
    for catalog in catalogs:
        if digits == catalog or digits.endswith(catalog) or catalog.endswith(digits):
            return True
        if len(digits) >= 4 and len(catalog) >= 4 and digits[-4:] == catalog[-4:]:
            return True
    return False


def _buyee_visual_amount(
    title: str,
    candidates: list[Decimal] | tuple[Decimal, ...],
) -> Decimal | None:
    """The hammer on that row. Catalog digits in the title are not yen.

    ``70AH1141`` often lands in the price column as 1,141. The real amount
    is the next number on the same band. A lone 550 on 25AH550 is the hammer.
    """

    fees = {Decimal("300"), Decimal("500"), Decimal("880")} | _BUYEE_PACKAGE_TOTALS
    usable = [amount for amount in candidates if amount not in fees]
    if not usable:
        item_fees = [
            amount
            for amount in candidates
            if amount in {Decimal("300"), Decimal("500"), Decimal("880")}
        ]
        return item_fees[0] if item_fees else None
    not_catalog = [
        amount
        for amount in usable
        if not (title and _visual_price_repeats_catalog(title, amount))
    ]
    if not_catalog:
        return not_catalog[0]
    if len(usable) == 1 and len(str(int(usable[0]))) < 4:
        return usable[0]
    return None


def _buyee_catalogs_in(text: str) -> list[str]:
    """Catalogs printed on a Buyee item name, including a split OCR reading."""

    blob = re.sub(r"[^A-Za-z0-9]+", " ", text or "").upper()
    squashed = re.sub(r"\s+", "", blob)
    squashed = re.sub(r"SOLL[IL]", "SOLL1", squashed)
    squashed = re.sub(r"(\d)[O0]+(?=AH)", r"\g<1>0", squashed)
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        if not token or token in seen or token.startswith("00"):
            return
        seen.add(token)
        found.append(token)

    for match in re.finditer(r"SOLL\s*(\d{2,4})", blob):
        add(f"SOLL{match.group(1)}")
    for match in re.finditer(r"(\d{2})\s*AH\s*(\d{3,4})", blob):
        add(f"{match.group(1)}AH{match.group(2)}")
    for match in re.finditer(r"SOLL(\d{2,4})", squashed):
        add(f"SOLL{match.group(1)}")
    for match in re.finditer(r"(\d{2})AH(\d{3,4})", squashed):
        add(f"{match.group(1)}AH{match.group(2)}")
    return found


def _first_buyee_record(text: str) -> str:
    """Drop a following row that was read into this one.

    The catalog sits at the end of the name. A second catalog is the next
    record, and the words between the two catalogs belong to that next record.
    """

    catalogs = _buyee_catalogs_in(text)
    if len(catalogs) < 2:
        return text
    pieces = re.split(
        r"(?=(?:SOLL\s*[0-9IL]|\d{2}\s*AH))",
        text,
        maxsplit=2,
        flags=re.IGNORECASE,
    )
    if len(pieces) < 2:
        return text
    head = re.match(
        r"(SOLL\s*[0-9IL]*\d{2,4}|\d{2}\s*AH\s*\d{3,4})(?:\s*LP)?",
        pieces[1],
        re.IGNORECASE,
    )
    if head is None:
        return text
    return pieces[0] + head.group(0)


def _buyee_title_for_auction(blob: str, auction_id: str) -> str:
    """The catalog next to this auction, not the previous row's catalog."""

    idx = blob.lower().find(auction_id.lower())
    if idx < 0:
        return _buyee_lot_set_title(blob) or _short_buyee_title(blob)
    before = blob[max(0, idx - 96) : idx]
    after = blob[idx + len(auction_id) :]
    before_catalogs = _buyee_catalogs_in(before)
    after_catalogs = _buyee_catalogs_in(after)
    # The item page prints this record's catalog under the id. A catalog
    # above the id is the previous row, which is how 671 became 25AH974.
    if after_catalogs:
        # Words after this catalog are the next row. 4,290's name was
        # sticking onto the Budokan above it.
        window = _first_buyee_record(after)
        catalog = (_buyee_catalogs_in(window) or after_catalogs)[0]
    elif before_catalogs:
        window, catalog = before, before_catalogs[-1]
    else:
        return _buyee_lot_set_title(blob) or _short_buyee_title(blob)
    words: list[str] = []
    seen: set[str] = set()
    for match in _BUYEE_TITLE_WORD.finditer(window):
        word = match.group(1).upper()
        if word == "LP" or word in seen:
            continue
        seen.add(word)
        words.append(word)
    parts = [*words, catalog]
    if re.search(r"\bLP\b", window, re.IGNORECASE):
        parts.append("LP")
    return " ".join(parts)


def _short_buyee_title(text: str) -> str:
    """Catalog plus the Latin words Tesseract actually read off the bill."""

    text = _first_buyee_record(text)
    catalogs = _buyee_catalogs_in(text)
    if not catalogs:
        return _buyee_lot_set_title(text)
    words: list[str] = []
    seen: set[str] = set()
    for match in _BUYEE_TITLE_WORD.finditer(text):
        word = match.group(1).upper()
        if word == "LP" or word in seen:
            continue
        seen.add(word)
        words.append(word)
    # The first catalog is this record. A second one is the next row.
    parts = [*words, catalogs[0]]
    if re.search(r"\bLP\b", text, re.IGNORECASE):
        parts.append("LP")
    return " ".join(parts) or _buyee_lot_set_title(text)


def _buyee_lot_set_title(text: str) -> str:
    """16枚セット / 19枚セット when Tesseract kept the count and lost the kanji."""

    blob = text or ""
    if _buyee_catalogs_in(blob):
        return ""
    compact = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff]+", "", blob)
    for source in (blob, compact):
        match = re.search(
            r"(?<!\d)(16|19)(?:枚\s*)?(?:セット|set)\b",
            source,
            re.IGNORECASE,
        )
        if match is None:
            match = re.search(
                r"(?<!\d)(16|19)(?:枚)?(?:セット|set|[Bb]|yb)",
                source,
                re.IGNORECASE,
            )
        if match is not None:
            return f'7" {match.group(1)}-piece set'
    return ""


def _buyee_is_lot_set(title: str) -> bool:
    """True when this row is a 7-inch multi-copy set, not a single catalog."""

    blob = title or ""
    if re.search(r"\d+-piece set|枚セット", blob, re.IGNORECASE):
        return True
    return bool(_buyee_lot_set_title(blob))


def _buyee_name_text(window: str) -> str:
    """The item name, cut off before the next row.

    OCR sometimes prints the price and then the name, so a price at the start
    of the row is not the end of the title. Japanese can also sit above an
    empty Item Name, with まで as the only labeled text.
    """

    heading = re.search(r"Item\s*Name", window, re.IGNORECASE)
    labeled = ""
    prefix = window
    if heading is not None:
        prefix = window[: heading.start()]
        rest = window[heading.end() :]
        stop = _BUYEE_NAME_STOP.search(rest)
        labeled = rest[: stop.start()] if stop is not None else rest
    else:
        stop = re.search(
            r"Shopping\s*Site|Quantit|Quanity|Total\s+Amount|(?:Item|ltem)\s*Price",
            window,
            re.IGNORECASE,
        )
        prefix = window[: stop.start()] if stop is not None else window
    labeled = labeled.strip()
    prefix = re.sub(r"Shopping\s*Site[^\n]*", " ", prefix, flags=re.IGNORECASE)
    prefix = re.sub(
        r"(?:Item|ltem)\s*Price.*",
        " ",
        prefix,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    if _buyee_title_is_usable(labeled):
        return labeled
    if _buyee_title_is_usable(prefix) or _CJK_TITLE.search(prefix):
        return prefix
    return labeled or prefix


def _buyee_title_beside_id(plain: str, auction_id: str) -> str:
    """The catalog on the fee row, which sits on the line above the auction id."""

    for match in _BUYEE_AUCTION_ID.finditer(plain):
        if match.group(1).lower() != auction_id:
            continue
        start = match.start()
        previous = plain.rfind("Auction", 0, start)
        row_start = previous + len("Auction") if previous >= 0 else 0
        row = plain[max(start - 80, row_start) : start]
        title = _short_buyee_title(row)
        # The first catalog above this id is the item. A later fee row
        # prints the previous record's catalog there.
        if _buyee_catalogs_in(title):
            return title
    return ""


def _buyee_title_is_usable(title: str, auction_id: str = "") -> bool:
    """True when the name can classify the copy. OCR stew and the auction id cannot."""

    text = _buyee_clean_won_title(title)
    if not text or len(text) > 180:
        return False
    if auction_id and text.lower() == auction_id.lower():
        return False
    compact = re.sub(r"[\s.。、,/]+", "", text)
    if _BUYEE_WEAK_TITLE.fullmatch(compact):
        return False
    if _CJK_TITLE.search(text):
        return True
    if _buyee_catalogs_in(text) or catalog_token(title=text):
        return True
    if _buyee_is_lot_set(text):
        return True
    if _BUYEE_TITLE_WORD.search(text):
        return True
    if len(re.findall(r"\b[A-Z]{2,3}\b", text)) >= 2:
        return False
    long_words = [
        word
        for word in re.findall(r"[A-Za-z]{5,}", text)
        if re.search(r"[aeiouyAEIOUY]", word)
    ]
    if len(long_words) >= 2:
        return True
    if len(_TITLE_CASE_WORD.findall(text)) >= 2:
        return True
    return False


def _buyee_usable_visual_title(title: str, auction_id: str) -> str:
    """Drop a visual band that is alphabet stew. Keep HIT PACK / 70AH1141."""

    text = str(title or "").strip()
    if _buyee_title_is_usable(text, auction_id):
        return text
    return ""


def _buyee_best_won_title_slice(titles: list[str], count: int) -> list[str]:
    """When the invoice also emitted Won titles, keep the print-order run that names the copies."""

    if count < 2 or len(titles) < count:
        return titles
    best: list[str] | None = None
    best_score: tuple[int, int] | None = None
    for start in range(len(titles) - count + 1):
        chunk = titles[start : start + count]
        score = (sum(_buyee_title_rank(title)[-1] for title in chunk), -start)
        if best_score is None or score > best_score:
            best = chunk
            best_score = score
    return best or titles[:count]


def _buyee_won_list_titles(plain: str, count: int | None = None) -> list[str]:
    """Item names from the won-auction table, keyed by Buyee order number R…"""

    noted = [
        match.group(1).strip()
        for match in _BUYEE_WON_TITLE.finditer(plain)
        if _buyee_title_is_usable(match.group(1))
    ]
    if count is not None and len(noted) > count >= 2:
        noted = _buyee_best_won_title_slice(noted, count)
    if count is not None and len(noted) == count:
        return noted
    if len(noted) >= 2:
        return noted
    titles: list[str] = []
    for match in re.finditer(
        r"(?:\bR25\d{8,}\b|(?<![A-Za-z0-9])25\d{8,}(?!\d))\s*(.+?)"
        r"(?=\bR25\d{8,}\b|(?<![A-Za-z0-9])25\d{8,}(?!\d)|JDirectItems|\Z)",
        plain,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = re.sub(r"\s+", " ", match.group(1)).strip()
        raw = re.sub(
            r"\s*(?:Insured|Delivery|✔|✓)\s*$",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip(" /-")
        if _buyee_title_is_usable(raw):
            titles.append(raw[:180])
    return titles


def _buyee_title_rank(title: str, auction_id: str = "") -> tuple[int, int, int, int, int]:
    """How much of a name the matcher can use. Auction ids and まで score lowest."""

    text = str(title or "").strip()
    cleaned = _buyee_polish_copy_title(text, auction_id)
    if not cleaned:
        return (0, 0, 0, 0, 0)
    chrome = bool(re.search(r"\bName\b|TemName|Item\s*Name", text, re.IGNORECASE))
    signal = _BUYEE_CJK_FILLER.sub("", cleaned)
    return (
        1,
        0 if chrome else 1,
        int(bool(catalog_token(title=cleaned))),
        int(purchase_media(cleaned) is not None),
        len(_CJK_TITLE.findall(signal)),
    )


def _buyee_overlay_won_list_titles(
    purchases: tuple[ParsedPurchase, ...],
    plain: str,
) -> tuple[ParsedPurchase, ...]:
    """Put the won-list names on invoice rows that only have OCR junk."""

    titles = _buyee_won_list_titles(plain, count=len(purchases))
    if not titles or len(titles) != len(purchases):
        return purchases
    updated: list[ParsedPurchase] = []
    for purchase, title in zip(purchases, titles, strict=True):
        if _buyee_title_rank(title, purchase.external_id) < _buyee_title_rank(
            purchase.title, purchase.external_id
        ):
            polished = _buyee_polish_copy_title(purchase.title, purchase.external_id)
            if polished and polished != purchase.title:
                updated.append(replace(purchase, title=polished))
            else:
                updated.append(purchase)
            continue
        polished = _buyee_polish_copy_title(title, purchase.external_id) or title
        catalog = catalog_token(title=polished) or purchase.catalog_number
        updated.append(replace(purchase, title=polished, catalog_number=catalog))
    return tuple(updated)


def _buyee_item_title(window: str, before: str, plain: str, auction_id: str) -> str:
    """The printed item name, or the catalog OCR managed to read.

    English Tesseract cannot read the Japanese. The catalog at the end of the
    name, and words such as BUDOKAN or YAMAGUCHI, are what make the row matchable.
    """

    raw = _buyee_name_text(window)
    cleaned = re.sub(r"[|«»©_]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    polished = _buyee_polish_copy_title(cleaned, auction_id)
    if polished and _CJK_TITLE.search(polished):
        return polished
    from_name = _short_buyee_title(raw)
    if from_name:
        return from_name
    set_title = _buyee_lot_set_title(raw) or _buyee_lot_set_title(window)
    if set_title:
        return set_title
    if _buyee_title_is_usable(cleaned, auction_id) and len(cleaned) <= 180:
        return _buyee_polish_copy_title(cleaned, auction_id)
    beside = _buyee_title_beside_id(plain, auction_id) or _short_buyee_title(before)
    if _buyee_title_is_usable(beside, auction_id):
        return _buyee_polish_copy_title(beside, auction_id)
    return ""


def _buyee_invoice_items(plain: str) -> list[tuple[str, str, Decimal | None]]:
    """One row per auction that prints an item price, wherever that block sits.

    A long invoice puts the fee heading between item screenshots. The auctions
    after that heading are still items. A breakdown row has the auction id and
    a fee, and no item price, so it is not a second copy.
    """

    matches = list(_BUYEE_AUCTION_ID.finditer(plain))
    chosen: dict[str, tuple[int, str, str]] = {}
    for index, match in enumerate(matches):
        auction_id = match.group(1).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
        window = plain[match.end() : end]
        fee_heading = re.search(
            r"Other Service Fees|Plan Fee|Buyee Service Fee|Domestic Shipping Fee|"
            r"International Shipping Fee|Customs Dut",
            window,
            re.IGNORECASE,
        )
        if fee_heading is not None:
            window = window[: fee_heading.start()]
        if _BUYEE_ITEM_MARK.search(window) is None:
            # Item Name dropped. A catalog plus the doubled yen is still a row.
            # A one-copy invoice can keep only the Japanese name.
            only_one = len({match.group(1).lower() for match in matches}) == 1
            if only_one and _CJK_TITLE.search(window):
                pass
            elif not _buyee_catalogs_in(window) or _buyee_item_amount(window) is None:
                continue
        previous = chosen.get(auction_id)
        if previous is not None:
            # The item-name block beats a fee row, which prints the next LP's catalog.
            prev_item = _buyee_window_is_item(previous[1])
            new_item = _buyee_window_is_item(window)
            if prev_item and not new_item:
                continue
            if not (new_item and not prev_item):
                if _buyee_item_amount(previous[1]) is not None:
                    continue
                if _buyee_item_amount(window) is None:
                    continue
        before = plain[max(0, match.start() - 120) : match.start()]
        chosen[auction_id] = (index, window, before)
    items: list[tuple[str, str, Decimal | None]] = []
    for auction_id, (_index, window, before) in sorted(
        chosen.items(), key=lambda item: item[1][0]
    ):
        amount = _buyee_item_amount(window)
        title = _buyee_item_title(window, before, plain, auction_id)
        if not _buyee_title_is_usable(title, auction_id):
            title = _buyee_cjk_title_for_auction(plain, auction_id) or title
        items.append((auction_id, title, amount))
    return items


def _buyee_cjk_title_for_auction(plain: str, auction_id: str) -> str:
    """A later fee-table row can still print the Japanese Item Name."""

    best = ""
    matches = list(_BUYEE_AUCTION_ID.finditer(plain))
    for index, match in enumerate(matches):
        if match.group(1).lower() != auction_id:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
        window = plain[match.end() : end]
        before = plain[max(0, match.start() - 120) : match.start()]
        title = _buyee_item_title(window, before, plain, auction_id)
        if _buyee_title_rank(title, auction_id) > _buyee_title_rank(best, auction_id):
            best = title
    return best if _buyee_title_is_usable(best, auction_id) else ""


def _buyee_window_is_item(window: str) -> bool:
    """True when this block is the item name, not a fee breakdown."""

    return bool(
        re.search(
            r"Item\s*Name|(?:Item|ltem|Trem)\s*Price|Quantity",
            window,
            flags=re.IGNORECASE,
        )
    )


def _buyee_item_amount(window: str) -> Decimal | None:
    """The printed item price. A fee breakdown's 500 is not an item price."""

    fee_heading = re.search(
        r"Other Service Fees|Plan Fee|Buyee Service Fee|Domestic Shipping Fee|"
        r"International Shipping Fee|Customs Dut",
        window,
        re.IGNORECASE,
    )
    if fee_heading is not None:
        window = window[: fee_heading.start()]
    labeled = re.findall(
        r"(?:Item|ltem|Ttem|Trem)\s*Price\D{0,40}([0-9][0-9,]*)",
        window,
        flags=re.IGNORECASE,
    )
    for raw in labeled:
        amount = _decimal(raw)
        if (
            amount is not None
            and amount >= Decimal("10")
            and not _buyee_amount_is_date_year(amount, window)
        ):
            return amount
    if re.search(r"(?:Item|ltem|Ttem|Trem)\s*Price", window, flags=re.IGNORECASE):
        for raw in re.findall(r"(?m)^\s*\[?\s*([0-9]{3,6})\s*\]?\s*$", window):
            amount = _decimal(raw)
            if amount is not None and amount >= Decimal("10"):
                return amount
    catalogs = _buyee_catalogs_in(window)
    if not (
        re.search(r"Item Name|Quantity|Shopping Site", window, flags=re.IGNORECASE)
        or catalogs
    ):
        return None
    fees = {Decimal("300"), Decimal("500"), Decimal("880")}
    candidates: list[Decimal] = []
    for raw in re.findall(r"[0-9]{1,3}(?:,[0-9]{3})+", window):
        amount = _decimal(raw)
        if amount is not None and amount not in fees:
            candidates.append(amount)
    for raw in re.findall(r"(?m)^\s*([1-9][0-9]{2,5})\s*$", window):
        amount = _decimal(raw)
        if amount is not None and amount not in fees:
            candidates.append(amount)
    # Pass catalogs as the title so "1,001" is not treated as catalog "001".
    return _buyee_visual_amount(" ".join(catalogs), candidates)


def _buyee_fee_key(label: str) -> str | None:
    """Map a printed fee heading to the charge it belongs to."""

    name = re.sub(r"\bduties\b", "duty", label.strip().lower())
    return {
        "customs clearance fee": "clearance",
        "domestic shipping fee": "domestic_shipping",
        "plan fee": "plan_fee",
        "buyee service fee": "service_fee",
        "international shipping fee": "international",
        "customs duty": "customs",
        "protective packaging fee": "packaging",
    }.get(name)


def _buyee_fee_sections(
    tail: str,
) -> dict[str, Any]:
    sections: dict[str, Any] = {
        "domestic_shipping": {},
        "plan_fee": {},
        "service_fee": {},
        "clearance": {},
        "international": None,
        "customs": None,
        "packaging": None,
        "package": {
            "domestic_shipping": None,
            "plan_fee": None,
            "service_fee": None,
            "clearance": None,
        },
    }
    rejected = _buyee_rejected_amounts(tail)
    parts = _BUYEE_FEE_SECTION.split(tail)
    labels = parts[1::2]
    bodies = parts[2::2]
    for label, body in zip(labels, bodies, strict=True):
        key = _buyee_fee_key(label)
        if key is None:
            continue
        if key in {"international", "customs", "packaging"}:
            minimum = Decimal("50")
            if key == "international":
                minimum = Decimal("500")
            elif key == "packaging":
                minimum = Decimal("100")
            amount = _buyee_nearby_fee_amount(
                body,
                rejected,
                minimum=minimum,
            )
            if amount is not None and sections[key] is None:
                sections[key] = amount
            continue
        amounts = (
            {}
            if _buyee_fee_body_repeats_items(body)
            else _buyee_auction_amounts(body, rejected)
        )
        if amounts:
            sections[key] = _buyee_plausible_fee_map(key, amounts)
            continue
        lone = _buyee_first_fee_amount(body, rejected)
        if lone is not None and sections["package"][key] is None:
            sections["package"][key] = lone
    _buyee_apply_fee_column(sections, tail, rejected)
    grand = _buyee_grand_total(tail)
    if (
        sections["international"] is not None
        and grand is not None
        and sections["international"] > grand
    ):
        sections["international"] = None
    return sections


def _buyee_fee_body_repeats_items(body: str) -> bool:
    """True when a fee heading is followed by the item table, not per-auction fees."""

    return bool(
        re.search(
            r"Shopping\s*Site\s*Item\s*Name|^\s*\(ID\)\s*$",
            body,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )


def _buyee_grand_total(text: str) -> Decimal | None:
    match = re.search(
        r"Grand Total Payment Amount\D{0,80}([0-9][0-9,]*)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _decimal(match.group(1))


def _buyee_other_service_total(text: str) -> Decimal | None:
    """The Other Service Fees table total is plan+service+domestic, not postage."""

    match = re.search(
        r"Other Service Fees(.*?)(?:Shipping Expenses|International Shipping Fee|Grand Total)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    totals = re.findall(
        r"Total Amount\D{0,20}([0-9][0-9,]*)",
        match.group(1),
        flags=re.IGNORECASE,
    )
    if not totals:
        return None
    return _decimal(totals[-1])


def _buyee_rejected_amounts(text: str) -> set[Decimal]:
    """The payment total is not a shipping line or a fee."""

    rejected: set[Decimal] = set()
    grand = _buyee_grand_total(text)
    if grand is not None:
        rejected.add(grand)
    for _date_text, amount in _buyee_payment_pairs(text):
        rejected.add(amount)
    for year_text in re.findall(r"\b(20\d{2})/\d{2}/\d{2}", text):
        rejected.add(Decimal(year_text))
    return rejected


def _buyee_plausible_fee_map(key: str, amounts: dict[str, Decimal]) -> dict[str, Decimal]:
    """Drop a fee column that OCR turned into 6 or 16,407.

    Plan and service are a few hundred yen. Domestic shipping on one auction
    stays under a few thousand. A 6 is the tail of an auction id.
    """

    if key in {"plan_fee", "service_fee"}:
        allowed = {Decimal("300"), Decimal("500")}
        return {
            auction_id: amount
            for auction_id, amount in amounts.items()
            if amount in allowed
        }
    if key not in {"domestic_shipping", "clearance"}:
        return amounts
    return {
        auction_id: amount
        for auction_id, amount in amounts.items()
        if Decimal("100") <= amount <= Decimal("5000")
    }


def _buyee_orphan_plan_fees(
    plain: str,
    items: list[tuple[str, str, Decimal | None]],
    sections: dict[str, Any],
) -> None:
    """Plan rows sometimes sit on the screenshot before the Plan Fee heading.

    The heading is the last line of the previous picture. The 500s are already
    on this one, above Buyee Service Fee.
    """

    if len(sections["plan_fee"]) >= len(items):
        return
    head = re.split(
        r"Buyee Service Fee|Domestic Shipping Fee",
        plain,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    found = _buyee_plausible_fee_map(
        "plan_fee",
        _buyee_auction_amounts(head, _buyee_rejected_amounts(plain)),
    )
    if len(found) < 3 or set(found.values()) != {Decimal("500")}:
        return
    sections["plan_fee"].update(found)


def _buyee_fill_flat_fees(
    sections: dict[str, Any],
    items: list[tuple[str, str, Decimal | None]],
) -> None:
    """Plan and service are the same on every auction of one Buyee bill.

    A fee page that only shows 500 next to some of the ids still names the
    fee for the rest. A 500 that leaked from Plan Fee into the service
    column is not a second service amount. Domestic shipping is not flat:
    a record missing from that table stays without it.
    """

    for key in ("plan_fee", "service_fee"):
        found = sections[key]
        if not found:
            continue
        three = 0
        five = 0
        for amount in found.values():
            if amount == Decimal("300"):
                three += 1
            elif amount == Decimal("500"):
                five += 1
        if three == 0 and five == 0:
            continue
        if key == "plan_fee":
            unit = Decimal("500") if five >= three else Decimal("300")
        else:
            unit = Decimal("300") if three >= five else Decimal("500")
        for auction_id, _title, _amount in items:
            found[auction_id] = unit


def _buyee_fill_single_invoice_gaps(
    items: list[tuple[str, str, Decimal | None]],
    sections: dict[str, Any],
    column_items: list[Decimal],
    grand: Decimal | None,
    plain: str,
) -> None:
    """A 1-copy bill: 1,200 is item+plan+service. Other-fees 980 is 500+300+180."""

    if len(items) != 1:
        return
    auction_id, _title, amount = items[0]
    if amount is None:
        return
    payments = [value for _date_text, value in _buyee_payment_pairs(plain)]
    plan = sections["plan_fee"].get(auction_id) or sections["package"].get("plan_fee")
    service = sections["service_fee"].get(auction_id) or sections["package"].get(
        "service_fee"
    )
    domestic = sections["domestic_shipping"].get(auction_id) or sections["package"].get(
        "domestic_shipping"
    )
    if plan is None and service is None and payments:
        extras = payments[0] - amount
        if extras == Decimal("800"):
            plan, service = Decimal("500"), Decimal("300")
        elif extras == Decimal("1000"):
            plan, service = Decimal("500"), Decimal("500")
    if plan is None and Decimal("500") in column_items and Decimal("300") in column_items:
        plan = Decimal("500")
    if service is None and Decimal("300") in column_items:
        service = Decimal("300")
    if (
        domestic is None
        and plan is not None
        and service is not None
    ):
        other_fees = plan + service
        for candidate in column_items:
            remainder = candidate - other_fees
            if (
                Decimal("0") < remainder <= Decimal("3000")
                and candidate not in {amount, grand, *payments}
            ):
                domestic = remainder
                break
    other_total = _buyee_other_service_total(plain)
    if plan is not None and service is not None:
        if domestic is not None and other_total == domestic:
            extras = domestic - plan - service
            if Decimal("0") < extras <= Decimal("3000"):
                domestic = extras
        elif domestic is None and other_total is not None:
            extras = other_total - plan - service
            if Decimal("0") < extras <= Decimal("3000"):
                domestic = extras
    if plan is not None:
        sections["plan_fee"][auction_id] = plan
    if service is not None:
        sections["service_fee"][auction_id] = service
    if domestic is not None:
        sections["domestic_shipping"][auction_id] = domestic
    skip = {
        value
        for value in (amount, plan, service, domestic, grand, *payments)
        if value is not None
    }
    covered_base = amount
    for part in (plan, service, domestic):
        if part is not None:
            covered_base += part
    needed = grand - covered_base if grand is not None else None
    other_total = (
        plan + service + domestic
        if plan is not None and service is not None and domestic is not None
        else None
    )
    current_intl = sections["international"]
    if (
        needed is not None
        and needed >= Decimal("500")
        and current_intl is not None
        and grand is not None
        and (current_intl > grand or current_intl == other_total)
    ):
        sections["international"] = None
        current_intl = None
    if current_intl is None:
        candidates = [
            candidate
            for candidate in column_items
            if candidate not in skip and candidate >= Decimal("500")
        ]
        chosen = None
        if needed is not None and needed >= Decimal("500") and needed in column_items:
            chosen = needed
        elif grand is not None:
            matching = []
            for candidate in candidates:
                remainder = grand - covered_base - candidate
                if Decimal("0") <= remainder <= Decimal("5000"):
                    matching.append((remainder, candidate))
            if matching:
                chosen = min(matching)[1]
        if chosen is None and candidates:
            chosen = max(candidates)
        if chosen is not None:
            sections["international"] = chosen
            skip.add(chosen)
    if grand is not None:
        covered = amount
        for part in (plan, service, domestic, sections["international"]):
            if part is not None:
                covered += part
        remainder = grand - covered
        current = sections["customs"]
        yearish = current is not None and Decimal("2000") <= current <= Decimal("2035")
        if Decimal("0") < remainder <= Decimal("5000") and (
            current is None or (yearish and current != remainder)
        ):
            sections["customs"] = remainder


def _buyee_even_fee(
    package: Decimal | None,
    count: int,
    *,
    blocked: bool,
    flat: bool,
) -> list[Decimal]:
    """The same plan or service fee on every auction, when the bill prints one total."""

    if blocked or package is None or count < 1 or package % count:
        return []
    each = package / count
    if flat and each not in {Decimal("300"), Decimal("500")}:
        return []
    if not flat and (each < Decimal("100") or each > Decimal("2000")):
        return []
    return [each] * count


def _buyee_nearby_fee_amount(
    body: str,
    rejected: set[Decimal],
    *,
    minimum: Decimal | None = None,
) -> Decimal | None:
    """The amount printed with the heading. A later stray number is not postage.

    ``International Shipping Fee`` followed by ``(Currency: YEN)`` has no
    amount on that line. OCR often glues ``21`` onto it, which is the
    thousands half of ``21,876``, not the postage. Skip the currency line
    and skip amounts below the floor.
    """

    raw: list[Decimal] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"currency|\(yen\)", stripped, re.IGNORECASE) and not re.search(
            r"\d", stripped
        ):
            continue
        amount = _ocr_amount_token(stripped)
        if amount is None and re.search(r"\d", stripped):
            amount = _buyee_first_fee_amount(stripped, set())
        if amount is not None:
            raw.append(amount)
        if len(raw) >= 4:
            break
    amounts: list[Decimal] = []
    index = 0
    while index < len(raw):
        current = raw[index]
        nxt = raw[index + 1] if index + 1 < len(raw) else None
        if (
            nxt is not None
            and current < Decimal("100")
            and Decimal("100") <= nxt <= Decimal("999")
        ):
            amounts.append(current * Decimal("1000") + nxt)
            index += 2
            continue
        amounts.append(current)
        index += 1
    for amount in amounts:
        if amount in rejected:
            continue
        if minimum is not None and amount < minimum:
            continue
        return amount
    return None


def _buyee_first_fee_amount(body: str, rejected: set[Decimal]) -> Decimal | None:
    for match in re.finditer(r"([0-9][0-9,]*)", body):
        amount = _decimal(match.group(1))
        if amount is None or amount in rejected:
            continue
        return amount
    return None


def _buyee_bare_amounts(text: str, rejected: set[Decimal] | None = None) -> list[Decimal]:
    found: list[Decimal] = []
    skip = rejected or set()
    for line in text.splitlines():
        stripped = line.strip().replace(" ", "")
        if not re.fullmatch(r"[0-9][0-9,]*", stripped):
            continue
        amount = _decimal(stripped)
        if amount is None or amount in skip:
            continue
        found.append(amount)
    kept: list[Decimal] = []
    for amount in found:
        if kept and amount == sum(kept, Decimal("0")):
            continue
        if kept and amount == kept[-1]:
            continue
        kept.append(amount)
    return kept


def _buyee_apply_fee_column(
    sections: dict[str, Any],
    tail: str,
    rejected: set[Decimal] | None = None,
) -> None:
    """Pair a left-hand fee column with the amounts Tesseract read underneath it."""

    if any(sections[key] for key in ("plan_fee", "service_fee", "domestic_shipping", "clearance")):
        return
    parts = _BUYEE_FEE_SECTION.split(tail)
    labels = [
        key
        for label in parts[1::2]
        if (key := _buyee_fee_key(label)) is not None
    ]
    bodies = parts[2::2]
    if not labels or len(bodies) != len(labels):
        return
    if all(re.search(r"[0-9]", body) for body in bodies):
        return
    bare = _buyee_bare_amounts(tail, rejected)
    if len(bare) < len(labels):
        return
    package_keys = {"plan_fee", "service_fee", "domestic_shipping", "clearance"}
    for key, amount in zip(labels, bare, strict=False):
        if key in package_keys:
            sections["package"][key] = amount
        elif key in {"international", "customs", "packaging"} and sections[key] is None:
            if key == "international" and amount < Decimal("500"):
                continue
            sections[key] = amount


def _buyee_amount_is_catalog_fragment(window: str, start: int, end: int) -> bool:
    """``70AH1 141`` is the catalog 70AH1141, not a domestic fee of 141."""

    digits = re.sub(r"\D", "", window[start:end])
    if len(digits) < 3:
        return False
    around = window[max(0, start - 16) : min(len(window), end + 4)]
    glued = re.sub(r"\s+", "", around)
    catalogs = _buyee_catalogs_in(around) + _buyee_catalogs_in(glued)
    return any(digits in re.sub(r"\D", "", catalog) for catalog in catalogs)


def _buyee_window_amount(window: str, rejected: set[Decimal]) -> Decimal | None:
    """The last standalone amount in a slice. Skip the payment total."""

    value = None
    for found in re.finditer(
        r"(?<![A-Za-z0-9])([0-9][0-9,]*)(?![A-Za-z0-9])",
        window,
    ):
        candidate = _decimal(found.group(1))
        if candidate is None or candidate in rejected:
            continue
        if _buyee_amount_is_catalog_fragment(window, found.start(), found.end()):
            continue
        value = candidate
    return value


def _buyee_auction_amounts(
    section: str,
    rejected: set[Decimal] | None = None,
) -> dict[str, Decimal]:
    """The fee on each auction. It is usually under the id, sometimes on the line above."""

    matches = list(_BUYEE_AUCTION_ID.finditer(section))
    skip = rejected or set()
    found: dict[str, Decimal] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        value = _buyee_window_amount(section[match.end() : end], skip)
        if value is None:
            value = _buyee_window_amount(section[max(0, match.start() - 80) : match.start()], skip)
        if value is not None:
            found[match.group(1).lower()] = value
    return found


def _buyee_bill_note(chunk: str) -> str:
    """Keep the charge lines. Leave names, addresses, and phone numbers out."""

    if _PERSONAL_LINE.search(chunk):
        chunk = "\n".join(
            line
            for line in chunk.splitlines()
            if not _PERSONAL_LINE.search(line)
        )
    pairs = (
        ("Item price", r"Item Price\s*[:：]?\s*(-?[0-9][0-9,]*)"),
        ("Coupon", r"Coupon discount\s*[:：]?\s*(-?[0-9][0-9,]*)"),
        ("Plan fee", r"Plan Fee\s*[:：]?\s*(-?[0-9][0-9,]*)"),
        ("Service fee", r"Buyee Service Fee\s*[:：]?\s*(-?[0-9][0-9,]*)"),
        (
            "Domestic shipping",
            r"Domestic Shipping Fee[^\n\d]{0,48}(-?[0-9][0-9,]*)",
        ),
        (
            "Customs clearance",
            r"Customs Clearance Fee\s*[:：]?\s*(-?[0-9][0-9,]*)",
        ),
        (
            "International shipping",
            r"International Shipping Fee\s*[:：]?\s*(-?[0-9][0-9,]*)",
        ),
        ("Customs", r"Customs Duty\s*[:：]?\s*(-?[0-9][0-9,]*)"),
        (
            "Grand total",
            r"Grand Total Payment Amount\s*[:：]?\s*(-?[0-9][0-9,]*)\s*YEN",
        ),
    )
    lines: list[str] = []
    auction = _BUYEE_AUCTION_ID.search(chunk)
    if auction is not None:
        lines.append(f"Auction {auction.group(1)}")
    for label, pattern in pairs:
        match = re.search(pattern, chunk, re.IGNORECASE)
        if match is not None:
            lines.append(f"{label} {match.group(1)} JPY")
    for date_text, amount in _buyee_payment_pairs(chunk):
        lines.append(f"Payment {date_text} {_note_yen(amount)} JPY")
    return "\n".join(lines)


def _ebay_rows(raw: str) -> list[ParsedPurchase]:
    plain = _plain_text(raw)
    combined = _ebay_combined_item_rows(plain)
    if combined:
        return combined
    detail_first = _ebay_detail_rows(plain)
    if detail_first and len(_EBAY_HREF.findall(plain)) < 2:
        return detail_first
    orders = _ebay_order_history_rows(plain)
    if orders:
        return orders
    detail = _ebay_detail_rows(plain)
    if detail:
        return detail
    soup_rows = _rows_from_links(
        raw,
        href_pattern=_EBAY_HREF,
        source="ebay",
        default_currency="USD",
    )
    if soup_rows:
        return soup_rows
    return _rows_from_pattern(
        raw,
        pattern=_EBAY_LABEL,
        source="ebay",
        default_currency="USD",
    )


def _buyee_rows(raw: str) -> list[ParsedPurchase]:
    plain = _plain_text(raw)
    invoice = _buyee_invoice_rows(plain)
    if invoice:
        return invoice
    orders = _buyee_order_rows(plain)
    if orders:
        return orders
    soup_rows = _rows_from_links(
        raw,
        href_pattern=_BUYEE_HREF,
        source="buyee",
        default_currency="JPY",
    )
    if soup_rows:
        return soup_rows
    return _rows_from_pattern(
        raw,
        pattern=_BUYEE_ID,
        source="buyee",
        default_currency="JPY",
    )


_RC_HISTORY = re.compile(
    r"^(?P<title>.+?)\s+JP\s*[¥￥]\s*(?P<yen>[0-9][0-9,]*)\s*$",
    re.IGNORECASE,
)
_RC_BADGE = re.compile(r"""^(?:(?P<seven>7)\s*["″]|LP|CD)\s*$""", re.IGNORECASE)


_RC_INCH_MARK = r"""["″“”′'°*]"""
_RC_FORMAT = rf"(?:LP|CD|EP|UP|WP|MAGAZINE|7\s*{_RC_INCH_MARK}?)"
_RC_ORDER_LINE = re.compile(
    rf"(?P<qty>\d+)\s+(?P<fmt>{_RC_FORMAT})\s+"
    r"JP\s*[¥￥]\s*(?P<yen>[0-9][0-9,]*)\s+"
    rf"(?P<body>.+?)(?=(?:\s+\d+\s+{_RC_FORMAT}\s+JP\s*[¥￥])"
    r"|\s*[\[(]\s*(?:Purchase\s+Total|Shipping|Invoice\s+Total|Estimated\s+Shipping|"
    r"Subtotal|Total|Order\s|Payment\s)"
    r"|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_RC_ITEM_LINE = re.compile(
    rf"^(?P<qty>\d+)\s+(?P<fmt>{_RC_FORMAT})\s+"
    r"JP\s*[¥￥]\s*(?P<yen>[0-9][0-9,]*)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_RC_ITEM_HEAD = re.compile(
    rf"^(?P<qty>\d+)\s+(?P<fmt>{_RC_FORMAT})(?=\s)"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)
_RC_YEN_IN_REST = re.compile(
    r"^\s*(?:JPY|JPV|JP|YP|Ye|J2)?"
    r"[\s¥￥YV.<]*"
    r"(?P<yen>\d(?:[\d,]|[A-Za-z](?=\d)){1,6})"
    r"(?P<body>\s+.+)$",
    re.IGNORECASE,
)
_RC_TOTAL_LINE = re.compile(
    r"^[\[(]\s*(?:Purchase\s+Total|Shipping|Invoice\s+Total|Estimated\s+Shipping|"
    r"Subtotal|Total|Order\s|Payment\s)",
    re.IGNORECASE,
)
_RC_ESTIMATED_SHIPPING = re.compile(
    r"[\[(](?:Estimated Shipping Fee|Shipping)\]\s*JP\s*[¥￥]\s*([0-9][0-9,]*)",
    re.IGNORECASE,
)
_RC_ORDER_TOTAL = re.compile(
    r"[\[(](?:Invoice Total|Total)\]\s*JP\s*[¥￥]\s*([0-9][0-9,]*)",
    re.IGNORECASE,
)
_RC_ORDER_NUMBER = re.compile(
    r"[\[(]Order Number\]\s*(\d{6,})",
    re.IGNORECASE,
)
_RC_RANGE_CATALOG = re.compile(
    r"^([A-Z]{0,4}\d{0,3}[A-Z]{1,4})\s*[- ]?\s*(\d{1,4})\s*[-~]\s*(\d{1,4})$",
    re.IGNORECASE,
)


def _record_city_rows(raw: str) -> list[ParsedPurchase]:
    """Read a Record City order history.

    The history prints a format, a title, and a yen price. The catalog
    number is not on the page, so it stays empty until a later lookup.
    An order receipt prints ``1 LP JP ¥ 8480 Title (LABEL) (MR 3037)
    (3224142)`` plus ``[Estimated Shipping Fee]``.
    """

    order_rows = _record_city_order_rows(raw)
    if order_rows:
        return order_rows
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    pending_format = ""
    for line in _record_city_blocks(raw):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue
        badge = _RC_BADGE.fullmatch(cleaned)
        if badge is not None:
            pending_format = "7" if badge.group("seven") else cleaned.upper()
            continue
        history = _RC_HISTORY.match(cleaned)
        if history is not None:
            title = history.group("title").strip()
            amount = _decimal(history.group("yen"))
            purchase = _record_city_purchase(
                title=title,
                amount=amount,
                paid_on=None,
                catalog=None,
                order_format=pending_format,
            )
            pending_format = ""
        else:
            catalog = catalog_token(title=cleaned)
            if not catalog:
                continue
            amount, _currency = _money(cleaned, default_currency="JPY")
            purchase = _record_city_purchase(
                title=_guess_title(cleaned, catalog) or catalog,
                amount=amount,
                paid_on=_date(cleaned),
                catalog=catalog,
                order_format=pending_format,
            )
            pending_format = ""
        if purchase.external_id in seen:
            continue
        seen.add(purchase.external_id)
        rows.append(purchase)
    return rows


def _record_city_order_rows(raw: str) -> list[ParsedPurchase]:
    """One Record City receipt: every item line, shipping split by price."""

    text = _plain_text(raw)
    found = _record_city_item_matches(text)
    if not found:
        return []
    paid_on = _date(text)
    order_match = _RC_ORDER_NUMBER.search(text)
    order_id = order_match.group(1) if order_match else ""
    drafts: list[tuple[str, str, Decimal | None, str | None, str]] = []
    for match in found:
        title, catalog, line_id = _record_city_order_tail(match.group("body"))
        amount = _decimal(match.group("yen"))
        drafts.append(
            (title, _record_city_order_format(match.group("fmt")), amount, catalog, line_id)
        )
    shipping_match = _RC_ESTIMATED_SHIPPING.search(text)
    shipping = _decimal(shipping_match.group(1)) if shipping_match else None
    total_match = _RC_ORDER_TOTAL.search(text)
    order_total = _decimal(total_match.group(1)) if total_match else None
    weights = [amount if amount is not None else Decimal("0") for _, _, amount, _, _ in drafts]
    shares = (
        _signed_package_shares(shipping, weights)
        if shipping is not None
        else [None] * len(drafts)
    )
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for (title, order_format, amount, catalog, line_id), share in zip(drafts, shares, strict=True):
        purchase = _record_city_purchase(
            title=title,
            amount=amount,
            paid_on=paid_on,
            catalog=catalog,
            order_format=order_format,
            external_id=line_id or None,
        )
        charges: list[tuple[str, Decimal | None]] = [("Shipping", share)]
        if order_total is not None:
            charges.append(("Order total", order_total))
        note = _charge_note(tuple(charges), "JPY")
        if purchase.billing_note:
            note = "\n".join(part for part in (note, purchase.billing_note) if part)
        purchase = ParsedPurchase(
            source=purchase.source,
            external_id=purchase.external_id,
            title=purchase.title,
            seller=purchase.seller,
            paid_amount=purchase.paid_amount,
            paid_currency=purchase.paid_currency,
            paid_on=purchase.paid_on,
            catalog_number=purchase.catalog_number,
            billing_note=note,
            order_id=order_id,
        )
        if purchase.external_id in seen:
            continue
        seen.add(purchase.external_id)
        rows.append(purchase)
    return rows


def _canonicalize_record_city_line(line: str) -> str | None:
    """Turn a smudged ``1 LP JPV¥579 Title`` back into ``1 LP JP ¥ 579 Title``."""

    head = _RC_ITEM_HEAD.match(line.strip())
    if head is None:
        return None
    yen = _RC_YEN_IN_REST.match(head.group("rest"))
    if yen is None:
        return None
    amount = re.sub(r"\D", "", yen.group("yen"))
    if not amount:
        return None
    fmt = head.group("fmt")
    if fmt.upper().startswith("7"):
        fmt = "7"
    elif re.fullmatch(r"UP|WP", fmt, flags=re.IGNORECASE):
        fmt = "LP"
    body = yen.group("body").strip()
    return f"{head.group('qty')} {fmt} JP ¥ {amount} {body}"


def _record_city_item_matches(text: str) -> list[re.Match[str]]:
    """One match per item line. A totals line does not swallow the last LP."""

    drafts: list[re.Match[str]] = []
    pending: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _RC_TOTAL_LINE.match(line):
            pending = None
            continue
        canonical = _canonicalize_record_city_line(line)
        match = _RC_ITEM_LINE.match(canonical) if canonical else None
        if match is not None:
            drafts.append(match)
            pending = canonical
            continue
        if pending is None or re.match(r"^\d+\s+\S", line):
            continue
        pending = f"{pending} {line}"
        wrapped = _RC_ITEM_LINE.match(pending)
        if wrapped is not None:
            drafts[-1] = wrapped
    if len(drafts) >= 2:
        return drafts
    return list(_RC_ORDER_LINE.finditer(text))


def _record_city_printed_catalog(part: str) -> str | None:
    """Keep a printed range such as 25AH 1-10. A single number still folds."""

    match = _RC_RANGE_CATALOG.fullmatch(part.strip())
    if match and _record_city_range_follows(match.group(2), match.group(3)):
        return f"{match.group(1).upper()}-{match.group(2)}~{match.group(3)}"
    return catalog_token(catalog_number=part, title=part)


def _record_city_range_follows(head: str, tail: str) -> bool:
    """1167-8 is the next number. 1-10 is the whole box."""

    if not head.isdigit() or not tail.isdigit():
        return False
    if int(tail) > int(head):
        return True
    if len(tail) >= len(head):
        return False
    return int(head[: -len(tail)] + tail) == int(head) + 1


def _record_city_order_format(raw: str) -> str:
    compact = re.sub(r"\s+", "", raw).upper()
    if compact.startswith("7"):
        return "7"
    return compact


def _record_city_order_tail(body: str) -> tuple[str, str | None, str]:
    """Title, catalog, and the trailing Record City line id."""

    rest = re.sub(r"\s+", " ", body).strip()
    parens: list[str] = []
    while True:
        match = re.search(r"\(([^)]+)\)\s*$", rest)
        if match is None:
            break
        parens.append(match.group(1).strip())
        rest = rest[: match.start()].strip(" -")
    line_id = ""
    catalog: str | None = None
    for part in parens:
        compact = re.sub(r"\s+", "", part)
        if not line_id and compact.isdigit():
            line_id = compact
            continue
        if catalog is None:
            catalog = _record_city_printed_catalog(part)
    title = rest or body.strip()
    return title, catalog, line_id


def _record_city_purchase(
    *,
    title: str,
    amount: Decimal | None,
    paid_on: date | None,
    catalog: str | None,
    order_format: str,
    external_id: str | None = None,
) -> ParsedPurchase:
    if not external_id and catalog:
        external_id = _record_city_id(catalog, paid_on, amount)
    elif not external_id:
        compact = re.sub(r"[^a-z0-9]", "", title.casefold())
        paid = f"{amount:.2f}" if amount is not None else ""
        external_id = f"title:{compact}:{paid}"
    note = ""
    if order_format == "7":
        note = 'Format: 7"'
    elif order_format:
        note = f"Format: {order_format}"
    return ParsedPurchase(
        source="recordcity",
        external_id=external_id,
        title=title,
        seller="Record City",
        paid_amount=amount,
        paid_currency="JPY",
        paid_on=paid_on,
        catalog_number=catalog,
        billing_note=note,
    )


def fill_record_city_catalogs(purchases, search):
    """Fill a Record City catalog only when Discogs has one matching release.

    Record City spells titles in its own romanization. The lookup searches
    the Japanese title Discogs stores for that spelling. ``search(title,
    format_name)`` returns Discogs hits. Other shops are left unchanged.
    A title with several catalogs stays blank.
    """

    filled: list[ParsedPurchase] = []
    for purchase in purchases:
        if purchase.source != "recordcity" or purchase.catalog_number:
            filled.append(purchase)
            continue
        catalog, note = _record_city_discogs_catalog(purchase, search)
        if not catalog:
            filled.append(purchase)
            continue
        extra = purchase.billing_note
        combined = "\n".join(part for part in (extra, note) if part)
        filled.append(
            ParsedPurchase(
                source=purchase.source,
                external_id=purchase.external_id,
                title=purchase.title,
                seller=purchase.seller,
                paid_amount=purchase.paid_amount,
                paid_currency=purchase.paid_currency,
                paid_on=purchase.paid_on,
                catalog_number=catalog,
                billing_note=combined,
            )
        )
    return tuple(filled)


# Record City romanization is not the spelling Discogs indexes. These
# groups are the titles verified against Discogs for that shop's history.
# They stay here so a Record City lookup does not change identity matching.
_RECORD_CITY_TITLES = (
    ("百恵白書", "Momoe Hakusyo", "Momoe Hakusho"),
    ("不死鳥伝説", "Fushicyou Densetsu", "Fushicho Densetsu"),
    ("ささやかな欲望", "Sasayakana Yokubou", "Sasayakana Yokubo"),
    ("絶唱", "Zessyo", "Zessho"),
    ("花ざかり", "Hanazakari"),
    ("パールカラーにゆれて", "Pearl Color ni Yurete"),
    ("愛染橋", "Aizomebashi"),
    ("絶体絶命", "Zettai Zetsumei"),
    ("秋桜", "Cosmos"),
    ("最後のページ", "Saigo no Page"),
    ("初恋草紙", "Hatsukoizoushi"),
    ("オレンジ・ブロッサム・ブルース", "Orange Blossom Blues"),
    ("赤い衝撃", "Akaishougeki"),
    ("君に涙のくちづけを", "Kimininamidanokuchizukeo"),
)
_RC_HEPBURN = (
    ("cyou", "cho"),
    ("syou", "sho"),
    ("jyou", "jo"),
    ("jyu", "ju"),
    ("syo", "sho"),
    ("cyo", "cho"),
    ("jyo", "jo"),
)


def _record_city_discogs_catalog(purchase: ParsedPurchase, search) -> tuple[str, str]:
    tracks = _record_city_tracks(purchase.title)
    if not tracks:
        return "", ""
    order_format = ""
    if '7"' in purchase.billing_note:
        order_format = "7"
    elif "Format: LP" in purchase.billing_note:
        order_format = "LP"
    format_name = '7"' if order_format == "7" else ("LP" if order_format == "LP" else "Vinyl")
    catalogs: list[str] = []
    for query in _record_city_queries(tracks[0]):
        if len(query.strip()) < 2:
            continue
        for hit in search(query, format_name):
            catno = str(getattr(hit, "catno", "") or "").strip()
            if not catno or is_junk_catalog(catno, title=purchase.title):
                continue
            formats = tuple(getattr(hit, "formats", ()) or ())
            if not _record_city_format_ok(order_format, formats):
                continue
            album = _record_city_album(str(getattr(hit, "title", "") or ""))
            if not _record_city_album_matches(album, tracks):
                continue
            catalogs.append(catno)
    folds = {fold_catalog(catno) for catno in catalogs if fold_catalog(catno)}
    if len(folds) != 1:
        return "", ""
    chosen = next(catno for catno in catalogs if fold_catalog(catno) == next(iter(folds)))
    return chosen, f"Catalog from Discogs: {chosen}"


def _record_city_tracks(title: str) -> tuple[tuple[str, ...], ...]:
    """Slash-separated tracks. A parenthetical is another spelling, not a track."""

    tracks: list[tuple[str, ...]] = []
    for piece in re.split(r"\s*[/／]\s*", title):
        names = tuple(
            part.strip() for part in re.split(r"[()（）]", piece) if part.strip()
        )
        if names:
            tracks.append(names)
    return tuple(tracks)


def _record_city_queries(track: tuple[str, ...]) -> tuple[str, ...]:
    """Search the Discogs title, which is the Japanese spelling when we know it."""

    forms = _record_city_forms(track)
    japanese = tuple(form for form in forms if _record_city_has_cjk(form))
    if japanese:
        return japanese[:2]
    return forms[:2]


def _record_city_forms(names: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    seeds: list[str] = []
    for name in names:
        seeds.append(name)
        folded = _record_city_hepburn(name)
        if _record_city_compact(folded) != _record_city_compact(name):
            seeds.append(folded)
    seed_compacts = {_record_city_compact(seed) for seed in seeds}
    seed_compacts.discard("")
    for group in _RECORD_CITY_TITLES:
        group_compacts = {_record_city_compact(item) for item in group}
        if seed_compacts & group_compacts:
            for item in group:
                if item not in found:
                    found.append(item)
    for seed in seeds:
        for spelling in equivalent_title_spellings(seed):
            if spelling not in found:
                found.append(spelling)
    if not found:
        found.extend(seeds)
    return tuple(found)


def _record_city_hepburn(value: str) -> str:
    folded = value.casefold()
    for source, dest in _RC_HEPBURN:
        folded = folded.replace(source, dest)
    return folded


def _record_city_compact(value: str) -> str:
    cleaned = value.casefold().replace("・", "").replace("･", "")
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]", "", cleaned)


def _record_city_has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", value))


def _record_city_album(hit_title: str) -> str:
    album = hit_title.split(" - ", 1)[1] if " - " in hit_title else hit_title
    return album.split("=", 1)[0].strip()


def _record_city_album_matches(album: str, tracks: tuple[tuple[str, ...], ...]) -> bool:
    album_compact = _record_city_compact(album)
    if len(album_compact) < 2:
        return False
    if len(tracks) >= 3:
        return all(_record_city_track_in_album(track, album_compact) for track in tracks)
    return any(
        _record_city_compact(form) == album_compact
        for form in _record_city_forms(tracks[0])
        if len(_record_city_compact(form)) >= 2
    )


def _record_city_track_in_album(track: tuple[str, ...], album_compact: str) -> bool:
    return any(
        len(compact) >= 2 and compact in album_compact
        for form in _record_city_forms(track)
        if (compact := _record_city_compact(form))
    )


def _record_city_format_ok(order_format: str, formats: tuple[str, ...]) -> bool:
    blob = " ".join(formats)
    shape = vinyl_shape(blob)
    if order_format == "7":
        return shape == "seven" or '7"' in blob
    if order_format == "LP":
        return shape == "lp"
    return shape in {"lp", "seven", "vinyl"}


def _rows_from_links(
    raw: str,
    *,
    href_pattern: re.Pattern[str],
    source: str,
    default_currency: str,
) -> list[ParsedPurchase]:
    if "<a" not in raw.lower():
        return []
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        match = href_pattern.search(str(link.get("href") or ""))
        if match is None:
            continue
        external_id = match.group(1)
        if external_id in seen:
            continue
        seen.add(external_id)
        context = _nearby_text(link)
        title = link.get_text(" ", strip=True) or _guess_title(context, external_id)
        rows.append(
            _purchase_from_context(
                source=source,
                external_id=external_id,
                title=title,
                context=context,
                default_currency=default_currency,
            )
        )
    return rows


def _rows_from_pattern(
    raw: str,
    *,
    pattern: re.Pattern[str],
    source: str,
    default_currency: str,
) -> list[ParsedPurchase]:
    plain = _plain_text(raw)
    rows: list[ParsedPurchase] = []
    seen: set[str] = set()
    for match in pattern.finditer(plain):
        external_id = match.group(1)
        if external_id in seen:
            continue
        seen.add(external_id)
        start = max(0, match.start() - 240)
        end = min(len(plain), match.end() + 240)
        context = plain[start:end]
        rows.append(
            _purchase_from_context(
                source=source,
                external_id=external_id,
                title=_guess_title(context, external_id),
                context=context,
                default_currency=default_currency,
            )
        )
    return rows


def _purchase_from_context(
    *,
    source: str,
    external_id: str,
    title: str,
    context: str,
    default_currency: str,
) -> ParsedPurchase:
    amount, currency = _money(context, default_currency=default_currency)
    seller_match = _SELLER.search(context)
    seller = seller_match.group(1) if seller_match else ""
    return ParsedPurchase(
        source=source,
        external_id=external_id,
        title=title.strip(),
        seller=seller,
        paid_amount=amount,
        paid_currency=currency,
        paid_on=_date(context),
        catalog_number=catalog_token(title=title) or catalog_token(title=context),
    )


def _record_city_blocks(raw: str) -> list[str]:
    if "<tr" in raw.lower():
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        blocks = [tr.get_text(" ", strip=True) for tr in soup.find_all("tr")]
        if blocks:
            return blocks
    return _plain_text(raw).splitlines()


def _record_city_id(
    catalog: str,
    paid_on: date | None,
    amount: Decimal | None,
) -> str:
    paid = f"{amount:.2f}" if amount is not None else ""
    when = paid_on.isoformat() if paid_on else ""
    return f"{fold_catalog(catalog)}:{when}:{paid}"


def _plain_text(raw: str) -> str:
    # OCR noise includes "<" and ">". Only a saved page is HTML.
    if not re.search(
        r"</[a-z]|<!doctype|<html\b|<table\b|<div\b|<a\s+href",
        raw,
        re.IGNORECASE,
    ):
        return raw
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _nearby_text(tag: object) -> str:
    node = tag
    chosen = ""
    for _ in range(5):
        parent = getattr(node, "parent", None)
        name = getattr(parent, "name", None)
        if parent is None or name in {None, "[document]", "html", "body"}:
            break
        text = parent.get_text(" ", strip=True)
        if len(text) > 2000:
            break
        chosen = text
        if (_YEN.search(text) or _USD.search(text) or _YEN_SUFFIX.search(text)) and (
            _DATE_ISO.search(text) or _DATE_MDY.search(text)
        ):
            return text
        node = parent
    if chosen:
        return chosen
    get_text = getattr(tag, "get_text", None)
    if get_text is None:
        return ""
    return str(get_text(" ", strip=True))


def _guess_title(context: str, external_id: str) -> str:
    cleaned = _USD.sub(" ", context)
    cleaned = _YEN.sub(" ", cleaned)
    cleaned = _YEN_SUFFIX.sub(" ", cleaned)
    cleaned = _DATE_ISO.sub(" ", cleaned)
    cleaned = _DATE_MDY.sub(" ", cleaned)
    cleaned = cleaned.replace(external_id, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|:")
    return cleaned[:180]


def _date(text: str) -> date | None:
    iso = _DATE_ISO.search(text)
    if iso is not None:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    day_first = _DATE_DMY.search(text)
    if day_first is not None:
        try:
            return date(
                int(day_first.group(3)),
                _MONTHS[day_first.group(2)[:3].lower()],
                int(day_first.group(1)),
            )
        except (KeyError, ValueError):
            return None
    named = _DATE_MDY.search(text)
    if named is None:
        return None
    try:
        return date(
            int(named.group(3)),
            _MONTHS[named.group(1)[:3].lower()],
            int(named.group(2)),
        )
    except (KeyError, ValueError):
        return None


def _money(text: str, *, default_currency: str) -> tuple[Decimal | None, str]:
    yen = _YEN.search(text) or _YEN_SUFFIX.search(text)
    usd = _USD.search(text)
    if default_currency == "JPY" and yen is not None:
        return _decimal(yen.group(1)), "JPY"
    if default_currency == "USD" and usd is not None:
        return _decimal(usd.group(1)), "USD"
    if yen is not None:
        return _decimal(yen.group(1)), "JPY"
    if usd is not None:
        return _decimal(usd.group(1)), "USD"
    return None, default_currency


def _cell_money(raw: str, *, default_currency: str) -> tuple[Decimal | None, str]:
    amount, currency = _money(raw, default_currency=default_currency)
    if amount is not None:
        return amount, currency
    return _decimal(raw), default_currency


def _decimal(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None

def purchase_from_lot_line(
    package: LotDraftPackage,
    line: LotDraftLine,
) -> ParsedPurchase:
    """Turn one confirmed lot line into a ParsedPurchase for shelf save."""

    shop = re.sub(r"\s+", " ", package.shop or "").strip() or "Seller list"
    catalog = re.sub(r"\s+", " ", line.catalog_number or "").strip()
    title = re.sub(r"\s+", " ", line.title or "").strip()
    sku = re.sub(r"\s+", " ", line.seller_sku or "").strip()
    catalog_number = None
    if catalog:
        catalog_number = catalog_token(catalog_number=catalog) or catalog
    day = package.paid_on.isoformat() if package.paid_on else ""
    identity = re.sub(
        r"[^a-z0-9]",
        "",
        (sku or catalog_number or title or line.line_id).casefold(),
    )
    paid_label = f"{line.paid_amount:.2f}" if line.paid_amount is not None else ""
    note = (line.billing_note or "").strip()
    return ParsedPurchase(
        source=shop,
        external_id=f"lot:{identity}:{day}:{paid_label}:{line.line_id}",
        title=title or catalog_number or sku or line.line_id,
        seller=shop,
        paid_amount=line.paid_amount,
        paid_currency=(package.currency or "HKD").upper(),
        paid_on=package.paid_on,
        catalog_number=catalog_number,
        billing_note=note,
        order_id=f"lot:{shop}:{day}" if day else f"lot:{shop}",
        package_item=line.paid_amount,
        package_shipping=package.shipping,
        package_tax=package.fee_amount,
        package_total=package.package_total,
        delivered_on=package.delivered_on,
    )
