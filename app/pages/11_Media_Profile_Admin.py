"""Audited media-profile administration."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from auction_etl.services.media_profile_admin import (
    apply_profile_changes,
    list_media_types,
    list_profile_audit,
    load_profile_editor,
    preview_profile_changes,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Media Profile Administration",
    page_icon="🧩",
    layout="wide",
)
render_navigation(current_page="pages/11_Media_Profile_Admin.py")


def _engine():
    """Return the warehouse engine."""
    return create_engine(
        os.environ.get(
            "DATABASE_URL",
            (
                "postgresql+psycopg://auction:auction"
                "@127.0.0.1:5544/auction_warehouse"
            ),
        ),
        pool_pre_ping=True,
        future=True,
    )


def main() -> None:
    """Render audited media-profile administration."""
    st.title(
        "Media Profile Administration"
    )

    st.caption(
        "Configure which component fields apply to each medium, "
        "how they are grouped, and their display order."
    )

    st.warning(
        "Media profiles configure the review interface; they do not "
        "assert that any component is REQUIRED or NOT_INCLUDED for "
        "an exact pressing."
    )

    engine = _engine()

    existing_media = list_media_types(
        engine
    )

    selection_options = [
        *existing_media,
        "CREATE_NEW_MEDIA_TYPE",
    ]

    selected = st.selectbox(
        "Media profile",
        options=selection_options,
    )

    if selected == "CREATE_NEW_MEDIA_TYPE":
        media_type = st.text_input(
            "New media-type key",
            placeholder="MINIDISC",
        ).strip().upper()
    else:
        media_type = selected

    if not media_type:
        st.info(
            "Enter a media-type key to continue."
        )
        return

    try:
        rows = load_profile_editor(
            engine,
            media_type,
        )
    except ValueError as error:
        st.error(
            str(
                error
            )
        )
        return

    enabled_count = len(
        [
            row
            for row in rows
            if row[
                "enabled"
            ]
        ]
    )

    metrics = st.columns(
        3
    )

    metrics[0].metric(
        "Media type",
        media_type,
    )

    metrics[1].metric(
        "Available component types",
        len(
            rows
        ),
    )

    metrics[2].metric(
        "Enabled fields",
        enabled_count,
    )

    edited = st.data_editor(
        pd.DataFrame(
            rows
        ),
        key=(
            "media_profile_editor_"
            + media_type
        ),
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_order=[
            "enabled",
            "component_code",
            "display_name",
            "field_group",
            "sort_order",
            "notes",
            "persisted",
        ],
        disabled=[
            "component_code",
            "display_name",
            "persisted",
        ],
        column_config={
            "enabled":
                st.column_config.CheckboxColumn(
                    "Applicable",
                ),
            "component_code":
                st.column_config.TextColumn(
                    "Component code",
                ),
            "display_name":
                st.column_config.TextColumn(
                    "Display name",
                ),
            "field_group":
                st.column_config.TextColumn(
                    "Professional field group",
                ),
            "sort_order":
                st.column_config.NumberColumn(
                    "Display order",
                    min_value=1,
                    step=10,
                ),
            "notes":
                st.column_config.TextColumn(
                    "Configuration notes",
                ),
            "persisted":
                st.column_config.CheckboxColumn(
                    "Persisted",
                ),
        },
    )

    edited_rows = edited.to_dict(
        orient="records"
    )

    preview_key = (
        "media_profile_preview_"
        + media_type
    )

    if st.button(
        "Preview media-profile changes",
        type="primary",
    ):
        preview = preview_profile_changes(
            engine,
            media_type,
            edited_rows,
        )

        st.session_state[
            preview_key
        ] = {
            "preview":
                preview.to_dict(),
            "rows":
                edited_rows,
        }

    stored = st.session_state.get(
        preview_key
    )

    if stored:
        preview = stored[
            "preview"
        ]

        if preview[
            "status"
        ] == "READY":
            st.success(
                "Profile changes are ready for reviewed application."
            )
        elif preview[
            "status"
        ] == "NO_CHANGES":
            st.info(
                "No profile mutations were requested."
            )
        else:
            st.error(
                "Profile preview is blocked."
            )

        for blocker in preview[
            "blockers"
        ]:
            st.error(
                blocker
            )

        if preview[
            "operations"
        ]:
            st.dataframe(
                pd.DataFrame(
                    preview[
                        "operations"
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )

        st.code(
            preview[
                "confirmation_token"
            ],
            language=None,
        )

        actor = st.text_input(
            "Reviewer",
        )

        reason = st.text_area(
            "Configuration change reason",
        )

        token = st.text_input(
            "Confirmation token",
        )

        if st.button(
            "Apply reviewed media profile",
            type="primary",
            disabled=not (
                preview[
                    "ready"
                ]
                and actor.strip()
                and reason.strip()
                and token.strip()
            ),
        ):
            result = apply_profile_changes(
                engine,
                media_type,
                stored[
                    "rows"
                ],
                actor=actor,
                reason=reason,
                confirmation_token=token,
            )

            st.success(
                "Media profile applied: "
                f"{result['applied_operation_count']} mutation(s)."
            )

            st.session_state.pop(
                preview_key,
                None,
            )

            st.rerun()

    st.divider()

    st.subheader(
        "Immutable media-profile audit history"
    )

    audit_rows = list_profile_audit(
        engine,
        media_type,
    )

    if audit_rows:
        st.dataframe(
            pd.DataFrame(
                audit_rows
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info(
            "No audited change exists for this media profile."
        )


main()
