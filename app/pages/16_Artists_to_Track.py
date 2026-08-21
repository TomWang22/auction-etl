"""Manage account-owned artists stored in account.tracked_artist."""

from __future__ import annotations

import html
import os
from datetime import datetime

import streamlit as st

from app.navigation import render_navigation
from auction_etl.auth.context import AccountContext
from auction_etl.auth.streamlit_auth import (
    render_account_menu,
    require_authenticated_account,
)
from auction_etl.services.auction_ingest_job import (
    RUNNING_STATES,
    artist_target_statuses,
    get_latest_status,
    start_job,
)
from auction_etl.services.artist_tracking import (
    MARKETPLACE_LABELS,
    SUPPORTED_MARKETPLACES,
    build_ebay_search_url,
    build_gripsweat_search_url,
    list_account_tracked_artists,
    remove_account_artist,
    set_account_artist_enabled,
    target_preview_url,
    upsert_account_artist,
)
from auction_etl.services.refresh_jobs import build_refresh_engine


st.set_page_config(
    page_title="Artists to track",
    page_icon="🎵",
    layout="wide",
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://auction:auction@127.0.0.1:5544/auction_warehouse",
)
ENGINE = build_refresh_engine(
    DATABASE_URL
)
ACCOUNT_CONTEXT = require_authenticated_account(
    ENGINE
)
render_account_menu(
    ACCOUNT_CONTEXT
)

render_navigation(
    current_page="pages/16_Artists_to_Track.py",
)


def rerun_with_message(
    message: str,
) -> None:
    """Show feedback before rerunning the page."""

    st.toast(
        message
    )

    st.rerun()


def platform_labels(
    artist: dict,
) -> list[str]:
    """Return enabled marketplace names for one artist."""

    targets = artist.get(
        "targets",
        {}
    )

    return [
        MARKETPLACE_LABELS[
            marketplace
        ]
        for marketplace
        in SUPPORTED_MARKETPLACES
        if bool(
            targets.get(
                marketplace,
                {},
            ).get(
                "enabled",
                False,
            )
        )
    ]


def selected_marketplace_keys(
    labels: list[str],
) -> list[str]:
    """Convert product-facing marketplace labels to service keys."""

    reverse = {
        label: key
        for key, label
        in MARKETPLACE_LABELS.items()
    }

    return [
        reverse[
            label
        ]
        for label
        in labels
        if label
        in reverse
    ]


def render_search_link(
    label: str,
    url: str,
) -> None:
    """Render a safe external marketplace search link."""

    safe_label = html.escape(
        label
    )

    safe_url = html.escape(
        url,
        quote=True,
    )

    st.markdown(
        (
            f'<a href="{safe_url}" '
            'target="_blank" '
            'rel="noopener noreferrer">'
            f"{safe_label} ↗"
            "</a>"
        ),
        unsafe_allow_html=True,
    )



def refresh_state_view(
    state: str,
) -> tuple[str, str]:
    """Return product-facing icon and label for one lifecycle state."""

    values = {
        "not_refreshed": (
            "⚪",
            "Not refreshed",
        ),
        "waiting": (
            "⚪",
            "Waiting",
        ),
        "running": (
            "🔵",
            "Running",
        ),
        "done": (
            "✅",
            "Complete",
        ),
        "unavailable": (
            "⚠️",
            "Unavailable",
        ),
        "failed": (
            "🔴",
            "Failed",
        ),
        "observed": (
            "🟡",
            "Legacy status",
        ),
    }

    return values.get(
        state,
        (
            "⚪",
            state.replace(
                "_",
                " ",
            ).title(),
        ),
    )


def format_refresh_time(
    value: object,
) -> str:
    """Format an ISO refresh timestamp in the user's local timezone."""

    if value is None:
        return "Never"

    text = str(
        value
    ).strip()

    if not text:
        return "Never"

    try:
        parsed = datetime.fromisoformat(
            text
        )
    except ValueError:
        return text

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()

    return parsed.strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    ).strip()


def active_artist_target_count(
    artists: list[dict],
) -> int:
    """Return enabled eBay/Gripsweat targets in the current artist model."""

    return sum(
        1
        for artist
        in artists
        if bool(
            artist.get(
                "enabled",
                True,
            )
        )
        for marketplace
        in SUPPORTED_MARKETPLACES
        if bool(
            artist.get(
                "targets",
                {},
            ).get(
                marketplace,
                {},
            ).get(
                "enabled",
                False,
            )
        )
    )


@st.fragment(
    run_every="3s"
)
def render_refresh_workspace(
    account_context: AccountContext,
) -> None:
    """Render account-owned refresh controls and artist coverage."""

    current_artists = list_account_tracked_artists(
        ENGINE,
        account_id=str(account_context.account_id),
    )

    target_count = (
        active_artist_target_count(
            current_artists
        )
    )

    latest = get_latest_status(
        account_id=str(account_context.account_id),
    )

    running = bool(
        latest is not None
        and latest.get(
            "status"
        )
        in RUNNING_STATES
    )

    st.subheader(
        "Refresh tracked artists"
    )

    st.write(
        "Run the same production marketplace refresh used by "
        "Refresh marketplace sales."
    )

    st.caption(
        "eBay and Gripsweat are tracked per artist. "
        "Buyee still refreshes from the authenticated watchlist "
        "and is shown as a global marketplace status."
    )

    if st.button(
        "Refresh tracked artists",
        type="primary",
        use_container_width=True,
        disabled=(
            running
            or target_count == 0
        ),
        key="refresh_tracked_artists",
    ):
        latest = start_job(
            account_id=str(account_context.account_id),
            requested_by_user_id=str(account_context.user_id),
            database_url=DATABASE_URL,
        )

        running = bool(
            latest.get(
                "status"
            )
            in RUNNING_STATES
        )

        st.toast(
            "Production marketplace refresh started.",
            icon="🔄",
        )

    if target_count == 0:
        st.info(
            "Enable at least one artist marketplace before refreshing."
        )

    if latest is None:
        st.caption(
            "No production marketplace refresh has been recorded yet."
        )
    else:
        source_states = latest.get(
            "source_states",
            {},
        )

        if not isinstance(
            source_states,
            dict,
        ):
            source_states = {}

        source_finished = latest.get(
            "source_finished_at",
            {},
        )

        if not isinstance(
            source_finished,
            dict,
        ):
            source_finished = {}

        source_columns = st.columns(
            3
        )

        for column, source in zip(
            source_columns,
            (
                "eBay",
                "Buyee",
                "Gripsweat",
            ),
            strict=True,
        ):
            state = str(
                source_states.get(
                    source,
                    "not_refreshed",
                )
            )

            icon, label = (
                refresh_state_view(
                    state
                )
            )

            with column:
                st.markdown(
                    f"{icon} **{source}**"
                )

                st.caption(
                    label
                )

                finished_at = (
                    source_finished.get(
                        source
                    )
                )

                if finished_at:
                    st.caption(
                        "Finished "
                        + format_refresh_time(
                            finished_at
                        )
                    )

        job_state = str(
            latest.get(
                "status",
                "",
            )
        )

        phase = str(
            latest.get(
                "phase",
                "",
            )
        )

        job_id = str(
            latest.get(
                "job_id",
                "",
            )
        )

        if job_state in RUNNING_STATES:
            st.info(
                (
                    phase
                    or "Marketplace refresh is running."
                )
                + (
                    f" · {job_id[:8]}"
                    if job_id
                    else ""
                ),
                icon="🔄",
            )

        elif job_state == "completed":
            all_done = all(
                source_states.get(
                    source
                )
                == "done"
                for source
                in (
                    "eBay",
                    "Buyee",
                    "Gripsweat",
                )
            )

            if all_done:
                st.success(
                    "All three marketplaces completed.",
                    icon="✅",
                )
            else:
                incomplete = [
                    source
                    for source
                    in (
                        "eBay",
                        "Buyee",
                        "Gripsweat",
                    )
                    if source_states.get(
                        source
                    )
                    != "done"
                ]

                st.warning(
                    "Refresh finished, but not every marketplace "
                    "is green: "
                    + ", ".join(
                        incomplete
                    ),
                    icon="⚠️",
                )

        elif job_state == "failed":
            st.error(
                phase
                or "Marketplace refresh failed.",
                icon="🚨",
            )

    st.markdown(
        "#### Artist refresh coverage"
    )

    if not current_artists:
        st.info(
            "No artists are being tracked yet."
        )

        return

    summaries = artist_target_statuses(
        current_artists,
        latest_status=latest,
    )

    header = st.columns(
        [
            3,
            2,
            2,
        ]
    )

    header[
        0
    ].markdown(
        "**Artist**"
    )

    header[
        1
    ].markdown(
        "**eBay refresh**"
    )

    header[
        2
    ].markdown(
        "**Gripsweat refresh**"
    )

    for artist in current_artists:
        artist_id = str(
            artist.get(
                "id",
                "",
            )
        )

        artist_enabled = bool(
            artist.get(
                "enabled",
                True,
            )
        )

        artist_statuses = summaries.get(
            artist_id,
            {},
        )

        row = st.columns(
            [
                3,
                2,
                2,
            ]
        )

        with row[
            0
        ]:
            st.markdown(
                "**"
                + str(
                    artist.get(
                        "name",
                        artist_id,
                    )
                )
                + "**"
            )

            st.caption(
                "Active"
                if artist_enabled
                else "Paused"
            )

        targets = artist.get(
            "targets",
            {},
        )

        for column_index, marketplace in (
            (
                1,
                "ebay",
            ),
            (
                2,
                "gripsweat",
            ),
        ):
            target = (
                targets.get(
                    marketplace,
                    {},
                )
                if isinstance(
                    targets,
                    dict,
                )
                else {}
            )

            with row[
                column_index
            ]:
                if not bool(
                    target.get(
                        "enabled",
                        False,
                    )
                ):
                    st.caption(
                        "— Not tracked"
                    )

                    continue

                summary = artist_statuses.get(
                    marketplace,
                    {
                        "state":
                            "not_refreshed",
                        "last_refreshed_at":
                            None,
                    },
                )

                state = str(
                    summary.get(
                        "state",
                        "not_refreshed",
                    )
                )

                icon, label = (
                    refresh_state_view(
                        state
                    )
                )

                st.markdown(
                    f"{icon} **{label}**"
                )

                st.caption(
                    "Last refreshed: "
                    + format_refresh_time(
                        summary.get(
                            "last_refreshed_at"
                        )
                    )
                )

                if bool(
                    summary.get(
                        "current_job",
                        False,
                    )
                ):
                    current_job = str(
                        summary.get(
                            "job_id",
                            "",
                        )
                    )

                    if current_job:
                        st.caption(
                            "Current run "
                            + current_job[
                                :8
                            ]
                        )

    st.caption(
        "Artist coverage reflects the artist settings captured "
        "when each production refresh started."
    )


st.title(
    "🎵 Artists to track"
)

st.write(
    "Choose the artists you care about and where to look for them. "
    "Search URLs are generated automatically."
)

st.caption(
    "Artist tracking is stored per account in PostgreSQL. "
    "Use Refresh tracked artists below only when you want to run "
    "this account's production ingestion pipeline."
)

artists = list_account_tracked_artists(
    ENGINE,
    account_id=str(ACCOUNT_CONTEXT.account_id),
)

active_artists = [
    artist
    for artist
    in artists
    if bool(
        artist.get(
            "enabled",
            True,
        )
    )
]

active_targets = sum(
    1
    for artist
    in active_artists
    for target
    in artist.get(
        "targets",
        {},
    ).values()
    if bool(
        target.get(
            "enabled",
            False,
        )
    )
)

metric_columns = st.columns(
    3
)

metric_columns[
    0
].metric(
    "Artists",
    len(
        artists
    ),
)

metric_columns[
    1
].metric(
    "Active",
    len(
        active_artists
    ),
)

metric_columns[
    2
].metric(
    "Marketplace searches",
    active_targets,
)

st.divider()

render_refresh_workspace(
    ACCOUNT_CONTEXT
)

st.divider()

st.subheader(
    "Add an artist"
)

with st.form(
    "add_artist_form",
    clear_on_submit=True,
):
    artist_name = st.text_input(
        "Artist name",
        placeholder="e.g. Faye Wong",
    )

    selected_labels = st.multiselect(
        "Track on",
        options=[
            "eBay",
            "Gripsweat",
        ],
        default=[
            "eBay",
            "Gripsweat",
        ],
    )

    if artist_name.strip():
        st.caption(
            "Search preview"
        )

        preview_columns = st.columns(
            2
        )

        with preview_columns[
            0
        ]:
            st.write(
                "**eBay**"
            )

            render_search_link(
                "Open generated search",
                build_ebay_search_url(
                    artist_name
                ),
            )

        with preview_columns[
            1
        ]:
            st.write(
                "**Gripsweat**"
            )

            render_search_link(
                "Open generated search",
                build_gripsweat_search_url(
                    artist_name
                ),
            )

    submitted = st.form_submit_button(
        "Save artist",
        type="primary",
        use_container_width=True,
    )

if submitted:
    try:
        upsert_account_artist(
            ENGINE,
            account_id=str(ACCOUNT_CONTEXT.account_id),
            user_id=str(ACCOUNT_CONTEXT.user_id),
            name=artist_name,
            marketplaces=selected_marketplace_keys(
                selected_labels
            ),
        )

    except ValueError as error:
        st.error(
            str(
                error
            )
        )

    else:
        rerun_with_message(
            f"{artist_name.strip()} is now tracked."
        )

st.divider()

st.subheader(
    "Currently tracked"
)

if not artists:
    st.info(
        "No artists are being tracked yet."
    )

for artist in artists:
    artist_id = str(
        artist[
            "id"
        ]
    )

    enabled = bool(
        artist.get(
            "enabled",
            True,
        )
    )

    labels = platform_labels(
        artist
    )

    with st.container(
        border=True
    ):
        heading_columns = st.columns(
            [
                5,
                1,
            ]
        )

        with heading_columns[
            0
        ]:
            st.markdown(
                f"### {artist['name']}"
            )

            if labels:
                st.caption(
                    "Tracked on "
                    + ", ".join(
                        labels
                    )
                )

            else:
                st.caption(
                    "No marketplace searches enabled"
                )

        with heading_columns[
            1
        ]:
            if enabled:
                st.markdown(
                    "🟢 **Active**"
                )

            else:
                st.markdown(
                    "⚪ **Paused**"
                )

        targets = artist.get(
            "targets",
            {}
        )

        visible_targets = [
            marketplace
            for marketplace
            in SUPPORTED_MARKETPLACES
            if marketplace
            in targets
            and bool(
                targets[
                    marketplace
                ].get(
                    "enabled",
                    False,
                )
            )
        ]

        if visible_targets:
            marketplace_columns = st.columns(
                len(
                    visible_targets
                )
            )

            for column, marketplace in zip(
                marketplace_columns,
                visible_targets,
                strict=True,
            ):
                with column:
                    target = targets[
                        marketplace
                    ]

                    st.write(
                        "**"
                        + MARKETPLACE_LABELS[
                            marketplace
                        ]
                        + "**"
                    )

                    metadata = target.get(
                        "metadata",
                        {},
                    )

                    context: list[str] = []

                    seller = metadata.get(
                        "seller"
                    )

                    profile = metadata.get(
                        "profile"
                    )

                    if seller:
                        context.append(
                            f"seller: {seller}"
                        )

                    if profile:
                        context.append(
                            f"profile: {profile}"
                        )

                    if context:
                        st.caption(
                            " · ".join(
                                context
                            )
                        )

                    st.caption(
                        "Search: "
                        + str(
                            artist[
                                "query"
                            ]
                        )
                    )

                    render_search_link(
                        (
                            "Open "
                            + MARKETPLACE_LABELS[
                                marketplace
                            ]
                            + " search"
                        ),
                        target_preview_url(
                            artist,
                            marketplace,
                        ),
                    )

        with st.expander(
            "Edit tracking"
        ):
            current_labels = platform_labels(
                artist
            )

            edited_labels = st.multiselect(
                "Track on",
                options=[
                    "eBay",
                    "Gripsweat",
                ],
                default=current_labels,
                key=(
                    "platforms_"
                    + artist_id
                ),
            )

            action_columns = st.columns(
                3
            )

            if action_columns[
                0
            ].button(
                "Save changes",
                key=(
                    "save_"
                    + artist_id
                ),
                use_container_width=True,
            ):
                try:
                    upsert_account_artist(
                        ENGINE,
                        account_id=str(ACCOUNT_CONTEXT.account_id),
                        user_id=str(ACCOUNT_CONTEXT.user_id),
                        name=str(
                            artist[
                                "name"
                            ]
                        ),
                        marketplaces=selected_marketplace_keys(
                            edited_labels
                        ),
                    )

                except ValueError as error:
                    st.error(
                        str(
                            error
                        )
                    )

                else:
                    rerun_with_message(
                        "Tracking updated."
                    )

            if enabled:
                pause_label = "Pause"
            else:
                pause_label = "Resume"

            if action_columns[
                1
            ].button(
                pause_label,
                key=(
                    "toggle_"
                    + artist_id
                ),
                use_container_width=True,
            ):
                set_account_artist_enabled(
                    ENGINE,
                    account_id=str(ACCOUNT_CONTEXT.account_id),
                    user_id=str(ACCOUNT_CONTEXT.user_id),
                    artist_id=artist_id,
                    enabled=not enabled,
                )

                rerun_with_message(
                    (
                        "Artist resumed."
                        if not enabled
                        else "Artist paused."
                    )
                )

            confirm_remove = action_columns[
                2
            ].checkbox(
                "Confirm removal",
                key=(
                    "confirm_remove_"
                    + artist_id
                ),
            )

            if st.button(
                "Remove artist",
                key=(
                    "remove_"
                    + artist_id
                ),
                disabled=not confirm_remove,
            ):
                remove_account_artist(
                    ENGINE,
                    account_id=str(ACCOUNT_CONTEXT.account_id),
                    user_id=str(ACCOUNT_CONTEXT.user_id),
                    artist_id=artist_id,
                )

                rerun_with_message(
                    "Artist removed."
                )

st.divider()

st.subheader(
    "Buyee"
)

with st.container(
    border=True
):
    st.write(
        "**Buyee currently works differently.**"
    )

    st.write(
        "The refresh uses your authenticated Buyee watchlist rather than "
        "running an artist search, so Buyee is not selected per artist here."
    )

    st.markdown(
        (
            '<a href="https://buyee.jp/myorders/watchlist/closed" '
            'target="_blank" '
            'rel="noopener noreferrer">'
            "Open Buyee watchlist ↗"
            "</a>"
        ),
        unsafe_allow_html=True,
    )

st.caption(
    "Artist settings currently live in the application runtime directory. "
    "They can move to PostgreSQL later without changing this workflow."
)
