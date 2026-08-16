"""Manage artists included in marketplace refreshes."""

from __future__ import annotations

import html

import streamlit as st

from app.navigation import render_navigation
from auction_etl.services.artist_tracking import (
    MARKETPLACE_LABELS,
    SUPPORTED_MARKETPLACES,
    build_ebay_search_url,
    build_gripsweat_search_url,
    list_tracked_artists,
    remove_artist,
    set_artist_enabled,
    target_preview_url,
    upsert_artist,
)


st.set_page_config(
    page_title="Artists to track",
    page_icon="🎵",
    layout="wide",
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


st.title(
    "🎵 Artists to track"
)

st.write(
    "Choose the artists you care about and where to look for them. "
    "Search URLs are generated automatically."
)

st.caption(
    "Saving an artist changes future marketplace refreshes. "
    "It does not start a refresh immediately."
)

artists = list_tracked_artists()

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
        upsert_artist(
            artist_name,
            selected_marketplace_keys(
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
                    upsert_artist(
                        str(
                            artist[
                                "name"
                            ]
                        ),
                        selected_marketplace_keys(
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
                set_artist_enabled(
                    artist_id,
                    not enabled,
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
                remove_artist(
                    artist_id
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
