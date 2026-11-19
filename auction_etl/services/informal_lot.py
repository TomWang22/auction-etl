"""Informal HK-style seller lists → lot draft with allocated paid amounts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


# Prefer plain digit runs; comma groups need at least one ,XXX chunk.
_AMOUNT = (
    r"([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
)
_MONEY = re.compile(rf"(?:¥\s*)?\$?\s*{_AMOUNT}")
_SHIPPING = re.compile(
    rf"(?:運費|shipping|postage)\s*[:=]?\s*(?:¥\s*)?\$?\s*{_AMOUNT}",
    re.IGNORECASE,
)
_NEGOTIATED = re.compile(
    rf"(?:好啦[,，]?\s*)?(?:¥\s*)?\$?\s*{_AMOUNT}\s*"
    rf"\+\s*([0-9]{{1,2}}(?:\.[0-9]+)?)\s*%\s*=\s*(?:¥\s*)?\$?\s*{_AMOUNT}",
)
_CONDITION = re.compile(
    r"(近?\s*\d{1,3}\s*成新|全新|ほぼ新品|美品|良好)",
)
_LINE = re.compile(
    rf"^([A-Za-z]{{0,4}}\d{{1,6}}[A-Za-z]?)\s+"
    rf"(.+?)\s+"
    rf"(近?\d{{1,3}}成新|全新)?\s*"
    rf"(?:[，,]?\s*(?:碟有[^\s$¥]+|帶歌詞|有歌詞))?\s*"
    rf"(?:¥\s*)?\$?\s*{_AMOUNT}\s*$",
)
_LINE_LOOSE = re.compile(
    r"^([A-Za-z]{0,4}\d{1,6}[A-Za-z]?)\s+(.+)$",
)

# HK “成新” → suggested Goldmine-ish media grade for the editor.
_HK_GRADE_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"全新|100\s*成新"), "NM"),
    (re.compile(r"近\s*95\s*成新|95\s*成新"), "EX+"),
    (re.compile(r"9\s*成新|90\s*成新"), "VG+"),
    (re.compile(r"85\s*成新"), "VG"),
    (re.compile(r"8\s*成新|80\s*成新"), "G+"),
    (re.compile(r"美品"), "EX"),
    (re.compile(r"良好"), "VG"),
)


def _money(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def hk_condition_to_grade(token: str | None) -> str | None:
    """Map a Hong Kong seller condition phrase to a shelf grade hint."""
    text = re.sub(r"\s+", "", str(token or ""))
    if not text:
        return None
    for pattern, grade in _HK_GRADE_MAP:
        if pattern.search(text):
            return grade
    return None


@dataclass
class LotDraftLine:
    """One pressing in an informal lot before Confirm."""

    line_id: str
    seller_sku: str = ""
    catalog_number: str = ""
    title: str = ""
    list_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    condition_hint: str = ""
    condition_media: str = ""
    condition_cover: str = ""
    media_type: str = ""
    region: str = ""
    disc_count: int = 1
    pressing_type: str = ""
    insert_choice: str = ""
    poster_choice: str = ""
    obi_choice: str = ""
    sealed_choice: str = ""
    rental_choice: str = ""
    pressing_group: str = ""
    verdict: str = ""
    completeness_notes: str = ""
    collector_notes: str = ""
    discogs_release_id: int | None = None
    pressing_id: int | None = None
    release_year: int | None = None
    marketplace: str = ""
    listing_id: str = ""
    billing_note: str = ""
    added: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("list_amount", "paid_amount"):
            value = payload.get(key)
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LotDraftLine:
        data = dict(raw or {})

        def _decimal(key: str) -> Decimal | None:
            value = data.get(key)
            if value in (None, ""):
                return None
            return Decimal(str(value))

        def _optional_int(key: str) -> int | None:
            value = data.get(key)
            if value in (None, ""):
                return None
            return int(value)

        disc_raw = data.get("disc_count")
        disc_count = 1 if disc_raw in (None, "") else max(1, int(disc_raw))
        return cls(
            line_id=str(data.get("line_id") or "lot-line"),
            seller_sku=str(data.get("seller_sku") or ""),
            catalog_number=str(data.get("catalog_number") or ""),
            title=str(data.get("title") or ""),
            list_amount=_decimal("list_amount"),
            paid_amount=_decimal("paid_amount"),
            condition_hint=str(data.get("condition_hint") or ""),
            condition_media=str(data.get("condition_media") or ""),
            condition_cover=str(data.get("condition_cover") or ""),
            media_type=str(data.get("media_type") or ""),
            region=str(data.get("region") or ""),
            disc_count=disc_count,
            pressing_type=str(data.get("pressing_type") or ""),
            insert_choice=str(data.get("insert_choice") or ""),
            poster_choice=str(data.get("poster_choice") or ""),
            obi_choice=str(data.get("obi_choice") or ""),
            sealed_choice=str(data.get("sealed_choice") or ""),
            rental_choice=str(data.get("rental_choice") or ""),
            pressing_group=str(data.get("pressing_group") or ""),
            verdict=str(data.get("verdict") or ""),
            completeness_notes=str(data.get("completeness_notes") or ""),
            collector_notes=str(data.get("collector_notes") or ""),
            discogs_release_id=_optional_int("discogs_release_id"),
            pressing_id=_optional_int("pressing_id"),
            release_year=_optional_int("release_year"),
            marketplace=str(data.get("marketplace") or ""),
            listing_id=str(data.get("listing_id") or ""),
            billing_note=str(data.get("billing_note") or ""),
            added=bool(data.get("added")),
        )


@dataclass
class LotDraftPackage:
    """Package header + lines for an informal seller lot."""

    shop: str = ""
    currency: str = "HKD"
    paid_on: date | None = None
    dispatch_on: date | None = None
    delivered_on: date | None = None
    shipping: Decimal | None = None
    merchandise: Decimal | None = None
    fee_amount: Decimal | None = None
    fee_percent: Decimal | None = None
    package_total: Decimal | None = None
    lines: list[LotDraftLine] = field(default_factory=list)
    raw_paste: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "shipping",
            "merchandise",
            "fee_amount",
            "fee_percent",
            "package_total",
        ):
            value = payload.get(key)
            if isinstance(value, Decimal):
                payload[key] = str(value)
        if isinstance(payload.get("paid_on"), date):
            payload["paid_on"] = payload["paid_on"].isoformat()
        if isinstance(payload.get("dispatch_on"), date):
            payload["dispatch_on"] = payload["dispatch_on"].isoformat()
        if isinstance(payload.get("delivered_on"), date):
            payload["delivered_on"] = payload["delivered_on"].isoformat()
        payload["lines"] = [line.to_dict() for line in self.lines]
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LotDraftPackage:
        data = dict(raw or {})
        for key in (
            "shipping",
            "merchandise",
            "fee_amount",
            "fee_percent",
            "package_total",
        ):
            if data.get(key) not in (None, ""):
                data[key] = Decimal(str(data[key]))
            else:
                data[key] = None
        for key in ("paid_on", "dispatch_on", "delivered_on"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                data[key] = date.fromisoformat(value.strip()[:10])
            elif not isinstance(value, date):
                data[key] = None
        lines = [
            LotDraftLine.from_dict(item)
            for item in (data.get("lines") or [])
            if isinstance(item, dict)
        ]
        return cls(
            shop=str(data.get("shop") or ""),
            currency=str(data.get("currency") or "HKD"),
            paid_on=data.get("paid_on"),
            dispatch_on=data.get("dispatch_on"),
            delivered_on=data.get("delivered_on"),
            shipping=data.get("shipping"),
            merchandise=data.get("merchandise"),
            fee_amount=data.get("fee_amount"),
            fee_percent=data.get("fee_percent"),
            package_total=data.get("package_total"),
            lines=lines,
            raw_paste=str(data.get("raw_paste") or ""),
        )


def list_subtotal(lines: list[LotDraftLine]) -> Decimal:
    total = Decimal("0")
    for line in lines:
        if line.list_amount is not None:
            total += line.list_amount
    return total


def allocate_lot_payments(package: LotDraftPackage) -> LotDraftPackage:
    """Weight-allocate merchandise across lines by list_price; keep stickers."""
    lines = list(package.lines)
    merchandise = package.merchandise
    if merchandise is None and package.package_total is not None:
        shipping = package.shipping or Decimal("0")
        fee = package.fee_amount or Decimal("0")
        merchandise = package.package_total - shipping - fee
        if merchandise < 0:
            merchandise = Decimal("0")
    if merchandise is None:
        merchandise = list_subtotal(lines)
    weights = [line.list_amount or Decimal("0") for line in lines]
    weight_sum = sum(weights)
    allocated: list[LotDraftLine] = []
    remaining = merchandise
    for index, line in enumerate(lines):
        if weight_sum > 0 and line.list_amount is not None:
            share = (merchandise * line.list_amount / weight_sum).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        elif lines:
            share = (merchandise / Decimal(len(lines))).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            share = None
        if index == len(lines) - 1 and share is not None:
            share = remaining
        if share is not None:
            remaining -= share
        note_parts = []
        if line.list_amount is not None:
            note_parts.append(f"List {line.list_amount} {package.currency}")
        if share is not None:
            note_parts.append(f"Allocated {share} {package.currency}")
        # Fee and shipping are package-fixed — same lines on every copy.
        if package.fee_amount is not None:
            note_parts.append(
                f"Package fee {package.fee_amount} {package.currency}"
            )
        if package.fee_percent is not None:
            note_parts.append(f"Package fee {package.fee_percent}%")
        if package.shipping is not None:
            note_parts.append(
                f"Shipping {package.shipping} {package.currency} "
                f"(package, fixed)"
            )
        if package.dispatch_on is not None:
            note_parts.append(f"Dispatch {package.dispatch_on.isoformat()}")
        billing = "\n".join(note_parts)
        # Drop prior allocation/shipping noise when re-allocating; keep
        # free-form collector notes that are not generated markers.
        prior = str(line.billing_note or "")
        kept_extra = [
            row
            for row in prior.splitlines()
            if row.strip()
            and not row.startswith("List ")
            and not row.startswith("Allocated ")
            and not row.startswith("Package fee ")
            and not row.startswith("Shipping ")
            and not row.startswith("Dispatch ")
            and not row.startswith("USD rate ")
        ]
        if kept_extra:
            billing = f"{billing}\n" + "\n".join(kept_extra)
        allocated.append(
            replace(
                line,
                paid_amount=share,
                billing_note=billing.strip(),
            )
        )
    package_total = package.package_total
    if package_total is None:
        total = merchandise + (package.shipping or Decimal("0")) + (
            package.fee_amount or Decimal("0")
        )
        package_total = total
    return replace(
        package,
        merchandise=merchandise,
        package_total=package_total,
        lines=allocated,
    )


def _parse_item_line(text: str, *, index: int) -> LotDraftLine | None:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return None
    match = _LINE.match(cleaned)
    if match:
        sku, title, condition, price_raw = match.groups()
        title_text = title.strip()
        # Strip trailing condition words that the loose title captured.
        title_text = re.sub(
            r"\s+(近?\d{1,3}成新|全新)\s*$",
            "",
            title_text,
        ).strip()
        condition_text = (condition or "").strip()
        if not condition_text:
            found = _CONDITION.search(cleaned)
            condition_text = found.group(1) if found else ""
        grade = hk_condition_to_grade(condition_text)
        amount = _money(price_raw)
        return LotDraftLine(
            line_id=f"lot-{index}-{sku}",
            seller_sku=sku.strip(),
            catalog_number=sku.strip(),
            title=title_text,
            list_amount=amount,
            condition_hint=condition_text,
            condition_media=grade or "",
            condition_cover=grade or "",
            added=True,
        )
    loose = _LINE_LOOSE.match(cleaned)
    if not loose:
        return None
    sku, rest = loose.groups()
    money = _MONEY.findall(rest)
    if not money:
        return None
    amount = _money(money[-1])
    condition_match = _CONDITION.search(rest)
    condition_text = condition_match.group(1) if condition_match else ""
    title_text = rest
    if condition_match:
        title_text = title_text[: condition_match.start()] + title_text[
            condition_match.end() :
        ]
    title_text = _MONEY.sub("", title_text)
    title_text = re.sub(r"\s+", " ", title_text).strip(" ,，")
    grade = hk_condition_to_grade(condition_text)
    return LotDraftLine(
        line_id=f"lot-{index}-{sku}",
        seller_sku=sku.strip(),
        catalog_number=sku.strip(),
        title=title_text,
        list_amount=amount,
        condition_hint=condition_text,
        condition_media=grade or "",
        condition_cover=grade or "",
        added=True,
    )


def parse_informal_seller_list(
    raw: str,
    *,
    currency: str = "HKD",
    shop: str = "",
) -> LotDraftPackage:
    """Parse an HK-style chat list into a lot draft (not yet allocated)."""
    text = raw.lstrip("\ufeff").strip()
    package = LotDraftPackage(
        shop=shop.strip() or "Seller list",
        currency=(currency or "HKD").strip().upper() or "HKD",
        raw_paste=text,
    )
    if not text:
        return package
    lines: list[LotDraftLine] = []
    for index, row in enumerate(text.splitlines(), start=1):
        row = row.strip()
        if not row:
            continue
        ship = _SHIPPING.search(row)
        if ship and not _LINE_LOOSE.match(row):
            package.shipping = _money(ship.group(1))
            continue
        negotiated = _NEGOTIATED.search(row.replace(",", ""))
        if negotiated:
            merchandise = _money(negotiated.group(1))
            percent = _money(negotiated.group(2))
            total = _money(negotiated.group(3))
            package.merchandise = merchandise
            package.fee_percent = percent
            if merchandise is not None and percent is not None:
                package.fee_amount = (
                    merchandise * percent / Decimal("100")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            package.package_total = total
            continue
        if re.fullmatch(
            r"(?:運費|shipping|postage).+",
            row,
            flags=re.IGNORECASE,
        ):
            money = _MONEY.findall(row)
            if money:
                package.shipping = _money(money[-1])
            continue
        item = _parse_item_line(row, index=index)
        if item is not None:
            lines.append(item)
    package.lines = lines
    if package.merchandise is None and package.package_total is not None:
        shipping = package.shipping or Decimal("0")
        package.merchandise = package.package_total - shipping
    return allocate_lot_payments(package)


def looks_like_informal_seller_list(raw: str) -> bool:
    """True when paste looks like a multi-line HK seller chat list."""
    text = raw.strip()
    if not text:
        return False
    first = text.splitlines()[0]
    if "," in first and "Where" in first:
        return False
    hits = 0
    for row in text.splitlines():
        row = row.strip()
        if not row:
            continue
        if _SHIPPING.search(row) or _NEGOTIATED.search(row.replace(",", "")):
            return True
        if _CONDITION.search(row) and _MONEY.search(row):
            hits += 1
        elif _LINE_LOOSE.match(row) and _MONEY.search(row):
            hits += 1
    return hits >= 2


def anatomy_values_from_lot_line(line: LotDraftLine) -> dict[str, Any]:
    """Collector Review anatomy fields from a draft line (for Confirm)."""

    def _grade(raw: str) -> str | None:
        text = str(raw or "").strip()
        if not text or text == "Automatic / unset":
            return None
        return text

    def _tri(raw: str) -> bool | None:
        text = str(raw or "").strip()
        if text == "Yes":
            return True
        if text in {"No", "Missing"}:
            return False
        return None

    values: dict[str, Any] = {}
    catalog = str(line.catalog_number or "").strip()
    if catalog:
        values["manual_catalog_number"] = catalog
    region = str(line.region or "").strip()
    if region and region != "Automatic / unset":
        values["manual_region"] = region
    if line.disc_count and int(line.disc_count) > 0:
        values["manual_disc_count"] = int(line.disc_count)
    pressing = str(line.pressing_type or "").strip()
    if pressing and pressing != "Automatic / unset":
        values["manual_pressing_type"] = pressing
    media = str(line.media_type or "").strip()
    if media and media != "Automatic / unset":
        values["manual_media_type"] = media
    media_grade = _grade(line.condition_media)
    if media_grade:
        values["manual_condition_media"] = media_grade
    cover_grade = _grade(line.condition_cover)
    if cover_grade:
        values["manual_condition_cover"] = cover_grade
    verdict = str(line.verdict or "").strip()
    if verdict and verdict != "Automatic / unset":
        values["manual_verdict"] = verdict
    insert = str(line.insert_choice or "").strip()
    if insert and insert != "Automatic / unset":
        if insert == "Yes":
            values["manual_insert_present"] = True
        elif insert in {"No", "Factory no insert"} or insert.casefold().startswith(
            "missing"
        ):
            values["manual_insert_present"] = False
            if insert != "No":
                values["manual_completeness_notes"] = insert
        else:
            # Review LP pack labels (Insert only, pin-up as the insert…).
            values["manual_insert_present"] = True
            values["manual_completeness_notes"] = insert
    poster = _tri(line.poster_choice)
    if poster is not None:
        values["manual_poster_present"] = poster
    obi = _tri(line.obi_choice)
    if obi is not None:
        values["manual_obi"] = obi
    sealed = _tri(line.sealed_choice)
    if sealed is not None:
        values["manual_sealed"] = sealed
    rental = _tri(line.rental_choice)
    if rental is not None:
        values["manual_rental"] = rental
    notes = str(line.completeness_notes or "").strip()
    if notes and "manual_completeness_notes" not in values:
        values["manual_completeness_notes"] = notes
    collector = str(line.collector_notes or "").strip()
    if collector:
        values["manual_collector_notes"] = collector
    return values


def package_readout(package: LotDraftPackage) -> dict[str, Decimal | None]:
    """Live totals for the lot wizard header."""

    allocated = allocate_lot_payments(package)
    return {
        "list_subtotal": list_subtotal(allocated.lines),
        "shipping": allocated.shipping,
        "fee": allocated.fee_amount,
        "merchandise": allocated.merchandise,
        "package_total": allocated.package_total,
    }
