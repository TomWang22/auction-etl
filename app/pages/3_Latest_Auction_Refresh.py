"""Latest-auction refresh controls, filters, and formatted reports."""

from __future__ import annotations

import json
import os
import subprocess
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
from app.navigation import render_navigation


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    (
        "postgresql://auction:auction@"
        "127.0.0.1:5544/auction_warehouse"
    ),
)

_state_dir_value = os.environ.get(
    "AUCTION_REFRESH_STATE_DIR"
)

if _state_dir_value:
    _state_dir = Path(
        _state_dir_value
    ).expanduser()

    if not _state_dir.is_absolute():
        _state_dir = ROOT / _state_dir
else:
    _state_dir = (
        ROOT / "logs/latest-refresh"
    )

STATUS_PATH = (
    _state_dir / "status.json"
)
LAUNCHER_PATH = (
    ROOT / "scripts/launch_latest_refresh_job.py"
)
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


def tail_file(
    path: Path,
    lines: int = 100,
) -> str:
    """Return the final lines of a text log."""
    if not path.is_file():
        return ""

    content = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    return "\n".join(
        content[-lines:]
    )


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


def launch_job(
    *,
    inspect_only: bool,
) -> None:
    """Launch a detached refresh or inspection process."""
    command = [
        sys.executable,
        str(LAUNCHER_PATH),
        "--database-url",
        DATABASE_URL,
        "--trigger",
        "ui",
    ]

    if inspect_only:
        command.append(
            "--inspect-only"
        )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = DATABASE_URL
    environment.pop(
        "DOCKER_HOST",
        None,
    )
    environment.pop(
        "DOCKER_CONTEXT",
        None,
    )
    environment.pop(
        "PGOPTIONS",
        None,
    )

    subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


st.set_page_config(
    page_title="Latest Auction Refresh",
    page_icon="↻",
    layout="wide",
)
render_navigation(current_page="pages/3_Latest_Auction_Refresh.py")

st.title("Latest Auction Refresh")
st.caption(
    "Inspect recent additions, launch one guarded ingestion round, "
    "filter collector data, and create formatted exports."
)

status = read_json(
    STATUS_PATH,
    {
        "state": "idle",
        "message": "No UI refresh job has been started.",
    },
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

trigger = status.get("trigger")

if trigger:
    st.caption(
        "Latest trigger: "
        + str(trigger).upper()
        + ". Cron and this page share the same launcher and lock."
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
        str(status.get("state", "")).lower()
        == "running"
    )

    control_columns = st.columns(2)

    if control_columns[0].button(
        "Inspect recent ingestion",
        type="secondary",
        disabled=job_running,
        width="stretch",
    ):
        launch_job(
            inspect_only=True,
        )
        st.success(
            "Inspection started in the background."
        )

    confirmation = control_columns[1].text_input(
        "Type RUN to enable a new ingestion round",
        key="refresh_confirmation",
    )

    refresh_enabled = (
        confirmation.strip().upper() == "RUN"
    )

    if control_columns[1].button(
        "Run Buyee, eBay, and Gripsweat",
        type="primary",
        disabled=not refresh_enabled or job_running,
        width="stretch",
    ):
        launch_job(
            inspect_only=False,
        )
        st.success(
            "The new ingestion round started in the background."
        )

    st.warning(
        "The ingestion round never prunes globally. "
        "It stops before another crawl if staging already contains "
        "un-ingested eBay identities."
    )

    if st.button(
        "Reload job status",
    ):
        st.cache_data.clear()
        st.rerun()

    log_value = status.get(
        "log_path",
    )

    if log_value:
        log_path = Path(
            str(log_value)
        )

        if not log_path.is_absolute():
            log_path = ROOT / log_path

        with st.expander(
            "Latest refresh log",
            expanded=False,
        ):
            st.code(
                tail_file(log_path),
                language="text",
            )

with report_tab:
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

    for parent, category in (
        (
            ROOT / "logs/latest-refresh",
            "Refresh",
        ),
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
        key=lambda row: row["Modified"],
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
