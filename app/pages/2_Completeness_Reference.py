"""Streamlit page for pressing completeness references."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.pressing_reference_admin import (
    REFERENCE_STATES,
    assigned_listing_preview,
    create_pressing,
    list_generation_values,
    list_media_types,
    list_pressings,
    load_reference_rows,
    normalize_reference_rows,
    reference_summary,
    save_reference_rows,
)


st.set_page_config(
    page_title="Pressing Completeness Reference",
    page_icon="📦",
    layout="wide",
)


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
    """Display a success message after rerunning."""
    st.session_state[
        "pressing_reference_message"
    ] = message

    st.rerun()


def _pressing_label(
    pressing: dict[str, Any],
) -> str:
    """Build one readable pressing selector label."""
    variant = (
        pressing.get(
            "pressing_variant_label"
        )
        or pressing.get(
            "pressing_variant_key"
        )
        or ""
    )

    suffix = (
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
        f"{suffix}"
    )


def _render_create_pressing(
    engine: Engine,
) -> None:
    """Render the exact-pressing creation form."""
    st.subheader("Create an exact pressing")

    st.caption(
        "Create the release-family identity first, then define "
        "the exact pressing. No auction listing is assigned by "
        "this form."
    )

    media_types = list_media_types(
        engine
    )

    generation_values = (
        list_generation_values(
            engine
        )
    )

    with st.form(
        "create-pressing-reference",
        clear_on_submit=False,
    ):
        family_column, pressing_column = st.columns(2)

        with family_column:
            st.markdown("#### Release family")

            display_artist = st.text_input(
                "Display artist",
                placeholder="Teresa Teng",
            )

            display_title = st.text_input(
                "Canonical title",
                placeholder=(
                    "アカシアの夢 / Acacia no Yume"
                ),
            )

            original_release_year = st.number_input(
                "Original release year",
                min_value=1800,
                max_value=2200,
                value=None,
                step=1,
            )

            family_notes = st.text_area(
                "Release-family notes",
                placeholder=(
                    "Family-level identity and title notes."
                ),
            )

        with pressing_column:
            st.markdown("#### Exact pressing")

            catalog_number = st.text_input(
                "Catalog number",
                placeholder="MR2276",
            )

            matrix_number = st.text_input(
                "Matrix number",
            )

            label_name = st.text_input(
                "Label",
                placeholder="Polydor",
            )

            media_type = st.selectbox(
                "Media type",
                options=media_types,
                index=(
                    media_types.index("LP")
                    if "LP" in media_types
                    else 0
                ),
            )

            format_detail = st.text_input(
                "Format detail",
                placeholder="1LP",
            )

            disc_count = st.number_input(
                "Disc count",
                min_value=1,
                max_value=100,
                value=1,
                step=1,
            )

            country = st.text_input(
                "Country",
                placeholder="Japan",
            )

            region = st.text_input(
                "Region",
                placeholder="JP",
            )

            release_year = st.number_input(
                "Pressing release year",
                min_value=1800,
                max_value=2200,
                value=None,
                step=1,
            )

            generation = st.selectbox(
                "Generation",
                options=generation_values,
                index=(
                    generation_values.index(
                        "UNKNOWN"
                    )
                    if "UNKNOWN"
                    in generation_values
                    else 0
                ),
            )

            pressing_variant_key = st.text_input(
                "Variant key",
                placeholder="PINK_OBI",
            )

            pressing_variant_label = st.text_input(
                "Variant label",
                placeholder="Pink obi issue",
            )

            is_first_press = st.checkbox(
                "First press",
            )

            is_modern_repress = st.checkbox(
                "Modern or later repress",
            )

            parent_first_press_id = st.number_input(
                "Parent first-press ID",
                min_value=1,
                value=None,
                step=1,
            )

            pressing_notes = st.text_area(
                "Pressing notes",
                placeholder=(
                    "Exact issue, matrix, packaging, "
                    "or edition notes."
                ),
            )

        submitted = st.form_submit_button(
            "Create pressing and open reference",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    try:
        pressing_id = create_pressing(
            engine,
            {
                "display_artist":
                    display_artist,
                "display_title":
                    display_title,
                "original_release_year":
                    original_release_year,
                "family_notes":
                    family_notes,
                "catalog_number":
                    catalog_number,
                "matrix_number":
                    matrix_number,
                "label_name":
                    label_name,
                "media_type":
                    media_type,
                "format_detail":
                    format_detail,
                "disc_count":
                    disc_count,
                "country":
                    country,
                "region":
                    region,
                "release_year":
                    release_year,
                "generation":
                    generation,
                "pressing_variant_key":
                    pressing_variant_key,
                "pressing_variant_label":
                    pressing_variant_label,
                "is_first_press":
                    is_first_press,
                "is_modern_repress":
                    is_modern_repress,
                "parent_first_press_id":
                    parent_first_press_id,
                "pressing_notes":
                    pressing_notes,
            },
        )
    except ValueError as error:
        st.error(str(error))
        return

    st.session_state[
        "pressing_reference_id"
    ] = pressing_id

    _rerun(
        f"Pressing #{pressing_id} created."
    )


def _render_reference_editor(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render the shared pressing-reference editor."""
    summary = reference_summary(
        engine,
        pressing_id,
    )

    st.subheader(
        "Pressing completeness reference"
    )

    st.warning(
        "This reference belongs to the exact pressing. "
        "Saving it affects every auction assigned to this "
        "pressing. Listing observations remain separate."
    )

    st.markdown(
        f"### {summary['display_artist']} — "
        f"{summary['display_title']}"
    )

    st.caption(
        f"Pressing #{pressing_id} · "
        f"{summary['catalog_number']} · "
        f"{summary['media_type']}"
    )

    metric_columns = st.columns(5)

    metric_columns[0].metric(
        "Active components",
        summary["active_components"],
    )

    metric_columns[1].metric(
        "Configured",
        summary["configured_components"],
    )

    metric_columns[2].metric(
        "Required rows",
        summary["required_rows"],
    )

    metric_columns[3].metric(
        "Unknown rows",
        summary["unknown_rows"],
    )

    metric_columns[4].metric(
        "Reference status",
        (
            "Verified"
            if summary["verified_reference"]
            else "Draft"
        ),
    )

    if summary["verified_reference"]:
        st.success(
            "This pressing has a complete, verified component "
            "reference and can participate in derived "
            "completeness logic."
        )
    else:
        st.info(
            "A verified reference requires every active component "
            "to be classified, at least one REQUIRED component, "
            "and zero UNKNOWN rows."
        )

    reference_rows = load_reference_rows(
        engine,
        pressing_id,
    )

    editor_dataframe = pd.DataFrame(
        reference_rows
    )

    edited = st.data_editor(
        editor_dataframe,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=(
            "pressing-reference-editor:"
            f"{pressing_id}"
        ),
        disabled=[
            "display_name",
            "applicable_media",
            "sort_order",
        ],
        column_config={
            "component_code": st.column_config.SelectboxColumn(
                "Component",
                options=sorted(
                    editor_dataframe[
                        "component_code"
                    ].dropna().unique().tolist()
                ),
                required=True,
            ),
            "display_name": st.column_config.TextColumn(
                "Display name",
            ),
            "applicable_media": st.column_config.TextColumn(
                "Applicable media",
            ),
            "variant_key": st.column_config.TextColumn(
                "Variant key",
                help=(
                    "Use a stable key such as PINK_OBI, "
                    "POSTER_A, or FACTORY_SEALED."
                ),
            ),
            "variant_label": st.column_config.TextColumn(
                "Variant label",
            ),
            "expectation_state": st.column_config.SelectboxColumn(
                "Reference state",
                options=list(
                    REFERENCE_STATES
                ),
                required=True,
            ),
            "expected_quantity": st.column_config.NumberColumn(
                "Quantity",
                min_value=0,
                step=1,
                required=True,
            ),
            "evidence_source": st.column_config.TextColumn(
                "Evidence source",
                help=(
                    "Discogs release page, physical copy, "
                    "catalog scan, label archive, or another "
                    "reviewed source."
                ),
            ),
            "confidence": st.column_config.NumberColumn(
                "Confidence",
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                format="%.2f",
            ),
            "notes": st.column_config.TextColumn(
                "Reference notes",
            ),
            "sort_order": None,
        },
    )

    normalized_preview: list[
        dict[str, Any]
    ] | None = None

    try:
        normalized_preview = normalize_reference_rows(
            edited.to_dict(
                orient="records"
            ),
            reference_rows_to_codes(
                reference_rows
            ),
        )
    except ValueError as error:
        st.warning(str(error))

    save_column, download_column = st.columns(
        [2, 1]
    )

    if save_column.button(
        "Save verified pressing reference",
        type="primary",
        width="stretch",
        disabled=(
            normalized_preview is None
        ),
        key=(
            "save-pressing-reference:"
            f"{pressing_id}"
        ),
    ):
        try:
            saved_summary = save_reference_rows(
                engine,
                pressing_id,
                edited.to_dict(
                    orient="records"
                ),
            )
        except ValueError as error:
            st.error(str(error))
        else:
            status = (
                "verified"
                if saved_summary[
                    "verified_reference"
                ]
                else "draft"
            )

            _rerun(
                "Pressing reference saved "
                f"as {status}."
            )

    csv_data = edited.to_csv(
        index=False
    ).encode("utf-8-sig")

    download_column.download_button(
        "Download reference CSV",
        data=csv_data,
        file_name=(
            "pressing-reference-"
            f"{pressing_id}.csv"
        ),
        mime="text/csv",
        width="stretch",
    )

    st.markdown("#### Discogs-style reference model")

    st.code(
        (
            "Pressing identity\n"
            "  ├── OBI: REQUIRED, qty 1, variant PINK_OBI\n"
            "  ├── INSERT: REQUIRED, qty 1\n"
            "  ├── POSTER: REQUIRED, qty 1\n"
            "  ├── PINUP: NOT_INCLUDED\n"
            "  ├── SHRINK_WRAP: NOT_INCLUDED\n"
            "  └── every other active component classified\n\n"
            "Listing observation\n"
            "  ├── OBI: PRESENT\n"
            "  ├── INSERT: PRESENT\n"
            "  └── POSTER: ABSENT\n\n"
            "Derived completeness\n"
            "  missing_components = [POSTER]\n"
            "  completeness_status = INCOMPLETE"
        ),
        language="text",
    )


def reference_rows_to_codes(
    rows: list[dict[str, Any]],
) -> list[str]:
    """Return unique component codes from editor rows."""
    return sorted(
        {
            str(row["component_code"])
            for row in rows
        }
    )


def _render_assigned_listings(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render listing-level completeness results."""
    st.subheader(
        "Assigned listings and derived completeness"
    )

    rows = assigned_listing_preview(
        engine,
        pressing_id,
    )

    if not rows:
        st.info(
            "No auction listing is assigned to this pressing."
        )
        return

    dataframe = pd.DataFrame(rows)

    st.dataframe(
        dataframe,
        width="stretch",
        hide_index=True,
        column_config={
            "auction_url": st.column_config.LinkColumn(
                "Auction",
            ),
            "completeness_ratio":
                st.column_config.NumberColumn(
                    "Completeness",
                    format="%.2f",
                ),
        },
    )

    status_counts = (
        dataframe[
            "completeness_status"
        ]
        .fillna("NO_RESULT")
        .value_counts()
        .rename_axis("status")
        .reset_index(name="rows")
    )

    st.markdown(
        "#### Completeness breakdown"
    )

    st.dataframe(
        status_counts,
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    """Render the pressing-reference administration page."""
    st.title(
        "📦 Pressing Completeness Reference"
    )

    st.caption(
        "Create exact pressings and define what an originally "
        "complete copy includes. This is the shared collector "
        "reference layer used by listing-level observations."
    )

    message = st.session_state.pop(
        "pressing_reference_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    create_tab, reference_tab, listings_tab = st.tabs(
        [
            "Create pressing",
            "Completeness reference",
            "Assigned listings",
        ]
    )

    with create_tab:
        _render_create_pressing(
            engine
        )

    search = st.text_input(
        "Search pressing library",
        placeholder=(
            "Artist, title, catalog number, matrix, or variant"
        ),
        key="pressing-reference-search",
    )

    pressings = list_pressings(
        engine,
        search,
    )

    if not pressings:
        with reference_tab:
            st.info(
                "No pressing matches the current search."
            )

        with listings_tab:
            st.info(
                "Create or locate a pressing first."
            )

        return

    pressing_by_id = {
        int(row["id"]): row
        for row in pressings
    }

    pressing_ids = list(
        pressing_by_id
    )

    preferred_id = st.session_state.get(
        "pressing_reference_id"
    )

    selected_index = (
        pressing_ids.index(preferred_id)
        if preferred_id in pressing_ids
        else 0
    )

    selected_id = st.selectbox(
        "Exact pressing",
        options=pressing_ids,
        index=selected_index,
        format_func=lambda pressing_id: (
            _pressing_label(
                pressing_by_id[
                    pressing_id
                ]
            )
        ),
        key="pressing-reference-selector",
    )

    st.session_state[
        "pressing_reference_id"
    ] = selected_id

    with reference_tab:
        _render_reference_editor(
            engine,
            selected_id,
        )

    with listings_tab:
        _render_assigned_listings(
            engine,
            selected_id,
        )


main()
