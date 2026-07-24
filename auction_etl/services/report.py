from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from auction_etl.services.export import load_rows


BUyee_TAX_RATE = Decimal("0.10")
EBAY_TAX_RATE = Decimal("0.0625")


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None

    return Decimal(str(value))


def _money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None

    return value.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _apply_ebay_tax(
    row: dict[str, Any],
    tax_rate: Decimal,
) -> None:
    hammer = _decimal(
        row.get("hammer_price_local")
    )

    if hammer is None:
        return

    tax = _money(
        hammer * tax_rate
    )
    gross = _money(
        hammer + tax
    )

    fx_rate = (
        _decimal(
            row.get("fx_rate_to_usd")
        )
        or Decimal("1")
    )

    row["tax_rate"] = tax_rate
    row["tax_amount_local"] = tax
    row["gross_price_local"] = gross
    row["price_includes_tax"] = False

    row["final_price_usd"] = _money(
        hammer * fx_rate
    )
    row["tax_usd"] = _money(
        tax * fx_rate
    )
    row["total_usd"] = _money(
        gross * fx_rate
    )


def _remove_shipping(
    row: dict[str, Any],
) -> None:
    row["shipping_price"] = None
    row["shipping_usd"] = None
    row["landed_usd"] = row.get(
        "total_usd"
    )


def load_report_rows(
    session: Session,
    *,
    marketplace: str | None = None,
    seller: str | None = None,
    exclude_bulk: bool = False,
    completed_only: bool = False,
    apply_ebay_tax: bool = True,
    ebay_tax_rate: Decimal = EBAY_TAX_RATE,
    include_shipping: bool = False,
    live_fx: bool = True,
    jpy_usd_rate: Decimal | None = None,
) -> list[dict[str, Any]]:
    rows = load_rows(
        session,
        marketplace=marketplace,
        live_fx=live_fx,
        jpy_usd_rate=jpy_usd_rate,
    )

    filtered: list[dict[str, Any]] = []

    for source_row in rows:
        row = dict(source_row)

        if seller:
            seller_value = str(
                row.get("seller") or ""
            ).casefold()

            if seller.casefold() not in seller_value:
                continue

        if exclude_bulk and bool(
            row.get("bulk_lot")
        ):
            continue

        if completed_only and not row.get(
            "ended_at"
        ):
            continue

        if (
            row.get("marketplace") == "ebay"
            and apply_ebay_tax
        ):
            _apply_ebay_tax(
                row,
                ebay_tax_rate,
            )

        if not include_shipping:
            _remove_shipping(row)

        filtered.append(row)

    return filtered
