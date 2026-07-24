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


st.set_page_config(
    page_title="Pressing Analytics",
    page_icon="📈",
    layout="wide",
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


@st.cache_data(ttl=120)
def load_catalog_options(search: str) -> pd.DataFrame:
    """Load exact pressing choices with completed-sale coverage."""
    conditions = [
        "effective_catalog_number IS NOT NULL",
        "BTRIM(effective_catalog_number) <> ''",
        "gross_price IS NOT NULL",
        "ended_at IS NOT NULL",
    ]
    parameters: dict[str, Any] = {}

    cleaned_search = search.strip()

    if cleaned_search:
        conditions.append(
            """
            (
                effective_catalog_number ILIKE :search
                OR title ILIKE :search
                OR seller ILIKE :search
            )
            """
        )
        parameters["search"] = f"%{cleaned_search}%"

    where_clause = "\nAND ".join(conditions)

    return query_dataframe(
        f"""
        SELECT
            effective_catalog_number AS catalog_number,
            COALESCE(
                effective_media_type,
                'UNKNOWN'
            ) AS media_type,
            currency,
            COUNT(*) AS sale_count,
            COUNT(DISTINCT marketplace) AS marketplace_count,
            COUNT(DISTINCT seller) AS seller_count,
            MIN(gross_price) AS minimum_price,
            PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY gross_price)
                AS median_price,
            AVG(gross_price) AS average_price,
            MAX(gross_price) AS maximum_price,
            MIN(ended_at) AS first_sale_at,
            MAX(ended_at) AS latest_sale_at
        FROM warehouse.auction_collector_effective
        WHERE {where_clause}
        GROUP BY
            effective_catalog_number,
            COALESCE(
                effective_media_type,
                'UNKNOWN'
            ),
            currency
        ORDER BY
            sale_count DESC,
            latest_sale_at DESC,
            effective_catalog_number
        LIMIT 1000
        """,
        parameters,
    )


@st.cache_data(ttl=120)
def load_filter_values(
    catalog_number: str,
    currency: str,
) -> dict[str, list[str]]:
    """Load valid filters for one exact pressing and currency."""
    dataframe = query_dataframe(
        """
        SELECT
            marketplace,
            seller,
            effective_media_type,
            effective_region
        FROM warehouse.auction_collector_effective
        WHERE effective_catalog_number = :catalog_number
          AND currency = :currency
          AND gross_price IS NOT NULL
          AND ended_at IS NOT NULL
        """,
        {
            "catalog_number": catalog_number,
            "currency": currency,
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
    currency: str,
) -> tuple[date, date]:
    """Load available completed-sale date bounds."""
    dataframe = query_dataframe(
        """
        SELECT
            MIN(ended_at)::date AS minimum_date,
            MAX(ended_at)::date AS maximum_date
        FROM warehouse.auction_collector_effective
        WHERE effective_catalog_number = :catalog_number
          AND currency = :currency
          AND gross_price IS NOT NULL
          AND ended_at IS NOT NULL
        """,
        {
            "catalog_number": catalog_number,
            "currency": currency,
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
    currency: str,
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
        "effective_catalog_number = :catalog_number",
        "currency = :currency",
        "gross_price IS NOT NULL",
        "ended_at IS NOT NULL",
        "ended_at::date BETWEEN :start_date AND :end_date",
    ]

    parameters: dict[str, Any] = {
        "catalog_number": catalog_number,
        "currency": currency,
        "start_date": start_date,
        "end_date": end_date,
    }

    if marketplaces:
        conditions.append(
            "marketplace = ANY(:marketplaces)"
        )
        parameters["marketplaces"] = list(marketplaces)

    if sellers:
        conditions.append(
            "seller = ANY(:sellers)"
        )
        parameters["sellers"] = list(sellers)

    if media_types:
        conditions.append(
            "effective_media_type = ANY(:media_types)"
        )
        parameters["media_types"] = list(media_types)

    if regions:
        conditions.append(
            "effective_region = ANY(:regions)"
        )
        parameters["regions"] = list(regions)

    if exclude_bulk:
        conditions.append(
            "COALESCE(effective_bulk_lot, false) = false"
        )

    where_clause = "\nAND ".join(conditions)

    dataframe = query_dataframe(
        f"""
        SELECT
            marketplace,
            listing_id,
            ended_at,
            seller,
            title,
            auction_url,
            effective_catalog_number AS catalog_number,
            effective_media_type AS media_type,
            effective_region AS region,
            effective_disc_count AS disc_count,
            effective_bulk_lot AS bulk_lot,
            effective_obi AS obi,
            effective_insert_present AS insert_present,
            effective_poster_present AS poster_present,
            effective_condition_media AS media_condition,
            effective_condition_cover AS cover_condition,
            start_price,
            final_price,
            tax_amount,
            gross_price,
            currency,
            bid_count,
            effective_importance_score AS importance_score,
            effective_verdict AS verdict
        FROM warehouse.auction_collector_effective
        WHERE {where_clause}
        ORDER BY
            ended_at ASC,
            id ASC
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

    return dataframe


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


def render_metrics(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render completed-sale summary statistics."""
    prices = sales["gross_price"].dropna()

    if prices.empty:
        st.warning("No priced sales match these filters.")
        return

    latest_row = sales.sort_values(
        "ended_at",
        ascending=False,
    ).iloc[0]

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
            latest_row["gross_price"],
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
) -> None:
    """Render a Discogs-style completed-sale history graph."""
    chart_data = sales.dropna(
        subset=[
            "completed_date",
            "gross_price",
        ]
    ).copy()

    if chart_data.empty:
        st.info("No dated completed sales are available.")
        return

    median_price = float(
        chart_data["gross_price"].median()
    )

    price_axis = alt.Axis(
        title=f"Completed sale price ({currency})",
        format=currency_format(currency),
    )

    x_encoding = alt.X(
        "completed_date:T",
        title="Completed date",
        axis=alt.Axis(
            format="%b %Y",
            labelAngle=-30,
        ),
    )

    y_encoding = alt.Y(
        "gross_price:Q",
        title=f"Completed sale price ({currency})",
        axis=price_axis,
        scale=alt.Scale(
            zero=False,
            nice=True,
        ),
    )

    trend_lines = (
        alt.Chart(chart_data)
        .mark_line(
            opacity=0.45,
            strokeWidth=2,
        )
        .encode(
            x=x_encoding,
            y=y_encoding,
            color=alt.Color(
                "marketplace_display:N",
                title="Marketplace",
            ),
            detail="marketplace_display:N",
        )
    )

    sale_points = (
        alt.Chart(chart_data)
        .mark_circle(
            size=120,
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
            shape=alt.Shape(
                "marketplace_display:N",
                title="Marketplace",
            ),
            tooltip=[
                alt.Tooltip(
                    "completed_date:T",
                    title="Completed",
                    format="%Y-%m-%d %H:%M",
                ),
                alt.Tooltip(
                    "gross_price:Q",
                    title=f"Price ({currency})",
                    format=currency_format(currency),
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
                alt.Tooltip(
                    "bid_count:Q",
                    title="Bids",
                    format=".0f",
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
        trend_lines
        + sale_points
        + median_rule
        + median_label
    ).properties(
        height=480,
        title=alt.TitleParams(
            "Completed-sale price history",
            subtitle=(
                "Points are individual completed listings. "
                "The dashed rule is the filtered median."
            ),
            anchor="start",
            fontSize=22,
            subtitleFontSize=13,
        ),
    )

    st.altair_chart(
        combined,
        width="stretch",
    )


def render_price_distribution(
    sales: pd.DataFrame,
    currency: str,
) -> None:
    """Render box plots and individual observations."""
    chart_data = sales.dropna(
        subset=["gross_price"]
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
                "gross_price:Q",
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
        )["gross_price"]
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
                format=currency_format(currency),
            ),
            "median": st.column_config.NumberColumn(
                f"Median ({currency})",
                format=currency_format(currency),
            ),
            "average": st.column_config.NumberColumn(
                f"Average ({currency})",
                format=currency_format(currency),
            ),
            "maximum": st.column_config.NumberColumn(
                f"Maximum ({currency})",
                format=currency_format(currency),
            ),
        },
    )

    st.markdown("#### Seller summary")

    seller_summary = (
        sales.groupby(
            "seller_display",
            dropna=False,
        )["gross_price"]
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
            "seller_display": st.column_config.TextColumn(
                "Seller"
            ),
            "sales": st.column_config.NumberColumn(
                "Sales",
                format="%d",
            ),
            "median": st.column_config.NumberColumn(
                f"Median ({currency})",
                format=currency_format(currency),
            ),
            "average": st.column_config.NumberColumn(
                f"Average ({currency})",
                format=currency_format(currency),
            ),
            "latest": st.column_config.NumberColumn(
                f"Latest ({currency})",
                format=currency_format(currency),
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
        "completed",
        "marketplace",
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
        "bid_count",
        "start_price",
        "final_price",
        "tax_amount",
        "gross_price",
        "verdict",
        "auction_url",
    ]

    st.dataframe(
        table[display_columns],
        hide_index=True,
        width="stretch",
        column_config={
            "completed": st.column_config.TextColumn(
                "Completed"
            ),
            "marketplace": st.column_config.TextColumn(
                "Marketplace"
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
            "bid_count": st.column_config.NumberColumn(
                "Bids",
                format="%d",
            ),
            "start_price": st.column_config.NumberColumn(
                f"Start ({currency})",
                format=currency_format(currency),
            ),
            "final_price": st.column_config.NumberColumn(
                f"Hammer ({currency})",
                format=currency_format(currency),
            ),
            "tax_amount": st.column_config.NumberColumn(
                f"Tax ({currency})",
                format=currency_format(currency),
            ),
            "gross_price": st.column_config.NumberColumn(
                f"Gross ({currency})",
                format=currency_format(currency),
            ),
            "verdict": st.column_config.TextColumn(
                "Verdict"
            ),
            "auction_url": st.column_config.LinkColumn(
                "Auction",
                display_text="Open",
            ),
        },
    )


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
    st.title("📈 Pressing Analytics")
    st.caption(
        "Discogs-style completed-sale history using actual "
        "auction results. Currencies remain completely separate."
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

    if options.empty:
        st.warning(
            "No priced and dated catalog-number sales "
            "match the search."
        )
        return

    option_keys = [
        (
            str(row.catalog_number),
            str(row.media_type),
            str(row.currency),
        )
        for row in options.itertuples()
    ]

    option_labels = {
        key: (
            f"{key[0]}  ·  "
            f"{key[1]}  ·  "
            f"{key[2]}  ·  "
            f"{int(row.sale_count)} sale(s)"
        )
        for key, row in zip(
            option_keys,
            options.itertuples(),
            strict=True,
        )
    }

    selected_catalog, selected_media, currency = (
        st.selectbox(
            "Exact pressing / catalog number",
            options=option_keys,
            format_func=lambda key: option_labels[key],
        )
    )

    selected_option = options[
        (options["catalog_number"] == selected_catalog)
        & (options["media_type"] == selected_media)
        & (options["currency"] == currency)
    ].iloc[0]

    heading_columns = st.columns(
        [3, 1, 1, 1]
    )

    heading_columns[0].subheader(
        selected_catalog
    )
    heading_columns[0].caption(
        f"{selected_media} · {currency}"
    )
    heading_columns[1].metric(
        "Stored sales",
        int(selected_option["sale_count"]),
    )
    heading_columns[2].metric(
        "Marketplaces",
        int(
            selected_option["marketplace_count"]
        ),
    )
    heading_columns[3].metric(
        "Sellers",
        int(selected_option["seller_count"]),
    )

    filter_values = load_filter_values(
        selected_catalog,
        currency,
    )

    minimum_date, maximum_date = load_date_bounds(
        selected_catalog,
        currency,
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
        currency=currency,
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
        currency,
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
            currency,
        )

    with distribution_tab:
        render_price_distribution(
            sales,
            currency,
        )

    with activity_tab:
        render_monthly_activity(
            sales,
        )

    with summary_tab:
        render_marketplace_summary(
            sales,
            currency,
        )

    with sales_tab:
        render_comparable_sales(
            sales,
            currency,
        )

    st.divider()

    st.caption(
        "Only exact effective catalog-number matches are included. "
        "Variants such as MR3166 and MR316-6 remain separate until "
        "they are manually normalized in Collector Review."
    )


if __name__ == "__main__":
    main()
