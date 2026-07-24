"""Human-in-the-loop auction collector review UI."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import text

from auction_etl.database.session import engine


DATABASE_URL_LABEL = "auction_warehouse"

VERDICTS = (
    "",
    "STRONG_INTEREST",
    "WATCH",
    "REFERENCE_ONLY",
    "PASS",
    "BULK_REVIEW",
    "LOW_PRIORITY_REISSUE",
)

MEDIA_TYPES = (
    "",
    "LP",
    "2LP",
    "3LP",
    "4LP",
    "5LP",
    "6LP",
    "7LP",
    "8LP",
    "10LP",
    "12LP",
    "EP_7_INCH",
    "12_INCH_SINGLE",
    "CD",
    "2CD",
    "3CD",
    "4CD",
    "5CD",
    "CD_BOX_SET",
    "CD_DVD_SET",
    "CASSETTE",
    "CASSETTE_BOX_SET",
    "DVD",
    "VHS",
    "LASERDISC",
    "REEL_TO_REEL",
    "BOOK",
    "MEMORABILIA",
    "MIXED_MEDIA",
    "OTHER",
)

REGIONS = (
    "",
    "Japan",
    "Hong Kong",
    "Taiwan",
    "Korea",
    "Malaysia",
    "Singapore",
    "China",
    "United States",
    "United Kingdom",
    "Europe",
    "Other",
)

TRI_STATE_OPTIONS = {
    "Automatic / unset": None,
    "Yes": True,
    "No": False,
}

PURCHASE_STATUSES = (
    "",
    "WATCHING",
    "CONSIDERING",
    "BID_PLANNED",
    "PURCHASED",
    "PASSED",
    "MISSED",
)


def initialize_schema() -> None:
    """Create purchase tracking storage without changing collector tables."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS warehouse.auction_purchase_review (
            marketplace text NOT NULL,
            listing_id text NOT NULL,
            purchase_status text,
            target_price numeric(14, 2),
            purchase_price numeric(14, 2),
            purchase_currency text,
            purchased_at timestamptz,
            purchase_notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (marketplace, listing_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_auction_purchase_review_status
        ON warehouse.auction_purchase_review (
            purchase_status
        )
        """,
    )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def query_dataframe(
    statement: str,
    parameters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a query and return a dataframe."""
    with engine.connect() as connection:
        return pd.read_sql_query(
            text(statement),
            connection,
            params=parameters or {},
        )


def execute_statement(
    statement: str,
    parameters: dict[str, Any],
) -> None:
    """Execute one transactional statement."""
    with engine.begin() as connection:
        connection.execute(
            text(statement),
            parameters,
        )


def display_value(value: Any) -> str:
    """Return a consistent string for Streamlit and PyArrow."""
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return format(value, "f")

    return str(value)


def normalize_text(value: Any) -> str:
    """Return a safe editable string."""
    if value is None or pd.isna(value):
        return ""

    return str(value)


def normalize_integer(value: Any) -> int | None:
    """Return a safe integer."""
    if value is None or pd.isna(value) or value == "":
        return None

    return int(value)


def normalize_decimal(value: Any) -> Decimal | None:
    """Return a safe decimal."""
    if value is None or pd.isna(value) or value == "":
        return None

    return Decimal(str(value))


def normalize_boolean(value: Any) -> bool | None:
    """Return a nullable boolean."""
    if value is None or pd.isna(value):
        return None

    return bool(value)


def select_index(
    options: tuple[str, ...],
    value: Any,
) -> int:
    """Return a safe selectbox index."""
    normalized = normalize_text(value)

    try:
        return options.index(normalized)
    except ValueError:
        return 0


def tri_state_label(value: Any) -> str:
    """Convert a nullable boolean to its UI label."""
    normalized = normalize_boolean(value)

    if normalized is True:
        return "Yes"

    if normalized is False:
        return "No"

    return "Automatic / unset"


def parse_purchase_date(value: Any) -> date:
    """Return a date suitable for Streamlit."""
    if value is None or pd.isna(value):
        return date.today()

    if isinstance(value, pd.Timestamp):
        return value.date()

    if isinstance(value, datetime):
        return value.date()

    return date.today()


def load_filter_options() -> dict[str, list[str]]:
    """Load distinct filter choices."""
    dataframe = query_dataframe(
        """
        SELECT
            marketplace,
            seller,
            effective_media_type,
            effective_verdict
        FROM warehouse.auction_collector_effective
        """
    )

    def values(column: str) -> list[str]:
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
        "verdicts": values("effective_verdict"),
    }


def load_results(
    *,
    marketplace: str,
    seller: str,
    verdict: str,
    media_type: str,
    bulk_status: str,
    purchase_status: str,
    missing_only: bool,
    search: str,
    limit: int,
) -> pd.DataFrame:
    """Load filtered collector rows."""
    conditions = ["1 = 1"]
    parameters: dict[str, Any] = {
        "limit": limit,
    }

    if marketplace != "all":
        conditions.append("a.marketplace = :marketplace")
        parameters["marketplace"] = marketplace

    if seller:
        conditions.append("a.seller ILIKE :seller")
        parameters["seller"] = f"%{seller}%"

    if verdict:
        conditions.append(
            "a.effective_verdict = :verdict"
        )
        parameters["verdict"] = verdict

    if media_type:
        conditions.append(
            "a.effective_media_type = :media_type"
        )
        parameters["media_type"] = media_type

    if bulk_status == "bulk":
        conditions.append(
            "COALESCE(a.effective_bulk_lot, false) = true"
        )
    elif bulk_status == "not_bulk":
        conditions.append(
            "COALESCE(a.effective_bulk_lot, false) = false"
        )

    if purchase_status:
        conditions.append(
            "p.purchase_status = :purchase_status"
        )
        parameters["purchase_status"] = purchase_status

    if missing_only:
        conditions.append(
            """
            (
                a.effective_media_type IS NULL
                OR a.effective_catalog_number IS NULL
                OR a.effective_region IS NULL
            )
            """
        )

    if search:
        conditions.append(
            """
            (
                a.title ILIKE :search
                OR a.listing_id ILIKE :search
                OR a.seller ILIKE :search
                OR a.effective_catalog_number ILIKE :search
                OR a.auction_url ILIKE :search
            )
            """
        )
        parameters["search"] = f"%{search}%"

    where_clause = "\nAND ".join(conditions)

    return query_dataframe(
        f"""
        SELECT
            a.marketplace,
            a.listing_id,
            a.ended_at,
            a.seller,
            a.title,
            a.auction_url,
            a.effective_catalog_number,
            a.effective_region,
            a.effective_media_type,
            a.effective_disc_count,
            a.effective_bulk_lot,
            a.effective_obi,
            a.effective_insert_present,
            a.effective_poster_present,
            a.effective_importance_score,
            a.effective_verdict,
            a.gross_price,
            a.currency,
            p.purchase_status,
            p.target_price,
            p.purchase_price
        FROM warehouse.auction_collector_effective AS a
        LEFT JOIN warehouse.auction_purchase_review AS p
          ON p.marketplace = a.marketplace
         AND p.listing_id = a.listing_id
        WHERE {where_clause}
        ORDER BY
            a.ended_at DESC NULLS LAST,
            a.id DESC
        LIMIT :limit
        """,
        parameters,
    )


def load_listing(
    marketplace: str,
    listing_id: str,
) -> dict[str, Any]:
    """Load one complete listing for review."""
    dataframe = query_dataframe(
        """
        SELECT
            a.*,
            p.purchase_status,
            p.target_price,
            p.purchase_price,
            p.purchase_currency,
            p.purchased_at,
            p.purchase_notes
        FROM warehouse.auction_collector_effective AS a
        LEFT JOIN warehouse.auction_purchase_review AS p
          ON p.marketplace = a.marketplace
         AND p.listing_id = a.listing_id
        WHERE a.marketplace = :marketplace
          AND a.listing_id = :listing_id
        LIMIT 1
        """,
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    )

    if dataframe.empty:
        raise ValueError(
            f"Listing not found: {marketplace}/{listing_id}"
        )

    return dataframe.iloc[0].to_dict()


def save_manual_review(
    marketplace: str,
    listing_id: str,
    values: dict[str, Any],
) -> None:
    """Persist manual collector overrides."""
    execute_statement(
        """
        UPDATE warehouse.auction_collector
        SET
            manual_catalog_number = :manual_catalog_number,
            manual_region = :manual_region,
            manual_media_type = :manual_media_type,
            manual_disc_count = :manual_disc_count,
            manual_bulk_lot = :manual_bulk_lot,
            manual_obi = :manual_obi,
            manual_insert_present = :manual_insert_present,
            manual_poster_present = :manual_poster_present,
            manual_rental = :manual_rental,
            manual_sticker = :manual_sticker,
            manual_promo = :manual_promo,
            manual_sealed = :manual_sealed,
            manual_reissue = :manual_reissue,
            manual_first_press = :manual_first_press,
            manual_importance_score = :manual_importance_score,
            manual_verdict = :manual_verdict,
            manual_condition_media = :manual_condition_media,
            manual_condition_cover = :manual_condition_cover,
            manual_completeness_notes = :manual_completeness_notes,
            manual_collector_notes = :manual_collector_notes,
            updated_at = now()
        WHERE marketplace = :marketplace
          AND listing_id = :listing_id
        """,
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
            **values,
        },
    )


def save_purchase_review(
    marketplace: str,
    listing_id: str,
    values: dict[str, Any],
) -> None:
    """Persist purchase planning information."""
    execute_statement(
        """
        INSERT INTO warehouse.auction_purchase_review (
            marketplace,
            listing_id,
            purchase_status,
            target_price,
            purchase_price,
            purchase_currency,
            purchased_at,
            purchase_notes
        )
        VALUES (
            :marketplace,
            :listing_id,
            :purchase_status,
            :target_price,
            :purchase_price,
            :purchase_currency,
            :purchased_at,
            :purchase_notes
        )
        ON CONFLICT (marketplace, listing_id)
        DO UPDATE SET
            purchase_status = EXCLUDED.purchase_status,
            target_price = EXCLUDED.target_price,
            purchase_price = EXCLUDED.purchase_price,
            purchase_currency = EXCLUDED.purchase_currency,
            purchased_at = EXCLUDED.purchased_at,
            purchase_notes = EXCLUDED.purchase_notes,
            updated_at = now()
        """,
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
            **values,
        },
    )


def nullable_text(value: str) -> str | None:
    """Convert blank text to NULL."""
    cleaned = value.strip()
    return cleaned or None


def render_summary(results: pd.DataFrame) -> None:
    """Render compact result metrics."""
    manual_mask = pd.Series(
        False,
        index=results.index,
    )

    columns = (
        "effective_catalog_number",
        "effective_region",
        "effective_media_type",
        "effective_disc_count",
        "effective_verdict",
    )

    for column in columns:
        if column in results:
            manual_mask |= results[column].notna()

    metric_columns = st.columns(6)

    metric_columns[0].metric(
        "Rows",
        len(results),
    )
    metric_columns[1].metric(
        "Sellers",
        results["seller"].nunique(dropna=True),
    )
    metric_columns[2].metric(
        "Bulk lots",
        int(
            results["effective_bulk_lot"]
            .fillna(False)
            .sum()
        ),
    )
    metric_columns[3].metric(
        "Missing media",
        int(
            results["effective_media_type"]
            .isna()
            .sum()
        ),
    )
    metric_columns[4].metric(
        "Purchase tracked",
        int(
            results["purchase_status"]
            .notna()
            .sum()
        ),
    )
    metric_columns[5].metric(
        "Visible",
        len(results),
    )


def render_result_table(
    results: pd.DataFrame,
) -> tuple[str, str] | None:
    """Render searchable results and return the selected key."""
    if results.empty:
        st.warning("No listings match the current filters.")
        return None

    table = results.copy()

    table["ended"] = pd.to_datetime(
        table["ended_at"],
        errors="coerce",
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    table["price"] = table.apply(
        lambda row: (
            f"{row['gross_price']} {row['currency']}"
            if pd.notna(row["gross_price"])
            else ""
        ),
        axis=1,
    )

    display_columns = [
        "marketplace",
        "listing_id",
        "ended",
        "seller",
        "title",
        "effective_media_type",
        "effective_catalog_number",
        "effective_region",
        "effective_disc_count",
        "effective_bulk_lot",
        "effective_verdict",
        "purchase_status",
        "price",
    ]

    st.dataframe(
        table[display_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "listing_id": st.column_config.TextColumn(
                "Listing ID",
                width="medium",
            ),
            "title": st.column_config.TextColumn(
                "Title",
                width="large",
            ),
            "effective_media_type": st.column_config.TextColumn(
                "Media",
            ),
            "effective_catalog_number": st.column_config.TextColumn(
                "Catalog",
            ),
            "effective_bulk_lot": st.column_config.CheckboxColumn(
                "Bulk",
            ),
            "purchase_status": st.column_config.TextColumn(
                "Purchase",
            ),
        },
    )

    options: list[tuple[str, str]] = [
        (
            str(row.marketplace),
            str(row.listing_id),
        )
        for row in results.itertuples()
    ]

    labels = {
        key: (
            f"{key[0]} · {key[1]} · "
            f"{normalize_text(row.seller)} · "
            f"{normalize_text(row.title)[:100]}"
        )
        for key, row in zip(
            options,
            results.itertuples(),
            strict=True,
        )
    }

    selected = st.selectbox(
        "Select a listing to edit",
        options=options,
        format_func=lambda key: labels[key],
        key="selected_listing_key",
    )

    return selected


def render_automatic_values(row: dict[str, Any]) -> None:
    """Display automatic and effective classification values."""
    with st.expander(
        "Automatic and effective classification",
        expanded=False,
    ):
        automatic = {
            "Automatic catalog": row.get("auto_catalog_number"),
            "Automatic region": row.get("auto_region"),
            "Automatic media": row.get("auto_media_type"),
            "Automatic disc count": row.get("auto_disc_count"),
            "Automatic bulk": row.get("auto_bulk_lot"),
            "Automatic obi": row.get("auto_obi"),
            "Automatic insert": row.get("auto_insert_present"),
            "Automatic poster": row.get("auto_poster_present"),
            "Automatic score": row.get("auto_importance_score"),
            "Automatic verdict": row.get("auto_verdict"),
            "Effective catalog": row.get(
                "effective_catalog_number"
            ),
            "Effective region": row.get("effective_region"),
            "Effective media": row.get("effective_media_type"),
            "Effective disc count": row.get(
                "effective_disc_count"
            ),
            "Effective score": row.get(
                "effective_importance_score"
            ),
            "Effective verdict": row.get("effective_verdict"),
        }

        automatic_rows = [
            {
                "Field": field,
                "Value": display_value(value),
            }
            for field, value in automatic.items()
        ]

        st.dataframe(
            pd.DataFrame(
                automatic_rows,
                columns=["Field", "Value"],
            ),
            hide_index=True,
            width="stretch",
        )


def render_listing_editor(row: dict[str, Any]) -> None:
    """Render the selected listing editor."""
    marketplace = str(row["marketplace"])
    listing_id = str(row["listing_id"])

    st.divider()

    title = normalize_text(row.get("title"))

    st.subheader(title or listing_id)

    identity_columns = st.columns([1, 1, 1, 2])

    identity_columns[0].caption("Marketplace")
    identity_columns[0].write(marketplace)

    identity_columns[1].caption("Listing ID")
    identity_columns[1].write(listing_id)

    identity_columns[2].caption("Seller")
    identity_columns[2].write(
        normalize_text(row.get("seller")) or "—"
    )

    identity_columns[3].caption("Ended")
    identity_columns[3].write(
        normalize_text(row.get("ended_at")) or "—"
    )

    auction_url = normalize_text(row.get("auction_url"))

    if auction_url:
        st.link_button(
            "Open original auction",
            auction_url,
        )

    render_automatic_values(row)

    classification_tab, purchase_tab, raw_tab = st.tabs(
        (
            "Classification",
            "Purchase tracking",
            "Auction data",
        )
    )

    with classification_tab:
        with st.form(
            f"classification_{marketplace}_{listing_id}"
        ):
            st.markdown("#### Core classification")

            core_columns = st.columns(4)

            manual_media_type = core_columns[0].selectbox(
                "Manual media type",
                MEDIA_TYPES,
                index=select_index(
                    MEDIA_TYPES,
                    row.get("manual_media_type"),
                ),
                help=(
                    "Blank preserves the automatic media type."
                ),
            )

            manual_catalog_number = core_columns[1].text_input(
                "Manual catalog / pressing number",
                value=normalize_text(
                    row.get("manual_catalog_number")
                ),
                placeholder="MR3166, 28TR-2062, 817 556-1",
            )

            manual_region = core_columns[2].selectbox(
                "Manual region",
                REGIONS,
                index=select_index(
                    REGIONS,
                    row.get("manual_region"),
                ),
            )

            disc_count_value = normalize_integer(
                row.get("manual_disc_count")
            )

            manual_disc_count = core_columns[3].number_input(
                "Manual disc count",
                min_value=0,
                max_value=999,
                value=disc_count_value or 0,
                step=1,
                help="Use 0 to preserve the automatic value.",
            )

            st.markdown("#### Completeness and edition")

            completeness_columns = st.columns(5)

            manual_bulk_lot_label = completeness_columns[
                0
            ].selectbox(
                "Bulk lot",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_bulk_lot")
                    )
                ),
            )

            manual_obi_label = completeness_columns[
                1
            ].selectbox(
                "Obi",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_obi")
                    )
                ),
            )

            manual_insert_label = completeness_columns[
                2
            ].selectbox(
                "Insert",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_insert_present")
                    )
                ),
            )

            manual_poster_label = completeness_columns[
                3
            ].selectbox(
                "Poster",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_poster_present")
                    )
                ),
            )

            manual_rental_label = completeness_columns[
                4
            ].selectbox(
                "Rental",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_rental")
                    )
                ),
            )

            edition_columns = st.columns(5)

            manual_sticker_label = edition_columns[0].selectbox(
                "Sticker",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_sticker")
                    )
                ),
            )

            manual_promo_label = edition_columns[1].selectbox(
                "Promo / sample",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_promo")
                    )
                ),
            )

            manual_sealed_label = edition_columns[
                2
            ].selectbox(
                "Sealed",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_sealed")
                    )
                ),
            )

            manual_reissue_label = edition_columns[
                3
            ].selectbox(
                "Reissue",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_reissue")
                    )
                ),
            )

            manual_first_press_label = edition_columns[
                4
            ].selectbox(
                "First pressing",
                tuple(TRI_STATE_OPTIONS),
                index=tuple(TRI_STATE_OPTIONS).index(
                    tri_state_label(
                        row.get("manual_first_press")
                    )
                ),
            )

            st.markdown("#### Condition and collector verdict")

            verdict_columns = st.columns(4)

            manual_condition_media = verdict_columns[
                0
            ].text_input(
                "Media condition",
                value=normalize_text(
                    row.get("manual_condition_media")
                ),
                placeholder="M, NM, E, VG+, VG",
            )

            manual_condition_cover = verdict_columns[
                1
            ].text_input(
                "Cover condition",
                value=normalize_text(
                    row.get("manual_condition_cover")
                ),
                placeholder="M, NM, E, VG+, VG",
            )

            existing_score = normalize_integer(
                row.get("manual_importance_score")
            )

            manual_importance_score = verdict_columns[
                2
            ].number_input(
                "Importance score",
                min_value=0,
                max_value=100,
                value=existing_score or 0,
                step=1,
                help="Use 0 to preserve the automatic score.",
            )

            manual_verdict = verdict_columns[3].selectbox(
                "Manual verdict",
                VERDICTS,
                index=select_index(
                    VERDICTS,
                    row.get("manual_verdict"),
                ),
            )

            manual_completeness_notes = st.text_area(
                "Completeness / pressing notes",
                value=normalize_text(
                    row.get("manual_completeness_notes")
                ),
                placeholder=(
                    "Complete with obi, insert and poster; "
                    "rental sticker on rear sleeve..."
                ),
                height=100,
            )

            manual_collector_notes = st.text_area(
                "Collector notes",
                value=normalize_text(
                    row.get("manual_collector_notes")
                ),
                placeholder=(
                    "Why this pressing matters, comparable sales, "
                    "condition concerns, desired ceiling..."
                ),
                height=140,
            )

            save_classification = st.form_submit_button(
                "Save classification",
                type="primary",
                width="stretch",
            )

        if save_classification:
            save_manual_review(
                marketplace,
                listing_id,
                {
                    "manual_catalog_number": nullable_text(
                        manual_catalog_number
                    ),
                    "manual_region": nullable_text(
                        manual_region
                    ),
                    "manual_media_type": nullable_text(
                        manual_media_type
                    ),
                    "manual_disc_count": (
                        manual_disc_count
                        if manual_disc_count > 0
                        else None
                    ),
                    "manual_bulk_lot": TRI_STATE_OPTIONS[
                        manual_bulk_lot_label
                    ],
                    "manual_obi": TRI_STATE_OPTIONS[
                        manual_obi_label
                    ],
                    "manual_insert_present": TRI_STATE_OPTIONS[
                        manual_insert_label
                    ],
                    "manual_poster_present": TRI_STATE_OPTIONS[
                        manual_poster_label
                    ],
                    "manual_rental": TRI_STATE_OPTIONS[
                        manual_rental_label
                    ],
                    "manual_sticker": TRI_STATE_OPTIONS[
                        manual_sticker_label
                    ],
                    "manual_promo": TRI_STATE_OPTIONS[
                        manual_promo_label
                    ],
                    "manual_sealed": TRI_STATE_OPTIONS[
                        manual_sealed_label
                    ],
                    "manual_reissue": TRI_STATE_OPTIONS[
                        manual_reissue_label
                    ],
                    "manual_first_press": TRI_STATE_OPTIONS[
                        manual_first_press_label
                    ],
                    "manual_importance_score": (
                        manual_importance_score
                        if manual_importance_score > 0
                        else None
                    ),
                    "manual_verdict": nullable_text(
                        manual_verdict
                    ),
                    "manual_condition_media": nullable_text(
                        manual_condition_media
                    ),
                    "manual_condition_cover": nullable_text(
                        manual_condition_cover
                    ),
                    "manual_completeness_notes": nullable_text(
                        manual_completeness_notes
                    ),
                    "manual_collector_notes": nullable_text(
                        manual_collector_notes
                    ),
                },
            )

            st.success(
                f"Saved classification for {listing_id}."
            )
            st.rerun()

    with purchase_tab:
        with st.form(
            f"purchase_{marketplace}_{listing_id}"
        ):
            st.markdown("#### Purchase decision")

            purchase_columns = st.columns(4)

            purchase_status = purchase_columns[0].selectbox(
                "Purchase status",
                PURCHASE_STATUSES,
                index=select_index(
                    PURCHASE_STATUSES,
                    row.get("purchase_status"),
                ),
            )

            target_price = purchase_columns[1].number_input(
                "Target / maximum price",
                min_value=0.0,
                value=float(
                    normalize_decimal(
                        row.get("target_price")
                    )
                    or Decimal("0")
                ),
                step=1.0,
            )

            purchase_price = purchase_columns[2].number_input(
                "Actual purchase price",
                min_value=0.0,
                value=float(
                    normalize_decimal(
                        row.get("purchase_price")
                    )
                    or Decimal("0")
                ),
                step=1.0,
            )

            default_currency = (
                normalize_text(
                    row.get("purchase_currency")
                )
                or normalize_text(row.get("currency"))
                or "USD"
            )

            purchase_currency = purchase_columns[
                3
            ].text_input(
                "Purchase currency",
                value=default_currency,
            )

            purchase_date = st.date_input(
                "Purchase date",
                value=parse_purchase_date(
                    row.get("purchased_at")
                ),
            )

            purchase_notes = st.text_area(
                "Purchase notes",
                value=normalize_text(
                    row.get("purchase_notes")
                ),
                placeholder=(
                    "Bought through Buyee, proxy fees excluded; "
                    "waiting on warehouse arrival..."
                ),
                height=140,
            )

            save_purchase = st.form_submit_button(
                "Save purchase tracking",
                type="primary",
                width="stretch",
            )

        if save_purchase:
            purchased_at = None

            if purchase_status == "PURCHASED":
                purchased_at = datetime.combine(
                    purchase_date,
                    time.min,
                    tzinfo=timezone.utc,
                )

            save_purchase_review(
                marketplace,
                listing_id,
                {
                    "purchase_status": nullable_text(
                        purchase_status
                    ),
                    "target_price": (
                        Decimal(str(target_price))
                        if target_price > 0
                        else None
                    ),
                    "purchase_price": (
                        Decimal(str(purchase_price))
                        if purchase_price > 0
                        else None
                    ),
                    "purchase_currency": nullable_text(
                        purchase_currency
                    ),
                    "purchased_at": purchased_at,
                    "purchase_notes": nullable_text(
                        purchase_notes
                    ),
                },
            )

            st.success(
                f"Saved purchase tracking for {listing_id}."
            )
            st.rerun()

    with raw_tab:
        detail_columns = st.columns(3)

        detail_columns[0].metric(
            "Gross price",
            (
                f"{row.get('gross_price')} "
                f"{normalize_text(row.get('currency'))}"
                if row.get("gross_price") is not None
                else "—"
            ),
        )
        detail_columns[1].metric(
            "Bids",
            normalize_text(row.get("bid_count")) or "—",
        )
        detail_columns[2].metric(
            "Seller sales",
            (
                normalize_text(
                    row.get("seller_total_sales")
                )
                or "—"
            ),
        )

        raw_fields = (
            "start_price",
            "final_price",
            "tax_amount",
            "gross_price",
            "currency",
            "bid_count",
            "auction_duration_days",
            "start_to_finish_multiplier",
            "bids_per_day",
            "condition_text",
            "condition_media",
            "condition_cover",
            "seller_first_sale_at",
            "seller_last_sale_at",
            "seller_average_gross_price",
        )

        raw_rows = [
            {
                "Field": field,
                "Value": display_value(
                    row.get(field)
                ),
            }
            for field in raw_fields
        ]

        st.dataframe(
            pd.DataFrame(
                raw_rows,
                columns=["Field", "Value"],
            ),
            hide_index=True,
            width="stretch",
        )


def main() -> None:
    """Run the Streamlit collector review interface."""
    st.set_page_config(
        page_title="Auction Collector Review",
        page_icon="💿",
        layout="wide",
    )

    initialize_schema()

    st.title("💿 Auction Collector Review")
    st.caption(
        "Search first, select one listing, then edit manual "
        "classification or purchase tracking. Blank manual fields "
        "preserve automatic classifications."
    )

    filter_options = load_filter_options()

    with st.sidebar:
        st.header("Search and filters")

        marketplace = st.selectbox(
            "Marketplace",
            ["all", *filter_options["marketplaces"]],
        )

        search = st.text_input(
            "Search",
            placeholder=(
                "Title, listing ID, catalog number, seller"
            ),
        )

        seller = st.text_input(
            "Seller contains",
        )

        verdict = st.selectbox(
            "Verdict",
            ["", *filter_options["verdicts"]],
        )

        media_type = st.selectbox(
            "Media type",
            ["", *filter_options["media_types"]],
        )

        bulk_status = st.selectbox(
            "Bulk status",
            ("all", "bulk", "not_bulk"),
        )

        purchase_status = st.selectbox(
            "Purchase status",
            PURCHASE_STATUSES,
        )

        missing_only = st.checkbox(
            "Only rows missing core classification",
        )

        limit = st.number_input(
            "Maximum rows",
            min_value=25,
            max_value=5_000,
            value=250,
            step=25,
        )

        st.caption(
            f"Database: {DATABASE_URL_LABEL}"
        )

    results = load_results(
        marketplace=marketplace,
        seller=seller,
        verdict=verdict,
        media_type=media_type,
        bulk_status=bulk_status,
        purchase_status=purchase_status,
        missing_only=missing_only,
        search=search,
        limit=int(limit),
    )

    render_summary(results)

    st.subheader("Search results")

    selected = render_result_table(results)

    if selected is None:
        return

    selected_marketplace, selected_listing_id = selected

    selected_row = load_listing(
        selected_marketplace,
        selected_listing_id,
    )

    render_listing_editor(selected_row)


if __name__ == "__main__":
    main()
