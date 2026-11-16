"""Completed-sale analytics for exact catalog and pressing numbers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

from auction_etl.database.session import engine
from auction_etl.services.discogs_identity import english_album_title
from auction_etl.services.tracked_listing_scope import (
    enabled_tracked_artist_names,
    listing_belongs_to_tracked_artists,
)
from app.navigation import render_navigation

from auction_etl.auth.streamlit_auth import (
    render_account_menu,
    require_authenticated_account,
    require_system_admin,
)


COMPLETED_SALE_PREDICATE = (
    "sale.gross_price IS NOT NULL",
    """NOT (
        COALESCE(sale.auction_format, '') IN (
            'AUCTION',
            'AUCTION_WITH_BUYOUT'
        )
        AND COALESCE(sale.bid_count, -1) = 0
    )""",
)

# Discogs files many 7-inch and cassette pressings as "Vinyl".
# The listing format is the one the sale was actually classified as.
ANALYTICS_MEDIA_SQL = """
CASE
    WHEN COALESCE(sale.effective_media_type, '') IN ('Vinyl', 'VINYL')
     AND sale.media_type IN (
        'EP_7_INCH',
        'SINGLE_12_INCH',
        'LP',
        'CD',
        'CASSETTE',
        'SACD',
        'DVD',
        'CD_BOX_SET',
        'LP_BOX_SET'
     )
    THEN sale.media_type
    WHEN COALESCE(sale.effective_media_type, '') IN ('Vinyl', 'VINYL')
    THEN 'LP'
    WHEN UPPER(BTRIM(COALESCE(
        sale.effective_media_type,
        sale.media_type,
        ''
    ))) = 'CASSETTE'
    THEN 'CASSETTE'
    ELSE COALESCE(
        NULLIF(BTRIM(sale.effective_media_type), ''),
        NULLIF(BTRIM(sale.media_type), ''),
        'UNKNOWN'
    )
END
"""


def _text_or_blank(value: object) -> str:
    """Return a stripped string, or nothing for a missing value."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _pressing_choice_label(row: Any) -> str:
    """Catalog choice with the record name and every marketplace."""
    album_title = _text_or_blank(getattr(row, "album_title", ""))
    artist_name = _text_or_blank(getattr(row, "artist_name", ""))
    english_name = english_album_title(album_title)
    name = english_name or album_title
    places = _text_or_blank(getattr(row, "marketplaces", ""))
    release_year = getattr(row, "release_year", None)
    year = ""
    if release_year is not None and not pd.isna(release_year):
        year = str(int(release_year))
    tracked = _text_or_blank(getattr(row, "tracked_artist", ""))
    parts = [
        year,
        tracked or artist_name,
        name,
        str(row.catalog_number),
        str(row.media_type),
        f"{int(row.sale_count)} sale(s)",
        places,
    ]
    return "  ·  ".join(part for part in parts if part)


def sale_type_label(auction_format: object) -> str:
    """Name the way the listing sold."""
    key = str(auction_format or "").strip().upper()
    if key in {"FIXED_PRICE_OBO", "OBO", "BEST_OFFER"}:
        return "Best Offer"
    if key == "FIXED_PRICE":
        return "Buy It Now"
    if key in {"AUCTION", "AUCTION_WITH_BUYOUT"}:
        return "Auction"
    return "Sale"


st.set_page_config(
    page_title="Pressing Analytics",
    page_icon="📈",
    layout="wide",
)
render_navigation(current_page="pages/2_Pressing_Analytics.py")


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


@st.cache_data(ttl=120)
def load_catalog_options(search: str) -> pd.DataFrame:
    """Load exact pressing choices with completed-sale coverage."""
    conditions = [
        "sale.effective_catalog_number IS NOT NULL",
        "BTRIM(sale.effective_catalog_number) <> ''",
        *COMPLETED_SALE_PREDICATE,
    ]
    parameters: dict[str, Any] = {}

    cleaned_search = search.strip()

    if cleaned_search:
        conditions.append(
            """
            (
                sale.effective_catalog_number ILIKE :search
                OR sale.title ILIKE :search
                OR sale.seller ILIKE :search
                OR family.display_title ILIKE :search
                OR family.display_artist ILIKE :search
                OR sale.effective_artist ILIKE :search
            )
            """
        )
        parameters["search"] = f"%{cleaned_search}%"

    where_clause = "\nAND ".join(conditions)

    return query_dataframe(
        f"""
        SELECT
            sale.effective_catalog_number AS catalog_number,
            {ANALYTICS_MEDIA_SQL} AS media_type,
            COALESCE(
                LEAST(
                    MIN(pressing.release_year) FILTER (
                        WHERE pressing.release_year BETWEEN 1950 AND 2015
                    ),
                    MIN(family.original_release_year) FILTER (
                        WHERE family.original_release_year BETWEEN 1950 AND 2015
                    )
                ),
                MIN(pressing.release_year) FILTER (
                    WHERE pressing.release_year BETWEEN 1950 AND 2030
                ),
                MIN(family.original_release_year) FILTER (
                    WHERE family.original_release_year BETWEEN 1950 AND 2030
                )
            ) AS release_year,
            STRING_AGG(
                DISTINCT sale.marketplace,
                ', ' ORDER BY sale.marketplace
            ) AS marketplaces,
            (ARRAY_AGG(family.display_artist) FILTER (
                WHERE family.display_artist IS NOT NULL
                  AND BTRIM(family.display_artist) <> ''
            ))[1] AS artist_name,
            (ARRAY_AGG(family.display_title) FILTER (
                WHERE family.display_title IS NOT NULL
                  AND BTRIM(family.display_title) <> ''
            ))[1] AS album_title,
            COALESCE(
                (ARRAY_AGG(sale.discogs_thumb_url) FILTER (
                    WHERE sale.discogs_thumb_url IS NOT NULL
                      AND BTRIM(sale.discogs_thumb_url) <> ''
                ))[1],
                (ARRAY_AGG(sale.image_url) FILTER (
                    WHERE sale.image_url IS NOT NULL
                      AND BTRIM(sale.image_url) <> ''
                ))[1]
            ) AS cover_url,
            COUNT(*) AS sale_count,
            COUNT(DISTINCT sale.marketplace) AS marketplace_count,
            COUNT(DISTINCT sale.seller) AS seller_count,
            MIN(sale.gross_price_usd) AS minimum_price,
            PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY sale.gross_price_usd)
                AS median_price,
            AVG(sale.gross_price_usd) AS average_price,
            MAX(sale.gross_price_usd) AS maximum_price,
            MIN(sale.ended_at) AS first_sale_at,
            MAX(sale.ended_at) AS latest_sale_at
        FROM warehouse.auction_collector_effective sale
        LEFT JOIN warehouse.pressing_identity pressing
            ON pressing.id = sale.pressing_id
        LEFT JOIN warehouse.release_family family
            ON family.id = pressing.release_family_id
        WHERE {where_clause}
        GROUP BY
            sale.effective_catalog_number,
            {ANALYTICS_MEDIA_SQL}
        ORDER BY
            release_year ASC NULLS LAST,
            sale.effective_catalog_number
        LIMIT 1000
        """,
        parameters,
    )


@st.cache_data(ttl=120)
def load_filter_values(
    catalog_number: str,
) -> dict[str, list[str]]:
    """Load valid filters for one pressing across every marketplace."""
    sale_filter = " AND ".join(COMPLETED_SALE_PREDICATE)
    dataframe = query_dataframe(
        f"""
        SELECT
            sale.marketplace,
            sale.seller,
            {ANALYTICS_MEDIA_SQL} AS effective_media_type,
            sale.effective_region
        FROM warehouse.auction_collector_effective sale
        WHERE sale.effective_catalog_number = :catalog_number
          AND {sale_filter}
        """,
        {
            "catalog_number": catalog_number,
        },
    )

    def values(column: str) -> list[str]:
        if column not in dataframe:
            return []

        series = (
            dataframe[column]
            .dropna()
            .astype(str)
            .str.strip()
        )

        return sorted(
            value
            for value in series.unique()
            if value
        )

    return {
        "marketplaces": values("marketplace"),
        "sellers": values("seller"),
        "media_types": values("effective_media_type"),
        "regions": values("effective_region"),
    }


@st.cache_data(ttl=120)
def load_date_bounds(
    catalog_number: str,
) -> tuple[date, date]:
    """Load available completed-sale date bounds."""
    sale_filter = " AND ".join(COMPLETED_SALE_PREDICATE)
    dataframe = query_dataframe(
        f"""
        SELECT
            MIN(COALESCE(sale.ended_at, sale.closing_at))::date
                AS minimum_date,
            MAX(COALESCE(sale.ended_at, sale.closing_at))::date
                AS maximum_date
        FROM warehouse.auction_collector_effective sale
        WHERE sale.effective_catalog_number = :catalog_number
          AND {sale_filter}
        """,
        {
            "catalog_number": catalog_number,
        },
    )

    today = date.today()

    if dataframe.empty:
        return today, today

    minimum = dataframe.iloc[0]["minimum_date"]
    maximum = dataframe.iloc[0]["maximum_date"]

    if pd.isna(minimum) or pd.isna(maximum):
        return today, today

    return (
        pd.Timestamp(minimum).date(),
        pd.Timestamp(maximum).date(),
    )


@st.cache_data(ttl=120)
def load_sales(
    *,
    catalog_number: str,
    account_id: str,
    marketplaces: tuple[str, ...],
    sellers: tuple[str, ...],
    media_types: tuple[str, ...],
    regions: tuple[str, ...],
    start_date: date,
    end_date: date,
    exclude_bulk: bool,
) -> pd.DataFrame:
    """Load exact completed comparable sales."""
    conditions = [
        "sale.effective_catalog_number = :catalog_number",
        *COMPLETED_SALE_PREDICATE,
        """(
            COALESCE(sale.ended_at, sale.closing_at) IS NULL
            OR COALESCE(sale.ended_at, sale.closing_at)::date
                BETWEEN :start_date AND :end_date
        )""",
    ]

    parameters: dict[str, Any] = {
        "catalog_number": catalog_number,
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    if marketplaces:
        conditions.append(
            "sale.marketplace = ANY(:marketplaces)"
        )
        parameters["marketplaces"] = list(marketplaces)

    if sellers:
        conditions.append(
            "sale.seller = ANY(:sellers)"
        )
        parameters["sellers"] = list(sellers)

    if media_types:
        conditions.append(
            f"({ANALYTICS_MEDIA_SQL}) = ANY(:media_types)"
        )
        parameters["media_types"] = list(media_types)

    if regions:
        conditions.append(
            "sale.effective_region = ANY(:regions)"
        )
        parameters["regions"] = list(regions)

    if exclude_bulk:
        conditions.append(
            "COALESCE(sale.effective_bulk_lot, false) = false"
        )

    where_clause = "\nAND ".join(conditions)

    dataframe = query_dataframe(
        f"""
        SELECT
            sale.marketplace,
            sale.listing_id,
            COALESCE(sale.ended_at, sale.closing_at) AS ended_at,
            sale.seller,
            sale.title,
            sale.auction_url,
            sale.auction_format,
            sale.effective_catalog_number AS catalog_number,
            COALESCE(
                family.display_artist,
                sale.effective_artist
            ) AS artist_name,
            family.display_title AS album_title,
            COALESCE(
                NULLIF(BTRIM(sale.discogs_thumb_url), ''),
                NULLIF(BTRIM(sale.image_url), '')
            ) AS cover_url,
            {ANALYTICS_MEDIA_SQL} AS media_type,
            sale.effective_region AS region,
            sale.effective_disc_count AS disc_count,
            sale.effective_bulk_lot AS bulk_lot,
            sale.effective_obi AS obi,
            sale.effective_insert_present AS insert_present,
            sale.effective_poster_present AS poster_present,
            sale.effective_condition_media AS media_condition,
            sale.effective_condition_cover AS cover_condition,
            sale.start_price,
            sale.final_price,
            sale.tax_amount,
            sale.gross_price,
            sale.gross_price_usd,
            paid.manual_purchase_price AS purchase_price,
            paid.manual_purchase_currency AS purchase_currency,
            sale.currency,
            sale.bid_count,
            sale.effective_importance_score AS importance_score,
            sale.effective_verdict AS verdict
        FROM warehouse.auction_collector_effective sale
        LEFT JOIN warehouse.pressing_identity pressing
            ON pressing.id = sale.pressing_id
        LEFT JOIN warehouse.release_family family
            ON family.id = pressing.release_family_id
        LEFT JOIN LATERAL (
            SELECT
                owned.manual_purchase_price,
                owned.manual_purchase_currency
            FROM warehouse.auction_collector owned
            WHERE owned.account_id = CAST(:account_id AS uuid)
              AND owned.marketplace::text = sale.marketplace::text
              AND owned.listing_id::text = sale.listing_id::text
              AND owned.manual_purchased IS TRUE
              AND owned.manual_purchase_price IS NOT NULL
            ORDER BY owned.purchase_updated_at DESC NULLS LAST
            LIMIT 1
        ) paid ON TRUE
        WHERE {where_clause}
        ORDER BY
            sale.ended_at ASC,
            sale.id ASC
        """,
        parameters,
    )

    if dataframe.empty:
        return dataframe

    dataframe["ended_at"] = pd.to_datetime(
        dataframe["ended_at"],
        errors="coerce",
        utc=True,
    )

    numeric_columns = (
        "start_price",
        "final_price",
        "tax_amount",
        "gross_price",
        "gross_price_usd",
        "purchase_price",
        "bid_count",
        "disc_count",
        "importance_score",
    )

    for column in numeric_columns:
        dataframe[column] = pd.to_numeric(
            dataframe[column],
            errors="coerce",
        )

    dataframe["completed_date"] = (
        dataframe["ended_at"]
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
    )

    dataframe["seller_display"] = (
        dataframe["seller"]
        .fillna("Unknown seller")
        .astype(str)
    )

    dataframe["marketplace_display"] = (
        dataframe["marketplace"]
        .fillna("unknown")
        .astype(str)
        .str.upper()
    )
    dataframe["price_usd"] = dataframe["gross_price_usd"]
    dataframe["native_price"] = [
        money(price, code)
        for price, code in zip(
            dataframe["gross_price"],
            dataframe["currency"].fillna(""),
            strict=True,
        )
    ]
    paid = pd.to_numeric(dataframe["purchase_price"], errors="coerce")
    paid_code = (
        dataframe["purchase_currency"].fillna("USD").astype(str).str.upper()
    )
    for idx in dataframe.index[paid.notna() & paid.gt(0)]:
        amount = paid.at[idx]
        code = paid_code.at[idx] or "USD"
        dataframe.at[idx, "native_price"] = money(amount, code)
        if code == "USD":
            dataframe.at[idx, "price_usd"] = float(amount)
    dataframe["sale_type"] = dataframe["auction_format"].map(
        sale_type_label
    )
    dataframe["bid_label"] = [
        _bid_label(sale_type, bid_count)
        for sale_type, bid_count in zip(
            dataframe["sale_type"],
            dataframe["bid_count"],
            strict=True,
        )
    ]
    recorded_bids = dataframe["bid_count"].where(
        dataframe["sale_type"].eq("Auction")
    )
    dataframe["point_size"] = recorded_bids.fillna(
        recorded_bids.median() if recorded_bids.notna().any() else 1
    )

    return dataframe


def _bid_label(sale_type: str, bid_count: Any) -> str:
    """Show a bid count only when the listing was an auction."""
    if sale_type != "Auction":
        return "—"
    if bid_count is None or pd.isna(bid_count):
        return "Not captured"
    return str(int(bid_count))


def money(
    value: Any,
    currency: str,
) -> str:
    """Format currency without performing conversion."""
    if value is None or pd.isna(value):
        return "—"

    amount = Decimal(str(value))

    if currency == "JPY":
        return f"¥{amount:,.0f}"

    if currency == "USD":
        return f"${amount:,.2f}"

    return f"{amount:,.2f} {currency}"


def currency_format(currency: str) -> str:
    """Return an Altair numeric format."""
    if currency == "JPY":
        return ",.0f"

    return ",.2f"


def streamlit_money_format(currency: str) -> str:
    """Return a printf format Streamlit NumberColumn can render."""
    if currency == "JPY":
        return "¥%.0f"

    if currency == "USD":
        return "$%.2f"

    return "%.2f"


def render_metrics(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render completed-sale summary statistics."""
    prices = sales["price_usd"].dropna()

    if prices.empty:
        st.warning("No stored USD prices match these filters.")
        return

    dated = sales.dropna(subset=["price_usd"]).sort_values(
        "ended_at",
        ascending=False,
    )
    latest_row = dated.iloc[0]

    columns = st.columns(7)

    columns[0].metric(
        "Comparable sales",
        len(prices),
    )
    columns[1].metric(
        "Median",
        money(prices.median(), currency),
    )
    columns[2].metric(
        "Average",
        money(prices.mean(), currency),
    )
    columns[3].metric(
        "Minimum",
        money(prices.min(), currency),
    )
    columns[4].metric(
        "Maximum",
        money(prices.max(), currency),
    )
    columns[5].metric(
        "Latest",
        money(
            latest_row["price_usd"],
            currency,
        ),
    )
    columns[6].metric(
        "Sellers",
        sales["seller"].nunique(dropna=True),
    )


def render_price_history(
    sales: pd.DataFrame,
    currency: str,
    *,
    artist_name: str,
    album_title: str,
    catalog_number: str,
    cover_url: str,
) -> None:
    """Render every marketplace on one stored-USD price chart."""
    chart_data = sales.dropna(
        subset=[
            "completed_date",
            "price_usd",
        ]
    ).copy()

    undated = int(sales["completed_date"].isna().sum())
    if undated:
        st.caption(
            f"{undated} sold "
            f"{'listing has' if undated == 1 else 'listings have'} "
            "no stored sale date, so they stay in the list below "
            "and not on the timeline."
        )

    if chart_data.empty:
        st.info("No dated completed sales are available.")
        return

    chart_data["media_condition_label"] = (
        chart_data["media_condition"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace("", "Unknown")
    )
    chart_data["cover_condition_label"] = (
        chart_data["cover_condition"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace("", "Unknown")
    )
    chart_data["listing_label"] = (
        chart_data["listing_id"]
        .fillna("")
        .astype(str)
    )

    median_price = float(
        chart_data["price_usd"].median()
    )

    price_axis = alt.Axis(
        title=f"Sold for ({currency})",
        format=currency_format(currency),
    )

    x_encoding = alt.X(
        "completed_date:T",
        title="Sale date",
        axis=alt.Axis(
            format="%b %Y",
            labelAngle=-30,
        ),
    )

    y_encoding = alt.Y(
        "price_usd:Q",
        title=f"Sold for ({currency})",
        axis=price_axis,
        scale=alt.Scale(
            zero=False,
            nice=True,
        ),
    )

    sale_points = (
        alt.Chart(chart_data)
        .mark_circle(
            opacity=0.9,
            stroke="white",
            strokeWidth=1,
        )
        .encode(
            x=x_encoding,
            y=y_encoding,
            color=alt.Color(
                "marketplace_display:N",
                title="Marketplace",
            ),
            size=alt.Size(
                "point_size:Q",
                title="Bids",
                scale=alt.Scale(
                    range=[80, 280],
                ),
            ),
            tooltip=[
                alt.Tooltip(
                    "completed_date:T",
                    title="Completed",
                    format="%Y-%m-%d %H:%M",
                ),
                alt.Tooltip(
                    "price_usd:Q",
                    title=f"Price ({currency})",
                    format=currency_format(currency),
                ),
                alt.Tooltip(
                    "native_price:N",
                    title="Original price",
                ),
                alt.Tooltip(
                    "media_condition_label:N",
                    title="Media condition",
                ),
                alt.Tooltip(
                    "cover_condition_label:N",
                    title="Sleeve condition",
                ),
                alt.Tooltip(
                    "sale_type:N",
                    title="Sale type",
                ),
                alt.Tooltip(
                    "bid_label:N",
                    title="Bids",
                ),
                alt.Tooltip(
                    "marketplace_display:N",
                    title="Marketplace",
                ),
                alt.Tooltip(
                    "seller_display:N",
                    title="Seller",
                ),
                alt.Tooltip(
                    "listing_label:N",
                    title="Listing",
                ),
                alt.Tooltip(
                    "title:N",
                    title="Title",
                ),
                alt.Tooltip(
                    "media_type:N",
                    title="Media",
                ),
                alt.Tooltip(
                    "region:N",
                    title="Region",
                ),
            ],
        )
        .interactive()
    )

    median_data = pd.DataFrame(
        {
            "median_price": [median_price],
            "label": [
                f"Median {money(median_price, currency)}"
            ],
        }
    )

    median_rule = (
        alt.Chart(median_data)
        .mark_rule(
            strokeDash=[8, 5],
            strokeWidth=2,
        )
        .encode(
            y=alt.Y(
                "median_price:Q",
                scale=alt.Scale(
                    zero=False,
                ),
            ),
            tooltip=[
                alt.Tooltip(
                    "label:N",
                    title="Reference",
                )
            ],
        )
    )

    median_label = (
        alt.Chart(median_data)
        .mark_text(
            align="left",
            baseline="bottom",
            dx=8,
            dy=-5,
            fontWeight="bold",
        )
        .encode(
            x=alt.value(0),
            y=alt.Y(
                "median_price:Q",
                scale=alt.Scale(
                    zero=False,
                ),
            ),
            text="label:N",
        )
    )

    combined = (
        sale_points
        + median_rule
        + median_label
    ).properties(
        height=480,
            title=alt.TitleParams(
            " · ".join(
                part
                for part in (
                    artist_name,
                    english_album_title(album_title) or album_title,
                    catalog_number,
                )
                if part
            ),
            subtitle=(
                "Buyee, eBay, and Gripsweat on one chart. "
                "The axis is the stored USD price. "
                "Color is the marketplace. "
                "Size is the bid count when the scrape recorded one."
            ),
            anchor="start",
            fontSize=22,
            subtitleFontSize=13,
        ),
    )

    identity, chart_column = st.columns([1, 4])
    if cover_url:
        identity.image(cover_url, width=210)
    shown_name = english_album_title(album_title) or album_title
    identity.markdown(
        "**"
        + " · ".join(
            part
            for part in (artist_name, shown_name, catalog_number)
            if part
        )
        + "**"
    )
    if album_title and album_title != shown_name:
        identity.caption(album_title)
    chart_column.altair_chart(
        combined,
        width="stretch",
    )


def render_price_distribution(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render box plots and individual observations."""
    chart_data = sales.dropna(
        subset=["price_usd"]
    ).copy()

    if chart_data.empty:
        st.info("No prices are available.")
        return

    box_plot = (
        alt.Chart(chart_data)
        .mark_boxplot(
            extent="min-max",
            size=55,
        )
        .encode(
            x=alt.X(
                "marketplace_display:N",
                title="Marketplace",
            ),
            y=alt.Y(
                "price_usd:Q",
                title=f"Completed price ({currency})",
                axis=alt.Axis(
                    format=currency_format(currency),
                ),
                scale=alt.Scale(
                    zero=False,
                ),
            ),
            color=alt.Color(
                "marketplace_display:N",
                title="Marketplace",
                legend=None,
            ),
            tooltip=[
                alt.Tooltip(
                    "marketplace_display:N",
                    title="Marketplace",
                )
            ],
        )
        .properties(
            height=390,
            title=alt.TitleParams(
                "Price distribution",
                subtitle=(
                    "Min/max whiskers with quartiles "
                    "and median."
                ),
                anchor="start",
                fontSize=22,
                subtitleFontSize=13,
            ),
        )
    )

    st.altair_chart(
        box_plot,
        width="stretch",
    )


def render_monthly_activity(
    sales: pd.DataFrame,
) -> None:
    """Render completed-sale volume by month."""
    chart_data = sales.dropna(
        subset=["completed_date"]
    ).copy()

    if chart_data.empty:
        st.info("No dated sales are available.")
        return

    chart_data["completed_month"] = (
        chart_data["completed_date"]
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    monthly = (
        chart_data.groupby(
            [
                "completed_month",
                "marketplace_display",
            ],
            as_index=False,
        )
        .agg(
            sales=("listing_id", "count"),
        )
    )

    chart = (
        alt.Chart(monthly)
        .mark_bar(
            cornerRadiusTopLeft=4,
            cornerRadiusTopRight=4,
        )
        .encode(
            x=alt.X(
                "completed_month:T",
                title="Completed month",
                axis=alt.Axis(
                    format="%b %Y",
                    labelAngle=-30,
                ),
            ),
            y=alt.Y(
                "sales:Q",
                title="Completed sales",
                stack="zero",
            ),
            color=alt.Color(
                "marketplace_display:N",
                title="Marketplace",
            ),
            tooltip=[
                alt.Tooltip(
                    "completed_month:T",
                    title="Month",
                    format="%B %Y",
                ),
                alt.Tooltip(
                    "marketplace_display:N",
                    title="Marketplace",
                ),
                alt.Tooltip(
                    "sales:Q",
                    title="Sales",
                    format=".0f",
                ),
            ],
        )
        .properties(
            height=390,
            title=alt.TitleParams(
                "Completed-sale volume",
                subtitle=(
                    "Number of exact pressing matches "
                    "completed each month."
                ),
                anchor="start",
                fontSize=22,
                subtitleFontSize=13,
            ),
        )
    )

    st.altair_chart(
        chart,
        width="stretch",
    )


def render_marketplace_summary(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render marketplace and seller statistics."""
    if sales.empty:
        st.info("No matching sales are available.")
        return

    marketplace_summary = (
        sales.groupby(
            "marketplace_display",
            dropna=False,
        )["price_usd"]
        .agg(
            sales="count",
            minimum="min",
            median="median",
            average="mean",
            maximum="max",
        )
        .reset_index()
        .sort_values(
            "sales",
            ascending=False,
        )
    )

    st.dataframe(
        marketplace_summary,
        hide_index=True,
        width="stretch",
        column_config={
            "marketplace_display": st.column_config.TextColumn(
                "Marketplace"
            ),
            "sales": st.column_config.NumberColumn(
                "Sales",
                format="%d",
            ),
            "minimum": st.column_config.NumberColumn(
                f"Minimum ({currency})",
                format=streamlit_money_format(currency),
            ),
            "median": st.column_config.NumberColumn(
                f"Median ({currency})",
                format=streamlit_money_format(currency),
            ),
            "average": st.column_config.NumberColumn(
                f"Average ({currency})",
                format=streamlit_money_format(currency),
            ),
            "maximum": st.column_config.NumberColumn(
                f"Maximum ({currency})",
                format=streamlit_money_format(currency),
            ),
        },
    )

    st.markdown("#### Seller summary")

    seller_summary = (
        sales.groupby(
            ["marketplace_display", "seller_display"],
            dropna=False,
        )["price_usd"]
        .agg(
            sales="count",
            median="median",
            average="mean",
            latest="last",
        )
        .reset_index()
        .sort_values(
            [
                "sales",
                "median",
            ],
            ascending=[
                False,
                False,
            ],
        )
    )

    st.dataframe(
        seller_summary,
        hide_index=True,
        width="stretch",
        column_config={
            "marketplace_display": st.column_config.TextColumn(
                "Marketplace"
            ),
            "seller_display": st.column_config.TextColumn(
                "Seller"
            ),
            "sales": st.column_config.NumberColumn(
                "Sales",
                format="%d",
            ),
            "median": st.column_config.NumberColumn(
                f"Median ({currency})",
                format=streamlit_money_format(currency),
            ),
            "average": st.column_config.NumberColumn(
                f"Average ({currency})",
                format=streamlit_money_format(currency),
            ),
            "latest": st.column_config.NumberColumn(
                f"Latest ({currency})",
                format=streamlit_money_format(currency),
            ),
        },
    )


def render_comparable_sales(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render individual completed comparable sales."""
    if sales.empty:
        st.info("No comparable sales match the filters.")
        return

    table = sales.sort_values(
        "ended_at",
        ascending=False,
    ).copy()

    table["completed"] = (
        table["completed_date"]
        .dt.strftime("%Y-%m-%d %H:%M")
    )

    display_columns = [
        "cover_url",
        "completed",
        "marketplace",
        "sale_type",
        "native_price",
        "price_usd",
        "listing_id",
        "seller",
        "title",
        "media_type",
        "region",
        "disc_count",
        "obi",
        "insert_present",
        "poster_present",
        "bulk_lot",
        "bid_label",
        "media_condition",
        "cover_condition",
        "verdict",
        "auction_url",
    ]

    st.dataframe(
        table[display_columns],
        hide_index=True,
        width="stretch",
        column_config={
            "cover_url": st.column_config.ImageColumn(
                "Pressing",
                width="small",
            ),
            "completed": st.column_config.TextColumn(
                "Completed"
            ),
            "marketplace": st.column_config.TextColumn(
                "Marketplace"
            ),
            "sale_type": st.column_config.TextColumn(
                "Sale type"
            ),
            "listing_id": st.column_config.TextColumn(
                "Listing ID"
            ),
            "seller": st.column_config.TextColumn(
                "Seller"
            ),
            "title": st.column_config.TextColumn(
                "Title",
                width="large",
            ),
            "media_type": st.column_config.TextColumn(
                "Media"
            ),
            "region": st.column_config.TextColumn(
                "Region"
            ),
            "disc_count": st.column_config.NumberColumn(
                "Discs",
                format="%d",
            ),
            "obi": st.column_config.CheckboxColumn(
                "Obi"
            ),
            "insert_present": st.column_config.CheckboxColumn(
                "Insert"
            ),
            "poster_present": st.column_config.CheckboxColumn(
                "Poster"
            ),
            "bulk_lot": st.column_config.CheckboxColumn(
                "Bulk"
            ),
            "bid_label": st.column_config.TextColumn(
                "Bids"
            ),
            "media_condition": st.column_config.TextColumn(
                "Media condition"
            ),
            "cover_condition": st.column_config.TextColumn(
                "Sleeve condition"
            ),
            "native_price": st.column_config.TextColumn(
                "Original price"
            ),
            "price_usd": st.column_config.NumberColumn(
                "USD",
                format=streamlit_money_format(currency),
            ),
            "verdict": st.column_config.TextColumn(
                "Verdict"
            ),
            "auction_url": st.column_config.LinkColumn(
                "Listing",
                display_text="Open",
            ),
        },
    )


_MEDIA_RANK = {
    "LP": 0,
    "LP_BOX_SET": 1,
    "EP_7_INCH": 2,
    "SINGLE_12_INCH": 3,
    "CASSETTE": 4,
    "CASSETTE_BOX_SET": 5,
    "CD": 6,
    "CD_BOX_SET": 7,
    "SACD": 8,
    "DVD": 9,
}


def _tracked_artist_for_pressing(
    artist: object,
    title: object,
    names: tuple[str, ...],
) -> str:
    """The tracked artist this pressing belongs to."""
    for name in names:
        if listing_belongs_to_tracked_artists(
            title=title,
            artist=artist,
            tracked_names=(name,),
        ):
            return name
    return ""


def pressings_for_tracked_artist(
    options: pd.DataFrame,
    artist_name: str,
    tracked_names: tuple[str, ...],
) -> pd.DataFrame:
    """One artist's records, earliest release first, then older formats."""
    if options.empty:
        return options
    frame = options.copy()
    frame["tracked_artist"] = [
        _tracked_artist_for_pressing(artist, title, tracked_names)
        for artist, title in zip(
            frame["artist_name"],
            frame["album_title"],
            strict=True,
        )
    ]
    frame = frame.loc[frame["tracked_artist"].eq(artist_name)].copy()
    frame["media_rank"] = (
        frame["media_type"].map(_MEDIA_RANK).fillna(50)
    )
    frame["release_year"] = pd.to_numeric(
        frame["release_year"],
        errors="coerce",
    )
    return frame.sort_values(
        ["release_year", "media_rank", "catalog_number"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def normalize_date_selection(
    selected_dates: Any,
    minimum_date: date,
    maximum_date: date,
) -> tuple[date, date]:
    """Normalize Streamlit's date-range result."""
    if isinstance(selected_dates, tuple):
        if len(selected_dates) == 2:
            return selected_dates

    if isinstance(selected_dates, list):
        if len(selected_dates) == 2:
            return selected_dates[0], selected_dates[1]

    if isinstance(selected_dates, date):
        return selected_dates, selected_dates

    return minimum_date, maximum_date


def main() -> None:
    """Render pressing analytics."""

    page_account_context = require_authenticated_account(
        engine
    )
    render_account_menu(
        page_account_context
    )
    st.title("📈 Pressing Analytics")
    st.caption(
        "One chart for the same record across Buyee, eBay, "
        "and Gripsweat. Prices use the stored USD amount. "
        "The original currency stays on each sale."
    )

    search_column, refresh_column = st.columns(
        [5, 1]
    )

    search = search_column.text_input(
        "Search catalog number, title, or seller",
        placeholder=(
            "MR3166, 28TR-2062, MRZ-9229/30, "
            "817 556-1"
        ),
    )

    if refresh_column.button(
        "Refresh data",
        width="stretch",
    ):
        st.cache_data.clear()
        st.rerun()

    options = load_catalog_options(search)
    tracked_names = enabled_tracked_artist_names(
        engine,
        account_id=page_account_context.account_id,
    )
    if tracked_names:
        selected_artist = st.selectbox(
            "Artist",
            tracked_names,
        )
        options = pressings_for_tracked_artist(
            options,
            selected_artist,
            tracked_names,
        )

    if options.empty:
        st.warning(
            "No priced catalog sales match this artist."
        )
        return

    option_keys = [
        (
            str(row.catalog_number),
            str(row.media_type),
        )
        for row in options.itertuples()
    ]

    option_labels = {
        key: _pressing_choice_label(row)
        for key, row in zip(
            option_keys,
            options.itertuples(),
            strict=True,
        )
    }

    selected_catalog, selected_media = (
        st.selectbox(
            "Record",
            options=option_keys,
            format_func=lambda key: option_labels[key],
        )
    )

    selected_option = options[
        (options["catalog_number"] == selected_catalog)
        & (options["media_type"] == selected_media)
    ].iloc[0]

    heading_columns = st.columns(
        [1.1, 2.4, 1, 1, 1]
    )
    cover_url = _text_or_blank(selected_option.get("cover_url"))
    if cover_url:
        heading_columns[0].image(
            cover_url,
            width=148,
        )
    artist_name = _text_or_blank(selected_option.get("artist_name"))
    album_title = _text_or_blank(selected_option.get("album_title"))
    english_name = english_album_title(album_title)
    heading_columns[1].subheader(
        " · ".join(
            part
            for part in (
                artist_name,
                english_name or album_title,
                selected_catalog,
            )
            if part
        )
    )
    if album_title and album_title != english_name:
        heading_columns[1].caption(album_title)
    places = _text_or_blank(selected_option.get("marketplaces"))
    heading_columns[1].caption(
        " · ".join(
            part
            for part in (selected_media, places)
            if part
        )
    )
    heading_columns[2].metric(
        "Stored sales",
        int(selected_option["sale_count"]),
    )
    heading_columns[3].metric(
        "Marketplaces",
        int(
            selected_option["marketplace_count"]
        ),
    )
    heading_columns[4].metric(
        "Sellers",
        int(selected_option["seller_count"]),
    )

    filter_values = load_filter_values(
        selected_catalog,
    )

    minimum_date, maximum_date = load_date_bounds(
        selected_catalog,
    )

    with st.expander(
        "Comparable-sale filters",
        expanded=True,
    ):
        first_row = st.columns(4)

        marketplaces = first_row[0].multiselect(
            "Marketplace",
            filter_values["marketplaces"],
        )
        sellers = first_row[1].multiselect(
            "Seller",
            filter_values["sellers"],
        )
        media_types = first_row[2].multiselect(
            "Media type",
            filter_values["media_types"],
            default=(
                [selected_media]
                if selected_media != "UNKNOWN"
                and selected_media
                in filter_values["media_types"]
                else []
            ),
        )
        regions = first_row[3].multiselect(
            "Region",
            filter_values["regions"],
        )

        second_row = st.columns([3, 1])

        selected_dates = second_row[0].date_input(
            "Completed-date interval",
            value=(
                minimum_date,
                maximum_date,
            ),
            min_value=minimum_date,
            max_value=maximum_date,
        )

        exclude_bulk = second_row[1].checkbox(
            "Exclude bulk lots",
            value=True,
        )

    start_date, end_date = normalize_date_selection(
        selected_dates,
        minimum_date,
        maximum_date,
    )

    sales = load_sales(
        catalog_number=selected_catalog,
        account_id=str(page_account_context.account_id),
        marketplaces=tuple(marketplaces),
        sellers=tuple(sellers),
        media_types=tuple(media_types),
        regions=tuple(regions),
        start_date=start_date,
        end_date=end_date,
        exclude_bulk=exclude_bulk,
    )

    render_metrics(
        sales,
        "USD",
    )

    (
        history_tab,
        distribution_tab,
        activity_tab,
        summary_tab,
        sales_tab,
    ) = st.tabs(
        (
            "Price history",
            "Price distribution",
            "Sale activity",
            "Marketplace and sellers",
            "Comparable sales",
        )
    )

    with history_tab:
        render_price_history(
            sales,
            "USD",
            artist_name=artist_name,
            album_title=album_title,
            catalog_number=selected_catalog,
            cover_url=cover_url,
        )
        st.markdown("#### Sales history")
        st.caption(
            "Each row is one completed sale. Buyee and any other "
            "non-USD price keeps the original amount and shows the "
            "stored USD conversion beside it. The pressing image is "
            "the cover for that row."
        )
        render_comparable_sales(
            sales,
            "USD",
        )

    with distribution_tab:
        render_price_distribution(
            sales,
            "USD",
        )

    with activity_tab:
        render_monthly_activity(
            sales,
        )

    with summary_tab:
        render_marketplace_summary(
            sales,
            "USD",
        )

    with sales_tab:
        render_comparable_sales(
            sales,
            "USD",
        )

    st.divider()

    st.caption(
        "One record keeps Buyee, eBay, and Gripsweat together. "
        "The chart uses the stored USD price, and each row still "
        "shows the original amount. A recorded zero-bid auction "
        "is left out. Variants such as MR3166 and MR316-6 remain "
        "separate until they are manually normalized in "
        "Collector Review."
    )


if __name__ == "__main__":
    main()
