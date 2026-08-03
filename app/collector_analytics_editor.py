"""Streamlit editor for collector analytics curation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

import pandas as pd
import streamlit as st
from sqlalchemy.engine import Engine

from app.collector_review_support import (
    listing_identity,
)
from auction_etl.services.collector_curation import (
    BIDDER_STATES,
    EXPECTATION_STATES,
    MATCH_BASES,
    OBSERVATION_STATES,
    PRESSING_GENERATIONS,
    PRICE_BASES,
    assign_existing_pressing,
    create_and_assign_pressing,
    list_component_types,
    list_condition_grades,
    list_pressings,
    load_analysis_input,
    load_assignment,
    load_behavior,
    load_completeness,
    load_component_rows,
    load_condition,
    load_score_snapshot,
    replace_component_rows,
    save_analysis_input,
    save_behavior,
    save_condition,
)
# collector-evidence-assistant:import-start
from auction_etl.services.collector_evidence import (
    apply_evidence_report,
    build_evidence_report,
)
# collector-evidence-assistant:import-end



def _clean(value: Any) -> str:
    """Return display-safe text."""
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value).strip()


def _first(
    row: Mapping[str, Any],
    *keys: str,
    default: Any = "",
) -> Any:
    """Return the first non-empty mapping value."""
    for key in keys:
        value = row.get(key)

        if value is None:
            continue

        if isinstance(value, float) and pd.isna(value):
            continue

        if str(value).strip():
            return value

    return default


def _select_index(
    options: list[str] | tuple[str, ...],
    value: Any,
) -> int:
    """Return a safe selectbox index."""
    normalized = _clean(value)

    try:
        return list(options).index(normalized)
    except ValueError:
        return 0


def _optional_text_number(value: Any) -> str:
    """Render nullable numeric values in text inputs."""
    return _clean(value)


def select_listing_record(
    dataframe: pd.DataFrame,
    selected_identity: str | None,
) -> dict[str, Any] | None:
    """Find the selected listing using the shared stable identity."""
    if (
        dataframe.empty
        or not selected_identity
        or "marketplace" not in dataframe.columns
        or "listing_id" not in dataframe.columns
    ):
        return None

    for _, row in dataframe.iterrows():
        marketplace = _clean(
            row.get("marketplace")
        )
        listing_id_value = _clean(
            row.get("listing_id")
        )

        if (
            listing_identity(
                marketplace,
                listing_id_value,
            )
            == selected_identity
        ):
            return row.to_dict()

    return None


def _rerun(message: str) -> None:
    """Display a success message after refreshing the editor."""
    st.session_state[
        "_collector_analytics_notice"
    ] = message

    st.rerun()


def _render_notice() -> None:
    """Render one pending editor notification."""
    message = st.session_state.pop(
        "_collector_analytics_notice",
        None,
    )

    if message:
        st.success(message)


def _render_listing_summary(
    selected: Mapping[str, Any],
) -> None:
    """Render immutable listing context."""
    columns = st.columns(4)

    columns[0].metric(
        "Marketplace",
        _clean(
            selected.get("marketplace")
        )
        or "Unknown",
    )

    columns[1].metric(
        "Listing ID",
        _clean(
            selected.get("listing_id")
        )
        or "Unknown",
    )

    columns[2].metric(
        "Media",
        _clean(
            _first(
                selected,
                "media_display",
                "media_type",
            )
        )
        or "Unknown",
    )

    columns[3].metric(
        "Catalog",
        _clean(
            _first(
                selected,
                "manual_catalog_number",
                "catalog_number",
                "pressing_token",
            )
        )
        or "Unknown",
    )

    st.subheader(
        _clean(
            selected.get("title")
        )
        or "Untitled listing"
    )

    seller = _clean(
        selected.get("seller")
    )

    if seller:
        st.caption(
            f"Seller: {seller}"
        )


def _render_current_assignment(
    assignment: Mapping[str, Any] | None,
) -> None:
    """Display current exact-pressing assignment."""
    if not assignment:
        st.info(
            "No pressing identity is assigned yet."
        )
        return

    st.success(
        "Assigned pressing "
        f"#{assignment['pressing_id']}: "
        f"{assignment['display_artist']} — "
        f"{assignment['display_title']}"
    )

    columns = st.columns(5)

    columns[0].metric(
        "Catalog",
        _clean(
            assignment.get(
                "catalog_number"
            )
        )
        or "Unknown",
    )

    columns[1].metric(
        "Region",
        _clean(
            assignment.get("region")
        )
        or "Unknown",
    )

    columns[2].metric(
        "Generation",
        _clean(
            assignment.get("generation")
        )
        or "Unknown",
    )

    columns[3].metric(
        "Match basis",
        _clean(
            assignment.get("match_basis")
        )
        or "Unknown",
    )

    columns[4].metric(
        "Confidence",
        _clean(
            assignment.get(
                "match_confidence"
            )
        )
        or "Unknown",
    )


def _render_pressing_editor(
    engine: Engine,
    selected: Mapping[str, Any],
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render exact pressing assignment controls."""
    assignment = load_assignment(
        engine,
        marketplace,
        listing_id_value,
    )

    pressings = list_pressings(
        engine
    )

    _render_current_assignment(
        assignment
    )

    modes = [
        "Create or update exact pressing",
    ]

    if pressings:
        modes.append(
            "Assign an existing pressing"
        )

    mode = st.radio(
        "Assignment action",
        modes,
        horizontal=True,
        key=(
            "collector_analytics:"
            f"{marketplace}:"
            f"{listing_id_value}:"
            "pressing_mode"
        ),
    )

    if mode == "Assign an existing pressing":
        labels = {
            (
                f"#{pressing['id']} · "
                f"{pressing['display_artist']} — "
                f"{pressing['display_title']} · "
                f"{pressing['catalog_number'] or 'no catalog'} · "
                f"{pressing['region'] or 'unknown region'}"
            ):
                pressing["id"]
            for pressing in pressings
        }

        with st.form(
            "collector_assign_existing_pressing"
        ):
            selected_label = st.selectbox(
                "Existing pressing",
                tuple(labels),
            )

            notes = st.text_area(
                "Assignment notes",
                height=90,
            )

            submitted = st.form_submit_button(
                "Assign existing pressing",
                type="primary",
                width="stretch",
            )

        if submitted:
            assign_existing_pressing(
                engine,
                marketplace,
                listing_id_value,
                labels[selected_label],
                notes=notes,
            )

            _rerun(
                "Existing pressing assigned."
            )

        return

    current = assignment or {}

    with st.form(
        "collector_create_pressing"
    ):
        st.caption(
            "The natural pressing identity is release family + "
            "catalog + matrix + region + media + variant key."
        )

        family_columns = st.columns(3)

        display_artist = family_columns[
            0
        ].text_input(
            "Canonical artist",
            value=_clean(
                _first(
                    current,
                    "display_artist",
                    default=_first(
                        selected,
                        "artist_display",
                        "artist",
                        default="Teresa Teng",
                    ),
                )
            ),
        )

        display_title = family_columns[
            1
        ].text_input(
            "Canonical release title",
            value=_clean(
                _first(
                    current,
                    "display_title",
                    default=selected.get(
                        "title",
                        "",
                    ),
                )
            ),
        )

        original_release_year = (
            family_columns[2].text_input(
                "Original release year",
                value=_optional_text_number(
                    current.get(
                        "original_release_year"
                    )
                ),
            )
        )

        identity_columns = st.columns(3)

        catalog_number = identity_columns[
            0
        ].text_input(
            "Catalog number",
            value=_clean(
                _first(
                    current,
                    "catalog_number",
                    default=_first(
                        selected,
                        "manual_catalog_number",
                        "catalog_number",
                    ),
                )
            ),
        )

        matrix_number = identity_columns[
            1
        ].text_input(
            "Matrix number",
            value=_clean(
                current.get(
                    "matrix_number"
                )
            ),
        )

        label_name = identity_columns[
            2
        ].text_input(
            "Label",
            value=_clean(
                current.get(
                    "label_name"
                )
            ),
        )

        geography_columns = st.columns(3)

        region = geography_columns[
            0
        ].text_input(
            "Pressing region",
            value=_clean(
                _first(
                    current,
                    "region",
                    default=_first(
                        selected,
                        "manual_region",
                        "pressing_region",
                    ),
                )
            ),
        )

        country = geography_columns[
            1
        ].text_input(
            "Country",
            value=_clean(
                current.get("country")
            ),
        )

        media_type = geography_columns[
            2
        ].text_input(
            "Media type",
            value=_clean(
                _first(
                    current,
                    "media_type",
                    default=_first(
                        selected,
                        "manual_media_type",
                        "media_type",
                        "media_display",
                    ),
                )
            ),
        )

        format_columns = st.columns(4)

        format_detail = format_columns[
            0
        ].text_input(
            "Format detail",
            value=_clean(
                current.get(
                    "format_detail"
                )
            ),
        )

        disc_count = format_columns[
            1
        ].text_input(
            "Disc count",
            value=_optional_text_number(
                _first(
                    current,
                    "disc_count",
                    default=selected.get(
                        "disc_count"
                    ),
                )
            ),
        )

        release_year = format_columns[
            2
        ].text_input(
            "Pressing year",
            value=_optional_text_number(
                current.get(
                    "release_year"
                )
            ),
        )

        generation = format_columns[
            3
        ].selectbox(
            "Generation",
            PRESSING_GENERATIONS,
            index=_select_index(
                PRESSING_GENERATIONS,
                current.get(
                    "generation",
                    "UNKNOWN",
                ),
            ),
        )

        variant_columns = st.columns(3)

        pressing_variant_key = (
            variant_columns[0].text_input(
                "Variant key",
                value=_clean(
                    current.get(
                        "pressing_variant_key"
                    )
                ),
                help=(
                    "Examples: pink-obi, white-label, "
                    "heavyweight-2026."
                ),
            )
        )

        pressing_variant_label = (
            variant_columns[1].text_input(
                "Variant label",
                value=_clean(
                    current.get(
                        "pressing_variant_label"
                    )
                ),
            )
        )

        parent_first_press_id = (
            variant_columns[2].text_input(
                "Parent first-press ID",
                value=_optional_text_number(
                    current.get(
                        "parent_first_press_id"
                    )
                ),
                help=(
                    "Use for repress-to-first-press comparisons."
                ),
            )
        )

        assignment_columns = st.columns(2)

        match_basis = assignment_columns[
            0
        ].selectbox(
            "Match basis",
            MATCH_BASES,
            index=_select_index(
                MATCH_BASES,
                current.get(
                    "match_basis",
                    "MANUAL",
                ),
            ),
        )

        match_confidence = (
            assignment_columns[1].text_input(
                "Match confidence (0–1)",
                value=_optional_text_number(
                    current.get(
                        "match_confidence",
                        "1",
                    )
                ),
            )
        )

        family_notes = st.text_area(
            "Release-family notes",
            value=_clean(
                current.get(
                    "family_notes"
                )
            ),
            height=80,
        )

        pressing_notes = st.text_area(
            "Pressing notes",
            value=_clean(
                current.get(
                    "pressing_notes"
                )
            ),
            height=80,
        )

        assignment_notes = st.text_area(
            "Assignment notes",
            value=_clean(
                current.get(
                    "assignment_notes"
                )
            ),
            height=80,
        )

        submitted = st.form_submit_button(
            "Save exact pressing assignment",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    pressing_id = create_and_assign_pressing(
        engine,
        marketplace,
        listing_id_value,
        {
            "display_artist":
                display_artist,
            "display_title":
                display_title,
            "original_release_year":
                original_release_year,
            "catalog_number":
                catalog_number,
            "matrix_number":
                matrix_number,
            "label_name":
                label_name,
            "region":
                region,
            "country":
                country,
            "media_type":
                media_type,
            "format_detail":
                format_detail,
            "disc_count":
                disc_count,
            "release_year":
                release_year,
            "generation":
                generation,
            "pressing_variant_key":
                pressing_variant_key,
            "pressing_variant_label":
                pressing_variant_label,
            "parent_first_press_id":
                parent_first_press_id,
            "match_basis":
                match_basis,
            "match_confidence":
                match_confidence,
            "family_notes":
                family_notes,
            "pressing_notes":
                pressing_notes,
            "assignment_notes":
                assignment_notes,
        },
    )

    _rerun(
        f"Pressing #{pressing_id} saved and assigned."
    )


def _render_completeness(
    completeness: Mapping[str, Any] | None,
) -> None:
    """Render derived completeness analytics."""
    if not completeness:
        st.info(
            "Completeness is unavailable until a pressing "
            "and expected components are saved."
        )
        return

    columns = st.columns(4)

    columns[0].metric(
        "Required",
        completeness.get(
            "required_component_count"
        )
        or 0,
    )

    columns[1].metric(
        "Present",
        completeness.get(
            "present_required_component_count"
        )
        or 0,
    )

    ratio = completeness.get(
        "completeness_ratio"
    )

    columns[2].metric(
        "Ratio",
        (
            f"{Decimal(str(ratio)):.2%}"
            if ratio is not None
            else "Unknown"
        ),
    )

    columns[3].metric(
        "Status",
        _clean(
            completeness.get(
                "completeness_status"
            )
        )
        or "Unknown",
    )

    missing = (
        completeness.get(
            "missing_components"
        )
        or []
    )

    unverified = (
        completeness.get(
            "unverified_components"
        )
        or []
    )

    unexpected = (
        completeness.get(
            "unexpected_components"
        )
        or []
    )

    st.caption(
        "Missing: "
        f"{', '.join(missing) or 'none'} · "
        "Unverified: "
        f"{', '.join(unverified) or 'none'} · "
        "Unexpected: "
        f"{', '.join(unexpected) or 'none'}"
    )


def _render_component_editor(
    engine: Engine,
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render expected and observed component curation."""
    assignment = load_assignment(
        engine,
        marketplace,
        listing_id_value,
    )

    if not assignment:
        st.warning(
            "Assign an exact pressing before editing components."
        )
        return

    pressing_id = int(
        assignment["pressing_id"]
    )

    component_types = list_component_types(
        engine
    )

    component_codes = [
        row["code"]
        for row in component_types
    ]

    grades = list_condition_grades(
        engine
    )

    grade_codes = [
        ""
    ] + [
        row["code"]
        for row in grades
    ]

    rows = load_component_rows(
        engine,
        marketplace,
        listing_id_value,
        pressing_id,
    )

    dataframe = pd.DataFrame(
        rows
    )

    editable_columns = [
        "component_code",
        "variant_key",
        "variant_label",
        "expectation_state",
        "expected_quantity",
        "expectation_evidence_source",
        "expectation_confidence",
        "expectation_notes",
        "observation_state",
        "observed_quantity",
        "normalized_condition",
        "source_condition_text",
        "observation_evidence_source",
        "observation_confidence",
        "evidence_url",
        "observation_notes",
    ]

    for column in editable_columns:
        if column not in dataframe.columns:
            dataframe[column] = None

    st.warning(
        "Expected components belong to pressing "
        f"#{pressing_id} and therefore apply to every listing "
        "assigned to that pressing."
    )

    edited = st.data_editor(
        dataframe[editable_columns],
        hide_index=True,
        width="stretch",
        num_rows="dynamic",
        column_config={
            "component_code":
                st.column_config.SelectboxColumn(
                    "Component",
                    options=component_codes,
                    required=True,
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
                    "Expected",
                    options=EXPECTATION_STATES,
                    required=True,
                ),
            "expected_quantity":
                st.column_config.NumberColumn(
                    "Expected qty",
                    min_value=1,
                    step=1,
                ),
            "expectation_confidence":
                st.column_config.NumberColumn(
                    "Expected confidence",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.05,
                ),
            "observation_state":
                st.column_config.SelectboxColumn(
                    "Observed",
                    options=OBSERVATION_STATES,
                    required=True,
                ),
            "observed_quantity":
                st.column_config.NumberColumn(
                    "Observed qty",
                    min_value=0,
                    step=1,
                ),
            "normalized_condition":
                st.column_config.SelectboxColumn(
                    "Component grade",
                    options=grade_codes,
                ),
            "observation_confidence":
                st.column_config.NumberColumn(
                    "Observed confidence",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.05,
                ),
            "evidence_url":
                st.column_config.LinkColumn(
                    "Evidence URL"
                ),
        },
        key=(
            "collector_component_editor:"
            f"{marketplace}:"
            f"{listing_id_value}:"
            f"{pressing_id}"
        ),
    )

    if st.button(
        "Save expected and observed components",
        type="primary",
        width="stretch",
        key=(
            "collector_component_save:"
            f"{marketplace}:"
            f"{listing_id_value}"
        ),
    ):
        payload = (
            edited.where(
                pd.notna(edited),
                None,
            )
            .to_dict(
                orient="records"
            )
        )

        payload = [
            row
            for row in payload
            if _clean(
                row.get("component_code")
            )
        ]

        replace_component_rows(
            engine,
            marketplace,
            listing_id_value,
            pressing_id,
            payload,
        )

        _rerun(
            "Expected and observed components saved."
        )

    _render_completeness(
        load_completeness(
            engine,
            marketplace,
            listing_id_value,
        )
    )


def _render_condition_editor(
    engine: Engine,
    selected: Mapping[str, Any],
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render normalized condition controls."""
    current = (
        load_condition(
            engine,
            marketplace,
            listing_id_value,
        )
        or {}
    )

    grades = list_condition_grades(
        engine
    )

    options = [
        ""
    ] + [
        row["code"]
        for row in grades
    ]

    with st.form(
        "collector_condition_form"
    ):
        columns = st.columns(2)

        media_grade = columns[
            0
        ].selectbox(
            "Normalized media grade",
            options,
            index=_select_index(
                options,
                current.get(
                    "media_grade_code"
                ),
            ),
        )

        cover_grade = columns[
            1
        ].selectbox(
            "Normalized cover grade",
            options,
            index=_select_index(
                options,
                current.get(
                    "cover_grade_code"
                ),
            ),
        )

        source_columns = st.columns(2)

        source_media = source_columns[
            0
        ].text_input(
            "Source media condition",
            value=_clean(
                _first(
                    current,
                    "source_media_condition",
                    default=selected.get(
                        "condition_media"
                    ),
                )
            ),
        )

        source_cover = source_columns[
            1
        ].text_input(
            "Source cover condition",
            value=_clean(
                _first(
                    current,
                    "source_cover_condition",
                    default=selected.get(
                        "condition_cover"
                    ),
                )
            ),
        )

        numeric_columns = st.columns(2)

        factor_override = numeric_columns[
            0
        ].text_input(
            "Market factor override",
            value=_optional_text_number(
                current.get(
                    "condition_factor_override"
                )
            ),
        )

        confidence = numeric_columns[
            1
        ].text_input(
            "Confidence (0–1)",
            value=_optional_text_number(
                current.get("confidence")
            ),
        )

        notes = st.text_area(
            "Condition notes",
            value=_clean(
                current.get("notes")
            ),
            height=100,
        )

        submitted = st.form_submit_button(
            "Save normalized condition",
            type="primary",
            width="stretch",
        )

    if submitted:
        save_condition(
            engine,
            marketplace,
            listing_id_value,
            {
                "media_grade_code":
                    media_grade,
                "cover_grade_code":
                    cover_grade,
                "source_media_condition":
                    source_media,
                "source_cover_condition":
                    source_cover,
                "condition_factor_override":
                    factor_override,
                "confidence":
                    confidence,
                "notes":
                    notes,
            },
        )

        _rerun(
            "Normalized condition saved."
        )

    if grades:
        grade_table = pd.DataFrame(
            grades
        )[
            [
                "code",
                "display_name",
                "sort_rank",
                "score_20",
                "market_value_factor",
            ]
        ]

        with st.expander(
            "Condition grade dictionary"
        ):
            st.dataframe(
                grade_table,
                hide_index=True,
                width="stretch",
            )


def _render_behavior_editor(
    engine: Engine,
    selected: Mapping[str, Any],
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render bidder visibility and closing-window evidence."""
    current = (
        load_behavior(
            engine,
            marketplace,
            listing_id_value,
        )
        or {}
    )

    default_state = (
        "NOT_EXPOSED"
        if marketplace.lower() == "buyee"
        else "UNAVAILABLE"
    )

    bidder_state = _clean(
        current.get(
            "distinct_bidder_state"
        )
    ) or default_state

    if marketplace.lower() == "buyee":
        st.info(
            "Buyee/Yahoo Japan bid totals do not reveal a reliable "
            "distinct-human bidder count. Keep NOT_EXPOSED unless "
            "external evidence proves otherwise."
        )

    with st.form(
        "collector_behavior_form"
    ):
        bidder_columns = st.columns(3)

        distinct_bidder_state = (
            bidder_columns[0].selectbox(
                "Distinct bidder state",
                BIDDER_STATES,
                index=_select_index(
                    BIDDER_STATES,
                    bidder_state,
                ),
            )
        )

        distinct_bidder_count = (
            bidder_columns[1].text_input(
                "Distinct bidder count",
                value=_optional_text_number(
                    current.get(
                        "distinct_bidder_count"
                    )
                ),
                help=(
                    "Ignored for NOT_EXPOSED and UNAVAILABLE."
                ),
            )
        )

        distinct_bidder_source = (
            bidder_columns[2].text_input(
                "Bidder-count source",
                value=_clean(
                    current.get(
                        "distinct_bidder_source"
                    )
                ),
            )
        )

        closing_columns = st.columns(4)

        closing_window_minutes = (
            closing_columns[0].text_input(
                "Closing window minutes",
                value=_optional_text_number(
                    current.get(
                        "closing_window_minutes"
                    )
                ),
            )
        )

        closing_window_start_price = (
            closing_columns[1].text_input(
                "Window start price",
                value=_optional_text_number(
                    current.get(
                        "closing_window_start_price"
                    )
                ),
            )
        )

        closing_window_final_price = (
            closing_columns[2].text_input(
                "Window final price",
                value=_optional_text_number(
                    current.get(
                        "closing_window_final_price"
                    )
                ),
            )
        )

        closing_window_currency = (
            closing_columns[3].text_input(
                "Window currency",
                value=_clean(
                    _first(
                        current,
                        "closing_window_currency",
                        default=selected.get(
                            "currency"
                        ),
                    )
                ),
            )
        )

        escalation_columns = st.columns(2)

        escalation_ratio = escalation_columns[
            0
        ].text_input(
            "Escalation ratio",
            value=_optional_text_number(
                current.get(
                    "closing_window_escalation_ratio"
                )
            ),
            help=(
                "Example: 1.725 represents a 172.5% increase."
            ),
        )

        reserve_status = escalation_columns[
            1
        ].text_input(
            "Reserve status",
            value=_clean(
                current.get(
                    "reserve_status"
                )
            ),
        )

        notes = st.text_area(
            "Auction behavior notes",
            value=_clean(
                current.get("notes")
            ),
            height=110,
        )

        submitted = st.form_submit_button(
            "Save auction behavior",
            type="primary",
            width="stretch",
        )

    if submitted:
        save_behavior(
            engine,
            marketplace,
            listing_id_value,
            {
                "distinct_bidder_state":
                    distinct_bidder_state,
                "distinct_bidder_count":
                    distinct_bidder_count,
                "distinct_bidder_source":
                    distinct_bidder_source,
                "closing_window_minutes":
                    closing_window_minutes,
                "closing_window_start_price":
                    closing_window_start_price,
                "closing_window_final_price":
                    closing_window_final_price,
                "closing_window_currency":
                    closing_window_currency,
                "closing_window_escalation_ratio":
                    escalation_ratio,
                "reserve_status":
                    reserve_status,
                "notes":
                    notes,
            },
        )

        _rerun(
            "Auction behavior evidence saved."
        )


def _metric_value(value: Any) -> str:
    """Format a nullable analytics value."""
    if value is None:
        return "—"

    if isinstance(value, Decimal):
        return f"{value:.2f}"

    if isinstance(value, float):
        return f"{value:.2f}"

    return str(value)


def _render_score_snapshot(
    snapshot: Mapping[str, Any] | None,
) -> None:
    """Render calculated score and incident outputs."""
    if not snapshot:
        st.info(
            "No calculated score row is available."
        )
        return

    score_columns = st.columns(5)

    score_columns[0].metric(
        "Title strength",
        _metric_value(
            snapshot.get(
                "title_strength_score"
            )
        ),
    )

    score_columns[1].metric(
        "Completeness",
        _metric_value(
            snapshot.get(
                "completeness_score"
            )
        ),
    )

    score_columns[2].metric(
        "Condition",
        _metric_value(
            snapshot.get(
                "condition_score"
            )
        ),
    )

    score_columns[3].metric(
        "Auction behavior",
        _metric_value(
            snapshot.get(
                "auction_behavior_score"
            )
        ),
    )

    score_columns[4].metric(
        "Market context",
        _metric_value(
            snapshot.get(
                "market_context_score"
            )
        ),
    )

    summary_columns = st.columns(4)

    summary_columns[0].metric(
        "Plushie Index",
        _metric_value(
            snapshot.get(
                "plushie_index"
            )
        ),
    )

    summary_columns[1].metric(
        "Plushie coverage",
        _metric_value(
            snapshot.get(
                "plushie_coverage"
            )
        ),
    )

    summary_columns[2].metric(
        "Emotional damage",
        _metric_value(
            snapshot.get(
                "emotional_damage_score"
            )
        ),
    )

    summary_columns[3].metric(
        "Incident class",
        _clean(
            snapshot.get(
                "incident_class"
            )
        )
        or "Unclassified",
    )

    detail = {
        "Expectation deviation":
            snapshot.get(
                "expectation_deviation"
            ),
        "Late spike":
            snapshot.get(
                "late_spike"
            ),
        "Historical-anchor deviation":
            snapshot.get(
                "historical_anchor_deviation"
            ),
        "Completeness contradiction":
            snapshot.get(
                "completeness_contradiction"
            ),
        "First-press distortion":
            snapshot.get(
                "first_press_distortion"
            ),
        "Bidder-war intensity":
            snapshot.get(
                "bidder_war_intensity"
            ),
        "Damage coverage":
            snapshot.get(
                "emotional_damage_coverage"
            ),
    }

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Metric": key,
                    "Value": value,
                }
                for key, value
                in detail.items()
            ]
        ),
        hide_index=True,
        width="stretch",
    )


# collector-evidence-assistant:function-start
def _render_evidence_assistant(
    engine: Engine,
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render conservative database-backed suggestions."""
    report = build_evidence_report(
        engine,
        marketplace,
        listing_id_value,
    )

    with st.expander(
        "Evidence-backed suggestions",
        expanded=False,
    ):
        st.caption(
            "Exact condition tokens only. Historical anchors "
            "require at least three high-confidence listings "
            "assigned to the same pressing. Closing-window "
            "analytics require a timestamped price snapshot."
        )

        columns = st.columns(3)

        if report.condition is None:
            columns[0].metric(
                "Condition",
                "No safe proposal",
            )
        else:
            grade_parts = [
                value
                for value in (
                    report.condition.media_grade_code,
                    report.condition.cover_grade_code,
                )
                if value
            ]

            columns[0].metric(
                "Condition",
                " / ".join(grade_parts),
            )

        if report.historical_anchor is None:
            columns[1].metric(
                "Historical anchor",
                "Not ready",
                delta=(
                    f"{report.comparable_count} "
                    "comparables"
                ),
            )
        else:
            columns[1].metric(
                "Historical anchor",
                (
                    f"${report.historical_anchor.anchor_usd}"
                ),
                delta=(
                    f"{report.historical_anchor.sample_count} "
                    "comparables"
                ),
            )

        if report.closing_window is None:
            columns[2].metric(
                "Closing window",
                "Not available",
                delta=(
                    f"{report.snapshot_count} snapshots"
                ),
            )
        else:
            columns[2].metric(
                "Closing window",
                (
                    f"{report.closing_window.escalation_ratio:.2%}"
                ),
                delta=(
                    f"{report.closing_window.minutes_before_close} "
                    "minutes"
                ),
            )

        if report.blockers:
            st.caption(
                " · ".join(report.blockers)
            )

        actions = report.ready_actions

        if actions:
            st.success(
                "Ready: "
                + ", ".join(actions)
            )
        else:
            st.info(
                "No evidence-backed write is currently ready. "
                "Nothing will be fabricated."
            )

        submitted = st.button(
            "Apply evidence-backed suggestions",
            type="primary",
            width="stretch",
            disabled=not actions,
            key=(
                "collector_evidence_apply:"
                f"{marketplace}:"
                f"{listing_id_value}"
            ),
        )

        if submitted:
            applied = apply_evidence_report(
                engine,
                report,
            )

            _rerun(
                (
                    "Evidence-backed suggestions applied: "
                    + ", ".join(applied)
                )
                if applied
                else (
                    "No evidence-backed changes were required."
                )
            )


# collector-evidence-assistant:function-end


def _render_analysis_editor(
    engine: Engine,
    marketplace: str,
    listing_id_value: str,
) -> None:
    """Render manual normalization and scoring inputs."""
    current = (
        load_analysis_input(
            engine,
            marketplace,
            listing_id_value,
        )
        or {}
    )

    with st.form(
        "collector_analysis_form"
    ):
        price_basis = st.selectbox(
            "Price basis",
            PRICE_BASES,
            index=_select_index(
                PRICE_BASES,
                current.get(
                    "price_basis",
                    "GROSS",
                ),
            ),
            help=(
                "Choose hammer, gross with tax, or landed cost."
            ),
        )

        factor_columns = st.columns(2)

        completeness_factor = (
            factor_columns[0].text_input(
                "Completeness market factor",
                value=_optional_text_number(
                    current.get(
                        "completeness_market_factor"
                    )
                ),
            )
        )

        condition_factor = factor_columns[
            1
        ].text_input(
            "Condition factor override",
            value=_optional_text_number(
                current.get(
                    "condition_factor_override"
                )
            ),
        )

        score_columns = st.columns(3)

        title_strength = score_columns[
            0
        ].text_input(
            "Title strength score (0–20)",
            value=_optional_text_number(
                current.get(
                    "title_strength_score"
                )
            ),
        )

        market_context = score_columns[
            1
        ].text_input(
            "Market context score (0–20)",
            value=_optional_text_number(
                current.get(
                    "market_context_score"
                )
            ),
        )

        behavior_score = score_columns[
            2
        ].text_input(
            "Manual behavior score (0–20)",
            value=_optional_text_number(
                current.get(
                    "manual_auction_behavior_score"
                )
            ),
        )

        anchor_columns = st.columns(2)

        expectation_price = anchor_columns[
            0
        ].text_input(
            "Expectation price USD",
            value=_optional_text_number(
                current.get(
                    "expectation_price_usd"
                )
            ),
        )

        historical_anchor = anchor_columns[
            1
        ].text_input(
            "Historical anchor USD",
            value=_optional_text_number(
                current.get(
                    "historical_anchor_usd"
                )
            ),
        )

        notes = st.text_area(
            "Analysis notes",
            value=_clean(
                current.get("notes")
            ),
            height=110,
        )

        submitted = st.form_submit_button(
            "Save analysis inputs",
            type="primary",
            width="stretch",
        )

    if submitted:
        save_analysis_input(
            engine,
            marketplace,
            listing_id_value,
            {
                "price_basis":
                    price_basis,
                "completeness_market_factor":
                    completeness_factor,
                "condition_factor_override":
                    condition_factor,
                "title_strength_score":
                    title_strength,
                "market_context_score":
                    market_context,
                "manual_auction_behavior_score":
                    behavior_score,
                "expectation_price_usd":
                    expectation_price,
                "historical_anchor_usd":
                    historical_anchor,
                "notes":
                    notes,
            },
        )

        _rerun(
            "Analysis inputs saved."
        )

    st.subheader(
        "Calculated analytics"
    )

    _render_score_snapshot(
        load_score_snapshot(
            engine,
            marketplace,
            listing_id_value,
        )
    )


def render_collector_analytics_editor(
    engine: Engine,
    records: pd.DataFrame,
    selected_identity: str | None,
) -> None:
    """Render pressing, component, condition, and score curation."""
    _render_notice()

    selected = select_listing_record(
        records,
        selected_identity,
    )

    if selected is None:
        st.info(
            "Select a listing in the Listings tab, then return "
            "here to curate its exact pressing and analytics."
        )
        return

    marketplace = _clean(
        selected.get("marketplace")
    )

    listing_id_value = _clean(
        selected.get("listing_id")
    )

    if not marketplace or not listing_id_value:
        st.error(
            "The selected listing has no stable marketplace/listing ID."
        )
        return

    _render_listing_summary(
        selected
    )

    tabs = st.tabs(
        (
            "Pressing",
            "Components",
            "Condition",
            "Auction behavior",
            "Scores and damage",
        )
    )

    with tabs[0]:
        _render_pressing_editor(
            engine,
            selected,
            marketplace,
            listing_id_value,
        )

    with tabs[1]:
        _render_component_editor(
            engine,
            marketplace,
            listing_id_value,
        )

    with tabs[2]:
        _render_condition_editor(
            engine,
            selected,
            marketplace,
            listing_id_value,
        )

    with tabs[3]:
        _render_behavior_editor(
            engine,
            selected,
            marketplace,
            listing_id_value,
        )

    with tabs[4]:
        _render_evidence_assistant(
            engine,
            marketplace,
            listing_id_value,
        )

        _render_analysis_editor(
            engine,
            marketplace,
            listing_id_value,
        )
