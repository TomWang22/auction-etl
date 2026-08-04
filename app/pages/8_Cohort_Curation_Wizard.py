"""Eleven-stage exact-pressing cohort curation wizard."""

from __future__ import annotations

import re

import json
import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.cohort_curation_wizard import (
    ATTACHMENT_KINDS,
    BASELINE_RULE_CODES,
    OBSERVATION_ACTIONS,
    OBSERVATION_STATES,
    REFERENCE_ACTIONS,
    REFERENCE_STATES,
    WIZARD_STEPS,
    apply_cohort_workbook,
    apply_observation_changes,
    apply_reference_changes,
    build_cohort_report,
    cohort_progress,
    export_cohort_workbook,
    list_attachments,
    list_cohort_audit,
    list_cohorts,
    list_component_types,
    list_evidence_sources,
    load_cohort,
    load_observation_rows,
    load_reference_rows,
    preview_cohort_workbook,
    save_attachment,
    uploaded_file_sha256,
)
from auction_etl.services.deterministic_verdicts import (
    evaluate_listing,
    list_rules,
)
from auction_etl.services.normalization_readiness import (
    get_readiness,
)
from auction_etl.services.normalization_workbench import (
    COMPARABLE_DECISIONS,
    list_comparable_candidates,
    save_comparable_review,
)

from auction_etl.services.evidence_intake import (
    clone_packet,
    discover_packets,
    evidence_packet_root,
    latest_packet_for_pressing,
)


st.set_page_config(
    page_title="Cohort Curation Wizard",
    page_icon="🧭",
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


def _cohort_label(
    cohort: dict[str, Any],
) -> str:
    """Build a readable cohort label."""
    return (
        f"Pressing #{cohort['pressing_id']} · "
        f"{cohort.get('display_artist') or 'Unknown artist'} · "
        f"{cohort.get('display_title') or 'Unknown title'} · "
        f"{cohort.get('catalog_number') or 'No catalog number'} · "
        f"{cohort['assigned_listing_count']} listings"
    )


def _listing_label(
    listing: dict[str, Any],
) -> str:
    """Build a readable listing label."""
    return (
        f"{listing['marketplace']}/"
        f"{listing['listing_id']} · "
        f"{listing.get('title') or 'Untitled listing'}"
    )


def _safe_dataframe(
    rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """Build a stable DataFrame for empty or populated results."""
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def _message(
    text: str,
) -> None:
    """Store a success message across one rerun."""
    st.session_state[
        "cohort_wizard_message"
    ] = text

    st.rerun()


def _stage_one(
    cohort: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    """Render exact pressing identity."""
    st.header(
        "1. Exact pressing identity"
    )

    pressing = cohort["pressing"]

    identity_fields = {
        "pressing_id":
            pressing.get("id"),
        "release_family_id":
            pressing.get(
                "release_family_id"
            ),
        "artist":
            pressing.get(
                "display_artist"
            ),
        "title":
            pressing.get(
                "display_title"
            ),
        "original_release_year":
            pressing.get(
                "original_release_year"
            ),
        "catalog_number":
            pressing.get(
                "catalog_number"
            ),
        "matrix_number":
            pressing.get(
                "matrix_number"
            ),
        "label_name":
            pressing.get(
                "label_name"
            ),
        "region":
            pressing.get("region"),
        "country":
            pressing.get("country"),
        "media_type":
            pressing.get(
                "media_type"
            ),
        "format_detail":
            pressing.get(
                "format_detail"
            ),
        "disc_count":
            pressing.get(
                "disc_count"
            ),
        "release_year":
            pressing.get(
                "release_year"
            ),
        "generation":
            pressing.get(
                "generation"
            ),
        "variant_key":
            pressing.get(
                "pressing_variant_key"
            ),
        "variant_label":
            pressing.get(
                "pressing_variant_label"
            ),
        "is_first_press":
            pressing.get(
                "is_first_press"
            ),
        "is_modern_repress":
            pressing.get(
                "is_modern_repress"
            ),
    }

    st.json(
        identity_fields,
        expanded=True,
    )

    st.subheader(
        "Eleven-stage workflow"
    )

    st.dataframe(
        _safe_dataframe(
            progress["stages"]
        ),
        width="stretch",
        hide_index=True,
    )


def _stage_two(
    cohort: dict[str, Any],
) -> None:
    """Render assigned listings."""
    st.header(
        "2. Assigned listings"
    )

    listings = cohort[
        "listings"
    ]

    metrics = st.columns(4)

    metrics[0].metric(
        "Assigned listings",
        len(listings),
    )

    metrics[1].metric(
        "Condition factors",
        sum(
            row[
                "condition_market_factor"
            ] is not None
            for row in listings
        ),
    )

    metrics[2].metric(
        "Completeness factors",
        sum(
            row[
                "completeness_market_factor"
            ] is not None
            for row in listings
        ),
    )

    metrics[3].metric(
        "Database ready",
        sum(
            row[
                "normalization_ready"
            ] is True
            for row in listings
        ),
    )

    st.dataframe(
        _safe_dataframe(listings),
        width="stretch",
        hide_index=True,
    )


def _stage_three(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render evidence sources and attachments."""
    st.header(
        "3. Evidence and attachments"
    )

    _render_evidence_intake_handoff()


    st.info(
        "Attachments are metadata records referencing external "
        "evidence by URI and SHA-256 checksum. File contents are "
        "not copied into PostgreSQL."
    )

    sources = list_evidence_sources(
        engine
    )

    source_options = [
        row["source_key"]
        for row in sources
    ]

    attachments = list_attachments(
        engine,
        pressing_id,
    )

    st.subheader(
        "Current pressing evidence"
    )

    st.dataframe(
        _safe_dataframe(attachments),
        width="stretch",
        hide_index=True,
    )

    with st.form(
        "cohort-wizard-attachment",
        clear_on_submit=True,
    ):
        uploaded = st.file_uploader(
            "Optional local file for checksum calculation",
            key="wizard-attachment-file",
        )

        source_key = st.selectbox(
            "Evidence source",
            options=[
                "",
                *source_options,
            ],
        )

        attachment_kind = st.selectbox(
            "Attachment kind",
            options=list(
                ATTACHMENT_KINDS
            ),
        )

        uri = st.text_input(
            "Evidence URI",
            placeholder=(
                "https://archive.example/catalog/page "
                "or file:///reviewed/archive/path"
            ),
        )

        manual_sha256 = st.text_input(
            "SHA-256",
            help=(
                "Automatically calculated when a local file is uploaded."
            ),
        )

        mime_type = st.text_input(
            "MIME type",
            value=(
                uploaded.type
                if uploaded is not None
                else ""
            ),
        )

        captured_at = st.text_input(
            "Captured timestamp (ISO 8601)",
            placeholder="2026-08-03T20:00:00-04:00",
        )

        page_reference = st.text_input(
            "Page, image, frame, or physical-copy reference",
        )

        notes = st.text_area(
            "Evidence notes",
        )

        actor = st.text_input(
            "Actor or workflow",
            value="STREAMLIT_COHORT_WIZARD",
        )

        reason = st.text_area(
            "Reason for registering this evidence",
        )

        submitted = st.form_submit_button(
            "Register attachment metadata",
            type="primary",
            width="stretch",
        )

    if submitted:
        sha256 = manual_sha256

        if uploaded is not None:
            sha256 = uploaded_file_sha256(
                uploaded.getvalue()
            )

        try:
            saved = save_attachment(
                engine,
                pressing_id,
                source_key=(
                    source_key or None
                ),
                attachment_kind=
                    attachment_kind,
                uri=uri,
                sha256=sha256,
                mime_type=(
                    mime_type or None
                ),
                captured_at=(
                    captured_at or None
                ),
                page_reference=(
                    page_reference or None
                ),
                notes=(
                    notes or None
                ),
                actor=actor,
                reason=reason,
            )
        except Exception as error:
            st.error(str(error))
        else:
            _message(
                "Evidence attachment registered: "
                f"#{saved['id']}."
            )



def _stage_four(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render the shared completeness reference editor."""
    st.header(
        "4. Shared completeness reference"
    )

    st.warning(
        "The reference belongs to the exact pressing. Saving a "
        "row affects completeness calculations for every listing "
        "assigned to this pressing. Observed presence alone does "
        "not prove that a component was originally required."
    )

    sources = list_evidence_sources(
        engine
    )

    source_options = [
        row["source_key"]
        for row in sources
    ]

    rows = load_reference_rows(
        engine,
        pressing_id,
    )

    editor = st.data_editor(
        _safe_dataframe(rows),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "id",
            "display_name",
        ],
        column_config={
            "action":
                st.column_config.SelectboxColumn(
                    "Action",
                    options=list(
                        REFERENCE_ACTIONS
                    ),
                    required=True,
                ),
            "expectation_state":
                st.column_config.SelectboxColumn(
                    "Reference state",
                    options=list(
                        REFERENCE_STATES
                    ),
                    required=True,
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
        },
        key=(
            "wizard-reference-editor:"
            f"{pressing_id}"
        ),
    )

    actor = st.text_input(
        "Reference reviewer",
        value="STREAMLIT_COHORT_WIZARD",
        key="wizard-reference-actor",
    )

    reason = st.text_area(
        "Reference change reason",
        key="wizard-reference-reason",
    )

    confirmed = st.checkbox(
        "I reviewed these shared pressing-reference changes.",
        key="wizard-reference-confirm",
    )

    if st.button(
        "Apply reviewed reference changes",
        type="primary",
        disabled=not confirmed,
        width="stretch",
    ):
        changes = [
            dict(row)
            for row in editor.to_dict(
                orient="records"
            )
            if str(
                row.get(
                    "action",
                    "NO_CHANGE",
                )
            ) != "NO_CHANGE"
        ]

        if not changes:
            st.info(
                "No reference rows are marked UPSERT or DELETE."
            )
            return

        try:
            result = apply_reference_changes(
                engine,
                pressing_id,
                changes,
                actor=actor,
                reason=reason,
            )
        except Exception as error:
            st.error(str(error))
        else:
            _message(
                "Reference changes saved: "
                f"{result['upserted']} upserted, "
                f"{result['deleted']} deleted."
            )


def _blank_observation_row(
    cohort: dict[str, Any],
) -> dict[str, Any]:
    """Build one blank observation template row."""
    first_listing = (
        cohort["listings"][0]
        if cohort["listings"]
        else {}
    )

    return {
        "action":
            "NO_CHANGE",
        "id":
            None,
        "marketplace":
            first_listing.get(
                "marketplace",
                "",
            ),
        "listing_id":
            first_listing.get(
                "listing_id",
                "",
            ),
        "title":
            first_listing.get(
                "title",
                "",
            ),
        "component_code":
            "",
        "variant_key":
            "",
        "variant_label":
            "",
        "observation_state":
            "UNKNOWN",
        "observed_quantity":
            0,
        "normalized_condition":
            "",
        "source_condition_text":
            "",
        "evidence_source":
            "",
        "confidence":
            0.9,
        "evidence_url":
            "",
        "notes":
            "",
    }


def _stage_five(
    engine: Engine,
    pressing_id: int,
    cohort: dict[str, Any],
) -> None:
    """Render listing component observations."""
    st.header(
        "5. Listing component observations"
    )

    st.info(
        "These rows describe only what is evidenced for one listing. "
        "They cannot modify the shared pressing reference."
    )

    existing = load_observation_rows(
        engine,
        pressing_id,
    )

    if not existing:
        existing = [
            _blank_observation_row(
                cohort
            )
        ]

    listing_options = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        ): _listing_label(row)
        for row in cohort["listings"]
    }

    component_options = [
        row["code"]
        for row in list_component_types(
            engine
        )
    ]

    source_options = [
        row["source_key"]
        for row in list_evidence_sources(
            engine
        )
    ]

    editor = st.data_editor(
        _safe_dataframe(existing),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "id",
            "title",
        ],
        column_config={
            "action":
                st.column_config.SelectboxColumn(
                    "Action",
                    options=list(
                        OBSERVATION_ACTIONS
                    ),
                    required=True,
                ),
            "marketplace":
                st.column_config.TextColumn(
                    "Marketplace",
                    required=True,
                ),
            "listing_id":
                st.column_config.TextColumn(
                    "Listing ID",
                    required=True,
                    help=(
                        "Must be assigned to this exact pressing."
                    ),
                ),
            "component_code":
                st.column_config.SelectboxColumn(
                    "Component",
                    options=component_options,
                    required=True,
                ),
            "observation_state":
                st.column_config.SelectboxColumn(
                    "Observation state",
                    options=list(
                        OBSERVATION_STATES
                    ),
                    required=True,
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
        },
        key=(
            "wizard-observation-editor:"
            f"{pressing_id}"
        ),
    )

    with st.expander(
        "Assigned listing identities"
    ):
        st.json(
            {
                (
                    f"{marketplace}/"
                    f"{listing_id}"
                ): label
                for (
                    marketplace,
                    listing_id
                ), label in listing_options.items()
            }
        )

    actor = st.text_input(
        "Observation reviewer",
        value="STREAMLIT_COHORT_WIZARD",
        key="wizard-observation-actor",
    )

    reason = st.text_area(
        "Observation change reason",
        key="wizard-observation-reason",
    )

    confirmed = st.checkbox(
        "I reviewed these listing-only observations.",
        key="wizard-observation-confirm",
    )

    if st.button(
        "Apply reviewed observation changes",
        type="primary",
        disabled=not confirmed,
        width="stretch",
    ):
        changes = [
            dict(row)
            for row in editor.to_dict(
                orient="records"
            )
            if str(
                row.get(
                    "action",
                    "NO_CHANGE",
                )
            ) != "NO_CHANGE"
        ]

        if not changes:
            st.info(
                "No observation rows are marked UPSERT or DELETE."
            )
            return

        try:
            result = apply_observation_changes(
                engine,
                pressing_id,
                changes,
                actor=actor,
                reason=reason,
            )
        except Exception as error:
            st.error(str(error))
        else:
            _message(
                "Observation changes saved: "
                f"{result['upserted']} upserted, "
                f"{result['deleted']} deleted."
            )


def _bulk_stage(
    engine: Engine,
    pressing_id: int,
    *,
    work_type: str,
    heading: str,
    description: str,
    key_prefix: str,
) -> None:
    """Render one audited schema-aware bulk stage."""
    st.header(heading)
    st.info(description)

    worksheet = export_cohort_workbook(
        engine,
        pressing_id,
        work_type,
    )

    st.download_button(
        "Download cohort worksheet",
        data=worksheet,
        file_name=(
            f"pressing-{pressing_id}-"
            f"{work_type.lower()}.csv"
        ),
        mime="text/csv",
        width="stretch",
        key=f"{key_prefix}-download",
    )

    uploaded = st.file_uploader(
        "Upload reviewed worksheet",
        type=["csv"],
        key=f"{key_prefix}-upload",
    )

    if uploaded is None:
        st.caption(
            "Set apply=TRUE only on rows approved for persistence. "
            "Rows left FALSE are ignored."
        )
        return

    payload = uploaded.getvalue()

    preview = preview_cohort_workbook(
        engine,
        work_type,
        payload,
    )

    summary_columns = st.columns(3)

    summary_columns[0].metric(
        "Requested rows",
        preview[
            "requested_rows"
        ],
    )

    summary_columns[1].metric(
        "Preview rows",
        len(
            preview["rows"]
        ),
    )

    summary_columns[2].metric(
        "Ready",
        str(
            preview["ready"]
        ),
    )

    for error in preview["errors"]:
        st.error(error)

    st.dataframe(
        _safe_dataframe(
            preview["rows"]
        ),
        width="stretch",
        hide_index=True,
    )

    actor = st.text_input(
        "Actor or workflow",
        value="STREAMLIT_COHORT_WIZARD",
        key=f"{key_prefix}-actor",
    )

    reason = st.text_area(
        "Reason for this batch",
        key=f"{key_prefix}-reason",
    )

    confirmed = st.checkbox(
        "I reviewed the preview and approve this atomic write.",
        key=f"{key_prefix}-confirm",
    )

    if st.button(
        "Apply approved cohort batch",
        type="primary",
        disabled=(
            not preview["ready"]
            or not confirmed
        ),
        width="stretch",
        key=f"{key_prefix}-apply",
    ):
        try:
            result = apply_cohort_workbook(
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
            _message(
                "Batch completed: "
                f"{result['batch_id']} · "
                f"{result['applied_rows']} rows."
            )


def _stage_six(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render condition normalization."""
    _bulk_stage(
        engine,
        pressing_id,
        work_type="CONDITION",
        heading=(
            "6. Condition normalization"
        ),
        description=(
            "Canonical grades, source condition text, confidence, "
            "manual-override state, and notes use the live PostgreSQL "
            "condition contract."
        ),
        key_prefix="wizard-condition",
    )


def _stage_seven(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render analysis and market factors."""
    _bulk_stage(
        engine,
        pressing_id,
        work_type="ANALYSIS_FACTOR",
        heading=(
            "7. Analysis and market factors"
        ),
        description=(
            "Historical anchors, price bases, normalization factors, "
            "and other analysis inputs use the live PostgreSQL contract."
        ),
        key_prefix="wizard-analysis",
    )


def _stage_eight(
    engine: Engine,
    cohort: dict[str, Any],
) -> None:
    """Render exact-pressing comparable review."""
    st.header(
        "8. Exact-pressing comparable review"
    )

    listings = cohort["listings"]

    if not listings:
        st.info(
            "The pressing has no assigned listings."
        )
        return

    target = st.selectbox(
        "Target listing",
        options=listings,
        format_func=_listing_label,
        key="wizard-comparable-target",
    )

    candidates = list_comparable_candidates(
        engine,
        str(target["marketplace"]),
        str(target["listing_id"]),
    )

    if not candidates:
        st.info(
            "No same-pressing comparable candidates are available."
        )
        return

    original_by_identity = {
        (
            str(row["marketplace"]),
            str(row["listing_id"]),
        ): row
        for row in candidates
    }

    editor_rows = []

    for candidate in candidates:
        editor_rows.append(
            {
                **candidate,
                "decision":
                    (
                        candidate[
                            "decision"
                        ]
                        or "NEEDS_REVIEW"
                    ),
                "review_reason":
                    (
                        candidate[
                            "reason"
                        ]
                        or ""
                    ),
            }
        )

    editor = st.data_editor(
        _safe_dataframe(editor_rows),
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
        key=(
            "wizard-comparable-editor:"
            f"{target['marketplace']}:"
            f"{target['listing_id']}"
        ),
    )

    actor = st.text_input(
        "Comparable reviewer",
        value="STREAMLIT_COHORT_WIZARD",
        key="wizard-comparable-actor",
    )

    default_reason = st.text_area(
        "Default comparable-review reason",
        key="wizard-comparable-reason",
    )

    if st.button(
        "Save changed comparable decisions",
        type="primary",
        width="stretch",
    ):
        saved = 0

        for edited_row in editor.to_dict(
            orient="records"
        ):
            identity = (
                str(
                    edited_row[
                        "marketplace"
                    ]
                ),
                str(
                    edited_row[
                        "listing_id"
                    ]
                ),
            )

            original = original_by_identity[
                identity
            ]

            decision = str(
                edited_row["decision"]
            )

            reason = str(
                edited_row.get(
                    "review_reason"
                )
                or default_reason
                or ""
            ).strip()

            original_decision = (
                original["decision"]
                or "NEEDS_REVIEW"
            )

            original_reason = (
                original["reason"]
                or ""
            )

            if (
                decision
                == original_decision
                and reason
                == original_reason
            ):
                continue

            try:
                save_comparable_review(
                    engine,
                    marketplace=str(
                        target[
                            "marketplace"
                        ]
                    ),
                    listing_id=str(
                        target[
                            "listing_id"
                        ]
                    ),
                    comparable_marketplace=
                        identity[0],
                    comparable_listing_id=
                        identity[1],
                    decision=decision,
                    actor=actor,
                    reason=reason,
                )
            except Exception as error:
                st.error(str(error))
                return

            saved += 1

        _message(
            f"Saved {saved} comparable-review decisions."
        )


def _stage_nine(
    engine: Engine,
    cohort: dict[str, Any],
) -> None:
    """Render deterministic normalization readiness."""
    st.header(
        "9. Normalization readiness"
    )

    readiness_rows = []

    for listing in cohort[
        "listings"
    ]:
        readiness_rows.append(
            get_readiness(
                engine,
                str(
                    listing[
                        "marketplace"
                    ]
                ),
                str(
                    listing[
                        "listing_id"
                    ]
                ),
            )
        )

    if not readiness_rows:
        st.info(
            "No assigned listings are available."
        )
        return

    display_rows = []

    for row in readiness_rows:
        display_rows.append(
            {
                "marketplace":
                    row[
                        "marketplace"
                    ],
                "listing_id":
                    row[
                        "listing_id"
                    ],
                "title":
                    row["title"],
                "reference_status":
                    row[
                        "reference_status"
                    ],
                "completeness_status":
                    row[
                        "completeness_status"
                    ],
                "raw_comparable_count":
                    row[
                        "raw_comparable_count"
                    ],
                "eligible_comparable_count":
                    row[
                        "eligible_comparable_count"
                    ],
                "readiness_gate_ratio":
                    row[
                        "readiness_gate_ratio"
                    ],
                "readiness_status":
                    row[
                        "readiness_status"
                    ],
                "blockers":
                    row["blockers"],
            }
        )

    st.dataframe(
        _safe_dataframe(
            display_rows
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "readiness_gate_ratio":
                st.column_config.ProgressColumn(
                    "Readiness gates",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.1%%",
                ),
        },
    )

    selected = st.selectbox(
        "Readiness detail",
        options=readiness_rows,
        format_func=lambda row: (
            f"{row['marketplace']}/"
            f"{row['listing_id']} · "
            f"{row['readiness_status']}"
        ),
    )

    st.subheader(
        "Explicit blockers"
    )

    if selected["blockers"]:
        for blocker in selected[
            "blockers"
        ]:
            st.warning(blocker)
    else:
        st.success(
            "All deterministic normalization gates are satisfied."
        )


def _stage_ten(
    engine: Engine,
    cohort: dict[str, Any],
) -> None:
    """Evaluate all eleven professional baseline rules."""
    st.header(
        "10. Eleven deterministic verdicts"
    )

    rules = list_rules(
        engine,
        include_inactive=True,
    )

    baseline_rules = [
        rule
        for rule in rules
        if str(
            rule["rule_code"]
        ) in BASELINE_RULE_CODES
    ]

    baseline_by_code = {
        str(rule["rule_code"]):
            rule
        for rule in baseline_rules
    }

    st.metric(
        "Professional baseline rules",
        (
            f"{len(baseline_rules)}/"
            f"{len(BASELINE_RULE_CODES)}"
        ),
    )

    missing_rules = [
        rule_code
        for rule_code in BASELINE_RULE_CODES
        if rule_code
        not in baseline_by_code
    ]

    if missing_rules:
        st.error(
            "Missing baseline rules: "
            + ", ".join(
                missing_rules
            )
        )

    st.dataframe(
        _safe_dataframe(
            [
                baseline_by_code[
                    rule_code
                ]
                for rule_code in BASELINE_RULE_CODES
                if rule_code
                in baseline_by_code
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    listings = cohort["listings"]

    if not listings:
        st.info(
            "No assigned listings are available."
        )
        return

    selected = st.selectbox(
        "Listing evaluation",
        options=listings,
        format_func=_listing_label,
        key="wizard-verdict-listing",
    )

    evaluation = evaluate_listing(
        engine,
        str(
            selected["marketplace"]
        ),
        str(
            selected["listing_id"]
        ),
    )

    evaluation_by_code = {
        str(row["rule_code"]):
            row
        for row in evaluation[
            "evaluations"
        ]
    }

    rows = []

    for rule_code in BASELINE_RULE_CODES:
        rule = baseline_by_code.get(
            rule_code
        )

        result = evaluation_by_code.get(
            rule_code
        )

        rows.append(
            {
                "rule_code":
                    rule_code,
                "professional_name":
                    (
                        rule[
                            "display_name"
                        ]
                        if rule
                        else "MISSING RULE"
                    ),
                "metric_code":
                    (
                        result[
                            "metric_code"
                        ]
                        if result
                        else None
                    ),
                "metric_value":
                    (
                        result[
                            "metric_value"
                        ]
                        if result
                        else None
                    ),
                "status":
                    (
                        result[
                            "status"
                        ]
                        if result
                        else "NOT_EVALUATED"
                    ),
                "severity":
                    (
                        result[
                            "severity"
                        ]
                        if result
                        else None
                    ),
                "verdict":
                    (
                        result[
                            "verdict_label"
                        ]
                        if result
                        and result[
                            "triggered"
                        ]
                        else None
                    ),
                "suppression_reason":
                    (
                        result[
                            "suppression_reason"
                        ]
                        if result
                        else (
                            "Rule is missing or inactive."
                        )
                    ),
            }
        )

    st.dataframe(
        _safe_dataframe(rows),
        width="stretch",
        hide_index=True,
    )

    triggered = [
        row
        for row in rows
        if row["verdict"]
    ]

    if triggered:
        st.subheader(
            "Triggered professional verdicts"
        )

        for row in triggered:
            st.warning(
                f"**{row['verdict']}** "
                f"({row['severity']})"
            )
    else:
        st.success(
            "No professional baseline verdict is currently triggered."
        )


def _stage_eleven(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Render immutable history and the final report."""
    st.header(
        "11. Audit and final report"
    )

    audit = list_cohort_audit(
        engine,
        pressing_id,
    )

    reference_events = audit[
        "reference_events"
    ]

    normalization_events = audit[
        "normalization_events"
    ]

    metrics = st.columns(2)

    metrics[0].metric(
        "Reference and evidence events",
        len(reference_events),
    )

    metrics[1].metric(
        "Normalization events",
        len(normalization_events),
    )

    st.subheader(
        "Reference, observation, and attachment history"
    )

    st.dataframe(
        _safe_dataframe(
            reference_events
        ),
        width="stretch",
        hide_index=True,
    )

    st.subheader(
        "Condition, factor, and comparable history"
    )

    st.dataframe(
        _safe_dataframe(
            normalization_events
        ),
        width="stretch",
        hide_index=True,
    )

    report = build_cohort_report(
        engine,
        pressing_id,
    )

    serialized = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    st.download_button(
        "Download complete cohort report",
        data=serialized.encode(
            "utf-8"
        ),
        file_name=(
            f"pressing-{pressing_id}-"
            "cohort-report.json"
        ),
        mime="application/json",
        width="stretch",
    )

    with st.expander(
        "Final report preview"
    ):
        st.json(
            report,
            expanded=False,
        )


def _render_navigation(
    current_step: int,
) -> None:
    """Render previous and next controls."""
    previous_column, progress_column, next_column = (
        st.columns(
            [
                1,
                3,
                1,
            ]
        )
    )

    with previous_column:
        if st.button(
            "← Previous",
            disabled=current_step <= 1,
            width="stretch",
        ):
            st.session_state[
                "cohort_wizard_step"
            ] = max(
                1,
                current_step - 1,
            )

            st.rerun()

    with progress_column:
        st.progress(
            current_step
            / len(
                WIZARD_STEPS
            ),
            text=(
                f"Stage {current_step} of "
                f"{len(WIZARD_STEPS)}"
            ),
        )

    with next_column:
        if st.button(
            "Next →",
            disabled=(
                current_step
                >= len(
                    WIZARD_STEPS
                )
            ),
            width="stretch",
        ):
            st.session_state[
                "cohort_wizard_step"
            ] = min(
                len(
                    WIZARD_STEPS
                ),
                current_step + 1,
            )

            st.rerun()




def _pressing_ids_from_value(
    value,
) -> set[int]:
    """Extract plausible pressing IDs from Streamlit session values."""
    found: set[int] = set()

    if isinstance(
        value,
        bool,
    ):
        return found

    if isinstance(
        value,
        int,
    ):
        if value > 0:
            found.add(
                value
            )

        return found

    if isinstance(
        value,
        str,
    ):
        for match in re.finditer(
            r"Pressing\s*#\s*(\d+)",
            value,
            re.IGNORECASE,
        ):
            found.add(
                int(
                    match.group(1)
                )
            )

        return found

    if isinstance(
        value,
        dict,
    ):
        for key, nested_value in value.items():
            key_text = str(
                key
            ).casefold()

            if (
                "pressing" in key_text
                or "cohort" in key_text
            ):
                found.update(
                    _pressing_ids_from_value(
                        nested_value
                    )
                )

        return found

    pressing_id = getattr(
        value,
        "pressing_id",
        None,
    )

    if pressing_id is not None:
        found.update(
            _pressing_ids_from_value(
                pressing_id
            )
        )

    label = getattr(
        value,
        "label",
        None,
    )

    if label is not None:
        found.update(
            _pressing_ids_from_value(
                str(
                    label
                )
            )
        )

    return found


def _current_wizard_pressing_id() -> int | None:
    """Resolve the currently selected exact pressing."""
    packet_root = evidence_packet_root()

    packets = discover_packets(
        packet_root
    )

    available_ids = {
        packet.pressing_id
        for packet in packets
    }

    explicit_value = st.session_state.get(
        "cohort_curation_selected_cohort_value"
    )

    for candidate in sorted(
        _pressing_ids_from_value(
            explicit_value
        )
    ):
        if candidate in available_ids:
            return candidate

    candidates: list[int] = []

    for key, value in st.session_state.items():
        key_text = str(
            key
        ).casefold()

        if (
            "pressing" not in key_text
            and "cohort" not in key_text
        ):
            continue

        candidates.extend(
            sorted(
                _pressing_ids_from_value(
                    value
                )
            )
        )

    for candidate in candidates:
        if candidate in available_ids:
            return candidate

    rendered_candidates: set[int] = set()

    for value in st.session_state.values():
        rendered_candidates.update(
            _pressing_ids_from_value(
                value
            )
        )

    for candidate in sorted(
        rendered_candidates
    ):
        if candidate in available_ids:
            return candidate

    if len(
        available_ids
    ) == 1:
        return next(
            iter(
                available_ids
            )
        )

    return None


def _render_evidence_intake_handoff() -> None:
    """Render Stage 3 packet handoff and latest review status."""
    st.markdown(
        "### Evidence Intake handoff"
    )

    st.caption(
        "Create an isolated working packet for this exact pressing, "
        "open the Evidence Intake page, and return here after its "
        "read-only safe review."
    )

    pressing_id = (
        _current_wizard_pressing_id()
    )

    if pressing_id is None:
        st.info(
            "No exported packet could be matched to the currently "
            "selected exact pressing."
        )

        return

    packet = latest_packet_for_pressing(
        pressing_id,
        evidence_packet_root(),
    )

    if packet is None:
        st.warning(
            "Export a complete curation packet for this pressing "
            "before opening Evidence Intake."
        )

        return

    st.code(
        str(
            packet.path
        ),
        language=None,
    )

    latest_result = st.session_state.get(
        "evidence_intake_last_result"
    )

    if (
        isinstance(
            latest_result,
            dict,
        )
        and latest_result.get(
            "pressing_id"
        )
        == pressing_id
    ):
        st.success(
            "Latest Evidence Intake safe review returned to "
            "this exact pressing."
        )

        status_columns = st.columns(
            4
        )

        status_columns[0].metric(
            "Workflow",
            latest_result.get(
                "workflow_status",
                "UNKNOWN",
            ),
        )

        status_columns[1].metric(
            "Safe review",
            latest_result.get(
                "review_status",
                "UNKNOWN",
            ),
        )

        status_columns[2].metric(
            "Planned mutations",
            latest_result.get(
                "planned_mutation_count",
                0,
            ),
        )

        status_columns[3].metric(
            "Database writes",
            latest_result.get(
                "database_writes",
                0,
            ),
        )

        blockers = latest_result.get(
            "blockers",
            [],
        )

        if blockers:
            st.error(
                "\n".join(
                    str(
                        blocker
                    )
                    for blocker in blockers
                )
            )

    if st.button(
        "Open Evidence Intake for this pressing",
        type="primary",
        use_container_width=True,
        key=(
            "open_evidence_intake_"
            f"{pressing_id}"
        ),
    ):
        working_packet = clone_packet(
            packet.path,
            destination_root=
                evidence_packet_root(),
        )

        st.session_state[
            "evidence_intake_packet"
        ] = str(
            working_packet
        )

        st.session_state[
            "evidence_intake_handoff_pressing_id"
        ] = pressing_id

        st.session_state[
            "evidence_intake_handoff_catalog"
        ] = packet.catalog

        st.session_state[
            "evidence_intake_return_page"
        ] = "pages/8_Cohort_Curation_Wizard.py"

        st.switch_page(
            "pages/9_Evidence_Intake.py"
        )

def main() -> None:
    """Render the complete eleven-stage cohort wizard."""
    st.title(
        "🧭 Cohort Curation Wizard"
    )

    st.caption(
        "One guided page for exact pressing identity, evidence, "
        "completeness references, listing observations, condition, "
        "analysis factors, comparable review, readiness, all eleven "
        "professional verdict rules, and immutable reporting."
    )

    st.info(
        "No language model assigns component requirements, grades, "
        "normalization factors, comparable decisions, scores, or "
        "verdicts. Every persistent curation change requires an "
        "explicit reviewed action."
    )

    message = st.session_state.pop(
        "cohort_wizard_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    search = st.sidebar.text_input(
        "Search exact pressing cohorts",
    )

    cohorts = list_cohorts(
        engine,
        search=search,
    )

    if not cohorts:
        st.warning(
            "No exact pressing cohort matches the search."
        )
        return

    selected_pressing_id = (
        st.sidebar.selectbox(
            "Exact pressing cohort",
            options=[
                int(
                    row[
                        "pressing_id"
                    ]
                )
                for row in cohorts
            ],
            format_func=lambda value: (
                _cohort_label(
                    next(
                        row
                        for row in cohorts
                        if int(
                            row[
                                "pressing_id"
                            ]
                        ) == value
                    )
                )
            ),
        )
    )

    st.session_state[
        "cohort_curation_selected_cohort_value"
    ] = selected_pressing_id

    cohort = load_cohort(
        engine,
        selected_pressing_id,
    )

    progress = cohort_progress(
        engine,
        selected_pressing_id,
    )

    st.sidebar.metric(
        "Completed stages",
        (
            f"{progress['completed_stages']}/"
            f"{len(WIZARD_STEPS)}"
        ),
    )

    st.sidebar.progress(
        progress[
            "completed_stages"
        ]
        / len(
            WIZARD_STEPS
        )
    )

    step_options = list(
        range(
            1,
            len(WIZARD_STEPS) + 1,
        )
    )

    current_step = int(
        st.session_state.get(
            "cohort_wizard_step",
            1,
        )
    )

    selected_step = st.sidebar.selectbox(
        "Wizard stage",
        options=step_options,
        index=step_options.index(
            current_step
        ),
        format_func=lambda value: (
            f"{value}. "
            f"{WIZARD_STEPS[value - 1]}"
        ),
    )

    if selected_step != current_step:
        current_step = selected_step
        st.session_state[
            "cohort_wizard_step"
        ] = current_step

    status_rows = []

    for stage in progress["stages"]:
        status_rows.append(
            {
                "stage":
                    stage["stage"],
                "status":
                    (
                        "✓"
                        if stage[
                            "complete"
                        ]
                        else "○"
                    ),
                "name":
                    stage["name"],
            }
        )

    st.sidebar.dataframe(
        _safe_dataframe(
            status_rows
        ),
        width="stretch",
        hide_index=True,
    )

    renderers = {
        1:
            lambda: _stage_one(
                cohort,
                progress,
            ),
        2:
            lambda: _stage_two(
                cohort
            ),
        3:
            lambda: _stage_three(
                engine,
                selected_pressing_id,
            ),
        4:
            lambda: _stage_four(
                engine,
                selected_pressing_id,
            ),
        5:
            lambda: _stage_five(
                engine,
                selected_pressing_id,
                cohort,
            ),
        6:
            lambda: _stage_six(
                engine,
                selected_pressing_id,
            ),
        7:
            lambda: _stage_seven(
                engine,
                selected_pressing_id,
            ),
        8:
            lambda: _stage_eight(
                engine,
                cohort,
            ),
        9:
            lambda: _stage_nine(
                engine,
                cohort,
            ),
        10:
            lambda: _stage_ten(
                engine,
                cohort,
            ),
        11:
            lambda: _stage_eleven(
                engine,
                selected_pressing_id,
            ),
    }

    renderers[current_step]()

    st.divider()

    _render_navigation(
        current_step
    )


main()
