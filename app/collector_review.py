"""Database-driven Auction Collector Review."""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

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

from app.collector_analytics_editor import (
    render_collector_analytics_editor,
)

from app.collector_export import render_export_toolbar

from app.collector_review_support import (
    as_boolean,
    clean_text,
    derive_pressing_token,
    derive_sale_type,
    is_missing,
    listing_identity,
    listing_option_label,
    safe_float,
    safe_int,
)
from auction_etl.reporting.main_review_integration import (
    integrate_recent_activity,
    load_gripsweat_records,
)

from auction_etl.reporting.main_review_integration import _concat_unique_columns
from app.navigation import render_navigation


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

MEDIA_OPTIONS = (
    "Automatic / unset",
    "LP",
    "EP_7_INCH",
    "SINGLE_12_INCH",
    "CD",
    "CD_BOX_SET",
    "CASSETTE",
    "DVD",
    "VHS",
    "OTHER",
)

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

CONDITION_OPTIONS = (
    "Automatic / unset",
    "M",
    "NM",
    "EX",
    "E",
    "VG+",
    "VG",
    "G+",
    "G",
    "F",
    "P",
)

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
    for candidate in (
        f"collector_{column_name}",
        column_name,
    ):
        if candidate in row.index:
            value = row[candidate]

            if not is_missing(value):
                return value

    return None


@st.cache_data(
    ttl=2,
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
              AND lower(btrim(visible.marketplace)) =
                  lower(btrim(r.marketplace))
              AND visible.listing_id = r.listing_id
        )
        """
    )

    visible_query = text(
        """
        SELECT
            lower(btrim(marketplace)) AS marketplace,
            listing_id
        FROM account.auction_listing
        WHERE account_id = CAST(:account_id AS uuid)
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
        visible_identities = pd.read_sql_query(
            visible_query,
            connection,
            params=parameters,
        )

    gripsweat_records = load_gripsweat_records(
        database_url=DATABASE_URL,
    )

    if not gripsweat_records.empty:
        gripsweat_records = gripsweat_records.copy()
        gripsweat_records["marketplace"] = (
            gripsweat_records["marketplace"]
            .astype(str)
            .str.strip()
            .str.lower()
        )
        visible_identities["marketplace"] = (
            visible_identities["marketplace"]
            .astype(str)
            .str.strip()
            .str.lower()
        )
        gripsweat_records = gripsweat_records.merge(
            visible_identities,
            how="inner",
            on=[
                "marketplace",
                "listing_id",
            ],
        )

    if gripsweat_records.empty:
        combined = native_records
    else:
        combined = _concat_unique_columns(
            [
                native_records,
                gripsweat_records,
            ],
            ignore_index=True,
            sort=False,
        )

    return prepare_records(
        combined
    )



def prepare_records(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Create consistent display and filter columns."""
    frame = dataframe.copy()

    frame["marketplace"] = coalesce_series(
        frame,
        ("marketplace",),
    ).map(clean_text)

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
        ("artist",),
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
            ("opening_at", "started_at"),
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
    ).fillna(0)

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
        lambda row: derive_pressing_token(
            override=row["pressing_override"],
            catalog_number=row["catalog_display"],
            title=row["title"],
        ),
        axis=1,
    )

    frame["pressing_group_key"] = frame.apply(
        lambda row: "|".join(
            value
            for value in (
                re.sub(
                    r"[^A-Z0-9]",
                    "",
                    row["artist_display"].upper(),
                ),
                row["media_display"].upper(),
                row["pressing_token"],
            )
            if value
        ),
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
        ),
        axis=1,
    )

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

    return st.selectbox(
        label,
        dynamic_options,
        index=dynamic_options.index(
            selected
        ),
        key=key,
    )


def tri_state_selectbox(
    label: str,
    current_value: Any,
    *,
    key: str,
) -> str:
    """Render an Automatic, Yes, or No selector."""
    if is_missing(current_value):
        selected = "Automatic / unset"
    elif as_boolean(current_value):
        selected = "Yes"
    else:
        selected = "No"

    return st.selectbox(
        label,
        TRI_STATE_OPTIONS,
        index=TRI_STATE_OPTIONS.index(
            selected
        ),
        key=key,
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
    "media_type": "collector_filter_media_type",
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
    matches = identities[
        identities == identity
    ]

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
        _request_clear_listing_identity()
        selected = None

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
        "media_type",
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
    "AUCTION": "Auction",
    "AUCTION_STYLE": "Auction",
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
) -> tuple[pd.DataFrame, str]:
    """Render sidebar filters and return matching rows."""
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

        media_types = [
            "all",
            *sorted(
                value
                for value in marketplace_rows[
                    "media_display"
                ].dropna().unique()
                if value
            ),
        ]

        media_type = st.selectbox(
            "Media type",
            media_types,
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

    return (
        filtered.reset_index(
            drop=True
        ),
        str(page_size),
    )



def render_metrics(
    dataframe: pd.DataFrame,
    page_number: int,
    page_count: int,
) -> None:
    """Render result-set metrics."""
    metrics = st.columns(6)

    metrics[0].metric(
        "Total matches",
        len(dataframe),
    )

    metrics[1].metric(
        "Listings shown",
        min(
            len(dataframe),
            int(
                st.session_state.get(
                    "_page_size",
                    250,
                )
            ),
        ),
    )

    metrics[2].metric(
        "Page",
        f"{page_number} / {page_count}",
    )

    metrics[3].metric(
        "Sellers shown",
        dataframe["seller"]
        .replace("", pd.NA)
        .nunique(),
    )

    metrics[4].metric(
        "In collection",
        int(
            dataframe[
                "in_collection_display"
            ].sum()
        ),
    )

    metrics[5].metric(
        "Pressing groups",
        dataframe[
            "pressing_group_key"
        ]
        .replace("", pd.NA)
        .nunique(),
    )



def _aggrid_selected_identity(
    response: Any,
) -> str | None:
    """Extract one stable identity from an AG Grid response."""
    selected_rows = getattr(
        response,
        "selected_rows",
        None,
    )

    if (
        selected_rows is None
        and isinstance(response, dict)
    ):
        selected_rows = response.get(
            "selected_rows"
        )

    if selected_rows is None:
        return None

    if isinstance(
        selected_rows,
        pd.DataFrame,
    ):
        if selected_rows.empty:
            return None

        value = selected_rows.iloc[0].get(
            "__identity"
        )

        return clean_text(value) or None

    if isinstance(
        selected_rows,
        dict,
    ):
        return (
            clean_text(
                selected_rows.get(
                    "__identity"
                )
            )
            or None
        )

    if isinstance(
        selected_rows,
        (list, tuple),
    ):
        if not selected_rows:
            return None

        first_row = selected_rows[0]

        if isinstance(first_row, dict):
            return (
                clean_text(
                    first_row.get(
                        "__identity"
                    )
                )
                or None
            )

    try:
        selected_frame = pd.DataFrame(
            selected_rows
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        selected_frame.empty
        or "__identity"
        not in selected_frame.columns
    ):
        return None

    return (
        clean_text(
            selected_frame.iloc[0][
                "__identity"
            ]
        )
        or None
    )


def render_listing_table(
    dataframe: pd.DataFrame,
    *,
    key: str,
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
            "__selected":
                identities.eq(
                    selected_identity
                ),
            "Marketplace":
                dataframe["marketplace"],
            "Listing ID":
                dataframe["listing_id"],
            "Title":
                dataframe["title"],
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
                dataframe[
                    "bid_count_display"
                ].astype(int),
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

    selected_row_rule = JsCode(
        """
        function(params) {
            return Boolean(
                params.data
                && params.data.__selected
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

    grid_options = {
        "columnDefs": [
            {
                "field": "__identity",
                "hide": True,
            },
            {
                "field": "__selected",
                "hide": True,
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
        "rowHeight": 40,
        "headerHeight": 44,
        "tooltipShowDelay": 150,
        "getRowId": row_identity,
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

    response = AgGrid(
        display,
        gridOptions=grid_options,
        height=560,
        theme="streamlit",
        update_on=[
            "selectionChanged",
        ],
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        show_toolbar=False,
        server_sync_strategy="server_wins",
        custom_css=custom_css,
        key=key,
    )

    identity = _aggrid_selected_identity(
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



def render_listing_editor(
    dataframe: pd.DataFrame,
    account_context: AccountContext,
) -> None:
    """Render the editor for the stable selected identity."""
    selected = _selected_listing_row(
        dataframe
    )

    if selected is None:
        st.caption(
            "Select any table row or use the sidebar search to open its details."
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
        f"editor:{identity}:{revision}:"
    )

    st.divider()

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
            "Clear",
            key=f"clear_listing:{identity}",
            width="stretch",
            help="Close the current editor selection.",
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

    summary_columns[5].metric(
        "Bids",
        int(
            selected[
                "bid_count_display"
            ]
        ),
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
                    "Pressing key: "
                    f"{selected['pressing_token'] or 'not assigned'}"
                ),
            )
        )
    )

    with st.form(
        key=(
            f"collector_editor:"
            f"{identity}:{revision}"
        ),
        clear_on_submit=False,
    ):
        st.subheader(
            "Pressing identification"
        )

        core_columns = st.columns(5)

        with core_columns[0]:
            manual_media_type = optional_selectbox(
                "Manual media type",
                MEDIA_OPTIONS,
                collector_value(
                    selected,
                    "manual_media_type",
                ),
                key=(
                    key_prefix
                    + "manual_media_type"
                ),
            )

        with core_columns[1]:
            manual_catalog_number = st.text_input(
                "Catalog / matrix number",
                value=clean_text(
                    collector_value(
                        selected,
                        "manual_catalog_number",
                    )
                ),
                key=(
                    key_prefix
                    + "manual_catalog_number"
                ),
            )

        with core_columns[2]:
            manual_region = optional_selectbox(
                "Manual region",
                REGION_OPTIONS,
                collector_value(
                    selected,
                    "manual_region",
                ),
                key=(
                    key_prefix
                    + "manual_region"
                ),
            )

        with core_columns[3]:
            manual_disc_count = st.number_input(
                "Disc count",
                min_value=0,
                max_value=100,
                value=(
                    safe_int(
                        collector_value(
                            selected,
                            "manual_disc_count",
                        )
                    )
                    or 0
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

        with core_columns[4]:
            manual_pressing_type = optional_selectbox(
                "Pressing type",
                PRESSING_TYPE_OPTIONS,
                collector_value(
                    selected,
                    "manual_pressing_type",
                ),
                key=(
                    key_prefix
                    + "manual_pressing_type"
                ),
            )

        manual_pressing_group = st.text_input(
            "Pressing group",
            value=clean_text(
                collector_value(
                    selected,
                    "manual_pressing_group",
                )
            ),
            placeholder=(
                "Optional canonical matrix/catalog identity"
            ),
            help=(
                "Listings with the same normalized value are grouped "
                "even when their titles differ."
            ),
            key=(
                key_prefix
                + "manual_pressing_group"
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
                collector_value(
                    selected,
                    "manual_sale_type",
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

        st.subheader(
            "Edition and completeness"
        )

        completeness_columns_1 = st.columns(5)

        with completeness_columns_1[0]:
            manual_bulk_lot = tri_state_selectbox(
                "Bulk lot",
                collector_value(
                    selected,
                    "manual_bulk_lot",
                ),
                key=(
                    key_prefix
                    + "manual_bulk_lot"
                ),
            )

        with completeness_columns_1[1]:
            manual_obi = tri_state_selectbox(
                "Obi",
                collector_value(
                    selected,
                    "manual_obi",
                ),
                key=(
                    key_prefix
                    + "manual_obi"
                ),
            )

        with completeness_columns_1[2]:
            manual_insert = tri_state_selectbox(
                "Insert",
                collector_value(
                    selected,
                    "manual_insert_present",
                ),
                key=(
                    key_prefix
                    + "manual_insert"
                ),
            )

        with completeness_columns_1[3]:
            manual_poster = tri_state_selectbox(
                "Poster",
                collector_value(
                    selected,
                    "manual_poster_present",
                ),
                key=(
                    key_prefix
                    + "manual_poster"
                ),
            )

        with completeness_columns_1[4]:
            manual_rental = tri_state_selectbox(
                "Rental",
                collector_value(
                    selected,
                    "manual_rental",
                ),
                key=(
                    key_prefix
                    + "manual_rental"
                ),
            )

        completeness_columns_2 = st.columns(3)

        with completeness_columns_2[0]:
            manual_sticker = tri_state_selectbox(
                "Sticker",
                collector_value(
                    selected,
                    "manual_sticker",
                ),
                key=(
                    key_prefix
                    + "manual_sticker"
                ),
            )

        with completeness_columns_2[1]:
            manual_sealed = tri_state_selectbox(
                "Sealed",
                collector_value(
                    selected,
                    "manual_sealed",
                ),
                key=(
                    key_prefix
                    + "manual_sealed"
                ),
            )

        with completeness_columns_2[2]:
            st.text_input(
                "Observed condition",
                value=clean_text(
                    selected.get(
                        "condition_text",
                        "",
                    )
                )
                or "Not available",
                disabled=True,
            )

        st.subheader(
            "Condition and assessment"
        )

        verdict_columns = st.columns(4)

        with verdict_columns[0]:
            manual_condition_media = optional_selectbox(
                "Media condition",
                CONDITION_OPTIONS,
                collector_value(
                    selected,
                    "manual_condition_media",
                ),
                key=(
                    key_prefix
                    + "manual_condition_media"
                ),
            )

        with verdict_columns[1]:
            manual_condition_cover = optional_selectbox(
                "Cover condition",
                CONDITION_OPTIONS,
                collector_value(
                    selected,
                    "manual_condition_cover",
                ),
                key=(
                    key_prefix
                    + "manual_condition_cover"
                ),
            )

        with verdict_columns[2]:
            manual_importance_score = st.number_input(
                "Importance score",
                min_value=0,
                max_value=100,
                value=(
                    safe_int(
                        collector_value(
                            selected,
                            "manual_importance_score",
                        )
                    )
                    or 0
                ),
                step=1,
                key=(
                    key_prefix
                    + "manual_importance_score"
                ),
            )

        with verdict_columns[3]:
            manual_verdict = optional_selectbox(
                "Manual verdict",
                VERDICT_OPTIONS,
                collector_value(
                    selected,
                    "manual_verdict",
                ),
                key=(
                    key_prefix
                    + "manual_verdict"
                ),
            )

        manual_completeness_notes = st.text_area(
            "Completeness / pressing notes",
            value=clean_text(
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

        submitted = st.form_submit_button(
            "Save collector record",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    payload = {
        "manual_media_type":
            nullable_choice(
                manual_media_type
            ),
        "manual_catalog_number":
            nullable_text(
                manual_catalog_number
            ),
        "manual_region":
            nullable_choice(
                manual_region
            ),
        "manual_disc_count":
            (
                int(manual_disc_count)
                if manual_disc_count > 0
                else None
            ),
        "manual_pressing_type":
            nullable_choice(
                manual_pressing_type
            ),
        "manual_pressing_group":
            nullable_text(
                manual_pressing_group
            ),
        "manual_sale_type":
            nullable_choice(
                manual_sale_type
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
        "manual_bulk_lot":
            tri_state_value(
                manual_bulk_lot
            ),
        "manual_obi":
            tri_state_value(
                manual_obi
            ),
        "manual_insert_present":
            tri_state_value(
                manual_insert
            ),
        "manual_poster_present":
            tri_state_value(
                manual_poster
            ),
        "manual_rental":
            tri_state_value(
                manual_rental
            ),
        "manual_sticker":
            tri_state_value(
                manual_sticker
            ),
        "manual_sealed":
            tri_state_value(
                manual_sealed
            ),
        "manual_condition_media":
            nullable_choice(
                manual_condition_media
            ),
        "manual_condition_cover":
            nullable_choice(
                manual_condition_cover
            ),
        "manual_importance_score":
            (
                int(
                    manual_importance_score
                )
                if manual_importance_score > 0
                else None
            ),
        "manual_verdict":
            nullable_choice(
                manual_verdict
            ),
        "manual_completeness_notes":
            nullable_text(
                manual_completeness_notes
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

    set_notification(
        (
            "Collector record saved for "
            f"{marketplace} {listing_id}. "
            "The selected editor was refreshed."
        )
    )

    load_records.clear()
    st.rerun()


def render_pressing_groups(
    dataframe: pd.DataFrame,
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

    st.dataframe(
        groups[
            [
                "Matrix",
                "Artist",
                "Media",
                "Listings",
                "Marketplaces",
                "Sellers",
                "Minimum USD",
                "Median USD",
                "Maximum USD",
                "In_collection",
                "Latest sale",
            ]
        ],
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

try:
    records = load_records(str(ACCOUNT_CONTEXT.account_id))
    records = integrate_recent_activity(records)
except Exception as error:
    st.error(
        f"Could not load marketplace listings: {error}"
    )
    st.stop()

filtered_records, page_size_text = (
    apply_filters(
        records
    )
)

page_size = int(
    page_size_text
)

st.session_state[
    "_page_size"
] = page_size

render_listing_jump(
    filtered_records,
    page_size,
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

render_metrics(
    filtered_records,
    page_number,
    page_count,
)

tabs = st.tabs(
    (
        "Listings",
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
            filtered_records,
            ACCOUNT_CONTEXT,
        )

with tabs[1]:
    st.header(
        "Equivalent pressing comparison"
    )

    st.caption(
        "Listings are grouped using pressing-group details, catalog/matrix number, artist, and media type."
    )

    render_pressing_groups(
        filtered_records
    )

with tabs[2]:
    st.header(
        "Data status"
    )

    render_update_status(
        records
    )


# collector-analytics-editor:start
with tabs[3]:
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
