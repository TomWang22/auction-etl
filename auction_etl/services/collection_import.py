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
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from auction_etl.classifiers.media import classify_media
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


@dataclass(frozen=True)
class ParseResult:
    """Purchases read from one dropped page."""

    source: str
    purchases: tuple[ParsedPurchase, ...]
    note: str


def is_collected_music(title: str | None) -> bool:
    """Keep LP, 7", 12", CD, and cassette. Leave the other formats out."""

    media = classify_media(title)
    if media in _KEEP_MEDIA:
        return True
    if media is None and not _EXTRA_NON_MUSIC.search(str(title or "")):
        return True
    return False


def detect_purchase_source(raw: str) -> str:
    """Name the shop from the page itself."""

    lowered = raw.lower()
    if re.search(r"subtotal", lowered) and re.search(r"\btax\b", lowered):
        return "discogs"
    if "recordcity.jp" in lowered or "record city" in lowered:
        return "recordcity"
    if (
        "buyee.jp" in lowered
        or "jdirectitems" in lowered
        or "won date" in lowered
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
    if re.search(r"\b1\s+item\b", lowered) and "order total" in lowered:
        return "ebay"
    return ""


_LOG_CURRENCIES = frozenset({"USD", "JPY", "EUR", "GBP", "HKD", "TWD", "SEK"})


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


def parse_purchase_export(raw: str) -> ParseResult:
    """Read one saved order page or a pasted table."""

    text = raw.lstrip("\ufeff").strip()
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
    return ParseResult(source=source, purchases=purchases, note="")


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


_EBAY_ORDER_SPLIT = re.compile(r"(?=Order date\s*:)", re.IGNORECASE)
_EBAY_ORDER_NUMBER = re.compile(
    r"Order number:\s*([0-9]{2}-[0-9]{4,6}-[0-9]{4,6})",
    re.IGNORECASE,
)
_EBAY_ORDER_TOTAL = re.compile(
    r"Order total:\s*(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_EBAY_SKIP_LINE = re.compile(
    r"^(delivered|used|new|sold by|order date|order total|order number|"
    r"returns accepted|delivered on|partially refunded|auto-paid|"
    r"ship to|shipping address)\b",
    re.IGNORECASE,
)
_BUYEE_ORDER_ID = re.compile(r"\b(R\d{8,})\b")
_BUYEE_AUCTION_ID = re.compile(
    r"JDirectItems\s+Auction\s*\(\s*([a-z]\d{6,})\s*\)",
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
        number = _EBAY_ORDER_NUMBER.search(chunk)
        if number is None:
            continue
        external_id = number.group(1)
        if external_id in seen:
            continue
        seen.add(external_id)
        seller_match = _SELLER.search(chunk) or re.search(
            r"Sold by:\s*([A-Za-z0-9._-]{2,64})",
            chunk,
            re.IGNORECASE,
        )
        seller = seller_match.group(1) if seller_match else ""
        order_date = re.search(
            r"Order date:\s*([A-Za-z]{3,9}\s+\d{1,2},\s+20\d{2})",
            chunk,
            re.IGNORECASE,
        )
        paid_on = _date(order_date.group(1)) if order_date else _date(chunk)
        detail = _ebay_detail_amounts(chunk)
        if detail["item"] is not None:
            amount, currency = detail["item"], "USD"
            note = _charge_note(
                (
                    ("Shipping", detail["shipping"]),
                    ("Tax", detail["tax"]),
                    ("Order total", detail["total"]),
                ),
                "USD",
            )
        else:
            without_total = _EBAY_ORDER_TOTAL.sub(" ", chunk)
            amount, currency = _money(without_total, default_currency="USD")
            order_total = _EBAY_ORDER_TOTAL.search(chunk)
            note = ""
            if (
                order_total is not None
                and amount is not None
                and _decimal(order_total.group(1)) != amount
            ):
                note = (
                    f"Item price US${amount}. "
                    f"Order total US${_decimal(order_total.group(1))}."
                )
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
                catalog_number=catalog_token(title=title),
                billing_note=note,
            )
        )
    return rows


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
        card = _BUYEE_CARD_TOTAL.search(chunk)
        if card is not None:
            amount = _decimal(card.group(1))
            usd_note = f"Buyee showed US${card.group(2)}."
        else:
            dated = re.search(
                r"20\d{2}/\d{2}/\d{2}\s+([0-9][0-9,]*)",
                chunk,
            )
            amount = _decimal(dated.group(1)) if dated else None
            usd_note = ""
        won = re.search(
            r"Won date\s*:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})",
            chunk,
            re.IGNORECASE,
        )
        paid_on = _date(won.group(1)) if won else _date(chunk)
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


def _order_title(chunk: str, skip: re.Pattern[str]) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in chunk.splitlines()]
    kept: list[str] = []
    for line in lines:
        if len(line) < 2 or skip.search(line) or _PERSONAL_LINE.search(line):
            if kept and re.fullmatch(r"(?:LPs?|CDs?|vinyl)", line, re.IGNORECASE):
                kept[-1] = f"{kept[-1]} {line}"
            continue
        if re.fullmatch(r"(?:US\s*)?\$\s*[0-9,.]+", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"[0-9][0-9,]*\s*YEN", line, re.IGNORECASE):
            continue
        kept.append(line)
    if not kept:
        return ""
    return max(kept, key=len)[:180]


_EBAY_DETAIL_ITEM = re.compile(
    r"\b1\s+item\b[^\n$]{0,80}\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_EBAY_DETAIL_SHIP = re.compile(
    r"\bShipping\b(?!\s+address)[^\n$]{0,80}\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_EBAY_DETAIL_TAX = re.compile(
    r"\bTax\b\*?[^\n$]{0,40}\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_EBAY_DETAIL_TOTAL = re.compile(
    r"\bOrder total\b\s*:?\s*(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_MONEY_CODE = r"(SEK|USD|EUR|GBP|JPY|HKD|TWD)"


def _ebay_detail_amounts(chunk: str) -> dict[str, Decimal | None]:
    """eBay order details: 1 item, shipping, tax, and the order total."""

    return {
        "item": _pattern_amount(_EBAY_DETAIL_ITEM, chunk),
        "shipping": _pattern_amount(_EBAY_DETAIL_SHIP, chunk),
        "tax": _pattern_amount(_EBAY_DETAIL_TAX, chunk),
        "total": _pattern_amount(_EBAY_DETAIL_TOTAL, chunk),
    }


def _pattern_amount(pattern: re.Pattern[str], text: str) -> Decimal | None:
    match = pattern.search(text)
    if match is None:
        return None
    return _decimal(match.group(1))


def _ebay_detail_rows(plain: str) -> list[ParsedPurchase]:
    detail = _ebay_detail_amounts(plain)
    if detail["item"] is None:
        return []
    item = detail["item"]
    total = detail["total"] if detail["total"] is not None else item
    assert item is not None
    return [
        ParsedPurchase(
            source="ebay",
            external_id=f"detail:{_plain_amount(item)}:{_plain_amount(total)}",
            title=_order_title(plain, _EBAY_SKIP_LINE),
            seller="",
            paid_amount=item,
            paid_currency="USD",
            paid_on=_date(plain),
            catalog_number=catalog_token(title=plain),
            billing_note=_charge_note(
                (
                    ("Shipping", detail["shipping"]),
                    ("Tax", detail["tax"]),
                    ("Order total", detail["total"]),
                ),
                "USD",
            ),
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
    r"(Domestic Shipping Fee|Plan Fee|Buyee Service Fee|"
    r"International Shipping Fee|Customs Duty)",
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
)
_COST_LINE = re.compile(
    r"^(?P<package>Package\s+)?"
    r"(?P<label>International shipping|Domestic shipping|Plan fee|Service fee|"
    r"Shipping|Tax|Customs clearance|Customs)"
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
}
_BUYEE_PAYMENT_ROW = re.compile(
    r"(20\d{2}/\d{2}/\d{2})\s+([0-9][0-9,]*)"
)


def _matched_copy_cost(line: str) -> re.Match[str] | None:
    """A charge that belongs to one copy. Package totals are left out."""

    match = _COST_LINE.match(line.strip())
    if match is None or match.group("package"):
        return None
    return match


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
    yen: Decimal,
) -> str:
    """Keep yen lines and add the dollar pair used to convert them."""

    if bill_usd_rate(note) is not None or yen == 0:
        return note.strip()
    usd_text = f"{usd.quantize(Decimal('0.01')):.2f}"
    line = f"USD rate {usd_text} for {_plain_amount(yen)} JPY"
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
            r"(Shipping|Tax|Plan fee|Service fee|Domestic shipping)\b",
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


def _plain_amount(amount: Decimal) -> str:
    text = f"{amount:.2f}"
    return text[:-3] if text.endswith(".00") else text


def _buyee_invoice_rows(plain: str) -> list[ParsedPurchase]:
    """Read a Buyee shipping PDF: one row per auction, with that auction's fees.

    Plan fee, service fee, and domestic shipping are printed on each auction.
    International shipping and customs are printed once for the package, so
    they stay labeled as package amounts.
    """

    if len(_BUYEE_AUCTION_ID.findall(plain)) < 2:
        return []
    if not re.search(r"item price", plain, re.IGNORECASE):
        return []
    marker = _BUYEE_FEE_SECTION.search(plain)
    head = plain[: marker.start()] if marker else plain
    tail = plain[marker.start() :] if marker else ""
    matches = list(_BUYEE_AUCTION_ID.finditer(head))
    if len(matches) < 2:
        return []
    items: list[tuple[str, str, Decimal | None]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        auction_id = match.group(1)
        if auction_id in seen:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(head)
        window = head[match.end() : end]
        name = re.search(r"Item Name\s+(.+)", window, re.IGNORECASE)
        price = re.search(r"Item Price\s+([0-9][0-9,]*)", window, re.IGNORECASE)
        if name is None or price is None:
            continue
        seen.add(auction_id)
        items.append((auction_id, name.group(1).strip(), _decimal(price.group(1))))
    if len(items) < 2:
        return []
    sections = _buyee_fee_sections(tail)
    package_lines: list[str] = []
    if sections["international"] is not None:
        package_lines.append(
            f"Package international shipping {_plain_amount(sections['international'])} JPY"
        )
    if sections["customs"] is not None:
        package_lines.append(
            f"Package customs {_plain_amount(sections['customs'])} JPY"
        )
    package = "\n".join(package_lines)
    rows: list[ParsedPurchase] = []
    for auction_id, title, amount in items:
        lines: list[str] = []
        if amount is not None:
            lines.append(f"Item price {_plain_amount(amount)} JPY")
        for key, label in (
            ("plan_fee", "Plan fee"),
            ("service_fee", "Service fee"),
            ("domestic_shipping", "Domestic shipping"),
        ):
            fee = sections[key].get(auction_id)
            if fee is not None:
                lines.append(f"{label} {_plain_amount(fee)} JPY")
        if package:
            lines.append(package)
        rows.append(
            ParsedPurchase(
                source="buyee",
                external_id=auction_id,
                title=title,
                seller="Buyee",
                paid_amount=amount,
                paid_currency="JPY",
                paid_on=None,
                catalog_number=catalog_token(title=title),
                billing_note="\n".join(lines),
            )
        )
    return rows


def _buyee_fee_sections(
    tail: str,
) -> dict[str, Any]:
    sections: dict[str, Any] = {
        "domestic_shipping": {},
        "plan_fee": {},
        "service_fee": {},
        "international": None,
        "customs": None,
    }
    keys = {
        "domestic shipping fee": "domestic_shipping",
        "plan fee": "plan_fee",
        "buyee service fee": "service_fee",
        "international shipping fee": "international",
        "customs duty": "customs",
    }
    parts = _BUYEE_FEE_SECTION.split(tail)
    labels = parts[1::2]
    bodies = parts[2::2]
    for label, body in zip(labels, bodies, strict=True):
        key = keys[label.strip().lower()]
        if key in {"international", "customs"}:
            amount = re.search(r"([0-9][0-9,]*)", body)
            if amount is not None and sections[key] is None:
                sections[key] = _decimal(amount.group(1))
            continue
        amounts = _buyee_auction_amounts(body)
        if amounts:
            sections[key] = amounts
    return sections


def _buyee_auction_amounts(section: str) -> dict[str, Decimal]:
    found: dict[str, Decimal] = {}
    matches = list(_BUYEE_AUCTION_ID.finditer(section))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        window = section[match.end() : end]
        amounts = re.findall(
            r"(?<![A-Za-z0-9])([0-9][0-9,]*)(?![A-Za-z0-9])",
            window,
        )
        if not amounts:
            continue
        value = _decimal(amounts[-1])
        if value is not None:
            found[match.group(1)] = value
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
            r"Domestic Shipping Fee[^\n]{0,48}\s+([0-9][0-9,]*)",
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
    for date_text, amount in _BUYEE_PAYMENT_ROW.findall(chunk):
        lines.append(f"Payment {date_text} {amount} JPY")
    return "\n".join(lines)


def _ebay_rows(raw: str) -> list[ParsedPurchase]:
    plain = _plain_text(raw)
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


def _record_city_rows(raw: str) -> list[ParsedPurchase]:
    """Read a Record City order history.

    The history prints a format, a title, and a yen price. The catalog
    number is not on the page, so it stays empty until a later lookup.
    """

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


def _record_city_purchase(
    *,
    title: str,
    amount: Decimal | None,
    paid_on: date | None,
    catalog: str | None,
    order_format: str,
) -> ParsedPurchase:
    if catalog:
        external_id = _record_city_id(catalog, paid_on, amount)
    else:
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
    if "<" not in raw or ">" not in raw:
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
