"""General pressing-reference workbench."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.pressing_reference_admin import (
    REFERENCE_STATES,
    create_pressing,
    list_generation_values,
    list_media_types,
    list_pressings,
    load_reference_rows,
    normalize_reference_rows,
    reference_summary,
    save_reference_rows,
)
from auction_etl.services.pressing_reference_workbench import (
    CLONE_MODES,
    IMPORT_MODES,
    clone_reference,
    import_reference_csv,
    list_reference_library,
    listing_verdict_bundle,
    parse_reference_csv,
    pressing_listing_scores,
    reference_csv_bytes,
)

import inspect as _canonical_inspect
import os as _canonical_os

import pandas as _canonical_pd
from sqlalchemy import create_engine as _canonical_create_engine

from auction_etl.services.media_aware_reference import (
    REFERENCE_ACTIONS as _canonical_reference_actions,
    REFERENCE_STATES as _canonical_reference_states,
    apply_reference_changes as _canonical_apply_reference_changes,
    list_assigned_listings as _canonical_list_assigned_listings,
    list_evidence_sources as _canonical_list_evidence_sources,
    list_pressings as _canonical_list_pressings,
    list_reference_audit as _canonical_list_reference_audit,
    load_media_profile as _canonical_load_media_profile,
    load_reference_editor_rows as _canonical_load_reference_editor_rows,
    preview_reference_changes as _canonical_preview_reference_changes,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Pressing Reference Workbench",
    page_icon="📦",
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
    """Rerun and display one success message."""
    st.session_state[
        "pressing_workbench_message"
    ] = message

    st.rerun()


def _pressing_label(
    pressing: dict[str, Any],
) -> str:
    """Build a readable exact-pressing label."""
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


def _library_label(
    pressing: dict[str, Any],
) -> str:
    """Build a label from a library row."""
    return (
        f"#{pressing['pressing_id']} · "
        f"{pressing['display_artist']} — "
        f"{pressing['display_title']} · "
        f"{pressing['catalog_number']} · "
        f"{pressing['media_type']}"
    )


def _create_pressing_panel(
    engine: Engine,
) -> None:
    """Create a release family and exact pressing."""
    st.subheader("Create an exact pressing")

    st.caption(
        "This creates a reusable pressing identity. "
        "It does not assign listings and does not invent "
        "component expectations."
    )

    media_types = list_media_types(
        engine
    )

    generations = list_generation_values(
        engine
    )

    with st.form(
        "general-create-pressing",
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
            )

        with pressing_column:
            st.markdown("#### Exact pressing")

            catalog_number = st.text_input(
                "Catalog number",
                placeholder="CAT-1234",
            )

            matrix_number = st.text_input(
                "Matrix number",
            )

            label_name = st.text_input(
                "Label",
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
            )

            region = st.text_input(
                "Region",
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
                options=generations,
                index=(
                    generations.index(
                        "UNKNOWN"
                    )
                    if "UNKNOWN" in generations
                    else 0
                ),
            )

            variant_key = st.text_input(
                "Pressing variant key",
                placeholder="PINK_OBI",
            )

            variant_label = st.text_input(
                "Pressing variant label",
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
            )

        submitted = st.form_submit_button(
            "Create pressing",
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
                    variant_key,
                "pressing_variant_label":
                    variant_label,
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
        "workbench_pressing_id"
    ] = pressing_id

    _rerun(
        f"Pressing #{pressing_id} created."
    )


def _reference_library_panel(
    engine: Engine,
    search: str,
) -> None:
    """Display all pressing references and their coverage."""
    st.subheader("Pressing reference library")

    st.caption(
        "This library is general. Every title, format, country, "
        "edition, matrix, obi variant, repress, and special issue "
        "can have its own exact pressing reference."
    )

    rows = list_reference_library(
        engine,
        search,
    )

    if not rows:
        st.info(
            "No pressing matches the current search."
        )
        return

    dataframe = pd.DataFrame(rows)

    st.dataframe(
        dataframe,
        width="stretch",
        hide_index=True,
        column_config={
            "pressing_id":
                st.column_config.NumberColumn(
                    "Pressing ID",
                    format="%d",
                ),
            "reference_coverage_percent":
                st.column_config.ProgressColumn(
                    "Reference coverage",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "verified_reference":
                st.column_config.CheckboxColumn(
                    "Verified",
                ),
        },
    )

    status_counts = (
        dataframe["reference_status"]
        .value_counts()
        .rename_axis("reference_status")
        .reset_index(name="pressings")
    )

    st.markdown("#### Reference status")

    st.dataframe(
        status_counts,
        width="stretch",
        hide_index=True,
    )


def _worksheet_panel(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Edit a shared component reference for one exact pressing."""
    summary = reference_summary(
        engine,
        pressing_id,
    )

    st.subheader("Pressing completeness reference")

    st.warning(
        "This worksheet belongs to the exact pressing. "
        "Saving it affects every listing assigned to that "
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
        "Required",
        summary["required_rows"],
    )

    metric_columns[3].metric(
        "Unknown",
        summary["unknown_rows"],
    )

    metric_columns[4].metric(
        "Reference verdict",
        (
            "VERIFIED"
            if summary["verified_reference"]
            else "DRAFT"
        ),
    )

    rows = load_reference_rows(
        engine,
        pressing_id,
    )

    dataframe = pd.DataFrame(rows)

    active_codes = sorted(
        dataframe[
            "component_code"
        ].dropna().unique().tolist()
    )

    edited = st.data_editor(
        dataframe,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "display_name",
            "applicable_media",
            "sort_order",
        ],
        key=(
            "general-reference-editor:"
            f"{pressing_id}"
        ),
        column_config={
            "component_code":
                st.column_config.SelectboxColumn(
                    "Component",
                    options=active_codes,
                    required=True,
                ),
            "display_name":
                st.column_config.TextColumn(
                    "Display name",
                ),
            "applicable_media":
                st.column_config.TextColumn(
                    "Applicable media",
                ),
            "variant_key":
                st.column_config.TextColumn(
                    "Variant key",
                    help=(
                        "Examples: PINK_OBI, POSTER_A, "
                        "FACTORY_SEALED."
                    ),
                ),
            "variant_label":
                st.column_config.TextColumn(
                    "Variant label",
                ),
            "expectation_state":
                st.column_config.SelectboxColumn(
                    "Reference state",
                    options=list(
                        REFERENCE_STATES
                    ),
                    required=True,
                ),
            "expected_quantity":
                st.column_config.NumberColumn(
                    "Quantity",
                    min_value=0,
                    step=1,
                    required=True,
                ),
            "evidence_source":
                st.column_config.TextColumn(
                    "Evidence source",
                    help=(
                        "Physical copy, Discogs release page, "
                        "catalog scan, label archive, booklet, "
                        "or another reviewed source."
                    ),
                ),
            "confidence":
                st.column_config.NumberColumn(
                    "Confidence",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    format="%.2f",
                ),
            "notes":
                st.column_config.TextColumn(
                    "Collector notes",
                ),
            "sort_order": None,
        },
    )

    valid_rows: list[
        dict[str, Any]
    ] | None = None

    try:
        valid_rows = normalize_reference_rows(
            edited.to_dict(
                orient="records"
            ),
            active_codes,
        )
    except ValueError as error:
        st.warning(str(error))

    save_column, export_column = st.columns(
        [2, 1]
    )

    if save_column.button(
        "Save verified pressing reference",
        type="primary",
        width="stretch",
        disabled=valid_rows is None,
        key=f"save-reference:{pressing_id}",
    ):
        try:
            result = save_reference_rows(
                engine,
                pressing_id,
                edited.to_dict(
                    orient="records"
                ),
            )
        except ValueError as error:
            st.error(str(error))
        else:
            verdict = (
                "VERIFIED"
                if result[
                    "verified_reference"
                ]
                else "DRAFT"
            )

            _rerun(
                "Reference saved with verdict "
                f"{verdict}."
            )

    export_column.download_button(
        "Download worksheet CSV",
        data=reference_csv_bytes(
            engine,
            pressing_id,
        ),
        file_name=(
            "pressing-reference-"
            f"{pressing_id}.csv"
        ),
        mime="text/csv",
        width="stretch",
    )

    st.markdown("#### Deterministic model")

    st.code(
        (
            "Expected pressing reference\n"
            "  component_code\n"
            "  variant_key\n"
            "  expectation_state\n"
            "  expected_quantity\n"
            "  evidence_source\n"
            "  confidence\n\n"
            "Listing observation\n"
            "  observation_state\n"
            "  observed_quantity\n"
            "  normalized_condition\n\n"
            "Structural completeness %\n"
            "  confirmed present required units\n"
            "  ÷ total required units\n\n"
            "Damage-adjusted %\n"
            "  structural completeness %\n"
            "  × exact canonical condition factor\n\n"
            "No AI inference is used."
        ),
        language="text",
    )


def _transfer_panel(
    engine: Engine,
    selected_pressing_id: int,
    pressings: list[dict[str, Any]],
) -> None:
    """Import, export, or clone shared references."""
    st.subheader("CSV import, export, and cloning")

    st.caption(
        "Draft transfers never become verified automatically. "
        "Verified imports and exact copies require explicit "
        "collector confirmation."
    )

    import_tab, clone_tab = st.tabs(
        [
            "Import CSV",
            "Clone reference",
        ]
    )

    with import_tab:
        uploaded_file = st.file_uploader(
            "Reference worksheet CSV",
            type=["csv"],
            key=(
                "reference-upload:"
                f"{selected_pressing_id}"
            ),
        )

        import_mode = st.radio(
            "Import mode",
            options=list(
                IMPORT_MODES
            ),
            format_func=lambda value: {
                "DRAFT":
                    "Draft — force review before verification",
                "VERIFIED":
                    "Verified — preserve supplied states",
            }[value],
            horizontal=True,
            key=(
                "reference-import-mode:"
                f"{selected_pressing_id}"
            ),
        )

        uploaded_bytes: bytes | None = None

        if uploaded_file is not None:
            uploaded_bytes = (
                uploaded_file.getvalue()
            )

            try:
                preview_rows = parse_reference_csv(
                    uploaded_bytes
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.dataframe(
                    pd.DataFrame(
                        preview_rows
                    ),
                    width="stretch",
                    hide_index=True,
                )

        if st.button(
            "Import worksheet",
            type="primary",
            width="stretch",
            disabled=uploaded_bytes is None,
            key=(
                "import-reference:"
                f"{selected_pressing_id}"
            ),
        ):
            try:
                result = import_reference_csv(
                    engine,
                    selected_pressing_id,
                    uploaded_bytes or b"",
                    import_mode,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                verdict = (
                    "VERIFIED"
                    if result[
                        "verified_reference"
                    ]
                    else "DRAFT"
                )

                _rerun(
                    "Worksheet imported with verdict "
                    f"{verdict}."
                )

    with clone_tab:
        pressing_by_id = {
            int(row["id"]): row
            for row in pressings
        }

        pressing_ids = list(
            pressing_by_id
        )

        source_id = st.selectbox(
            "Source pressing",
            options=pressing_ids,
            format_func=lambda value: (
                _pressing_label(
                    pressing_by_id[value]
                )
            ),
            key=(
                "clone-source:"
                f"{selected_pressing_id}"
            ),
        )

        st.text_input(
            "Target pressing",
            value=_pressing_label(
                pressing_by_id[
                    selected_pressing_id
                ]
            ),
            disabled=True,
        )

        clone_mode = st.radio(
            "Clone mode",
            options=list(
                CLONE_MODES
            ),
            format_func=lambda value: {
                "DRAFT":
                    "Draft — copy structure but force every row to UNKNOWN",
                "VERIFIED_COPY":
                    "Verified exact copy — preserve all states",
            }[value],
            horizontal=True,
            key=(
                "clone-mode:"
                f"{selected_pressing_id}"
            ),
        )

        overwrite = st.checkbox(
            "Overwrite the target reference",
            value=False,
            key=(
                "clone-overwrite:"
                f"{selected_pressing_id}"
            ),
        )

        verified_confirmation = st.checkbox(
            (
                "I verified that the target pressing has "
                "the same original component package."
            ),
            value=False,
            disabled=(
                clone_mode !=
                "VERIFIED_COPY"
            ),
            key=(
                "clone-confirmation:"
                f"{selected_pressing_id}"
            ),
        )

        clone_disabled = (
            source_id ==
                selected_pressing_id
            or (
                clone_mode ==
                    "VERIFIED_COPY"
                and not
                    verified_confirmation
            )
        )

        if st.button(
            "Clone reference",
            type="primary",
            width="stretch",
            disabled=clone_disabled,
            key=(
                "clone-reference:"
                f"{selected_pressing_id}"
            ),
        ):
            try:
                result = clone_reference(
                    engine,
                    source_id,
                    selected_pressing_id,
                    clone_mode,
                    overwrite=overwrite,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                verdict = (
                    "VERIFIED"
                    if result[
                        "verified_reference"
                    ]
                    else "DRAFT"
                )

                _rerun(
                    "Reference cloned with verdict "
                    f"{verdict}."
                )


def _verdict_panel(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Display deterministic and existing analytics verdicts."""
    st.subheader("Assigned listings and derived completeness")

    st.caption(
        "Component percentages are arithmetic. Condition damage "
        "uses exact canonical grade tokens only. Existing "
        "Midfication, Emotional Damage, alerts, and auction-score "
        "views retain their database-defined formulas."
    )

    cohort = pressing_listing_scores(
        engine,
        pressing_id,
    )

    if not cohort:
        st.info(
            "No listings are assigned to this pressing."
        )
        return

    cohort_dataframe = pd.DataFrame(
        cohort
    )

    st.dataframe(
        cohort_dataframe,
        width="stretch",
        hide_index=True,
        column_config={
            "structural_completeness_percent":
                st.column_config.ProgressColumn(
                    "Completeness",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "verification_percent":
                st.column_config.ProgressColumn(
                    "Verification",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "condition_coverage_percent":
                st.column_config.ProgressColumn(
                    "Condition coverage",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "condition_percent":
                st.column_config.ProgressColumn(
                    "Condition",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "damage_adjusted_percent":
                st.column_config.ProgressColumn(
                    "Damage-adjusted",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
            "damage_penalty_percent":
                st.column_config.NumberColumn(
                    "Damage penalty",
                    format="%.2f%%",
                ),
        },
    )

    listing_options = [
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        )
        for row in cohort
    ]

    listing_labels = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        ): (
            f"{row['marketplace']}/"
            f"{row['listing_id']} · "
            f"{row['title']}"
        )
        for row in cohort
    }

    selected_listing = st.selectbox(
        "Listing verdict",
        options=listing_options,
        format_func=lambda value: (
            listing_labels[value]
        ),
        key=(
            "verdict-listing:"
            f"{pressing_id}"
        ),
    )

    bundle = listing_verdict_bundle(
        engine,
        selected_listing[0],
        selected_listing[1],
    )

    score = bundle[
        "component_score"
    ]

    metric_columns = st.columns(6)

    metric_columns[0].metric(
        "Verdict",
        score["verdict"],
    )

    metric_columns[1].metric(
        "Completeness",
        (
            f"{score['structural_completeness_percent']:.2f}%"
            if score[
                "structural_completeness_percent"
            ] is not None
            else "N/A"
        ),
    )

    metric_columns[2].metric(
        "Verification",
        (
            f"{score['verification_percent']:.2f}%"
            if score[
                "verification_percent"
            ] is not None
            else "N/A"
        ),
    )

    metric_columns[3].metric(
        "Condition coverage",
        (
            f"{score['condition_coverage_percent']:.2f}%"
            if score[
                "condition_coverage_percent"
            ] is not None
            else "N/A"
        ),
    )

    metric_columns[4].metric(
        "Damage-adjusted",
        (
            f"{score['damage_adjusted_percent']:.2f}%"
            if score[
                "damage_adjusted_percent"
            ] is not None
            else "INSUFFICIENT DATA"
        ),
    )

    metric_columns[5].metric(
        "Damage penalty",
        (
            f"{score['damage_penalty_percent']:.2f}%"
            if score[
                "damage_penalty_percent"
            ] is not None
            else "N/A"
        ),
    )

    st.markdown("#### Component calculation")

    st.dataframe(
        pd.DataFrame(
            score["components"]
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Database completeness")

    st.json(
        score[
            "database_completeness"
        ],
        expanded=False,
    )

    analytics_tabs = st.tabs(
        [
            "Plushie / auction scores",
            "Emotional Damage",
            "Alerts",
            "Midfication",
            "Completeness premium",
            "Obi analytics",
        ]
    )

    with analytics_tabs[0]:
        st.json(
            bundle[
                "auction_scores"
            ],
            expanded=False,
        )

    with analytics_tabs[1]:
        st.json(
            bundle[
                "emotional_damage"
            ],
            expanded=False,
        )

    with analytics_tabs[2]:
        st.json(
            bundle[
                "auction_alerts"
            ],
            expanded=False,
        )

    with analytics_tabs[3]:
        st.json(
            bundle[
                "midfication_detection"
            ],
            expanded=False,
        )

    with analytics_tabs[4]:
        st.json(
            bundle[
                "completeness_premium"
            ],
            expanded=False,
        )

    with analytics_tabs[5]:
        st.markdown("##### Obi premium")

        st.json(
            bundle[
                "obi_premium"
            ],
            expanded=False,
        )

        st.markdown(
            "##### Obi variant summary"
        )

        st.json(
            bundle[
                "obi_variant_price_summary"
            ],
            expanded=False,
        )



# pressing-reference-page-compatibility:start
def _render_create_pressing(
    engine: Engine,
) -> None:
    """Preserve the original pressing-creation page contract."""
    _create_pressing_panel(engine)


def _render_reference_editor(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Preserve the original shared-reference editor contract."""
    _worksheet_panel(
        engine,
        pressing_id,
    )


def _render_assigned_listings(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Preserve the original assigned-listing preview contract."""
    _verdict_panel(
        engine,
        pressing_id,
    )


# pressing-reference-page-compatibility:end


# canonical-media-aware-reference:start
def _canonical_reference_engine():
    """Return the canonical reference database engine."""
    database_url = _canonical_os.environ.get(
        "DATABASE_URL",
        (
            "postgresql+psycopg://auction:auction"
            "@127.0.0.1:5544/auction_warehouse"
        ),
    )

    return _canonical_create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
    )


def _canonical_pressing_label(
    pressing: dict[str, object],
) -> str:
    """Return one exact-pressing selector label."""
    catalog = (
        pressing.get(
            "catalog_number"
        )
        or "No catalog"
    )

    return (
        f"Pressing #{pressing['pressing_id']} · "
        f"{pressing['display_artist']} · "
        f"{pressing['display_title']} · "
        f"{catalog} · "
        f"{pressing['media_type']}"
    )


def _canonical_operation_rows(
    operations: list[dict[str, object]]
    | tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    """Flatten preview operations for display."""
    rows = []

    for operation in operations:
        identity = operation.get(
            "identity"
        ) or {}

        before = operation.get(
            "before"
        ) or {}

        after = operation.get(
            "after"
        ) or {}

        rows.append(
            {
                "operation":
                    operation.get(
                        "operation"
                    ),
                "component_code":
                    identity.get(
                        "component_code"
                    ),
                "variant_key":
                    identity.get(
                        "variant_key"
                    ),
                "before_state":
                    before.get(
                        "expectation_state"
                    ),
                "after_state":
                    after.get(
                        "expectation_state"
                    ),
                "before_quantity":
                    before.get(
                        "expected_quantity"
                    ),
                "after_quantity":
                    after.get(
                        "expected_quantity"
                    ),
                "evidence_source":
                    after.get(
                        "evidence_source"
                    ),
            }
        )

    return rows


def _canonical_render_create_pressing(
    engine,
) -> None:
    """Render the existing exact-pressing creation workflow."""
    renderer = globals().get(
        "_render_create_pressing"
    )

    if not callable(
        renderer
    ):
        renderer = globals().get(
            "_create_pressing_panel"
        )

    if not callable(
        renderer
    ):
        st.info(
            "Use Reference Record Admin to create a new exact "
            "pressing before defining its master reference."
        )
        return

    signature = _canonical_inspect.signature(
        renderer
    )

    required_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if (
            parameter.default
            is _canonical_inspect.Parameter.empty
            and parameter.kind
            not in (
                _canonical_inspect.Parameter.VAR_POSITIONAL,
                _canonical_inspect.Parameter.VAR_KEYWORD,
            )
        )
    ]

    if len(
        required_parameters
    ) == 0:
        renderer()
    elif len(
        required_parameters
    ) == 1:
        renderer(
            engine
        )
    else:
        st.info(
            "The legacy pressing creator has a newer contract. "
            "Use Reference Record Admin for creation."
        )


def _render_canonical_media_reference() -> None:
    """Render the authoritative exact-pressing master page."""
    st.title(
        "Pressing Completeness Reference"
    )

    st.caption(
        "The master definition of what a complete example of one "
        "exact pressing should contain."
    )

    st.info(
        "Auction observations describe individual copies. They never "
        "become shared pressing requirements automatically."
    )

    engine = _canonical_reference_engine()

    pressings = _canonical_list_pressings(
        engine
    )

    if not pressings:
        st.warning(
            "No exact pressings exist yet."
        )

        _canonical_render_create_pressing(
            engine
        )
        return

    pressing_map = {
        int(
            row[
                "pressing_id"
            ]
        ):
            row
        for row in pressings
    }

    selected_pressing_id = st.selectbox(
        "Exact pressing",
        options=list(
            pressing_map
        ),
        format_func=lambda value:
            _canonical_pressing_label(
                pressing_map[
                    int(
                        value
                    )
                ]
            ),
        key=(
            "canonical_media_reference_pressing"
        ),
    )

    selected_pressing = pressing_map[
        int(
            selected_pressing_id
        )
    ]

    profile = _canonical_load_media_profile(
        engine,
        int(
            selected_pressing_id
        ),
    )

    applicable_components = profile[
        "applicable_components"
    ]

    applicable_codes = [
        str(
            row[
                "code"
            ]
        )
        for row in applicable_components
    ]

    evidence_sources = (
        _canonical_list_evidence_sources(
            engine
        )
    )

    source_options = [
        "",
        *[
            str(
                row[
                    "source_key"
                ]
            )
            for row in evidence_sources
        ],
    ]

    metric_columns = st.columns(
        4
    )

    metric_columns[0].metric(
        "Media type",
        selected_pressing[
            "media_type"
        ],
    )

    metric_columns[1].metric(
        "Applicable fields",
        profile[
            "applicable_component_count"
        ],
    )

    metric_columns[2].metric(
        "Assigned auctions",
        selected_pressing[
            "assigned_listing_count"
        ],
    )

    metric_columns[3].metric(
        "Persisted reference rows",
        selected_pressing[
            "reference_row_count"
        ],
    )

    st.caption(
        "PROFILE_CONTRACT "
        f"pressing_id={selected_pressing_id} "
        f"media_type={selected_pressing['media_type']} "
        "applicable_components="
        f"{profile['applicable_component_count']}"
    )

    with st.expander(
        "Reference-state definitions",
        expanded=False,
    ):
        st.markdown(
            """
**Not applicable** — hidden because the component registry does
not apply it to this medium. No master row is created.

**UNKNOWN** — applicable to the medium, but inclusion for this
exact pressing is unresolved.

**NOT_INCLUDED** — reviewed evidence confirms this exact pressing
did not include the component.

**REQUIRED** — reviewed evidence confirms that a complete copy of
this exact pressing should contain the component.
            """
        )

    tabs = st.tabs(
        [
            "Master reference",
            "Create exact pressing",
            "Assigned listings",
            "Audit history",
        ]
    )

    with tabs[0]:
        st.subheader(
            "Media-aware master worksheet"
        )

        st.write(
            f"{selected_pressing['media_type']} exposes "
            f"{profile['applicable_component_count']} applicable "
            "standard component fields."
        )

        non_applicable = profile[
            "non_applicable_components"
        ]

        with st.expander(
            "Fields excluded by this media profile",
            expanded=False,
        ):
            excluded_names = [
                (
                    f"{row['code']} — "
                    f"{row['display_name']}"
                )
                for row in non_applicable
            ]

            if excluded_names:
                st.write(
                    ", ".join(
                        excluded_names
                    )
                )
            else:
                st.write(
                    "No active component fields are excluded."
                )

        editor_rows = (
            _canonical_load_reference_editor_rows(
                engine,
                int(
                    selected_pressing_id
                ),
            )
        )

        component_options = sorted(
            {
                *applicable_codes,
                *[
                    str(
                        row[
                            "component_code"
                        ]
                    )
                    for row in editor_rows
                    if row.get(
                        "component_code"
                    )
                ],
            }
        )

        editor_frame = _canonical_pd.DataFrame(
            editor_rows
        )

        edited_frame = st.data_editor(
            editor_frame,
            key=(
                "canonical_media_reference_editor_"
                f"{selected_pressing_id}"
            ),
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_order=[
                "action",
                "group",
                "component_code",
                "display_name",
                "variant_key",
                "variant_label",
                "expectation_state",
                "expected_quantity",
                "evidence_source",
                "confidence",
                "notes",
                "persisted",
                "applicable",
            ],
            disabled=[
                "group",
                "display_name",
                "persisted",
                "applicable",
            ],
            column_config={
                "action":
                    st.column_config.SelectboxColumn(
                        "Reviewed action",
                        options=list(
                            _canonical_reference_actions
                        ),
                        required=True,
                    ),
                "group":
                    st.column_config.TextColumn(
                        "Media-specific group"
                    ),
                "component_code":
                    st.column_config.SelectboxColumn(
                        "Component",
                        options=component_options,
                        required=True,
                    ),
                "display_name":
                    st.column_config.TextColumn(
                        "Display name"
                    ),
                "variant_key":
                    st.column_config.TextColumn(
                        "Variant key"
                    ),
                "variant_label":
                    st.column_config.TextColumn(
                        "Variant label"
                    ),
                "expectation_state":
                    st.column_config.SelectboxColumn(
                        "Master state",
                        options=list(
                            _canonical_reference_states
                        ),
                        required=True,
                    ),
                "expected_quantity":
                    st.column_config.NumberColumn(
                        "Required quantity",
                        min_value=1,
                        step=1,
                    ),
                "evidence_source":
                    st.column_config.SelectboxColumn(
                        "Evidence source",
                        options=source_options,
                    ),
                "confidence":
                    st.column_config.NumberColumn(
                        "Confidence",
                        min_value=0.0,
                        max_value=1.0,
                        step=0.01,
                        format="%.4f",
                    ),
                "notes":
                    st.column_config.TextColumn(
                        "Reference notes"
                    ),
                "persisted":
                    st.column_config.CheckboxColumn(
                        "Persisted"
                    ),
                "applicable":
                    st.column_config.CheckboxColumn(
                        "Applicable"
                    ),
            },
        )

        edited_rows = edited_frame.to_dict(
            orient="records"
        )

        preview_key = (
            "canonical_reference_preview_"
            f"{selected_pressing_id}"
        )

        if st.button(
            "Preview reviewed changes",
            type="primary",
            key=(
                "canonical_reference_preview_button_"
                f"{selected_pressing_id}"
            ),
        ):
            preview = (
                _canonical_preview_reference_changes(
                    engine,
                    int(
                        selected_pressing_id
                    ),
                    edited_rows,
                )
            )

            st.session_state[
                preview_key
            ] = {
                "preview":
                    preview.to_dict(),
                "rows":
                    edited_rows,
            }

        stored_preview = st.session_state.get(
            preview_key
        )

        if stored_preview:
            preview_data = stored_preview[
                "preview"
            ]

            status = preview_data[
                "status"
            ]

            if status == "READY":
                st.success(
                    "Preview is ready for reviewed application."
                )
            elif status == "NO_CHANGES":
                st.info(
                    "No master-reference mutations were requested."
                )
            else:
                st.error(
                    "Preview is blocked."
                )

            for blocker in preview_data[
                "blockers"
            ]:
                st.error(
                    blocker
                )

            for warning in preview_data[
                "warnings"
            ]:
                st.warning(
                    warning
                )

            operation_rows = (
                _canonical_operation_rows(
                    preview_data[
                        "operations"
                    ]
                )
            )

            if operation_rows:
                st.dataframe(
                    _canonical_pd.DataFrame(
                        operation_rows
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

            st.code(
                preview_data[
                    "confirmation_token"
                ],
                language=None,
            )

            st.caption(
                "Preview digest: "
                + preview_data[
                    "digest"
                ]
            )

            actor = st.text_input(
                "Reviewer",
                key=(
                    "canonical_reference_actor_"
                    f"{selected_pressing_id}"
                ),
            )

            reason = st.text_area(
                "Review reason",
                key=(
                    "canonical_reference_reason_"
                    f"{selected_pressing_id}"
                ),
            )

            scope_confirmed = st.checkbox(
                (
                    "I confirm this master reference applies only "
                    "to exact pressing "
                    f"#{selected_pressing_id} · "
                    f"{selected_pressing.get('catalog_number') or 'No catalog'}."
                ),
                key=(
                    "canonical_reference_scope_"
                    f"{selected_pressing_id}"
                ),
            )

            token_value = st.text_input(
                "Confirmation token",
                key=(
                    "canonical_reference_token_"
                    f"{selected_pressing_id}"
                ),
            )

            apply_disabled = not (
                preview_data[
                    "ready"
                ]
                and actor.strip()
                and reason.strip()
                and scope_confirmed
                and token_value.strip()
            )

            if st.button(
                "Apply reviewed master reference",
                type="primary",
                disabled=apply_disabled,
                key=(
                    "canonical_reference_apply_"
                    f"{selected_pressing_id}"
                ),
            ):
                result = (
                    _canonical_apply_reference_changes(
                        engine,
                        int(
                            selected_pressing_id
                        ),
                        stored_preview[
                            "rows"
                        ],
                        actor=actor,
                        reason=reason,
                        confirmation_token=token_value,
                        confirmed_catalog=str(
                            selected_pressing.get(
                                "catalog_number"
                            )
                            or ""
                        ),
                        scope_confirmed=scope_confirmed,
                    )
                )

                st.success(
                    "Master reference applied: "
                    f"{result['applied_operation_count']} "
                    "reviewed mutation(s)."
                )

                st.session_state.pop(
                    preview_key,
                    None,
                )

                st.rerun()

    with tabs[1]:
        st.subheader(
            "Create an exact pressing"
        )

        st.write(
            "Create the exact pressing first, then return to the "
            "Master reference tab to define its media-aware contents."
        )

        _canonical_render_create_pressing(
            engine
        )

    with tabs[2]:
        st.subheader(
            "Assigned listings and derived completeness"
        )

        assigned_rows = (
            _canonical_list_assigned_listings(
                engine,
                int(
                    selected_pressing_id
                ),
            )
        )

        if assigned_rows:
            st.dataframe(
                _canonical_pd.DataFrame(
                    assigned_rows
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info(
                "No auction listings are assigned to this exact pressing."
            )

        st.caption(
            "New auction observations remain listing-specific. "
            "Completeness is evaluated against this master reference."
        )

    with tabs[3]:
        st.subheader(
            "Immutable reference audit history"
        )

        audit_rows = (
            _canonical_list_reference_audit(
                engine,
                int(
                    selected_pressing_id
                ),
            )
        )

        if audit_rows:
            st.dataframe(
                _canonical_pd.DataFrame(
                    audit_rows
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info(
                "No audited master-reference mutation exists yet."
            )


# canonical-media-aware-reference:end


def main() -> None:
    """Render the general pressing-reference workbench."""
    _render_canonical_media_reference()
    return

    st.title(
        "📦 Pressing Reference Workbench"
    )

    st.caption(
        "Pressing Completeness Reference for every title and "
        "exact pressing. "
        "A collector-grade reference library for every title and "
        "exact pressing. Shared expected components, per-listing "
        "observations, deterministic percentages, and existing "
        "market verdicts remain separate and auditable."
    )

    message = st.session_state.pop(
        "pressing_workbench_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    search = st.text_input(
        "Search pressing library",
        placeholder=(
            "Artist, title, catalog number, matrix, "
            "label, format, or variant"
        ),
    )

    pressings = list_pressings(
        engine,
        search,
    )

    library_rows = list_reference_library(
        engine,
        search,
    )

    pressing_by_id = {
        int(row["id"]): row
        for row in pressings
    }

    pressing_ids = list(
        pressing_by_id
    )

    selected_pressing_id: int | None = None

    if pressing_ids:
        preferred_id = st.session_state.get(
            "workbench_pressing_id"
        )

        selected_index = (
            pressing_ids.index(
                preferred_id
            )
            if preferred_id in pressing_ids
            else 0
        )

        selected_pressing_id = st.selectbox(
            "Exact pressing",
            options=pressing_ids,
            index=selected_index,
            format_func=lambda value: (
                _pressing_label(
                    pressing_by_id[value]
                )
            ),
        )

        st.session_state[
            "workbench_pressing_id"
        ] = selected_pressing_id

    tabs = st.tabs(
        [
            "Reference library",
            "Create pressing",
            "Completeness worksheet",
            "CSV and cloning",
            "Listing verdicts",
        ]
    )

    with tabs[0]:
        _reference_library_panel(
            engine,
            search,
        )

        if library_rows:
            st.caption(
                f"{len(library_rows)} pressing references shown."
            )

    with tabs[1]:
        _create_pressing_panel(
            engine
        )

    if selected_pressing_id is None:
        for tab in tabs[2:]:
            with tab:
                st.info(
                    "Create or select an exact pressing first."
                )

        return

    with tabs[2]:
        _worksheet_panel(
            engine,
            selected_pressing_id,
        )

    with tabs[3]:
        _transfer_panel(
            engine,
            selected_pressing_id,
            pressings,
        )

    with tabs[4]:
        _verdict_panel(
            engine,
            selected_pressing_id,
        )


main()
