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
from app.navigation import render_navigation


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


def parse_timestamp(
    value: Any,
) -> datetime | None:
    """Parse one persisted ISO timestamp."""

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(
                value
            )
        )
    except ValueError:
        return None


def format_timestamp(
    value: Any,
) -> str:
    """Format a persisted ISO timestamp in local time."""

    parsed = parse_timestamp(
        value
    )

    if parsed is None:
        return (
            str(
                value
            )
            if value
            else "—"
        )

    return parsed.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def format_duration(
    started_at: Any,
    finished_at: Any,
) -> str:
    """Format elapsed refresh time for normal users."""

    started = parse_timestamp(
        started_at
    )

    finished = parse_timestamp(
        finished_at
    )

    if (
        started is None
        or finished is None
    ):
        return "—"

    total_seconds = max(
        0,
        int(
            (
                finished
                - started
            ).total_seconds()
        ),
    )

    hours, remainder = divmod(
        total_seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    if hours:
        return (
            f"{hours}h "
            f"{minutes}m "
            f"{seconds}s"
        )

    if minutes:
        return (
            f"{minutes}m "
            f"{seconds}s"
        )

    return f"{seconds}s"



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
    """Keep troubleshooting information secondary to product status."""

    with st.expander(
        "Advanced technical details",
        expanded=False,
    ):
        st.caption(
            "Troubleshooting information. Most users can ignore this section."
        )

        run_details_tab, log_output_tab = st.tabs(
            (
                "Run details",
                "Log output",
            )
        )

        job_id = str(
            status.get(
                "job_id",
                "",
            )
            or ""
        )

        state = str(
            status.get(
                "status",
                "",
            )
            or ""
        )

        phase = str(
            status.get(
                "phase",
                "",
            )
            or ""
        )

        stage = str(
            status.get(
                "stage",
                "",
            )
            or ""
        )

        return_code = status.get(
            "return_code"
        )

        log_path_value = status.get(
            "log_path"
        )

        with run_details_tab:
            detail_columns = st.columns(
                2
            )

            with detail_columns[0]:
                st.caption(
                    "Refresh ID"
                )
                st.write(
                    job_id
                    or "—"
                )

                st.caption(
                    "State"
                )
                st.write(
                    state.replace(
                        "_",
                        " ",
                    ).title()
                    or "—"
                )

                st.caption(
                    "Stage"
                )
                st.write(
                    stage.replace(
                        "_",
                        " ",
                    ).title()
                    or "—"
                )

            with detail_columns[1]:
                st.caption(
                    "Phase"
                )
                st.write(
                    phase
                    or "—"
                )

                st.caption(
                    "Return code"
                )
                st.write(
                    str(
                        return_code
                    )
                    if return_code is not None
                    else "—"
                )

                st.caption(
                    "Log file"
                )
                st.write(
                    str(
                        log_path_value
                    )
                    if log_path_value
                    else "—"
                )

        with log_output_tab:
            log_text = tail_log(
                log_path_value,
                line_count=80,
            )

            if log_text:
                st.caption(
                    "Showing the most recent 80 log lines."
                )

                st.code(
                    log_text,
                    language="text",
                )
            else:
                st.caption(
                    "No technical output is available yet."
                )

            if log_path_value:
                log_path = Path(
                    str(
                        log_path_value
                    )
                )

                if log_path.is_file():
                    full_log = log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    st.download_button(
                        "Download full refresh log",
                        data=full_log,
                        file_name=(
                            f"refresh-{job_id or 'latest'}.log"
                        ),
                        mime="text/plain",
                        key=(
                            "refresh-log-download:"
                            f"{job_id or 'latest'}"
                        ),
                    )



def render_status(
    status: dict[str, Any],
) -> None:
    """Render a clear user-facing refresh summary."""

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
        "Latest refresh"
    )

    if state != "completed":
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
        3
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

    with detail_columns[2]:
        st.caption(
            "Duration"
        )
        st.write(
            format_duration(
                status.get(
                    "started_at"
                ),
                status.get(
                    "finished_at"
                ),
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
render_navigation(current_page="pages/15_Ingest_New_Auctions.py")

st.title(
    "🔄 Refresh Marketplace Sales"
)
st.page_link(
    "pages/16_Artists_to_Track.py",
    label="🎵 See artists currently being tracked",
    help=(
        "Review the artists and marketplace searches "
        "used by refreshes."
    ),
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

job_id = (
    str(
        status.get(
            "job_id",
            "",
        )
    )
    if status
    else ""
)

session_job_key = (
    "auction_ingest_started_job"
)

if (
    is_running
    and job_id
):
    st.session_state[
        session_job_key
    ] = job_id

session_job_id = str(
    st.session_state.get(
        session_job_key,
        "",
    )
    or ""
)

is_session_job = bool(
    job_id
    and session_job_id
    == job_id
)

show_primary_status = bool(
    status
    and (
        is_running
        or is_session_job
    )
)

if is_running:
    button_label = (
        "Marketplace refresh is running…"
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

elif show_primary_status:
    render_status(
        status
    )

else:
    render_source_progress(
        None
    )

    st.info(
        "Ready when you are. Start a refresh to check "
        "all three marketplaces for new sales.",
        icon="ℹ️",
    )

    with st.expander(
        "Previous refresh",
        expanded=False,
    ):
        st.caption(
            "The previous refresh is available for reference."
        )

        render_status(
            status
        )

if status is not None:
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
        is_session_job
        and state == "completed"
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
        is_session_job
        and state == "failed"
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
