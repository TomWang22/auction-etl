"""General normalization workbench and bulk curation."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.normalization_workbench import (
    COMPARABLE_DECISIONS,
    apply_workbook,
    export_workbook_csv,
    list_comparable_candidates,
    list_queue,
    list_reference_candidates,
    list_work_audit,
    list_work_batches,
    preview_workbook,
    queue_summary,
    save_comparable_review,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Normalization Workbench",
    page_icon="🧭",
    layout="wide",
)
render_navigation(current_page="pages/7_Normalization_Workbench.py")


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


def _listing_label(
    row: dict[str, Any],
) -> str:
    """Build one readable listing label."""
    return (
        f"{row['marketplace']}/"
        f"{row['listing_id']} · "
        f"{row.get('title') or 'Untitled listing'}"
    )


def _identity_options(
    rows: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Return unique listing identities."""
    return list(
        dict.fromkeys(
            (
                str(row["marketplace"]),
                str(row["listing_id"]),
            )
            for row in rows
        )
    )


def _render_queue(
    engine: Engine,
) -> None:
    """Render the prioritized normalization queue."""
    st.subheader(
        "Prioritized normalization queue"
    )

    search = st.text_input(
        "Search queue",
        key="normalization-queue-search",
    )

    status = st.selectbox(
        "Work status",
        options=[
            "ALL",
            "READY",
            "NEEDS_PRESSING",
            "NEEDS_REFERENCE",
            "NEEDS_REFERENCE_VERIFICATION",
            "NEEDS_CONDITION",
            "NEEDS_COMPLETENESS_FACTOR",
            "NEEDS_PRICE_BASIS",
            "NEEDS_COMPARABLES",
            "BLOCKED_OTHER",
        ],
    )

    blocker = st.selectbox(
        "Blocker",
        options=[
            "ALL",
            "PRESSING_ASSIGNMENT",
            "COMPLETENESS_REFERENCE",
            "REFERENCE_VERIFICATION",
            "CONDITION_NORMALIZATION",
            "COMPLETENESS_FACTOR",
            "PRICE_BASIS",
            "ELIGIBLE_COMPARABLES",
        ],
    )

    rows = list_queue(
        engine,
        search=search,
        work_status=(
            None
            if status == "ALL"
            else status
        ),
        blocker_code=(
            None
            if blocker == "ALL"
            else blocker
        ),
        limit=2000,
    )

    summary = queue_summary(rows)

    columns = st.columns(6)

    columns[0].metric(
        "Listings",
        summary["total"],
    )
    columns[1].metric(
        "Ready",
        summary["ready"],
    )
    columns[2].metric(
        "Blocked",
        summary["blocked"],
    )
    columns[3].metric(
        "Needs pressing",
        summary.get(
            "NEEDS_PRESSING",
            0,
        ),
    )
    columns[4].metric(
        "Needs reference",
        summary.get(
            "NEEDS_REFERENCE",
            0,
        ),
    )
    columns[5].metric(
        "Needs condition",
        summary.get(
            "NEEDS_CONDITION",
            0,
        ),
    )

    display_columns = (
        "priority_score",
        "work_status",
        "marketplace",
        "listing_id",
        "title",
        "artist",
        "catalog_number",
        "media_type",
        "pressing_id",
        "expectation_count",
        "completeness_status",
        "condition_market_factor",
        "completeness_market_factor",
        "selected_price_usd",
        "raw_comparable_count",
        "eligible_comparable_count",
        "blocker_codes",
    )

    st.dataframe(
        pd.DataFrame(rows).reindex(
            columns=display_columns
        ),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Priority is deterministic. Missing pressing identity is "
        "ranked first, followed by missing shared reference, "
        "reference verification, condition, completeness factor, "
        "price basis, and comparable eligibility."
    )


def _render_reference_cohort(
    engine: Engine,
) -> None:
    """Render the first-reference candidate cohort."""
    st.subheader(
        "Pressing reference cohort"
    )

    st.info(
        "This cohort does not invent expected components. "
        "It prioritizes exact pressings using assigned-listing "
        "coverage and existing observed-component evidence."
    )

    search = st.text_input(
        "Search exact pressings",
        key="reference-candidate-search",
    )

    rows = list_reference_candidates(
        engine,
        search=search,
    )

    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
    )

    if not rows:
        return

    candidate = st.selectbox(
        "Reference candidate",
        options=rows,
        format_func=lambda row: (
            f"Pressing #{row['pressing_id']} · "
            f"{row.get('display_artist') or ''} · "
            f"{row.get('display_title') or ''} · "
            f"{row.get('catalog_number') or ''}"
        ),
    )

    st.write(
        {
            "pressing_id":
                candidate["pressing_id"],
            "assigned_listing_count":
                candidate[
                    "assigned_listing_count"
                ],
            "existing_expectation_count":
                candidate[
                    "expectation_count"
                ],
            "observed_component_count":
                candidate[
                    "observation_count"
                ],
            "observed_component_codes":
                candidate[
                    "observed_component_codes"
                ],
        }
    )

    st.warning(
        "Observed presence does not prove that a component was "
        "originally required. Confirm the pressing reference from "
        "catalog scans, documented physical copies, inserts, or "
        "other registered evidence before saving expectations."
    )

    st.markdown(
        "Use **Completeness Reference** or "
        "**Reference Record Admin** in the sidebar to create the "
        "reviewed pressing record."
    )


def _render_bulk_editor(
    engine: Engine,
    work_type: str,
    title: str,
    queue_rows: list[dict[str, Any]],
) -> None:
    """Render one schema-aware CSV bulk editor."""
    st.subheader(title)

    identities = _identity_options(
        queue_rows
    )

    selected = st.multiselect(
        "Listings",
        options=identities,
        format_func=lambda identity: (
            f"{identity[0]}/{identity[1]}"
        ),
        key=f"bulk-selection:{work_type}",
    )

    if selected:
        worksheet = export_workbook_csv(
            engine,
            work_type,
            selected,
        )

        st.download_button(
            "Download schema-accurate worksheet",
            data=worksheet,
            file_name=(
                f"{work_type.lower()}-worksheet.csv"
            ),
            mime="text/csv",
            width="stretch",
            key=f"download:{work_type}",
        )

    uploaded = st.file_uploader(
        "Upload edited worksheet",
        type=["csv"],
        key=f"upload:{work_type}",
    )

    if uploaded is None:
        st.caption(
            "Set apply=TRUE only on rows that should be written. "
            "Unedited template rows are ignored."
        )
        return

    payload = uploaded.getvalue()

    preview = preview_workbook(
        engine,
        work_type,
        payload,
    )

    if preview["errors"]:
        for error in preview["errors"]:
            st.error(error)
    else:
        st.success(
            "Worksheet preview passed."
        )

    st.write(
        {
            "requested_rows":
                preview[
                    "requested_rows"
                ],
            "ready":
                preview["ready"],
        }
    )

    st.dataframe(
        pd.DataFrame(
            preview["rows"]
        ),
        width="stretch",
        hide_index=True,
    )

    actor = st.text_input(
        "Actor or workflow",
        value="STREAMLIT_NORMALIZATION_WORKBENCH",
        key=f"actor:{work_type}",
    )

    reason = st.text_area(
        "Reason for this batch",
        key=f"reason:{work_type}",
    )

    confirmed = st.checkbox(
        "I reviewed this preview and approve the atomic write.",
        key=f"confirm:{work_type}",
    )

    if st.button(
        "Apply approved batch",
        type="primary",
        disabled=(
            not preview["ready"]
            or not confirmed
        ),
        width="stretch",
        key=f"apply:{work_type}",
    ):
        try:
            result = apply_workbook(
                engine,
                work_type,
                payload,
                actor=actor,
                reason=reason,
                filename=uploaded.name,
            )
        except Exception as error:
            st.error(str(error))
        else:
            st.success(
                "Batch completed: "
                f"{result['batch_id']} · "
                f"{result['applied_rows']} rows."
            )

            st.rerun()


def _render_comparable_review(
    engine: Engine,
    queue_rows: list[dict[str, Any]],
) -> None:
    """Render exact-pressing comparable review."""
    st.subheader(
        "Exact-pressing comparable review"
    )

    eligible_targets = [
        row
        for row in queue_rows
        if row["pressing_id"] is not None
        and row[
            "raw_comparable_count"
        ] > 0
    ]

    if not eligible_targets:
        st.info(
            "No exact-pressing comparable cohort is available."
        )
        return

    target = st.selectbox(
        "Target listing",
        options=eligible_targets,
        format_func=_listing_label,
        key="comparable-target",
    )

    candidates = list_comparable_candidates(
        engine,
        target["marketplace"],
        target["listing_id"],
    )

    if not candidates:
        st.info(
            "No same-pressing candidates were found."
        )
        return

    editor_rows = []

    for candidate in candidates:
        editor_rows.append(
            {
                **candidate,
                "decision":
                    candidate[
                        "decision"
                    ]
                    or "NEEDS_REVIEW",
                "review_reason":
                    candidate[
                        "reason"
                    ]
                    or "",
            }
        )

    edited = st.data_editor(
        pd.DataFrame(editor_rows),
        width="stretch",
        hide_index=True,
        disabled=[
            "marketplace",
            "listing_id",
            "title",
            "seller",
            "ended_at",
            "selected_price_usd",
            "condition_market_factor",
            "completeness_market_factor",
            "normalization_ready",
            "actor",
            "updated_at",
        ],
        column_config={
            "decision":
                st.column_config.SelectboxColumn(
                    "Decision",
                    options=list(
                        COMPARABLE_DECISIONS
                    ),
                    required=True,
                ),
        },
        key="comparable-review-editor",
    )

    actor = st.text_input(
        "Reviewer",
        value="STREAMLIT_COMPARABLE_REVIEW",
        key="comparable-review-actor",
    )

    global_reason = st.text_area(
        "Review reason",
        key="comparable-review-reason",
    )

    if st.button(
        "Save changed comparable decisions",
        type="primary",
        width="stretch",
    ):
        changed = 0

        for index, edited_row in (
            edited.iterrows()
        ):
            original = candidates[index]

            decision = str(
                edited_row["decision"]
            )

            row_reason = str(
                edited_row[
                    "review_reason"
                ]
                or global_reason
            ).strip()

            if (
                decision
                == (
                    original["decision"]
                    or "NEEDS_REVIEW"
                )
                and row_reason
                == (
                    original["reason"]
                    or ""
                )
            ):
                continue

            try:
                save_comparable_review(
                    engine,
                    marketplace=target[
                        "marketplace"
                    ],
                    listing_id=target[
                        "listing_id"
                    ],
                    comparable_marketplace=str(
                        edited_row[
                            "marketplace"
                        ]
                    ),
                    comparable_listing_id=str(
                        edited_row[
                            "listing_id"
                        ]
                    ),
                    decision=decision,
                    actor=actor,
                    reason=(
                        row_reason
                        or global_reason
                    ),
                )
            except Exception as error:
                st.error(str(error))
                return

            changed += 1

        st.success(
            f"Saved {changed} comparable decisions."
        )

        st.rerun()


def _render_history(
    engine: Engine,
) -> None:
    """Render batch and immutable audit history."""
    st.subheader(
        "Normalization history"
    )

    st.markdown(
        "#### Bulk batches"
    )

    st.dataframe(
        pd.DataFrame(
            list_work_batches(
                engine
            )
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown(
        "#### Immutable write audit"
    )

    st.dataframe(
        pd.DataFrame(
            list_work_audit(
                engine
            )
        ),
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    """Render the complete normalization workbench."""
    st.title(
        "🧭 Normalization Workbench"
    )

    st.caption(
        "Prioritized, evidence-backed work for pressing identity, "
        "completeness references, condition normalization, price "
        "factors, and exact-pressing comparable eligibility."
    )

    st.info(
        "No language model assigns component requirements, grades, "
        "market factors, or comparable decisions. Every write "
        "requires explicit reviewed input."
    )

    engine = _engine()

    queue_rows = list_queue(
        engine,
        limit=2000,
    )

    tabs = st.tabs(
        [
            "Priority queue",
            "Reference cohort",
            "Condition bulk editor",
            "Factor bulk editor",
            "Comparable review",
            "History",
        ]
    )

    with tabs[0]:
        _render_queue(
            engine
        )

    with tabs[1]:
        _render_reference_cohort(
            engine
        )

    with tabs[2]:
        _render_bulk_editor(
            engine,
            "CONDITION",
            "Bulk condition normalization",
            queue_rows,
        )

    with tabs[3]:
        _render_bulk_editor(
            engine,
            "ANALYSIS_FACTOR",
            "Bulk analysis and normalization factors",
            queue_rows,
        )

    with tabs[4]:
        _render_comparable_review(
            engine,
            queue_rows,
        )

    with tabs[5]:
        _render_history(
            engine
        )


main()
