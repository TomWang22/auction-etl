"""Streamlit page for user-triggered marketplace refreshes."""

from __future__ import annotations

import os
import subprocess
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


from auction_etl.auth.context import AccountContext  # noqa: E402
from auction_etl.auth.streamlit_auth import (  # noqa: E402
    render_account_menu,
    require_authenticated_account,
)
from auction_etl.services.control_plane_refresh import (  # noqa: E402
    enqueue_refresh_via_control_plane,
)
from auction_etl.services.refresh_jobs import (  # noqa: E402
    build_refresh_engine,
    coordination_schema_ready,
    get_latest_refresh_job,
    refresh_job_to_ui_status,
)

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

PLANNED_SOURCES = (
    "buyee",
    "ebay",
    "gripsweat",
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
    "unavailable":
        "⚠️",
    "done":
        "✅",
    "failed":
        "❌",
    "unknown":
        "❔",
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

    if source_state == "unavailable":
        return "Unavailable"

    if source_state == "observed":
        if overall_state == "failed":
            return "Reached before failure"

        return "Processing"

    if source_state == "unknown":
        return "Status unavailable"

    return source_state.replace(
        "_",
        " ",
    ).title()


def durable_source_states(
    status: dict[str, Any] | None,
) -> dict[str, str]:
    """Return normalized durable marketplace states."""

    if not status:
        return {}

    raw_states = status.get(
        "source_states"
    )

    if not isinstance(
        raw_states,
        dict,
    ):
        raw_states = status.get(
            "marketplace_states"
        )

    if not isinstance(
        raw_states,
        dict,
    ):
        return {}

    result: dict[str, str] = {}

    for source in PLANNED_SOURCES:
        raw_state = raw_states.get(
            source
        )

        if raw_state is None:
            continue

        state = str(
            raw_state
        ).casefold()

        if state == "skipped":
            state = "unavailable"

        result[
            source
        ] = state

    return result


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

    source_states = durable_source_states(
        status
    )
    summary = (
        status.get("summary", {}).get("marketplaces", {})
        if status
        else {}
    )
    if not isinstance(summary, dict):
        summary = {}
    total_visible = int(status.get("total_visible", 0) or 0) if status else 0
    st.metric("Total visible", f"{total_visible:,}")


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
        raw_state = source_states.get(
            source
        )

        state = (
            str(
                raw_state
            ).casefold()
            if raw_state is not None
            else (
                "waiting"
                if status is None
                else "unknown"
            )
        )

        icon = SOURCE_ICONS.get(
            state,
            "⚪",
        )

        details = summary.get(source, {})
        if not isinstance(details, dict):
            details = {}
        visible_count = int(details.get("visible_count", 0) or 0)
        visible_added = int(details.get("visible_added", 0) or 0)

        with column:
            st.markdown(
                f"### {icon} {source}"
            )
            st.markdown(f"**{visible_count:,} visible**")
            st.caption(f"+{visible_added:,} this refresh")

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

    source_states = durable_source_states(
        status
    )

    return [
        source
        for source in PLANNED_SOURCES
        if source_states.get(
            source
        ) == "failed"
    ]


def unavailable_sources(
    status: dict[str, Any],
) -> list[str]:
    """Return marketplaces unavailable during this refresh."""

    source_states = durable_source_states(
        status
    )

    return [
        source
        for source in PLANNED_SOURCES
        if source_states.get(
            source
        ) == "unavailable"
    ]


def all_sources_done(
    status: dict[str, Any],
) -> bool:
    """Return whether every marketplace completed successfully."""

    source_states = durable_source_states(
        status
    )

    return all(
        source_states.get(
            source
        ) == "done"
        for source in PLANNED_SOURCES
    )


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




def deployment_revision() -> str:
    """Return the deployed Git revision when available."""
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--short=12",
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return "unknown"

    return result.stdout.strip() or "unknown"


def durable_progress(
    status: dict[str, Any],
) -> tuple[int, int]:
    """Return success and execution percentages from durable source states."""
    source_states = durable_source_states(
        status
    )

    states = [
        str(
            source_states.get(
                source,
                "waiting",
            )
        ).casefold()
        for source in PLANNED_SOURCES
    ]

    meaningful_states = {
        "running",
        "observed",
        "unavailable",
        "done",
        "failed",
    }

    if not any(
        state in meaningful_states
        for state in states
    ):
        success = int(
            status.get(
                "progress",
                0,
            )
            or 0
        )
        execution = int(
            status.get(
                "execution_progress",
                0,
            )
            or 0
        )

        return (
            max(
                0,
                min(
                    success,
                    100,
                ),
            ),
            max(
                0,
                min(
                    execution,
                    100,
                ),
            ),
        )

    successful = sum(
        state == "done"
        for state in states
    )

    terminal = sum(
        state
        in {
            "done",
            "unavailable",
            "failed",
        }
        for state in states
    )

    total = len(
        PLANNED_SOURCES
    )

    return (
        int(
            successful
            / total
            * 100
        ),
        int(
            terminal
            / total
            * 100
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

    progress, execution_progress = (
        durable_progress(
            status
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

    st.subheader(
        "Latest refresh"
    )

    st.caption(
        "App revision: "
        f"{deployment_revision()} · "
        f"job={status.get('job_id', 'unknown')} · "
        f"progress={progress} · "
        f"execution={execution_progress}"
    )

    display_phase = phase

    if (
        state == "completed"
        and (
            not display_phase
            or display_phase.casefold()
            == "completed"
        )
    ):
        display_phase = "Completed"

    st.progress(
        progress / 100.0,
        text=(
            f"{progress}% — {display_phase}"
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
        unavailable = unavailable_sources(
            status
        )

        if all_sources_done(
            status
        ):
            st.success(
                "Marketplace sales are up to date.",
                icon="✅",
            )
        elif unavailable:
            source_text = ", ".join(
                unavailable
            )

            st.warning(
                "Refresh finished, but "
                f"{source_text} was unavailable. "
                "Only completed marketplaces are up to date.",
                icon="⚠️",
            )
        else:
            st.warning(
                "Refresh finished, but not every marketplace "
                "reported successful completion.",
                icon="⚠️",
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



@st.cache_resource
def refresh_engine(
    database_url: str,
):
    """Return the durable refresh coordination engine."""
    return build_refresh_engine(
        database_url
    )


@st.cache_data(ttl=2)
def get_latest_status(
    database_url: str,
    account_id: str,
) -> dict[str, Any] | None:
    """Load the latest account-scoped durable refresh."""
    engine = refresh_engine(
        database_url
    )

    if not coordination_schema_ready(
        engine
    ):
        raise RuntimeError(
            "Durable refresh coordination is not installed "
            "in the configured database."
        )

    job = get_latest_refresh_job(
        engine,
        account_id=account_id,
    )

    if job is None:
        return None

    raw_status = refresh_job_to_ui_status(
        job
    )

    result = dict(
        raw_status
    )

    state = str(
        result.get(
            "state",
            result.get(
                "status",
                "",
            ),
        )
    ).casefold()

    result["status"] = {
        "idle": "idle",
        "queued": "queued",
        "running": "running",
        "success": "completed",
        "succeeded": "completed",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "failed",
        "canceled": "failed",
    }.get(
        state,
        state,
    )

    if not result.get(
        "job_id"
    ):
        identifier = result.get(
            "id"
        )

        if identifier is not None:
            result[
                "job_id"
            ] = str(
                identifier
            )

    return result


def tail_log(
    *args: Any,
    **kwargs: Any,
) -> str:
    """Return durable worker details without relying on local log files."""
    del kwargs

    status = (
        args[0]
        if args
        and isinstance(
            args[0],
            dict,
        )
        else {}
    )

    for key in (
        "log",
        "log_text",
        "worker_log",
        "output",
        "error",
        "message",
    ):
        value = status.get(
            key
        )

        if value:
            return str(
                value
            )

    return ""



def start_refresh(
    account_context: AccountContext,
) -> dict[str, Any] | None:
    """Queue or reuse one durable refresh for this account."""
    if not CONTROL_PLANE_URL:
        st.error(
            "Marketplace refresh is not configured: "
            "AUCTION_CONTROL_PLANE_URL is missing.",
            icon="❌",
        )
        return None

    if not REFRESH_SIGNING_SECRET:
        st.error(
            "Marketplace refresh is not configured: "
            "AUCTION_REFRESH_SIGNING_SECRET is missing.",
            icon="❌",
        )
        return None

    try:
        job, created = enqueue_refresh_via_control_plane(
            base_url=CONTROL_PLANE_URL,
            signing_secret=REFRESH_SIGNING_SECRET,
            account_context=account_context,
        )
    except Exception as exc:
        st.error(
            "Could not queue the marketplace refresh. "
            f"{exc}",
            icon="❌",
        )
        return None

    job_id = str(
        job.get(
            "job_id",
            job.get(
                "id",
                "",
            ),
        )
        or ""
    )

    st.session_state[
        "auction_ingest_started_job"
    ] = job_id

    get_latest_status.clear()

    st.toast(
        (
            "Marketplace refresh queued."
            if created
            else
            "A marketplace refresh is already queued or running."
        ),
        icon="🔄",
    )

    result = dict(
        refresh_job_to_ui_status(
            job
        )
    )

    state = str(
        result.get(
            "state",
            result.get(
                "status",
                "",
            ),
        )
    ).casefold()

    result["status"] = {
        "queued": "queued",
        "running": "running",
        "success": "completed",
        "succeeded": "completed",
        "completed": "completed",
        "failed": "failed",
    }.get(
        state,
        state,
    )

    if job_id:
        result[
            "job_id"
        ] = job_id

    return result

st.set_page_config(
    page_title="Refresh Marketplace Sales",
    page_icon="🔄",
    layout="wide",
)
render_navigation(current_page="pages/15_Ingest_New_Auctions.py")


account_context = require_authenticated_account(
    refresh_engine(
        DATABASE_URL
    )
)

render_account_menu(
    account_context
)
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

try:
    status = get_latest_status(
        DATABASE_URL,
        str(
            account_context.account_id
        ),
    )
except Exception as exc:
    status = None

    st.error(
        "Could not load durable marketplace refresh status. "
        f"{exc}",
        icon="❌",
    )
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

button_label = (
    "Marketplace refresh is running…"
    if is_running
    else "Refresh marketplace sales"
)

button_clicked = st.button(
    button_label,
    type="primary",
    use_container_width=True,
    disabled=is_running,
)

if button_clicked:
    started_status = start_refresh(
        account_context
    )

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
        and all_sources_done(
            status
        )
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
        and state == "completed"
        and previous_notification
        != notification_value
    ):
        st.toast(
            "Marketplace refresh finished with warnings.",
            icon="⚠️",
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
