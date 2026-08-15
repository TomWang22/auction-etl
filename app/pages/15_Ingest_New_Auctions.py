"""Streamlit page for user-triggered marketplace refreshes."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[2]

if str(
    REPOSITORY_ROOT
) not in sys.path:
    sys.path.insert(
        0,
        str(
            REPOSITORY_ROOT
        ),
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
    """Format a persisted ISO timestamp in local time."""

    if not value:
        return "—"

    try:
        parsed = datetime.fromisoformat(
            str(
                value
            )
        )
    except ValueError:
        return str(
            value
        )

    return parsed.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def source_state_label(
    source_state: str,
    overall_state: str,
) -> str:
    """Return concise product copy for one marketplace state."""

    if source_state == "waiting":
        return "Waiting"

    if source_state == "running":
        return "Refreshing"

    if source_state == "done":
        return "Complete"

    if source_state == "failed":
        return "Failed"

    if source_state == "observed":
        if overall_state == "failed":
            return "Reached before failure"

        return "Processing"

    return source_state.replace(
        "_",
        " ",
    ).title()


def render_source_progress(
    status: dict[str, Any] | None,
) -> None:
    """Show one compact status card per marketplace."""

    overall_state = (
        str(
            status.get(
                "status",
                "",
            )
        )
        if status
        else ""
    )

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
                source_state_label(
                    state,
                    overall_state,
                )
            )


def failed_sources(
    status: dict[str, Any],
) -> list[str]:
    """Return marketplace names currently marked failed."""

    source_states = status.get(
        "source_states",
        {},
    )

    return [
        source
        for source in PLANNED_SOURCES
        if source_states.get(
            source
        ) == "failed"
    ]


def render_technical_details(
    status: dict[str, Any],
) -> None:
    """Keep operational details available without dominating the UI."""

    with st.expander(
        "Technical details",
        expanded=False,
    ):
        job_id = status.get(
            "job_id"
        )

        if job_id:
            st.caption(
                f"Refresh ID: {job_id}"
            )

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
                "No technical output is available yet."
            )


def render_status(
    status: dict[str, Any],
) -> None:
    """Render the current persisted background refresh."""

    state = str(
        status.get(
            "status",
            "unknown",
        )
    )

    progress = max(
        0,
        min(
            int(
                status.get(
                    "progress",
                    0,
                )
            ),
            100,
        ),
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

    st.subheader(
        "Refresh status"
    )

    st.progress(
        progress / 100.0,
        text=(
            f"{progress}% — {phase}"
        ),
    )

    render_source_progress(
        status
    )

    if state in RUNNING_STATES:
        st.info(
            "Marketplace data is refreshing in the background. "
            "You can leave this page and come back later.",
            icon="⏳",
        )

    elif state == "completed":
        st.success(
            "Marketplace sales are up to date.",
            icon="✅",
        )

    elif state == "failed":
        sources = failed_sources(
            status
        )

        failure_stage = str(
            status.get(
                "failure_stage",
                "",
            )
        )

        if sources:
            source_text = ", ".join(
                sources
            )

            st.error(
                "The refresh stopped while updating "
                f"{source_text}. You can retry when ready.",
                icon="❌",
            )

        elif failure_stage == "post_processing":
            st.error(
                "Marketplace collection finished, but processing "
                "the refreshed data failed. You can retry when ready.",
                icon="❌",
            )

        elif failure_stage == "verification":
            st.error(
                "Marketplace data was refreshed, but the verification "
                "step did not finish. You can retry when ready.",
                icon="❌",
            )

        elif failure_stage == "finalizing":
            st.error(
                "Marketplace data was refreshed, but the final "
                "processing step did not finish. You can retry when ready.",
                icon="❌",
            )

        elif failure_stage == "starting":
            st.error(
                "The background refresh could not start successfully. "
                "You can retry when ready.",
                icon="❌",
            )

        else:
            st.error(
                "The marketplace refresh did not finish. "
                "You can retry when ready.",
                icon="❌",
            )

        if message:
            st.caption(
                message
            )

    elif message:
        st.info(
            message
        )

    detail_columns = st.columns(
        2
    )

    with detail_columns[0]:
        st.caption(
            "Started"
        )

        st.write(
            format_timestamp(
                status.get(
                    "started_at"
                )
            )
        )

    with detail_columns[1]:
        st.caption(
            "Finished"
        )

        st.write(
            format_timestamp(
                status.get(
                    "finished_at"
                )
            )
        )

    render_technical_details(
        status
    )


def start_refresh() -> dict[str, Any] | None:
    """Start the background refresh and report launch errors."""

    try:
        status = start_job()
    except Exception as exc:
        st.error(
            "Could not start the marketplace refresh. "
            f"{exc}",
            icon="❌",
        )

        return None

    st.session_state[
        "auction_ingest_started_job"
    ] = status.get(
        "job_id"
    )

    st.toast(
        "Marketplace refresh started.",
        icon="🔄",
    )

    return status


st.set_page_config(
    page_title="Refresh Marketplace Sales",
    page_icon="🔄",
    layout="wide",
)

st.title(
    "🔄 Refresh Marketplace Sales"
)

st.caption(
    "Bring in the latest available sales from eBay, Buyee, "
    "and Gripsweat. The refresh continues in the background."
)

status = get_latest_status()

is_running = bool(
    status
    and status.get(
        "status"
    )
    in RUNNING_STATES
)

current_state = (
    str(
        status.get(
            "status",
            "",
        )
    )
    if status
    else ""
)

if is_running:
    button_label = (
        "Marketplace refresh is running…"
    )
elif current_state == "failed":
    button_label = (
        "Retry marketplace refresh"
    )
else:
    button_label = (
        "Refresh marketplace sales"
    )

button_clicked = st.button(
    button_label,
    type="primary",
    use_container_width=True,
    disabled=is_running,
)

if button_clicked:
    started_status = start_refresh()

    if started_status is not None:
        st.rerun()

st.divider()

if status is None:
    render_source_progress(
        None
    )

    st.info(
        "Ready when you are. Start a refresh to check "
        "all three marketplaces for new sales.",
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

    previous_notification = (
        st.session_state.get(
            notification_key
        )
    )

    if (
        state == "completed"
        and previous_notification
        != notification_value
    ):
        st.toast(
            "Marketplace sales are up to date.",
            icon="✅",
        )

        st.session_state[
            notification_key
        ] = notification_value

    elif (
        state == "failed"
        and previous_notification
        != notification_value
    ):
        st.toast(
            "Marketplace refresh stopped before completion.",
            icon="❌",
        )

        st.session_state[
            notification_key
        ] = notification_value

    if state in RUNNING_STATES:
        st.caption(
            "Status updates automatically while the refresh runs."
        )

        time.sleep(
            2
        )

        st.rerun()
