"""General exact-pressing evidence intake."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine

from auction_etl.services.evidence_intake import (
    ATTACHMENT_KINDS,
    ComponentClaim,
    EvidenceIntakeError,
    IntakeRequest,
    clone_packet,
    discover_packets,
    evidence_packet_root,
    list_active_components,
    list_active_sources,
    stage_and_review,
    store_uploaded_evidence,
)


st.set_page_config(
    page_title="Evidence Intake",
    page_icon="📚",
    layout="wide",
)


@st.cache_resource
def _engine():
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


def _rerun() -> None:
    """Rerun across supported Streamlit versions."""
    rerun = getattr(
        st,
        "rerun",
        None,
    )

    if rerun is None:
        rerun = getattr(
            st,
            "experimental_rerun",
        )

    rerun()


def _packet_selector():
    """Render the general exact-pressing packet selector."""
    packets = discover_packets(
        evidence_packet_root()
    )

    current_path = st.session_state.get(
        "evidence_intake_packet"
    )

    if current_path:
        current = Path(
            current_path
        )

        if current.exists() and all(
            packet.path.resolve()
            != current.resolve()
            for packet in packets
        ):
            packets = discover_packets(
                current.parent.parent
            ) + packets

    unique = {}

    for packet in packets:
        unique[
            str(
                packet.path.resolve()
            )
        ] = packet

    packets = list(
        unique.values()
    )

    if not packets:
        st.warning(
            "No complete exact-pressing review packet was found. "
            "Export one from Cohort Curation Wizard first."
        )

        return None

    selected = st.selectbox(
        "Exact-pressing review packet",
        packets,
        format_func=lambda packet:
            packet.label,
        key="evidence_intake_packet_selector",
    )

    if st.button(
        "Create isolated working copy",
        type="secondary",
        use_container_width=True,
    ):
        destination = clone_packet(
            selected.path,
            destination_root=
                evidence_packet_root(),
        )

        st.session_state[
            "evidence_intake_packet"
        ] = str(
            destination
        )

        st.success(
            f"Working copy created: {destination}"
        )

        _rerun()

    active_path = Path(
        st.session_state.get(
            "evidence_intake_packet",
            str(
                selected.path
            ),
        )
    )

    matching = next(
        (
            packet
            for packet in packets
            if packet.path.resolve()
            == active_path.resolve()
        ),
        selected,
    )

    return matching


def _claim_editor(
    component,
) -> ComponentClaim:
    """Render one exact-pressing component claim."""
    st.markdown(
        f"**{component.display_name}** "
        f"(`{component.code}`)"
    )

    state_column, quantity_column, confidence_column = st.columns(
        (1.4, 1, 1)
    )

    with state_column:
        state = st.selectbox(
            "Reference state",
            (
                "REQUIRED",
                "NOT_INCLUDED",
            ),
            key=(
                "evidence_state_"
                + component.code
            ),
        )

    with quantity_column:
        quantity = st.number_input(
            "Quantity",
            min_value=0,
            value=(
                1
                if state == "REQUIRED"
                else 0
            ),
            step=1,
            key=(
                "evidence_quantity_"
                + component.code
            ),
            disabled=(
                state == "NOT_INCLUDED"
            ),
        )

    with confidence_column:
        confidence = st.number_input(
            "Confidence",
            min_value=0.8000,
            max_value=1.0000,
            value=0.9900,
            step=0.0100,
            format="%.4f",
            key=(
                "evidence_confidence_"
                + component.code
            ),
        )

    variant_column, label_column = st.columns(
        2
    )

    with variant_column:
        variant_key = st.text_input(
            "Variant key",
            key=(
                "evidence_variant_key_"
                + component.code
            ),
        )

    with label_column:
        variant_label = st.text_input(
            "Variant label",
            key=(
                "evidence_variant_label_"
                + component.code
            ),
        )

    notes = st.text_area(
        "Component claim notes",
        placeholder=(
            "Explain exactly where the source establishes "
            "this component and quantity for the exact pressing."
        ),
        key=(
            "evidence_claim_notes_"
            + component.code
        ),
    )

    st.divider()

    return ComponentClaim(
        component_code=
            component.code,
        expectation_state=
            state,
        expected_quantity=(
            int(quantity)
            if state == "REQUIRED"
            else 0
        ),
        confidence=
            Decimal(
                str(confidence)
            ),
        variant_key=
            variant_key,
        variant_label=
            variant_label,
        notes=
            notes,
    )




def _render_return_to_wizard() -> None:
    """Render the active Cohort Curation Wizard return control."""
    return_page = st.session_state.get(
        "evidence_intake_return_page"
    )

    if not return_page:
        return

    pressing_id = st.session_state.get(
        "evidence_intake_handoff_pressing_id"
    )

    catalog = st.session_state.get(
        "evidence_intake_handoff_catalog",
        "",
    )

    st.info(
        "Handoff from Cohort Curation Wizard"
        + (
            f" · Pressing #{pressing_id}"
            if pressing_id is not None
            else ""
        )
        + (
            f" · {catalog}"
            if catalog
            else ""
        )
    )

    if st.button(
        "Return to Cohort Curation Wizard",
        type="secondary",
        use_container_width=True,
        key="evidence_intake_return_to_wizard",
    ):
        st.switch_page(
            str(
                return_page
            )
        )

def main() -> None:
    """Render the general evidence-intake workflow."""
    st.title(
        "📚 Exact-Pressing Evidence Intake"
    )

    st.caption(
        "Stage reviewed source evidence and supported "
        "completeness-reference actions for any exact pressing. "
        "This page edits packet files only; it never applies "
        "PostgreSQL mutations."
    )

    packet = _packet_selector()

    if packet is None:
        return

    packet_path = Path(
        st.session_state.get(
            "evidence_intake_packet",
            str(
                packet.path
            ),
        )
    )

    st.info(
        f"Working packet: `{packet_path}`"
    )

    _render_return_to_wizard()

    identity_columns = st.columns(
        4
    )

    identity_columns[0].metric(
        "Pressing ID",
        packet.pressing_id,
    )

    identity_columns[1].metric(
        "Catalog",
        packet.catalog,
    )

    identity_columns[2].metric(
        "Artist",
        packet.artist or "Unknown",
    )

    identity_columns[3].metric(
        "Workflow status",
        packet.workflow_status,
    )

    engine = _engine()

    sources = list_active_sources(
        engine
    )

    components = list_active_components(
        engine
    )

    if not sources:
        st.error(
            "No active evidence source exists. Create one in "
            "Evidence and Bulk Observations before continuing."
        )

        return

    source_by_label = {
        source.label:
            source
        for source in sources
    }

    component_by_label = {
        component.label:
            component
        for component in components
    }

    st.subheader(
        "1. Reviewed source"
    )

    source_label = st.selectbox(
        "Evidence source",
        tuple(
            source_by_label
        ),
    )

    source = source_by_label[
        source_label
    ]

    if source.source_key in {
        "LISTING_TITLE",
        "AUCTION_TITLE_STATES",
        "AUCTION_TITLE_STATES_",
    }:
        st.error(
            "This source is listing-specific and cannot establish "
            "a shared exact-pressing completeness reference."
        )

    attachment_kind = st.selectbox(
        "Attachment kind",
        ATTACHMENT_KINDS,
    )

    uploaded_file = st.file_uploader(
        "Upload reviewed evidence",
        help=(
            "Uploaded content is stored inside the working packet "
            "and receives an automatic SHA-256 checksum."
        ),
    )

    uri = ""
    checksum = ""
    mime_type = ""

    if uploaded_file is None:
        uri = st.text_input(
            "Evidence URI",
            placeholder=(
                "https://… or file:///…"
            ),
        )

        checksum = st.text_input(
            "Content SHA-256",
            max_chars=64,
            help=(
                "Hash the evidence content, not the URI text."
            ),
        ).lower()

        mime_type = st.text_input(
            "MIME type",
            placeholder="image/jpeg",
        )
    else:
        payload = uploaded_file.getvalue()
        preview_checksum = __import__(
            "hashlib"
        ).sha256(
            payload
        ).hexdigest()

        st.code(
            preview_checksum,
            language=None,
        )

        mime_type = (
            uploaded_file.type
            or "application/octet-stream"
        )

    captured_at = st.text_input(
        "Captured timestamp (ISO 8601)",
        value=datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    )

    page_reference = st.text_input(
        "Page, image, or frame reference",
    )

    evidence_notes = st.text_area(
        "Evidence notes",
        placeholder=(
            "Describe the exact pressing identity and the source "
            "section that establishes the selected components."
        ),
    )

    actor_column, reason_column = st.columns(
        2
    )

    with actor_column:
        actor = st.text_input(
            "Reviewer",
        )

    with reason_column:
        reason = st.text_input(
            "Review reason",
            placeholder=(
                "Establish verified exact-pressing component reference."
            ),
        )

    st.subheader(
        "2. Explicitly supported components"
    )

    selected_labels = st.multiselect(
        "Components directly supported by this source",
        tuple(
            component_by_label
        ),
    )

    claims = [
        _claim_editor(
            component_by_label[
                label
            ]
        )
        for label in selected_labels
    ]

    confirms_scope = st.checkbox(
        "I verified that this evidence documents the selected "
        "components for this exact pressing, not merely one listing."
    )

    st.warning(
        "Unsupported components remain UNKNOWN with blank quantity, "
        "confidence, evidence source, and notes."
    )

    submit = st.button(
        "Stage evidence and run safe review",
        type="primary",
        use_container_width=True,
    )

    if not submit:
        return

    try:
        if uploaded_file is not None:
            (
                uri,
                checksum,
            ) = store_uploaded_evidence(
                packet_path,
                uploaded_file.name,
                uploaded_file.getvalue(),
            )

        request = IntakeRequest(
            packet_dir=
                packet_path,
            source_key=
                source.source_key,
            attachment_kind=
                attachment_kind,
            uri=
                uri,
            sha256=
                checksum,
            mime_type=
                mime_type,
            captured_at=
                captured_at,
            page_reference=
                page_reference,
            evidence_notes=
                evidence_notes,
            actor=
                actor,
            reason=
                reason,
            confirms_exact_pressing_scope=
                confirms_scope,
            claims=
                tuple(claims),
        )

        review_dir = (
            packet_path
            / "latest-safe-review"
        )

        result = stage_and_review(
            request,
            active_source_keys=(
                item.source_key
                for item in sources
            ),
            active_component_codes=(
                item.code
                for item in components
            ),
            review_output_dir=
                review_dir,
        )

        st.session_state["evidence_intake_last_result"] = {
            "pressing_id": packet.pressing_id,
            "catalog": packet.catalog,
            "packet_path": str(result.packet_dir),
            "workflow_status": result.workflow_status,
            "review_status": result.review_status,
            "blockers": list(result.blockers),
            "planned_mutation_count": result.planned_mutation_count,
            "database_writes": result.database_writes,
        }
    except EvidenceIntakeError as error:
        st.error(
            str(error)
        )

        return

    st.success(
        "Reviewed packet changes were staged. "
        "PostgreSQL was not modified."
    )

    result_columns = st.columns(
        5
    )

    result_columns[0].metric(
        "Attachments",
        result.attachment_rows_added,
    )

    result_columns[1].metric(
        "References",
        result.reference_rows_updated,
    )

    result_columns[2].metric(
        "Manifest files",
        result.manifest_files,
    )

    result_columns[3].metric(
        "Review status",
        result.review_status,
    )

    result_columns[4].metric(
        "Database writes",
        result.database_writes,
    )

    if result.blockers:
        st.error(
            "\n".join(
                result.blockers
            )
        )
    else:
        st.info(
            "Review the planned mutations before using the separate "
            "evidence-safe apply command."
        )

    st.code(
        str(
            review_dir
            / "packet-review-summary.json"
        ),
        language=None,
    )


main()
