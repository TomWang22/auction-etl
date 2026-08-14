"""Streamlit page for user-triggered multisource auction ingestion."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPOSITORY_ROOT),
    )

from auction_etl.services.auction_ingest_job import (  # noqa: E402
    PLANNED_SOURCES,
    get_latest_status,
    start_job,
    tail_log,
)


RUNNING_STATES = {
    "queued",
    "running",
}

SOURCE_ICONS = {
    "waiting":
        "⚪",
    "running":
        "🔵",
    "observed":
        "🟡",
    "done":
        "✅",
    "failed":
        "❌",
}


def format_timestamp(
    value: Any,
) -> str:
    """Format persisted ISO timestamps for display."""

    if not value:
        return "—"

    try:
        parsed = datetime.fromisoformat(
            str(value)
        )
    except ValueError:
        return str(value)

    return parsed.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def render_source_progress(
    status: dict[str, Any] | None,
) -> None:
    """Show the three multisource ingestion states."""

    source_states = (
        status.get(
            "source_states",
            {},
        )
        if status
        else {}
    )

    columns = st.columns(
        len(
            PLANNED_SOURCES
        )
    )

    for column, source in zip(
        columns,
        PLANNED_SOURCES,
        strict=True,
    ):
        state = str(
            source_states.get(
                source,
                "waiting",
            )
        )

        icon = SOURCE_ICONS.get(
            state,
            "⚪",
        )

        with column:
            st.markdown(
                f"### {icon} {source}"
            )
            st.caption(
                state.replace(
                    "_",
                    " ",
                ).title()
            )


def render_status(
    status: dict[str, Any],
) -> None:
    """Render persisted background-job state."""

    state = str(
        status.get(
            "status",
            "unknown",
        )
    )

    progress = int(
        status.get(
            "progress",
            0,
        )
    )

    phase = str(
        status.get(
            "phase",
            "Waiting",
        )
    )

    message = str(
        status.get(
            "message",
            "",
        )
    )

    st.progress(
        max(
            0,
            min(
                progress,
                100,
            ),
        )
        / 100.0,
        text=(
            f"{progress}% — {phase}"
        ),
    )

    render_source_progress(
        status
    )

    if state in RUNNING_STATES:
        st.info(
            message,
            icon="⏳",
        )

    elif state == "completed":
        st.success(
            "Auction ingestion completed. "
            "The refreshed auction data is ready.",
            icon="✅",
        )

    elif state == "failed":
        st.error(
            message,
            icon="❌",
        )

    else:
        st.info(
            message or "Waiting.",
        )

    metadata_columns = st.columns(
        3
    )

    with metadata_columns[0]:
        st.metric(
            "State",
            state.title(),
        )

    with metadata_columns[1]:
        st.metric(
            "Started",
            format_timestamp(
                status.get(
                    "started_at"
                )
            ),
        )

    with metadata_columns[2]:
        st.metric(
            "Finished",
            format_timestamp(
                status.get(
                    "finished_at"
                )
            ),
        )

    latest_output = status.get(
        "last_output"
    )

    if latest_output:
        st.caption(
            f"Latest: {latest_output}"
        )

    with st.expander(
        "Live ingestion log",
        expanded=(
            state == "failed"
        ),
    ):
        log_text = tail_log(
            status.get(
                "log_path"
            ),
            line_count=120,
        )

        if log_text:
            st.code(
                log_text,
                language="text",
            )
        else:
            st.caption(
                "The job has not emitted log output yet."
            )


st.set_page_config(
    page_title="Ingest New Auctions",
    page_icon="🔄",
    layout="wide",
)

st.title(
    "🔄 Ingest New Auctions"
)

st.caption(
    "Run one background refresh across eBay, Buyee, and Gripsweat. "
    "You can leave this page while it runs."
)

status = get_latest_status()

is_running = bool(
    status
    and status.get(
        "status"
    )
    in RUNNING_STATES
)

button_label = (
    "Auction ingestion is running…"
    if is_running
    else "Ingest new auctions across all sites"
)

button_clicked = st.button(
    button_label,
    type="primary",
    use_container_width=True,
    disabled=is_running,
)

if button_clicked:
    try:
        status = start_job()
    except Exception as exc:
        st.error(
            f"Could not start auction ingestion: {exc}",
            icon="❌",
        )
    else:
        st.session_state[
            "auction_ingest_started_job"
        ] = status.get(
            "job_id"
        )

        st.toast(
            "Auction ingestion started.",
            icon="🔄",
        )

        st.rerun()

st.divider()

if status is None:
    render_source_progress(
        None
    )

    st.info(
        "No auction-ingestion job has been started yet. "
        "Press the button above when you want fresh marketplace data.",
        icon="ℹ️",
    )

else:
    render_status(
        status
    )

    job_id = str(
        status.get(
            "job_id",
            "",
        )
    )

    state = str(
        status.get(
            "status",
            "",
        )
    )

    notification_key = (
        "auction_ingest_last_notification"
    )

    notification_value = (
        f"{job_id}:{state}"
    )

    if (
        state == "completed"
        and st.session_state.get(
            notification_key
        )
        != notification_value
    ):
        st.toast(
            "New auctions are ready.",
            icon="✅",
        )

        st.session_state[
            notification_key
        ] = notification_value

    elif (
        state == "failed"
        and st.session_state.get(
            notification_key
        )
        != notification_value
    ):
        st.toast(
            "Auction ingestion failed. Open the log for details.",
            icon="❌",
        )

        st.session_state[
            notification_key
        ] = notification_value

    if state in RUNNING_STATES:
        st.caption(
            "This page refreshes automatically every 2 seconds."
        )

        time.sleep(
            2
        )

        st.rerun()

st.divider()

st.caption(
    "This control uses scripts/run_auction_refresh_on_demand.sh. "
    "It does not rerun the old release/finalization chain."
)
