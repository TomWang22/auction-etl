"""Bring purchases in, then see what the shelf still lacks."""

from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text
from st_aggrid import AgGrid, JsCode

import app.collector_review_support as collector_review_support
import app.navigation as app_navigation
import auction_etl.services.collection_acquisition as collection_acquisition
import auction_etl.services.collection_billing as collection_billing
import auction_etl.services.collection_import as collection_import
import auction_etl.services.collection_shelf as collection_shelf
import auction_etl.services.discogs_client as discogs_client
import auction_etl.services.discogs_fill as discogs_fill
import auction_etl.services.discogs_identity as discogs_identity
import auction_etl.services.fx as fx
from auction_etl.auth.streamlit_auth import (
    render_account_menu,
    require_authenticated_account,
)
from auction_etl.database.session import engine
from auction_etl.services.tracked_listing_scope import (
    enabled_tracked_artist_names,
    listing_belongs_to_tracked_artists,
)

def _reload_services_if_changed() -> None:
    """Reload service modules only when their files change.

    Reloading on every Streamlit run remounts widgets and AgGrid, which is
    what makes the shelf flash after a save. Keep identity before acquisition.
    """

    modules = (
        discogs_client,
        discogs_identity,
        discogs_fill,
        collection_acquisition,
        collection_billing,
        collection_import,
        collection_shelf,
        fx,
        collector_review_support,
        app_navigation,
    )
    stamp = 0.0
    for module in modules:
        path = getattr(module, "__file__", None)
        if not path:
            continue
        try:
            stamp = max(stamp, Path(path).stat().st_mtime)
        except OSError:
            continue
    cache = sys.modules.setdefault(
        "_auction_etl_collection_reload",
        {"stamp": 0.0},
    )
    if stamp and stamp <= float(cache.get("stamp") or 0.0):
        return
    for module in modules:
        importlib.reload(module)
    cache["stamp"] = stamp


_reload_services_if_changed()

rate_on = fx.rate_on
DiscogsClient = discogs_client.DiscogsClient
DiscogsRateLimitError = discogs_client.DiscogsRateLimitError
DiscogsUnavailableError = discogs_client.DiscogsUnavailableError
english_album_title = discogs_identity.english_album_title
fold_catalog = discogs_identity.fold_catalog
listing_identity_catalog = discogs_identity.listing_identity_catalog
search_user_catalog = discogs_identity.search_user_catalog
shortlist_field = discogs_identity.shortlist_field
apply_release_choice = discogs_fill.apply_release_choice

ParsedPurchase = collection_import.ParsedPurchase
parse_purchase_export = collection_import.parse_purchase_export
describe_lot = collection_import.describe_lot
lot_tally = collection_import.lot_tally
purchase_media = collection_import.purchase_media
parse_purchase_pages = collection_import.parse_purchase_pages
listing_title_is_chrome = collection_import.listing_title_is_chrome
listing_title_is_ocr_junk = collection_import.listing_title_is_ocr_junk
listing_catalog_is_structured = collection_import.listing_catalog_is_structured
ocr_promo_item_price = collection_import.ocr_promo_item_price
owned_copy_shows_on_shelf = collection_import.owned_copy_shows_on_shelf
bill_text_from_bytes = collection_import.bill_text_from_bytes
harvest_screenshot_bills = collection_import.harvest_screenshot_bills
is_screenshot_bytes = collection_import.is_screenshot_bytes
combine_bill_pages = collection_import.combine_bill_pages
anatomy_gaps = collection_billing.anatomy_gaps
billing_gaps = collection_billing.billing_gaps
COLLECTION_MEDIA_LABELS = collection_billing.COLLECTION_MEDIA_LABELS
collection_media_code = collection_billing.collection_media_code
collection_media_label = collection_billing.collection_media_label
collection_bulk_lot = collection_billing.collection_bulk_lot
media_asks_disc_count = collection_billing.media_asks_disc_count
effective_sale_type = collection_acquisition.effective_sale_type
sale_type_label = collection_acquisition.sale_type_label
shelf_copy_filled = collection_billing.shelf_copy_filled
acquisition_breakdown = collection_acquisition.acquisition_breakdown
ensure_collection_bill_tables = collection_billing.ensure_collection_bill_tables
preview_shelf_bills = collection_billing.preview_shelf_bills
extracted_delivered_on = collection_billing.extracted_delivered_on
next_unfilled_copy = collection_billing.next_unfilled_copy
closest_unfilled_copy = collection_billing.closest_unfilled_copy
order_copies_by_artist = collection_billing.order_copies_by_artist
bill_disagreements = collection_billing.bill_disagreements
copy_charge_layout = collection_billing.copy_charge_layout
parse_logged_table = collection_import.parse_logged_table
logged_purchase = collection_import.logged_purchase
ParseResult = collection_import.ParseResult
copy_costs = collection_import.copy_costs
copy_refund = collection_import.copy_refund
buyee_invoice_lines = collection_import.buyee_invoice_lines
buyee_package_display_lines = collection_import.buyee_package_display_lines
buyee_package_landed_extras = collection_import.buyee_package_landed_extras
hold_import_purchases = collection_import.hold_import_purchases
shelf_charge_amounts = collection_import.shelf_charge_amounts
copy_cost_currency = collection_import.copy_cost_currency
bill_usd_rate = collection_import.bill_usd_rate
to_usd = collection_import.to_usd
note_with_copy_costs = collection_import.note_with_copy_costs
arrange_lot_columns = collection_import.arrange_lot_columns
buyee_tax_included = collection_import.buyee_tax_included
note_with_included_tax = collection_import.note_with_included_tax
note_with_printed_usd_rate = collection_import.note_with_printed_usd_rate
yen_rate_anchor = collection_import.yen_rate_anchor
fill_record_city_catalogs = collection_import.fill_record_city_catalogs
classify_purchases = collection_shelf.classify_purchases
ensure_owned_copy_table = collection_shelf.ensure_owned_copy_table
mark_listing_purchased = collection_shelf.mark_listing_purchased
save_billing_note = collection_shelf.save_billing_note
save_package_bill = collection_shelf.save_package_bill
bill_copy_identity = collection_shelf.bill_copy_identity
save_copy_anatomy = collection_shelf.save_copy_anatomy
ensure_anatomy_copy = collection_shelf.ensure_anatomy_copy
anatomy_values_from_choice = collection_shelf.anatomy_values_from_choice
propagate_catalog_identity_to_siblings = (
    collection_shelf.propagate_catalog_identity_to_siblings
)
catalog_identity_groups = collection_shelf.catalog_identity_groups
fill_same_catalog_identities = collection_shelf.fill_same_catalog_identities
listing_url_for_copy = collection_shelf.listing_url_for_copy
apply_common_record_fields = collection_shelf.apply_common_record_fields
save_owned_copy = collection_shelf.save_owned_copy
pressing_for_edited_catalog = collection_shelf.pressing_for_edited_catalog
save_shelf_facts = collection_shelf.save_shelf_facts
save_shelf_dates = collection_shelf.save_shelf_dates
align_lot_dates = collection_shelf.align_lot_dates
inherit_lot_dates = collection_shelf.inherit_lot_dates
purchases_with_lot_paid_on = collection_shelf.purchases_with_lot_paid_on
backfill_lot_paid_on = collection_shelf.backfill_lot_paid_on
lot_package_id = collection_shelf.lot_package_id
stamp_lot_dates = collection_shelf.stamp_lot_dates
LotCopy = collection_shelf.LotCopy
remove_shelf_copy = collection_shelf.remove_shelf_copy
apply_delivery_dates = collection_shelf.apply_delivery_dates
condition_profile = collector_review_support.condition_profile
edition_values_from_form = collector_review_support.edition_values_from_form
factory_pack_sentence = collector_review_support.factory_pack_sentence
insert_owns_poster = collector_review_support.insert_owns_poster
notes_insert_fact = collector_review_support.notes_insert_fact
notes_without_insert_fact = collector_review_support.notes_without_insert_fact
notes_with_lot_mix = collector_review_support.notes_with_lot_mix
notes_without_lot_mix = collector_review_support.notes_without_lot_mix
lot_mix_from_notes = collector_review_support.lot_mix_from_notes
lot_mix_from_title = collector_review_support.lot_mix_from_title
lot_count_noun = collector_review_support.lot_count_noun
obi_for_region = collector_review_support.obi_for_region
obi_label_for_region = collector_review_support.obi_label_for_region
obi_value_for_region = collector_review_support.obi_value_for_region
FACTORY_NO_INSERT_NOTE = collector_review_support.FACTORY_NO_INSERT_NOTE
INSERT_ONLY_NOTE = collector_review_support.INSERT_ONLY_NOTE
MISSING_INSERT = collector_review_support.MISSING_INSERT
PINUP_INSERT_NOTE = collector_review_support.PINUP_INSERT_NOTE
sealed_allowed_for_grades = collector_review_support.sealed_allowed_for_grades
sealed_choice_for_grades = collector_review_support.sealed_choice_for_grades
search_visible_sales = collection_shelf.search_visible_sales
render_navigation = app_navigation.render_navigation


st.set_page_config(
    page_title="My collection",
    page_icon="💿",
    layout="wide",
)
render_navigation(current_page="pages/17_My_Collection.py")

_CURRENCIES = ("USD", "JPY", "EUR", "GBP", "HKD", "SEK", "AUD")
_BILL_UPLOAD_TYPES = (
    "pdf",
    "html",
    "htm",
    "csv",
    "txt",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
)
_REGION_OPTIONS = (
    "Automatic / unset",
    "Japan",
    "Hong Kong",
    "Taiwan",
    "Singapore",
    "Malaysia",
    "South Korea",
    "China",
    "United States",
    "United Kingdom",
    "Europe",
    "Other",
)
_PRESSING_TYPE_OPTIONS = (
    "Automatic / unset",
    "STANDARD",
    "FIRST_PRESSING",
    "PROMO_SAMPLE",
    "REISSUE",
)
_VERDICT_OPTIONS = (
    "Automatic / unset",
    "PASS",
    "WATCH",
    "REFERENCE_ONLY",
    "REJECT",
)
_GRADE_OPTIONS = (
    "Automatic / unset",
    "S",
    "A",
    "B",
    "C",
    "D",
    "M",
    "NM",
    "EX+",
    "EX",
    "VG+",
    "VG",
    "G",
)
_TRI_OPTIONS = ("Automatic / unset", "Yes", "No")
_UNSET = "Automatic / unset"
_LP_INSERT_OPTIONS = (
    "Automatic / unset",
    "Yes",
    MISSING_INSERT,
    "Insert only",
    "Pin-up is the insert",
    "Factory no insert",
)
_LP_POSTER_OPTIONS = (
    "Automatic / unset",
    "Yes",
    "No",
    "Pin-up is the poster",
)


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


def _sections_then_oldest(
    frame: pd.DataFrame,
    tracked: tuple[str, ...] | list[str],
) -> pd.DataFrame:
    """Artists stay together. The artist acquired first comes first."""

    names = tuple(tracked)
    records = frame.to_dict("records")
    for row in records:
        section = _tracked_artist(
            row.get("artist_name"),
            row.get("album_title") or row.get("listing_title"),
            names,
        )
        row["section"] = section or _shelf_text(row.get("artist_name")) or "Unknown"
        row["artist_section"] = row["section"]
    ordered = order_copies_by_artist(records)
    return pd.DataFrame(ordered).drop(columns=["section"]).reset_index(drop=True)


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
    """Listings this account marked in the collection, including delivery date."""
    return query_dataframe(
        """
        SELECT
            sale.marketplace::text AS marketplace,
            sale.listing_id::text AS listing_id,
            sale.seller,
            sale.auction_url,
            sale.title AS listing_title,
            COALESCE(family.display_artist, sale.effective_artist) AS artist_name,
            family.display_title AS album_title,
            sale.effective_catalog_number AS catalog_number,
            sale.pressing_id,
            NULLIF(BTRIM(sale.image_url), '') AS listing_image_url,
            NULLIF(BTRIM(sale.discogs_thumb_url), '') AS discogs_thumb_url,
            COALESCE(
                NULLIF(BTRIM(sale.discogs_thumb_url), ''),
                NULLIF(BTRIM(sale.image_url), '')
            ) AS cover_url,
            owned.manual_purchase_price AS paid,
            owned.manual_purchase_currency AS paid_currency,
            owned.manual_purchase_date AS paid_on,
            owned.manual_delivered_on AS delivered_on,
            owned.manual_auction_format AS sale_type,
            sale.auction_format AS stored_sale_type,
            COALESCE(bill.line_note, owned.manual_purchase_notes) AS billing_note,
            bill.shipping_amount,
            bill.tax_amount,
            bill.fee_amount,
            bill.order_id,
            bill.package_item,
            bill.package_shipping,
            bill.package_tax,
            bill.package_total,
            owned.manual_catalog_number,
            owned.manual_media_type,
            owned.manual_region,
            owned.manual_disc_count,
            owned.manual_pressing_type,
            owned.manual_condition_media,
            owned.manual_condition_cover,
            owned.manual_verdict,
            owned.manual_obi,
            owned.manual_insert_present,
            owned.manual_poster_present,
            owned.manual_sealed,
            owned.manual_rental,
            owned.manual_completeness_notes,
            owned.manual_collector_notes,
            COALESCE(
                NULLIF(BTRIM(owned.manual_media_type), ''),
                NULLIF(BTRIM(sale.effective_media_type), ''),
                NULLIF(BTRIM(pressing.media_type), '')
            ) AS media_type,
            pressing.format_detail,
            pressing.disc_count
        FROM warehouse.auction_collector owned
        JOIN warehouse.auction_collector_effective sale
          ON sale.marketplace::text = owned.marketplace::text
         AND sale.listing_id::text = owned.listing_id::text
        LEFT JOIN warehouse.pressing_identity pressing
          ON pressing.id = sale.pressing_id
        LEFT JOIN warehouse.release_family family
          ON family.id = pressing.release_family_id
        LEFT JOIN LATERAL (
            SELECT
                line.shipping_amount,
                line.tax_amount,
                line.fee_amount,
                line.line_note,
                header.external_order_id AS order_id,
                header.item_total AS package_item,
                header.shipping_total AS package_shipping,
                header.tax_total AS package_tax,
                header.grand_total AS package_total
            FROM warehouse.collection_bill_line line
            JOIN warehouse.collection_bill header
              ON header.id = line.bill_id
            WHERE line.account_id = owned.account_id
              AND lower(btrim(line.marketplace)) =
                  lower(btrim(owned.marketplace::text))
              AND line.listing_id = owned.listing_id::text
            ORDER BY line.created_at DESC
            LIMIT 1
        ) bill ON TRUE
        WHERE owned.account_id = CAST(:account_id AS uuid)
          AND owned.manual_purchased IS TRUE
        ORDER BY owned.manual_purchase_date DESC NULLS LAST,
                 sale.effective_catalog_number
        """,
        {"account_id": account_id},
    )


@st.cache_data(ttl=120)
def load_owned(account_id: str) -> pd.DataFrame:
    """Shop orders saved without a scraped marketplace listing. Charges come from the billing note."""
    frame = query_dataframe(
        """
        SELECT
            owned.source AS marketplace,
            owned.external_id AS listing_id,
            owned.seller,
            NULL::text AS auction_url,
            owned.title AS listing_title,
            COALESCE(family.display_artist, '') AS artist_name,
            COALESCE(family.display_title, owned.title) AS album_title,
            COALESCE(pressing.catalog_number, owned.catalog_number) AS catalog_number,
            owned.pressing_id,
            cover.cover_url,
            owned.paid_amount AS paid,
            owned.paid_currency,
            owned.paid_on,
            owned.delivered_on,
            owned.sale_type,
            owned.media_type,
            pressing.format_detail,
            pressing.disc_count,
            NULL::varchar AS stored_sale_type,
            COALESCE(bill.line_note, owned.billing_note) AS billing_note,
            bill.shipping_amount,
            bill.tax_amount,
            bill.fee_amount,
            bill.order_id,
            bill.package_item,
            bill.package_shipping,
            bill.package_tax,
            bill.package_total
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
        LEFT JOIN LATERAL (
            SELECT
                line.shipping_amount,
                line.tax_amount,
                line.fee_amount,
                line.line_note,
                header.external_order_id AS order_id,
                header.item_total AS package_item,
                header.shipping_total AS package_shipping,
                header.tax_total AS package_tax,
                header.grand_total AS package_total
            FROM warehouse.collection_bill_line line
            JOIN warehouse.collection_bill header
              ON header.id = line.bill_id
            WHERE line.account_id = owned.account_id
              AND lower(btrim(line.marketplace)) = lower(btrim(owned.source))
              AND line.listing_id = owned.external_id::text
            ORDER BY line.created_at DESC
            LIMIT 1
        ) bill ON TRUE
        WHERE owned.account_id = CAST(:account_id AS uuid)
          AND NOT EXISTS (
            SELECT 1
            FROM warehouse.auction_collector collector
            WHERE collector.account_id = owned.account_id
              AND lower(btrim(collector.marketplace::text)) =
                  lower(btrim(owned.source))
              AND collector.listing_id::text = owned.external_id::text
              AND collector.manual_purchased IS TRUE
          )
        ORDER BY owned.paid_on DESC NULLS LAST, owned.catalog_number
        """,
        {"account_id": account_id},
    )
    if frame.empty:
        return frame
    titles = (
        frame["listing_title"]
        if "listing_title" in frame.columns
        else frame["album_title"]
    )
    keep = [owned_copy_shows_on_shelf(title) for title in titles]
    return frame.loc[keep].reset_index(drop=True)


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
    if number < 0:
        if code == "JPY":
            return f"-¥{abs(number):,.0f}"
        if code == "USD":
            return f"-${abs(number):,.2f}"
        return f"-{abs(number):,.2f} {code}"
    if code == "JPY":
        return f"¥{number:,.0f}"
    if code == "USD":
        return f"${number:,.2f}"
    return f"{number:,.2f} {code}"


def _package_cost_caption(row: dict[str, object]) -> str:
    """Combined order totals card: items, shipping, tax, order total."""

    shipping = _editor_decimal(row.get("package_shipping"))
    tax = _editor_decimal(row.get("package_tax"))
    total = _editor_decimal(row.get("package_total"))
    items = _editor_decimal(row.get("package_item"))
    if shipping is None and tax is None and total is None:
        return ""
    layout = copy_charge_layout(
        paid=_editor_decimal(row.get("paid")),
        shipping=_editor_decimal(row.get("shipping_amount")),
        tax=_editor_decimal(row.get("tax_amount")),
        fees=_editor_decimal(row.get("fee_amount")),
        package_item=items,
        package_shipping=shipping,
        package_tax=tax,
        package_total=total,
    )
    if not layout["combined"]:
        return ""
    currency = str(row.get("paid_currency") or "USD").upper()
    order_id = _shelf_text(row.get("order_id"))
    parts = [
        part
        for part in (
            f"Items {_money(items, currency)}" if items is not None else "",
            f"Shipping {_money(shipping, currency)}" if shipping is not None else "",
            f"Tax {_money(tax, currency)}" if tax is not None else "",
            f"Order {_money(total, currency)}" if total is not None else "",
        )
        if part
    ]
    if not parts:
        return ""
    heading = "Share of combined order"
    if order_id and not order_id.startswith("package:"):
        heading = f"{heading} {order_id}"
    return heading + ": " + " · ".join(parts)


def _printed_catalog(row: dict[str, object]) -> str:
    """Catalog printed on the listing title, then the stored number."""

    return _shelf_text(
        listing_identity_catalog(
            stored=_shelf_text(
                row.get("manual_catalog_number") or row.get("catalog_number")
            )
            or None,
            title=_shelf_text(row.get("listing_title")) or None,
            artist=_shelf_text(row.get("artist_name")) or None,
            media_type=_shelf_text(row.get("media_type")) or None,
        )
    )


def _row_pressing_id(row: dict[str, object]) -> int | None:
    """Pressing already attached to this shelf copy, if any."""

    raw = row.get("pressing_id")
    if raw is None or raw == "":
        return None
    try:
        if pd.isna(raw):
            return None
    except TypeError:
        pass
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _media_label(media: object) -> str:
    labels = {
        "LP": "LP",
        "LP_BOX_SET": "LP box",
        "EP_7_INCH": "EP",
        "SINGLE_12_INCH": "12-inch",
        "12_INCH_SINGLE": "12-inch",
        "CD": "CD",
        "CD_BOX_SET": "CD box",
        "SHM_CD": "SHM-CD",
        "SACD": "SACD",
        "BLU_SPEC_CD": "Blu-spec",
        "CD_SINGLE_8CM": "8cm CD",
        "CASSETTE": "Cassette",
        "CASSETTE_BOX_SET": "Cassette box",
        "DVD": "DVD",
        "LASERDISC": "Laserdisc",
        "LP_BULK_LOT": "LP lot",
        "EP_BULK_LOT": "EP lot",
        "CD_BULK_LOT": "CD lot",
        "CASSETTE_BULK_LOT": "Cassette lot",
        "MIXED_BULK_LOT": "Mixed lot",
        "BULK_LOT": "Lot",
        "MIXED_MEDIA": "Mixed",
        "MAGAZINE": "Magazine",
    }
    return labels.get(str(media or ""), "")


def _printed_matrix(row: dict[str, object] | object, catalog: object = None) -> str:
    """Catalog / matrix for save messages. Prefer the manual print over Discogs."""

    if isinstance(row, dict):
        return _shelf_text(
            row.get("manual_catalog_number")
            or row.get("catalog_number")
            or catalog
        )
    return _shelf_text(catalog)


def _record_label(
    artist: object,
    title: object,
    catalog: object,
    listing_id: object = None,
    media: object = None,
) -> str:
    shown_title = _shelf_text(title)
    shown_catalog = _shelf_text(catalog)
    if listing_title_is_ocr_junk(shown_title):
        shown_title = ""
        if not listing_catalog_is_structured(shown_catalog):
            shown_catalog = ""
    # Catalog / matrix first so save banners name the pressing, not buyee:j….
    label = " · ".join(
        part
        for part in (
            shown_catalog,
            _shelf_text(artist),
            english_album_title(shown_title) or shown_title,
            _media_label(media) if str(media or "") not in {"", "LP"} else "",
        )
        if part
    )
    if label:
        return label
    return _shelf_text(listing_id)


def _display_album_title(album: object, listing: object) -> str:
    album_text = _shelf_text(album)
    listing_text = _shelf_text(listing)
    if listing_title_is_chrome(album_text) or listing_title_is_ocr_junk(album_text):
        album_text = ""
    if listing_title_is_chrome(listing_text) or listing_title_is_ocr_junk(listing_text):
        listing_text = ""
    return english_album_title(album_text) or album_text or listing_text


def _paid_on_date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _pending_bill_purchases() -> list[Any]:
    """Bills already read off the screenshots, before this copy is saved."""

    pages = [
        str(part)
        for part in (st.session_state.get("collection-shelf-fill-pages") or [])
        if str(part).strip()
    ]
    raw = str(st.session_state.get("collection-shelf-fill-raw") or "").strip()
    text = combine_bill_pages([*pages, raw])
    purchases: list[Any] = []
    if text:
        purchases.extend(parse_purchase_export(text).purchases)
    purchases.extend(st.session_state.get("collection-shelf-fill-billed") or [])
    return purchases


def _known_delivered_on(row: dict[str, object]) -> date | None:
    """Stored delivery date, or the one just extracted for this listing."""

    stored = _paid_on_date(row.get("delivered_on"))
    if stored is not None:
        return stored
    return extracted_delivered_on(row, _pending_bill_purchases())


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


def _close_shelf_copy(row: dict[str, object], *, values: dict[str, Any]) -> None:
    """Save this record returns the shelf to no row selected."""

    snapshot = dict(row)
    snapshot.update(values)
    label = _record_label(
        snapshot.get("artist_name"),
        snapshot.get("album_title") or snapshot.get("listing_title"),
        _printed_matrix(snapshot),
        snapshot.get("listing_id"),
    )
    st.session_state.pop("collection-shelf-focus", None)
    st.session_state["collection-shelf-apply-focus"] = False
    st.session_state["collection-shelf-fill-status"] = "record-saved"
    st.session_state["collection-shelf-saved-label"] = label
    st.session_state["collection-shelf-saved-gaps"] = anatomy_gaps(snapshot)
    _bump_fill_seq("collection-shelf-grid-seq")
    load_collected.clear()
    load_owned.clear()
    st.rerun()


def _copy_identity(row: dict[str, object]) -> str:
    return (
        f"{_shelf_text(row.get('marketplace'))}:"
        f"{_shelf_text(row.get('listing_id'))}"
    )


def _set_widget_if_changed(key: str, value: str) -> None:
    """Assign widget state only when it actually changes. A write every rerun extra-runs Streamlit."""

    if st.session_state.get(key) != value:
        st.session_state[key] = value


def _fill_seq(name: str) -> int:
    return int(st.session_state.get(name) or 0)


def _bump_fill_seq(name: str) -> int:
    nxt = _fill_seq(name) + 1
    st.session_state[name] = nxt
    return nxt


def _clear_import_drop(*, keep_pages: bool = False) -> None:
    """Drop parked Bring-in screenshots. After a save, drop the extracted text too."""

    st.session_state.pop("collection-import-shots", None)
    _bump_fill_seq("collection-import-upload-seq")
    if keep_pages:
        return
    st.session_state.pop("collection-import-pages", None)
    st.session_state.pop("collection-import-raw", None)
    st.session_state.pop("collection-import-pending", None)
    st.session_state.pop("collection-import-done", None)
    _bump_fill_seq("collection-import-paste-seq")


def _import_done_ids() -> set[str]:
    return {str(item) for item in (st.session_state.get("collection-import-done") or [])}


def _pending_import_purchases(parsed):
    """Keep unprocessed Bring-in rows after one of them is added or left out."""

    parked = list(st.session_state.get("collection-import-pending") or [])
    kept = hold_import_purchases(
        parsed.purchases,
        parked,
        _import_done_ids(),
    )
    st.session_state["collection-import-pending"] = kept
    return replace(parsed, purchases=tuple(kept))


def _remove_pending_purchases(external_ids: list[str]) -> None:
    drop = {str(item) for item in external_ids if str(item).strip()}
    done = _import_done_ids() | drop
    st.session_state["collection-import-done"] = list(done)
    parked = list(st.session_state.get("collection-import-pending") or [])
    st.session_state["collection-import-pending"] = hold_import_purchases(
        (),
        parked,
        done,
    )


def _clear_fill_bill(*, keep_extracted_pages: bool = False) -> None:
    """Drop parked screenshots. After a save, drop the extracted text too."""

    st.session_state.pop("collection-shelf-fill-shots", None)
    st.session_state.pop("collection-shelf-fill-shot", None)
    _bump_fill_seq("collection-shelf-fill-upload-seq")
    if keep_extracted_pages:
        return
    st.session_state.pop("collection-shelf-fill-pages", None)
    st.session_state.pop("collection-shelf-fill-raw", None)
    st.session_state.pop("collection-shelf-fill-billed", None)
    _bump_fill_seq("collection-shelf-fill-paste-seq")


def _advance_to_closest_open(
    frame: pd.DataFrame,
    current: dict[str, object],
) -> None:
    """After a save, open the nearest shelf row that is still empty."""

    nxt = closest_unfilled_copy(frame.to_dict("records"), current=current)
    _bump_fill_seq("collection-shelf-grid-seq")
    if nxt is None:
        st.session_state.pop("collection-shelf-focus", None)
        st.session_state["collection-shelf-apply-focus"] = False
        st.session_state["collection-shelf-fill-status"] = "facts-done"
        return
    st.session_state["collection-shelf-focus"] = _copy_identity(nxt)
    st.session_state["collection-shelf-apply-focus"] = True
    st.session_state["collection-shelf-next-label"] = _shelf_copy_label(nxt)
    st.session_state["collection-shelf-fill-status"] = "facts-next"


def _advance_unfilled_copy(
    frame: pd.DataFrame,
    *,
    current: dict[str, object],
    filled: list[tuple[str, str]],
) -> None:
    nxt = next_unfilled_copy(
        frame.to_dict("records"),
        after=current,
        filled=set(filled),
    )
    _clear_fill_bill()
    _bump_fill_seq("collection-shelf-grid-seq")
    if nxt is None:
        st.session_state.pop("collection-shelf-focus", None)
        st.session_state["collection-shelf-apply-focus"] = False
        st.session_state["collection-shelf-fill-status"] = "saved-done"
        return
    st.session_state["collection-shelf-focus"] = _copy_identity(nxt)
    st.session_state["collection-shelf-apply-focus"] = True
    st.session_state["collection-shelf-next-label"] = _shelf_copy_label(nxt)
    st.session_state["collection-shelf-fill-status"] = "saved-next"


def _show_fill_status() -> None:
    status = st.session_state.pop("collection-shelf-fill-status", "")
    if status == "facts-next":
        nxt = st.session_state.pop("collection-shelf-next-label", "")
        complete = st.session_state.pop("collection-shelf-saved-complete", False)
        lead = "Saved billing and the record. This copy is filled." if complete else "Saved."
        st.success(f"{lead} Next open copy: {nxt}")
        return
    if status == "both-partial":
        gaps = st.session_state.pop("collection-shelf-saved-gaps", None) or []
        if gaps:
            st.success(
                "Saved billing and the record. Still needs: "
                + ", ".join(str(item) for item in gaps)
                + "."
            )
            return
        st.success("Saved billing and the record.")
        return
    if status == "facts-done":
        complete = st.session_state.pop("collection-shelf-saved-complete", False)
        lead = "Saved billing and the record. This copy is filled." if complete else "Saved."
        st.success(f"{lead} Every other copy on the shelf is filled.")
        return
    if status == "saved-next":
        nxt = st.session_state.pop("collection-shelf-next-label", "")
        st.success(f"Saved. Next unfilled: {nxt}")
        return
    if status == "saved-done":
        st.success("Saved. Every copy on the shelf has shipping and tax.")
        return
    if status == "saved":
        st.success("Saved the yen charges on this copy. Landed adds their dollar value.")
        return
    if status == "delivery-saved":
        label = str(st.session_state.pop("collection-shelf-saved-label", "") or "").strip()
        st.success(label or "Saved those delivery dates.")
        return
    if status == "catalogs-filled":
        stats = st.session_state.pop("collection-shelf-catalog-stats", {}) or {}
        copied = int(stats.get("copied") or 0)
        filled = int(stats.get("filled_search") or 0)
        searched = int(stats.get("searched") or 0)
        skipped = int(stats.get("skipped") or 0)
        st.success(
            f"Filled {copied} same-catalog copies without Discogs. "
            f"Searched {searched} catalogs and filled {filled}. "
            f"{skipped} still need a pick."
        )
        return
    if status == "record-saved":
        label = str(st.session_state.pop("collection-shelf-saved-label", "") or "").strip()
        gaps = st.session_state.pop("collection-shelf-saved-gaps", None) or []
        named = f"Saved {label}." if label else "Saved this record."
        if gaps:
            st.success(f"{named} Still needs: {', '.join(str(item) for item in gaps)}.")
            return
        st.success(f"{named} Record is filled.")
        return


def _render_catalog_fill(
    frame: pd.DataFrame,
    *,
    account_id: str,
    user_id: str,
) -> None:
    """Same catalogs inherit identity. Leftover catalogs get one Discogs search."""

    rows = frame.to_dict("records")
    groups = catalog_identity_groups(rows)
    copyable = [group for group in groups if group.pressing_id is not None]
    searchable = [group for group in groups if group.needs_search]
    if not copyable and not searchable:
        return
    sibling_copies = sum(max(len(group.copies) - 1, 0) for group in copyable)
    st.caption(
        f"{sibling_copies} copies share a catalog already identified. "
        f"{len(searchable)} catalogs still need Discogs. "
        "One search per leftover catalog. Condition stays on each copy."
    )
    if not st.button("Fill same catalogs", key="collection-fill-catalogs"):
        return
    client = DiscogsClient(timeout=8.0) if searchable else None
    stats = fill_same_catalog_identities(
        engine,
        account_id=account_id,
        user_id=user_id,
        rows=rows,
        client=client,
        search_missing=bool(searchable),
    )
    st.session_state["collection-shelf-fill-status"] = "catalogs-filled"
    st.session_state["collection-shelf-catalog-stats"] = stats
    _refresh_shelf()


def _sum_amounts(*values: Decimal | None) -> Decimal | None:
    total: Decimal | None = None
    for value in values:
        if value is None:
            continue
        total = value if total is None else total + value
    return total


def _note_has_charges(note: object) -> bool:
    text = "" if note is None else str(note)
    return any(
        value is not None
        for key, value in copy_costs(text).items()
        if key != "tax_included"
    )


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


def _scan_amount(usd: Decimal | None, amount: object, currency: object) -> str:
    """Short table cell: dollars when we have them, otherwise the original charge."""

    if usd is not None:
        return _money(usd, "USD")
    return _money(amount, currency)


def _copy_price_view(row: dict[str, object]) -> dict[str, Any]:
    """Item, charges, and landed for one shelf copy — dollars for scanning, yen kept."""

    parts = _shelf_costs(row.get("billing_note"), row.get("paid_currency"))
    item_code = str(row.get("paid_currency") or "USD").upper()
    charge_code = str(parts["charge_currency"])
    paid_on_date = _paid_on_date(row.get("paid_on"))
    note_text = str(parts["note"])
    item_rate = _usd_per_unit(item_code, note_text, paid_on_date)
    charge_rate = _usd_per_unit(charge_code, note_text, paid_on_date)
    item_amount = _editor_decimal(row.get("paid"))
    recovered_item = ocr_promo_item_price(
        _shelf_text(row.get("album_title")) or _shelf_text(row.get("listing_title")),
        item_amount,
    )
    if recovered_item is not None:
        item_amount = recovered_item
    shipping, tax, fees = shelf_charge_amounts(
        shipping_amount=row.get("shipping_amount"),
        tax_amount=row.get("tax_amount"),
        fee_amount=row.get("fee_amount"),
        billing_note=note_text,
    )
    included_tax = copy_costs(note_text).get("tax_included")
    tax_inside = tax is None and included_tax is not None
    shown_tax = included_tax if tax_inside else tax
    refund = copy_refund(
        note_text,
        item=item_amount,
        shipping=shipping,
        tax=tax,
        fees=fees,
    )
    discount = copy_costs(note_text).get("discount")
    item_usd = (
        to_usd(item_amount, item_rate)
        if item_amount is not None and item_rate is not None
        else None
    )
    shipping_usd = (
        to_usd(shipping, charge_rate)
        if shipping is not None and charge_rate is not None
        else None
    )
    tax_usd = (
        to_usd(shown_tax, charge_rate)
        if shown_tax is not None and charge_rate is not None
        else None
    )
    fees_usd = (
        to_usd(fees, charge_rate)
        if fees is not None and charge_rate is not None
        else None
    )
    refund_usd = (
        to_usd(refund, charge_rate)
        if refund is not None and charge_rate is not None
        else None
    )
    discount_usd = (
        to_usd(discount, charge_rate)
        if discount is not None and charge_rate is not None
        else None
    )
    package_item = _editor_decimal(row.get("package_item"))
    package_shipping = _editor_decimal(row.get("package_shipping"))
    package_tax = _editor_decimal(row.get("package_tax"))
    buyee_lines = []
    for label, amount in buyee_package_display_lines(
        note_text,
        package_shipping=package_shipping,
        package_tax=package_tax,
    ):
        usd = (
            to_usd(amount, charge_rate) if charge_rate is not None else None
        )
        buyee_lines.append(
            {
                "label": label,
                "amount": amount,
                "usd": usd,
                "scan": _scan_amount(usd, amount, charge_code),
            }
        )
    extra_landed: list[tuple[Decimal | None, str, Decimal | None]] = []
    for amount in buyee_package_landed_extras(
        note_text,
        marketplace=str(row.get("marketplace") or ""),
        paid=item_amount,
        package_item=package_item,
        package_shipping=package_shipping,
        package_tax=package_tax,
    ):
        extra_landed.append((amount, charge_code, charge_rate))
    landed = _landed_label(
        (
            (item_amount, item_code, item_rate),
            (shipping, charge_code, charge_rate),
            (tax, charge_code, charge_rate),
            (fees, charge_code, charge_rate),
            (discount, charge_code, charge_rate),
            (refund, charge_code, charge_rate),
            *extra_landed,
        )
    )
    return {
        "item": item_amount,
        "item_code": item_code,
        "item_usd": item_usd,
        "shipping": shipping,
        "tax": shown_tax,
        "tax_inside": tax_inside,
        "fees": fees,
        "refund": refund,
        "discount": discount,
        "discount_usd": discount_usd,
        "shipping_usd": shipping_usd,
        "tax_usd": tax_usd,
        "fees_usd": fees_usd,
        "refund_usd": refund_usd,
        "charge_code": charge_code,
        "landed": landed,
        "item_scan": _scan_amount(item_usd, item_amount, item_code),
        "shipping_scan": _scan_amount(shipping_usd, shipping, charge_code),
        "tax_scan": _scan_amount(tax_usd, shown_tax, charge_code),
        "fees_scan": _scan_amount(fees_usd, fees, charge_code),
        "landed_scan": landed,
        "buyee_lines": buyee_lines,
    }


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


def _price_metric(
    slot: Any,
    title: str,
    usd: Decimal | None,
    amount: object,
    currency: object,
) -> None:
    usd_label = _money(usd, "USD") if usd is not None else ""
    foreign_label = _money(amount, currency)
    primary = usd_label or foreign_label or "—"
    extra = ""
    if (
        usd_label
        and foreign_label
        and str(currency or "USD").upper() != "USD"
        and foreign_label != usd_label
    ):
        extra = foreign_label
    slot.markdown(
        f'<div class="collection-price-label">{title}</div>'
        f'<div class="collection-price-value">{primary}</div>',
        unsafe_allow_html=True,
    )
    if extra:
        slot.caption(extra)


def _buyee_scan(view: dict[str, Any], label: str) -> str:
    for line in view.get("buyee_lines") or ():
        if line["label"] == label:
            return str(line["scan"])
    return "—"


def _shelf_row_from_grid(
    picked: dict[str, object],
    table: pd.DataFrame,
) -> dict[str, object] | None:
    """Map the checked grid row to the stored shelf copy, not a shifted index."""

    listing = str(picked.get("listing_id") or "").strip()
    market = str(picked.get("marketplace") or "").strip()
    if listing:
        matches = table.loc[table["listing_id"].astype(str).eq(listing)]
        if market:
            market_hits = matches.loc[
                matches["marketplace"].astype(str).str.casefold().eq(market.casefold())
            ]
            if not market_hits.empty:
                matches = market_hits
        if len(matches) == 1:
            return matches.iloc[0].to_dict()
    key = str(picked.get("row_key") or "").strip()
    if key:
        matches = table.loc[table["row_key"].astype(str).eq(key)]
        if len(matches) == 1:
            return matches.iloc[0].to_dict()
    record = str(picked.get("Record") or "").strip()
    if not record:
        return None
    matches = table.loc[table["record"].astype(str).eq(record)]
    paid = str(picked.get("Paid on") or "").strip()
    if paid:
        paid_hits = matches.loc[matches["paid_on"].astype(str).eq(paid)]
        if not paid_hits.empty:
            matches = paid_hits
    item = str(picked.get("Item") or "").strip()
    if item and len(matches) > 1:
        item_hits = matches.loc[matches["item_scan"].astype(str).eq(item)]
        if not item_hits.empty:
            matches = item_hits
    if len(matches) == 1:
        return matches.iloc[0].to_dict()
    return None


def _aggrid_selected_rows(response: object) -> list[dict[str, object]]:
    selected = getattr(response, "selected_rows", None)
    if selected is None and isinstance(response, dict):
        selected = response.get("selected_rows")
    if selected is None:
        return []
    if isinstance(selected, pd.DataFrame):
        if selected.empty:
            return []
        return selected.to_dict("records")
    if isinstance(selected, dict):
        return [selected]
    if isinstance(selected, (list, tuple)):
        return [row for row in selected if isinstance(row, dict)]
    return []


def _aggrid_first_selected(response: object) -> dict[str, object] | None:
    rows = _aggrid_selected_rows(response)
    return rows[0] if rows else None


_SHELF_COVER_RENDERER = JsCode(
    """
    class ShelfCoverRenderer {
        init(params) {
            this.eGui = document.createElement("div");
            this.eGui.style.height = "44px";
            this.eGui.style.width = "44px";
            this.eGui.style.overflow = "hidden";
            const url = params.value || "";
            if (!url) {
                return;
            }
            const image = document.createElement("img");
            image.src = url;
            image.alt = "";
            image.style.height = "44px";
            image.style.width = "44px";
            image.style.objectFit = "cover";
            image.style.borderRadius = "4px";
            image.style.pointerEvents = "none";
            this.eGui.appendChild(image);
        }
        getGui() {
            return this.eGui;
        }
    }
    """
)

_SHELF_ROW_ID = JsCode(
    """
    function(params) {
        return String(params.data.row_key);
    }
    """
)

_SELECT_FOCUS_ROW = JsCode(
    """
    function(params) {
        const api = params.api;
        if (!api || !api.forEachNode) {
            return;
        }
        let target = null;
        api.forEachNode(function(node) {
            if (node.data && String(node.data.__focus_row) === "1") {
                target = node;
            }
        });
        if (!target || typeof target.setSelected !== "function") {
            return;
        }
        target.setSelected(true, true);
        if (typeof api.ensureIndexVisible === "function" && target.rowIndex != null) {
            api.ensureIndexVisible(target.rowIndex, "middle");
        }
    }
    """
)


def _shelf_copy_label(row: dict[str, object]) -> str:
    """Human label for save / next-copy banners. Catalog first, never marketplace:id."""

    return " · ".join(
        part
        for part in (
            _record_label(
                row.get("artist_name"),
                row.get("album_title") or row.get("listing_title"),
                _printed_matrix(row),
                row.get("listing_id"),
            ),
            _shelf_text(row.get("seller")),
            _money(row.get("paid"), row.get("paid_currency")),
        )
        if part
    )


def _show_selected_copy(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
) -> None:
    st.markdown(
        """
        <style>
        .collection-price-label { color: rgba(49, 51, 63, 0.6); font-size: 0.85rem; }
        .collection-price-value {
            font-size: 1.45rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
            overflow: visible;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    billing_tab, record_tab = st.tabs(("Billing", "Record"))
    with billing_tab:
        _show_billing_panel(row, account_id=account_id, user_id=user_id, frame=frame)
        _render_shelf_fill(account_id, user_id, frame, row)
    with record_tab:
        _show_record_panel(row, account_id=account_id, user_id=user_id, frame=frame)


_SALE_TYPE_CHOICES = (
    ("Auction", "AUCTION"),
    ("Fixed", "FIXED_PRICE"),
    ("OBO", "FIXED_PRICE_OBO"),
)


def _lot_choices(
    row: dict[str, object],
    frame: pd.DataFrame,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Other shelf copies, with the rest of this order selected."""

    identity = _copy_identity(row)
    order_id = _shelf_text(row.get("order_id"))
    choices: dict[str, dict[str, object]] = {}
    same_order: list[str] = []
    if frame is None or frame.empty:
        return choices, same_order
    for other in frame.to_dict("records"):
        other_id = _copy_identity(other)
        if not other_id or other_id == identity:
            continue
        label = _shelf_copy_label(other) or _shelf_text(other.get("listing_id"))
        if label in choices:
            label = f"{label} · {_shelf_text(other.get('listing_id'))}"
        choices[label] = other
        if order_id and _shelf_text(other.get("order_id")) == order_id:
            same_order.append(label)
    return choices, same_order


def _row_format_code(row: dict[str, object], identity: str) -> str | None:
    """Media type already chosen on this copy, including a bulk lot."""

    format_label = str(
        st.session_state.get(f"collection-anatomy-format:{identity}") or ""
    )
    stored = row.get("manual_media_type") or row.get("media_type")
    if format_label:
        return collection_media_code(format_label, stored=stored)
    return collection_media_code(
        collection_media_label(stored),
        stored=stored,
    )


def _lot_mix_counts_from_state(
    identity: str,
    row: dict[str, object],
) -> dict[str, int]:
    mix_key = f"collection-lot-mix:{identity}"
    chosen = st.session_state.get(mix_key)
    mix_formats = ("LP", "EP", "CD", "Cassette")
    if chosen is None:
        title = _display_album_title(row.get("album_title"), row.get("listing_title"))
        saved = lot_mix_from_notes(row.get("manual_completeness_notes"))
        chosen = [
            name
            for name in mix_formats
            if name in (saved or lot_mix_from_title(title))
        ]
    counts: dict[str, int] = {}
    for name in chosen:
        raw = st.session_state.get(f"collection-lot-mix-count:{identity}:{name}")
        try:
            count = int(raw) if raw not in {None, ""} else 0
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            counts[name] = count
    return counts


def _anatomy_values_from_state(
    row: dict[str, object],
    identity: str,
) -> dict[str, Any] | None:
    """Record fields already on screen. None until that form has been shown."""

    catalog_key = f"collection-anatomy-catalog:{identity}"
    if catalog_key not in st.session_state:
        return None
    region = str(st.session_state.get(f"collection-anatomy-region:{identity}") or _UNSET)
    pressing = str(st.session_state.get(f"collection-anatomy-press:{identity}") or _UNSET)
    media = str(st.session_state.get(f"collection-anatomy-media:{identity}") or _UNSET)
    cover = str(st.session_state.get(f"collection-anatomy-cover:{identity}") or _UNSET)
    verdict = str(st.session_state.get(f"collection-anatomy-verdict:{identity}") or _UNSET)
    format_label = str(
        st.session_state.get(f"collection-anatomy-format:{identity}") or _UNSET
    )
    format_code = collection_media_code(
        format_label,
        stored=row.get("manual_media_type") or row.get("media_type"),
    )
    profile = condition_profile(format_code or _shelf_text(row.get("media_type")) or None)
    kind = str(profile.get("kind") or "other")
    discs = st.session_state.get(f"collection-anatomy-discs:{identity}")
    obi_choice = str(st.session_state.get(f"collection-anatomy-obi:{identity}") or "No")
    insert_choice = str(
        st.session_state.get(f"collection-anatomy-insert:{identity}:{kind}")
        or st.session_state.get(f"collection-anatomy-insert:{identity}")
        or _UNSET
    )
    poster_choice = str(st.session_state.get(f"collection-anatomy-poster:{identity}") or "No")
    rental = str(st.session_state.get(f"collection-anatomy-rental:{identity}") or _UNSET)
    sealed = str(st.session_state.get(f"collection-anatomy-sealed:{identity}") or _UNSET)
    notes = str(st.session_state.get(f"collection-anatomy-notes:{identity}") or "")
    if collection_bulk_lot(format_code):
        mix_counts = _lot_mix_counts_from_state(identity, row)
        if format_code == "MIXED_BULK_LOT":
            disc_count = sum(mix_counts.values()) or None
            notes = notes_with_lot_mix(notes_without_lot_mix(notes), mix_counts)
        else:
            try:
                disc_count = int(discs) if discs else None
            except (TypeError, ValueError):
                disc_count = None
            notes = notes_without_lot_mix(notes)
        return {
            "manual_catalog_number": None,
            "manual_region": None,
            "manual_disc_count": disc_count,
            "manual_pressing_type": None,
            "manual_media_type": format_code,
            "manual_condition_media": None if media == _UNSET else media,
            "manual_condition_cover": None,
            "manual_verdict": None if verdict == _UNSET else verdict,
            "manual_obi": None,
            "manual_insert_present": None,
            "manual_poster_present": None,
            "manual_rental": None,
            "manual_sealed": None,
            "manual_completeness_notes": notes or None,
        }
    pack = edition_values_from_form(
        insert=insert_choice,
        poster=poster_choice,
        notes=notes,
    )
    try:
        disc_count = int(discs) if discs not in {None, ""} else 1
    except (TypeError, ValueError):
        disc_count = 1
    return {
        "manual_catalog_number": _shelf_text(st.session_state.get(catalog_key)) or None,
        "manual_region": None if region == _UNSET else region,
        "manual_disc_count": disc_count,
        "manual_pressing_type": None if pressing == _UNSET else pressing,
        "manual_media_type": format_code,
        "manual_condition_media": None if media == _UNSET else media,
        "manual_condition_cover": None if cover == _UNSET else cover,
        "manual_verdict": None if verdict == _UNSET else verdict,
        "manual_obi": obi_value_for_region(
            _tri_stored(obi_choice),
            None if region == _UNSET else region,
        ),
        "manual_insert_present": pack["manual_insert_present"],
        "manual_poster_present": pack["manual_poster_present"],
        "manual_rental": _tri_stored(rental),
        "manual_sealed": _tri_stored(
            sealed_choice_for_grades(media, cover, sealed)
        ),
        "manual_completeness_notes": pack["manual_completeness_notes"],
    }


def _save_billing_and_record(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
    paid_amount: Decimal,
    paid_on: date | None,
    delivered_on: date | None,
    sale_type: str,
) -> None:
    """One save writes the billing facts and the record. Both together are filled."""

    identity = _copy_identity(row)
    lowered = (
        f"{_shelf_text(row.get('marketplace')).lower()}:"
        f"{_shelf_text(row.get('listing_id'))}"
    )
    if (
        f"collection-anatomy-catalog:{identity}" not in st.session_state
        and f"collection-anatomy-catalog:{lowered}" in st.session_state
    ):
        identity = lowered
    market = _shelf_text(row.get("marketplace"))
    listing_id = _shelf_text(row.get("listing_id"))
    wrote = save_shelf_facts(
        engine,
        account_id=account_id,
        marketplace=market,
        listing_id=listing_id,
        paid_amount=paid_amount,
        paid_on=paid_on,
        delivered_on=delivered_on,
        sale_type=sale_type,
    )
    anatomy = _anatomy_values_from_state(row, identity)
    if anatomy is not None:
        wrote += save_copy_anatomy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=market,
            listing_id=listing_id,
            values=anatomy,
        )
        identification = {
            key: anatomy.get(key)
            for key in (
                "manual_catalog_number",
                "manual_region",
                "manual_disc_count",
                "manual_pressing_type",
                "manual_media_type",
            )
            if anatomy.get(key) not in {None, ""}
        }
        if identification:
            propagate_catalog_identity_to_siblings(
                engine,
                account_id=account_id,
                user_id=user_id,
                marketplace=market,
                listing_id=listing_id,
                values=identification,
                pressing_id=_row_pressing_id(row),
            )
    if not wrote:
        st.error("Could not save this copy.")
        return
    snapshot = dict(row)
    if anatomy:
        snapshot.update(anatomy)
    snapshot["sale_type"] = sale_type
    snapshot["paid"] = paid_amount
    if shelf_copy_filled(snapshot):
        st.session_state["collection-shelf-saved-complete"] = True
        _advance_to_closest_open(frame, row)
    else:
        gaps = anatomy_gaps(snapshot)
        if not effective_sale_type(
            marketplace=market,
            stored=row.get("stored_sale_type"),
            manual=sale_type,
        ):
            gaps.append("Sale type")
        st.session_state["collection-shelf-fill-status"] = "both-partial"
        st.session_state["collection-shelf-saved-gaps"] = gaps
    _refresh_shelf()


def _render_shelf_facts(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
) -> None:
    """Paid, delivered, item, and sale type. Remove takes the copy off the shelf."""

    identity = _copy_identity(row)
    market = _shelf_text(row.get("marketplace"))
    listing_id = _shelf_text(row.get("listing_id"))
    paid_value = _paid_on_date(row.get("paid_on"))
    delivered_value = _known_delivered_on(row)
    current_type = effective_sale_type(
        marketplace=market,
        stored=row.get("stored_sale_type"),
        manual=row.get("sale_type"),
    )
    labels = [label for label, _code in _SALE_TYPE_CHOICES]
    codes = {label: code for label, code in _SALE_TYPE_CHOICES}
    current_label = sale_type_label(current_type)
    st.markdown("**This copy**")
    st.caption(
        "Save writes these billing facts and the record together. "
        "A copy with both filled in is complete."
    )
    paid_col, delivered_col, item_col, type_col = st.columns(4)
    paid_on = paid_col.date_input(
        "Paid on",
        value=paid_value,
        key=f"collection-shelf-paid:{identity}:{paid_value or 'none'}",
    )
    not_delivered = delivered_col.checkbox(
        "Not delivered yet",
        value=delivered_value is None,
        key=f"collection-shelf-not-delivered:{identity}:{delivered_value or ''}",
    )
    delivered_on = delivered_col.date_input(
        "Delivered on",
        value=delivered_value,
        key=f"collection-shelf-delivered:{identity}:{delivered_value or 'none'}",
    )
    item_amount = _editor_decimal(row.get("paid"))
    item = item_col.number_input(
        "Item",
        min_value=0.0,
        value=float(item_amount or 0),
        step=0.01,
        format="%.2f",
        key=f"collection-shelf-item:{identity}",
    )
    chosen = type_col.selectbox(
        "Sale type",
        labels,
        index=labels.index(current_label) if current_label in labels else None,
        placeholder="Auction, fixed, or OBO",
        key=f"collection-shelf-sale-type:{identity}",
    )
    lot_choices, same_order = _lot_choices(row, frame)
    lot_selected: list[str] = []
    if lot_choices:
        st.caption(
            "Copies in one order share the order date and the delivery date. "
            "If one copy in the order is already delivered, the rest of the order "
            "uses that delivery date and that order date. "
            "The rest of this order is already selected. Add or remove copies."
        )
        lot_selected = st.multiselect(
            "Also these copies",
            list(lot_choices),
            default=same_order,
            key=f"collection-shelf-lot:{identity}",
        )
    save_facts = st.button("Save this copy", type="primary", key=f"collection-shelf-save:{identity}")
    save_lot = st.button(
        "Use these dates on the selected copies",
        key=f"collection-shelf-save-lot:{identity}",
    )
    st.session_state[f"collection-shelf-facts-live:{identity}"] = {
        "paid_amount": Decimal(str(item)),
        "paid_on": paid_on,
        "delivered_on": None if not_delivered else delivered_on,
        "sale_type": codes.get(str(chosen or ""), ""),
    }
    if save_lot and lot_choices:
        delivered = None if not_delivered else delivered_on
        wrote = save_shelf_dates(
            engine,
            account_id=account_id,
            marketplace=market,
            listing_id=listing_id,
            paid_on=paid_on,
            delivered_on=delivered,
        )
        for label in lot_selected:
            other = lot_choices[label]
            wrote += save_shelf_dates(
                engine,
                account_id=account_id,
                marketplace=_shelf_text(other.get("marketplace")),
                listing_id=_shelf_text(other.get("listing_id")),
                paid_on=paid_on,
                delivered_on=delivered,
            )
        if wrote:
            _advance_to_closest_open(frame, row)
            _refresh_shelf()
            return
        st.error("Could not save those dates.")
    if save_facts:
        live = st.session_state[f"collection-shelf-facts-live:{identity}"]
        _save_billing_and_record(
            row,
            account_id=account_id,
            user_id=user_id,
            frame=frame,
            paid_amount=live["paid_amount"],
            paid_on=live["paid_on"],
            delivered_on=live["delivered_on"],
            sale_type=live["sale_type"],
        )
        if (
            lot_choices
            and set(lot_selected) == set(same_order)
            and (live["paid_on"] is not None or live["delivered_on"] is not None)
        ):
            for label in lot_selected:
                other = lot_choices[label]
                save_shelf_dates(
                    engine,
                    account_id=account_id,
                    marketplace=_shelf_text(other.get("marketplace")),
                    listing_id=_shelf_text(other.get("listing_id")),
                    paid_on=live["paid_on"],
                    delivered_on=live["delivered_on"],
                )
        return
    confirm_key = f"collection-shelf-remove:{identity}"
    if st.button("Remove from shelf", key=f"collection-shelf-remove-ask:{identity}"):
        st.session_state[confirm_key] = True
    if st.session_state.get(confirm_key):
        st.caption(
            "This takes the copy off My Collection. "
            "The marketplace listing stays in Review."
        )
        if st.button(
            "Remove this copy",
            type="primary",
            key=f"collection-shelf-remove-confirm:{identity}",
        ):
            remove_shelf_copy(
                engine,
                account_id=account_id,
                marketplace=market,
                listing_id=listing_id,
            )
            st.session_state.pop(confirm_key, None)
            st.session_state.pop("collection-shelf-focus", None)
            st.session_state["collection-shelf-apply-focus"] = False
            _refresh_shelf()


def _show_billing_panel(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
) -> None:
    view = _copy_price_view(row)
    charged = dict(row)
    charged["shipping_amount"] = view["shipping"]
    charged["tax_amount"] = view["tax"]
    charged["fee_amount"] = view["fees"]
    heading, listing = st.columns([4, 1])
    with heading:
        st.markdown(
            f"**{_record_label(row.get('artist_name'), row.get('album_title') or row.get('listing_title'), _printed_matrix(row), row.get('listing_id'))}**"
        )
        paid_on = ""
        parsed_paid_on = pd.to_datetime(row.get("paid_on"), errors="coerce")
        if not pd.isna(parsed_paid_on):
            paid_on = parsed_paid_on.strftime("%Y-%m-%d")
        meta = " · ".join(
            part
            for part in (
                paid_on,
                _shelf_text(row.get("seller")),
            )
            if part
        )
        if meta:
            st.caption(meta)
    url = listing_url_for_copy(
        marketplace=_shelf_text(row.get("marketplace")),
        listing_id=_shelf_text(row.get("listing_id")),
        stored=_shelf_text(row.get("auction_url")),
    )
    if url:
        listing.link_button("Open listing", url)
    item_col, ship_col, tax_col, fee_col, landed_col = st.columns(5)
    _price_metric(item_col, "Item", view["item_usd"], view["item"], view["item_code"])
    _price_metric(
        ship_col,
        "Shipping",
        view["shipping_usd"],
        view["shipping"],
        view["charge_code"],
    )
    _price_metric(
        tax_col,
        "Tax included" if view.get("tax_inside") else "Tax",
        view["tax_usd"],
        view["tax"],
        view["charge_code"],
    )
    _price_metric(fee_col, "Fees", view["fees_usd"], view["fees"], view["charge_code"])
    landed_col.markdown(
        '<div class="collection-price-label">Landed</div>'
        f'<div class="collection-price-value">{view["landed"] or "—"}</div>',
        unsafe_allow_html=True,
    )
    if view.get("discount") is not None:
        discount_col, *_rest = st.columns(5)
        _price_metric(
            discount_col,
            "Discount",
            view["discount_usd"],
            view["discount"],
            view["charge_code"],
        )
    if view.get("refund") is not None:
        refund_col, *_rest = st.columns(5)
        _price_metric(
            refund_col,
            "Refund",
            view["refund_usd"],
            view["refund"],
            view["charge_code"],
        )
    package = _package_cost_caption(row)
    if package:
        st.caption(package)
    by_label = {line["label"]: line for line in view.get("buyee_lines") or ()}
    if by_label:
        st.caption(
            "Shipping is domestic + international. Tax is customs. "
            "Fees are plan, service, and clearance. "
            "Domestic is seller to warehouse; international is Japan to you."
        )
        charge_code = view["charge_code"]
        for group in (
            ("Domestic", "International", "Customs"),
            ("Plan fee", "Service fee", "Clearance"),
        ):
            present = [by_label[label] for label in group if label in by_label]
            if not present:
                continue
            slots = st.columns(len(present))
            for slot, line in zip(slots, present, strict=True):
                _price_metric(
                    slot,
                    line["label"],
                    line["usd"],
                    line["amount"],
                    charge_code,
                )
    _render_shelf_facts(row, account_id=account_id, user_id=user_id, frame=frame)
    money_gaps = billing_gaps(charged)
    if money_gaps:
        st.caption("Still needs: " + ", ".join(money_gaps))
    else:
        st.caption("Paid is set. In process or delivered is enough.")
    note = _shelf_text(row.get("billing_note"))
    if note:
        with st.expander("Bill"):
            st.text(note)


def _show_record_panel(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    frame: pd.DataFrame,
) -> None:
    st.markdown("**Record anatomy**")
    st.caption(
        "Same fields as Review marketplace sales. Search Discogs, then save. "
        "Save writes this record and the billing facts together."
    )
    market = _shelf_text(row.get("marketplace")).lower()
    listing_id = _shelf_text(row.get("listing_id"))
    if not market or not listing_id:
        st.caption("This copy has no id yet, so the record fields cannot be saved.")
        return
    identity = f"{market}:{listing_id}"
    pick = st.session_state.get(f"collection-discogs-pick:{identity}") or {}
    listing_cover = _shelf_text(row.get("listing_image_url"))
    discogs_cover = _shelf_text(pick.get("thumb") or row.get("discogs_thumb_url"))
    photo, discogs_photo, facts = st.columns([1, 1, 2])
    with photo:
        if listing_cover:
            st.image(listing_cover, caption="Listing", width=160)
        else:
            st.caption("No listing photo stored.")
    with discogs_photo:
        if discogs_cover:
            st.image(discogs_cover, caption="Discogs", width=160)
    with facts:
        listing_title = _display_album_title(
            row.get("album_title"),
            row.get("listing_title"),
        )
        if listing_title:
            st.caption(listing_title)
        gaps = anatomy_gaps(row)
        if gaps:
            st.caption("Still needs: " + ", ".join(gaps))
        url = listing_url_for_copy(
            marketplace=market,
            listing_id=listing_id,
            stored=_shelf_text(row.get("auction_url")),
        )
        if url:
            st.link_button("Open listing", url)
    if not collection_bulk_lot(_row_format_code(row, identity)):
        _render_discogs_lookup(
            row,
            identity,
            account_id=account_id,
            user_id=user_id,
        )
    _render_anatomy_form(
        row,
        account_id=account_id,
        user_id=user_id,
        identity=identity,
        frame=frame,
    )


def _render_discogs_lookup(
    row: dict[str, object],
    identity: str,
    *,
    account_id: str,
    user_id: str,
) -> None:
    st.markdown("**Look up on Discogs**")
    st.caption(
        "Type a year, an album name, or a catalog number. "
        "A year lists every release Discogs dates to that year for this artist, "
        "in every format, including compilations and appearances. "
        "A catalog number is searched across Discogs, including a soundtrack "
        "filed under another artist."
    )
    catalog = _printed_catalog(row) or _shelf_text(
        row.get("manual_catalog_number") or row.get("catalog_number")
    )
    artist = _shelf_text(row.get("artist_name"))
    query_key = f"collection-discogs-q:{identity}"
    if query_key not in st.session_state:
        st.session_state[query_key] = catalog
    search_col, action_col = st.columns([3, 1])
    with search_col:
        query = st.text_input(
            "Catalog, artist, or title",
            key=query_key,
            placeholder="1972, 女記者, or MR 3037",
        )
    with action_col:
        st.write("")
        run = st.button("Search Discogs", key=f"collection-discogs-go:{identity}")
    hits_key = f"collection-discogs-hits:{identity}"
    if run:
        client = DiscogsClient(timeout=8.0)
        try:
            listing_title = _display_album_title(
                row.get("album_title"),
                row.get("listing_title"),
            )
            hits = search_user_catalog(
                client,
                artist=artist or None,
                title=listing_title or None,
                query=str(query or "").strip(),
                listing_media=(
                    _shelf_text(row.get("media_type"))
                    or purchase_media(
                        listing_title,
                        _shelf_text(row.get("billing_note")),
                    )
                    or None
                ),
            )
        except DiscogsRateLimitError:
            st.warning("Discogs rate limit — wait a minute, then search again.")
            hits = []
        except DiscogsUnavailableError:
            st.warning("Discogs did not finish this search. Try the catalog again.")
            hits = []
        st.session_state[hits_key] = hits
    hits = st.session_state.get(hits_key) or []
    if run and not hits:
        st.info("Discogs has nothing under that catalog or title.")
        return
    pick_key = f"collection-discogs-pick:{identity}"
    chosen = st.session_state.get(pick_key)
    if chosen:
        st.caption(
            f"Using Discogs {chosen.get('title') or ''} · {chosen.get('catno') or ''}"
        )
    for hit in list(hits)[:8]:
        cover, body, use = st.columns([1, 3, 1])
        thumb = shortlist_field(hit, "thumb", "thumb_url")
        if thumb:
            cover.image(thumb, width=72)
        body.write(str(shortlist_field(hit, "title") or ""))
        formats = shortlist_field(hit, "format", "formats") or ()
        if isinstance(formats, str):
            format_label = formats
        else:
            format_label = ", ".join(str(part) for part in formats if part)
        body.caption(
            " · ".join(
                part
                for part in (
                    str(shortlist_field(hit, "catno") or ""),
                    str(shortlist_field(hit, "year") or ""),
                    str(shortlist_field(hit, "country") or ""),
                    format_label,
                )
                if part
            )
        )
        discogs_id = shortlist_field(hit, "id", "discogs_id")
        if use.button("Use this", key=f"collection-discogs-use:{identity}:{discogs_id}"):
            try:
                release_id = int(discogs_id)
            except (TypeError, ValueError):
                st.warning("That Discogs row has no release id.")
                continue
            if not ensure_anatomy_copy(
                engine,
                account_id=account_id,
                user_id=user_id,
                marketplace=_shelf_text(row.get("marketplace")),
                listing_id=_shelf_text(row.get("listing_id")),
            ):
                st.error("Could not save those record fields on this copy.")
                continue
            try:
                applied = apply_release_choice(
                    engine,
                    marketplace=_shelf_text(row.get("marketplace")),
                    listing_id=_shelf_text(row.get("listing_id")),
                    release_id=release_id,
                )
            except DiscogsRateLimitError:
                st.warning("Discogs rate limit — wait a minute, then search again.")
                continue
            except DiscogsUnavailableError:
                st.warning("Discogs did not finish this release. Try Use this again.")
                continue
            values = anatomy_values_from_choice(
                applied,
                printed_catalog=_printed_catalog(row) or None,
            )
            wrote = save_copy_anatomy(
                engine,
                account_id=account_id,
                user_id=user_id,
                marketplace=_shelf_text(row.get("marketplace")),
                listing_id=_shelf_text(row.get("listing_id")),
                values=values,
            )
            if not wrote:
                st.error("Could not save those record fields on this copy.")
                continue
            propagate_catalog_identity_to_siblings(
                engine,
                account_id=account_id,
                user_id=user_id,
                marketplace=_shelf_text(row.get("marketplace")),
                listing_id=_shelf_text(row.get("listing_id")),
                values=values,
                pressing_id=applied.get("pressing_id"),
                thumb_url=applied.get("discogs_thumb_url") or thumb,
            )
            st.session_state[pick_key] = {
                "catno": values.get("manual_catalog_number"),
                "country": applied.get("country"),
                "title": shortlist_field(hit, "title"),
                "thumb": applied.get("discogs_thumb_url") or thumb,
                "uri": shortlist_field(hit, "uri"),
            }
            st.session_state.pop(f"collection-anatomy-catalog:{identity}", None)
            st.session_state.pop(f"collection-anatomy-region:{identity}", None)
            st.session_state.pop(f"collection-anatomy-discs:{identity}", None)
            st.session_state.pop(f"collection-anatomy-press:{identity}", None)
            _refresh_shelf()


def _choice_or_unset(value: object, options: tuple[str, ...]) -> str:
    text = _shelf_text(value)
    if text in options:
        return text
    if text in {"True", "true", "Yes"}:
        return "Yes"
    if text in {"False", "false", "No"}:
        return "No"
    return _UNSET


def _lp_insert_choice(row: dict[str, object]) -> str:
    saved = notes_insert_fact(row.get("manual_completeness_notes"))
    if saved == PINUP_INSERT_NOTE:
        return "Pin-up is the insert"
    if saved == INSERT_ONLY_NOTE:
        return "Insert only"
    if saved == FACTORY_NO_INSERT_NOTE:
        return "Factory no insert"
    flag = _choice_or_unset(row.get("manual_insert_present"), _TRI_OPTIONS)
    if flag == "Yes":
        return "Yes"
    if flag == "No":
        return MISSING_INSERT
    return _UNSET


def _tri_stored(choice: str) -> bool | None:
    if choice == "Yes":
        return True
    if choice == "No":
        return False
    return None


def _grade_or_unset(value: object) -> str:
    text = _shelf_text(value)
    if text in _GRADE_OPTIONS:
        return text
    return _UNSET


def _render_lot_counts(
    row: dict[str, object],
    identity: str,
    format_code: str,
) -> None:
    """Count the pile. Mixed lots name each format, like Review marketplace sales."""

    title = _display_album_title(row.get("album_title"), row.get("listing_title"))
    if format_code == "MIXED_BULK_LOT":
        st.caption(
            "This sale has more than one format. "
            "Choose the formats in the pile, then enter how many of each. "
            "Discogs identity stays off."
        )
        mix_formats = ("LP", "EP", "CD", "Cassette")
        mix_key = f"collection-lot-mix:{identity}"
        saved_mix = lot_mix_from_notes(row.get("manual_completeness_notes"))
        initial_mix = saved_mix or lot_mix_from_title(title)
        if mix_key not in st.session_state:
            st.session_state[mix_key] = [
                name for name in mix_formats if name in initial_mix
            ]
        chosen_formats = st.multiselect(
            "Formats in this lot",
            list(mix_formats),
            key=mix_key,
            help="Pick every format in the pile. A count appears for each one you pick.",
        )
        mix_nouns = {
            "LP": "LPs",
            "EP": "EPs",
            "CD": "CDs",
            "Cassette": "Cassettes",
        }
        if chosen_formats:
            count_columns = st.columns(len(chosen_formats))
            for column, name in zip(count_columns, chosen_formats, strict=True):
                count_key = f"collection-lot-mix-count:{identity}:{name}"
                if count_key not in st.session_state:
                    st.session_state[count_key] = int(initial_mix.get(name) or 0)
                with column:
                    st.number_input(
                        mix_nouns[name],
                        min_value=0,
                        max_value=20000,
                        step=1,
                        key=count_key,
                    )
        else:
            st.caption("Choose at least one format.")
        return
    counted = lot_count_noun(format_code)
    counted_label = counted if counted in {"CDs", "EPs"} else counted.lower()
    st.caption(
        "This sale is not one title. "
        f"Count the {counted_label}, give the pile one grade, and save. "
        "Discogs identity stays off."
    )
    discs_key = f"collection-anatomy-discs:{identity}"
    if discs_key not in st.session_state:
        stored_discs = _editor_decimal(row.get("manual_disc_count"))
        st.session_state[discs_key] = int(stored_discs) if stored_discs else 0
    st.number_input(
        f"{counted} in the lot",
        min_value=0,
        max_value=20000,
        step=1,
        key=discs_key,
    )


def _render_anatomy_form(
    row: dict[str, object],
    *,
    account_id: str,
    user_id: str,
    identity: str,
    frame: pd.DataFrame,
) -> None:
    catalog_key = f"collection-anatomy-catalog:{identity}"
    region_key = f"collection-anatomy-region:{identity}"
    format_key = f"collection-anatomy-format:{identity}"
    if catalog_key not in st.session_state:
        st.session_state[catalog_key] = _shelf_text(
            row.get("manual_catalog_number") or row.get("catalog_number")
        )
    if region_key not in st.session_state:
        st.session_state[region_key] = _choice_or_unset(
            row.get("manual_region"),
            _REGION_OPTIONS,
        )
    if format_key not in st.session_state:
        st.session_state[format_key] = collection_media_label(
            row.get("manual_media_type") or row.get("media_type")
        )
    st.markdown("**Pressing identification**")
    type_col, catalog_col, region_col, press_col = st.columns(4)
    with type_col:
        format_label = st.selectbox(
            "Media type",
            COLLECTION_MEDIA_LABELS,
            key=format_key,
            help=(
                "CD, DVD, Cassette, Laserdisc, EP, LP, or Box set. "
                "LP bulk lot, EP bulk lot, CD bulk lot, Cassette bulk lot, "
                "Mixed bulk lot, or Bulk lot is a pile: pick the formats, "
                "then count the copies."
            ),
        )
    format_code = collection_media_code(
        format_label,
        stored=row.get("manual_media_type") or row.get("media_type"),
    )
    profile = condition_profile(
        format_code or _shelf_text(row.get("media_type")) or None
    )
    kind = str(profile.get("kind") or "other")
    lot_mode = collection_bulk_lot(format_code)
    if lot_mode:
        region = _UNSET
        with catalog_col:
            st.caption("A pile has no single catalog.")
        with region_col:
            st.caption("Discogs identity stays off.")
        with press_col:
            st.caption("Count the copies in the lot.")
        _render_lot_counts(row, identity, format_code)
    else:
        with catalog_col:
            catalog = st.text_input("Catalog / matrix number", key=catalog_key)
        with region_col:
            region = st.selectbox("Region", _REGION_OPTIONS, key=region_key)
        with press_col:
            press_key = f"collection-anatomy-press:{identity}"
            if press_key not in st.session_state:
                st.session_state[press_key] = _choice_or_unset(
                    row.get("manual_pressing_type"),
                    _PRESSING_TYPE_OPTIONS,
                )
            pressing = st.selectbox(
                "Pressing type",
                _PRESSING_TYPE_OPTIONS,
                key=press_key,
            )
        discs_key = f"collection-anatomy-discs:{identity}"
        if discs_key not in st.session_state:
            stored_discs = _editor_decimal(row.get("manual_disc_count"))
            st.session_state[discs_key] = int(stored_discs) if stored_discs else 1
        st.number_input(
            "Disc count",
            min_value=1,
            step=1,
            key=discs_key,
            help="1 is a single sleeve. 2 is a double LP / gatefold. 3 is a trifold. 4 or 5 is a box set.",
        )
    st.markdown("**Condition and assessment**")
    if profile.get("caption"):
        st.caption(str(profile["caption"]))
    if lot_mode:
        record_col, verdict_col = st.columns(2)
        cover = _UNSET
    else:
        record_col, jacket_col, verdict_col = st.columns(3)
    with record_col:
        media = st.selectbox(
            str(profile.get("media_label") or "Record"),
            _GRADE_OPTIONS,
            index=_option_index(_grade_or_unset(row.get("manual_condition_media")), _GRADE_OPTIONS),
            key=f"collection-anatomy-media:{identity}",
        )
    if not lot_mode:
        with jacket_col:
            cover_label = str(profile.get("cover_label") or "Jacket")
            cover = st.selectbox(
                cover_label,
                _GRADE_OPTIONS,
                index=_option_index(_grade_or_unset(row.get("manual_condition_cover")), _GRADE_OPTIONS),
                key=f"collection-anatomy-cover:{identity}",
            )
    with verdict_col:
        verdict = st.selectbox(
            "Verdict",
            _VERDICT_OPTIONS,
            index=_option_index(
                _choice_or_unset(row.get("manual_verdict"), _VERDICT_OPTIONS),
                _VERDICT_OPTIONS,
            ),
            key=f"collection-anatomy-verdict:{identity}",
        )
    if not lot_mode:
        st.markdown("**Edition and completeness**")
        japan_market = obi_for_region(region)
        show_obi = profile.get("show_obi") == "yes" and japan_market
        show_poster = profile.get("show_poster") == "yes"
        lp_pack = kind == "lp"
        if lp_pack:
            st.caption(
                "Complete means this copy still has what the factory included. "
                "Insert and poster together, insert only, pin-up as the insert, "
                "or pin-up as the poster only. "
                "Obi is only on a Japanese pressing."
            )
        slots: list[str] = []
        if show_obi:
            slots.append("obi")
        slots.append("insert")
        if show_poster:
            slots.append("poster")
        slots.extend(("rental", "sealed"))
        columns = st.columns(len(slots))
        column_for = dict(zip(slots, columns, strict=True))
        obi_choice = "No"
        if show_obi:
            obi_key = f"collection-anatomy-obi:{identity}"
            if obi_key not in st.session_state:
                st.session_state[obi_key] = _choice_or_unset(
                    row.get("manual_obi"),
                    _TRI_OPTIONS,
                )
            with column_for["obi"]:
                obi_choice = st.selectbox("Obi", _TRI_OPTIONS, key=obi_key)
        insert_key = f"collection-anatomy-insert:{identity}:{kind}"
        insert_options = _LP_INSERT_OPTIONS if lp_pack else _TRI_OPTIONS
        if insert_key not in st.session_state:
            st.session_state[insert_key] = (
                _lp_insert_choice(row) if lp_pack else _choice_or_unset(
                    row.get("manual_insert_present"),
                    _TRI_OPTIONS,
                )
            )
        with column_for["insert"]:
            insert_choice = st.selectbox(
                str(profile.get("insert_label") or "Insert"),
                insert_options,
                key=insert_key,
            )
        poster_choice = "No"
        if show_poster:
            poster_key = f"collection-anatomy-poster:{identity}"
            poster_options = _LP_POSTER_OPTIONS if lp_pack else _TRI_OPTIONS
            owns_poster = lp_pack and insert_owns_poster(str(insert_choice))
            if owns_poster:
                _set_widget_if_changed(poster_key, "No")
            elif poster_key not in st.session_state:
                stored_poster = _choice_or_unset(
                    row.get("manual_poster_present"),
                    _TRI_OPTIONS,
                )
                st.session_state[poster_key] = stored_poster
            with column_for["poster"]:
                poster_choice = st.selectbox(
                    str(profile.get("poster_label") or "Poster / pin-up"),
                    poster_options,
                    key=poster_key,
                    disabled=owns_poster,
                    help=(
                        "No. Factory no insert, insert only, and pin-up as the insert "
                        "have no extra poster or pin-up."
                        if owns_poster
                        else "Yes means insert and poster together. "
                        "Pin-up is the poster only means that pin-up is the extra paper."
                    ),
                )
        rental_key = f"collection-anatomy-rental:{identity}"
        if rental_key not in st.session_state:
            st.session_state[rental_key] = _choice_or_unset(
                row.get("manual_rental"),
                _TRI_OPTIONS,
            )
        with column_for["rental"]:
            rental = st.selectbox("Rental", _TRI_OPTIONS, key=rental_key)
        sealed_key = f"collection-anatomy-sealed:{identity}"
        can_seal = sealed_allowed_for_grades(media, cover)
        if not can_seal:
            _set_widget_if_changed(sealed_key, "No")
        elif sealed_key not in st.session_state:
            st.session_state[sealed_key] = sealed_choice_for_grades(
                media,
                cover,
                _choice_or_unset(row.get("manual_sealed"), _TRI_OPTIONS),
            )
        with column_for["sealed"]:
            sealed = st.selectbox(
                "Sealed",
                _TRI_OPTIONS,
                key=sealed_key,
                disabled=not can_seal,
                help=(
                    "No. A copy graded below mint is not sealed."
                    if not can_seal
                    else "Yes only when Record and Jacket are M or S."
                ),
            )
        if lp_pack:
            st.caption(
                factory_pack_sentence(
                    obi_label_for_region(obi_choice, region),
                    str(insert_choice),
                    str(poster_choice),
                )
            )
    notes_key = f"collection-anatomy-notes:{identity}"
    if notes_key not in st.session_state:
        raw_notes = notes_without_insert_fact(row.get("manual_completeness_notes"))
        st.session_state[notes_key] = (
            notes_without_lot_mix(raw_notes) if lot_mode else raw_notes
        )
    notes = st.text_area(
        "Lot notes" if lot_mode else "Completeness / pressing notes",
        key=notes_key,
        height=80,
    )
    if st.button("Save this record", type="primary", key=f"collection-anatomy-save:{identity}"):
        live = st.session_state.get(f"collection-shelf-facts-live:{_copy_identity(row)}") or {}
        if "paid_amount" in live:
            paid_amount = live["paid_amount"]
        else:
            paid_amount = _editor_decimal(row.get("paid")) or Decimal("0")
        _save_billing_and_record(
            row,
            account_id=account_id,
            user_id=user_id,
            frame=frame,
            paid_amount=paid_amount,
            paid_on=live["paid_on"] if "paid_on" in live else _paid_on_date(row.get("paid_on")),
            delivered_on=(
                live["delivered_on"]
                if "delivered_on" in live
                else _paid_on_date(row.get("delivered_on"))
            ),
            sale_type=(
                str(live["sale_type"])
                if "sale_type" in live
                else str(row.get("sale_type") or "")
            ),
        )
        return


def _option_index(value: str, options: tuple[str, ...]) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _render_speed_fill(
    copies: list[dict[str, object]],
    *,
    account_id: str,
    user_id: str,
) -> None:
    """Set media type and disc count on every selected copy. Grades stay."""

    count = len(copies)
    st.markdown("**Speed fill**")
    st.caption(
        f"{count} copies selected. Media type and disc count go on all of them. "
        "1 is a single sleeve. 2 is a double LP / gatefold. 3 is a trifold. "
        "4 or 5 is a box set. Condition and the form below stay on each copy."
    )
    media_col, disc_col, go_col = st.columns([2, 1, 1])
    with media_col:
        format_label = st.selectbox(
            "Media type",
            COLLECTION_MEDIA_LABELS,
            key="collection-speed-media",
        )
    with disc_col:
        discs = st.number_input(
            "Disc count",
            min_value=1,
            step=1,
            key="collection-speed-discs",
            help="1 is a single sleeve. 2 is a double LP / gatefold. 3 is a trifold. 4 or 5 is a box set.",
        )
    with go_col:
        st.write("")
        apply = st.button(
            f"Apply to {count} copies",
            type="primary",
            key="collection-speed-apply",
        )
    if not apply:
        return
    format_code = collection_media_code(format_label)
    identities = [
        (
            _shelf_text(row.get("marketplace")),
            _shelf_text(row.get("listing_id")),
        )
        for row in copies
        if _shelf_text(row.get("marketplace")) and _shelf_text(row.get("listing_id"))
    ]
    wrote = apply_common_record_fields(
        engine,
        account_id=account_id,
        user_id=user_id,
        copies=identities,
        media_type=format_code,
        disc_count=int(discs),
    )
    if wrote:
        st.success(
            f"Set media type and disc count on {wrote} "
            f"{'copy' if wrote == 1 else 'copies'}."
        )
        _refresh_shelf()
        return
    st.warning("Pick a media type or a disc count, then apply.")


def _show_collected(
    frame: pd.DataFrame,
    *,
    account_id: str,
    user_id: str,
) -> dict[str, object] | None:
    if frame.empty:
        st.info("Nothing is on the shelf yet. Bring in a purchase above, or add one copy.")
        return None
    _show_fill_status()
    _render_catalog_fill(frame, account_id=account_id, user_id=user_id)
    table = frame.reset_index(drop=True).copy()
    views = [_copy_price_view(row) for row in table.to_dict("records")]
    table["record"] = [
        _record_label(
            artist,
            _shelf_text(title) or _shelf_text(listing),
            catalog,
            listing_id,
            media,
        )
        for artist, title, listing, catalog, listing_id, media in zip(
            table["artist_name"],
            table["album_title"],
            table["listing_title"] if "listing_title" in table.columns
            else [""] * len(table),
            table["catalog_number"],
            table["listing_id"] if "listing_id" in table.columns
            else [""] * len(table),
            table["media_type"] if "media_type" in table.columns
            else [""] * len(table),
            strict=True,
        )
    ]
    table["item_scan"] = [view["item_scan"] for view in views]
    table["shipping_scan"] = [view["shipping_scan"] for view in views]
    table["tax_scan"] = [view["tax_scan"] for view in views]
    table["fees_scan"] = [view["fees_scan"] for view in views]
    table["landed_scan"] = [view["landed_scan"] for view in views]
    table["paid_on"] = pd.to_datetime(table["paid_on"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    if "delivered_on" not in table.columns:
        table["delivered_on"] = pd.NaT
    table["delivered_on"] = pd.to_datetime(
        table["delivered_on"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    stored_types = (
        table["stored_sale_type"]
        if "stored_sale_type" in table.columns
        else [""] * len(table)
    )
    manual_types = (
        table["sale_type"] if "sale_type" in table.columns else [""] * len(table)
    )
    table["type_scan"] = [
        sale_type_label(
            effective_sale_type(
                marketplace=market,
                stored=stored,
                manual=manual,
            )
        )
        for market, stored, manual in zip(
            table["marketplace"],
            stored_types,
            manual_types,
            strict=True,
        )
    ]
    table["row_key"] = [
        f"{_shelf_text(row.get('marketplace'))}:{_shelf_text(row.get('listing_id'))}"
        for row in table.to_dict("records")
    ]
    covers = (
        [_shelf_text(url) for url in table["cover_url"]]
        if "cover_url" in table.columns
        else [""] * len(table)
    )
    apply_focus = bool(st.session_state.get("collection-shelf-apply-focus"))
    focus = str(st.session_state.get("collection-shelf-focus") or "")
    show_buyee_split = any(
        {
            label
            for label, _amount in buyee_package_display_lines(
                _shelf_text(row.get("billing_note")),
                package_shipping=_editor_decimal(row.get("package_shipping")),
                package_tax=_editor_decimal(row.get("package_tax")),
            )
        }
        & {"Domestic", "International"}
        for row in table.to_dict("records")
    )
    columns: dict[str, object] = {
        "Cover": covers,
        "Artist": (
            table["artist_section"]
            if "artist_section" in table.columns
            else table["artist_name"]
        ),
        "Record": table["record"],
        "Filled": [
            "Filled" if shelf_copy_filled(row) else ""
            for row in table.to_dict("records")
        ],
        "Item": table["item_scan"],
        "Shipping": table["shipping_scan"],
    }
    if show_buyee_split:
        columns["Domestic"] = [_buyee_scan(view, "Domestic") for view in views]
        columns["Intl"] = [_buyee_scan(view, "International") for view in views]
    columns["Tax"] = table["tax_scan"]
    columns["Fees"] = table["fees_scan"]
    columns["Landed"] = table["landed_scan"]
    columns["Paid on"] = table["paid_on"]
    columns["Delivered"] = table["delivered_on"]
    columns["Type"] = table["type_scan"]
    columns["marketplace"] = table["marketplace"]
    columns["listing_id"] = table["listing_id"]
    columns["row_key"] = table["row_key"]
    columns["__focus_row"] = [
        "1" if apply_focus and str(key) == focus else "0"
        for key in table["row_key"]
    ]
    display = pd.DataFrame(columns)
    st.caption(
        "One artist, then the next. The artist you bought first comes first, "
        "and that artist's oldest copy is first. "
        "Click a row — the whole album, not one cell. "
        "The header checkbox selects every copy. "
        "Shift-click or drag the checkboxes for a run of rows. "
        "Two or more selected copies can take media type and disc count together. "
        "Item is the record price. Landed is in US dollars. "
        "eBay is one Shipping amount. Buyee also lists Domestic (seller to warehouse) "
        "and Intl (Japan to you) when those lines are on the invoice. "
        "Yen and other foreign charges stay in the row you click, converted into that dollar total. "
        "Click a Buyee row for plan, service, clearance, and customs. "
        "Use Fill in the breakdown under this table. The item price stays as it is."
    )
    money_columns = [
        {
            "field": "Item",
            "width": 110,
            "type": "rightAligned",
        },
        {
            "field": "Shipping",
            "width": 110,
            "type": "rightAligned",
        },
    ]
    if show_buyee_split:
        money_columns.extend(
            [
                {
                    "field": "Domestic",
                    "width": 100,
                    "type": "rightAligned",
                },
                {
                    "field": "Intl",
                    "width": 100,
                    "type": "rightAligned",
                },
            ]
        )
    money_columns.extend(
        [
            {
                "field": "Tax",
                "width": 100,
                "type": "rightAligned",
            },
            {
                "field": "Fees",
                "width": 100,
                "type": "rightAligned",
            },
            {
                "field": "Landed",
                "width": 120,
                "type": "rightAligned",
            },
        ]
    )
    row_count = max(len(display), 1)
    response = AgGrid(
        display,
        gridOptions={
            "columnDefs": [
                {
                    "field": "Cover",
                    "width": 72,
                    "minWidth": 64,
                    "maxWidth": 80,
                    "sortable": False,
                    "cellRenderer": _SHELF_COVER_RENDERER,
                },
                {
                    "field": "Artist",
                    "width": 150,
                    "minWidth": 120,
                },
                {
                    "field": "Record",
                    "flex": 1,
                    "minWidth": 180,
                },
                {
                    "field": "Filled",
                    "width": 90,
                    "minWidth": 80,
                },
                *money_columns,
                {
                    "field": "Paid on",
                    "width": 120,
                },
                {
                    "field": "Delivered",
                    "width": 120,
                },
                {
                    "field": "Type",
                    "width": 110,
                },
                {
                    "field": "marketplace",
                    "hide": True,
                },
                {
                    "field": "listing_id",
                    "hide": True,
                },
                {
                    "field": "row_key",
                    "hide": True,
                },
                {
                    "field": "__focus_row",
                    "hide": True,
                },
            ],
            "defaultColDef": {
                "sortable": True,
                "resizable": True,
                "filter": False,
                "editable": False,
            },
            "rowSelection": {
                "mode": "multiRow",
                "checkboxes": True,
                "headerCheckbox": True,
                "enableClickSelection": True,
            },
            "cellSelection": False,
            "suppressCellFocus": True,
            "animateRows": False,
            "ensureDomOrder": True,
            "rowHeight": 52,
            "headerHeight": 44,
            "getRowId": _SHELF_ROW_ID,
            "onFirstDataRendered": _SELECT_FOCUS_ROW,
        },
        height=min(44 + row_count * 56 + 8, 44 + 12 * 56 + 8),
        theme="streamlit",
        update_on=["selectionChanged"],
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        show_toolbar=False,
        show_search=False,
        show_download_button=False,
        custom_css={
            ".ag-row": {
                "cursor": "pointer !important",
            },
            ".ag-row-hover": {
                "background-color": "rgba(255, 75, 75, 0.08) !important",
            },
            ".ag-row-selected": {
                "background-color": "rgba(255, 75, 75, 0.14) !important",
                "box-shadow": "inset 4px 0 0 rgb(255, 75, 75) !important",
            },
            ".ag-row-selected .ag-cell": {
                "background-color": "transparent !important",
            },
            ".ag-cell-focus": {
                "border": "none !important",
                "outline": "none !important",
            },
            ".ag-cell": {
                "display": "flex",
                "align-items": "center",
                "overflow": "hidden",
            },
            ".ag-header-cell": {
                "overflow": "hidden",
            },
        },
        key=f"collection-shelf-aggrid:{_fill_seq('collection-shelf-grid-seq')}",
    )
    if apply_focus:
        st.session_state["collection-shelf-apply-focus"] = False
    picked_rows = _aggrid_selected_rows(response)
    chosen_copies: list[dict[str, object]] = []
    seen: set[str] = set()
    for picked in picked_rows:
        row = _shelf_row_from_grid(picked, table)
        if row is None:
            continue
        identity = _copy_identity(row)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        chosen_copies.append(row)
    chosen: dict[str, object] | None = chosen_copies[-1] if chosen_copies else None
    if chosen is None and apply_focus and focus:
        for rec in table.to_dict("records"):
            if _copy_identity(rec) == focus:
                chosen = rec
                chosen_copies = [rec]
                break
    if chosen is None:
        return None
    if len(chosen_copies) >= 2:
        _render_speed_fill(
            chosen_copies,
            account_id=account_id,
            user_id=user_id,
        )
    st.session_state["collection-shelf-focus"] = _copy_identity(chosen)
    _show_selected_copy(
        chosen,
        account_id=account_id,
        user_id=user_id,
        frame=frame,
    )
    return chosen


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
    return bill_text_from_bytes(data)


def _read_dropped_page() -> list[str]:
    uploaded = st.file_uploader(
        "Drag and drop the saved order page or Buyee invoice PDF",
        type=list(_BILL_UPLOAD_TYPES),
        accept_multiple_files=True,
        help=(
            "Drop several eBay orders at once, both screenshots of one "
            "combined order, a Buyee invoice PDF, or a Record City order page."
        ),
        key=f"collection-import-file:{_fill_seq('collection-import-upload-seq')}",
    )
    pasted = st.text_area(
        "Or paste the order table",
        height=120,
        placeholder="Paste the orders here if you copied them instead of saving the page.",
        key=f"collection-import-paste:{_fill_seq('collection-import-paste-seq')}",
    )
    pages = list(st.session_state.get("collection-import-pages") or [])
    shots = list(st.session_state.get("collection-import-shots") or [])
    companion_text: list[str] = []
    if uploaded:
        texts: list[str] = []
        images: list[bytes] = []
        for file in uploaded:
            data = file.getvalue()
            if is_screenshot_bytes(data):
                images.append(data)
                continue
            try:
                texts.append(_bytes_to_bill_text(data))
            except ValueError as exc:
                st.error(str(exc))
        if texts:
            companion_text = texts
            pages = texts
            st.session_state["collection-import-pages"] = pages
        if images:
            shots = images
            st.session_state["collection-import-shots"] = shots
    extract_col, clear_col = st.columns(2)
    with extract_col:
        extract_clicked = st.button(
            "Extract bill from screenshots",
            type="primary",
            key="collection-import-extract",
            disabled=not bool(shots),
        )
    with clear_col:
        if st.button("Clear bill pages", key="collection-import-clear"):
            _clear_import_drop()
            st.rerun()
    if extract_clicked:
        # Read the screenshots in the box. A previous extract stays out of this read.
        harvested = harvest_screenshot_bills(shots, companion_text)
        if harvested.error:
            st.error(harvested.error)
        elif not harvested.shots:
            st.session_state["collection-import-pages"] = list(harvested.pages)
            st.session_state.pop("collection-import-pending", None)
            st.session_state.pop("collection-import-done", None)
            _clear_import_drop(keep_pages=True)
            st.rerun()
    for index, shot in enumerate(shots, start=1):
        st.image(shot, caption=f"Screenshot {index}")
    if shots and not pages:
        st.caption(
            "The screenshot is parked. Extract bill from screenshots reads "
            "the order, or paste the text / type shipping and tax on Billing."
        )
    parts = [part.strip() for part in (*pages, pasted) if str(part).strip()]
    raw = combine_bill_pages(parts)
    if raw:
        st.session_state["collection-import-raw"] = raw
    elif not pasted.strip() and not uploaded:
        stored = str(st.session_state.get("collection-import-raw") or "")
        return [stored] if stored.strip() else []
    return parts


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
            title=purchase.title,
            delivered_on=purchase.delivered_on,
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
        "Several eBay orders in one drop stay separate purchases. "
        "A combined eBay order still brings in every album in that package. "
        "Gripsweat rows use the eBay item number. "
        "The item price, date, seller, and catalog are filled in. "
        "The bill keeps the charges and leaves out names and addresses. "
        "Magazines, photos, posters, and pins are left out."
    )
    parsed = parse_purchase_pages(_read_dropped_page())
    parsed = _record_city_with_discogs(parsed)
    parked = list(st.session_state.get("collection-import-pending") or [])
    if parsed.note and not parsed.purchases and not parked:
        st.info(parsed.note)
        return
    if not parsed.purchases:
        if not parked:
            return
        parsed = replace(
            parsed,
            note="",
            purchases=tuple(parked),
            source=parsed.source or parked[0].source,
        )
    parsed = _pending_import_purchases(parsed)
    if not parsed.purchases:
        st.success("Those purchases are on the shelf.")
        _clear_import_drop()
        return

    _review_purchases(account_id, user_id, parsed, key_prefix="collection-import")


def _render_incoming_lot(ready: list, key_prefix: str) -> None:
    """One order date for the drop, including a single copy."""

    if not ready:
        return
    by_label: dict[str, str] = {}
    for match in ready:
        purchase = match.purchase
        label = " · ".join(
            part
            for part in (
                purchase.title or purchase.catalog_number or "",
                purchase.external_id,
            )
            if part
        )
        by_label[label] = purchase.external_id
    groups: dict[str, list[str]] = {}
    for match in ready:
        order_id = str(match.purchase.order_id or "").strip()
        if order_id:
            groups.setdefault(order_id, []).append(match.purchase.external_id)
    default_ids = set(max(groups.values(), key=len)) if groups else set(by_label.values())
    default_labels = [
        label for label, external_id in by_label.items() if external_id in default_ids
    ]
    order_day = next(
        (
            match.purchase.paid_on
            for match in ready
            if match.purchase.paid_on is not None
        ),
        None,
    )
    seeded = next(
        (
            match.purchase.delivered_on
            for match in ready
            if match.purchase.delivered_on is not None
        ),
        None,
    )
    lot_ids = "|".join(match.purchase.external_id for match in ready)
    one = len(ready) == 1
    st.caption(
        (
            "This copy uses the order date and the delivery date. "
            if one
            else
            "Copies in one order share the order date and the delivery date. "
            "This whole drop uses that date, including copies not on the shelf yet. "
            "Use the button only when you are changing which copies."
        )
        + (
            " This bill has no payment date — enter it once"
            + ("." if one else " for the whole lot.")
            if order_day is None
            else ""
        )
    )
    paid_on = st.date_input(
        "Order date",
        value=order_day,
        key=f"{key_prefix}-order-date:{lot_ids}:{order_day or 'none'}",
    )
    st.session_state[f"{key_prefix}-lot-paid-on"] = paid_on
    not_delivered = st.checkbox(
        "Not delivered yet",
        value=seeded is None,
        key=f"{key_prefix}-not-delivered:{lot_ids}:{seeded or 'none'}",
    )
    delivered_on = st.date_input(
        "Delivered on",
        value=seeded,
        key=f"{key_prefix}-delivered-on:{lot_ids}:{seeded or 'none'}",
    )
    if one:
        selected_ids = list(by_label.values())
        adjusting = False
    else:
        chosen = st.multiselect(
            "These copies",
            list(by_label),
            default=default_labels,
            key=f"{key_prefix}-lot-copies:{lot_ids}",
        )
        selected_ids = [by_label[label] for label in chosen]
        adjusting = set(selected_ids) != set(default_ids)
    apply_dates = False
    if adjusting:
        apply_dates = st.button("Use these dates on the selected copies")
        if not apply_dates:
            return
    elif paid_on is None and (not_delivered or delivered_on is None):
        return
    delivered = None if not_delivered or not delivered_on else delivered_on
    if paid_on is None and delivered is None:
        return
    stamped = stamp_lot_dates(
        [
            LotCopy(
                marketplace=str(match.purchase.source or ""),
                listing_id=match.purchase.external_id,
                order_id=str(match.purchase.order_id or ""),
                paid_on=match.purchase.paid_on,
                delivered_on=match.purchase.delivered_on,
            )
            for match in ready
        ],
        paid_on=paid_on,
        delivered_on=delivered,
        selected_ids=selected_ids,
        explicit=adjusting,
    )
    overrides = st.session_state.setdefault(f"{key_prefix}-lot-dates", {})
    changed = False
    for copy in stamped:
        payload = {
            "paid_on": copy.paid_on.isoformat() if copy.paid_on else "",
            "delivered_on": (
                copy.delivered_on.isoformat() if copy.delivered_on else ""
            ),
        }
        if overrides.get(copy.listing_id) != payload:
            overrides[copy.listing_id] = payload
            changed = True
    if not changed:
        return
    st.session_state[f"{key_prefix}-lot-stamp"] = (
        int(st.session_state.get(f"{key_prefix}-lot-stamp") or 0) + 1
    )


def _batch_editor(ready: list, key_prefix: str) -> pd.DataFrame:
    """One editable table for the whole extracted batch."""

    overrides = st.session_state.get(f"{key_prefix}-lot-dates") or {}
    stamp = int(st.session_state.get(f"{key_prefix}-lot-stamp") or 0)
    rows = []
    for match in ready:
        purchase = match.purchase
        costs = copy_costs(purchase.billing_note)
        pressing = match.pressings[0] if match.pressings else None
        paid_on = purchase.paid_on
        delivered_on = purchase.delivered_on
        override = overrides.get(purchase.external_id) or {}
        if override.get("paid_on"):
            paid_on = date.fromisoformat(str(override["paid_on"])[:10])
        if "delivered_on" in override:
            delivered_text = str(override.get("delivered_on") or "").strip()
            delivered_on = (
                date.fromisoformat(delivered_text[:10]) if delivered_text else None
            )
        rows.append(
            {
                "Keep": True,
                "Title": purchase.title,
                "Media": _media_label(purchase_media(purchase.title, purchase.billing_note)),
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
                "Paid on": paid_on.isoformat() if paid_on else "",
                "Delivered": (
                    delivered_on.isoformat() if delivered_on else ""
                ),
                "Shipping": _editor_number(costs["shipping"]),
                "Tax": _editor_number(
                    costs["tax"]
                    if costs["tax"] is not None
                    else (
                        costs["customs"]
                        if costs["customs"] is not None
                        else (
                            costs.get("tax_included")
                            if costs.get("tax_included") is not None
                            else buyee_tax_included(purchase)
                        )
                    )
                ),
                "Plan fee": _editor_number(costs["plan_fee"]),
                "Service fee": _editor_number(costs["service_fee"]),
                "Domestic shipping": _editor_number(costs["domestic_shipping"]),
                "Bill": purchase.billing_note,
                "Seller": purchase.seller,
                "Id": purchase.external_id,
            }
        )
    frame = pd.DataFrame(rows)
    optional = ["Plan fee", "Service fee", "Domestic shipping"]
    for column in optional:
        if column in frame.columns and not frame[column].fillna(0).astype(float).gt(0).any():
            frame = frame.drop(columns=[column])
    lot_international = next(
        (
            match.purchase.package_shipping
            for match in ready
            if match.purchase.package_shipping is not None
        ),
        None,
    )
    has_copy_shipping = (
        "Shipping" in frame.columns
        and frame["Shipping"].fillna(0).astype(float).gt(0).any()
    )
    included_tax = any(
        copy_costs(match.purchase.billing_note).get("tax_included") is not None
        or (
            copy_costs(match.purchase.billing_note)["tax"] is None
            and buyee_tax_included(match.purchase) is not None
        )
        for match in ready
    )
    ordered = arrange_lot_columns(
        list(frame.columns),
        package_shipping=lot_international,
        has_copy_shipping=has_copy_shipping,
    )
    if "International" in ordered and "International" not in frame.columns:
        frame["International"] = float(lot_international)
    frame = frame[ordered]
    disabled = ["Seller", "Id", "Media"]
    if "International" in frame.columns:
        disabled.append("International")
    return st.data_editor(
        frame,
        hide_index=True,
        width="stretch",
        num_rows="fixed",
        disabled=disabled,
        key=(
            f"{key_prefix}-batch:{stamp}:tax-inside-v2:"
            + hashlib.sha256(
                "|".join(
                    f"{match.purchase.external_id}:{match.purchase.paid_amount}:"
                    f"{match.purchase.catalog_number}:{match.purchase.billing_note}:"
                    f"{(overrides.get(match.purchase.external_id) or {}).get('paid_on', '')}"
                    for match in ready
                ).encode()
            ).hexdigest()
        ),
        column_config={
            "Keep": st.column_config.CheckboxColumn("Keep"),
            "Paid": st.column_config.NumberColumn("Item price"),
            "Shipping": st.column_config.NumberColumn("Shipping"),
            "International": st.column_config.NumberColumn(
                "International (lot)",
                help="Shared by this lot. Not added again on each copy.",
            ),
            "Tax": st.column_config.NumberColumn(
                "Tax included" if included_tax else "Tax",
                help=(
                    "10% already inside the item price. The price you see is 110%. "
                    "This is not added on top."
                    if included_tax
                    else None
                ),
            ),
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
    delivered_on = (
        _editor_date(row["Delivered"]) if "Delivered" in row.index else purchase.delivered_on
    )
    currency = str(row["Currency"] or purchase.paid_currency or "").strip()
    bill_costs = copy_costs(str(row["Bill"] or purchase.billing_note or ""))
    tax_inside = bill_costs.get("tax_included") is not None or (
        bill_costs["tax"] is None and buyee_tax_included(purchase) is not None
    )
    tax_amount = _editor_decimal(row["Tax"]) if "Tax" in row.index else None
    billing_note = note_with_copy_costs(
        str(row["Bill"] or ""),
        shipping=(
            _editor_decimal(row["Shipping"]) if "Shipping" in row.index else None
        ),
        tax=None if tax_inside else tax_amount,
        plan_fee=(
            _editor_decimal(row["Plan fee"]) if "Plan fee" in row.index else None
        ),
        service_fee=(
            _editor_decimal(row["Service fee"]) if "Service fee" in row.index else None
        ),
        domestic_shipping=(
            _editor_decimal(row["Domestic shipping"])
            if "Domestic shipping" in row.index
            else None
        ),
        currency=currency or purchase.paid_currency,
    )
    if tax_inside:
        billing_note = note_with_included_tax(
            billing_note,
            tax_amount,
            currency or purchase.paid_currency or "JPY",
        )
    edited = replace(
        purchase,
        title=title,
        catalog_number=catalog or None,
        paid_amount=paid_amount,
        paid_currency=currency or purchase.paid_currency,
        paid_on=paid_on,
        delivered_on=delivered_on,
        billing_note=billing_note,
    )
    stored_catalog, stored_pressing = pressing_for_edited_catalog(pressing, catalog)
    if stored_pressing is not None:
        return edited, stored_catalog, stored_pressing, paid_amount, paid_on
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
            label = _shelf_copy_label(row)
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
    *,
    matched_ids: set[str] | None = None,
) -> None:
    """Write a dropped bill onto a copy that is already on the shelf."""

    matched = {str(item) for item in (matched_ids or set()) if str(item)}
    billed = [
        purchase
        for purchase in purchases
        if _note_has_charges(purchase.billing_note)
        and str(purchase.external_id) not in matched
    ]
    options = _shelf_options(account_id)
    if not billed or not options:
        return
    st.subheader("Backfill a copy already on the shelf")
    st.caption(
        "This item number is not on the shelf. Pick the copy it belongs to. "
        "Do not leave the first album selected. "
        "Shipping, tax, and fees are written on that copy. "
        "The item price stays as it is. "
        "Bills that already matched a listing id are saved with Save these bills above."
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
        index=None,
        placeholder="Pick a copy on the shelf",
        key=f"{key_prefix}-backfill-copy-pick",
    )
    if st.button(
        "Save this breakdown on that copy",
        key=f"{key_prefix}-backfill-save",
        disabled=copy_choice is None,
    ):
        if copy_choice is None:
            st.error("Pick the copy on the shelf first.")
            return
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
    backfill = [match for match in matches if match.status == "backfill"]
    source_label = {
        "ebay": "eBay",
        "buyee": "Buyee",
        "recordcity": "Record City",
        "discogs": "Discogs",
        "log": "Logged",
    }.get(parsed.source, parsed.source)

    st.subheader(f"{source_label}: {len(parsed.purchases)} purchases")
    status_bits = []
    if ready:
        status_bits.append(f"{len(ready)} ready to add")
    if picks:
        status_bits.append(f"{len(picks)} need a catalog")
    if already or backfill:
        status_bits.append(f"{len(already) + len(backfill)} already on the shelf")
    dated = [row for row in parsed.purchases if row.delivered_on is not None]
    if dated:
        st.caption(
            f"{len(dated)} purchases include a delivery date. "
            "Save those delivery dates onto copies already on the shelf. "
            "Item prices stay as they are. A date you already set stays."
        )
        if st.button(
            "Save those delivery dates",
            key=f"{key_prefix}-delivery-dates",
        ):
            wrote = apply_delivery_dates(
                engine,
                account_id=account_id,
                purchases=dated,
            )
            if wrote:
                st.session_state["collection-shelf-fill-status"] = "delivery-saved"
                st.session_state["collection-shelf-saved-label"] = (
                    f"Delivery dates saved on {wrote} copies."
                )
                _refresh_shelf()
                return
            st.info("None of these delivery dates matched a copy already on the shelf.")
    if left_out:
        status_bits.append(f"{len(left_out)} left out")
    if status_bits:
        st.caption(" · ".join(status_bits))
    if ready and picks:
        st.info(
            f"{len(ready)} ready copies are on hold. "
            "Add or leave out a catalog below — that does not drop the rest."
        )
    lot_source = [match.purchase for match in matches]
    lot = next(
        (
            purchase
            for purchase in lot_source
            if purchase.package_shipping is not None or purchase.package_total is not None
        ),
        None,
    )
    if lot is not None:
        currency = lot.paid_currency or "JPY"
        bits = []
        if lot.package_shipping is not None:
            bits.append(f"international shipping {lot.package_shipping:,.0f} {currency}")
        if lot.package_tax is not None:
            bits.append(f"customs {lot.package_tax:,.0f} {currency}")
        if lot.package_total is not None:
            bits.append(f"grand total {lot.package_total:,.0f} {currency}")
        tally = lot_tally(lot_source)
        st.caption(
            "This lot: "
            + ", ".join(bits)
            + ". International is that lot shipping. "
            "The item price includes 10% consumption tax, shown as Tax included. "
            "Customs stays on the lot. Domestic shipping is on each record. "
            + tally.caption()
        )
        if tally.issues:
            st.warning(tally.caption())
    if ready:
        inherited = inherit_lot_dates(tuple(match.purchase for match in ready))
        by_id = {purchase.external_id: purchase for purchase in inherited}
        ready = [
            replace(
                match,
                purchase=by_id.get(match.purchase.external_id, match.purchase),
            )
            for match in ready
        ]
        st.caption(describe_lot(tuple(match.purchase for match in ready)))
        _render_incoming_lot(ready, key_prefix)
        edited = _batch_editor(ready, key_prefix)
        if st.button(
            f"Add these {len(ready)} copies",
            type="primary",
            key=f"{key_prefix}-add-ready",
        ):
            copies: list[tuple[str, str, ParsedPurchase]] = []
            added_ids: list[str] = []
            pending: list[tuple[Any, ParsedPurchase, str, int | None, Decimal | None]] = []
            for match in ready:
                row = edited.loc[edited["Id"] == match.purchase.external_id]
                if row.empty or not bool(row.iloc[0]["Keep"]):
                    continue
                purchase, catalog_number, pressing_id, paid_amount, paid_on = (
                    _purchase_from_edit(match, row.iloc[0])
                )
                pending.append(
                    (
                        match,
                        replace(purchase, paid_on=paid_on),
                        catalog_number,
                        pressing_id,
                        paid_amount,
                    )
                )
            lot_paid = st.session_state.get(f"{key_prefix}-lot-paid-on")
            if not isinstance(lot_paid, date):
                lot_paid = None
            dated = {
                purchase.external_id: purchase
                for purchase in purchases_with_lot_paid_on(
                    tuple(item[1] for item in pending),
                    paid_on=lot_paid,
                )
            }
            for match, purchase, catalog_number, pressing_id, paid_amount in pending:
                purchase = dated.get(purchase.external_id, purchase)
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
                    paid_on=purchase.paid_on,
                )
                added_ids.append(purchase.external_id)
                market, listing = bill_copy_identity(
                    match.marketplace,
                    match.listing_id,
                    purchase,
                )
                if market and listing:
                    copies.append((market, listing, purchase))
            if copies:
                save_package_bill(
                    engine,
                    account_id=account_id,
                    copies=copies,
                    user_id=user_id,
                )
            _remove_pending_purchases(added_ids)
            if not st.session_state.get("collection-import-pending"):
                _clear_import_drop()
            _refresh_shelf()
    else:
        st.caption("Nothing new is ready to add from this page.")

    billed = backfill + [
        match
        for match in already
        if _note_has_charges(match.purchase.billing_note)
    ]
    if billed:
        st.caption(
            f"{len(billed)} already on your shelf. Save the bill. "
            "The item price stays as it is."
        )
        for match in billed:
            st.write(match.purchase.title or match.purchase.catalog_number)
            st.text(match.purchase.billing_note)
        if st.button(
            "Save these bills on the shelf",
            key=f"{key_prefix}-save-bills",
        ):
            copies: list[tuple[str, str, ParsedPurchase]] = []
            for match in billed:
                save_billing_note(
                    engine,
                    account_id=account_id,
                    purchase=match.purchase,
                    marketplace=match.marketplace,
                    listing_id=match.listing_id,
                    user_id=user_id,
                    persist_bill=False,
                )
                market, listing = bill_copy_identity(
                    match.marketplace,
                    match.listing_id,
                    match.purchase,
                )
                copies.append((market, listing, match.purchase))
            if copies:
                save_package_bill(
                    engine,
                    account_id=account_id,
                    copies=copies,
                    user_id=user_id,
                )
            _clear_import_drop()
            _refresh_shelf()
    elif already:
        st.caption(f"{len(already)} already on your shelf. The item price stays as it is.")

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
                    leave_out = st.button(
                        "Leave out",
                        key=f"collection-pick-skip:{purchase.external_id}",
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
                        paid_on=paid_on,
                        paid_currency=str(currency),
                    )
                    _remove_pending_purchases([purchase.external_id])
                    _refresh_shelf()
                if leave_out:
                    _remove_pending_purchases([purchase.external_id])
                    st.rerun()

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
    _render_backfill(
        account_id,
        user_id,
        parsed.purchases,
        key_prefix,
        matched_ids={
            str(match.purchase.external_id)
            for match in billed
            if match.marketplace and match.listing_id
        },
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
    selected: dict[str, object] | None = None,
) -> None:
    """Write a bill or typed charges onto a copy already on the shelf."""

    if frame.empty:
        return
    st.subheader("Fill in the breakdown")
    st.caption(
        "Click a row on the shelf, or pick a copy here. Drop the Buyee invoice PDF, "
        "paste its bill, or type the charges in that copy’s currency. "
        "Charge lines only. The record title stays as it is. "
        "The price on each item line becomes the item price. "
        "Yen and other foreign charges stay visible, "
        "and landed adds their dollar value."
    )
    options: dict[str, dict[str, object]] = {}
    for row in frame.to_dict("records"):
        label = _shelf_copy_label(row)
        if label in options:
            label = f"{label} · {row.get('listing_id')}"
        options[label] = row
    row = selected
    if row is not None:
        st.caption(
            f"Selected: {_shelf_copy_label(row)}. "
            "A one-item totals card uses this row. Item numbers on a combined order "
            "pick those copies and write each copy’s share of shipping and tax. "
            "Paid on becomes the order date. "
            "The price on each item line becomes the item price."
        )
    else:
        choice = st.selectbox(
            "Copy",
            list(options),
            key="collection-shelf-fill-copy",
        )
        row = options[choice]
    if row is None:
        return
    currency = str(row.get("paid_currency") or "USD").upper()
    if currency not in _CURRENCIES:
        currency = "USD"
    with st.container(border=True):
        st.markdown(
            "**Drop every page of the bill.** eBay order details often need two screenshots."
        )
        uploaded = st.file_uploader(
            "Drop the Buyee invoice PDF",
            type=list(_BILL_UPLOAD_TYPES),
            accept_multiple_files=True,
            help=(
                "Drop both screenshots of View order details, the PDF, or the order text. "
                "Yen amounts stay in yen; landed adds dollars."
            ),
            key=f"collection-shelf-fill-file:{_fill_seq('collection-shelf-fill-upload-seq')}",
            label_visibility="collapsed",
        )
    pasted = st.text_area(
        "Or paste one page of the bill",
        height=140,
        placeholder="Paste page 1, add it, then paste page 2. Or paste the whole order.",
        key=f"collection-shelf-fill-bill:{_fill_seq('collection-shelf-fill-paste-seq')}",
    )
    pages = list(st.session_state.get("collection-shelf-fill-pages") or [])
    shots = list(st.session_state.get("collection-shelf-fill-shots") or [])
    if uploaded:
        texts: list[str] = []
        images: list[bytes] = []
        for file in uploaded:
            data = file.getvalue()
            if is_screenshot_bytes(data):
                images.append(data)
                continue
            try:
                texts.append(_bytes_to_bill_text(data))
            except ValueError as exc:
                st.error(str(exc))
        if texts:
            pages = texts
            st.session_state["collection-shelf-fill-pages"] = pages
        if images:
            shots = images
            st.session_state["collection-shelf-fill-shots"] = shots
    add_col, extract_col, clear_col = st.columns(3)
    with add_col:
        if st.button("Add this page to the bill", key="collection-shelf-fill-add-page"):
            if pasted.strip():
                pages = [*pages, pasted.strip()]
                st.session_state["collection-shelf-fill-pages"] = pages
                st.rerun()
    with extract_col:
        extract_clicked = st.button(
            "Extract bill from screenshots",
            type="primary",
            key="collection-shelf-fill-extract",
            disabled=not bool(shots),
        )
    with clear_col:
        if st.button("Clear bill pages", key="collection-shelf-fill-clear-pages"):
            _clear_fill_bill()
            st.rerun()
    if extract_clicked:
        harvested = harvest_screenshot_bills(shots, pages)
        if harvested.error:
            st.error(harvested.error)
        elif not harvested.shots:
            st.session_state["collection-shelf-fill-pages"] = list(harvested.pages)
            st.session_state["collection-shelf-fill-extracted"] = True
            _clear_fill_bill(keep_extracted_pages=True)
            st.rerun()
    if st.session_state.pop("collection-shelf-fill-extracted", False):
        st.caption(
            "Screenshot removed. Save this bill to move to the next unfilled copy."
        )
    for index, shot in enumerate(shots, start=1):
        st.image(shot, caption=f"Screenshot {index} of this order")
    if shots and not pages and not pasted.strip():
        st.caption(
            "The screenshot is parked. Extract bill from screenshots reads "
            "Shipping / Tax / Order total off the picture. "
            "Paste the order text, or type shipping and tax. "
            "A one-item card uses this copy. Combined 2 items totals still need every Item number."
        )
    raw = combine_bill_pages([*pages, pasted])
    if raw:
        st.session_state["collection-shelf-fill-raw"] = raw
    elif not pasted.strip() and not uploaded:
        raw = str(st.session_state.get("collection-shelf-fill-raw") or "")
    if pages:
        st.caption(f"{len(pages)} page(s) in this bill.")
    parsed = parse_purchase_export(raw) if raw.strip() else None
    billed = [
        purchase
        for purchase in (parsed.purchases if parsed is not None else ())
        if _note_has_charges(purchase.billing_note)
    ]
    if billed:
        st.session_state["collection-shelf-fill-billed"] = billed
    elif uploaded is None and not pasted.strip():
        billed = list(st.session_state.get("collection-shelf-fill-billed") or [])
    if raw.strip() and not billed:
        st.info("That page did not include a shipping, tax, or fee line.")
    if billed:
        matched, missed = preview_shelf_bills(
            billed,
            frame.to_dict("records"),
            selected=row,
        )
        st.caption(
            "Charge lines only. Yen stays yen. Dollars are the conversion, "
            "not a replacement. The record title stays as it is. "
            "Match is the listing id, not the catalog or the selected row's date."
        )
        package_ids = [
            purchase.external_id
            for purchase in billed
            if str(purchase.external_id).startswith("package:")
        ]
        if package_ids and not matched:
            st.warning(
                "This bill is more than one item and has no Item number yet. "
                "Paste View order details for each copy in the order. "
                "One Item number is enough to write that copy’s share; "
                "the rest stay skipped until their numbers are on the bill. "
                "It does not dump the package total onto the selected copy."
            )
        previews: list[tuple[dict[str, object], ParsedPurchase, str]] = []
        for pair in matched:
            target = pair["row"]
            purchase = pair["purchase"]
            preview = _bill_note_for_copy(purchase, target)
            previews.append((target, purchase, preview))
            st.write(_shelf_copy_label(target))
            clashes = bill_disagreements(purchase, target)
            if clashes:
                st.warning(
                    "The shelf date or seller is not the order. "
                    + " ".join(clashes)
                    + " Matching is the item number. "
                    "The line price becomes the item price. "
                    "Paid on becomes the order date when you save."
                )
            if purchase.paid_on is not None:
                st.caption(f"Paid on {purchase.paid_on.isoformat()} from this bill.")
            else:
                st.warning(
                    "No order date on this bill. Shipping and tax still save. "
                    "The shelf date stays as it is."
                )
            if purchase.delivered_on is not None:
                st.caption(
                    f"Delivered on {purchase.delivered_on.isoformat()} from this bill."
                )
            st.text(preview)
        missed_ids = set(missed)
        new_copies = [
            purchase
            for purchase in billed
            if str(purchase.external_id or "").strip() in missed_ids
            and str(purchase.external_id or "").strip().isdigit()
        ]
        other_missed = [
            item
            for item in missed
            if item not in {str(purchase.external_id) for purchase in new_copies}
        ]
        for purchase in new_copies:
            st.write(purchase.title or purchase.external_id)
            st.caption(
                f"Item {purchase.external_id} is not on the shelf yet. "
                "Save adds it as its own copy."
            )
        if other_missed:
            st.warning("Skipped unmatched ids: " + ", ".join(other_missed))
        if (previews or new_copies) and st.button(
            "Save this bill on these copies",
            type="primary",
            key="collection-shelf-fill-save-bill",
        ):
            wrote = 0
            copies: list[tuple[str, str, ParsedPurchase]] = []
            for purchase in new_copies:
                save_owned_copy(
                    engine,
                    account_id=account_id,
                    purchase=purchase,
                    catalog_number=purchase.catalog_number or "",
                    pressing_id=None,
                    paid_amount=purchase.paid_amount,
                    paid_currency=purchase.paid_currency or "USD",
                    paid_on=purchase.paid_on,
                )
                wrote += 1
                market, listing = bill_copy_identity("", "", purchase)
                if market and listing:
                    copies.append((market, listing, purchase))
                added = (
                    str(purchase.source or "ebay"),
                    str(purchase.external_id),
                )
                st.session_state["collection-shelf-focus"] = ":".join(added)
                st.session_state["collection-shelf-apply-focus"] = True
            for target, purchase, preview in previews:
                catalog = _shelf_text(target.get("catalog_number")) or (
                    purchase.catalog_number or ""
                )
                billed = replace(
                    purchase,
                    catalog_number=catalog or None,
                    billing_note=preview,
                )
                marketplace = _shelf_text(target.get("marketplace"))
                listing_id = _shelf_text(target.get("listing_id"))
                wrote += save_billing_note(
                    engine,
                    account_id=account_id,
                    purchase=billed,
                    marketplace=marketplace,
                    listing_id=listing_id,
                    user_id=user_id,
                    persist_bill=False,
                )
                copies.append((marketplace, listing_id, billed))
            if copies:
                save_package_bill(
                    engine,
                    account_id=account_id,
                    copies=copies,
                    user_id=user_id,
                )
            if wrote and new_copies and not copies:
                _refresh_shelf()
            elif wrote:
                _advance_unfilled_copy(
                    frame,
                    current=row,
                    filled=[(marketplace, listing_id) for marketplace, listing_id, _ in copies],
                )
                _refresh_shelf()
            else:
                st.error(
                    "Could not attach that bill to the selected copy. "
                    "The listing id on the shelf did not match a purchased row."
                )
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
                source="typed",
                external_id="",
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
            _advance_unfilled_copy(
                frame,
                current=row,
                filled=[
                    (
                        _shelf_text(row.get("marketplace")),
                        _shelf_text(row.get("listing_id")),
                    )
                ],
            )
            _refresh_shelf()
            return
        st.error("Could not attach those amounts to the selected copy.")


def _acquisition_chart(
    rows: list[tuple[str, int]],
    *,
    title: str,
    horizontal: bool = False,
) -> None:
    frame = pd.DataFrame(rows, columns=["label", "records"])
    frame = frame.loc[frame["records"].gt(0)]
    if frame.empty:
        st.caption(f"{title}: none yet.")
        return
    if horizontal:
        chart = (
            alt.Chart(frame)
            .mark_bar()
            .encode(
                y=alt.Y("label:N", sort="-x", title=None),
                x=alt.X("records:Q", title="Records"),
                tooltip=["label", "records"],
            )
        )
    else:
        chart = (
            alt.Chart(frame)
            .mark_bar()
            .encode(
                x=alt.X("label:N", sort=None, title=None),
                y=alt.Y("records:Q", title="Records"),
                tooltip=["label", "records"],
            )
        )
    st.altair_chart(
        chart.properties(title=title, height=240),
        width="stretch",
    )


def _show_acquisition(frame: pd.DataFrame) -> None:
    """How the shelf was bought: type, shop, time, and artist."""

    if frame.empty:
        st.info("Nothing is on the shelf yet.")
        return
    grain = st.radio(
        "When",
        ("Week", "Month", "Year"),
        horizontal=True,
        index=1,
        key="collection-acquisition-grain",
    )
    summary = acquisition_breakdown(
        frame.to_dict("records"),
        grain=str(grain).lower(),
    )
    type_col, shop_col = st.columns(2)
    with type_col:
        _acquisition_chart(summary["types"], title="Auction, fixed, and OBO")
    with shop_col:
        _acquisition_chart(summary["shops"], title="Where they came from")
    _acquisition_chart(summary["periods"], title=f"Records by {grain.lower()}")
    if summary["undated"]:
        st.caption(f"{summary['undated']} without a paid date.")
    _acquisition_chart(
        summary["packages"],
        title="EPs, sleeves, gatefolds, and box sets",
        horizontal=True,
    )
    _acquisition_chart(
        summary["artists"],
        title="By artist",
        horizontal=True,
    )


def main() -> None:
    """Render the intake and the shelf."""
    account = require_authenticated_account(engine)
    render_account_menu(account)
    ensure_owned_copy_table(engine)
    ensure_collection_bill_tables(engine)
    st.title("My collection")
    st.caption(
        "Bring in a saved order page, or log a copy when that history is gone. "
        "Then see the tracked records that are still missing."
    )

    account_id = str(account.account_id)
    user_id = str(account.user_id)
    if align_lot_dates(engine, account_id=account_id):
        load_collected.clear()
        load_owned.clear()
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
    if not collected.empty and "paid_on" in collected.columns:
        collected = _sections_then_oldest(collected, tracked)
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

    shelf_tab, acquisition_tab = st.tabs(("Shelf", "Acquisition"))
    with shelf_tab:
        collected_tab, missing_tab = st.tabs(
            (
                f"Collected ({len(collected)})",
                f"Not yet ({len(missing)})",
            )
        )
        with collected_tab:
            _show_collected(collected, account_id=account_id, user_id=user_id)
        with missing_tab:
            _show_missing(missing)
    with acquisition_tab:
        _show_acquisition(collected)


if __name__ == "__main__":
    main()
