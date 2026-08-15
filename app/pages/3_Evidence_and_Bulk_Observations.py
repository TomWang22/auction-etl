"""Evidence-source registry and bulk observation workbench."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.reference_record_admin import (
    apply_audited_bulk_observations as apply_bulk_observations,
)
from auction_etl.services.collector_observation_bulk import (
    export_observation_worksheet,
    list_evidence_sources,
    preview_bulk_observations,
    save_evidence_source,
    set_evidence_source_active,
)
from auction_etl.services.pressing_reference_admin import (
    list_pressings,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Evidence and Bulk Observations",
    page_icon="🧾",
    layout="wide",
)
render_navigation()


@st.cache_resource
def _engine() -> Engine:
    """Create the shared PostgreSQL engine."""
    database_url = os.environ.get(
        "DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required."
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def _rerun(message: str) -> None:
    """Rerun with one success notification."""
    st.session_state[
        "evidence_bulk_message"
    ] = message

    st.rerun()


def _pressing_label(
    pressing: dict[str, Any],
) -> str:
    """Build one readable pressing label."""
    variant = (
        pressing.get(
            "pressing_variant_label"
        )
        or pressing.get(
            "pressing_variant_key"
        )
        or ""
    )

    variant_suffix = (
        f" · {variant}"
        if variant
        else ""
    )

    return (
        f"#{pressing['id']} · "
        f"{pressing['display_artist']} — "
        f"{pressing['display_title']} · "
        f"{pressing['catalog_number']} · "
        f"{pressing['media_type']}"
        f"{variant_suffix}"
    )


def _render_registry(
    engine: Engine,
) -> None:
    """Render evidence-source registry administration."""
    st.subheader(
        "Reusable evidence-source registry"
    )

    st.caption(
        "Evidence-source keys are reusable identifiers such as "
        "LISTING_TITLE, PHYSICAL_COPY, CATALOG_SCAN, or "
        "DISCOGS_RELEASE. Registry defaults never overwrite "
        "reviewed observation confidence."
    )

    sources = list_evidence_sources(
        engine,
        include_inactive=True,
    )

    if sources:
        st.dataframe(
            pd.DataFrame(sources),
            width="stretch",
            hide_index=True,
            column_config={
                "active":
                    st.column_config.CheckboxColumn(
                        "Active",
                    ),
                "default_confidence":
                    st.column_config.NumberColumn(
                        "Default confidence",
                        min_value=0.0,
                        max_value=1.0,
                        format="%.2f",
                    ),
                "base_url":
                    st.column_config.LinkColumn(
                        "Base URL",
                    ),
            },
        )
    else:
        st.info(
            "No evidence sources are registered yet."
        )

    source_by_key = {
        str(row["source_key"]): row
        for row in sources
    }

    source_keys = list(
        source_by_key
    )

    selected_key: str | None = None

    if source_keys:
        selected_key = st.selectbox(
            "Edit an existing source",
            options=[""] + source_keys,
            format_func=lambda value: (
                "Create a new source"
                if not value
                else (
                    f"{value} — "
                    f"{source_by_key[value]['display_name']}"
                )
            ),
        )

        if not selected_key:
            selected_key = None

    selected = (
        source_by_key.get(
            selected_key
        )
        if selected_key is not None
        else None
    )

    with st.form(
        "evidence-source-form",
        clear_on_submit=False,
    ):
        source_key = st.text_input(
            "Source key",
            value=(
                str(
                    selected[
                        "source_key"
                    ]
                )
                if selected
                else ""
            ),
            placeholder="CATALOG_SCAN",
            disabled=selected is not None,
        )

        display_name = st.text_input(
            "Display name",
            value=(
                str(
                    selected[
                        "display_name"
                    ]
                )
                if selected
                else ""
            ),
            placeholder="Manufacturer catalog scan",
        )

        source_type = st.text_input(
            "Source type",
            value=(
                str(
                    selected[
                        "source_type"
                    ]
                )
                if selected
                else "OTHER"
            ),
            placeholder="REFERENCE_DATABASE",
        )

        base_url = st.text_input(
            "Base URL",
            value=(
                str(
                    selected[
                        "base_url"
                    ]
                    or ""
                )
                if selected
                else ""
            ),
        )

        default_confidence = st.number_input(
            "Default confidence",
            min_value=0.0,
            max_value=1.0,
            value=(
                float(
                    selected[
                        "default_confidence"
                    ]
                )
                if (
                    selected
                    and selected[
                        "default_confidence"
                    ] is not None
                )
                else 0.90
            ),
            step=0.01,
        )

        active = st.checkbox(
            "Active",
            value=(
                bool(
                    selected[
                        "active"
                    ]
                )
                if selected
                else True
            ),
        )

        notes = st.text_area(
            "Registry notes",
            value=(
                str(
                    selected[
                        "notes"
                    ]
                    or ""
                )
                if selected
                else ""
            ),
        )

        submitted = st.form_submit_button(
            (
                "Update evidence source"
                if selected
                else "Create evidence source"
            ),
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            saved = save_evidence_source(
                engine,
                {
                    "source_key":
                        (
                            selected_key
                            or source_key
                        ),
                    "display_name":
                        display_name,
                    "source_type":
                        source_type,
                    "base_url":
                        base_url,
                    "default_confidence":
                        default_confidence,
                    "active":
                        active,
                    "notes":
                        notes,
                },
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Evidence source saved: "
                f"{saved['source_key']}"
            )

    if selected_key is not None:
        selected_active = bool(
            source_by_key[
                selected_key
            ]["active"]
        )

        action_label = (
            "Deactivate evidence source"
            if selected_active
            else "Reactivate evidence source"
        )

        if st.button(
            action_label,
            width="stretch",
            key=(
                "toggle-source:"
                f"{selected_key}"
            ),
        ):
            set_evidence_source_active(
                engine,
                selected_key,
                not selected_active,
            )

            _rerun(
                f"Evidence source {selected_key} updated."
            )


def _render_bulk_import(
    engine: Engine,
) -> None:
    """Render bulk worksheet export and import."""
    st.subheader(
        "Bulk listing-component observations"
    )

    st.caption(
        "Download one worksheet for an exact pressing cohort, "
        "enter explicit listing observations, preview every row, "
        "then apply the complete file atomically."
    )

    pressings = list_pressings(
        engine
    )

    if not pressings:
        st.info(
            "Create and assign an exact pressing first."
        )
        return

    pressing_by_id = {
        int(row["id"]): row
        for row in pressings
    }

    pressing_ids = list(
        pressing_by_id
    )

    pressing_id = st.selectbox(
        "Exact pressing cohort",
        options=pressing_ids,
        format_func=lambda value: (
            _pressing_label(
                pressing_by_id[value]
            )
        ),
    )

    worksheet = export_observation_worksheet(
        engine,
        pressing_id,
    )

    st.download_button(
        "Download bulk observation worksheet",
        data=worksheet,
        file_name=(
            "component-observations-"
            f"pressing-{pressing_id}.csv"
        ),
        mime="text/csv",
        width="stretch",
    )

    st.markdown(
        "#### Worksheet rules"
    )

    st.code(
        (
            "PRESENT\n"
            "  observed_quantity >= 1\n\n"
            "ABSENT\n"
            "  observed_quantity = 0\n\n"
            "Blank observation_state\n"
            "  row is ignored only when all evidence fields are blank\n\n"
            "Evidence source\n"
            "  must exist and be active in the registry\n\n"
            "Existing exact observation key\n"
            "  blocked unless overwrite is explicitly enabled"
        ),
        language="text",
    )

    uploaded = st.file_uploader(
        "Completed observation worksheet",
        type=["csv"],
    )

    if uploaded is None:
        return

    payload = uploaded.getvalue()

    preview = preview_bulk_observations(
        engine,
        payload,
    )

    summary_columns = st.columns(5)

    summary_columns[0].metric(
        "Rows",
        len(preview.rows),
    )

    summary_columns[1].metric(
        "Listings",
        preview.touched_listing_count,
    )

    summary_columns[2].metric(
        "Errors",
        len(preview.errors),
    )

    summary_columns[3].metric(
        "Warnings",
        len(preview.warnings),
    )

    summary_columns[4].metric(
        "Existing conflicts",
        len(
            preview.existing_conflicts
        ),
    )

    if preview.errors:
        st.error(
            "\n".join(
                f"• {message}"
                for message in preview.errors
            )
        )

    if preview.warnings:
        st.warning(
            "\n".join(
                f"• {message}"
                for message in preview.warnings
            )
        )

    if preview.rows:
        st.markdown(
            "#### Parsed observations"
        )

        st.dataframe(
            pd.DataFrame(
                preview.rows
            ),
            width="stretch",
            hide_index=True,
        )

    if preview.existing_conflicts:
        st.markdown(
            "#### Existing-row conflicts"
        )

        st.dataframe(
            pd.DataFrame(
                preview.existing_conflicts
            ),
            width="stretch",
            hide_index=True,
        )

    overwrite = st.checkbox(
        "Overwrite only conflicting exact observation keys",
        value=False,
        disabled=not bool(
            preview.existing_conflicts
        ),
    )

    confirmed = st.checkbox(
        (
            "I reviewed the parsed observations, evidence "
            "sources, quantities, confidence values, warnings, "
            "and existing conflicts."
        ),
        value=False,
    )

    apply_disabled = (
        not preview.ready
        or not confirmed
        or (
            bool(
                preview.existing_conflicts
            )
            and not overwrite
        )
    )

    if st.button(
        "Apply bulk observations atomically",
        type="primary",
        width="stretch",
        disabled=apply_disabled,
    ):
        try:
            result = apply_bulk_observations(
                engine,
                payload,
                overwrite_existing=overwrite,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Bulk observations applied: "
                f"{result['inserted_rows']} rows across "
                f"{result['touched_listings']} listings."
            )


def main() -> None:
    """Render evidence registry and bulk observation workflows."""
    st.title(
        "🧾 Evidence and Bulk Observations"
    )

    st.caption(
        "Reusable evidence-source administration and atomic "
        "listing-component observation imports for every title "
        "and exact pressing."
    )

    message = st.session_state.pop(
        "evidence_bulk_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    registry_tab, import_tab = st.tabs(
        [
            "Evidence-source registry",
            "Bulk observations",
        ]
    )

    with registry_tab:
        _render_registry(
            engine
        )

    with import_tab:
        _render_bulk_import(
            engine
        )


main()
