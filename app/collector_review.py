"""Database-driven Auction Collector Review."""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

EBAY_US_TAX_RATE = Decimal("0.0625")

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, JsCode
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from auction_etl.auth.context import AccountContext
from auction_etl.auth.streamlit_auth import (
    render_account_menu,
    require_authenticated_account,
)
from auction_etl.services.account_scope import account_transaction
from auction_etl.runtime_authority import cloud_runtime_detected
from auction_etl.services.tracked_listing_scope import (
    enabled_tracked_artist_names,
    listing_belongs_to_tracked_artists,
)

from app.collector_analytics_editor import (
    render_collector_analytics_editor,
)

from app.collector_export import render_export_toolbar

import app.collector_review_support as _collector_support

importlib.reload(_collector_support)

from app.collector_review_support import (
    _catalog_helpers,
    _media_helpers,
    apply_local_identity,
    apply_pressing_copy_facts,
    as_boolean,
    automatic_catalog,
    automatic_disc_count,
    automatic_media_type,
    automatic_pressing_group,
    automatic_pressing_type,
    automatic_region,
    automatic_sale_type,
    clean_text,
    derive_pressing_group_key,
    derive_pressing_token,
    derive_sale_type,
    display_listing_catalog,
    display_matrix_catalog,
    display_release_year,
    drop_overlapping_gripsweat_rows,
    form_choice,
    form_disc_count,
    form_flag,
    form_text,
    _is_cassette,
    condition_grade_options,
    condition_profile,
    PAPER_MEDIA,
    obi_for_region,
    obi_label_for_region,
    obi_value_for_region,
    factory_pack_sentence,
    notes_insert_fact,
    notes_with_insert_fact,
    notes_without_insert_fact,
    FACTORY_NO_INSERT_NOTE,
    INSERT_ONLY_NOTE,
    PINUP_INSERT_NOTE,
    format_count,
    identity_matches_queue,
    identity_mix_caption,
    place_review_media,
    review_lot_flag,
    review_media_slot,
    is_missing,
    save_choice,
    save_count,
    save_flag,
    save_text,
    grid_row_identity,
    _grid_click_identity,
    listing_identity,
    listing_stays_open,
    listing_option_label,
    auction_outcome_chart,
    format_chart_bucket,
    marketplace_source_label,
    no_bid_auction_rows,
    omit_no_bid_auctions,
    pressing_type_label,
    sales_without_no_bid_auctions,
    recent_change_facts,
    seller_condition_summary,
    media_matches_group,
    media_matches_scene,
    safe_float,
    safe_int,
    shortlist_preview_label,
    shortlist_preview_thumb,
    IDENTITY_QUEUE_ALL,
    MEDIA_GROUP_ALL_MUSIC,
    MEDIA_GROUP_EVERYTHING,
    MEDIA_GROUP_LP,
    MEDIA_GROUP_LOTS,
    MEDIA_GROUP_OPTIONS,
    MEDIA_GROUP_TWELVE,
    MEDIA_GROUPS_SKIP_SCENE,
    SCENE_ALL,
    SCENE_OPTIONS,
    SOURCE_ORDER,
    TWELVE_INCH_MEDIA,
)
from auction_etl.reporting.main_review_integration import (
    integrate_recent_activity,
    load_gripsweat_records,
)
from auction_etl.services.sold_item_overlap import (
    apply_gripsweat_official_usd,
    gripsweat_listing_id_from_row,
)
import auction_etl.services.discogs_identity as _discogs_identity

importlib.reload(_discogs_identity)

from auction_etl.services.discogs_identity import (
    discogs_format_label,
    listing_format_label,
    listing_identity_catalog,
    listing_media_compatible,
    listing_search_artist,
    search_user_catalog,
    shortlist_agrees_with_listing,
    visible_shortlist_hits,
)
from auction_etl.services.discogs_client import (
    DiscogsClient,
    DiscogsRateLimitError,
)
import auction_etl.services.discogs_cover as _discogs_cover

importlib.reload(_discogs_cover)

from auction_etl.services.discogs_cover import (
    rank_catalog_covers,
)
import auction_etl.services.discogs_fill as _discogs_fill

importlib.reload(_discogs_fill)

from auction_etl.services.discogs_fill import (
    apply_release_choice,
    research_listing_identity,
)
from auction_etl.services.discogs_identity import map_release_payload
from app.navigation import render_navigation


def title_classification(
    title: Any,
) -> tuple[str | None, str | None, bool]:
    """Media, catalog, and bulk hints taken from the listing title."""
    text = clean_text(title)
    if not text:
        return None, None, False

    catalog_token, _fold, _junk = _catalog_helpers()
    classify_media_details, _is_job_lot = _media_helpers()
    details = classify_media_details(text)
    return (
        details.format,
        catalog_token(title=text),
        details.bulk_lot,
    )


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://auction:auction@localhost:5544/auction_warehouse",
)

PAGE_SIZE_OPTIONS = (
    50,
    100,
    250,
)

SELECTED_LISTING_KEY = "_selected_listing_identity"
JUMP_LISTING_KEY = "collector_jump_listing"
PENDING_JUMP_LISTING_KEY = "_pending_jump_listing_identity"
RESET_JUMP_LISTING_KEY = "_reset_jump_listing"
TABLE_SELECTION_REVISION_KEY = "_listing_table_selection_revision"
LIVE_REVIEW_RENDERED_AT_KEY = "_collector_live_review_rendered_at"

MEDIA_OPTIONS = (
    "Automatic / unset",
    "BULK_LOT",
    "LP",
    "EP_7_INCH",
    "SINGLE_12_INCH",
    "CD",
    "CD_BOX_SET",
    "CASSETTE",
    "DVD",
    "VHS",
    "MAGAZINE",
    "PHOTO",
    "PHOTOBOOK",
    "PRINT",
    "STAMP",
    "USB",
    "OTHER",
)

MEDIA_OPTION_LABELS = {
    "Automatic / unset": "Automatic / unset",
    "BULK_LOT": "Bulk lot",
    "LP": "LP",
    "EP_7_INCH": 'EP / 7"',
    "SINGLE_12_INCH": '12"',
    "CD": "CD",
    "CD_BOX_SET": "CD box set",
    "CASSETTE": "Cassette",
    "DVD": "DVD",
    "VHS": "VHS",
    "MAGAZINE": "Magazine",
    "PHOTO": "Photo",
    "PHOTOBOOK": "Photobook",
    "PRINT": "Print",
    "STAMP": "Stamp",
    "USB": "USB",
    "OTHER": "Other",
}

REGION_OPTIONS = (
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

PRESSING_TYPE_OPTIONS = (
    "Automatic / unset",
    "STANDARD",
    "FIRST_PRESSING",
    "PROMO_SAMPLE",
    "REISSUE",
)

SALE_TYPE_OPTIONS = (
    "Automatic / unset",
    "AUCTION",
    "FIXED_PRICE",
    "FIXED_PRICE_OBO",
    "UNKNOWN",
)

VERDICT_OPTIONS = (
    "Automatic / unset",
    "PASS",
    "WATCH",
    "REFERENCE_ONLY",
    "REJECT",
)

# CDs are a jewel case, a booklet, and a disc. The seller's scale is not the vinyl one.
CD_MEDIA = {
    "CD",
    "CD_BOX_SET",
    "SHM_CD",
    "SACD",
    "BLU_SPEC_CD",
    "CD_SINGLE_8CM",
}
TRI_STATE_OPTIONS = (
    "Automatic / unset",
    "Yes",
    "No",
)


st.set_page_config(
    page_title="Review marketplace sales",
    page_icon="🔎",
    layout="wide",
)

if cloud_runtime_detected():
    st.error(
        "Collector Ledger's authoritative database is local. "
        "The hosted database-backed UI is disabled."
    )
    st.caption(
        "Run Collector Review locally against "
        "127.0.0.1:5544/auction_warehouse."
    )
    st.stop()

render_navigation(current_page="collector_review.py")

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        border: 1px solid rgba(49, 51, 63, 0.14);
        border-radius: 0.65rem;
        padding: 0.65rem 0.85rem;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(49, 51, 63, 0.12);
        border-radius: 0.65rem;
        overflow: hidden;
    }

    .collector-subtle {
        color: rgba(49, 51, 63, 0.62);
        font-size: 0.92rem;
    }

    [class*="st-key-identity-pile-"] button {
        min-height: 7.25rem;
        justify-content: flex-start;
        align-items: flex-start;
        text-align: left;
        border-left-width: 6px !important;
        border-left-style: solid !important;
        white-space: pre-wrap;
    }

    [class*="st-key-identity-pile-"] button [data-testid="stMarkdownContainer"] p {
        margin: 0;
        text-align: left;
        white-space: pre-wrap;
        line-height: 1.35;
    }

    [class*="st-key-identity-pile-"] button p strong {
        display: block;
        margin-bottom: 0.35rem;
        font-size: 1.55rem;
        line-height: 1.15;
        font-weight: 700;
    }

    [class*="st-key-identity-pile-all"] button {
        border-left-color: #64748b !important;
        background: color-mix(in srgb, #64748b 12%, transparent);
    }

    [class*="st-key-identity-pile-matched"] button {
        border-left-color: #15803d !important;
        background: color-mix(in srgb, #15803d 16%, transparent);
    }

    [class*="st-key-identity-pile-review"] button {
        border-left-color: #c2410c !important;
        background: color-mix(in srgb, #c2410c 16%, transparent);
    }

    [class*="st-key-identity-pile-unmatched"] button {
        border-left-color: #64748b !important;
        background: color-mix(in srgb, #475569 16%, transparent);
    }

    [class*="st-key-identity-pile-lots"] button {
        border-left-color: #7c3aed !important;
        background: color-mix(in srgb, #7c3aed 16%, transparent);
    }

    [class*="st-key-identity-pile-"][class*="-on"] button {
        box-shadow: inset 0 0 0 1px currentColor;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def sqlalchemy_database_url(url: str) -> str:
    """Use SQLAlchemy's Psycopg 3 dialect."""
    if url.startswith(
        "postgresql+psycopg://"
    ):
        return url

    if url.startswith(
        "postgresql://"
    ):
        return url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return url


@st.cache_resource
def get_engine() -> Engine:
    """Create the shared SQLAlchemy engine."""
    return create_engine(
        sqlalchemy_database_url(
            DATABASE_URL
        ),
        pool_pre_ping=True,
    )


def account_refresh_is_active(
    account_id: str,
) -> bool:
    """Return whether this account has a queued or running refresh."""
    statement = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM ops.refresh_job
            WHERE account_id = CAST(
                :account_id AS uuid
            )
              AND state IN (
                  'queued',
                  'running'
              )
        )
        """
    )

    try:
        with get_engine().connect() as connection:
            return bool(
                connection.execute(
                    statement,
                    {
                        "account_id":
                            account_id,
                    },
                ).scalar_one()
            )
    except Exception:
        return False


@st.fragment(
    run_every="3s",
)
def rerun_review_while_refresh_active(
    account_id: str,
) -> None:
    """Refresh the full review page while durable ingestion is active."""
    if not account_refresh_is_active(
        account_id
    ):
        return

    rendered_at = float(
        st.session_state.get(
            LIVE_REVIEW_RENDERED_AT_KEY,
            0.0,
        )
        or 0.0
    )

    if (
        time.monotonic()
        - rendered_at
        < 2.5
    ):
        return

    load_records.clear()
    st.rerun()


ACCOUNT_CONTEXT = require_authenticated_account(
    get_engine()
)
render_account_menu(
    ACCOUNT_CONTEXT
)


def quote_identifier(
    identifier: str,
) -> str:
    """Quote a trusted SQL identifier."""
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        identifier,
    ):
        raise ValueError(
            f"Unsafe SQL identifier: {identifier!r}"
        )

    return f'"{identifier}"'


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def relation_columns(
    schema_name: str,
    relation_name: str,
) -> tuple[str, ...]:
    """Return database relation columns."""
    statement = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema_name
          AND table_name = :relation_name
        ORDER BY ordinal_position
        """
    )

    with get_engine().connect() as connection:
        rows = connection.execute(
            statement,
            {
                "schema_name": schema_name,
                "relation_name": relation_name,
            },
        ).scalars()

        return tuple(rows)


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def review_relation() -> str:
    """Resolve the best available collector view."""
    statement = text(
        """
        SELECT
            to_regclass(
                'warehouse.auction_collector_review'
            ),
            to_regclass(
                'warehouse.auction_collector_effective'
            )
        """
    )

    with get_engine().connect() as connection:
        review_view, effective_view = (
            connection.execute(
                statement
            ).one()
        )

    if review_view:
        return (
            "warehouse."
            "auction_collector_review"
        )

    if effective_view:
        return (
            "warehouse."
            "auction_collector_effective"
        )

    return "warehouse.auction"


def coalesce_series(
    dataframe: pd.DataFrame,
    candidates: Iterable[str],
) -> pd.Series:
    """Coalesce the first populated candidate columns."""
    result = pd.Series(
        pd.NA,
        index=dataframe.index,
        dtype="object",
    )

    for candidate in candidates:
        if candidate in dataframe.columns:
            result = result.combine_first(
                dataframe[candidate]
            )

    return result


def collector_value(
    row: pd.Series,
    column_name: str,
) -> Any:
    """Read a collector value from joined aliases."""
    aliases = {
        "in_collection": "manual_purchased",
        "purchase_date": "manual_purchase_date",
        "purchase_price": "manual_purchase_price",
        "purchase_currency": "manual_purchase_currency",
    }
    names = [column_name]
    mapped = aliases.get(column_name)
    if mapped:
        names.append(mapped)
    for name in names:
        for candidate in (
            f"collector_{name}",
            name,
        ):
            if candidate in row.index:
                value = row[candidate]

                if not is_missing(value):
                    return value

    return None


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def load_records(account_id: str) -> pd.DataFrame:
    """Load only listings visible to the authenticated account."""
    relation = review_relation()

    collector_columns = relation_columns(
        "warehouse",
        "auction_collector",
    )

    if "account_id" not in collector_columns:
        raise RuntimeError(
            "Phase D account scoping is not installed for "
            "warehouse.auction_collector."
        )

    joined_columns = []

    for column_name in collector_columns:
        if column_name in {
            "id",
            "account_id",
            "marketplace",
            "listing_id",
            # Bulk-refresh hash. About half a megabyte, never shown.
            "source_fingerprint",
        }:
            continue

        joined_columns.append(
            (
                f"c.{quote_identifier(column_name)} "
                f"AS {quote_identifier('collector_' + column_name)}"
            )
        )

    joined_sql = ""

    if joined_columns:
        joined_sql = ",\n" + ",\n".join(
            joined_columns
        )

    query = text(
        f"""
        SELECT
            r.*
            {joined_sql}
        FROM {relation} AS r
        LEFT JOIN warehouse.auction_collector AS c
          ON c.account_id = CAST(:account_id AS uuid)
         AND c.marketplace = r.marketplace
         AND c.listing_id = r.listing_id
        WHERE EXISTS (
            SELECT 1
            FROM account.auction_listing AS visible
            WHERE visible.account_id = CAST(:account_id AS uuid)
              AND visible.marketplace = r.marketplace
              AND visible.listing_id = r.listing_id
        )
        """
    )

    parameters = {
        "account_id": account_id,
    }

    with get_engine().connect() as connection:
        native_records = pd.read_sql_query(
            query,
            connection,
            params=parameters,
        )
        gripsweat_usd_rows = pd.read_sql_query(
            """
            SELECT
                original_listing_id,
                gripsweat_url,
                gripsweat_item_id,
                sold_price,
                currency,
                sold_at
            FROM warehouse.gripsweat_sale
            """,
            connection,
        )

    # Warehouse already stores Gripsweat-only sales. Concatenating the
    # archive again invented a second ID for the same eBay sale.
    combined = drop_overlapping_gripsweat_rows(native_records)

    official_usd_index = {}
    for row in gripsweat_usd_rows.to_dict(orient="records"):
        listing_id = gripsweat_listing_id_from_row(row)
        if listing_id:
            official_usd_index[listing_id] = row

    combined = apply_gripsweat_official_usd(
        combined,
        official_usd_index,
    )

    # Item-page and Yahoo description reports. Cached with this function.
    seller_reports = pd.read_sql(
        text(
            """
            SELECT
                marketplace,
                listing_id,
                description AS seller_report_text,
                updated_at AS seller_report_updated_at
            FROM warehouse.auction_detail
            WHERE description IS NOT NULL
              AND btrim(description) <> ''
            """
        ),
        get_engine(),
    )
    if not seller_reports.empty and not combined.empty:
        combined = combined.merge(
            seller_reports,
            on=["marketplace", "listing_id"],
            how="left",
        )
    records = prepare_records(
        apply_pressing_copy_facts(
            combined,
            pd.read_sql(
                text(
                    """
                    SELECT
                        id,
                        discogs_master_id,
                        release_year,
                        generation,
                        media_type,
                        format_detail,
                        notes
                    FROM warehouse.pressing_identity
                    """
                ),
                get_engine(),
            ),
        )
    )
    tracked_names = enabled_tracked_artist_names(
        get_engine(),
        account_id=account_id,
    )
    if tracked_names and not records.empty:
        keep = [
            listing_belongs_to_tracked_artists(
                title=title,
                artist=artist,
                tracked_names=tracked_names,
            )
            for title, artist in zip(
                records["title"],
                records["artist_display"],
                strict=True,
            )
        ]
        records = records.loc[keep].reset_index(drop=True)
    return records



def prepare_records(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Create consistent display and filter columns."""
    frame = dataframe.copy()

    frame["marketplace"] = coalesce_series(
        frame,
        ("marketplace",),
    ).map(clean_text)
    frame["source_display"] = frame["marketplace"].map(
        marketplace_source_label
    )

    frame["listing_id"] = coalesce_series(
        frame,
        ("listing_id",),
    ).map(clean_text)

    frame["title"] = coalesce_series(
        frame,
        ("title",),
    ).map(clean_text)

    frame["seller"] = coalesce_series(
        frame,
        ("seller", "seller_name"),
    ).map(clean_text)

    frame["artist_display"] = coalesce_series(
        frame,
        (
            "effective_artist",
            "artist",
        ),
    ).map(clean_text)

    frame["auction_url"] = coalesce_series(
        frame,
        ("auction_url",),
    ).map(clean_text)

    frame["currency_display"] = coalesce_series(
        frame,
        ("currency",),
    ).map(clean_text)

    frame["opening_display"] = pd.to_datetime(
        coalesce_series(
            frame,
            (
                "opening_at",
                "started_at",
                "_source_first_seen_at",
            ),
        ),
        errors="coerce",
        utc=True,
    )

    frame["closing_display"] = pd.to_datetime(
        coalesce_series(
            frame,
            (
                "closing_at",
                "ended_at",
            ),
        ),
        errors="coerce",
        utc=True,
    )

    frame["starting_local"] = pd.to_numeric(
        coalesce_series(
            frame,
            (
                "start_price",
                "starting_price",
            ),
        ),
        errors="coerce",
    )

    frame["hammer_local"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("final_price",),
        ),
        errors="coerce",
    )

    frame["tax_local"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("tax_amount",),
        ),
        errors="coerce",
    )

    frame["total_local"] = pd.to_numeric(
        coalesce_series(
            frame,
            (
                "gross_price",
                "current_price_gross",
            ),
        ),
        errors="coerce",
    )

    frame["buyout_local"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("buyout_price_gross",),
        ),
        errors="coerce",
    )

    frame["starting_usd"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("start_price_usd",),
        ),
        errors="coerce",
    )

    frame["hammer_usd"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("final_price_usd",),
        ),
        errors="coerce",
    )

    frame["tax_usd_display"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("tax_usd",),
        ),
        errors="coerce",
    )

    frame["total_usd"] = pd.to_numeric(
        coalesce_series(
            frame,
            (
                "gross_price_usd",
                "current_price_usd",
            ),
        ),
        errors="coerce",
    )

    us_ebay = (
        frame["marketplace"].str.casefold().eq("ebay")
        & frame["currency_display"].str.upper().eq("USD")
        & frame["hammer_local"].notna()
    )
    if us_ebay.any():
        tax = (
            frame.loc[us_ebay, "hammer_local"] * float(EBAY_US_TAX_RATE)
        ).round(2)
        frame.loc[us_ebay, "tax_local"] = tax
        frame.loc[us_ebay, "tax_usd_display"] = tax
        frame.loc[us_ebay, "total_local"] = (
            frame.loc[us_ebay, "hammer_local"] + tax
        )
        frame.loc[us_ebay, "total_usd"] = (
            frame.loc[us_ebay, "hammer_local"] + tax
        )
        frame.loc[us_ebay, "hammer_usd"] = frame.loc[us_ebay, "hammer_local"]

    frame["buyout_usd"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("buyout_price_usd",),
        ),
        errors="coerce",
    )

    frame["bid_count_display"] = pd.to_numeric(
        coalesce_series(
            frame,
            ("bid_count",),
        ),
        errors="coerce",
    )

    frame["media_display"] = coalesce_series(
        frame,
        (
            "effective_media_type",
            "manual_media_type",
            "auto_media_type",
            "media_type",
        ),
    ).map(clean_text)

    frame["catalog_display"] = coalesce_series(
        frame,
        (
            "effective_catalog_number",
            "manual_catalog_number",
            "auto_catalog_number",
            "catalog_number",
        ),
    ).map(clean_text)

    frame["matrix_display"] = coalesce_series(
        frame,
        (
            "effective_matrix_number",
            "matrix_number",
        ),
    ).map(clean_text)

    media_fills: list[str] = []
    catalog_fills: list[str] = []
    if "collector_manual_media_type" in frame.columns:
        saved_media = frame["collector_manual_media_type"]
    elif "manual_media_type" in frame.columns:
        saved_media = frame["manual_media_type"]
    else:
        saved_media = [""] * len(frame)
    if "manual_media_type" in frame.columns:
        shared_media = frame["manual_media_type"]
    else:
        shared_media = [""] * len(frame)
    if "manual_bulk_lot" in frame.columns:
        manual_lots = frame["manual_bulk_lot"]
    else:
        manual_lots = [None] * len(frame)
    for title, media, saved, shared, catalog, matrix, manual_lot in zip(
        frame["title"],
        frame["media_display"],
        saved_media,
        shared_media,
        frame["catalog_display"],
        frame["matrix_display"],
        manual_lots,
        strict=True,
    ):
        chosen_media = clean_text(saved) or clean_text(shared)
        display_media = review_media_slot(chosen_media, title, media)
        media_fills.append(display_media)
        catalog_fills.append(
            display_matrix_catalog(
                stored_catalog=catalog,
                stored_matrix=matrix,
                title=title,
            )
        )

    frame["media_display"] = media_fills
    frame["catalog_display"] = catalog_fills
    frame["job_lot"] = [
        review_lot_flag(title, manual_lot)
        for title, manual_lot in zip(frame["title"], manual_lots, strict=True)
    ]
    frame.loc[frame["job_lot"], "catalog_display"] = ""

    frame["label_display"] = coalesce_series(
        frame,
        (
            "effective_label",
            "label",
        ),
    ).map(clean_text)
    if "discogs_shortlist" in frame.columns:
        missing_label = frame["label_display"].map(clean_text) == ""
        frame.loc[missing_label, "label_display"] = frame.loc[
            missing_label,
            "discogs_shortlist",
        ].map(shortlist_preview_label)

    pressing_years = coalesce_series(
        frame,
        ("effective_release_year",),
    )
    titles = (
        frame["title"]
        if "title" in frame.columns
        else pd.Series("", index=frame.index)
    )
    frame["release_year_display"] = [
        display_release_year(pressing_year=year, title=title)
        for year, title in zip(pressing_years, titles, strict=False)
    ]

    frame["identity_status_display"] = coalesce_series(
        frame,
        ("identity_status",),
    ).map(
        lambda value: {
            "filled_auto": "Filled",
            "filled_manual": "Filled",
            "needs_review": "Needs review",
            "unmatched": "Unmatched",
        }.get(clean_text(value), clean_text(value) or "Unmatched")
    )
    frame.loc[frame["job_lot"], "identity_status_display"] = "Lot"

    frame["identity_updated_display"] = coalesce_series(
        frame,
        ("identity_status_changed_at", "identity_filled_at"),
    ).map(
        lambda value: "Updated" if pd.notna(value) and str(value).strip() else ""
    )
    recent_rows = frame.to_dict(orient="records")
    recent_facts = [
        recent_change_facts(
            [
                ("Seller report", row.get("seller_report_updated_at")),
                ("Identity", row.get("identity_status_changed_at")),
                ("Identity", row.get("identity_filled_at")),
                ("Saved", row.get("collector_updated_at")),
            ]
        )
        for row in recent_rows
    ]
    frame["recent_change_display"] = [mark for mark, _detail, _when in recent_facts]
    frame["recent_change_detail"] = [detail for _mark, detail, _when in recent_facts]
    frame["recent_change_at"] = [
        when if when is not None else pd.NaT
        for _mark, _detail, when in recent_facts
    ]

    frame["listing_image_url"] = coalesce_series(
        frame,
        ("image_url",),
    ).map(clean_text)

    frame["discogs_thumb_url"] = coalesce_series(
        frame,
        ("discogs_thumb_url",),
    ).map(clean_text)
    identity_values = coalesce_series(
        frame,
        ("identity_status",),
    ).map(clean_text)
    unmatched = identity_values.eq("unmatched")
    frame.loc[unmatched, "discogs_thumb_url"] = ""

    frame["region_display"] = coalesce_series(
        frame,
        (
            "effective_region",
            "manual_region",
            "auto_region",
        ),
    ).map(clean_text)

    frame["verdict_display"] = coalesce_series(
        frame,
        (
            "effective_verdict",
            "manual_verdict",
            "auto_verdict",
        ),
    ).map(clean_text)

    frame["detail_status_display"] = coalesce_series(
        frame,
        (
            "detail_status",
            "auction_status",
        ),
    ).map(clean_text)

    frame["in_collection_display"] = coalesce_series(
        frame,
        (
            "collector_in_collection",
            "in_collection",
            "collector_manual_purchased",
            "manual_purchased",
        ),
    ).map(as_boolean)

    frame["pressing_override"] = coalesce_series(
        frame,
        (
            "collector_manual_pressing_group",
            "manual_pressing_group",
        ),
    ).map(clean_text)

    frame["pressing_token"] = frame.apply(
        lambda row: (
            ""
            if row["job_lot"] and not row["pressing_override"]
            else derive_pressing_token(
                override=row["pressing_override"],
                catalog_number=row["catalog_display"],
                title=row["title"],
            )
        ),
        axis=1,
    )

    listing_source_counts = frame.groupby("listing_id")["marketplace"].transform(
        "nunique"
    )
    token_counts = pd.Series(0, index=frame.index, dtype="int64")
    has_token = frame["pressing_token"].astype(str).str.strip() != ""
    if bool(has_token.any()):
        counts = frame.loc[has_token, "pressing_token"].value_counts()
        token_counts.loc[has_token] = (
            frame.loc[has_token, "pressing_token"].map(counts).astype("int64")
        )
    overlap_notes: list[str] = []
    for job, sources, token, shared in zip(
        frame["job_lot"],
        listing_source_counts.fillna(1),
        frame["pressing_token"],
        token_counts,
        strict=True,
    ):
        if job:
            overlap_notes.append("")
        elif int(sources) > 1:
            overlap_notes.append("Same listing")
        elif token and int(shared) > 1:
            overlap_notes.append("Shared pressing")
        else:
            overlap_notes.append("")
    frame["overlap_display"] = overlap_notes

    frame["pressing_group_key"] = frame.apply(
        derive_pressing_group_key,
        axis=1,
        result_type="reduce",
    )

    frame["sale_type_display"] = frame.apply(
        lambda row: derive_sale_type(
            manual_value=collector_value(
                row,
                "manual_sale_type",
            ),
            title=row["title"],
            starting_price=row["starting_local"],
            bid_count=row["bid_count_display"],
            buyout_price=row["buyout_local"],
            stored_format=row.get("auction_format"),
        ),
        axis=1,
    )

    frame = omit_no_bid_auctions(frame)

    frame.sort_values(
        by=[
            "closing_display",
            "listing_id",
        ],
        ascending=[
            False,
            True,
        ],
        na_position="last",
        inplace=True,
    )

    frame.reset_index(
        drop=True,
        inplace=True,
    )

    return frame


def optional_selectbox(
    label: str,
    options: tuple[str, ...],
    current_value: Any,
    *,
    key: str,
    format_func: Any = None,
    help: str | None = None,
) -> str:
    """Render a selectbox with an automatic NULL option."""
    current = clean_text(
        current_value
    )

    selected = current or options[0]

    if selected not in options:
        dynamic_options = (
            options[0],
            selected,
            *options[1:],
        )
    else:
        dynamic_options = options

    extra: dict[str, Any] = {}
    if format_func is not None:
        extra["format_func"] = format_func
    if help:
        extra["help"] = help

    return st.selectbox(
        label,
        dynamic_options,
        index=dynamic_options.index(
            selected
        ),
        key=key,
        **extra,
    )


def automatic_widget_key(key: str, manual: Any, automatic: Any) -> str:
    """Keep a saved choice. A new automatic fact gets a fresh widget."""
    if not is_missing(manual):
        return key
    if is_missing(automatic):
        token = "auto"
    elif isinstance(automatic, str):
        token = clean_text(automatic) or "auto"
    else:
        token = "yes" if as_boolean(automatic) else "no"
    return f"{key}:{token}"


def tri_state_selectbox(
    label: str,
    current_value: Any,
    *,
    key: str,
    help: str | None = None,
    disabled: bool = False,
) -> str:
    """Render an Automatic, Yes, or No selector."""
    if is_missing(current_value):
        selected = "Automatic / unset"
    elif as_boolean(current_value):
        selected = "Yes"
    else:
        selected = "No"

    extra: dict[str, Any] = {}
    if help:
        extra["help"] = help
    return st.selectbox(
        label,
        TRI_STATE_OPTIONS,
        index=TRI_STATE_OPTIONS.index(
            selected
        ),
        key=key,
        disabled=disabled,
        **extra,
    )


def tri_state_value(
    selected: str,
) -> bool | None:
    """Convert a tri-state selection to a database scalar."""
    if selected == "Yes":
        return True

    if selected == "No":
        return False

    return None


def nullable_choice(
    selected: str,
) -> str | None:
    """Convert the automatic option to NULL."""
    if selected == "Automatic / unset":
        return None

    return selected


def nullable_text(
    value: Any,
) -> str | None:
    """Convert blank text to NULL."""
    cleaned = clean_text(
        value
    )

    return cleaned or None


def format_money(
    value: Any,
    currency: str,
) -> str:
    """Format a local-currency value."""
    number = safe_float(
        value
    )

    if number is None:
        return "—"

    code = clean_text(
        currency
    ) or "USD"

    if code == "USD":
        return f"${number:,.2f}"

    if code == "JPY":
        return f"¥{number:,.0f}"

    return f"{number:,.2f} {code}"


def format_usd(
    value: Any,
) -> str:
    """Format a normalized USD value."""
    number = safe_float(
        value
    )

    if number is None:
        return "—"

    return f"${number:,.2f}"


def format_datetime(
    value: Any,
) -> str:
    """Format a timestamp for display."""
    timestamp = pd.to_datetime(
        value,
        errors="coerce",
        utc=True,
    )

    if pd.isna(timestamp):
        return "—"

    return timestamp.strftime(
        "%Y-%m-%d %H:%M"
    )


def set_notification(
    message: str,
) -> None:
    """Persist a success notification across a rerun."""
    st.session_state[
        "_collector_notification"
    ] = message


def render_pending_notification() -> None:
    """Render a pending save notification."""
    message = st.session_state.pop(
        "_collector_notification",
        None,
    )

    if message:
        st.success(
            message,
            icon="✅",
        )
        st.toast(
            message,
            icon="✅",
        )


def save_collector_record(
    account_id: str,
    user_id: str,
    marketplace: str,
    listing_id: str,
    values: dict[str, Any],
) -> int:
    """Insert or update one collector override owned by an account."""
    columns = set(
        relation_columns(
            "warehouse",
            "auction_collector",
        )
    )

    if "account_id" not in columns:
        raise RuntimeError(
            "Phase D account scoping is not installed for "
            "warehouse.auction_collector."
        )

    allowed_values = {
        column_name: value
        for column_name, value in values.items()
        if (
            column_name in columns
            and column_name
            not in {
                "account_id",
                "marketplace",
                "listing_id",
            }
        )
    }
    write_aliases = {
        "in_collection": "manual_purchased",
        "purchase_date": "manual_purchase_date",
        "purchase_price": "manual_purchase_price",
        "purchase_currency": "manual_purchase_currency",
    }
    for source_name, dest_name in write_aliases.items():
        if source_name not in values:
            continue
        if dest_name in columns and dest_name not in allowed_values:
            allowed_values[dest_name] = values[source_name]

    with account_transaction(
        get_engine(),
        account_id=account_id,
        user_id=user_id,
    ) as connection:
        visible = connection.execute(
            text(
                """
                SELECT 1
                FROM account.auction_listing
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace)) =
                      lower(btrim(:marketplace))
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one_or_none()

        if visible is None:
            raise PermissionError(
                "The selected listing is not visible to this account."
            )

        connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_collector (
                    account_id,
                    marketplace,
                    listing_id
                )
                VALUES (
                    CAST(:account_id AS uuid),
                    CAST(:marketplace AS character varying),
                    CAST(:listing_id AS character varying)
                )
                ON CONFLICT (
                    account_id,
                    marketplace,
                    listing_id
                )
                WHERE account_id IS NOT NULL
                DO NOTHING
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        )

        assignments = [
            (
                f"{quote_identifier(column_name)} "
                f"= :{column_name}"
            )
            for column_name in allowed_values
        ]

        if "updated_at" in columns:
            assignments.append(
                "updated_at = now()"
            )

        if not assignments:
            return 0

        parameters = {
            **allowed_values,
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        }

        result = connection.execute(
            text(
                f"""
                UPDATE warehouse.auction_collector
                SET {", ".join(assignments)}
                WHERE account_id = CAST(:account_id AS uuid)
                  AND marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            parameters,
        )

        return result.rowcount


FILTER_WIDGET_KEYS = {
    "marketplace": "collector_filter_marketplace",
    "search": "collector_filter_search",
    "seller": "collector_filter_seller",
    "recent_only": "collector_filter_recent_only",
    "filter_dates": "collector_filter_dates",
    "activity_from": "collector_filter_activity_from",
    "activity_through": "collector_filter_activity_through",
    "verdict": "collector_filter_verdict",
    "scene": "collector_filter_scene",
    "media_type": "collector_filter_media_type",
    "media_group": "collector_filter_media_group",
    "identity": "collector_filter_identity",
    "purchase": "collector_filter_purchase",
    "sale_type": "collector_filter_sale_type",
    "enable_price": "collector_filter_enable_price",
    "price_basis": "collector_filter_price_basis",
    "minimum_price": "collector_filter_minimum_price",
    "maximum_price": "collector_filter_maximum_price",
    "page_size": "collector_filter_page_size",
}


def _increment_table_selection_revision() -> None:
    """Force a fresh table widget while preserving stable selection."""
    st.session_state[
        TABLE_SELECTION_REVISION_KEY
    ] = (
        int(
            st.session_state.get(
                TABLE_SELECTION_REVISION_KEY,
                0,
            )
        )
        + 1
    )


def _reset_listing_results() -> None:
    """Reset pagination and table identity after filter changes."""
    st.session_state["_listing_page"] = 1
    st.session_state["_filter_revision"] = (
        int(
            st.session_state.get(
                "_filter_revision",
                0,
            )
        )
        + 1
    )
    _increment_table_selection_revision()


def _media_group_changed() -> None:
    """Keep the Lots chip and the Lot work pile in sync."""
    media = st.session_state.get(
        FILTER_WIDGET_KEYS["media_group"],
        MEDIA_GROUP_ALL_MUSIC,
    ) or MEDIA_GROUP_ALL_MUSIC
    identity_key = FILTER_WIDGET_KEYS["identity"]
    if media == MEDIA_GROUP_LOTS:
        st.session_state[identity_key] = "Lot"
    elif st.session_state.get(identity_key) == "Lot":
        st.session_state[identity_key] = IDENTITY_QUEUE_ALL
    _reset_listing_results()


def _identity_queue_changed() -> None:
    """Jump the table onto the selected Discogs pile, including parked lots."""
    selected = st.session_state.get(
        FILTER_WIDGET_KEYS["identity"],
        IDENTITY_QUEUE_ALL,
    ) or IDENTITY_QUEUE_ALL
    media_key = FILTER_WIDGET_KEYS["media_group"]
    if selected == "Lot":
        st.session_state[media_key] = MEDIA_GROUP_LOTS
    elif (
        selected != IDENTITY_QUEUE_ALL
        and st.session_state.get(media_key) == MEDIA_GROUP_LOTS
    ):
        st.session_state[media_key] = MEDIA_GROUP_ALL_MUSIC
    _reset_listing_results()


def _current_listing_identity() -> str | None:
    """Return the stable identity selected for review."""
    value = st.session_state.get(
        SELECTED_LISTING_KEY
    )

    if not value:
        return None

    return str(value)


def _set_listing_identity(
    identity: str,
    *,
    synchronize_jump: bool,
) -> None:
    """Select one stable listing identity."""
    st.session_state[
        SELECTED_LISTING_KEY
    ] = identity

    if synchronize_jump:
        st.session_state[
            PENDING_JUMP_LISTING_KEY
        ] = identity


def _request_clear_listing_identity() -> None:
    """Clear selection on the next clean rerun."""
    st.session_state.pop(
        SELECTED_LISTING_KEY,
        None,
    )
    st.session_state.pop(
        PENDING_JUMP_LISTING_KEY,
        None,
    )
    st.session_state[
        RESET_JUMP_LISTING_KEY
    ] = True
    _increment_table_selection_revision()


def _listing_identity_series(
    dataframe: pd.DataFrame,
) -> pd.Series:
    """Return stable identities for a listing dataframe."""
    return pd.Series(
        [
            listing_identity(
                marketplace,
                listing_id,
            )
            for marketplace, listing_id in zip(
                dataframe["marketplace"],
                dataframe["listing_id"],
            )
        ],
        index=dataframe.index,
        dtype="string",
    )


def _listing_position(
    dataframe: pd.DataFrame,
    identity: str,
) -> int | None:
    """Return the positional index of a stable identity."""
    identities = _listing_identity_series(
        dataframe
    )
    matches = identities[identities.astype(str) == str(identity)]

    if matches.empty:
        return None

    return int(
        dataframe.index.get_loc(
            matches.index[0]
        )
    )


def _selected_listing_row(
    dataframe: pd.DataFrame,
) -> pd.Series | None:
    """Resolve the selected identity against current filtered rows."""
    identity = _current_listing_identity()

    if identity is None:
        return None

    position = _listing_position(
        dataframe,
        identity,
    )

    if position is None:
        return None

    return dataframe.iloc[position]


def _selection_rows(
    event: Any,
) -> list[int]:
    """Extract selected row positions from a Streamlit event."""
    selection = getattr(
        event,
        "selection",
        None,
    )

    if selection is None:
        try:
            selection = event["selection"]
        except (
            KeyError,
            TypeError,
        ):
            return []

    rows = getattr(
        selection,
        "rows",
        None,
    )

    if rows is None:
        try:
            rows = selection["rows"]
        except (
            KeyError,
            TypeError,
        ):
            return []

    return [
        int(row)
        for row in rows
    ]


def _prepare_jump_widget(
    valid_identities: set[str],
) -> None:
    """Synchronize pending selection before rendering its widget."""
    if st.session_state.pop(
        RESET_JUMP_LISTING_KEY,
        False,
    ):
        st.session_state.pop(
            JUMP_LISTING_KEY,
            None,
        )

    pending = st.session_state.pop(
        PENDING_JUMP_LISTING_KEY,
        None,
    )

    if pending in valid_identities:
        st.session_state[
            JUMP_LISTING_KEY
        ] = pending

    selected = _current_listing_identity()

    if (
        selected in valid_identities
        and JUMP_LISTING_KEY
        not in st.session_state
    ):
        st.session_state[
            JUMP_LISTING_KEY
        ] = selected

    widget_value = st.session_state.get(
        JUMP_LISTING_KEY
    )

    if widget_value not in valid_identities:
        st.session_state.pop(
            JUMP_LISTING_KEY,
            None,
        )


def render_listing_jump(
    dataframe: pd.DataFrame,
    page_size: int,
    *,
    open_records: pd.DataFrame | None = None,
) -> None:
    """Render a searchable sidebar jump control."""
    identities = _listing_identity_series(
        dataframe
    ).tolist()
    valid_identities = set(
        identities
    )

    selected = _current_listing_identity()

    if (
        selected is not None
        and selected not in valid_identities
    ):
        # Use this moves a sale onto Matched. Keep the editor open so
        # condition can be filled after the Discogs choice.
        still_open = listing_stays_open(
            selected,
            in_filter=False,
            in_sales=(
                open_records is not None
                and _listing_position(open_records, selected) is not None
            ),
        )
        st.session_state["_editor_outside_filter"] = still_open
        if not still_open:
            _request_clear_listing_identity()
            selected = None
    else:
        st.session_state["_editor_outside_filter"] = False

    _prepare_jump_widget(
        valid_identities
    )

    labels = {
        identity:
            listing_option_label(
                marketplace=row.marketplace,
                listing_id=row.listing_id,
                seller=row.seller,
                title=row.title,
            )
        for identity, row in zip(
            identities,
            dataframe.itertuples(
                index=False,
            ),
        )
    }

    with st.sidebar:
        st.divider()
        st.subheader(
            "Choose a listing"
        )
        st.caption(
            "Search by marketplace, listing ID, seller, or title."
        )

        choice = st.selectbox(
            "Find a listing",
            identities,
            index=None,
            placeholder=(
                "Search ID, seller, or title…"
            ),
            format_func=labels.__getitem__,
            key=JUMP_LISTING_KEY,
        )

        if choice:
            st.caption(
                f"Selected: {labels[choice]}"
            )

    if (
        choice
        and choice != selected
    ):
        _set_listing_identity(
            choice,
            synchronize_jump=False,
        )

        position = _listing_position(
            dataframe,
            choice,
        )

        if position is not None:
            st.session_state[
                "_listing_page"
            ] = (
                position
                // page_size
                + 1
            )

        _increment_table_selection_revision()
        st.rerun()


def _marketplace_changed() -> None:
    """Reset marketplace-dependent controls and rerender immediately."""
    for key_name in (
        "activity_from",
        "activity_through",
        "verdict",
        "scene",
        "media_type",
        "identity",
        "sale_type",
        "minimum_price",
        "maximum_price",
    ):
        st.session_state.pop(
            FILTER_WIDGET_KEYS[key_name],
            None,
        )

    _reset_listing_results()




SALE_TYPE_DISPLAY_LABELS: dict[str, str] = {
    "ALL": "All sale types",
    "AUCTION_WITH_BUYOUT": "Auction with buyout",
    "ARCHIVE": "Archive",
    "FIXED": "Fixed price",
    "FIXED_PRICE": "Fixed price",
    "FIXEDPRICE": "Fixed price",
    "BUY_IT_NOW": "Fixed price",
    "BUYITNOW": "Fixed price",
    "BIN": "Fixed price",
    "OBO": "Best Offer (OBO)",
    "BEST_OFFER": "Best Offer (OBO)",
    "BESTOFFER": "Best Offer (OBO)",
    "MAKE_OFFER": "Best Offer (OBO)",
    "UNKNOWN": "Unspecified",
    "UNSPECIFIED": "Unspecified",
    "NONE": "Unspecified",
    "": "Unspecified",
}


def format_sale_type(value: object) -> str:
    """Return a product-facing label for an internal sale-type value."""

    raw_value = str(
        value
    ).strip()

    normalized = (
        raw_value
        .upper()
        .replace(
            "-",
            "_",
        )
        .replace(
            " ",
            "_",
        )
    )

    return SALE_TYPE_DISPLAY_LABELS.get(
        normalized,
        raw_value.replace(
            "_",
            " ",
        ).title(),
    )

def apply_filters(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, str, pd.DataFrame, pd.DataFrame]:
    """Render sidebar filters and return sales, page size, the pre-queue set, and 0-bid history."""
    with st.sidebar:
        st.header(
            "Find listings"
        )

        marketplaces = [
            "all",
            *sorted(
                value
                for value in dataframe[
                    "marketplace"
                ].dropna().unique()
                if value
            ),
        ]

        marketplace = st.selectbox(
            "Marketplace",
            marketplaces,
            key=FILTER_WIDGET_KEYS[
                "marketplace"
            ],
            on_change=_marketplace_changed,
        )

        marketplace_rows = dataframe

        if marketplace != "all":
            marketplace_rows = dataframe[
                dataframe["marketplace"]
                == marketplace
            ]

        search_text = st.text_input(
            "Search",
            placeholder=(
                "Title, ID, matrix, seller, artist"
            ),
            key=FILTER_WIDGET_KEYS[
                "search"
            ],
            on_change=_reset_listing_results,
        )

        seller_contains = st.text_input(
            "Seller",
            key=FILTER_WIDGET_KEYS[
                "seller"
            ],
            on_change=_reset_listing_results,
        )

        recent_only = st.checkbox(
            "Recently added only",
            key=FILTER_WIDGET_KEYS[
                "recent_only"
            ],
            on_change=_reset_listing_results,
        )

        filter_dates = st.checkbox(
            "Limit by activity date",
            key=FILTER_WIDGET_KEYS[
                "filter_dates"
            ],
            on_change=_reset_listing_results,
        )

        date_from = None
        date_through = None

        if filter_dates:
            valid_dates = (
                pd.to_datetime(
                    marketplace_rows[
                        "_activity_sort"
                    ],
                    errors="coerce",
                    utc=True,
                )
                .dropna()
            )

            default_from = (
                valid_dates.min().date()
                if not valid_dates.empty
                else date.today()
            )

            default_through = (
                valid_dates.max().date()
                if not valid_dates.empty
                else date.today()
            )

            date_columns = st.columns(2)

            with date_columns[0]:
                date_from = st.date_input(
                    "Activity from",
                    value=default_from,
                    key=FILTER_WIDGET_KEYS[
                        "activity_from"
                    ],
                    on_change=_reset_listing_results,
                )

            with date_columns[1]:
                date_through = st.date_input(
                    "Activity through",
                    value=default_through,
                    key=FILTER_WIDGET_KEYS[
                        "activity_through"
                    ],
                    on_change=_reset_listing_results,
                )

        verdicts = [
            "all",
            *sorted(
                value
                for value in marketplace_rows[
                    "verdict_display"
                ].dropna().unique()
                if value
            ),
        ]

        verdict = st.selectbox(
            "Review status",
            verdicts,
            key=FILTER_WIDGET_KEYS[
                "verdict"
            ],
            on_change=_reset_listing_results,
        )

        scene = st.selectbox(
            "Collection scene",
            SCENE_OPTIONS,
            key=FILTER_WIDGET_KEYS[
                "scene"
            ],
            on_change=_reset_listing_results,
            help=(
                "Main records shows LP, CD, cassette, and other music media. "
                "Magazines, prints, and video stay on their own scenes."
            ),
        )

        media_group = st.session_state.get(
            FILTER_WIDGET_KEYS["media_group"],
            MEDIA_GROUP_ALL_MUSIC,
        ) or MEDIA_GROUP_ALL_MUSIC
        if media_group == MEDIA_GROUP_LOTS:
            # A leftover format such as EP 7" was hiding the rest of the lot pile.
            st.session_state[FILTER_WIDGET_KEYS["media_type"]] = "all"

        media_types = [
            "all",
            *sorted(
                {
                    *(
                        value
                        for value in marketplace_rows[
                            "media_display"
                        ].dropna().unique()
                        if value
                    ),
                    "BULK_LOT",
                }
            ),
        ]

        media_type = st.selectbox(
            "Media type",
            media_types,
            format_func=lambda value: MEDIA_OPTION_LABELS.get(
                value,
                value,
            ),
            key=FILTER_WIDGET_KEYS[
                "media_type"
            ],
            on_change=_reset_listing_results,
        )

        purchase_filter = st.selectbox(
            "Collection status",
            (
                "all",
                "In collection",
                "Not in collection",
            ),
            key=FILTER_WIDGET_KEYS[
                "purchase"
            ],
            on_change=_reset_listing_results,
        )

        sale_types = [
            "all",
            *sorted(
                value
                for value in marketplace_rows[
                    "sale_type_display"
                ].dropna().unique()
                if value
            ),
        ]

        sale_type = st.selectbox(
            "Sale type",
            sale_types,
            key=FILTER_WIDGET_KEYS[
                "sale_type"
            ],
            on_change=_reset_listing_results,
            format_func=format_sale_type,
        )

        st.divider()

        enable_price_filter = st.checkbox(
            "Filter by price",
            key=FILTER_WIDGET_KEYS[
                "enable_price"
            ],
            on_change=_reset_listing_results,
        )

        price_basis = st.selectbox(
            "Price basis",
            (
                "USD normalized total",
                "Local total",
                "USD hammer before tax",
                "Local hammer before tax",
            ),
            disabled=not enable_price_filter,
            key=FILTER_WIDGET_KEYS[
                "price_basis"
            ],
            on_change=_reset_listing_results,
        )

        minimum_price = None
        maximum_price = None

        if enable_price_filter:
            price_column = {
                "USD normalized total":
                    "total_usd",
                "Local total":
                    "total_local",
                "USD hammer before tax":
                    "hammer_usd",
                "Local hammer before tax":
                    "hammer_local",
            }[price_basis]

            valid_prices = pd.to_numeric(
                marketplace_rows[
                    price_column
                ],
                errors="coerce",
            ).dropna()

            default_maximum = (
                float(valid_prices.max())
                if not valid_prices.empty
                else 0.0
            )

            price_columns = st.columns(2)

            with price_columns[0]:
                minimum_price = st.number_input(
                    "Minimum",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    key=FILTER_WIDGET_KEYS[
                        "minimum_price"
                    ],
                    on_change=_reset_listing_results,
                )

            with price_columns[1]:
                maximum_price = st.number_input(
                    "Maximum",
                    min_value=0.0,
                    value=default_maximum,
                    step=1.0,
                    key=FILTER_WIDGET_KEYS[
                        "maximum_price"
                    ],
                    on_change=_reset_listing_results,
                )

        page_size = st.selectbox(
            "Rows per page",
            PAGE_SIZE_OPTIONS,
            index=2,
            key=FILTER_WIDGET_KEYS[
                "page_size"
            ],
            on_change=_reset_listing_results,
        )

        if st.button(
            "Reload data",
            width="stretch",
            key="collector_refresh_database",
        ):
            load_records.clear()
            relation_columns.clear()
            review_relation.clear()
            _reset_listing_results()
            st.rerun()

    filtered = marketplace_rows.copy()

    if recent_only:
        filtered = filtered[
            filtered[
                "_is_recent_addition"
            ].fillna(False)
        ]

    if search_text.strip():
        needle = search_text.strip().lower()

        searchable = (
            filtered[
                [
                    "title",
                    "listing_id",
                    "seller",
                    "artist_display",
                    "catalog_display",
                    "pressing_token",
                ]
            ]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.lower()
        )

        filtered = filtered[
            searchable.str.contains(
                needle,
                regex=False,
            )
        ]

    if seller_contains.strip():
        filtered = filtered[
            filtered["seller"]
            .fillna("")
            .str.contains(
                seller_contains.strip(),
                case=False,
                regex=False,
            )
        ]

    if filter_dates:
        activity_dates = pd.to_datetime(
            filtered[
                "_activity_sort"
            ],
            errors="coerce",
            utc=True,
        ).dt.date

        filtered = filtered[
            activity_dates.notna()
            & (
                activity_dates
                >= date_from
            )
            & (
                activity_dates
                <= date_through
            )
        ]

    if verdict != "all":
        filtered = filtered[
            filtered["verdict_display"]
            == verdict
        ]

    if media_type == "BULK_LOT":
        filtered = filtered[
            filtered["job_lot"].fillna(False).astype(bool)
        ]
    else:
        if scene != SCENE_ALL and media_group not in MEDIA_GROUPS_SKIP_SCENE:
            filtered = filtered[
                filtered["media_display"].map(
                    lambda value: media_matches_scene(
                        value,
                        scene,
                    )
                )
            ]

        if media_group != MEDIA_GROUP_EVERYTHING and not filtered.empty:
            filtered = filtered.loc[
                [
                    media_matches_group(
                        media,
                        media_group,
                        job_lot=bool(lot),
                    )
                    for media, lot in zip(
                        filtered["media_display"],
                        filtered["job_lot"],
                        strict=True,
                    )
                ]
            ]

        if media_type != "all":
            filtered = filtered[
                filtered["media_display"]
                == media_type
            ]

    if purchase_filter == "In collection":
        filtered = filtered[
            filtered[
                "in_collection_display"
            ]
        ]
    elif purchase_filter == "Not in collection":
        filtered = filtered[
            ~filtered[
                "in_collection_display"
            ]
        ]

    if sale_type != "all":
        filtered = filtered[
            filtered["sale_type_display"]
            == sale_type
        ]

    if enable_price_filter:
        price_column = {
            "USD normalized total":
                "total_usd",
            "Local total":
                "total_local",
            "USD hammer before tax":
                "hammer_usd",
            "Local hammer before tax":
                "hammer_local",
        }[price_basis]

        prices = pd.to_numeric(
            filtered[price_column],
            errors="coerce",
        )

        filtered = filtered[
            prices.notna()
            & (
                prices
                >= minimum_price
            )
            & (
                prices
                <= maximum_price
            )
        ]

    queue = filtered
    identity_queue = st.session_state.get(
        FILTER_WIDGET_KEYS["identity"],
        IDENTITY_QUEUE_ALL,
    ) or IDENTITY_QUEUE_ALL
    if identity_queue != IDENTITY_QUEUE_ALL and not filtered.empty:
        statuses = filtered.get(
            "identity_status_display",
            pd.Series("Unmatched", index=filtered.index),
        ).fillna("Unmatched")
        lots = (
            filtered["job_lot"]
            if "job_lot" in filtered.columns
            else pd.Series(False, index=filtered.index)
        )
        filtered = filtered.loc[
            [
                identity_matches_queue(
                    str(status),
                    identity_queue,
                    job_lot=bool(lot),
                )
                for status, lot in zip(statuses, lots, strict=True)
            ]
        ]

    history = no_bid_auction_rows(queue)
    return (
        sales_without_no_bid_auctions(filtered),
        str(page_size),
        sales_without_no_bid_auctions(queue),
        history,
    )



def render_media_group_pills() -> str:
    """Classify the table by media without hunting in the sidebar."""
    media_key = FILTER_WIDGET_KEYS["media_group"]
    if st.session_state.get(media_key) == MEDIA_GROUP_TWELVE:
        st.session_state[media_key] = MEDIA_GROUP_LP
    st.caption("Classify this view, then click a pile to filter the listings table")
    selected = st.pills(
        "Media",
        MEDIA_GROUP_OPTIONS,
        default=MEDIA_GROUP_ALL_MUSIC,
        key=media_key,
        on_change=_media_group_changed,
        label_visibility="collapsed",
    )
    if selected == MEDIA_GROUP_TWELVE:
        selected = MEDIA_GROUP_LP
    return selected or MEDIA_GROUP_ALL_MUSIC


def _source_count_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Buyee / eBay / Gripsweat-only counts for the unique-sale chart."""
    counts = (
        dataframe.get(
            "source_display",
            pd.Series(dtype="object"),
        )
        .fillna("Other")
        .value_counts()
        .reindex(SOURCE_ORDER, fill_value=0)
    )
    return pd.DataFrame(
        {
            "Marketplace": list(counts.index),
            "Sales": [int(value) for value in counts.values],
        }
    )


def _open_identity_pile(queue: str) -> None:
    """Filter the listings table to one Discogs work pile.

    This runs as a button callback, before the media control is drawn,
    so the Lots chip can change that control.
    """
    st.session_state[FILTER_WIDGET_KEYS["identity"]] = queue
    _identity_queue_changed()


def _identity_pile_counts(dataframe: pd.DataFrame) -> dict[str, int]:
    counts = (
        dataframe.get(
            "identity_status_display",
            pd.Series(dtype="object"),
        )
        .fillna("Unmatched")
        .value_counts()
    )
    return {
        "Filled": int(counts.get("Filled", 0)),
        "Needs review": int(counts.get("Needs review", 0)),
        "Unmatched": int(counts.get("Unmatched", 0)),
        "Lot": int(counts.get("Lot", 0)),
    }


def _render_identity_queue_cards(
    identity_frame: pd.DataFrame,
    *,
    view_label: str,
    lot_count: int = 0,
) -> None:
    """Clickable piles open the matching rows in the table. No charts to decode."""
    counts = _identity_pile_counts(identity_frame)
    filled = counts["Filled"]
    review = counts["Needs review"]
    unmatched = counts["Unmatched"]
    lots = counts["Lot"] or lot_count
    total = filled + review + unmatched
    if view_label == MEDIA_GROUP_LOTS:
        total = lots
    sources = _source_count_caption(identity_frame)
    selected = st.session_state.get(
        FILTER_WIDGET_KEYS["identity"],
        IDENTITY_QUEUE_ALL,
    ) or IDENTITY_QUEUE_ALL
    st.caption(
        f"{view_label} · click Unmatched or Need a decision to open that pile in the table"
    )
    if sources:
        st.caption(sources)
    piles = (
        (IDENTITY_QUEUE_ALL, "all", "All in this view", total),
        ("Filled", "matched", "Matched", filled),
        ("Needs review", "review", "Need a decision", review),
        ("Unmatched", "unmatched", "Unmatched", unmatched),
    )
    if view_label in {MEDIA_GROUP_ALL_MUSIC, MEDIA_GROUP_LOTS} or lots:
        piles = (*piles, ("Lot", "lots", "Lots", lots))
    if view_label == MEDIA_GROUP_LOTS:
        piles = (
            (IDENTITY_QUEUE_ALL, "all", "All lots", lots),
            ("Lot", "lots", "Lots", lots),
        )
    view_slug = re.sub(r"[^a-z0-9]+", "-", view_label.casefold()).strip("-")
    columns = st.columns(len(piles))
    for column, (value, slug, label, count) in zip(columns, piles, strict=True):
        with column:
            showing = selected == value
            suffix = "-on" if showing else ""
            st.button(
                (
                    f"**{format_count(count)}**  \n{label}  \nIn the table"
                    if showing
                    else f"**{format_count(count)}**  \n{label}"
                ),
                key=f"identity-pile-{slug}-{view_slug}{suffix}",
                width="stretch",
                help="Filter the listings table to these rows.",
                disabled=showing,
                on_click=_open_identity_pile,
                args=(value,),
            )
    pile_labels = {
        IDENTITY_QUEUE_ALL: "all listings in this view",
        "Filled": "matched",
        "Needs review": "need a decision",
        "Unmatched": "unmatched",
        "Lot": "lots",
    }
    if selected == IDENTITY_QUEUE_ALL:
        st.caption(
            identity_mix_caption(
                filled,
                review,
                unmatched,
                lots=(
                    lots
                    if view_label in {MEDIA_GROUP_ALL_MUSIC, MEDIA_GROUP_LOTS}
                    else 0
                ),
            )
        )
    else:
        st.caption(
            "Listings table is showing "
            f"{pile_labels.get(selected, selected.lower())}. "
            "Click All in this view to clear it."
        )


def _source_count_caption(dataframe: pd.DataFrame) -> str:
    counts = _source_count_frame(dataframe)
    parts = [
        f"{row.Marketplace} {format_count(int(row.Sales))}"
        for row in counts.itertuples(index=False)
        if int(row.Sales)
    ]
    return " · ".join(parts)


def _render_identity_reflection(
    identity_frame: pd.DataFrame,
    *,
    view_label: str,
    lot_count: int = 0,
) -> None:
    """Clickable identity piles, not a chart to decode."""
    _render_identity_queue_cards(
        identity_frame,
        view_label=view_label,
        lot_count=lot_count,
    )


def _render_sale_history_chart(
    sales: pd.DataFrame,
    history: pd.DataFrame,
    *,
    view_label: str,
) -> None:
    """Show sales beside 0-bid auctions for each format in this view."""
    chart = auction_outcome_chart(sales, history)
    if chart.empty:
        return
    held = int(chart["0-bid auctions"].sum()) if "0-bid auctions" in chart.columns else 0
    st.caption(
        f"{view_label}: a recorded 0 bids is not a sale. "
        f"Relists of a pressing that sold sit on that sale. "
        f"{format_count(held)} unsold offers are on the History tab."
    )
    st.bar_chart(
        chart,
        x="Format",
        y=["Sales", "0-bid auctions"],
        height=220,
    )


def _render_all_music_charts(
    identity_frame: pd.DataFrame,
    *,
    lot_count: int = 0,
    history: pd.DataFrame | None = None,
) -> None:
    """Marketplace counts already sit in the unique-sale cards."""
    _render_identity_reflection(
        identity_frame,
        view_label="All music",
        lot_count=lot_count,
    )
    _render_sale_history_chart(
        identity_frame,
        history if history is not None else pd.DataFrame(),
        view_label="All music",
    )


def _render_media_view_charts(
    filtered: pd.DataFrame,
    identity_frame: pd.DataFrame,
    *,
    view_label: str,
    lot_count: int = 0,
    history: pd.DataFrame | None = None,
) -> None:
    del filtered
    _render_identity_reflection(
        identity_frame,
        view_label=view_label,
        lot_count=lot_count,
    )
    _render_sale_history_chart(
        identity_frame,
        history if history is not None else pd.DataFrame(),
        view_label=view_label,
    )


def render_dataset_overview(
    dataset: pd.DataFrame,
    filtered: pd.DataFrame,
    *,
    media_group: str,
    queue: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
) -> None:
    """Show dataset-wide unique sales only on All music; otherwise the chip view."""
    identity_frame = queue if queue is not None else filtered
    parked_lots = 0
    if "job_lot" in dataset.columns:
        parked_lots = int(dataset["job_lot"].fillna(False).astype(bool).sum())
    if media_group == MEDIA_GROUP_ALL_MUSIC:
        source_counts = _source_count_frame(dataset)
        buyee = int(
            source_counts.loc[source_counts["Marketplace"] == "Buyee", "Sales"].sum()
        )
        ebay = int(
            source_counts.loc[source_counts["Marketplace"] == "eBay", "Sales"].sum()
        )
        gripsweat = int(
            source_counts.loc[source_counts["Marketplace"] == "Gripsweat", "Sales"].sum()
        )
        unique_sales = buyee + ebay + gripsweat
        dataset_metrics = st.columns(4)
        dataset_metrics[0].metric(
            "Unique sales",
            format_count(unique_sales),
            help=(
                f"{format_count(buyee)} Buyee + {format_count(ebay)} eBay + "
                f"{format_count(gripsweat)} Gripsweat-only"
            ),
        )
        dataset_metrics[1].metric(
            "Buyee",
            format_count(buyee),
            help=f"{buyee * 100 // unique_sales}%" if unique_sales else None,
        )
        dataset_metrics[2].metric(
            "eBay",
            format_count(ebay),
            help=f"{ebay * 100 // unique_sales}%" if unique_sales else None,
        )
        dataset_metrics[3].metric(
            "Gripsweat",
            format_count(gripsweat),
            help="Archive rows that are not already on eBay",
        )
        st.caption(
            f"{format_count(unique_sales)} unique sales = "
            f"{format_count(buyee)} Buyee + {format_count(ebay)} eBay + "
            f"{format_count(gripsweat)} Gripsweat-only (no eBay overlap)."
        )
        if parked_lots:
            st.caption(
                f"{format_count(parked_lots)} bulk lots sit on the Lots chip — "
                "click Lots to open them."
            )
        _render_all_music_charts(
            identity_frame,
            lot_count=parked_lots,
            history=history,
        )
        return

    _render_media_view_charts(
        filtered,
        identity_frame,
        view_label=media_group or "This view",
        lot_count=parked_lots if media_group == MEDIA_GROUP_LOTS else 0,
        history=history,
    )


def render_metrics(
    dataframe: pd.DataFrame,
    page_number: int,
    page_count: int,
    *,
    parked_lots: int = 0,
    queue: pd.DataFrame | None = None,
) -> None:
    """Render result-set metrics."""
    metrics = st.columns(6)

    metrics[0].metric(
        "This view",
        format_count(len(dataframe)),
    )

    metrics[1].metric(
        "On this page",
        format_count(
            min(
                len(dataframe),
                int(
                    st.session_state.get(
                        "_page_size",
                        250,
                    )
                ),
            )
        ),
    )

    metrics[2].metric(
        "Page",
        f"{page_number} / {page_count}",
    )

    metrics[3].metric(
        "Sellers",
        format_count(
            dataframe["seller"]
            .replace("", pd.NA)
            .nunique()
        ),
    )

    metrics[4].metric(
        "In collection",
        format_count(
            int(
                dataframe[
                    "in_collection_display"
                ].sum()
            )
        ),
    )

    metrics[5].metric(
        "Pressing groups",
        format_count(
            dataframe[
                "pressing_group_key"
            ]
            .replace("", pd.NA)
            .nunique()
        ),
    )

    identity_counts = (
        (queue if queue is not None else dataframe)
        .get(
            "identity_status_display",
            pd.Series(dtype="object"),
        )
        .fillna("Unmatched")
        .value_counts()
    )
    filled = int(identity_counts.get("Filled", 0))
    needs_review = int(identity_counts.get("Needs review", 0))
    unmatched = int(identity_counts.get("Unmatched", 0))
    lots = int(identity_counts.get("Lot", 0))
    overlap_counts = (
        dataframe.get(
            "overlap_display",
            pd.Series(dtype="object"),
        )
        .fillna("")
        .value_counts()
    )
    shared = int(overlap_counts.get("Shared pressing", 0))
    same_listing = int(overlap_counts.get("Same listing", 0))
    extra_bits = []
    if shared:
        extra_bits.append(f"{format_count(shared)} shared pressings")
    if same_listing:
        extra_bits.append(f"{format_count(same_listing)} same listing")
    extra = f" · {' · '.join(extra_bits)}" if extra_bits else ""
    selected_queue = st.session_state.get(
        FILTER_WIDGET_KEYS["identity"],
        IDENTITY_QUEUE_ALL,
    ) or IDENTITY_QUEUE_ALL
    if selected_queue != IDENTITY_QUEUE_ALL:
        queue_label = {
            "Filled": "matched",
            "Needs review": "need a decision",
            "Unmatched": "unmatched",
            "Lot": "lots",
        }.get(selected_queue, selected_queue.lower())
        st.caption(
            f"Listings table: {queue_label} · "
            f"{format_count(len(dataframe))} rows. "
            "Change the pile with the cards above."
        )
    st.caption(
        identity_mix_caption(
            filled,
            needs_review,
            unmatched,
            lots,
        )
        + extra
    )



def render_listing_table(
    dataframe: pd.DataFrame,
    *,
    key: str,
    show_changed: bool = False,
) -> None:
    """Render a hoverable click-to-review listing grid."""
    duration = pd.to_numeric(
        dataframe.get(
            "auction_duration_days",
            pd.Series(
                pd.NA,
                index=dataframe.index,
            ),
        ),
        errors="coerce",
    ).map(
        lambda value: (
            "—"
            if pd.isna(value)
            else f"{float(value):.2f}"
        )
    )

    identities = _listing_identity_series(
        dataframe
    ).astype(str)

    selected_identity = (
        _current_listing_identity()
    )

    display = pd.DataFrame(
        {
            "__identity":
                identities,
            "__current_listing":
                identities.eq(
                    selected_identity
                ),
            "Marketplace":
                dataframe["marketplace"],
            "Listing ID":
                dataframe["listing_id"],
            "Title":
                dataframe["title"],
            "Copy":
                dataframe["copy_status"]
                if "copy_status" in dataframe.columns
                else "",
            "Seller":
                dataframe["seller"],
            "Sale type":
                dataframe["sale_type_display"],
            "Opened":
                dataframe[
                    "opening_display"
                ].map(format_datetime),
            "Closed":
                dataframe[
                    "closing_display"
                ].map(format_datetime),
            "Added":
                dataframe[
                    "_audit_first_seen_at"
                ].map(format_datetime),
            "Activity":
                dataframe[
                    "_activity_display"
                ].map(format_datetime),
            "Date basis":
                dataframe[
                    "_activity_date_basis"
                ],
            "Duration days":
                duration,
            "Starting bid":
                [
                    format_money(
                        value,
                        currency,
                    )
                    for value, currency in zip(
                        dataframe[
                            "starting_local"
                        ],
                        dataframe[
                            "currency_display"
                        ],
                    )
                ],
            "Hammer before tax":
                [
                    format_money(
                        value,
                        currency,
                    )
                    for value, currency in zip(
                        dataframe[
                            "hammer_local"
                        ],
                        dataframe[
                            "currency_display"
                        ],
                    )
                ],
            "Tax":
                [
                    format_money(
                        value,
                        currency,
                    )
                    for value, currency in zip(
                        dataframe[
                            "tax_local"
                        ],
                        dataframe[
                            "currency_display"
                        ],
                    )
                ],
            "Total with tax":
                [
                    format_money(
                        value,
                        currency,
                    )
                    for value, currency in zip(
                        dataframe[
                            "total_local"
                        ],
                        dataframe[
                            "currency_display"
                        ],
                    )
                ],
            "Total USD":
                dataframe[
                    "total_usd"
                ].map(format_usd),
            "Buyout":
                [
                    format_money(
                        value,
                        currency,
                    )
                    for value, currency in zip(
                        dataframe[
                            "buyout_local"
                        ],
                        dataframe[
                            "currency_display"
                        ],
                    )
                ],
            "Bids":
                [
                    None
                    if pd.isna(value)
                    else int(value)
                    for value in dataframe[
                        "bid_count_display"
                    ]
                ],
            "Cycles":
                dataframe["listing_cycles"]
                if "listing_cycles" in dataframe.columns
                else pd.Series(pd.NA, index=dataframe.index, dtype="Int64"),
            "Days to sell":
                dataframe["days_to_sell"]
                if "days_to_sell" in dataframe.columns
                else pd.Series(pd.NA, index=dataframe.index, dtype="Int64"),
            "Identity":
                dataframe[
                    "identity_status_display"
                ],
            "Overlap":
                dataframe.get(
                    "overlap_display",
                    pd.Series("", index=dataframe.index),
                ),
            "Recent":
                dataframe.get(
                    "recent_change_display",
                    pd.Series("", index=dataframe.index),
                ),
            "Recent detail":
                dataframe.get(
                    "recent_change_detail",
                    pd.Series("", index=dataframe.index),
                ),
            "Updated":
                dataframe[
                    "identity_updated_display"
                ],
            "Label":
                dataframe[
                    "label_display"
                ],
            "Year":
                dataframe[
                    "release_year_display"
                ],
            "Listing photo":
                dataframe[
                    "listing_image_url"
                ],
            "Discogs":
                dataframe[
                    "discogs_thumb_url"
                ],
            "Matrix / catalog":
                dataframe[
                    "catalog_display"
                ],
            "Pressing key":
                dataframe[
                    "pressing_token"
                ],
            "In collection":
                dataframe[
                    "in_collection_display"
                ].map(
                    {
                        True: "Yes",
                        False: "No",
                    }
                ),
            "Verdict":
                dataframe[
                    "verdict_display"
                ],
            "Detail status":
                dataframe[
                    "detail_status_display"
                ],
            "Listing":
                dataframe[
                    "auction_url"
                ],
        }
    )

    link_renderer = JsCode(
        """
        class ListingLinkRenderer {
            init(params) {
                this.eGui = document.createElement("a");

                const url = params.value || "";

                if (!url) {
                    this.eGui.textContent = "";
                    return;
                }

                this.eGui.textContent = "Open ↗";
                this.eGui.href = url;
                this.eGui.target = "_blank";
                this.eGui.rel = "noopener noreferrer";
                this.eGui.className = "collector-listing-link";

                this.eGui.addEventListener(
                    "click",
                    (event) => event.stopPropagation()
                );
            }

            getGui() {
                return this.eGui;
            }
        }
        """
    )

    thumb_renderer = JsCode(
        """
        class IdentityThumbRenderer {
            init(params) {
                this.eGui = document.createElement("div");
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

    selected_row_rule = JsCode(
        """
        function(params) {
            return Boolean(
                params.data
                && params.data.__current_listing
            );
        }
        """
    )

    row_identity = JsCode(
        """
        function(params) {
            return params.data.__identity;
        }
        """
    )

    keep_current_row = JsCode(
        """
        function(params) {
            const api = params.api;
            if (!api || !api.forEachNode) {
                return;
            }
            let index = -1;
            api.forEachNode(function(node) {
                if (index < 0 && node.data && node.data.__current_listing) {
                    index = node.rowIndex;
                }
            });
            if (index < 0) {
                return;
            }
            const first = typeof api.getFirstDisplayedRowIndex === "function"
                ? api.getFirstDisplayedRowIndex()
                : 0;
            const last = typeof api.getLastDisplayedRowIndex === "function"
                ? api.getLastDisplayedRowIndex()
                : first;
            if (index >= first && index <= last) {
                return;
            }
            if (first > 0) {
                return;
            }
            api.ensureIndexVisible(index, "middle");
        }
        """
    )

    grid_options = {
        "columnDefs": [
            {
                "field": "__identity",
                "hide": True,
            },
            {
                "field": "__current_listing",
                "hide": True,
            },
            {
                "field": "Listing photo",
                "headerName": "Photo",
                "pinned": "left",
                "lockPinned": True,
                "width": 68,
                "minWidth": 68,
                "maxWidth": 76,
                "sortable": False,
                "cellRenderer": thumb_renderer,
            },
            {
                "field": "Discogs",
                "headerName": "Discogs",
                "pinned": "left",
                "lockPinned": True,
                "width": 76,
                "minWidth": 76,
                "maxWidth": 84,
                "sortable": False,
                "cellRenderer": thumb_renderer,
            },
            {
                "field": "Recent",
                "headerName": "●",
                "pinned": "left",
                "lockPinned": True,
                "width": 52,
                "minWidth": 52,
                "maxWidth": 64,
                "sortable": True,
                "tooltipField": "Recent detail",
                "headerTooltip": "Changed in the last 7 days",
                "cellStyle": {
                    "textAlign": "center",
                    "fontWeight": "700",
                },
            },
            {
                "field": "Recent detail",
                "headerName": "Changed",
                "hide": not show_changed,
                "pinned": "left" if show_changed else None,
                "width": 168,
                "minWidth": 140,
            },
            {
                "field": "Marketplace",
                "pinned": "left",
                "lockPinned": True,
                "width": 118,
                "minWidth": 105,
            },
            {
                "field": "Listing ID",
                "pinned": "left",
                "lockPinned": True,
                "width": 170,
                "minWidth": 145,
            },
            {
                "field": "Title",
                "pinned": "left",
                "lockPinned": True,
                "width": 480,
                "minWidth": 330,
                "tooltipField": "Title",
            },
            {
                "field": "Seller",
                "width": 190,
                "minWidth": 150,
                "tooltipField": "Seller",
            },
            {
                "field": "Sale type",
                "width": 145,
            },
            {
                "field": "Opened",
                "width": 155,
            },
            {
                "field": "Closed",
                "width": 155,
            },
            {
                "field": "Added",
                "width": 155,
            },
            {
                "field": "Activity",
                "width": 155,
            },
            {
                "field": "Date basis",
                "width": 120,
            },
            {
                "field": "Duration days",
                "width": 125,
            },
            {
                "field": "Starting bid",
                "width": 125,
            },
            {
                "field": "Hammer before tax",
                "width": 155,
            },
            {
                "field": "Tax",
                "width": 105,
            },
            {
                "field": "Total with tax",
                "width": 145,
            },
            {
                "field": "Total USD",
                "width": 120,
            },
            {
                "field": "Buyout",
                "width": 115,
            },
            {
                "field": "Bids",
                "width": 82,
            },
            {
                "field": "Cycles",
                "width": 90,
                "headerTooltip": "How many times this pressing was offered as an auction, including listings with 0 bids",
            },
            {
                "field": "Days to sell",
                "width": 120,
                "headerTooltip": "Days from the first no-bid auction of this pressing to this sale",
            },
            {
                "field": "Identity",
                "width": 128,
            },
            {
                "field": "Updated",
                "width": 100,
            },
            {
                "field": "Label",
                "width": 140,
                "tooltipField": "Label",
            },
            {
                "field": "Year",
                "width": 80,
            },
            {
                "field": "Matrix / catalog",
                "width": 155,
                "tooltipField":
                    "Matrix / catalog",
            },
            {
                "field": "Pressing key",
                "width": 155,
                "tooltipField":
                    "Pressing key",
            },
            {
                "field": "In collection",
                "width": 125,
            },
            {
                "field": "Verdict",
                "width": 155,
            },
            {
                "field": "Detail status",
                "width": 125,
            },
            {
                "field": "Listing",
                "width": 105,
                "sortable": False,
                "cellRenderer":
                    link_renderer,
            },
        ],
        "defaultColDef": {
            "sortable": True,
            "resizable": True,
            "filter": False,
            "editable": False,
            "wrapHeaderText": True,
            "autoHeaderHeight": True,
        },
        "rowSelection": {
            "mode": "singleRow",
            "checkboxes": False,
            "headerCheckbox": False,
            "enableClickSelection": True,
        },
        "cellSelection": False,
        "suppressRowHoverHighlight": False,
        "suppressCellFocus": True,
        "animateRows": False,
        "ensureDomOrder": True,
        "rowHeight": 52,
        "headerHeight": 44,
        "tooltipShowDelay": 150,
        "getRowId": row_identity,
        "suppressScrollOnNewData": True,
        "onFirstDataRendered": keep_current_row,
        "onRowDataUpdated": keep_current_row,
        "rowClassRules": {
            "collector-current-row":
                selected_row_rule,
        },
    }

    custom_css = {
        ".ag-row": {
            "cursor":
                "pointer !important",
        },
        ".ag-row-hover": {
            "background-color":
                "rgba(37, 99, 235, 0.08) !important",
        },
        ".ag-row-selected": {
            "background-color":
                "rgba(37, 99, 235, 0.14) !important",
            "box-shadow":
                "inset 4px 0 0 rgb(37, 99, 235) !important",
        },
        ".collector-current-row": {
            "background-color":
                "rgba(37, 99, 235, 0.14) !important",
            "box-shadow":
                "inset 4px 0 0 rgb(37, 99, 235) !important",
        },
        ".ag-selection-checkbox": {
            "display":
                "none !important",
        },
        ".ag-header-select-all": {
            "display":
                "none !important",
        },
        ".ag-cell": {
            "display":
                "flex",
            "align-items":
                "center",
        },
        ".collector-listing-link": {
            "color":
                "rgb(37, 99, 235) !important",
            "font-weight":
                "600",
            "text-decoration":
                "none",
        },
        ".collector-listing-link:hover": {
            "text-decoration":
                "underline",
        },
    }

    st.caption(
        "Hover over a row to inspect it. Click anywhere on the row to open its details."
    )

    # selectionChanged still fires when server_wins replaces row data.
    # That follow-up has no selected row and was replacing the click
    # before Streamlit could read it. Only a real click may return.
    click_returns_value = JsCode(
        """
        function({streamlitRerunEventTriggerName, eventData}) {
            if (streamlitRerunEventTriggerName === "rowClicked") {
                return true;
            }
            if (streamlitRerunEventTriggerName !== "selectionChanged") {
                return false;
            }
            const source = eventData && eventData.source;
            if (source === "rowDataChanged" || source === "api") {
                return false;
            }
            const api = eventData && eventData.api;
            if (api && api.getSelectedNodes) {
                return api.getSelectedNodes().length > 0;
            }
            return false;
        }
        """
    )

    response = AgGrid(
        display,
        gridOptions=grid_options,
        height=560,
        theme="streamlit",
        update_on=[
            "selectionChanged",
            "rowClicked",
        ],
        should_grid_return=click_returns_value,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        show_toolbar=False,
        server_sync_strategy="server_wins",
        custom_css=custom_css,
        key=key,
    )

    identity = _grid_click_identity(
        response
    )

    if (
        not identity
        or identity
        == selected_identity
    ):
        return

    valid_identities = set(
        identities.tolist()
    )

    if identity not in valid_identities:
        return

    _set_listing_identity(
        identity,
        synchronize_jump=True,
    )

    st.rerun()



def render_pagination(
    page_number: int,
    page_count: int,
    key_prefix: str = "pagination",
) -> None:
    """Render page navigation controls with a unique namespace."""
    columns = st.columns(
        [
            2,
            *([1] * min(page_count, 7)),
            2,
        ]
    )

    with columns[0]:
        if st.button(
            "← Previous",
            disabled=page_number <= 1,
            width="stretch",
            key=f"{key_prefix}:previous",
        ):
            st.session_state[
                "_listing_page"
            ] = page_number - 1
            st.rerun()

    visible_pages = list(
        range(
            1,
            min(page_count, 7) + 1,
        )
    )

    for position, candidate in enumerate(
        visible_pages,
        start=1,
    ):
        with columns[position]:
            label = (
                f"• {candidate} •"
                if candidate == page_number
                else str(candidate)
            )

            if st.button(
                label,
                key=(
                    f"{key_prefix}:"
                    f"page:{candidate}"
                ),
                width="stretch",
            ):
                st.session_state[
                    "_listing_page"
                ] = candidate
                st.rerun()

    with columns[-1]:
        if st.button(
            "Next →",
            disabled=page_number >= page_count,
            width="stretch",
            key=f"{key_prefix}:next",
        ):
            st.session_state[
                "_listing_page"
            ] = page_number + 1
            st.rerun()



def _shortlist_needs_cover(shortlist: list[dict[str, Any]]) -> bool:
    for hit in shortlist:
        if not isinstance(hit, dict) or not hit.get("id"):
            continue
        labels = hit.get("label") or []
        if isinstance(labels, str):
            labels = [labels]
        has_label = any(str(item).strip() for item in labels)
        if not str(hit.get("thumb") or "").strip() or not has_label:
            return True
    return False


def _cover_fields(payload: dict[str, Any]) -> dict[str, Any]:
    draft = map_release_payload(payload)
    names: list[str] = []
    for choice in draft.labels:
        name = (choice.display_name or "").strip()
        if name and name not in names:
            names.append(name)
    if not names and (draft.label_name or "").strip():
        names.append(draft.label_name.strip())
    return {"thumb": draft.discogs_thumb_url or "", "label": names}


def _enrich_shortlist_covers(
    shortlist: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Fill missing Discogs covers and labels, one release lookup per id."""
    client = DiscogsClient(timeout=8.0)
    cache: dict[int, dict[str, Any]] = st.session_state.setdefault(
        "_discogs_cover_cache",
        {},
    )
    changed = False
    updated: list[dict[str, Any]] = []
    looked_up = 0
    for hit in shortlist:
        if not isinstance(hit, dict) or not _shortlist_needs_cover([hit]):
            updated.append(hit)
            continue
        if looked_up >= 3:
            updated.append(hit)
            continue
        looked_up += 1
        release_id = int(hit["id"])
        if release_id not in cache:
            try:
                cache[release_id] = _cover_fields(client.get_release(release_id))
            except DiscogsRateLimitError:
                raise
            except Exception:
                cache[release_id] = {}
        fields = cache[release_id]
        if not fields:
            updated.append(hit)
            continue
        card = dict(hit)
        if fields.get("thumb") and not str(card.get("thumb") or "").strip():
            card["thumb"] = fields["thumb"]
            changed = True
        if fields.get("label") and not card.get("label"):
            card["label"] = list(fields["label"])
            changed = True
        updated.append(card)
    return updated, changed


def _save_shortlist_covers(
    marketplace: str,
    listing_id: str,
    shortlist: list[dict[str, Any]],
) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET discogs_shortlist = CAST(:shortlist AS jsonb)
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
                "shortlist": json.dumps(shortlist, ensure_ascii=False),
            },
        )


def load_identity_shortlist(
    marketplace: str,
    listing_id: str,
) -> list[dict[str, Any]]:
    """Load cached Discogs candidates for one warehouse sale."""
    with get_engine().connect() as connection:
        raw = connection.execute(
            text(
                """
                SELECT discogs_shortlist
                FROM warehouse.auction
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar()

    if raw is None:
        return []
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    if isinstance(raw, list):
        return raw
    return []


_CATALOG_JOBS: dict[str, str] = {}
_CATALOG_HITS: dict[str, list[dict[str, Any]]] = {}
_CATALOG_LOCK = threading.Lock()


def _catalog_job_state(identity: str) -> str | None:
    with _CATALOG_LOCK:
        return _CATALOG_JOBS.get(identity)


def _clear_catalog_job(identity: str) -> None:
    with _CATALOG_LOCK:
        _CATALOG_JOBS.pop(identity, None)


def _ensure_catalog_job(
    identity: str,
    *,
    artist: str | None,
    title: str | None,
    query: str,
    listing_media: str | None,
    listing_image: str | None = None,
) -> None:
    """Look up the catalog the user typed, off the page thread."""
    with _CATALOG_LOCK:
        if _CATALOG_JOBS.get(identity) == "running":
            return
        _CATALOG_JOBS[identity] = "running"

    def work() -> None:
        hits: list[dict[str, Any]] = []
        state = "done"
        try:
            hits = search_user_catalog(
                DiscogsClient(timeout=8.0),
                artist=artist,
                title=title,
                query=query,
                listing_media=listing_media,
            )
        except DiscogsRateLimitError:
            state = "rate_limit"
        except Exception:
            state = "failed"
        if state == "done" and listing_image and hits:
            try:
                hits = rank_catalog_covers(hits, listing_image)
            except Exception:
                pass
        with _CATALOG_LOCK:
            _CATALOG_HITS[identity] = hits
            _CATALOG_JOBS[identity] = state

    threading.Thread(
        target=work,
        name=f"discogs-catalog-{identity}",
        daemon=True,
    ).start()


@st.fragment(run_every="1s")
def _poll_catalog_search(identity: str) -> None:
    """Refresh once the typed catalog search returns."""
    state = _catalog_job_state(identity) or "running"
    if state == "running":
        st.caption("Searching the catalog…")
        return
    if _current_listing_identity() != identity:
        _clear_catalog_job(identity)
        return
    with _CATALOG_LOCK:
        hits = list(_CATALOG_HITS.pop(identity, []))
    st.session_state[f"_catalog_hits:{identity}"] = hits
    st.session_state[f"_catalog_state:{identity}"] = state
    _clear_catalog_job(identity)
    st.rerun(scope="app")


def _render_choice_cards(
    hits: list[dict[str, Any]],
    *,
    marketplace: str,
    listing_id: str,
    identity: str,
    listing_media: str,
    key_prefix: str,
) -> None:
    """One Discogs row with Use this. A format mismatch stays clickable."""
    listing_label = listing_format_label(listing_media)
    for index, hit in enumerate(hits):
        release_id = hit.get("id")
        title = hit.get("title") or f"Release {release_id}"
        catno = hit.get("catno") or ""
        country = hit.get("country") or ""
        year = hit.get("year") or ""
        thumb = hit.get("thumb") or ""
        formats = hit.get("format") or []
        if isinstance(formats, str):
            formats = [formats]
        format_label = discogs_format_label(
            [str(item) for item in formats if str(item).strip()]
        )
        compatible = listing_media_compatible(
            listing_media,
            " ".join(str(item) for item in formats),
        )
        bits = [f"**{format_label}**"] if format_label else []
        if catno:
            bits.append(f"`{catno}`")
        if country:
            bits.append(str(country))
        if year:
            bits.append(str(year))
        else:
            bits.append("release date missing on Discogs")
        labels = hit.get("label") or []
        if isinstance(labels, str):
            labels = [labels]
        label_names: list[str] = []
        for label in labels:
            label_text = str(label).strip()
            if label_text and label_text not in label_names:
                label_names.append(label_text)
        columns = st.columns([1, 4, 1])
        with columns[0]:
            if thumb:
                st.image(thumb, width=96)
            else:
                st.caption("No cover")
        with columns[1]:
            st.markdown(f"**{title}**")
            if bits:
                st.caption(" · ".join(bits))
            if label_names:
                st.markdown(f"Label: {label_names[0]}")
            if listing_label and format_label and not compatible:
                st.caption(
                    f"Different format than this listing ({listing_label})."
                )
        with columns[2]:
            st.button(
                "Use this",
                key=f"{key_prefix}:{identity}:{release_id}:{index}",
                on_click=_commit_discogs_choice,
                args=(
                    marketplace,
                    listing_id,
                    int(release_id),
                    identity,
                ),
            )


@st.fragment
def _shelf_format(hit: dict[str, Any]) -> str:
    """Format chip for the cover shelf. SACD stays its own pile."""
    formats = hit.get("format") or []
    if isinstance(formats, str):
        formats = [formats]
    blob = " ".join(str(item) for item in formats)
    if re.search(r"\bsacd\b|super\s+audio", blob, re.IGNORECASE):
        return "SACD"
    return discogs_format_label(
        [str(item) for item in formats if str(item).strip()]
    ) or "Other"


def _render_cover_grid(
    hits: list[dict[str, Any]],
    *,
    marketplace: str,
    listing_id: str,
    identity: str,
    listing_media: str,
    key_prefix: str,
) -> None:
    """Covers in a row, with the catalog number under the picture."""
    listing_label = listing_format_label(listing_media)
    for start in range(0, len(hits), 4):
        columns = st.columns(4)
        for offset, hit in enumerate(hits[start : start + 4]):
            release_id = hit.get("id")
            catno = hit.get("catno") or ""
            country = hit.get("country") or ""
            year = hit.get("year") or ""
            thumb = hit.get("thumb") or ""
            format_label = _shelf_format(hit)
            with columns[offset]:
                if thumb:
                    st.image(thumb, width=140)
                else:
                    st.caption("No cover")
                st.markdown(f"**{catno or 'No catalog'}**")
                bits = [format_label]
                if country:
                    bits.append(str(country))
                if year:
                    bits.append(str(year))
                st.caption(" · ".join(bits))
                if listing_label and format_label and not listing_media_compatible(
                    listing_media,
                    " ".join(
                        str(item)
                        for item in (
                            hit.get("format")
                            if isinstance(hit.get("format"), list)
                            else [hit.get("format") or ""]
                        )
                    ),
                ):
                    st.caption(f"Different format ({listing_label}).")
                st.button(
                    "Use this",
                    key=f"{key_prefix}:{identity}:{release_id}:{start + offset}",
                    on_click=_commit_discogs_choice,
                    args=(
                        marketplace,
                        listing_id,
                        int(release_id),
                        identity,
                    ),
                )


_CATALOG_PAGE_SIZE = 8


def _render_catalog_shelf(
    hits: list[dict[str, Any]],
    *,
    marketplace: str,
    listing_id: str,
    identity: str,
    listing_media: str,
    key_prefix: str,
) -> None:
    """Browse a large Discogs result by cover and format, not by catalog number."""
    labels: list[str] = []
    for hit in hits:
        label = _shelf_format(hit)
        if label not in labels:
            labels.append(label)
    listing_label = listing_format_label(listing_media)
    options = ["All", *labels] if labels else ["All"]
    format_key = f"catalog-format:{identity}"
    typed = st.session_state.get(f"_catalog_typed:{identity}")
    format_for = f"catalog-format-for:{identity}"
    if format_key not in st.session_state or st.session_state.get(format_for) != typed:
        st.session_state[format_for] = typed
        st.session_state[format_key] = (
            listing_label if listing_label in labels else "All"
        )
    if st.session_state.get(format_key) not in options:
        st.session_state[format_key] = "All"
    chosen = st.radio(
        "Format",
        options,
        horizontal=True,
        key=format_key,
    )
    visible = [hit for hit in hits if chosen == "All" or _shelf_format(hit) == chosen]
    close = [hit for hit in visible if hit.get("photo_same") is True]
    rest = [hit for hit in visible if hit not in close]
    compared = any("photo_distance" in hit for hit in hits)
    if compared:
        st.caption(
            "Same cover means the pixels and the colors agree. "
            "Another picture of the same catalog stays in the list. "
            "Closer colors are first. A spine or disc photo will not match a front cover."
        )
    else:
        st.caption("Browse by cover and format. The catalog number is under each picture.")
    grid_args = dict(
        marketplace=marketplace,
        listing_id=listing_id,
        identity=identity,
        listing_media=listing_media,
    )
    if close:
        st.markdown("**Same cover as the listing photo**")
        _render_cover_grid(close, key_prefix=f"{key_prefix}-close", **grid_args)
    if not rest:
        return
    page_key = f"catalog-page:{identity}:{chosen}"
    page = int(st.session_state.get(page_key, 0) or 0)
    page_count = max(1, (len(rest) + _CATALOG_PAGE_SIZE - 1) // _CATALOG_PAGE_SIZE)
    if page >= page_count:
        page = 0
    start = page * _CATALOG_PAGE_SIZE
    window = rest[start : start + _CATALOG_PAGE_SIZE]
    st.markdown(
        f"**Other releases** — {start + 1}–{start + len(window)} of {len(rest)}"
    )
    _render_cover_grid(window, key_prefix=f"{key_prefix}-page", **grid_args)
    if page_count == 1:
        return
    nav = st.columns(2)
    with nav[0]:
        if page > 0 and st.button("Previous covers", key=f"{key_prefix}-prev:{chosen}"):
            st.session_state[page_key] = page - 1
            st.rerun()
    with nav[1]:
        if page + 1 < page_count and st.button(
            "More covers",
            key=f"{key_prefix}-more:{chosen}",
        ):
            st.session_state[page_key] = page + 1
            st.rerun()


def _render_catalog_search(
    *,
    identity: str,
    artist: str | None,
    title: str | None,
    listing_media: str,
    listing_image: str | None = None,
) -> None:
    """Typed Discogs search when the guessed candidate is the wrong record."""
    st.markdown("**Search catalog**")
    st.caption(
        "Type a catalog number or an album name. "
        "The full Discogs result is listed, with this format first."
    )
    query = st.text_input(
        "Catalog or album",
        key=f"catalog-query:{identity}",
        placeholder="MR 3037 or Best Hits",
        label_visibility="collapsed",
    )
    if st.button("Search catalog", key=f"catalog-go:{identity}"):
        typed = clean_text(query)
        if len(typed) < 2:
            st.session_state[f"_catalog_state:{identity}"] = "short"
        else:
            st.session_state.pop(f"_catalog_hits:{identity}", None)
            st.session_state[f"_catalog_state:{identity}"] = "running"
            st.session_state[f"_catalog_typed:{identity}"] = typed
            _ensure_catalog_job(
                identity,
                artist=artist,
                title=title,
                query=typed,
                listing_media=listing_media or None,
                listing_image=listing_image,
            )
    state = _catalog_job_state(identity) or st.session_state.get(
        f"_catalog_state:{identity}"
    )
    if state == "running" or _catalog_job_state(identity) == "running":
        _poll_catalog_search(identity)
        return
    if state == "short":
        st.caption("Type at least a catalog number or an album name.")
    elif state == "rate_limit":
        st.warning("Discogs rate limit — wait a minute, then search again.")
    elif state == "failed":
        st.warning("Discogs did not finish this search. Try the catalog again.")
    hits = st.session_state.get(f"_catalog_hits:{identity}") or []
    if state == "done" and not hits:
        st.caption("Discogs has no release for that search.")


def _commit_discogs_choice(
    marketplace: str,
    listing_id: str,
    release_id: int,
    identity: str,
) -> None:
    """Persist the clicked Discogs row before the next Review render."""
    apply_release_choice(
        get_engine(),
        marketplace=marketplace,
        listing_id=listing_id,
        release_id=int(release_id),
    )
    load_records.clear()
    revision_key = f"_editor_revision:{identity}"
    st.session_state[revision_key] = int(st.session_state.get(revision_key, 0)) + 1
    st.session_state[f"_finish_condition:{identity}"] = True


_DISCOGS_JOBS: dict[str, str] = {}
_DISCOGS_JOB_LOCK = threading.Lock()


def _discogs_job_state(identity: str) -> str | None:
    """Background Discogs search state for one listing."""
    with _DISCOGS_JOB_LOCK:
        return _DISCOGS_JOBS.get(identity)


def _clear_discogs_job(identity: str) -> None:
    """Forget a finished background search so a retry can start."""
    with _DISCOGS_JOB_LOCK:
        _DISCOGS_JOBS.pop(identity, None)
        _COVER_JOBS.discard(identity)


_COVER_JOBS: set[str] = set()


def _ensure_cover_job(
    identity: str,
    marketplace: str,
    listing_id: str,
    shortlist: list[dict[str, Any]],
) -> None:
    """Fill missing covers after the row is already on screen."""
    with _DISCOGS_JOB_LOCK:
        if identity in _COVER_JOBS:
            return
        _COVER_JOBS.add(identity)
    payload = [dict(hit) for hit in shortlist if isinstance(hit, dict)]

    def work() -> None:
        try:
            client = DiscogsClient(timeout=8.0)
            updated: list[dict[str, Any]] = []
            looked_up = 0
            changed = False
            for hit in payload:
                if not _shortlist_needs_cover([hit]) or looked_up >= 3:
                    updated.append(hit)
                    continue
                looked_up += 1
                try:
                    fields = _cover_fields(client.get_release(int(hit["id"])))
                except Exception:
                    updated.append(hit)
                    continue
                card = dict(hit)
                if fields.get("thumb") and not str(card.get("thumb") or "").strip():
                    card["thumb"] = fields["thumb"]
                    changed = True
                if fields.get("label") and not card.get("label"):
                    card["label"] = list(fields["label"])
                    changed = True
                updated.append(card)
            if changed:
                _save_shortlist_covers(marketplace, listing_id, updated)
        except Exception:
            return

    threading.Thread(
        target=work,
        name=f"discogs-cover-{identity}",
        daemon=True,
    ).start()


def _ensure_discogs_job(
    identity: str,
    marketplace: str,
    listing_id: str,
) -> None:
    """Search Discogs off the page thread so another row can be opened."""
    with _DISCOGS_JOB_LOCK:
        if identity in _DISCOGS_JOBS:
            return
        _DISCOGS_JOBS[identity] = "running"
    engine = get_engine()

    def work() -> None:
        state = "done"
        try:
            research_listing_identity(
                engine,
                marketplace=marketplace,
                listing_id=listing_id,
            )
        except DiscogsRateLimitError:
            state = "rate_limit"
        except Exception:
            state = "failed"
        with _DISCOGS_JOB_LOCK:
            _DISCOGS_JOBS[identity] = state

    threading.Thread(
        target=work,
        name=f"discogs-{identity}",
        daemon=True,
    ).start()


@st.fragment(run_every="1s")
def _poll_discogs_search(identity: str) -> None:
    """Paint the search line, then refresh the page when Discogs returns."""
    state = _discogs_job_state(identity) or "running"
    if state == "running":
        st.caption("Searching Discogs for this sale…")
        return
    # A click on another row already replaced this one. Do not
    # rerun the page back onto the listing whose search just ended.
    if _current_listing_identity() != identity:
        _clear_discogs_job(identity)
        return
    search_key = f"_discogs_live:{identity}"
    if state == "done":
        st.session_state[search_key] = "done"
        load_records.clear()
    elif state == "rate_limit":
        st.session_state[search_key] = "rate_limit"
    else:
        st.session_state[search_key] = "failed"
    _clear_discogs_job(identity)
    st.rerun(scope="app")


def render_identity_shortlist(
    selected: pd.Series,
    *,
    account_context: AccountContext,
    identity: str,
) -> None:
    """Inline Discogs chooser for flagged rows. Never a popup."""
    del account_context
    if as_boolean(selected.get("job_lot")):
        st.info(
            "Bulk lot — leftover box or mixed pile, not an individual Discogs pressing."
        )
        listing_image = clean_text(selected.get("listing_image_url"))
        if listing_image:
            st.image(listing_image, caption="Listing", width=280)
        return
    status = clean_text(selected.get("identity_status"))
    listing_image = clean_text(selected.get("listing_image_url"))
    listing_media = clean_text(
        selected.get("effective_media_type") or selected.get("media_type")
    )
    if listing_media.upper() not in PAPER_MEDIA:
        hint_media, _hint_catalog, _hint_lot = title_classification(
            selected.get("title")
        )
        if clean_text(hint_media).upper() in PAPER_MEDIA:
            listing_media = clean_text(hint_media)
    shortlist = []
    agrees = False
    force_key = f"_discogs_force:{identity}"
    if status in {"needs_review", "unmatched"}:
        shortlist = load_identity_shortlist(
            str(selected["marketplace"]),
            str(selected["listing_id"]),
        )
        listing_token = listing_identity_catalog(
            stored=clean_text(selected.get("catalog_number"))
            or clean_text(selected.get("effective_catalog_number"))
            or None,
            title=clean_text(selected.get("title")) or None,
            artist=clean_text(selected.get("artist")) or None,
            media_type=listing_media,
            infer=False,
        )
        if st.session_state.pop(force_key, None):
            shortlist = []
        agrees = bool(shortlist) and shortlist_agrees_with_listing(
            selected.get("title"),
            shortlist,
            listing_token,
        )
        if shortlist and agrees:
            shortlist = [
                hit
                for hit in shortlist
                if shortlist_agrees_with_listing(
                    selected.get("title"),
                    [hit],
                    listing_token,
                )
            ]
    if (
        status in {"needs_review", "unmatched"}
        and _shortlist_needs_cover(shortlist)
    ):
        _ensure_cover_job(
            identity,
            str(selected["marketplace"]),
            str(selected["listing_id"]),
            shortlist,
        )
    discogs_thumb = ""
    if status in {"filled_auto", "filled_manual"}:
        discogs_thumb = clean_text(selected.get("discogs_thumb_url"))
    else:
        for hit in visible_shortlist_hits(shortlist, title=str(selected.get("title") or "")):
            formats = hit.get("format") or []
            if isinstance(formats, str):
                formats = [formats]
            if listing_media_compatible(
                listing_media,
                " ".join(str(item) for item in formats),
            ):
                discogs_thumb = clean_text(hit.get("thumb"))
                if discogs_thumb:
                    break
    photo_columns = st.columns(2)
    with photo_columns[0]:
        if listing_image:
            st.image(listing_image, caption="Listing", width=160)
        else:
            st.caption("No listing photo stored.")
    with photo_columns[1]:
        if discogs_thumb:
            st.image(discogs_thumb, caption="Discogs", width=160)
    if listing_media.upper() in PAPER_MEDIA:
        st.info(
            "This is a photo or other non-record. "
            "Discogs search stays off so the unmatched records can move."
        )
        return

    _render_catalog_search(
        identity=identity,
        artist=clean_text(selected.get("artist")) or None,
        title=clean_text(selected.get("title")) or None,
        listing_media=listing_media,
        listing_image=listing_image or None,
    )
    catalog_hits = st.session_state.get(f"_catalog_hits:{identity}") or []
    if catalog_hits:
        typed = clean_text(st.session_state.get(f"_catalog_typed:{identity}"))
        scoped = listing_search_artist(
            clean_text(selected.get("artist")) or None,
            clean_text(selected.get("title")) or None,
        )
        if scoped:
            st.caption(
                f"Catalog search for “{typed}” under {scoped}. Pick the cover, then Use this."
            )
        else:
            st.caption(f"Catalog search for “{typed}”. Pick the cover, then Use this.")
        _render_catalog_shelf(
            list(catalog_hits),
            marketplace=str(selected["marketplace"]),
            listing_id=str(selected["listing_id"]),
            identity=identity,
            listing_media=listing_media,
            key_prefix="catalog-choose",
        )

    if status not in {"needs_review", "unmatched"}:
        if st.session_state.get(f"_finish_condition:{identity}"):
            st.info(
                "Matched. This listing stays open. Set the media and cover condition below, then Save."
            )
        return

    search_key = f"_discogs_live:{identity}"
    if not shortlist and st.session_state.get(search_key) != "done":
        if st.session_state.get(search_key) in {"rate_limit", "failed"}:
            if st.session_state.get(search_key) == "rate_limit":
                st.warning("Discogs rate limit — wait a minute, then search again.")
            else:
                st.warning(
                    "Discogs did not finish this search. The sale is still here — search again."
                )
            if st.button("Search Discogs again", key=f"discogs-retry:{identity}"):
                st.session_state.pop(search_key, None)
                _clear_discogs_job(identity)
                st.rerun()
            return
        _ensure_discogs_job(
            identity,
            str(selected["marketplace"]),
            str(selected["listing_id"]),
        )
        _poll_discogs_search(identity)
        return

    shortlist = shortlist or load_identity_shortlist(
        str(selected["marketplace"]),
        str(selected["listing_id"]),
    )
    if not shortlist:
        if st.session_state.get(search_key) == "done":
            st.warning(
                "Discogs has no release for this sleeve in the artist's catalog. "
                "The sale stays unmatched."
            )
        else:
            st.caption("No Discogs shortlist for this sale yet.")
        if st.button("Search Discogs", key=f"discogs-search:{identity}"):
            st.session_state.pop(search_key, None)
            _clear_discogs_job(identity)
            st.rerun()
        return

    st.markdown("**Discogs candidates** — LP, EP / 7\", and CD are separate options. Match the listing photo.")
    if not agrees:
        if st.button("Search Discogs", key=f"discogs-search-open:{identity}"):
            st.session_state[force_key] = True
            st.session_state.pop(f"_discogs_live:{identity}", None)
            _clear_discogs_job(identity)
            st.rerun()
    shown_hits = visible_shortlist_hits(
        shortlist,
        title=str(selected.get("title") or ""),
    )
    if not shown_hits:
        st.caption(
            "None of the stored candidates is the album named in this title."
        )
        if st.button("Search Discogs", key=f"discogs-search-filtered:{identity}"):
            st.session_state[force_key] = True
            st.session_state.pop(f"_discogs_live:{identity}", None)
            _clear_discogs_job(identity)
            st.rerun()
        return
    _render_choice_cards(
        shown_hits,
        marketplace=str(selected["marketplace"]),
        listing_id=str(selected["listing_id"]),
        identity=identity,
        listing_media=listing_media,
        key_prefix="identity-choose",
    )


def render_listing_editor(
    dataframe: pd.DataFrame,
    account_context: AccountContext,
) -> None:
    """Open the selected listing under the table."""
    if (
        _selected_listing_row(dataframe)
        is None
    ):
        st.caption(
            "Select any table row or use the sidebar search to open its details."
        )
        return

    _render_listing_editor_body(
        dataframe,
        account_context,
    )


def _render_listing_editor_body(
    dataframe: pd.DataFrame,
    account_context: AccountContext,
) -> None:
    """Render the editor for the stable selected identity."""
    selected = _selected_listing_row(
        dataframe
    )

    if selected is None:
        st.info(
            "That listing is no longer in this view."
        )
        return

    marketplace = selected[
        "marketplace"
    ]

    listing_id = selected[
        "listing_id"
    ]

    identity = listing_identity(
        marketplace,
        listing_id,
    )

    revision_key = (
        f"_editor_revision:{identity}"
    )

    revision = int(
        st.session_state.get(
            revision_key,
            0,
        )
    )

    key_prefix = (
        f"editor:{identity}:{revision}:facts:"
    )
    media_automatic = automatic_media_type(selected, MEDIA_OPTIONS)
    catalog_automatic = automatic_catalog(selected)
    region_automatic = automatic_region(selected, REGION_OPTIONS)
    disc_automatic = automatic_disc_count(selected)
    pressing_type_automatic = automatic_pressing_type(
        selected,
        PRESSING_TYPE_OPTIONS,
    )
    pressing_group_automatic = derive_pressing_token(
        override=clean_text(
            collector_value(selected, "manual_pressing_group")
        )
        or None,
        catalog_number=clean_text(selected.get("catalog_number"))
        or clean_text(selected.get("effective_catalog_number"))
        or None,
        title=clean_text(selected.get("title")) or None,
    ) or automatic_pressing_group(selected)
    sale_automatic = automatic_sale_type(selected, SALE_TYPE_OPTIONS)

    st.divider()

    if st.session_state.get("_editor_outside_filter"):
        st.caption(
            "This sale left the current filter. It stays open so you can finish the condition and Save. Close leaves it."
        )

    heading_columns = st.columns(
        [5, 1, 1]
    )

    with heading_columns[0]:
        st.subheader(
            selected["title"]
            or listing_id
        )

        st.markdown(
            (
                '<div class="collector-subtle">'
                f"{marketplace} · "
                f"{listing_id} · "
                f"{selected['seller']}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    with heading_columns[1]:
        if selected["auction_url"]:
            st.link_button(
                "Open listing ↗",
                selected["auction_url"],
                width="stretch",
            )

    with heading_columns[2]:
        if st.button(
            "Close",
            key=f"clear_listing:{identity}",
            width="stretch",
            help="Close this listing. The match and saved grades stay.",
        ):
            _request_clear_listing_identity()
            st.rerun()

    summary_columns = st.columns(6)

    summary_columns[0].metric(
        "Starting price",
        format_money(
            selected["starting_local"],
            selected["currency_display"],
        ),
    )

    summary_columns[1].metric(
        "Sale price before tax",
        format_money(
            selected["hammer_local"],
            selected["currency_display"],
        ),
    )

    summary_columns[2].metric(
        "Tax",
        format_money(
            selected["tax_local"],
            selected["currency_display"],
        ),
    )

    summary_columns[3].metric(
        "Total with tax",
        format_money(
            selected["total_local"],
            selected["currency_display"],
        ),
    )

    summary_columns[4].metric(
        "Total USD",
        format_usd(
            selected["total_usd"]
        ),
    )

    bid_count = selected["bid_count_display"]
    summary_columns[5].metric(
        "Bids",
        "—"
        if pd.isna(bid_count)
        else int(bid_count),
    )

    st.caption(
        " · ".join(
            (
                (
                    "Opened: "
                    f"{format_datetime(selected['opening_display'])}"
                ),
                (
                    "Closed: "
                    f"{format_datetime(selected['closing_display'])}"
                ),
                (
                    "Detail: "
                    f"{selected['detail_status_display'] or 'not available'}"
                ),
                (
                    "Identity: "
                    f"{selected.get('identity_status_display') or 'Unmatched'}"
                ),
                (
                    "Overlap: "
                    f"{selected.get('overlap_display') or '—'}"
                ),
                (
                    "Label: "
                    f"{clean_text(selected.get('label_display')) or '—'}"
                ),
                (
                    "Year: "
                    f"{clean_text(selected.get('release_year_display')) or '—'}"
                ),
                (
                    "Pressing key: "
                    f"{clean_text(selected.get('pressing_token')) or 'not assigned'}"
                ),
                (
                    "Cycles: "
                    + (
                        str(int(selected["listing_cycles"]))
                        if pd.notna(selected.get("listing_cycles"))
                        else "—"
                    )
                ),
                (
                    "Days to sell: "
                    + (
                        str(int(selected["days_to_sell"]))
                        if pd.notna(selected.get("days_to_sell"))
                        else "—"
                    )
                ),
            )
        )
    )

    render_identity_shortlist(
        selected,
        account_context=account_context,
        identity=identity,
    )

    is_lot = as_boolean(selected.get("job_lot"))

    @st.fragment
    def _collector_editor_fragment() -> None:
        saved_media_type = clean_text(
            collector_value(
                selected,
                "manual_media_type",
            )
        )
        media_automatic_choice = (
            "BULK_LOT" if is_lot else media_automatic
        )
        media_key = key_prefix + "manual_media_type"
        if not saved_media_type:
            media_key += ":" + (media_automatic_choice or "auto")
        manual_media_type = optional_selectbox(
            "Media type",
            MEDIA_OPTIONS,
            form_choice(
                saved_media_type,
                media_automatic_choice,
                MEDIA_OPTIONS,
            ),
            key=media_key,
            help=(
                "Bulk lot is several records in one sale, not one album. "
                "Photo, print, and magazine are not records. "
                "The grades below follow the format you pick."
            ),
            format_func=lambda value: MEDIA_OPTION_LABELS.get(
                value, value
            ),
        )
        lot_mode = clean_text(manual_media_type) == "BULK_LOT"
        paper_mode = clean_text(manual_media_type).upper() in PAPER_MEDIA
        if lot_mode:
            st.subheader("Bulk lot review")
            st.caption(
                "This sale is not one title. Count the records, "
                "give the pile one grade, and save. "
                "Discogs identity stays off."
            )
            manual_catalog_number = ""
            manual_region = "Automatic / unset"
            manual_disc_count = st.number_input(
                "Records in the lot",
                min_value=0,
                max_value=500,
                value=form_disc_count(
                    collector_value(
                        selected,
                        "manual_disc_count",
                    ),
                    disc_automatic,
                ),
                step=1,
                help="How many records are in this sale.",
                key=key_prefix + "lot_record_count",
            )
            manual_pressing_type = "Automatic / unset"
            manual_pressing_group = ""
        elif paper_mode:
            st.caption(
                "This is not a record. One condition is enough. "
                "Discogs identity stays off."
            )
            manual_catalog_number = ""
            manual_region = "Automatic / unset"
            manual_disc_count = 0
            manual_pressing_type = "Automatic / unset"
            manual_pressing_group = ""
        else:
            st.subheader(
                "Pressing identification"
            )

            core_columns = st.columns(4)

            with core_columns[0]:
                manual_catalog_number = st.text_input(
                    "Catalog / matrix number",
                    value=form_text(
                        collector_value(
                            selected,
                            "manual_catalog_number",
                        ),
                        catalog_automatic,
                    ),
                    key=(
                        key_prefix
                        + "manual_catalog_number"
                    ),
                )

            with core_columns[1]:
                manual_region = optional_selectbox(
                    "Region",
                    REGION_OPTIONS,
                    form_choice(
                        collector_value(
                            selected,
                            "manual_region",
                        ),
                        region_automatic,
                        REGION_OPTIONS,
                    ),
                    key=(
                        key_prefix
                        + "manual_region"
                    ),
                )

            with core_columns[2]:
                manual_disc_count = st.number_input(
                    "Disc count",
                    min_value=0,
                    max_value=100,
                    value=form_disc_count(
                        collector_value(
                            selected,
                            "manual_disc_count",
                        ),
                        disc_automatic,
                    ),
                    step=1,
                    help=(
                        "Use 0 to preserve automatic classification."
                    ),
                    key=(
                        key_prefix
                        + "manual_disc_count"
                    ),
                )

            saved_pressing_type = clean_text(
                collector_value(
                    selected,
                    "manual_pressing_type",
                )
            )
            pressing_type_key = key_prefix + "manual_pressing_type"
            if not saved_pressing_type:
                pressing_type_key += ":" + (pressing_type_automatic or "auto")
            with core_columns[3]:
                manual_pressing_type = optional_selectbox(
                    "Pressing type",
                    PRESSING_TYPE_OPTIONS,
                    form_choice(
                        saved_pressing_type,
                        pressing_type_automatic,
                        PRESSING_TYPE_OPTIONS,
                    ),
                    help=(
                        "First pressing means this copy's year is the "
                        "earliest release date of this record. A later "
                        "year is a later press. 180 gram and new vinyl "
                        "copies are later presses. A promo stays a promo."
                    ),
                    format_func=lambda value: pressing_type_label(
                        value,
                        display_release_year(
                            pressing_year=selected.get("effective_release_year"),
                            title=selected.get("title"),
                        ),
                    ),
                    key=pressing_type_key,
                )

            saved_pressing_group = clean_text(
                collector_value(
                    selected,
                    "manual_pressing_group",
                )
            )
            pressing_group_key = key_prefix + "manual_pressing_group"
            if not saved_pressing_group:
                pressing_group_key += ":" + (pressing_group_automatic or "auto")
            manual_pressing_group = st.text_input(
                "Pressing group",
                value=form_text(
                    saved_pressing_group,
                    pressing_group_automatic,
                ),
                placeholder=(
                    "Optional canonical matrix/catalog identity"
                ),
                help=(
                    "Listings with the same normalized value are grouped "
                    "even when their titles differ."
                ),
                key=pressing_group_key,
            )

        shown_media = clean_text(manual_media_type)
        if shown_media in {"", "Automatic / unset"}:
            shown_media = clean_text(media_automatic)
        if lot_mode:
            shown_media = "BULK_LOT"
        profile = condition_profile(shown_media)
        grade_options = condition_grade_options(profile["scale"])
        grade_help = profile["help"] or None
        st.subheader(
            "Condition and assessment"
        )
        if profile["caption"]:
            st.caption(profile["caption"])
        if st.session_state.get(f"_finish_condition:{identity}"):
            st.caption(
                "Set the grades for this copy, then Save."
                if profile["kind"] != "lot"
                else "Set one grade for the pile, then Save."
            )
        verdict_columns = st.columns(4)
        with verdict_columns[0]:
            saved_media_grade = collector_value(
                selected,
                "manual_condition_media",
            )
            automatic_media_grade = (
                clean_text(selected.get("effective_condition_media")) or None
            )
            manual_condition_media = optional_selectbox(
                profile["media_label"],
                grade_options,
                form_choice(
                    saved_media_grade,
                    automatic_media_grade,
                    grade_options,
                ),
                help=grade_help,
                key=automatic_widget_key(
                    key_prefix
                    + "manual_condition_media:"
                    + profile["kind"],
                    saved_media_grade,
                    automatic_media_grade,
                ),
            )
        with verdict_columns[1]:
            saved_cover_grade = collector_value(
                selected,
                "manual_condition_cover",
            )
            automatic_cover_grade = (
                clean_text(selected.get("effective_condition_cover")) or None
            )
            if profile["kind"] in {"lot", "paper"}:
                manual_condition_cover = "Automatic / unset"
            else:
                manual_condition_cover = optional_selectbox(
                    profile["cover_label"],
                    grade_options,
                    form_choice(
                        saved_cover_grade,
                        automatic_cover_grade,
                        grade_options,
                    ),
                    help=grade_help,
                    key=automatic_widget_key(
                        key_prefix
                        + "manual_condition_cover:"
                        + profile["kind"],
                        saved_cover_grade,
                        automatic_cover_grade,
                    ),
                )
        with verdict_columns[2]:
            manual_importance_score = st.number_input(
                "Importance score",
                min_value=0,
                max_value=100,
                value=form_disc_count(
                    collector_value(
                        selected,
                        "manual_importance_score",
                    ),
                    safe_int(selected.get("effective_importance_score")) or 0,
                ),
                step=1,
                key=(
                    key_prefix
                    + "manual_importance_score"
                ),
            )
        with verdict_columns[3]:
            manual_verdict = optional_selectbox(
                "Verdict",
                VERDICT_OPTIONS,
                form_choice(
                    collector_value(
                        selected,
                        "manual_verdict",
                    ),
                    clean_text(selected.get("effective_verdict")) or None,
                    VERDICT_OPTIONS,
                ),
                key=(
                    key_prefix
                    + "manual_verdict"
                ),
            )
        manual_completeness_notes = st.text_area(
            "Completeness / pressing notes",
            value=notes_without_insert_fact(
                collector_value(
                    selected,
                    "manual_completeness_notes",
                )
            ),
            height=110,
            key=(
                key_prefix
                + "manual_completeness_notes"
            ),
        )
        manual_collector_notes = st.text_area(
            "Collector notes",
            value=clean_text(
                collector_value(
                    selected,
                    "manual_collector_notes",
                )
            ),
            height=140,
            key=(
                key_prefix
                + "manual_collector_notes"
            ),
        )

        st.subheader(
            "Sale and collection"
        )

        sale_columns = st.columns(5)

        with sale_columns[0]:
            manual_sale_type = optional_selectbox(
                "Sale type",
                SALE_TYPE_OPTIONS,
                form_choice(
                    collector_value(
                        selected,
                        "manual_sale_type",
                    ),
                    sale_automatic,
                    SALE_TYPE_OPTIONS,
                ),
                key=(
                    key_prefix
                    + "manual_sale_type"
                ),
            )

        with sale_columns[1]:
            in_collection = st.checkbox(
                "In my collection",
                value=as_boolean(
                    collector_value(
                        selected,
                        "in_collection",
                    )
                ),
                key=(
                    key_prefix
                    + "in_collection"
                ),
            )

        existing_purchase_date = pd.to_datetime(
            collector_value(
                selected,
                "purchase_date",
            ),
            errors="coerce",
        )

        with sale_columns[2]:
            purchase_date = st.date_input(
                "Purchase date",
                value=(
                    existing_purchase_date.date()
                    if not pd.isna(
                        existing_purchase_date
                    )
                    else date.today()
                ),
                disabled=not in_collection,
                key=(
                    key_prefix
                    + "purchase_date"
                ),
            )

        with sale_columns[3]:
            purchase_price = st.number_input(
                "Purchase price",
                min_value=0.0,
                value=(
                    safe_float(
                        collector_value(
                            selected,
                            "purchase_price",
                        )
                    )
                    or 0.0
                ),
                step=1.0,
                disabled=not in_collection,
                key=(
                    key_prefix
                    + "purchase_price"
                ),
            )

        with sale_columns[4]:
            purchase_currency = st.selectbox(
                "Purchase currency",
                (
                    "USD",
                    "JPY",
                    "GBP",
                    "EUR",
                    "CAD",
                    "AUD",
                    "HKD",
                ),
                index=(
                    (
                        "USD",
                        "JPY",
                        "GBP",
                        "EUR",
                        "CAD",
                        "AUD",
                        "HKD",
                    ).index(
                        clean_text(
                            collector_value(
                                selected,
                                "purchase_currency",
                            )
                        )
                        or (
                            selected[
                                "currency_display"
                            ]
                            if selected[
                                "currency_display"
                            ]
                            in {
                                "USD",
                                "JPY",
                                "GBP",
                                "EUR",
                                "CAD",
                                "AUD",
                                "HKD",
                            }
                            else "USD"
                        )
                    )
                ),
                disabled=not in_collection,
                key=(
                    key_prefix
                    + "purchase_currency"
                ),
            )

        if lot_mode:
            st.subheader("Edition and completeness")
            st.caption(
                "A mixed lot has no single obi, booklet, poster, or sleeve."
            )
            manual_bulk_lot = "Yes"
            manual_obi = "Automatic / unset"
            manual_insert = "Automatic / unset"
            manual_poster = "Automatic / unset"
            manual_rental = "Automatic / unset"
            manual_sticker = "Automatic / unset"
            manual_sealed = "Automatic / unset"
        elif paper_mode:
            st.subheader("Edition and completeness")
            st.caption("A photo, print, or magazine has no obi, booklet, or poster.")
            manual_bulk_lot = "No" if is_lot else "Automatic / unset"
            manual_obi = "No"
            manual_insert = "No"
            manual_poster = "No"
            manual_rental = "No"
            manual_sticker = "No"
            manual_sealed = "No"
        else:
            st.subheader(
                "Edition and completeness"
            )
            catalog_note = clean_text(
                selected.get("catalog_completeness")
            )
            if catalog_note and profile["kind"] != "lp":
                st.caption(catalog_note)

            edition_media = clean_text(manual_media_type)
            if edition_media in {"", "Automatic / unset"}:
                edition_media = clean_text(media_automatic)
            cassette_copy = _is_cassette(edition_media)
            manual_bulk_lot = "No" if is_lot else "Automatic / unset"
            poster_reference = clean_text(selected.get("catalog_poster"))
            poster_manual = collector_value(selected, "manual_poster_present")
            resolved_region = clean_text(manual_region)
            if resolved_region in {"", "Automatic / unset"}:
                resolved_region = clean_text(region_automatic)
            japan_market = obi_for_region(resolved_region)
            show_obi = profile.get("show_obi") == "yes" and japan_market
            show_poster = profile.get("show_poster") == "yes"
            if profile["kind"] == "ep" and (
                poster_reference == "included" or as_boolean(poster_manual)
            ):
                show_poster = True
            part_note = {
                "cd": (
                    "A CD has a booklet. It does not have a poster. "
                    "Obi is only on a Japanese pressing."
                ),
                "ep": (
                    "This 7\" catalog includes a poster. The insert is still the sheet. "
                    "Obi is only on a Japanese pressing."
                    if show_poster
                    else "A 7\" has an insert. Obi is only on a Japanese pressing."
                ),
                "lp": (
                    "Complete means this copy still has what the factory included. "
                    "Obi is only on a Japanese pressing. "
                    "A sealed copy can still be any of these packs."
                ),
                "cassette": (
                    "A cassette has a lyric card. It does not have an obi or a poster."
                ),
            }.get(profile["kind"])
            if part_note:
                st.caption(part_note)
            slots = []
            if show_obi:
                slots.append("obi")
            slots.append("insert")
            if show_poster:
                slots.append("poster")
            slots.append("rental")
            completeness_columns_1 = st.columns(len(slots))
            column_for = dict(zip(slots, completeness_columns_1, strict=True))

            saved_insert_fact = notes_insert_fact(
                collector_value(selected, "manual_completeness_notes")
            )
            insert_current = form_flag(
                selected,
                "manual_insert_present",
                "effective_insert_present",
            )
            if (
                cassette_copy
                and is_missing(collector_value(selected, "manual_insert_present"))
                and is_missing(insert_current)
            ):
                insert_current = True
            insert_options = (
                "Automatic / unset",
                "Yes",
                "Insert only",
                "Pin-up is the insert",
                "Factory no insert",
                "No",
            )
            if saved_insert_fact == PINUP_INSERT_NOTE:
                insert_choice = "Pin-up is the insert"
            elif saved_insert_fact == INSERT_ONLY_NOTE:
                insert_choice = "Insert only"
            elif saved_insert_fact == FACTORY_NO_INSERT_NOTE:
                insert_choice = "Factory no insert"
            elif is_missing(insert_current):
                insert_choice = "Automatic / unset"
            elif as_boolean(insert_current):
                insert_choice = "Yes"
            else:
                insert_choice = "No"
            insert_key = automatic_widget_key(
                key_prefix + "manual_insert:" + profile["kind"],
                saved_insert_fact
                or collector_value(selected, "manual_insert_present"),
                insert_choice,
            )
            live_insert = st.session_state.get(insert_key, insert_choice)
            insert_only = (
                profile["kind"] == "lp" and live_insert == "Insert only"
            )
            insert_help = (
                "The booklet. A CD does not have a poster."
                if profile["kind"] == "cd"
                else "The lyric card. A cassette does not have an obi or a poster."
                if profile["kind"] == "cassette"
                else "The sheet or picture sleeve. A Japanese copy can also have an obi."
                if profile["kind"] == "ep"
                else "Yes is an insert beside the other parts. "
                "Insert only means that sheet is all the factory included. "
                "Pin-up is the insert means that pin-up is the sheet. "
                "Factory no insert means this pressing never included one."
                if profile["kind"] == "lp"
                else "The booklet, lyric sheet, or extra paper."
            )

            if show_obi:
                with column_for["obi"]:
                    obi_current = form_flag(
                        selected,
                        "manual_obi",
                        "effective_obi",
                    )
                    obi_key = automatic_widget_key(
                        key_prefix + "manual_obi",
                        collector_value(selected, "manual_obi"),
                        obi_current,
                    )
                    if insert_only:
                        obi_key += ":insert-only"
                        st.session_state[obi_key] = "No"
                        manual_obi = st.selectbox(
                            "Obi",
                            TRI_STATE_OPTIONS,
                            help="Insert only means the factory did not include an obi.",
                            key=obi_key,
                            disabled=True,
                        )
                    else:
                        manual_obi = tri_state_selectbox(
                            "Obi",
                            obi_current,
                            help="The paper strip on a Japanese pressing.",
                            key=obi_key,
                        )
            elif profile.get("show_obi") == "yes" and resolved_region:
                manual_obi = "No"
            elif profile.get("show_obi") != "yes":
                manual_obi = "No"
            else:
                stored_obi = collector_value(selected, "manual_obi")
                if is_missing(stored_obi):
                    manual_obi = "Automatic / unset"
                elif as_boolean(stored_obi):
                    manual_obi = "Yes"
                else:
                    manual_obi = "No"

            with column_for["insert"]:
                if profile["kind"] == "lp":
                    manual_insert = st.selectbox(
                        profile["insert_label"],
                        insert_options,
                        index=insert_options.index(insert_choice),
                        help=insert_help,
                        key=insert_key,
                    )
                else:
                    manual_insert = tri_state_selectbox(
                        profile["insert_label"],
                        insert_current,
                        help=insert_help,
                        key=automatic_widget_key(
                            key_prefix + "manual_insert",
                            collector_value(selected, "manual_insert_present"),
                            insert_current,
                        ),
                    )

            insert_owns_poster = manual_insert in {
                "Pin-up is the insert",
                "Insert only",
            }
            if show_poster:
                with column_for["poster"]:
                    if profile["kind"] == "lp":
                        poster_options = (
                            "Automatic / unset",
                            "Pin-up is the poster",
                            "No",
                        )
                        if insert_owns_poster:
                            poster_choice = "No"
                        else:
                            poster_current = form_flag(
                                selected,
                                "manual_poster_present",
                                "effective_poster_present",
                            )
                            if (
                                is_missing(poster_manual)
                                and is_missing(poster_current)
                                and poster_reference == "not_included"
                            ):
                                poster_choice = "No"
                            elif as_boolean(poster_current):
                                poster_choice = "Pin-up is the poster"
                            elif is_missing(poster_current):
                                poster_choice = "Automatic / unset"
                            else:
                                poster_choice = "No"
                        poster_key = automatic_widget_key(
                            key_prefix + "manual_poster:" + profile["kind"],
                            "insert-owns" if insert_owns_poster else poster_manual,
                            poster_choice,
                        )
                        if insert_owns_poster:
                            st.session_state[poster_key] = "No"
                            manual_poster = st.selectbox(
                                profile.get("poster_label") or "Poster / pin-up",
                                poster_options,
                                help=(
                                    "Insert only came with that sheet. "
                                    "Pin-up is the insert has no separate poster."
                                ),
                                key=poster_key,
                                disabled=True,
                            )
                        else:
                            manual_poster = st.selectbox(
                                profile.get("poster_label") or "Poster / pin-up",
                                poster_options,
                                index=poster_options.index(poster_choice),
                                help=(
                                    "Pin-up is the poster means a separate pin-up. "
                                    "No means this copy has no separate poster."
                                ),
                                key=poster_key,
                            )
                    else:
                        poster_current = form_flag(
                            selected,
                            "manual_poster_present",
                            "effective_poster_present",
                        )
                        manual_poster = tri_state_selectbox(
                            "Poster",
                            poster_current,
                            help="This catalog's reference includes a poster.",
                            key=automatic_widget_key(
                                key_prefix + "manual_poster:" + profile["kind"],
                                poster_manual,
                                poster_current,
                            ),
                        )
            else:
                manual_poster = "No"

            with column_for["rental"]:
                rental_current = form_flag(
                    selected,
                    "manual_rental",
                    "effective_rental",
                )
                if (
                    cassette_copy
                    and is_missing(collector_value(selected, "manual_rental"))
                    and is_missing(rental_current)
                ):
                    rental_current = False
                manual_rental = tri_state_selectbox(
                    "Rental",
                    rental_current,
                    help=(
                        "A rental copy is a shop rental. It carries its own sticker. "
                        "No rental means no rental sticker."
                    ),
                    key=automatic_widget_key(
                        key_prefix + "manual_rental",
                        collector_value(selected, "manual_rental"),
                        rental_current,
                    ),
                )

            if profile["kind"] == "lp":
                st.caption(
                    factory_pack_sentence(
                        obi_label_for_region(manual_obi, resolved_region),
                        manual_insert,
                        manual_poster,
                    )
                )

            completeness_columns_2 = st.columns(3)

            rental_choice_value = tri_state_value(manual_rental)
            rental_is_yes = rental_choice_value is True
            rental_is_no = rental_choice_value is False
            with completeness_columns_2[0]:
                sticker_current = form_flag(
                    selected,
                    "manual_sticker",
                    "effective_sticker",
                )
                if rental_is_yes:
                    sticker_current = True
                elif rental_is_no:
                    sticker_current = False
                sticker_key = automatic_widget_key(
                    key_prefix + "manual_sticker",
                    None if rental_is_yes or rental_is_no else collector_value(selected, "manual_sticker"),
                    sticker_current,
                )
                if rental_is_yes:
                    sticker_key += ":rental-yes"
                elif rental_is_no:
                    sticker_key += ":rental-no"
                sticker_help = (
                    "A rental copy always has the rental sticker."
                    if rental_is_yes
                    else "No rental means this copy has no rental sticker."
                    if rental_is_no
                    else "The sticker on a rental copy. A shop copy of this catalog does not have one."
                )
                if rental_is_yes or rental_is_no:
                    # A typed sticker does not win. No rental is No sticker.
                    st.session_state[sticker_key] = "Yes" if rental_is_yes else "No"
                    manual_sticker = st.selectbox(
                        "Rental sticker",
                        TRI_STATE_OPTIONS,
                        key=sticker_key,
                        disabled=True,
                        help=sticker_help,
                    )
                else:
                    manual_sticker = tri_state_selectbox(
                        "Rental sticker",
                        sticker_current,
                        help=sticker_help,
                        key=sticker_key,
                    )

            with completeness_columns_2[1]:
                sealed_current = form_flag(
                    selected,
                    "manual_sealed",
                    "effective_sealed",
                )
                manual_sealed = tri_state_selectbox(
                    "Sealed",
                    sealed_current,
                    help=(
                        "No unless the listing says this copy is sealed."
                    ),
                    key=automatic_widget_key(
                        key_prefix + "manual_sealed",
                        collector_value(selected, "manual_sealed"),
                        sealed_current,
                    ),
                )

            with completeness_columns_2[2]:
                observed = seller_condition_summary(
                    "\n".join(
                        part
                        for part in (
                            clean_text(selected.get("title")),
                            clean_text(selected.get("seller_report_text")),
                        )
                        if part
                    )
                )
                plain_condition = clean_text(selected.get("condition_text", ""))
                if plain_condition.casefold() in {"used", "pre-owned", "preowned"}:
                    plain_condition = ""
                st.text_input(
                    "Observed condition",
                    value=observed or plain_condition or "Not available",
                    disabled=True,
                )


        submitted = st.button(
            "Save collector record",
            type="primary",
            width="stretch",
        )

        if not submitted:
            return

        payload = {
            "manual_media_type":
                save_choice(
                    manual_media_type,
                    media_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_media_type")
                    ),
                ),
            "manual_catalog_number":
                save_text(
                    manual_catalog_number,
                    catalog_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_catalog_number")
                    ),
                ),
            "manual_region":
                save_choice(
                    manual_region,
                    region_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_region")
                    ),
                ),
            "manual_disc_count":
                save_count(
                    manual_disc_count,
                    disc_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_disc_count")
                    ),
                ),
            "manual_pressing_type":
                save_choice(
                    manual_pressing_type,
                    pressing_type_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_pressing_type")
                    ),
                ),
            "manual_pressing_group":
                save_text(
                    manual_pressing_group,
                    pressing_group_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_pressing_group")
                    ),
                ),
            "manual_sale_type":
                save_choice(
                    manual_sale_type,
                    sale_automatic,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_sale_type")
                    ),
                ),
            "in_collection":
                bool(in_collection),
            "purchase_date":
                (
                    purchase_date
                    if in_collection
                    else None
                ),
            "purchase_price":
                (
                    Decimal(
                        str(purchase_price)
                    )
                    if in_collection
                    else None
                ),
            "purchase_currency":
                (
                    purchase_currency
                    if in_collection
                    else None
                ),
            "manual_bulk_lot": (
                True
                if lot_mode
                else False
                if is_lot
                else (
                    None
                    if is_missing(collector_value(selected, "manual_bulk_lot"))
                    else as_boolean(collector_value(selected, "manual_bulk_lot"))
                )
            ),
            "manual_obi":
                save_flag(
                    obi_value_for_region(
                        tri_state_value(manual_obi),
                        clean_text(manual_region)
                        if clean_text(manual_region) not in {"", "Automatic / unset"}
                        else clean_text(region_automatic),
                    ),
                    selected.get("effective_obi"),
                    manual_already=not is_missing(
                        collector_value(selected, "manual_obi")
                    ),
                ),
            "manual_insert_present":
                save_flag(
                    (
                        True
                        if manual_insert in {"Yes", "Insert only", "Pin-up is the insert"}
                        else False
                        if manual_insert in {"No", "Factory no insert"}
                        else tri_state_value(manual_insert)
                    ),
                    selected.get("effective_insert_present"),
                    manual_already=not is_missing(
                        collector_value(selected, "manual_insert_present")
                    ),
                ),
            "manual_poster_present":
                save_flag(
                    (
                        False
                        if manual_insert in {"Pin-up is the insert", "Insert only"}
                        else True
                        if manual_poster == "Pin-up is the poster"
                        else tri_state_value(manual_poster)
                    ),
                    selected.get("effective_poster_present"),
                    manual_already=not is_missing(
                        collector_value(selected, "manual_poster_present")
                    ),
                ),
            "manual_rental":
                save_flag(
                    tri_state_value(manual_rental),
                    selected.get("effective_rental"),
                    manual_already=not is_missing(
                        collector_value(selected, "manual_rental")
                    ),
                ),
            "manual_sticker":
                (
                    True
                    if tri_state_value(manual_rental) is True
                    else False
                    if tri_state_value(manual_rental) is False
                    else save_flag(
                        tri_state_value(manual_sticker),
                        selected.get("effective_sticker"),
                        manual_already=not is_missing(
                            collector_value(selected, "manual_sticker")
                        ),
                    )
                ),
            "manual_sealed":
                save_flag(
                    tri_state_value(manual_sealed),
                    selected.get("effective_sealed"),
                    manual_already=not is_missing(
                        collector_value(selected, "manual_sealed")
                    ),
                ),
            "manual_condition_media":
                save_choice(
                    manual_condition_media,
                    clean_text(selected.get("effective_condition_media")) or None,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_condition_media")
                    ),
                ),
            "manual_condition_cover":
                save_choice(
                    manual_condition_cover,
                    clean_text(selected.get("effective_condition_cover")) or None,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_condition_cover")
                    ),
                ),
            "manual_importance_score":
                save_count(
                    manual_importance_score,
                    safe_int(selected.get("effective_importance_score")) or 0,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_importance_score")
                    ),
                ),
            "manual_verdict":
                save_choice(
                    manual_verdict,
                    clean_text(selected.get("effective_verdict")) or None,
                    manual_already=not is_missing(
                        collector_value(selected, "manual_verdict")
                    ),
                ),
            "manual_completeness_notes":
                nullable_text(
                    notes_with_insert_fact(
                        manual_completeness_notes,
                        {
                            "Pin-up is the insert": PINUP_INSERT_NOTE,
                            "Insert only": INSERT_ONLY_NOTE,
                            "Factory no insert": FACTORY_NO_INSERT_NOTE,
                        }.get(manual_insert),
                    )
                ),
            "manual_collector_notes":
                nullable_text(
                    manual_collector_notes
                ),
        }

        changed_rows = save_collector_record(
            str(account_context.account_id),
            str(account_context.user_id),
            marketplace,
            listing_id,
            payload,
        )

        if changed_rows != 1:
            st.error(
                "Changes were not saved."
            )
            return

        st.session_state[
            revision_key
        ] = revision + 1
        st.session_state.pop(f"_finish_condition:{identity}", None)

        set_notification(
            (
                "Collector record saved for "
                f"{marketplace} {listing_id}. "
                "The selected editor was refreshed."
            )
        )

        load_records.clear()
        st.rerun()

    _collector_editor_fragment()


def render_auction_history(history: pd.DataFrame) -> None:
    """List auctions that recorded 0 bids. They are not sales."""
    st.header("Auction history")
    st.caption(
        "An auction needs at least 1 bid to stay in Listings. "
        "This tab follows the same media chip, so 7\", LP, CD, and Everything "
        "each show their own 0-bid auctions. Cycles on a sale counts these offers."
    )
    if history is None or history.empty:
        st.info("No auctions with 0 bids in this view.")
        return

    chart = auction_outcome_chart(pd.DataFrame(), history)
    if not chart.empty:
        st.bar_chart(
            chart,
            x="Format",
            y=["0-bid auctions"],
            height=220,
        )

    opened = pd.to_datetime(
        history["opening_display"] if "opening_display" in history.columns else None,
        utc=True,
        errors="coerce",
    )
    display = pd.DataFrame(
        {
            "Marketplace": history.get(
                "source_display",
                history.get("marketplace", pd.Series("", index=history.index)),
            ),
            "Listing": history.get("listing_id", pd.Series("", index=history.index)),
            "Title": history.get("title", pd.Series("", index=history.index)),
            "Format": [
                format_chart_bucket(media, job_lot=bool(lot))
                for media, lot in zip(
                    history.get("media_display", pd.Series("", index=history.index)),
                    history["job_lot"].fillna(False)
                    if "job_lot" in history.columns
                    else pd.Series(False, index=history.index),
                    strict=True,
                )
            ],
            "Catalog": history.get(
                "catalog_display",
                pd.Series("", index=history.index),
            ),
            "Opened": opened.map(
                lambda value: "" if pd.isna(value) else value.strftime("%Y-%m-%d")
            ),
            "Bids": [
                0 if pd.isna(value) else int(value)
                for value in history.get(
                    "bid_count_display",
                    pd.Series(0, index=history.index),
                )
            ],
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=420,
    )


def render_pressing_groups(
    dataframe: pd.DataFrame,
    history: pd.DataFrame | None = None,
) -> None:
    """Aggregate listings with matching matrix identities."""
    groupable = dataframe[
        dataframe[
            "pressing_group_key"
        ].fillna("")
        != ""
    ].copy()

    if groupable.empty:
        st.info(
            "No normalized matrix or catalog identities are available."
        )
        return

    groups = (
        groupable.groupby(
            "pressing_group_key",
            dropna=False,
        )
        .agg(
            Matrix=(
                "pressing_token",
                "first",
            ),
            Artist=(
                "artist_display",
                lambda values: next(
                    (
                        value
                        for value in values
                        if value
                    ),
                    "",
                ),
            ),
            Media=(
                "media_display",
                lambda values: ", ".join(
                    sorted(
                        {
                            value
                            for value in values
                            if value
                        }
                    )
                ),
            ),
            Listings=(
                "listing_id",
                "count",
            ),
            Marketplaces=(
                "marketplace",
                lambda values: ", ".join(
                    sorted(
                        set(values)
                    )
                ),
            ),
            Sellers=(
                "seller",
                lambda values: len(
                    {
                        value
                        for value in values
                        if value
                    }
                ),
            ),
            Minimum_USD=(
                "total_usd",
                "min",
            ),
            Median_USD=(
                "total_usd",
                "median",
            ),
            Maximum_USD=(
                "total_usd",
                "max",
            ),
            In_collection=(
                "in_collection_display",
                "sum",
            ),
            Latest_sale=(
                "closing_display",
                "max",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "Listings",
                "Latest_sale",
            ],
            ascending=[
                False,
                False,
            ],
        )
    )
    if "copy_status" in groupable.columns:
        def _copy_count(values: Any, bucket: str) -> int:
            count = 0
            for value in values:
                text = clean_text(value)
                if bucket == "complete" and text == "Complete":
                    count += 1
                elif bucket == "missing" and text.startswith("Missing"):
                    count += 1
                elif (
                    bucket == "unstated"
                    and text != "Complete"
                    and not text.startswith("Missing")
                    and "not stated" in text.casefold()
                ):
                    count += 1
            return count

        counts = (
            groupable.groupby("pressing_group_key", dropna=False)["copy_status"]
            .agg(
                Complete=lambda values: _copy_count(values, "complete"),
                Missing=lambda values: _copy_count(values, "missing"),
                Not_stated=lambda values: _copy_count(values, "unstated"),
            )
            .reset_index()
        )
        groups = groups.merge(counts, on="pressing_group_key", how="left")
        groups = groups.rename(columns={"Not_stated": "Not stated"})

    groups["Minimum USD"] = groups[
        "Minimum_USD"
    ].map(format_usd)

    groups["Median USD"] = groups[
        "Median_USD"
    ].map(format_usd)

    groups["Maximum USD"] = groups[
        "Maximum_USD"
    ].map(format_usd)

    groups["Latest sale"] = groups[
        "Latest_sale"
    ].map(format_datetime)

    group_columns = [
        "Matrix",
        "Artist",
        "Media",
        "Listings",
    ]
    if "Complete" in groups.columns:
        group_columns.extend(["Complete", "Missing", "Not stated"])
    group_columns.extend(
        [
            "Marketplaces",
            "Sellers",
            "Minimum USD",
            "Median USD",
            "Maximum USD",
            "In_collection",
            "Latest sale",
        ]
    )
    st.dataframe(
        groups[group_columns],
        hide_index=True,
        width="stretch",
        height=470,
    )

    selector_labels = {
        (
            f"{row.Matrix or 'Unknown matrix'} · "
            f"{row.Artist or 'Unknown artist'} · "
            f"{row.Listings} listings"
        ):
            row.pressing_group_key
        for row in groups.itertuples()
    }

    selected_label = st.selectbox(
        "Choose a pressing group",
        tuple(
            selector_labels.keys()
        ),
    )

    selected_key = selector_labels[
        selected_label
    ]

    selected_rows = groupable[
        groupable[
            "pressing_group_key"
        ]
        == selected_key
    ].copy()

    metric_columns = st.columns(5)

    metric_columns[0].metric(
        "Listings",
        len(selected_rows),
    )

    metric_columns[1].metric(
        "Sellers",
        selected_rows[
            "seller"
        ]
        .replace("", pd.NA)
        .nunique(),
    )

    metric_columns[2].metric(
        "Minimum USD",
        format_usd(
            selected_rows[
                "total_usd"
            ].min()
        ),
    )

    metric_columns[3].metric(
        "Median USD",
        format_usd(
            selected_rows[
                "total_usd"
            ].median()
        ),
    )

    metric_columns[4].metric(
        "Maximum USD",
        format_usd(
            selected_rows[
                "total_usd"
            ].max()
        ),
    )

    trend = selected_rows[
        [
            "closing_display",
            "total_usd",
        ]
    ].dropna()

    if len(trend) >= 2:
        trend = (
            trend.sort_values(
                "closing_display"
            )
            .set_index(
                "closing_display"
            )
        )

        st.line_chart(
            trend,
            y="total_usd",
            x_label="Closing date",
            y_label="Total price USD",
        )

    if history is not None and not history.empty and "pressing_group_key" in history.columns:
        unsold = history.loc[
            history["pressing_group_key"].fillna("").eq(selected_key)
        ]
        if not unsold.empty:
            st.caption(
                f"{format_count(len(unsold))} auctions with 0 bids for this pressing "
                "are on the History tab. Cycles on the sale counts those offers."
            )

    render_listing_table(
        selected_rows,
        key=(
            "pressing-group:"
            + selected_key
        ),
    )


def coverage_count(
    dataframe: pd.DataFrame,
    column_name: str,
) -> int:
    """Count populated values in a prepared column."""
    if column_name not in dataframe.columns:
        return 0

    series = dataframe[
        column_name
    ]

    if pd.api.types.is_datetime64_any_dtype(
        series
    ):
        return int(
            series.notna().sum()
        )

    return int(
        series.replace(
            "",
            pd.NA,
        ).notna().sum()
    )


def _coalesce_duplicate_named_column(
    dataframe: pd.DataFrame,
    column_name: str,
) -> pd.Series:
    """Return one Series even when a column label is duplicated."""
    selected = dataframe.loc[:, column_name]

    if isinstance(selected, pd.DataFrame):
        return (
            selected
            .bfill(axis=1)
            .iloc[:, 0]
        )

    return selected


def render_update_status(
    dataframe: pd.DataFrame,
) -> None:
    """Render database coverage and recent-review status."""
    coverage_rows = []

    for marketplace, group in dataframe.groupby(
        "marketplace"
    ):
        coverage_rows.append(
            {
                "marketplace":
                    marketplace,
                "rows":
                    len(group),
                "opening dates":
                    coverage_count(
                        group,
                        "opening_display",
                    ),
                "closing dates":
                    coverage_count(
                        group,
                        "closing_display",
                    ),
                "starting bids":
                    coverage_count(
                        group,
                        "starting_local",
                    ),
                "hammer prices":
                    coverage_count(
                        group,
                        "hammer_local",
                    ),
                "totals with tax":
                    coverage_count(
                        group,
                        "total_local",
                    ),
                "USD totals":
                    coverage_count(
                        group,
                        "total_usd",
                    ),
                "matrix/catalog":
                    coverage_count(
                        group,
                        "catalog_display",
                    ),
                "pressing groups":
                    group[
                        "pressing_group_key"
                    ]
                    .replace(
                        "",
                        pd.NA,
                    )
                    .nunique(),
                "in collection":
                    int(
                        group[
                            "in_collection_display"
                        ].sum()
                    ),
            }
        )

    st.subheader(
        "Available data"
    )

    st.dataframe(
        pd.DataFrame(
            coverage_rows
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader(
        "Listing details"
    )

    detail_status = (
        dataframe.assign(
            detail_status=(
                dataframe[
                    "detail_status_display"
                ]
                .replace(
                    "",
                    "not available",
                )
            )
        )
        .groupby(
            [
                "marketplace",
                "detail_status",
            ]
        )
        .size()
        .rename(
            "rows"
        )
        .reset_index()
    )

    st.dataframe(
        detail_status,
        hide_index=True,
        width="stretch",
    )

    updated_column = next(
        (
            candidate
            for candidate in (
                "collector_updated_at",
                "collector_updated_at",
                "updated_at",
            )
            if candidate in dataframe.columns
        ),
        None,
    )

    if updated_column:
        recent = dataframe.copy()

        recent[
            "_updated_sort"
        ] = pd.to_datetime(
            _coalesce_duplicate_named_column(recent, updated_column),
            errors="coerce",
            utc=True,
        )

        recent = (
            recent.dropna(
                subset=[
                    "_updated_sort"
                ]
            )
            .sort_values(
                "_updated_sort",
                ascending=False,
            )
            .head(25)
        )

        if not recent.empty:
            st.subheader(
                "Recently updated listings"
            )

            recent_display = pd.DataFrame(
                {
                    "Updated":
                        recent[
                            "_updated_sort"
                        ].map(
                            format_datetime
                        ),
                    "Marketplace":
                        recent[
                            "marketplace"
                        ],
                    "Listing ID":
                        recent[
                            "listing_id"
                        ],
                    "Title":
                        recent[
                            "title"
                        ],
                    "Matrix":
                        recent[
                            "pressing_token"
                        ],
                    "Verdict":
                        recent[
                            "verdict_display"
                        ],
                    "In collection":
                        recent[
                            "in_collection_display"
                        ].map(
                            {
                                True: "Yes",
                                False: "No",
                            }
                        ),
                }
            )

            st.dataframe(
                recent_display,
                hide_index=True,
                width="stretch",
            )


render_pending_notification()

st.title(
    "🔎 Review marketplace sales"
)

st.caption(
    "Search marketplace sales, refine pressing details, track collection status, and compare equivalent pressings."
)

render_media_group_pills()

st.session_state[
    LIVE_REVIEW_RENDERED_AT_KEY
] = time.monotonic()

rerun_review_while_refresh_active(
    str(
        ACCOUNT_CONTEXT.account_id
    )
)

try:
    records = load_records(str(ACCOUNT_CONTEXT.account_id))
    records = integrate_recent_activity(records)
    records = place_review_media(records)
    records = apply_local_identity(records)
except Exception as error:
    st.error(
        f"Could not load marketplace listings: {error}"
    )
    st.stop()

filtered_records, page_size_text, queue_records, history_records = (
    apply_filters(
        records
    )
)
records = sales_without_no_bid_auctions(records)

page_size = int(
    page_size_text
)

st.session_state[
    "_page_size"
] = page_size

render_listing_jump(
    filtered_records,
    page_size,
    open_records=records,
)

page_count = max(
    1,
    (
        len(filtered_records)
        + page_size
        - 1
    )
    // page_size,
)

page_number = int(
    st.session_state.get(
        "_listing_page",
        1,
    )
)

page_number = max(
    1,
    min(
        page_number,
        page_count,
    ),
)

st.session_state[
    "_listing_page"
] = page_number

render_dataset_overview(
    records,
    filtered_records,
    media_group=st.session_state.get(
        FILTER_WIDGET_KEYS["media_group"],
        MEDIA_GROUP_ALL_MUSIC,
    )
    or MEDIA_GROUP_ALL_MUSIC,
    queue=queue_records,
    history=history_records,
)

render_metrics(
    filtered_records,
    page_number,
    page_count,
    parked_lots=int(
        records["job_lot"].fillna(False).astype(bool).sum()
    )
    if "job_lot" in records.columns
    else 0,
    queue=queue_records,
)

def render_recent_updates(dataframe: pd.DataFrame) -> None:
    """Rows whose seller report, identity, or collector record changed this week."""
    st.header("Recent updates")
    st.caption(
        "Seller reports, identity matches, and saved collector records from the last 7 days. "
        "Select a row, then open Listings to grade that copy."
    )
    if (
        dataframe is None
        or dataframe.empty
        or "recent_change_at" not in dataframe.columns
    ):
        st.info("Nothing in this view changed in the last 7 days.")
        return
    stamps = pd.to_datetime(
        dataframe["recent_change_at"],
        utc=True,
        errors="coerce",
    )
    recent = dataframe.loc[stamps.notna()].copy()
    if recent.empty:
        st.info("Nothing in this view changed in the last 7 days.")
        return
    recent["_recent_at"] = pd.to_datetime(
        recent["recent_change_at"],
        utc=True,
        errors="coerce",
    )
    recent = recent.sort_values("_recent_at", ascending=False)
    now = pd.Timestamp.now(tz="America/New_York")
    local = recent["_recent_at"].dt.tz_convert("America/New_York")
    today_count = int((local.dt.date == now.date()).sum())
    st.caption(f"{today_count} today. {len(recent)} in the last 7 days.")
    render_listing_table(
        recent.drop(columns=["_recent_at"]),
        key="recent-updates",
        show_changed=True,
    )


tabs = st.tabs(
    (
        "Listings",
        "Recent",
        "History",
        "Pressing groups",
        "Data status",
        "Insights",
    )
)

with tabs[0]:
    st.header(
        "Search results"
    )

    if filtered_records.empty:
        selected_queue = st.session_state.get(
            FILTER_WIDGET_KEYS["identity"],
            IDENTITY_QUEUE_ALL,
        ) or IDENTITY_QUEUE_ALL
        if selected_queue != IDENTITY_QUEUE_ALL:
            st.warning(
                f"No listings in the {selected_queue} pile for this view."
            )
        else:
            st.warning(
                "No listings match the current filters."
            )
    else:
        render_export_toolbar(
            filtered_records,
            records,
        )

        start_index = (
            page_number - 1
        ) * page_size

        end_index = (
            start_index
            + page_size
        )

        page_rows = (
            filtered_records.iloc[
                start_index:end_index
            ]
            .copy()
            .reset_index(
                drop=True
            )
        )

        filter_revision = int(
            st.session_state.get(
                "_filter_revision",
                0,
            )
        )

        row_signature = int(
            pd.util.hash_pandas_object(
                page_rows[
                    [
                        "marketplace",
                        "listing_id",
                    ]
                ],
                index=False,
            ).sum()
        )

        table_selection_revision = int(
            st.session_state.get(
                TABLE_SELECTION_REVISION_KEY,
                0,
            )
        )

        render_pagination(
            page_number,
            page_count,
            key_prefix=(
                "collector_pagination:"
                f"{filter_revision}"
            ),
        )

        render_listing_table(
            page_rows,
            key=(
                "listings:"
                f"{filter_revision}:"
                f"{table_selection_revision}:"
                f"{page_number}:"
                f"{row_signature}"
            ),
        )

        render_listing_editor(
            records,
            ACCOUNT_CONTEXT,
        )

with tabs[1]:
    render_recent_updates(filtered_records)

with tabs[2]:
    render_auction_history(history_records)

with tabs[3]:
    st.header(
        "Equivalent pressing comparison"
    )

    st.caption(
        "Listings are grouped using pressing-group details, catalog/matrix number, artist, and media type."
    )

    render_pressing_groups(
        filtered_records,
        history_records,
    )

with tabs[4]:
    st.header(
        "Data status"
    )

    render_update_status(
        records
    )


# collector-analytics-editor:start
with tabs[5]:
    st.header(
        "Collection insights"
    )

    st.caption(
        "Assign exact pressings, record expected and observed components, normalize condition, note bidder-data limitations, and review collection insights."
    )

    if ACCOUNT_CONTEXT.is_system_admin:
        render_collector_analytics_editor(
            get_engine(),
            records,
            st.session_state.get(
                SELECTED_LISTING_KEY
            ),
        )
    else:
        st.info(
            "Collection analytics editing is temporarily restricted "
            "to system administrators until its Phase D account-owned "
            "write path is migrated."
        )
# collector-analytics-editor:end
