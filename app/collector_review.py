"""Interactive review UI for Auction ETL collector records."""

from __future__ import annotations

import math
import os
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://"
    "auction:auction@localhost:5444/auction_warehouse"
)
PAGE_SIZE_OPTIONS = (50, 100, 250)
TRI_STATE_OPTIONS = (
    "Automatic / unset",
    "Yes",
    "No",
)
PRESSING_TYPES = (
    "Automatic / unset",
    "STANDARD",
    "FIRST_PRESSING",
    "PROMO_SAMPLE",
    "REISSUE",
)
AUCTION_FORMATS = (
    "Automatic / derived",
    "AUCTION",
    "AUCTION_WITH_BUYOUT",
    "FIXED_PRICE",
    "BEST_OFFER",
    "UNKNOWN",
)
MEDIA_TYPES = (
    "Automatic / unset",
    "LP",
    "EP_7_INCH",
    "12_INCH_SINGLE",
    "CD",
    "CD_BOX_SET",
    "CASSETTE",
    "DVD",
    "VHS",
    "OTHER",
)
REGIONS = (
    "Automatic / unset",
    "Japan",
    "Hong Kong",
    "Taiwan",
    "Singapore",
    "Malaysia",
    "China",
    "Korea",
    "United States",
    "Europe",
    "Other",
)
VERDICTS = (
    "Automatic / unset",
    "PASS",
    "WATCH",
    "REFERENCE_ONLY",
    "REJECT",
)
CONDITIONS = (
    "Automatic / unset",
    "M",
    "NM",
    "EX",
    "VG+",
    "VG",
    "G+",
    "G",
    "P",
    "UNKNOWN",
)


def normalize_database_url(database_url: str) -> str:
    """Return a Psycopg 3 SQLAlchemy URL."""
    cleaned = database_url.strip()

    if cleaned.startswith("postgresql+psycopg://"):
        return cleaned

    if cleaned.startswith("postgresql://"):
        return cleaned.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    raise ValueError(
        "DATABASE_URL must use PostgreSQL."
    )


@st.cache_resource
def get_engine() -> Engine:
    """Create the shared SQLAlchemy engine."""
    return create_engine(
        normalize_database_url(
            os.getenv(
                "DATABASE_URL",
                DEFAULT_DATABASE_URL,
            )
        ),
        pool_pre_ping=True,
    )


def read_dataframe(
    sql: str,
    parameters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Read one query into a dataframe."""
    with get_engine().connect() as connection:
        return pd.read_sql_query(
            text(sql),
            connection,
            params=parameters or {},
        )


def execute_statement(
    sql: str,
    parameters: dict[str, Any],
) -> None:
    """Execute one transactional statement."""
    with get_engine().begin() as connection:
        connection.execute(
            text(sql),
            parameters,
        )


def optional_text(value: Any) -> str | None:
    """Normalize an optional text input."""
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def optional_choice(
    value: str,
    automatic_label: str,
) -> str | None:
    """Convert an automatic choice to NULL."""
    if value == automatic_label:
        return None

    return value


def tri_state_to_value(value: str) -> bool | None:
    """Convert a tri-state label to a database value."""
    if value == "Yes":
        return True

    if value == "No":
        return False

    return None


def tri_state_index(value: Any) -> int:
    """Return the selectbox index for a nullable boolean."""
    if value is True:
        return 1

    if value is False:
        return 2

    return 0


def choice_index(
    choices: tuple[str, ...],
    value: Any,
) -> int:
    """Return a safe selectbox index."""
    if value is None:
        return 0

    normalized = str(value)

    try:
        return choices.index(normalized)
    except ValueError:
        return 0


def money_display(
    local_value: Any,
    usd_value: Any,
    currency: Any,
) -> str:
    """Format local and converted USD values together."""
    if pd.isna(local_value):
        return "—"

    local = Decimal(str(local_value))
    currency_code = str(
        currency or ""
    ).upper()

    if currency_code == "JPY":
        local_text = f"¥{local:,.0f}"
    elif currency_code == "USD":
        local_text = f"${local:,.2f}"
    else:
        local_text = (
            f"{local:,.2f} {currency_code}".strip()
        )

    if (
        currency_code != "USD"
        and not pd.isna(usd_value)
    ):
        usd = Decimal(str(usd_value))
        return (
            f"{local_text} / ${usd:,.2f}"
        )

    return local_text


def date_display(value: Any) -> str:
    """Format one date or timestamp."""
    if value is None or pd.isna(value):
        return "—"

    parsed = pd.Timestamp(value)

    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC")

    return parsed.strftime(
        "%Y-%m-%d %H:%M"
    )


def bool_display(value: Any) -> str:
    """Return a human-readable boolean."""
    return "Yes" if bool(value) else "No"


def derive_filter_sql() -> tuple[str, dict[str, Any]]:
    """Build the current sidebar filtering expression."""
    clauses: list[str] = []
    parameters: dict[str, Any] = {}

    marketplace = st.session_state.marketplace_filter

    if marketplace != "all":
        clauses.append(
            "a.marketplace = :marketplace"
        )
        parameters["marketplace"] = marketplace

    search_text = (
        st.session_state.search_filter.strip()
    )

    if search_text:
        clauses.append(
            """
            (
                a.title ILIKE :search_text
                OR a.listing_id ILIKE :search_text
                OR COALESCE(a.catalog_number, '')
                    ILIKE :search_text
                OR COALESCE(a.seller, '')
                    ILIKE :search_text
                OR COALESCE(a.artist, '')
                    ILIKE :search_text
            )
            """
        )
        parameters["search_text"] = (
            f"%{search_text}%"
        )

    seller_contains = (
        st.session_state.seller_filter.strip()
    )

    if seller_contains:
        clauses.append(
            "COALESCE(a.seller, '') "
            "ILIKE :seller_contains"
        )
        parameters["seller_contains"] = (
            f"%{seller_contains}%"
        )

    if st.session_state.enable_date_filter:
        date_clause = (
            "COALESCE(a.closing_at, a.ended_at)"
        )

        if st.session_state.include_unknown_dates:
            clauses.append(
                f"""
                (
                    {date_clause} IS NULL
                    OR {date_clause}::date
                        BETWEEN :ended_from
                            AND :ended_through
                )
                """
            )
        else:
            clauses.append(
                f"""
                {date_clause}::date
                    BETWEEN :ended_from
                        AND :ended_through
                """
            )

        parameters["ended_from"] = (
            st.session_state.ended_from_filter
        )
        parameters["ended_through"] = (
            st.session_state.ended_through_filter
        )

    verdict = st.session_state.verdict_filter

    if verdict != "all":
        clauses.append(
            """
            COALESCE(
                c.manual_verdict,
                c.auto_verdict
            ) = :verdict
            """
        )
        parameters["verdict"] = verdict

    media_type = (
        st.session_state.media_filter
    )

    if media_type != "all":
        clauses.append(
            """
            COALESCE(
                c.manual_media_type,
                c.auto_media_type,
                a.media_type
            ) = :media_type
            """
        )
        parameters["media_type"] = media_type

    purchase = (
        st.session_state.purchase_filter
    )

    if purchase == "Purchased":
        clauses.append(
            "COALESCE(c.manual_purchased, false)"
        )
    elif purchase == "Not purchased":
        clauses.append(
            "NOT COALESCE("
            "c.manual_purchased, false)"
        )

    auction_format = (
        st.session_state.auction_format_filter
    )

    if auction_format != "all":
        clauses.append(
            """
            COALESCE(
                c.manual_auction_format,
                a.auction_format,
                CASE
                    WHEN a.buyout_price_gross
                            IS NOT NULL
                     AND COALESCE(
                            a.bid_count,
                            0
                         ) > 0
                        THEN 'AUCTION_WITH_BUYOUT'

                    WHEN a.buyout_price_gross
                            IS NOT NULL
                        THEN 'FIXED_PRICE'

                    WHEN COALESCE(
                            a.bid_count,
                            0
                         ) > 0
                      OR a.start_price IS NOT NULL
                        THEN 'AUCTION'

                    ELSE 'UNKNOWN'
                END
            ) = :auction_format
            """
        )
        parameters[
            "auction_format"
        ] = auction_format

    if not clauses:
        return "TRUE", parameters

    return (
        "\nAND ".join(clauses),
        parameters,
    )


FROM_SQL = """
FROM warehouse.auction AS a

LEFT JOIN warehouse.auction_collector AS c
  ON c.marketplace = a.marketplace
 AND c.listing_id = a.listing_id

LEFT JOIN warehouse.auction_detail AS d
  ON d.marketplace = a.marketplace
 AND d.listing_id = a.listing_id
"""


SELECT_SQL = """
SELECT
    a.id,
    a.marketplace,
    a.listing_id,
    a.auction_url,
    a.seller,
    a.artist,
    a.title,
    a.currency,

    a.opening_at,
    COALESCE(
        a.closing_at,
        a.ended_at
    ) AS closing_at,

    a.start_price,
    a.start_price_usd,

    a.final_price,
    a.final_price_usd,

    a.tax_amount,
    a.tax_usd,

    a.gross_price,
    a.gross_price_usd,

    a.shipping_price,
    a.shipping_price_usd,

    a.current_price_gross,
    a.current_price_usd,

    a.buyout_price_gross,
    a.buyout_price_usd,

    a.bid_count,
    a.fx_rate_to_usd,
    a.fx_rate_date,

    COALESCE(
        c.manual_media_type,
        c.auto_media_type,
        a.media_type
    ) AS effective_media_type,

    COALESCE(
        c.manual_catalog_number,
        c.auto_catalog_number,
        a.catalog_number
    ) AS effective_catalog_number,

    COALESCE(
        c.manual_region,
        c.auto_region
    ) AS effective_region,

    COALESCE(
        c.manual_disc_count,
        c.auto_disc_count,
        a.disc_count
    ) AS effective_disc_count,

    COALESCE(
        c.manual_bulk_lot,
        c.auto_bulk_lot,
        a.bulk_lot,
        false
    ) AS effective_bulk_lot,

    COALESCE(
        c.manual_verdict,
        c.auto_verdict
    ) AS effective_verdict,

    COALESCE(
        c.manual_pressing_type,
        c.auto_pressing_type,
        CASE
            WHEN COALESCE(
                c.manual_promo,
                c.auto_promo,
                false
            )
                THEN 'PROMO_SAMPLE'

            WHEN COALESCE(
                c.manual_first_press,
                c.auto_first_press,
                false
            )
                THEN 'FIRST_PRESSING'

            WHEN COALESCE(
                c.manual_reissue,
                c.auto_reissue,
                false
            )
                THEN 'REISSUE'

            ELSE 'STANDARD'
        END
    ) AS effective_pressing_type,

    COALESCE(
        c.manual_auction_format,
        a.auction_format,
        CASE
            WHEN a.buyout_price_gross IS NOT NULL
             AND COALESCE(a.bid_count, 0) > 0
                THEN 'AUCTION_WITH_BUYOUT'

            WHEN a.buyout_price_gross IS NOT NULL
                THEN 'FIXED_PRICE'

            WHEN COALESCE(a.bid_count, 0) > 0
              OR a.start_price IS NOT NULL
                THEN 'AUCTION'

            ELSE 'UNKNOWN'
        END
    ) AS effective_auction_format,

    COALESCE(
        c.manual_purchased,
        false
    ) AS purchased,

    c.manual_purchase_date,
    c.manual_purchase_price,
    c.manual_purchase_currency,
    c.manual_purchase_notes,

    c.manual_catalog_number,
    c.manual_region,
    c.manual_media_type,
    c.manual_disc_count,
    c.manual_bulk_lot,
    c.manual_obi,
    c.manual_insert_present,
    c.manual_poster_present,
    c.manual_rental,
    c.manual_sticker,
    c.manual_sealed,
    c.manual_pressing_type,
    c.manual_auction_format,
    c.manual_importance_score,
    c.manual_verdict,
    c.manual_condition_media,
    c.manual_condition_cover,
    c.manual_completeness_notes,
    c.manual_collector_notes,

    d.auction_status,
    d.condition_text,
    d.detail_status,
    d.fetched_at AS detail_fetched_at
"""


def render_navigation(
    page: int,
    page_count: int,
    prefix: str,
) -> None:
    """Render previous and next controls."""
    previous_column, page_column, next_column = (
        st.columns(
            [3, 1.5, 3]
        )
    )

    with previous_column:
        if st.button(
            "← Previous",
            disabled=page <= 1,
            use_container_width=True,
            key=f"{prefix}_previous",
        ):
            st.session_state.page_number = (
                max(1, page - 1)
            )
            st.rerun()

    with page_column:
        st.button(
            f"• {page} / {page_count} •",
            disabled=True,
            use_container_width=True,
            key=f"{prefix}_page",
        )

    with next_column:
        if st.button(
            "Next →",
            disabled=page >= page_count,
            use_container_width=True,
            key=f"{prefix}_next",
        ):
            st.session_state.page_number = (
                min(page_count, page + 1)
            )
            st.rerun()


def initialize_state() -> None:
    """Initialize stable widget and pagination state."""
    defaults = {
        "marketplace_filter": "all",
        "search_filter": "",
        "seller_filter": "",
        "enable_date_filter": False,
        "include_unknown_dates": True,
        "ended_from_filter": date(2025, 1, 1),
        "ended_through_filter": date.today(),
        "verdict_filter": "all",
        "media_filter": "all",
        "purchase_filter": "all",
        "auction_format_filter": "all",
        "page_size": 250,
        "page_number": 1,
        "filter_signature": None,
    }

    for key, value in defaults.items():
        st.session_state.setdefault(
            key,
            value,
        )


st.set_page_config(
    page_title="Auction Collector Review",
    page_icon="💿",
    layout="wide",
)

initialize_state()

st.title("💿 Auction Collector Review")
st.caption(
    "Search, compare local and USD prices, review live auction "
    "facts, and track collection purchases. Blank manual fields "
    "preserve automatic classifications."
)

marketplaces = read_dataframe(
    """
    SELECT DISTINCT marketplace
    FROM warehouse.auction
    ORDER BY marketplace
    """
)["marketplace"].dropna().astype(str).tolist()

verdicts = read_dataframe(
    """
    SELECT DISTINCT
        COALESCE(
            manual_verdict,
            auto_verdict
        ) AS verdict
    FROM warehouse.auction_collector
    WHERE COALESCE(
        manual_verdict,
        auto_verdict
    ) IS NOT NULL
    ORDER BY verdict
    """
)["verdict"].dropna().astype(str).tolist()

media_types = read_dataframe(
    """
    SELECT DISTINCT
        COALESCE(
            c.manual_media_type,
            c.auto_media_type,
            a.media_type
        ) AS media_type
    FROM warehouse.auction AS a
    LEFT JOIN warehouse.auction_collector AS c
      ON c.marketplace = a.marketplace
     AND c.listing_id = a.listing_id
    WHERE COALESCE(
        c.manual_media_type,
        c.auto_media_type,
        a.media_type
    ) IS NOT NULL
    ORDER BY media_type
    """
)["media_type"].dropna().astype(str).tolist()

with st.sidebar:
    st.header("Search and filters")

    st.selectbox(
        "Marketplace",
        ["all", *marketplaces],
        key="marketplace_filter",
    )

    st.text_input(
        "Search",
        placeholder=(
            "Title, listing ID, catalog number, seller"
        ),
        key="search_filter",
    )

    st.text_input(
        "Seller contains",
        key="seller_filter",
    )

    st.checkbox(
        "Filter by closing date",
        key="enable_date_filter",
    )

    if st.session_state.enable_date_filter:
        date_left, date_right = st.columns(2)

        with date_left:
            st.date_input(
                "Closed from",
                key="ended_from_filter",
            )

        with date_right:
            st.date_input(
                "Closed through",
                key="ended_through_filter",
            )

        st.checkbox(
            "Include unknown closing dates",
            key="include_unknown_dates",
        )

    st.selectbox(
        "Verdict",
        ["all", *verdicts],
        key="verdict_filter",
    )

    st.selectbox(
        "Media type",
        ["all", *media_types],
        key="media_filter",
    )

    st.selectbox(
        "Purchase",
        [
            "all",
            "Purchased",
            "Not purchased",
        ],
        key="purchase_filter",
    )

    st.selectbox(
        "Auction type",
        [
            "all",
            "AUCTION",
            "AUCTION_WITH_BUYOUT",
            "FIXED_PRICE",
            "BEST_OFFER",
            "UNKNOWN",
        ],
        key="auction_format_filter",
    )

    st.selectbox(
        "Rows per page",
        PAGE_SIZE_OPTIONS,
        key="page_size",
    )

filter_signature = (
    st.session_state.marketplace_filter,
    st.session_state.search_filter,
    st.session_state.seller_filter,
    st.session_state.enable_date_filter,
    st.session_state.include_unknown_dates,
    st.session_state.ended_from_filter,
    st.session_state.ended_through_filter,
    st.session_state.verdict_filter,
    st.session_state.media_filter,
    st.session_state.purchase_filter,
    st.session_state.auction_format_filter,
    st.session_state.page_size,
)

if (
    st.session_state.filter_signature
    != filter_signature
):
    st.session_state.filter_signature = (
        filter_signature
    )
    st.session_state.page_number = 1

where_sql, query_parameters = (
    derive_filter_sql()
)

summary = read_dataframe(
    f"""
    SELECT
        COUNT(*) AS total_matches,
        COUNT(DISTINCT a.seller)
            AS visible_sellers,

        COUNT(*) FILTER (
            WHERE COALESCE(
                c.manual_bulk_lot,
                c.auto_bulk_lot,
                a.bulk_lot,
                false
            )
        ) AS bulk_lots,

        COUNT(*) FILTER (
            WHERE COALESCE(
                c.manual_media_type,
                c.auto_media_type,
                a.media_type
            ) IS NULL
        ) AS missing_media

    {FROM_SQL}
    WHERE {where_sql}
    """,
    query_parameters,
).iloc[0]

total_matches = int(
    summary["total_matches"]
)
page_size = int(
    st.session_state.page_size
)
page_count = max(
    1,
    math.ceil(
        total_matches / page_size
    ),
)
page_number = min(
    int(
        st.session_state.page_number
    ),
    page_count,
)
st.session_state.page_number = page_number

offset = (
    page_number - 1
) * page_size

page_parameters = dict(
    query_parameters
)
page_parameters.update(
    {
        "limit": page_size,
        "offset": offset,
    }
)

records = read_dataframe(
    f"""
    {SELECT_SQL}
    {FROM_SQL}
    WHERE {where_sql}
    ORDER BY
        COALESCE(
            a.closing_at,
            a.ended_at
        ) DESC NULLS LAST,
        a.id DESC
    LIMIT :limit
    OFFSET :offset
    """,
    page_parameters,
)

metrics = st.columns(6)

metrics[0].metric(
    "Total matches",
    total_matches,
)
metrics[1].metric(
    "Visible rows",
    len(records),
)
metrics[2].metric(
    "Page",
    f"{page_number} / {page_count}",
)
metrics[3].metric(
    "Visible sellers",
    int(summary["visible_sellers"]),
)
metrics[4].metric(
    "Visible bulk lots",
    int(summary["bulk_lots"]),
)
metrics[5].metric(
    "Visible missing media",
    int(summary["missing_media"]),
)

render_navigation(
    page_number,
    page_count,
    "top",
)

st.subheader("Search results")

if records.empty:
    st.warning(
        "No listings match the current filters."
    )
else:
    display = pd.DataFrame(
        {
            "Marketplace": records[
                "marketplace"
            ],
            "Listing ID": records[
                "listing_id"
            ],
            "Seller": records[
                "seller"
            ].fillna("—"),
            "Title": records[
                "title"
            ],
            "Media": records[
                "effective_media_type"
            ].fillna("—"),
            "Catalog": records[
                "effective_catalog_number"
            ].fillna("—"),
            "Region": records[
                "effective_region"
            ].fillna("—"),
            "Pressing": records[
                "effective_pressing_type"
            ].fillna("STANDARD"),
            "Auction type": records[
                "effective_auction_format"
            ].fillna("UNKNOWN"),
            "Opened": records[
                "opening_at"
            ].map(date_display),
            "Closed": records[
                "closing_at"
            ].map(date_display),
            "Starting bid": [
                money_display(
                    local_value,
                    usd_value,
                    currency,
                )
                for local_value, usd_value, currency
                in zip(
                    records["start_price"],
                    records["start_price_usd"],
                    records["currency"],
                    strict=False,
                )
            ],
            "Hammer before tax": [
                money_display(
                    local_value,
                    usd_value,
                    currency,
                )
                for local_value, usd_value, currency
                in zip(
                    records["final_price"],
                    records["final_price_usd"],
                    records["currency"],
                    strict=False,
                )
            ],
            "Tax": [
                money_display(
                    local_value,
                    usd_value,
                    currency,
                )
                for local_value, usd_value, currency
                in zip(
                    records["tax_amount"],
                    records["tax_usd"],
                    records["currency"],
                    strict=False,
                )
            ],
            "Total with tax": [
                money_display(
                    local_value,
                    usd_value,
                    currency,
                )
                for local_value, usd_value, currency
                in zip(
                    records["gross_price"],
                    records["gross_price_usd"],
                    records["currency"],
                    strict=False,
                )
            ],
            "Buyout": [
                money_display(
                    local_value,
                    usd_value,
                    currency,
                )
                for local_value, usd_value, currency
                in zip(
                    records[
                        "buyout_price_gross"
                    ],
                    records[
                        "buyout_price_usd"
                    ],
                    records["currency"],
                    strict=False,
                )
            ],
            "Bids": records[
                "bid_count"
            ].fillna(0).astype(int),
            "Purchased": records[
                "purchased"
            ].map(bool_display),
            "Verdict": records[
                "effective_verdict"
            ].fillna("—"),
            "Detail status": records[
                "detail_status"
            ].fillna("—"),
            "URL": records[
                "auction_url"
            ],
        }
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=540,
        column_config={
            "URL": st.column_config.LinkColumn(
                "Listing",
                display_text="Open ↗",
            ),
            "Purchased": st.column_config.TextColumn(
                "In collection",
            ),
        },
    )

render_navigation(
    page_number,
    page_count,
    "bottom",
)

if not records.empty:
    option_rows = {
        (
            f"{row.marketplace} · "
            f"{row.listing_id} · "
            f"{row.seller or 'unknown seller'} · "
            f"{row.title}"
        ): row
        for row in records.itertuples(
            index=False
        )
    }

    selected_label = st.selectbox(
        "Select a listing to edit",
        options=list(option_rows),
    )

    selected = option_rows[
        selected_label
    ]

    st.divider()

    header_left, header_right = st.columns(
        [5, 1]
    )

    with header_left:
        st.subheader(selected.title)
        st.caption(
            f"{selected.marketplace} · "
            f"{selected.listing_id} · "
            f"{selected.seller or 'unknown seller'}"
        )

    with header_right:
        st.link_button(
            "Open listing ↗",
            selected.auction_url,
            use_container_width=True,
        )

    price_columns = st.columns(5)

    price_columns[0].metric(
        "Starting bid",
        money_display(
            selected.start_price,
            selected.start_price_usd,
            selected.currency,
        ),
    )
    price_columns[1].metric(
        "Hammer before tax",
        money_display(
            selected.final_price,
            selected.final_price_usd,
            selected.currency,
        ),
    )
    price_columns[2].metric(
        "Tax",
        money_display(
            selected.tax_amount,
            selected.tax_usd,
            selected.currency,
        ),
    )
    price_columns[3].metric(
        "Total with tax",
        money_display(
            selected.gross_price,
            selected.gross_price_usd,
            selected.currency,
        ),
    )
    price_columns[4].metric(
        "Bids",
        int(selected.bid_count or 0),
    )

    st.caption(
        f"Opened: {date_display(selected.opening_at)} · "
        f"Closed: {date_display(selected.closing_at)} · "
        f"FX date: "
        f"{selected.fx_rate_date or 'not available'} · "
        f"Live detail: "
        f"{selected.detail_status or 'not available'}"
    )

    with st.form(
        "collector_editor",
        clear_on_submit=False,
    ):
        st.subheader("Core classification")

        core_columns = st.columns(5)

        with core_columns[0]:
            manual_media_type = st.selectbox(
                "Manual media type",
                MEDIA_TYPES,
                index=choice_index(
                    MEDIA_TYPES,
                    selected.manual_media_type,
                ),
            )

        with core_columns[1]:
            manual_catalog_number = st.text_input(
                "Manual catalog / pressing number",
                value=(
                    selected.manual_catalog_number
                    or ""
                ),
            )

        with core_columns[2]:
            manual_region = st.selectbox(
                "Manual region",
                REGIONS,
                index=choice_index(
                    REGIONS,
                    selected.manual_region,
                ),
            )

        with core_columns[3]:
            manual_disc_count = st.number_input(
                "Manual disc count",
                min_value=0,
                max_value=100,
                value=int(
                    selected.manual_disc_count
                    or 0
                ),
                step=1,
                help="Zero preserves the automatic value.",
            )

        with core_columns[4]:
            manual_pressing_type = st.selectbox(
                "Pressing type",
                PRESSING_TYPES,
                index=choice_index(
                    PRESSING_TYPES,
                    selected.manual_pressing_type,
                ),
                help=(
                    "One mutually exclusive choice: standard, "
                    "first pressing, promo/sample, or reissue."
                ),
            )

        st.subheader("Sale format and collection")

        sale_columns = st.columns(5)

        with sale_columns[0]:
            manual_auction_format = st.selectbox(
                "Sale type",
                AUCTION_FORMATS,
                index=choice_index(
                    AUCTION_FORMATS,
                    selected.manual_auction_format,
                ),
            )

        with sale_columns[1]:
            purchased = st.checkbox(
                "In collection / purchased",
                value=bool(
                    selected.purchased
                ),
            )

        purchase_date_value = (
            selected.manual_purchase_date
            if selected.manual_purchase_date
            else date.today()
        )

        with sale_columns[2]:
            purchase_date = st.date_input(
                "Purchase date",
                value=purchase_date_value,
                disabled=not purchased,
            )

        with sale_columns[3]:
            purchase_price = st.number_input(
                "Purchase price",
                min_value=0.0,
                value=float(
                    selected.manual_purchase_price
                    or 0
                ),
                step=1.0,
                disabled=not purchased,
            )

        with sale_columns[4]:
            purchase_currency = st.selectbox(
                "Purchase currency",
                (
                    "USD",
                    "JPY",
                    "HKD",
                    "TWD",
                    "Other",
                ),
                index=(
                    (
                        "USD",
                        "JPY",
                        "HKD",
                        "TWD",
                        "Other",
                    ).index(
                        selected.manual_purchase_currency
                    )
                    if selected.manual_purchase_currency
                    in (
                        "USD",
                        "JPY",
                        "HKD",
                        "TWD",
                        "Other",
                    )
                    else 0
                ),
                disabled=not purchased,
            )

        st.subheader("Completeness and edition")

        flag_columns_one = st.columns(5)

        with flag_columns_one[0]:
            manual_bulk_lot = st.selectbox(
                "Bulk lot",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_bulk_lot
                ),
            )

        with flag_columns_one[1]:
            manual_obi = st.selectbox(
                "Obi",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_obi
                ),
            )

        with flag_columns_one[2]:
            manual_insert_present = st.selectbox(
                "Insert",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_insert_present
                ),
            )

        with flag_columns_one[3]:
            manual_poster_present = st.selectbox(
                "Poster",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_poster_present
                ),
            )

        with flag_columns_one[4]:
            manual_rental = st.selectbox(
                "Rental",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_rental
                ),
            )

        flag_columns_two = st.columns(3)

        with flag_columns_two[0]:
            manual_sticker = st.selectbox(
                "Sticker",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_sticker
                ),
            )

        with flag_columns_two[1]:
            manual_sealed = st.selectbox(
                "Sealed",
                TRI_STATE_OPTIONS,
                index=tri_state_index(
                    selected.manual_sealed
                ),
            )

        with flag_columns_two[2]:
            st.text_input(
                "Live condition",
                value=(
                    selected.condition_text
                    or "Not available"
                ),
                disabled=True,
            )

        st.subheader(
            "Condition and collector verdict"
        )

        condition_columns = st.columns(4)

        with condition_columns[0]:
            manual_condition_media = st.selectbox(
                "Media condition",
                CONDITIONS,
                index=choice_index(
                    CONDITIONS,
                    selected.manual_condition_media,
                ),
            )

        with condition_columns[1]:
            manual_condition_cover = st.selectbox(
                "Cover condition",
                CONDITIONS,
                index=choice_index(
                    CONDITIONS,
                    selected.manual_condition_cover,
                ),
            )

        with condition_columns[2]:
            manual_importance_score = (
                st.number_input(
                    "Importance score",
                    min_value=0,
                    max_value=100,
                    value=int(
                        selected.manual_importance_score
                        or 0
                    ),
                    step=1,
                )
            )

        with condition_columns[3]:
            manual_verdict = st.selectbox(
                "Manual verdict",
                VERDICTS,
                index=choice_index(
                    VERDICTS,
                    selected.manual_verdict,
                ),
            )

        manual_completeness_notes = (
            st.text_area(
                "Completeness / pressing notes",
                value=(
                    selected.manual_completeness_notes
                    or ""
                ),
                placeholder=(
                    "Complete with obi, insert and poster; "
                    "rental sticker on rear sleeve..."
                ),
            )
        )

        manual_collector_notes = st.text_area(
            "Collector notes",
            value=(
                selected.manual_collector_notes
                or ""
            ),
            placeholder=(
                "Why this pressing matters, comparable sales, "
                "condition concerns, desired ceiling..."
            ),
        )

        purchase_notes = st.text_area(
            "Purchase notes",
            value=(
                selected.manual_purchase_notes
                or ""
            ),
            disabled=not purchased,
            placeholder=(
                "Source, shipping, fees, shelf location, "
                "or acquisition details..."
            ),
        )

        save_submitted = st.form_submit_button(
            "Save collector record",
            type="primary",
            use_container_width=True,
        )

    if save_submitted:
        pressing_type_value = optional_choice(
            manual_pressing_type,
            "Automatic / unset",
        )

        manual_promo = None
        manual_first_press = None
        manual_reissue = None

        if pressing_type_value == "STANDARD":
            manual_promo = False
            manual_first_press = False
            manual_reissue = False
        elif pressing_type_value == "PROMO_SAMPLE":
            manual_promo = True
            manual_first_press = False
            manual_reissue = False
        elif pressing_type_value == "FIRST_PRESSING":
            manual_promo = False
            manual_first_press = True
            manual_reissue = False
        elif pressing_type_value == "REISSUE":
            manual_promo = False
            manual_first_press = False
            manual_reissue = True

        save_parameters = {
            "marketplace": selected.marketplace,
            "listing_id": selected.listing_id,
            "manual_media_type": optional_choice(
                manual_media_type,
                "Automatic / unset",
            ),
            "manual_catalog_number": optional_text(
                manual_catalog_number
            ),
            "manual_region": optional_choice(
                manual_region,
                "Automatic / unset",
            ),
            "manual_disc_count": (
                int(manual_disc_count)
                if manual_disc_count > 0
                else None
            ),
            "manual_pressing_type": (
                pressing_type_value
            ),
            "manual_promo": manual_promo,
            "manual_first_press": (
                manual_first_press
            ),
            "manual_reissue": manual_reissue,
            "manual_auction_format": optional_choice(
                manual_auction_format,
                "Automatic / derived",
            ),
            "manual_bulk_lot": tri_state_to_value(
                manual_bulk_lot
            ),
            "manual_obi": tri_state_to_value(
                manual_obi
            ),
            "manual_insert_present": (
                tri_state_to_value(
                    manual_insert_present
                )
            ),
            "manual_poster_present": (
                tri_state_to_value(
                    manual_poster_present
                )
            ),
            "manual_rental": tri_state_to_value(
                manual_rental
            ),
            "manual_sticker": tri_state_to_value(
                manual_sticker
            ),
            "manual_sealed": tri_state_to_value(
                manual_sealed
            ),
            "manual_condition_media": optional_choice(
                manual_condition_media,
                "Automatic / unset",
            ),
            "manual_condition_cover": optional_choice(
                manual_condition_cover,
                "Automatic / unset",
            ),
            "manual_importance_score": (
                int(manual_importance_score)
                if manual_importance_score > 0
                else None
            ),
            "manual_verdict": optional_choice(
                manual_verdict,
                "Automatic / unset",
            ),
            "manual_completeness_notes": optional_text(
                manual_completeness_notes
            ),
            "manual_collector_notes": optional_text(
                manual_collector_notes
            ),
            "manual_purchased": purchased,
            "manual_purchase_date": (
                purchase_date
                if purchased
                else None
            ),
            "manual_purchase_price": (
                Decimal(str(purchase_price))
                if purchased
                and purchase_price > 0
                else None
            ),
            "manual_purchase_currency": (
                purchase_currency
                if purchased
                else None
            ),
            "manual_purchase_notes": (
                optional_text(purchase_notes)
                if purchased
                else None
            ),
        }

        execute_statement(
            """
            INSERT INTO warehouse.auction_collector (
                marketplace,
                listing_id,
                updated_at
            )
            VALUES (
                :marketplace,
                :listing_id,
                NOW()
            )
            ON CONFLICT (
                marketplace,
                listing_id
            )
            DO NOTHING
            """,
            save_parameters,
        )

        execute_statement(
            """
            UPDATE warehouse.auction_collector
            SET
                manual_media_type =
                    :manual_media_type,
                manual_catalog_number =
                    :manual_catalog_number,
                manual_region =
                    :manual_region,
                manual_disc_count =
                    :manual_disc_count,

                manual_pressing_type =
                    :manual_pressing_type,
                manual_promo =
                    :manual_promo,
                manual_first_press =
                    :manual_first_press,
                manual_reissue =
                    :manual_reissue,

                manual_auction_format =
                    :manual_auction_format,

                manual_bulk_lot =
                    :manual_bulk_lot,
                manual_obi =
                    :manual_obi,
                manual_insert_present =
                    :manual_insert_present,
                manual_poster_present =
                    :manual_poster_present,
                manual_rental =
                    :manual_rental,
                manual_sticker =
                    :manual_sticker,
                manual_sealed =
                    :manual_sealed,

                manual_condition_media =
                    :manual_condition_media,
                manual_condition_cover =
                    :manual_condition_cover,
                manual_importance_score =
                    :manual_importance_score,
                manual_verdict =
                    :manual_verdict,
                manual_completeness_notes =
                    :manual_completeness_notes,
                manual_collector_notes =
                    :manual_collector_notes,

                manual_purchased =
                    :manual_purchased,
                manual_purchase_date =
                    :manual_purchase_date,
                manual_purchase_price =
                    :manual_purchase_price,
                manual_purchase_currency =
                    :manual_purchase_currency,
                manual_purchase_notes =
                    :manual_purchase_notes,
                purchase_updated_at = NOW(),
                updated_at = NOW()

            WHERE marketplace = :marketplace
              AND listing_id = :listing_id
            """,
            save_parameters,
        )

        st.toast(
            "Collector record updated successfully.",
            icon="✅",
        )
        st.success(
            "Saved. Purchase status, classification, "
            "pressing type, and notes were updated."
        )
        st.cache_data.clear()
        st.rerun()

st.divider()

st.subheader("Data quality and update telemetry")

telemetry = read_dataframe(
    f"""
    SELECT
        COUNT(*) AS rows,

        COUNT(*) FILTER (
            WHERE a.opening_at IS NULL
        ) AS missing_opening,

        COUNT(*) FILTER (
            WHERE COALESCE(
                a.closing_at,
                a.ended_at
            ) IS NULL
        ) AS missing_closing,

        COUNT(*) FILTER (
            WHERE a.start_price IS NULL
        ) AS missing_starting_bid,

        COUNT(*) FILTER (
            WHERE a.final_price IS NULL
        ) AS missing_hammer,

        COUNT(*) FILTER (
            WHERE a.gross_price IS NULL
        ) AS missing_total,

        COUNT(*) FILTER (
            WHERE a.fx_rate_to_usd IS NULL
        ) AS missing_fx,

        COUNT(*) FILTER (
            WHERE COALESCE(
                c.manual_purchased,
                false
            )
        ) AS purchased_rows,

        MAX(d.fetched_at)
            AS latest_detail_fetch,

        MAX(c.updated_at)
            AS latest_collector_update

    {FROM_SQL}
    WHERE {where_sql}
    """,
    query_parameters,
).iloc[0]

telemetry_columns = st.columns(6)

telemetry_columns[0].metric(
    "Rows",
    int(telemetry["rows"]),
)
telemetry_columns[1].metric(
    "Missing opening date",
    int(telemetry["missing_opening"]),
)
telemetry_columns[2].metric(
    "Missing closing date",
    int(telemetry["missing_closing"]),
)
telemetry_columns[3].metric(
    "Missing starting bid",
    int(
        telemetry[
            "missing_starting_bid"
        ]
    ),
)
telemetry_columns[4].metric(
    "Missing hammer",
    int(telemetry["missing_hammer"]),
)
telemetry_columns[5].metric(
    "In collection",
    int(telemetry["purchased_rows"]),
)

st.caption(
    "Latest live-detail fetch: "
    f"{date_display(telemetry['latest_detail_fetch'])} · "
    "Latest collector update: "
    f"{date_display(telemetry['latest_collector_update'])} · "
    f"Missing totals: {int(telemetry['missing_total'])} · "
    f"Missing FX rates: {int(telemetry['missing_fx'])}"
)
