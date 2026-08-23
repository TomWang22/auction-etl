"""Latest-auction refresh controls, filters, and formatted reports."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from auction_etl.auth.context import AccountContext  # noqa: E402
from auction_etl.auth.streamlit_auth import (  # noqa: E402
    render_account_menu,
    require_authenticated_account,
)

from auction_etl.reporting.recent_ingestion import (  # noqa: E402
    CSVExportOptions,
    QueryFilters,
    REPORT_PRESETS,
    available_report_columns,
    connect,
    get_media_types,
    get_report_rows,
    write_formatted_csv,
)
from auction_etl.services.control_plane_refresh import (  # noqa: E402
    enqueue_refresh_via_control_plane,
)
from auction_etl.services.refresh_jobs import (  # noqa: E402
    build_refresh_engine,
    coordination_schema_ready,
    get_latest_refresh_job,
    list_refresh_jobs,
    refresh_job_to_ui_status,
)
from app.navigation import render_navigation
import time


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    (
        "postgresql://auction:auction@"
        "127.0.0.1:5544/auction_warehouse"
    ),
)
CONTROL_PLANE_URL = os.environ.get(
    "AUCTION_CONTROL_PLANE_URL",
    "",
).strip()
REFRESH_SIGNING_SECRET = os.environ.get(
    "AUCTION_REFRESH_SIGNING_SECRET",
    "",
).strip()

MEDIA_CONFIG_PATH = (
    ROOT / "config/report_media_types.json"
)

FRIENDLY_HEADERS = {
    "marketplace": "Marketplace",
    "listing_id": "Listing ID",
    "first_seen_at": "First seen",
    "last_seen_at": "Last seen",
    "ended_at": "Auction ended",
    "seller": "Seller",
    "artist": "Artist",
    "title": "Title",
    "display_media_type": "Media type",
    "effective_catalog_number": "Catalog number",
    "effective_region": "Region",
    "effective_disc_count": "Disc count",
    "bid_count": "Bids",
    "final_price": "Final price",
    "shipping_price": "Shipping",
    "tax_amount": "Tax",
    "gross_price": "Gross price",
    "currency": "Currency",
    "effective_verdict": "Verdict",
    "effective_importance_score": "Importance",
    "auction_url": "Auction URL",
}


def read_json(
    path: Path,
    default: dict[str, Any],
) -> dict[str, Any]:
    """Read a JSON object without crashing the page."""
    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(payload, dict):
            return payload
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        pass

    return dict(default)


def write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Atomically write a JSON object."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


@st.cache_data(ttl=30)
def load_schema_contract(
    database_url: str,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
]:
    """Load available report fields and represented media types."""
    with connect(database_url) as connection:
        columns = available_report_columns(
            connection
        )
        media_types = get_media_types(
            connection
        )

    return columns, media_types


@st.cache_data(ttl=10)
def load_report(
    database_url: str,
    columns: tuple[str, ...],
    marketplaces: tuple[str, ...],
    media_types: tuple[str, ...],
    added_from: date | None,
    added_to: date | None,
    ended_from: date | None,
    ended_to: date | None,
    recent_days: int | None,
    seller: str | None,
    search: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Load filtered reporting rows."""
    filters = QueryFilters(
        marketplaces=marketplaces,
        media_types=media_types,
        added_from=added_from,
        added_to=added_to,
        ended_from=ended_from,
        ended_to=ended_to,
        recent_days=recent_days,
        seller=seller or None,
        search=search or None,
        limit=limit,
    )

    with connect(database_url) as connection:
        return get_report_rows(
            connection,
            columns=columns,
            filters=filters,
        )


@st.cache_resource
def refresh_engine(
    database_url: str,
):
    """Return the durable refresh coordination engine."""
    return build_refresh_engine(
        database_url
    )


@st.cache_data(ttl=2)
def load_refresh_status(
    database_url: str,
    account_id: str,
) -> dict[str, Any]:
    """Load the latest durable refresh state from PostgreSQL."""
    try:
        engine = refresh_engine(
            database_url
        )

        if not coordination_schema_ready(
            engine
        ):
            return {
                "state": "idle",
                "phase": "not-installed",
                "message": (
                    "Durable refresh coordination has not been "
                    "migrated into this database yet."
                ),
                "coordination_ready": False,
            }

        job = get_latest_refresh_job(
            engine,
            account_id=account_id,
        )
    except Exception as exc:
        return {
            "state": "unavailable",
            "phase": "database",
            "message": (
                "Durable refresh status is unavailable: "
                f"{exc}"
            ),
            "coordination_ready": False,
        }

    if job is None:
        return {
            "state": "idle",
            "phase": "idle",
            "message": "No durable refresh job has been queued.",
            "coordination_ready": True,
        }

    status = refresh_job_to_ui_status(
        job
    )
    status[
        "coordination_ready"
    ] = True

    return status


def enqueue_refresh_job(
    account_context: AccountContext,
) -> tuple[dict[str, Any], bool]:
    """Create or reuse one durable refresh through Vercel."""
    return enqueue_refresh_via_control_plane(
        base_url=CONTROL_PLANE_URL,
        signing_secret=REFRESH_SIGNING_SECRET,
        account_context=account_context,
    )



MARKETPLACE_PROGRESS = (
    ("buyee", "Buyee"),
    ("ebay", "eBay"),
    ("gripsweat", "Gripsweat"),
)


def marketplace_progress_states(
    status: dict[str, Any],
) -> dict[str, str]:
    """Return normalized live marketplace progress."""

    defaults = {
        key: "waiting"
        for key, _label
        in MARKETPLACE_PROGRESS
    }

    raw_states = status.get(
        "marketplace_states"
    )

    if isinstance(
        raw_states,
        dict,
    ):
        for key in defaults:
            value = str(
                raw_states.get(
                    key,
                    defaults[key],
                )
            ).casefold()

            if value in {
                "waiting",
                "running",
                "done",
                "failed",
                "unavailable",
            }:
                defaults[
                    key
                ] = value

        return defaults

    overall_state = str(
        status.get(
            "state",
            "",
        )
    ).casefold()

    if overall_state in {
        "complete",
        "completed",
        "success",
        "succeeded",
    }:
        return {
            key: "done"
            for key in defaults
        }

    return defaults


def render_marketplace_progress(
    status: dict[str, Any],
) -> None:
    """Render live sequential marketplace progress."""

    labels = {
        "waiting": (
            "⚪",
            "Waiting",
        ),
        "running": (
            "🟡",
            "Running",
        ),
        "done": (
            "✅",
            "Complete",
        ),
        "failed": (
            "❌",
            "Failed",
        ),
        "unavailable": (
            "⚠️",
            "Unavailable",
        ),
    }

    states = marketplace_progress_states(
        status
    )

    st.subheader(
        "Latest refresh"
    )

    columns = st.columns(
        len(
            MARKETPLACE_PROGRESS
        )
    )

    for column, (
        key,
        label,
    ) in zip(
        columns,
        MARKETPLACE_PROGRESS,
        strict=True,
    ):
        icon, state_label = labels[
            states[key]
        ]

        column.markdown(
            f"### {icon} {label}"
        )
        column.caption(
            state_label
        )

st.set_page_config(
    page_title="Latest Auction Refresh",
    page_icon="↻",
    layout="wide",
)
ACCOUNT_CONTEXT = require_authenticated_account(
    refresh_engine(
        DATABASE_URL
    )
)
render_account_menu(
    ACCOUNT_CONTEXT
)
render_navigation(current_page="pages/3_Latest_Auction_Refresh.py")

st.title("Latest Auction Refresh")
st.caption(
    "Inspect recent additions, launch one guarded ingestion round, "
    "filter collector data, and create formatted exports."
)

status = load_refresh_status(
    DATABASE_URL,
    str(ACCOUNT_CONTEXT.account_id),
)

status_columns = st.columns(4)

status_columns[0].metric(
    "Job state",
    str(status.get("state", "idle")).upper(),
)
status_columns[1].metric(
    "Phase",
    str(status.get("phase", "—")),
)

summary = status.get("summary")

if isinstance(summary, dict):
    marketplaces = summary.get(
        "marketplaces",
        {},
    )
    buyee = marketplaces.get(
        "buyee",
        {},
    )
    ebay = marketplaces.get(
        "ebay",
        {},
    )

    status_columns[2].metric(
        "Latest new Buyee",
        int(
            buyee.get(
                "newly_ingested",
                0,
            )
        ),
    )
    status_columns[3].metric(
        "Latest new eBay",
        int(
            ebay.get(
                "newly_ingested",
                0,
            )
        ),
    )
else:
    status_columns[2].metric(
        "Latest new Buyee",
        "—",
    )
    status_columns[3].metric(
        "Latest new eBay",
        "—",
    )

st.info(
    str(
        status.get(
            "message",
            "No status message is available.",
        )
    )
)

render_marketplace_progress(
    status
)

trigger = status.get("trigger")

if trigger:
    st.caption(
        "Latest trigger: "
        + str(trigger).upper()
        + ". Refresh ownership and progress are stored in PostgreSQL."
    )

refresh_tab, report_tab, history_tab = st.tabs(
    (
        "Refresh controls",
        "Browse & export",
        "Run history",
    )
)

with refresh_tab:
    st.subheader("Safe refresh controls")

    st.write(
        "Inspection is read-only. A new ingestion round performs "
        "one fresh FaceRecords eBay crawl, parses and normalizes "
        "that cohort, and guarded-ingests only identities that are "
        "new to the warehouse."
    )

    job_running = (
        str(
            status.get(
                "state",
                "",
            )
        ).lower()
        in {
            "queued",
            "running",
        }
    )

    control_columns = st.columns(2)

    if control_columns[0].button(
        "Inspect recent ingestion",
        type="secondary",
        disabled=False,
        width="stretch",
    ):
        st.cache_data.clear()
        st.rerun()

    confirmation = control_columns[1].text_input(
        "Type RUN to enable a new ingestion round",
        key="refresh_confirmation",
    )

    refresh_enabled = (
        confirmation.strip().upper() == "RUN"
        and not job_running
        and bool(
            status.get(
                "coordination_ready",
                False,
            )
        )
    )

    if control_columns[1].button(
        "Run Buyee, eBay, and Gripsweat",
        type="primary",
        disabled=not refresh_enabled,
        width="stretch",
    ):
        try:
            queued_status, created = (
                enqueue_refresh_job(
                    ACCOUNT_CONTEXT,
                )
            )
        except Exception as exc:
            st.error(
                "Could not queue the durable refresh job: "
                f"{exc}"
            )
        else:
            st.cache_data.clear()

            if created:
                st.success(
                    "The refresh was queued for the "
                    "persistent marketplace worker."
                )
            else:
                st.info(
                    "An active durable refresh already exists; "
                    "showing that job instead."
                )

            status = queued_status

            time.sleep(
                0.25
            )
            st.rerun()

    st.warning(
        "The ingestion round never prunes globally. "
        "The web process only queues work; the persistent worker "
        "owns marketplace execution."
    )

    if st.button(
        "Reload job status",
    ):
        st.cache_data.clear()
        st.rerun()

    durable_job_id = status.get(
        "job_id"
    )

    if durable_job_id:
        st.caption(
            "Durable refresh job: "
            + str(
                durable_job_id
            )
        )

    if job_running:
        time.sleep(
            2
        )
        st.rerun()


with report_tab:
    if not ACCOUNT_CONTEXT.is_system_admin:
        st.info(
            "Browse & export remains system-admin only until the "
            "reporting query itself is account-scoped. Refresh controls "
            "and refresh history are already account-owned."
        )
    else:
        st.subheader("Auction data browser")

        available_columns, represented_types = (
            load_schema_contract(
                DATABASE_URL
            )
        )

        media_config = read_json(
            MEDIA_CONFIG_PATH,
            {
                "allowed_media_types": list(
                    represented_types
                ),
            },
        )

        configured_types = [
            str(value)
            for value in media_config.get(
                "allowed_media_types",
                [],
            )
            if str(value).strip()
        ]

        with st.expander(
            "Allowed media classifications",
            expanded=False,
        ):
            edited_types = st.text_area(
                "One media type per line",
                value="\n".join(
                    configured_types
                ),
                height=220,
            )

            if st.button(
                "Save allowed media types",
            ):
                normalized_types = sorted(
                    {
                        line.strip().upper()
                        for line in edited_types.splitlines()
                        if line.strip()
                    }
                )

                write_json(
                    MEDIA_CONFIG_PATH,
                    {
                        "allowed_media_types": normalized_types,
                    },
                )

                st.success(
                    "Allowed media types were saved."
                )
                st.cache_data.clear()

        filter_columns = st.columns(3)

        marketplaces = filter_columns[0].multiselect(
            "Marketplace",
            options=("buyee", "ebay"),
            default=("buyee", "ebay"),
        )

        all_media_options = sorted(
            set(configured_types)
            | set(represented_types)
        )

        selected_media_types = filter_columns[1].multiselect(
            "Media type",
            options=all_media_options,
            default=[],
            help=(
                "Leave empty to include every represented media type."
            ),
        )

        recent_additions = filter_columns[2].checkbox(
            "Recent additions",
            value=True,
        )

        recent_days = (
            filter_columns[2].number_input(
                "Added within the last N days",
                min_value=0,
                max_value=3_650,
                value=7,
                step=1,
                disabled=not recent_additions,
            )
            if recent_additions
            else None
        )

        date_columns = st.columns(2)

        use_added_dates = date_columns[0].checkbox(
            "Use exact first-seen date range",
            value=False,
        )

        if use_added_dates:
            default_added_start = (
                date.today()
                - timedelta(days=30)
            )

            added_range = date_columns[0].date_input(
                "First-seen range",
                value=(
                    default_added_start,
                    date.today(),
                ),
            )

            if isinstance(
                added_range,
                tuple,
            ):
                added_from, added_to = added_range
            else:
                added_from = added_range
                added_to = added_range
        else:
            added_from = None
            added_to = None

        use_ended_dates = date_columns[1].checkbox(
            "Use auction-ended date range",
            value=False,
        )

        if use_ended_dates:
            default_ended_start = (
                date.today()
                - timedelta(days=90)
            )

            ended_range = date_columns[1].date_input(
                "Auction-ended range",
                value=(
                    default_ended_start,
                    date.today(),
                ),
            )

            if isinstance(
                ended_range,
                tuple,
            ):
                ended_from, ended_to = ended_range
            else:
                ended_from = ended_range
                ended_to = ended_range
        else:
            ended_from = None
            ended_to = None

        search_columns = st.columns(3)

        seller = search_columns[0].text_input(
            "Seller contains",
        )
        search = search_columns[1].text_input(
            "Search title, artist, seller, listing, or catalog",
        )
        row_limit = search_columns[2].number_input(
            "Maximum report rows",
            min_value=1,
            max_value=100_000,
            value=5_000,
            step=100,
        )

        preset = st.selectbox(
            "Report field preset",
            options=tuple(REPORT_PRESETS),
            index=0,
        )

        preset_fields = [
            field
            for field in REPORT_PRESETS[preset]
            if field in available_columns
        ]

        selected_fields = st.multiselect(
            "Report fields",
            options=available_columns,
            default=preset_fields,
            help=(
                "Column order follows the selected order shown here."
            ),
        )

        required_fields = [
            "marketplace",
            "listing_id",
        ]

        for required_field in reversed(
            required_fields
        ):
            if required_field not in selected_fields:
                selected_fields.insert(
                    0,
                    required_field,
                )

        if st.button(
            "Load report",
            type="primary",
            width="stretch",
        ):
            rows = load_report(
                DATABASE_URL,
                tuple(selected_fields),
                tuple(marketplaces),
                tuple(selected_media_types),
                added_from,
                added_to,
                ended_from,
                ended_to,
                (
                    int(recent_days)
                    if recent_additions
                    and recent_days is not None
                    else None
                ),
                seller,
                search,
                int(row_limit),
            )

            st.session_state[
                "latest_auction_rows"
            ] = rows
            st.session_state[
                "latest_auction_fields"
            ] = list(selected_fields)

        rows = st.session_state.get(
            "latest_auction_rows",
            [],
        )
        fields = st.session_state.get(
            "latest_auction_fields",
            selected_fields,
        )

        if rows:
            frame = pd.DataFrame(rows)

            metric_columns = st.columns(4)
            metric_columns[0].metric(
                "Matching rows",
                len(frame),
            )
            metric_columns[1].metric(
                "Buyee",
                int(
                    (
                        frame.get(
                            "marketplace",
                            pd.Series(dtype=str),
                        )
                        == "buyee"
                    ).sum()
                ),
            )
            metric_columns[2].metric(
                "eBay",
                int(
                    (
                        frame.get(
                            "marketplace",
                            pd.Series(dtype=str),
                        )
                        == "ebay"
                    ).sum()
                ),
            )

            recent_count = 0

            if "first_seen_source" in frame:
                recent_count = int(
                    (
                        frame["first_seen_source"]
                        == "new-only-export"
                    ).sum()
                )

            metric_columns[3].metric(
                "Explicit recent additions",
                recent_count,
            )

            st.dataframe(
                frame,
                width="stretch",
                hide_index=True,
            )

            media_column = None

            for candidate in (
                "display_media_type",
                "effective_media_type",
                "media_type",
            ):
                if candidate in frame:
                    media_column = candidate
                    break

            if media_column:
                breakdown = (
                    frame[media_column]
                    .fillna("UNKNOWN")
                    .astype(str)
                    .value_counts()
                    .rename_axis("Media type")
                    .reset_index(name="Rows")
                )

                st.subheader("Media-type breakdown")

                breakdown_columns = st.columns(
                    (1, 2)
                )

                breakdown_columns[0].dataframe(
                    breakdown,
                    width="stretch",
                    hide_index=True,
                )
                breakdown_columns[1].bar_chart(
                    breakdown.set_index(
                        "Media type"
                    )
                )

            st.subheader("Formatted export")

            export_columns = st.columns(4)

            delimiter_label = export_columns[0].selectbox(
                "Delimiter",
                options=(
                    "Comma",
                    "Tab",
                    "Semicolon",
                    "Pipe",
                ),
            )
            quote_style = export_columns[1].selectbox(
                "Quoting",
                options=(
                    "minimal",
                    "all",
                    "nonnumeric",
                    "none",
                ),
            )
            date_format = export_columns[2].selectbox(
                "Date format",
                options=(
                    "iso",
                    "date",
                    "us",
                    "eu",
                ),
            )
            decimal_places = export_columns[3].number_input(
                "Decimal places",
                min_value=0,
                max_value=8,
                value=2,
                step=1,
            )

            option_columns = st.columns(3)

            include_bom = option_columns[0].checkbox(
                "Excel-compatible UTF-8 BOM",
                value=True,
            )
            friendly_headers = option_columns[1].checkbox(
                "Friendly column headings",
                value=True,
            )
            null_text = option_columns[2].text_input(
                "Null value text",
                value="",
            )

            delimiter_values = {
                "Comma": ",",
                "Tab": "\t",
                "Semicolon": ";",
                "Pipe": "|",
            }

            csv_payload = write_formatted_csv(
                rows,
                columns=fields,
                options=CSVExportOptions(
                    delimiter=delimiter_values[
                        delimiter_label
                    ],
                    quote_style=quote_style,
                    include_bom=include_bom,
                    date_format=date_format,
                    decimal_places=int(
                        decimal_places
                    ),
                    null_text=null_text,
                ),
                header_aliases=(
                    FRIENDLY_HEADERS
                    if friendly_headers
                    else None
                ),
            )

            extension = (
                "tsv"
                if delimiter_label == "Tab"
                else "csv"
            )

            filename = (
                "auction-report-"
                + datetime.now().strftime(
                    "%Y%m%d-%H%M%S"
                )
                + f".{extension}"
            )

            st.download_button(
                "Download formatted CSV",
                data=csv_payload,
                file_name=filename,
                mime=(
                    "text/tab-separated-values"
                    if extension == "tsv"
                    else "text/csv"
                ),
                width="stretch",
            )

            with st.expander(
                "Manual and effective classification fields",
                expanded=False,
            ):
                classification_fields = [
                    column
                    for column in available_columns
                    if column.startswith(
                        ("manual_", "effective_")
                    )
                ]

                st.write(
                    ", ".join(
                        classification_fields
                    )
                )

                st.caption(
                    "Manual overrides remain managed by Collector Review. "
                    "This page reports both manual and effective values."
                )

                if hasattr(
                    st,
                    "page_link",
                ):
                    st.page_link(
                        "app/collector_review.py",
                        label="Open Collector Review",
                    )
        else:
            st.info(
                "Choose filters and press Load report."
            )

with history_tab:
    st.subheader("Refresh and report history")

    history_rows: list[dict[str, Any]] = []

    try:
        coordination_engine = refresh_engine(
            DATABASE_URL
        )

        if coordination_schema_ready(
            coordination_engine
        ):
            for job in list_refresh_jobs(
                coordination_engine,
                account_id=str(ACCOUNT_CONTEXT.account_id),
                limit=50,
            ):
                history_rows.append(
                    {
                        "Category": "Refresh",
                        "Name": str(
                            job["id"]
                        ),
                        "Modified": (
                            job.get(
                                "updated_at"
                            )
                            or job.get(
                                "requested_at"
                            )
                        ),
                        "Path": (
                            "PostgreSQL ops.refresh_job"
                        ),
                    }
                )
    except Exception:
        pass

    for parent, category in (
        (
            ROOT / "reports/recent-ingestion",
            "Report",
        ),
        (
            ROOT / "exports/new-only",
            "New-only export",
        ),
    ):
        if not parent.is_dir():
            continue

        for path in parent.iterdir():
            if not path.is_dir():
                continue

            history_rows.append(
                {
                    "Category": category,
                    "Name": path.name,
                    "Modified": datetime.fromtimestamp(
                        path.stat().st_mtime
                    ),
                    "Path": str(
                        path.relative_to(ROOT)
                    ),
                }
            )

    history_rows.sort(
        key=lambda row: (
            row["Modified"].timestamp()
            if isinstance(
                row.get(
                    "Modified"
                ),
                datetime,
            )
            else 0.0
        ),
        reverse=True,
    )

    if history_rows:
        st.dataframe(
            pd.DataFrame(
                history_rows[:100]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info(
            "No refresh history is available."
        )
