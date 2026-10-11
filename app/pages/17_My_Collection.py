"""Bring purchases in, then see what the shelf still lacks."""

from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import text

import app.navigation as app_navigation
import auction_etl.services.collection_import as collection_import
import auction_etl.services.collection_shelf as collection_shelf
import auction_etl.services.fx as fx
from auction_etl.auth.streamlit_auth import (
    render_account_menu,
    require_authenticated_account,
)
from auction_etl.database.session import engine
from auction_etl.services.discogs_client import (
    DiscogsClient,
    DiscogsRateLimitError,
    DiscogsUnavailableError,
)
from auction_etl.services.discogs_identity import english_album_title
from auction_etl.services.tracked_listing_scope import (
    enabled_tracked_artist_names,
    listing_belongs_to_tracked_artists,
)

importlib.reload(collection_import)
importlib.reload(collection_shelf)
importlib.reload(fx)
importlib.reload(app_navigation)

rate_on = fx.rate_on

ParsedPurchase = collection_import.ParsedPurchase
parse_purchase_export = collection_import.parse_purchase_export
extract_pdf_text = collection_import.extract_pdf_text
parse_logged_table = collection_import.parse_logged_table
logged_purchase = collection_import.logged_purchase
ParseResult = collection_import.ParseResult
copy_costs = collection_import.copy_costs
copy_cost_currency = collection_import.copy_cost_currency
bill_usd_rate = collection_import.bill_usd_rate
to_usd = collection_import.to_usd
note_with_copy_costs = collection_import.note_with_copy_costs
note_with_printed_usd_rate = collection_import.note_with_printed_usd_rate
yen_rate_anchor = collection_import.yen_rate_anchor
fill_record_city_catalogs = collection_import.fill_record_city_catalogs
classify_purchases = collection_shelf.classify_purchases
ensure_owned_copy_table = collection_shelf.ensure_owned_copy_table
mark_listing_purchased = collection_shelf.mark_listing_purchased
save_billing_note = collection_shelf.save_billing_note
save_owned_copy = collection_shelf.save_owned_copy
search_visible_sales = collection_shelf.search_visible_sales
render_navigation = app_navigation.render_navigation


st.set_page_config(
    page_title="My collection",
    page_icon="💿",
    layout="wide",
)
render_navigation(current_page="pages/17_My_Collection.py")

_CURRENCIES = ("USD", "JPY", "EUR", "GBP", "HKD", "SEK")


def query_dataframe(
    statement: str,
    parameters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Execute a read-only database query."""
    with engine.connect() as connection:
        return pd.read_sql_query(
            text(statement),
            connection,
            params=parameters or {},
        )


def _tracked_artist(artist: object, title: object, names: tuple[str, ...]) -> str:
    for name in names:
        if listing_belongs_to_tracked_artists(
            title=title,
            artist=artist,
            tracked_names=(name,),
        ):
            return name
    return ""


@st.cache_data(ttl=120)
def load_collected(account_id: str) -> pd.DataFrame:
    """Listings this account marked in the collection."""
    return query_dataframe(
        """
        SELECT
            sale.marketplace::text AS marketplace,
            sale.listing_id::text AS listing_id,
            sale.seller,
            sale.auction_url,
            COALESCE(family.display_artist, sale.effective_artist) AS artist_name,
            family.display_title AS album_title,
            sale.effective_catalog_number AS catalog_number,
            COALESCE(
                NULLIF(BTRIM(sale.discogs_thumb_url), ''),
                NULLIF(BTRIM(sale.image_url), '')
            ) AS cover_url,
            owned.manual_purchase_price AS paid,
            owned.manual_purchase_currency AS paid_currency,
            owned.manual_purchase_date AS paid_on,
            owned.manual_purchase_notes AS billing_note
        FROM warehouse.auction_collector owned
        JOIN warehouse.auction_collector_effective sale
          ON sale.marketplace::text = owned.marketplace::text
         AND sale.listing_id::text = owned.listing_id::text
        LEFT JOIN warehouse.pressing_identity pressing
          ON pressing.id = sale.pressing_id
        LEFT JOIN warehouse.release_family family
          ON family.id = pressing.release_family_id
        WHERE owned.account_id = CAST(:account_id AS uuid)
          AND owned.manual_purchased IS TRUE
        ORDER BY owned.manual_purchase_date DESC NULLS LAST,
                 sale.effective_catalog_number
        """,
        {"account_id": account_id},
    )


@st.cache_data(ttl=120)
def load_owned(account_id: str) -> pd.DataFrame:
    """Shop orders saved without a scraped marketplace listing."""
    return query_dataframe(
        """
        SELECT
            owned.source AS marketplace,
            owned.external_id AS listing_id,
            owned.seller,
            NULL::text AS auction_url,
            COALESCE(family.display_artist, '') AS artist_name,
            COALESCE(family.display_title, owned.title) AS album_title,
            COALESCE(pressing.catalog_number, owned.catalog_number) AS catalog_number,
            cover.cover_url,
            owned.paid_amount AS paid,
            owned.paid_currency,
            owned.paid_on,
            owned.billing_note
        FROM warehouse.owned_copy owned
        LEFT JOIN warehouse.pressing_identity pressing
          ON pressing.id = owned.pressing_id
        LEFT JOIN warehouse.release_family family
          ON family.id = pressing.release_family_id
        LEFT JOIN LATERAL (
            SELECT COALESCE(
                NULLIF(BTRIM(sale.discogs_thumb_url), ''),
                NULLIF(BTRIM(sale.image_url), '')
            ) AS cover_url
            FROM warehouse.auction_collector_effective sale
            WHERE sale.effective_catalog_number =
                  COALESCE(pressing.catalog_number, owned.catalog_number)
            LIMIT 1
        ) cover ON TRUE
        WHERE owned.account_id = CAST(:account_id AS uuid)
        ORDER BY owned.paid_on DESC NULLS LAST, owned.catalog_number
        """,
        {"account_id": account_id},
    )


@st.cache_data(ttl=120)
def load_pressings() -> pd.DataFrame:
    """One row per catalog that has a completed sale."""
    return query_dataframe(
        """
        SELECT DISTINCT ON (sale.effective_catalog_number)
            sale.effective_catalog_number AS catalog_number,
            COALESCE(family.display_artist, sale.effective_artist) AS artist_name,
            family.display_title AS album_title,
            COALESCE(
                pressing.release_year,
                family.original_release_year
            ) AS release_year,
            COALESCE(
                NULLIF(BTRIM(sale.discogs_thumb_url), ''),
                NULLIF(BTRIM(sale.image_url), '')
            ) AS cover_url
        FROM warehouse.auction_collector_effective sale
        LEFT JOIN warehouse.pressing_identity pressing
          ON pressing.id = sale.pressing_id
        LEFT JOIN warehouse.release_family family
          ON family.id = pressing.release_family_id
        WHERE sale.gross_price IS NOT NULL
          AND sale.effective_catalog_number IS NOT NULL
          AND BTRIM(sale.effective_catalog_number) <> ''
        ORDER BY sale.effective_catalog_number,
                 pressing.release_year NULLS LAST
        """
    )


def _money(amount: object, currency: object) -> str:
    if amount is None or pd.isna(amount):
        return ""
    code = str(currency or "USD").upper()
    number = float(amount)
    if code == "JPY":
        return f"¥{number:,.0f}"
    if code == "USD":
        return f"${number:,.2f}"
    return f"{number:,.2f} {code}"


def _record_label(artist: object, title: object, catalog: object) -> str:
    return " · ".join(
        part
        for part in (
            str(artist or "").strip(),
            english_album_title(title) or str(title or "").strip(),
            str(catalog or "").strip(),
        )
        if part
    )


def _paid_on_date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return date.today()
    return parsed.date()


def _amount(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _currency_index(code: str) -> int:
    try:
        return _CURRENCIES.index(code.upper())
    except ValueError:
        return 0


def _refresh_shelf() -> None:
    st.session_state.pop("collection-log-pending", None)
    load_collected.clear()
    load_owned.clear()
    st.rerun()


def _sum_amounts(*values: Decimal | None) -> Decimal | None:
    total: Decimal | None = None
    for value in values:
        if value is None:
            continue
        total = value if total is None else total + value
    return total


def _shelf_costs(note: object, paid_currency: object) -> dict[str, object]:
    if note is None or (not isinstance(note, str) and pd.isna(note)):
        text = ""
    else:
        text = str(note)
    costs = copy_costs(text)
    item_code = str(paid_currency or "USD").upper()
    return {
        "note": text,
        "shipping": _sum_amounts(costs["shipping"], costs["domestic_shipping"]),
        "tax": _sum_amounts(costs["tax"], costs["customs"]),
        "fees": _sum_amounts(
            costs["plan_fee"],
            costs["service_fee"],
            costs["clearance"],
        ),
        "charge_currency": (copy_cost_currency(text) or item_code).upper(),
    }


@st.cache_data(ttl=60 * 60 * 12)
def load_usd_rate(currency: str, on_iso: str) -> str | None:
    """Dollars per one unit of ``currency`` on that date, from the ECB rate."""

    try:
        quote = rate_on(currency, date.fromisoformat(on_iso))
    except RuntimeError:
        return None
    return format(quote.rate, "f")


def _usd_per_unit(currency: str, note: str, paid_on: date | None) -> Decimal | None:
    code = str(currency or "USD").upper()
    if code == "USD":
        return Decimal("1")
    printed = bill_usd_rate(note)
    if printed is not None and printed[0] == code:
        return printed[1]
    raw = load_usd_rate(code, (paid_on or date.today()).isoformat())
    if raw is None:
        return None
    return Decimal(raw)


def _with_usd(amount: object, currency: object, usd: Decimal | None) -> str:
    label = _money(amount, currency)
    if not label or str(currency or "USD").upper() == "USD" or usd is None:
        return label
    return f"{label} ({_money(usd, 'USD')})"


def _landed_label(
    parts: tuple[tuple[Decimal | None, str, Decimal | None], ...],
) -> str:
    """US dollar total. A charge without a rate stays visible in its own currency."""

    dollars: Decimal | None = None
    missing: list[str] = []
    for amount, currency, rate in parts:
        if amount is None:
            continue
        if rate is None:
            missing.append(_money(amount, currency))
            continue
        converted = to_usd(amount, rate)
        dollars = converted if dollars is None else dollars + converted
    label = _money(dollars, "USD")
    if not missing:
        return label
    extra = " + ".join(missing)
    return f"{label} + {extra}" if label else extra


def _show_collected(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("Nothing is on the shelf yet. Bring in a purchase above, or add one copy.")
        return
    table = frame.copy()
    table["record"] = [
        _record_label(artist, title, catalog)
        for artist, title, catalog in zip(
            table["artist_name"],
            table["album_title"],
            table["catalog_number"],
            strict=True,
        )
    ]
    notes = (
        table["billing_note"]
        if "billing_note" in table.columns
        else pd.Series([""] * len(table), index=table.index)
    )
    shipping, tax, fees, landed, paid_labels = [], [], [], [], []
    paid_on_values = table["paid_on"]
    for amount, code, note, paid_on in zip(
        table["paid"],
        table["paid_currency"],
        notes,
        paid_on_values,
        strict=True,
    ):
        parts = _shelf_costs(note, code)
        item_code = str(code or "USD").upper()
        charge_code = str(parts["charge_currency"])
        paid_on_date = _paid_on_date(paid_on)
        note_text = str(parts["note"])
        item_rate = _usd_per_unit(item_code, note_text, paid_on_date)
        charge_rate = _usd_per_unit(charge_code, note_text, paid_on_date)
        item_amount = _editor_decimal(amount)
        item_usd = to_usd(item_amount, item_rate) if item_amount is not None and item_rate else None
        ship_usd = (
            to_usd(parts["shipping"], charge_rate)
            if parts["shipping"] is not None and charge_rate is not None
            else None
        )
        tax_usd = (
            to_usd(parts["tax"], charge_rate)
            if parts["tax"] is not None and charge_rate is not None
            else None
        )
        fee_usd = (
            to_usd(parts["fees"], charge_rate)
            if parts["fees"] is not None and charge_rate is not None
            else None
        )
        paid_labels.append(_with_usd(amount, item_code, item_usd))
        shipping.append(_with_usd(parts["shipping"], charge_code, ship_usd))
        tax.append(_with_usd(parts["tax"], charge_code, tax_usd))
        fees.append(_with_usd(parts["fees"], charge_code, fee_usd))
        landed.append(
            _landed_label(
                (
                    (item_amount, item_code, item_rate),
                    (parts["shipping"], charge_code, charge_rate),
                    (parts["tax"], charge_code, charge_rate),
                    (parts["fees"], charge_code, charge_rate),
                )
            )
        )
    table["paid_label"] = paid_labels
    table["shipping_label"] = shipping
    table["tax_label"] = tax
    table["fees_label"] = fees
    table["landed_label"] = landed
    table["paid_on"] = pd.to_datetime(table["paid_on"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    st.caption(
        "Item is the record price. Landed is in US dollars. "
        "A yen or other foreign charge stays visible and is converted into that dollar total. "
        "Use Fill in the breakdown under this table. The item price stays as it is."
    )
    st.dataframe(
        table[
            [
                "cover_url",
                "record",
                "paid_label",
                "shipping_label",
                "tax_label",
                "fees_label",
                "landed_label",
                "paid_on",
                "seller",
                "marketplace",
                "auction_url",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "cover_url": st.column_config.ImageColumn("Cover", width="small"),
            "record": st.column_config.TextColumn("Record", width="large"),
            "paid_label": st.column_config.TextColumn("Item"),
            "shipping_label": st.column_config.TextColumn("Shipping"),
            "tax_label": st.column_config.TextColumn("Tax"),
            "fees_label": st.column_config.TextColumn("Fees"),
            "landed_label": st.column_config.TextColumn("Landed"),
            "paid_on": st.column_config.TextColumn("Paid on"),
            "seller": st.column_config.TextColumn("Seller"),
            "marketplace": st.column_config.TextColumn("From"),
            "auction_url": st.column_config.LinkColumn("Listing", display_text="Open"),
        },
    )


def _show_missing(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("Every tracked record with a sale is already on the shelf.")
        return
    table = frame.copy()
    table["record"] = [
        " · ".join(
            part
            for part in (
                str(int(year)) if pd.notna(year) else "",
                str(artist or "").strip(),
                english_album_title(title) or str(title or "").strip(),
                str(catalog or "").strip(),
            )
            if part
        )
        for year, artist, title, catalog in zip(
            table["release_year"],
            table["tracked_artist"],
            table["album_title"],
            table["catalog_number"],
            strict=True,
        )
    ]
    st.dataframe(
        table[["cover_url", "record"]],
        hide_index=True,
        width="stretch",
        column_config={
            "cover_url": st.column_config.ImageColumn("Cover", width="small"),
            "record": st.column_config.TextColumn("Record", width="large"),
        },
    )


def _bytes_to_bill_text(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return extract_pdf_text(data)
    return data.decode("utf-8", errors="replace")


def _read_dropped_page() -> str:
    uploaded = st.file_uploader(
        "Drag and drop the saved order page or Buyee invoice PDF",
        type=["pdf", "html", "htm", "csv", "txt"],
        help=(
            "Drag and drop a Buyee invoice PDF, or save eBay purchase history "
            "or a Record City order page."
        ),
        key="collection-import-file",
    )
    pasted = st.text_area(
        "Or paste the order table",
        height=120,
        placeholder="Paste the orders here if you copied them instead of saving the page.",
        key="collection-import-paste",
    )
    if uploaded is not None:
        try:
            return _bytes_to_bill_text(uploaded.getvalue())
        except ValueError as exc:
            st.error(str(exc))
            return ""
    return pasted


def _save_match(
    *,
    account_id: str,
    user_id: str,
    purchase: ParsedPurchase,
    marketplace: str,
    listing_id: str,
    catalog_number: str,
    pressing_id: int | None,
    paid_amount: Decimal | None,
    paid_currency: str,
    paid_on: date | None,
) -> None:
    if marketplace and listing_id:
        mark_listing_purchased(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
            paid_amount=paid_amount,
            paid_currency=paid_currency,
            paid_on=paid_on,
            billing_note=purchase.billing_note,
        )
        return
    save_owned_copy(
        engine,
        account_id=account_id,
        purchase=purchase,
        catalog_number=catalog_number,
        pressing_id=pressing_id,
        paid_amount=paid_amount,
        paid_currency=paid_currency,
        paid_on=paid_on,
    )


def _record_city_with_discogs(parsed):
    """Offer a Discogs catalog lookup for Record City titles only."""

    if parsed.source != "recordcity" or not parsed.purchases:
        return parsed
    if all(row.catalog_number for row in parsed.purchases):
        return parsed
    token = "|".join(row.external_id for row in parsed.purchases)
    cached = st.session_state.get("collection-recordcity-rows")
    if st.session_state.get("collection-recordcity-token") == token and cached:
        return parsed.__class__(
            source=parsed.source,
            purchases=tuple(cached),
            note=parsed.note,
        )
    st.caption(
        "Record City spells titles its own way. "
        "The lookup searches the Discogs title for that spelling, "
        "and fills a catalog when one release matches. "
        "A title with more than one catalog stays blank."
    )
    if not st.button(
        "Look up catalogs on Discogs",
        key="collection-recordcity-discogs",
    ):
        return parsed

    client = DiscogsClient()

    def search(title: str, format_name: str):
        return client.search_releases(
            title=title,
            format_name=format_name,
            page_limit=1,
        )

    try:
        filled = fill_record_city_catalogs(parsed.purchases, search)
    except (DiscogsRateLimitError, DiscogsUnavailableError) as exc:
        st.error(str(exc))
        return parsed
    st.session_state["collection-recordcity-token"] = token
    st.session_state["collection-recordcity-rows"] = filled
    st.rerun()
    return parsed


def _render_import(account_id: str, user_id: str) -> None:
    st.caption(
        "Save eBay purchase history or the eBay order details, a Buyee invoice PDF, "
        "a Discogs order, or Record City history, and drag it onto the box below. "
        "The item price, date, seller, and catalog are filled in. "
        "The bill keeps the charges and leaves out names and addresses. "
        "Magazines, photos, posters, and pins are left out."
    )
    raw = _read_dropped_page()
    parsed = parse_purchase_export(raw)
    parsed = _record_city_with_discogs(parsed)
    if parsed.note:
        st.info(parsed.note)
        return
    if not parsed.purchases:
        return

    _review_purchases(account_id, user_id, parsed, key_prefix="collection-import")


def _batch_editor(ready: list, key_prefix: str) -> pd.DataFrame:
    """One editable table for the whole extracted batch."""

    rows = []
    for match in ready:
        purchase = match.purchase
        costs = copy_costs(purchase.billing_note)
        pressing = match.pressings[0] if match.pressings else None
        rows.append(
            {
                "Keep": True,
                "Title": purchase.title,
                "Catalog": (
                    pressing.catalog_number
                    if pressing is not None
                    else (purchase.catalog_number or "")
                ),
                "Paid": (
                    float(purchase.paid_amount)
                    if purchase.paid_amount is not None
                    else None
                ),
                "Currency": purchase.paid_currency,
                "Paid on": (
                    purchase.paid_on.isoformat() if purchase.paid_on else ""
                ),
                "Shipping": _editor_number(costs["shipping"]),
                "Tax": _editor_number(costs["tax"]),
                "Plan fee": _editor_number(costs["plan_fee"]),
                "Service fee": _editor_number(costs["service_fee"]),
                "Domestic shipping": _editor_number(costs["domestic_shipping"]),
                "Bill": purchase.billing_note,
                "Seller": purchase.seller,
                "Id": purchase.external_id,
            }
        )
    return st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        num_rows="fixed",
        disabled=["Seller", "Id"],
        key=f"{key_prefix}-batch",
        column_config={
            "Keep": st.column_config.CheckboxColumn("Keep"),
            "Paid": st.column_config.NumberColumn("Item price"),
            "Shipping": st.column_config.NumberColumn("Shipping"),
            "Tax": st.column_config.NumberColumn("Tax"),
            "Plan fee": st.column_config.NumberColumn("Plan fee"),
            "Service fee": st.column_config.NumberColumn("Service fee"),
            "Domestic shipping": st.column_config.NumberColumn("Domestic shipping"),
            "Bill": st.column_config.TextColumn("Bill", width="large"),
        },
    )


def _purchase_from_edit(match, row: pd.Series):
    purchase = match.purchase
    pressing = match.pressings[0] if match.pressings else None
    catalog = str(row["Catalog"] or "").strip()
    title = str(row["Title"] or "").strip() or purchase.title
    paid_amount = _editor_decimal(row["Paid"])
    paid_on = _editor_date(row["Paid on"])
    currency = str(row["Currency"] or purchase.paid_currency or "").strip()
    edited = replace(
        purchase,
        title=title,
        catalog_number=catalog or None,
        paid_amount=paid_amount,
        paid_currency=currency or purchase.paid_currency,
        paid_on=paid_on,
        billing_note=note_with_copy_costs(
            str(row["Bill"] or ""),
            shipping=_editor_decimal(row["Shipping"]),
            tax=_editor_decimal(row["Tax"]),
            plan_fee=_editor_decimal(row["Plan fee"]),
            service_fee=_editor_decimal(row["Service fee"]),
            domestic_shipping=_editor_decimal(row["Domestic shipping"]),
            currency=currency or purchase.paid_currency,
        ),
    )
    original_catalog = (
        pressing.catalog_number
        if pressing is not None
        else (purchase.catalog_number or "")
    )
    if pressing is not None and catalog == original_catalog:
        return (
            edited,
            pressing.catalog_number,
            pressing.pressing_id,
            paid_amount,
            paid_on,
        )
    return edited, catalog, None, paid_amount, paid_on


def _editor_number(amount: Decimal | None) -> float | None:
    if amount is None:
        return None
    return float(amount)


def _editor_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _editor_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text == "NaT":
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _shelf_options(account_id: str) -> dict[str, dict[str, object]]:
    """Copies already on the shelf, labeled for a backfill choice."""

    options: dict[str, dict[str, object]] = {}
    for frame in (load_collected(account_id), load_owned(account_id)):
        if frame.empty:
            continue
        for row in frame.to_dict("records"):
            label = " · ".join(
                part
                for part in (
                    _record_label(
                        row.get("artist_name"),
                        row.get("album_title"),
                        row.get("catalog_number"),
                    ),
                    str(row.get("seller") or "").strip(),
                    _money(row.get("paid"), row.get("paid_currency")),
                )
                if part
            )
            if label in options:
                label = f"{label} · {row.get('listing_id')}"
            options[label] = row
    return options


def _breakdown_summary(purchase: ParsedPurchase) -> str:
    costs = copy_costs(purchase.billing_note)
    parts = []
    shipping = _sum_amounts(costs["shipping"], costs["domestic_shipping"])
    tax = _sum_amounts(costs["tax"], costs["customs"])
    fees = _sum_amounts(
        costs["plan_fee"],
        costs["service_fee"],
        costs["clearance"],
    )
    if shipping is not None:
        parts.append(f"Shipping {_money(shipping, purchase.paid_currency)}")
    if tax is not None:
        parts.append(f"Tax {_money(tax, purchase.paid_currency)}")
    if fees is not None:
        parts.append(f"Fees {_money(fees, purchase.paid_currency)}")
    return " · ".join(parts)


def _render_backfill(
    account_id: str,
    user_id: str,
    purchases: tuple,
    key_prefix: str,
) -> None:
    """Write a dropped bill onto a copy that is already on the shelf."""

    billed = [purchase for purchase in purchases if purchase.billing_note.strip()]
    options = _shelf_options(account_id)
    if not billed or not options:
        return
    st.subheader("Backfill a copy already on the shelf")
    st.caption(
        "Choose the bill and the copy. Shipping, tax, and fees are written on that copy. "
        "The item price stays as it is."
    )
    bill_labels: dict[str, ParsedPurchase] = {}
    for purchase in billed:
        label = " · ".join(
            part
            for part in (
                purchase.title or purchase.catalog_number or purchase.external_id,
                _breakdown_summary(purchase),
            )
            if part
        )
        if label in bill_labels:
            label = f"{label} · {purchase.external_id}"
        bill_labels[label] = purchase
    bill_choice = st.selectbox(
        "Bill",
        list(bill_labels),
        key=f"{key_prefix}-backfill-bill",
    )
    copy_choice = st.selectbox(
        "Copy on the shelf",
        list(options),
        key=f"{key_prefix}-backfill-copy",
    )
    if st.button(
        "Save this breakdown on that copy",
        key=f"{key_prefix}-backfill-save",
    ):
        purchase = bill_labels[bill_choice]
        row = options[copy_choice]
        catalog = str(row.get("catalog_number") or purchase.catalog_number or "")
        wrote = save_billing_note(
            engine,
            account_id=account_id,
            purchase=replace(
                purchase,
                catalog_number=catalog or None,
                billing_note=_bill_note_for_copy(purchase, row),
            ),
            marketplace=_shelf_text(row.get("marketplace")),
            listing_id=_shelf_text(row.get("listing_id")),
            user_id=user_id,
        )
        if wrote:
            _refresh_shelf()
            return
        st.error("Could not attach that bill to the selected copy.")


def _review_purchases(
    account_id: str,
    user_id: str,
    parsed,
    *,
    key_prefix: str,
) -> None:
    matches = classify_purchases(engine, account_id, parsed.purchases)
    ready = [match for match in matches if match.status in {"ready", "new_copy"}]
    picks = [match for match in matches if match.status == "pick"]
    left_out = [match for match in matches if match.status == "left_out"]
    already = [match for match in matches if match.status == "already"]
    source_label = {
        "ebay": "eBay",
        "buyee": "Buyee",
        "recordcity": "Record City",
        "discogs": "Discogs",
        "log": "Logged",
    }.get(parsed.source, parsed.source)

    st.subheader(f"{source_label}: {len(parsed.purchases)} purchases")
    if any("Package international shipping" in match.purchase.billing_note for match in ready):
        st.caption(
            "Plan fee, service fee, and domestic shipping are the amounts on that record. "
            "International shipping and customs are the whole Buyee package. "
            "The PDF repeats them on every row because it does not assign them to one record."
        )
    if ready:
        edited = _batch_editor(ready, key_prefix)
        if st.button(
            f"Add these {len(ready)} copies",
            type="primary",
            key=f"{key_prefix}-add-ready",
        ):
            for match in ready:
                row = edited.loc[edited["Id"] == match.purchase.external_id]
                if row.empty or not bool(row.iloc[0]["Keep"]):
                    continue
                purchase, catalog_number, pressing_id, paid_amount, paid_on = (
                    _purchase_from_edit(match, row.iloc[0])
                )
                _save_match(
                    account_id=account_id,
                    user_id=user_id,
                    purchase=purchase,
                    marketplace=match.marketplace,
                    listing_id=match.listing_id,
                    catalog_number=catalog_number,
                    pressing_id=pressing_id,
                    paid_amount=paid_amount,
                    paid_currency=purchase.paid_currency,
                    paid_on=paid_on,
                )
            _refresh_shelf()
    else:
        st.caption("Nothing new is ready to add from this page.")

    if already:
        st.caption(f"{len(already)} already on your shelf. The item price stays as it is.")
        billed = [match for match in already if match.purchase.billing_note.strip()]
        if billed:
            for match in billed:
                st.write(match.purchase.title or match.purchase.catalog_number)
                st.text(match.purchase.billing_note)
            if st.button(
                "Save these bills on the shelf",
                key=f"{key_prefix}-save-bills",
            ):
                for match in billed:
                    save_billing_note(
                        engine,
                        account_id=account_id,
                        purchase=match.purchase,
                        user_id=user_id,
                    )
                _refresh_shelf()
    _render_backfill(account_id, user_id, parsed.purchases, key_prefix)

    if picks:
        st.subheader(f"Needs a catalog ({len(picks)})")
        st.caption("These purchases did not match one pressing. Choose it, or type the catalog.")
        for match in picks:
            purchase = match.purchase
            with st.container(border=True):
                st.write(purchase.title or purchase.external_id)
                paid_key = f"collection-pick-paid:{purchase.external_id}"
                date_key = f"collection-pick-date:{purchase.external_id}"
                currency_key = f"collection-pick-currency:{purchase.external_id}"
                if paid_key not in st.session_state:
                    st.session_state[paid_key] = _amount(purchase.paid_amount)
                if date_key not in st.session_state:
                    st.session_state[date_key] = purchase.paid_on or date.today()
                if currency_key not in st.session_state:
                    st.session_state[currency_key] = (
                        purchase.paid_currency
                        if purchase.paid_currency in _CURRENCIES
                        else "USD"
                    )
                choice_column, paid_column, date_column, action_column = st.columns(
                    [3, 1, 1, 1]
                )
                pressing_id: int | None = None
                catalog_number = purchase.catalog_number or ""
                with choice_column:
                    if match.pressings:
                        labels = {
                            _record_label(
                                choice.artist_name,
                                choice.album_title,
                                choice.catalog_number,
                            ): choice
                            for choice in match.pressings
                        }
                        selected = st.selectbox(
                            "Pressing",
                            list(labels),
                            key=f"collection-pick-pressing:{purchase.external_id}",
                        )
                        chosen = labels[selected]
                        pressing_id = chosen.pressing_id
                        catalog_number = chosen.catalog_number
                    else:
                        catalog_key = f"collection-pick-catalog:{purchase.external_id}"
                        if catalog_key not in st.session_state:
                            st.session_state[catalog_key] = purchase.catalog_number or ""
                        catalog_number = st.text_input("Catalog", key=catalog_key)
                with paid_column:
                    paid_value = st.number_input("Paid", min_value=0.0, key=paid_key)
                with date_column:
                    paid_on = st.date_input("Paid on", key=date_key)
                with action_column:
                    st.write("")
                    add_pick = st.button(
                        "Add",
                        key=f"collection-pick-add:{purchase.external_id}",
                        disabled=not str(catalog_number).strip(),
                    )
                currency = st.session_state[currency_key]
                if add_pick:
                    _save_match(
                        account_id=account_id,
                        user_id=user_id,
                        purchase=purchase,
                        marketplace="",
                        listing_id="",
                        catalog_number=str(catalog_number).strip(),
                        pressing_id=pressing_id,
                        paid_amount=Decimal(str(paid_value)),
                        paid_currency=str(currency),
                        paid_on=paid_on,
                    )
                    _refresh_shelf()

    if left_out:
        with st.expander(f"Left out ({len(left_out)})"):
            st.dataframe(
                pd.DataFrame(
                    {
                        "Record": [match.purchase.title for match in left_out],
                        "Why": [match.reason for match in left_out],
                    }
                ),
                hide_index=True,
                width="stretch",
            )


def _render_log(account_id: str, user_id: str) -> None:
    """Ingest a copy when the order page is already gone."""

    st.caption(
        "Use this when the order page is gone. "
        "Type one copy, or paste a table with the same columns. "
        "The catalog and the title stay as you enter them."
    )
    notice = st.session_state.pop("collection-log-notice", "")
    saved = st.session_state.pop("collection-log-saved", "")
    if saved:
        st.success(f"Added {saved}.")
    if notice:
        st.info(notice)
    where = st.text_input(
        "Where it came from",
        placeholder="Shop, friend, or show",
        key="collection-log-from",
    )
    catalog = st.text_input(
        "Catalog",
        placeholder="LFLP-497",
        key="collection-log-catalog",
    )
    title = st.text_input(
        "Title",
        placeholder="Album name, if you have no catalog",
        key="collection-log-title",
    )
    paid_column, currency_column, date_column = st.columns(3)
    with paid_column:
        paid_value = st.number_input(
            "Paid",
            min_value=0.0,
            step=0.01,
            key="collection-log-paid",
        )
    with currency_column:
        currency = st.selectbox(
            "Currency",
            _CURRENCIES,
            key="collection-log-currency",
        )
    with date_column:
        paid_on = st.date_input("Paid on", key="collection-log-date")
    if st.button("Add this copy", type="primary", key="collection-log-add"):
        purchase = logged_purchase(
            where=where,
            catalog=catalog,
            title=title,
            paid=Decimal(f"{paid_value:.2f}") if paid_value else None,
            currency=str(currency),
            paid_on=paid_on,
        )
        if purchase is None:
            st.session_state["collection-log-notice"] = "Type a catalog or a title."
            st.rerun()
            return
        matches = classify_purchases(engine, account_id, [purchase])
        match = matches[0]
        if match.status in {"ready", "new_copy"}:
            pressing = match.pressings[0] if match.pressings else None
            _save_match(
                account_id=account_id,
                user_id=user_id,
                purchase=purchase,
                marketplace=match.marketplace,
                listing_id=match.listing_id,
                catalog_number=(
                    pressing.catalog_number
                    if pressing is not None
                    else (purchase.catalog_number or "")
                ),
                pressing_id=pressing.pressing_id if pressing is not None else None,
                paid_amount=purchase.paid_amount,
                paid_currency=purchase.paid_currency,
                paid_on=purchase.paid_on,
            )
            st.session_state["collection-log-saved"] = purchase.title
            _refresh_shelf()
        elif match.status == "already":
            st.session_state["collection-log-notice"] = "That copy is already on the shelf."
            st.rerun()
        elif match.status == "left_out":
            st.session_state["collection-log-notice"] = match.reason or "Not music."
            st.rerun()
        else:
            st.session_state["collection-log-pending"] = purchase
            st.rerun()
    pending = st.session_state.get("collection-log-pending")
    if pending is not None:
        _review_purchases(
            account_id,
            user_id,
            ParseResult(source="log", purchases=(pending,), note=""),
            key_prefix="collection-log-one",
        )
    st.subheader("Or paste a table")
    pasted = st.text_area(
        "Copies",
        height=140,
        placeholder=(
            "Where, Catalog, Title, Paid, Currency, Date\n"
            "Disc Union, LFLP-497, , 105.00, USD, 2026-09-15"
        ),
        key="collection-log-paste",
    )
    logged = parse_logged_table(pasted)
    if logged:
        _review_purchases(
            account_id,
            user_id,
            ParseResult(source="log", purchases=logged, note=""),
            key_prefix="collection-log-batch",
        )
    elif pasted.strip():
        st.info(
            "Start with a header row: Where, Catalog, Title, Paid, Currency, Date."
        )


def _render_add_one(account_id: str, user_id: str) -> None:
    st.caption(
        "Search the sales already stored, by catalog, title, artist, or seller. "
        "The price and date fill in from that sale. Change them if you paid something else."
    )
    query = st.text_input(
        "Find a sale",
        placeholder="LFLP-486, Ryan, or the album name",
        key="collection-add-search",
    )
    sales = search_visible_sales(engine, account_id, query)
    if len(query.strip()) >= 2 and not sales:
        st.info("No stored sale matches that search.")
        return
    if not sales:
        return
    labels = []
    by_label: dict[str, dict[str, Any]] = {}
    for sale in sales:
        label = " · ".join(
            part
            for part in (
                _record_label(sale.get("artist_name"), sale.get("title"), sale.get("catalog_number")),
                str(sale.get("seller") or "").strip(),
                str(sale.get("marketplace") or "").strip(),
                _money(sale.get("gross_price"), sale.get("currency")),
                str(sale.get("listing_id") or "").strip(),
            )
            if part
        )
        labels.append(label)
        by_label[label] = sale
    selected_label = st.selectbox(
        "Sale",
        labels,
        key=f"collection-add-choice:{query.strip()}",
    )
    selected = by_label[selected_label]
    identity = f"{selected['marketplace']}:{selected['listing_id']}"
    paid_key = f"collection-one-paid:{identity}"
    date_key = f"collection-one-date:{identity}"
    currency_key = f"collection-one-currency:{identity}"
    if paid_key not in st.session_state:
        st.session_state[paid_key] = _amount(
            Decimal(str(selected["gross_price"]))
            if selected.get("gross_price") is not None
            else None
        )
    if date_key not in st.session_state:
        st.session_state[date_key] = _as_date(selected.get("sold_on"))
    if currency_key not in st.session_state:
        code = str(selected.get("currency") or "USD").upper()
        st.session_state[currency_key] = code if code in _CURRENCIES else "USD"
    paid_column, currency_column, date_column = st.columns(3)
    with paid_column:
        paid_value = st.number_input("Paid", min_value=0.0, key=paid_key)
    with currency_column:
        currency = st.selectbox("Currency", _CURRENCIES, key=currency_key)
    with date_column:
        paid_on = st.date_input("Paid on", key=date_key)
    if st.button("Add this copy", type="primary", key="collection-add-one"):
        mark_listing_purchased(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=str(selected["marketplace"]),
            listing_id=str(selected["listing_id"]),
            paid_amount=Decimal(str(paid_value)),
            paid_currency=str(currency),
            paid_on=paid_on,
        )
        _refresh_shelf()


def _typed_charge(value: float) -> Decimal | None:
    if value <= 0:
        return None
    return Decimal(str(value))


def _shelf_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.casefold() in {"nan", "none"}:
        return ""
    return text


def _bill_note_for_copy(purchase: ParsedPurchase, row: dict[str, object]) -> str:
    """Keep yen lines and pair them with this copy's dollar item price."""

    note = purchase.billing_note.strip()
    paid = _editor_decimal(row.get("paid"))
    paid_currency = _shelf_text(row.get("paid_currency")).upper()
    yen = yen_rate_anchor(note)
    if paid is None or paid_currency != "USD" or yen is None:
        return note
    return note_with_printed_usd_rate(note, usd=paid, yen=yen)


def _render_shelf_fill(
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
) -> None:
    """Write a bill or typed charges onto a copy already on the shelf."""

    if frame.empty:
        return
    st.subheader("Fill in the breakdown")
    st.caption(
        "Pick a copy that is already here. Drop the Buyee invoice PDF, paste its bill, "
        "or type the charges in that copy’s currency. "
        "Charge lines only. The record title stays as it is. "
        "The item price stays as it is. Yen and other foreign charges stay visible, "
        "and landed adds their dollar value."
    )
    options: dict[str, dict[str, object]] = {}
    for row in frame.to_dict("records"):
        label = " · ".join(
            part
            for part in (
                _record_label(
                    row.get("artist_name"),
                    row.get("album_title"),
                    row.get("catalog_number"),
                ),
                str(row.get("seller") or "").strip(),
                _money(row.get("paid"), row.get("paid_currency")),
            )
            if part
        )
        if label in options:
            label = f"{label} · {row.get('listing_id')}"
        options[label] = row
    choice = st.selectbox(
        "Copy",
        list(options),
        key="collection-shelf-fill-copy",
    )
    row = options[choice]
    currency = str(row.get("paid_currency") or "USD").upper()
    if currency not in _CURRENCIES:
        currency = "USD"
    with st.container(border=True):
        st.markdown("**Drag and drop the Buyee invoice PDF here**, or browse.")
        uploaded = st.file_uploader(
            "Drop the Buyee invoice PDF",
            type=["pdf", "html", "htm", "csv", "txt"],
            accept_multiple_files=False,
            help="Drag the PDF onto this box. Yen amounts stay in yen; landed adds dollars.",
            key="collection-shelf-fill-file",
            label_visibility="collapsed",
        )
    pasted = st.text_area(
        "Or paste the bill",
        height=140,
        placeholder="Paste the Buyee invoice, the eBay order details, or the Discogs order.",
        key="collection-shelf-fill-bill",
    )
    raw = pasted
    if uploaded is not None:
        try:
            raw = _bytes_to_bill_text(uploaded.getvalue())
            st.session_state["collection-shelf-fill-raw"] = raw
        except ValueError as exc:
            st.error(str(exc))
            raw = ""
    elif not pasted.strip():
        raw = str(st.session_state.get("collection-shelf-fill-raw") or "")
    parsed = parse_purchase_export(raw) if raw.strip() else None
    billed = [
        purchase
        for purchase in (parsed.purchases if parsed is not None else ())
        if purchase.billing_note.strip()
    ]
    if billed:
        st.session_state["collection-shelf-fill-billed"] = billed
    elif uploaded is None and not pasted.strip():
        billed = list(st.session_state.get("collection-shelf-fill-billed") or [])
    if raw.strip() and not billed:
        st.info("That page did not include a shipping, tax, or fee line.")
    if billed:
        bill_labels: dict[str, ParsedPurchase] = {}
        for purchase in billed:
            label = " · ".join(
                part
                for part in (
                    purchase.external_id,
                    _breakdown_summary(purchase),
                )
                if part
            )
            if label in bill_labels:
                label = f"{label} · {purchase.external_id}"
            bill_labels[label] = purchase
        bill_choice = st.selectbox(
            "Bill",
            list(bill_labels),
            key="collection-shelf-fill-which",
        )
        st.caption(
            "Charge lines only. Yen stays yen. Dollars are the conversion, "
            "not a replacement. The record title stays as it is."
        )
        preview = _bill_note_for_copy(bill_labels[bill_choice], row)
        st.text(preview)
        if st.button(
            "Save this bill on this copy",
            type="primary",
            key="collection-shelf-fill-save-bill",
        ):
            purchase = bill_labels[bill_choice]
            catalog = _shelf_text(row.get("catalog_number")) or (
                purchase.catalog_number or ""
            )
            wrote = save_billing_note(
                engine,
                account_id=account_id,
                purchase=replace(
                    purchase,
                    catalog_number=catalog or None,
                    billing_note=preview,
                ),
                marketplace=_shelf_text(row.get("marketplace")),
                listing_id=_shelf_text(row.get("listing_id")),
                user_id=user_id,
            )
            if wrote:
                st.session_state.pop("collection-shelf-fill-raw", None)
                st.session_state.pop("collection-shelf-fill-billed", None)
                st.session_state["collection-shelf-fill-status"] = "saved"
                _refresh_shelf()
            else:
                st.error(
                    "Could not attach that bill to the selected copy. "
                    "The listing id on the shelf did not match a purchased row."
                )
    if st.session_state.pop("collection-shelf-fill-status", "") == "saved":
        st.success("Saved the yen charges on this copy. Landed adds their dollar value.")
    identity = (
        f"{_shelf_text(row.get('marketplace'))}:"
        f"{_shelf_text(row.get('listing_id'))}"
    )
    st.caption(f"Or type the charges in {currency}.")
    ship_col, tax_col, plan_col, service_col, domestic_col = st.columns(5)
    with ship_col:
        shipping = st.number_input(
            "Shipping",
            min_value=0.0,
            key=f"collection-shelf-fill-shipping:{identity}",
        )
    with tax_col:
        tax = st.number_input(
            "Tax",
            min_value=0.0,
            key=f"collection-shelf-fill-tax:{identity}",
        )
    with plan_col:
        plan_fee = st.number_input(
            "Plan fee",
            min_value=0.0,
            key=f"collection-shelf-fill-plan:{identity}",
        )
    with service_col:
        service_fee = st.number_input(
            "Service fee",
            min_value=0.0,
            key=f"collection-shelf-fill-service:{identity}",
        )
    with domestic_col:
        domestic = st.number_input(
            "Domestic shipping",
            min_value=0.0,
            key=f"collection-shelf-fill-domestic:{identity}",
        )
    if st.button(
        "Save these amounts on this copy",
        key="collection-shelf-fill-save-typed",
    ):
        note = note_with_copy_costs(
            "",
            shipping=_typed_charge(shipping),
            tax=_typed_charge(tax),
            plan_fee=_typed_charge(plan_fee),
            service_fee=_typed_charge(service_fee),
            domestic_shipping=_typed_charge(domestic),
            currency=currency,
        )
        if not note:
            st.info("Type a shipping, tax, or fee amount first.")
            return
        catalog = _shelf_text(row.get("catalog_number")) or None
        wrote = save_billing_note(
            engine,
            account_id=account_id,
            purchase=ParsedPurchase(
                source=_shelf_text(row.get("marketplace")) or "log",
                external_id=_shelf_text(row.get("listing_id")),
                title="",
                seller=_shelf_text(row.get("seller")),
                paid_amount=None,
                paid_currency=currency,
                paid_on=None,
                catalog_number=catalog,
                billing_note=note,
            ),
            marketplace=_shelf_text(row.get("marketplace")),
            listing_id=_shelf_text(row.get("listing_id")),
            user_id=user_id,
        )
        if wrote:
            _refresh_shelf()
            return
        st.error("Could not attach those amounts to the selected copy.")


def main() -> None:
    """Render the intake and the shelf."""
    account = require_authenticated_account(engine)
    render_account_menu(account)
    ensure_owned_copy_table(engine)
    st.title("My collection")
    st.caption(
        "Bring in a saved order page, or log a copy when that history is gone. "
        "Then see the tracked records that are still missing."
    )

    account_id = str(account.account_id)
    user_id = str(account.user_id)
    bring_in, log_copy, add_one = st.tabs(
        ("Bring in purchases", "Log a copy", "Add one copy")
    )
    with bring_in:
        _render_import(account_id, user_id)
    with log_copy:
        _render_log(account_id, user_id)
    with add_one:
        _render_add_one(account_id, user_id)

    st.divider()
    st.subheader("Your shelf")
    tracked = enabled_tracked_artist_names(engine, account_id=account_id)
    collected = load_collected(account_id)
    owned = load_owned(account_id)
    if not owned.empty:
        collected = (
            owned.copy()
            if collected.empty
            else pd.concat([collected, owned], ignore_index=True)
        )
    pressings = load_pressings()
    owned_catalogs = set()
    if not collected.empty:
        owned_catalogs = set(collected["catalog_number"].dropna().astype(str))

    if not pressings.empty:
        pressings = pressings.copy()
        pressings["tracked_artist"] = [
            _tracked_artist(artist, title, tracked)
            for artist, title in zip(
                pressings["artist_name"],
                pressings["album_title"],
                strict=True,
            )
        ]
        missing = pressings.loc[
            pressings["tracked_artist"].ne("")
            & ~pressings["catalog_number"].astype(str).isin(owned_catalogs)
        ].copy()
        missing["release_year"] = pd.to_numeric(
            missing["release_year"],
            errors="coerce",
        )
        missing = missing.sort_values(
            ["tracked_artist", "release_year", "catalog_number"],
            ascending=[True, True, True],
            na_position="last",
        )
    else:
        missing = pressings

    if tracked:
        artist = st.selectbox(
            "Artist",
            ("All tracked artists", *tracked),
            key="collection-shelf-artist",
        )
        if artist != "All tracked artists":
            if not collected.empty:
                collected = collected.loc[
                    [
                        _tracked_artist(artist_name, title, (artist,)) == artist
                        for artist_name, title in zip(
                            collected["artist_name"],
                            collected["album_title"],
                            strict=True,
                        )
                    ]
                ].copy()
            if not missing.empty:
                missing = missing.loc[missing["tracked_artist"].eq(artist)].copy()

    collected_tab, missing_tab = st.tabs(
        (
            f"Collected ({len(collected)})",
            f"Not yet ({len(missing)})",
        )
    )
    with collected_tab:
        _show_collected(collected)
        _render_shelf_fill(account_id, user_id, collected)
    with missing_tab:
        _show_missing(missing)


if __name__ == "__main__":
    main()
