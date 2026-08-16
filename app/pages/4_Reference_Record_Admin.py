"""Real pressing-reference record administration."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.pressing_reference_admin import (
    list_pressings,
)
from auction_etl.services.reference_record_admin import (
    ATTACHMENT_KINDS,
    REFERENCE_STATES,
    create_reference_record,
    deactivate_attachment,
    delete_reference_record,
    list_active_components,
    list_active_sources,
    list_attachments,
    list_audit_events,
    list_bulk_batch_rows,
    list_bulk_batches,
    list_reference_records,
    register_attachment,
    restore_reference_event,
    update_reference_record,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Reference Record Admin",
    page_icon="🗃️",
    layout="wide",
)
render_navigation(current_page="pages/4_Reference_Record_Admin.py")


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
        "reference_record_admin_message"
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


def _record_label(
    record: dict[str, Any],
) -> str:
    """Build one readable record label."""
    variant = (
        record.get(
            "variant_label"
        )
        or record.get(
            "variant_key"
        )
        or "default"
    )

    return (
        f"#{record['id']} · "
        f"{record['component_code']} · "
        f"{variant} · "
        f"{record['expectation_state']}"
    )


def _reference_payload_form(
    *,
    form_key: str,
    pressing_id: int,
    components: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str, bool]:
    """Render reusable reference-record fields."""
    values = defaults or {}

    component_codes = [
        str(row["code"])
        for row in components
    ]

    component_labels = {
        str(row["code"]): (
            f"{row['code']} — "
            f"{row['display_name']}"
        )
        for row in components
    }

    source_keys = [
        str(row["source_key"])
        for row in sources
    ]

    source_labels = {
        str(row["source_key"]): (
            f"{row['source_key']} — "
            f"{row['display_name']}"
        )
        for row in sources
    }

    default_component = str(
        values.get(
            "component_code"
        )
        or component_codes[0]
    )

    default_source = str(
        values.get(
            "evidence_source"
        )
        or source_keys[0]
    )

    default_state = str(
        values.get(
            "expectation_state"
        )
        or "UNKNOWN"
    )

    with st.form(
        form_key,
        clear_on_submit=False,
    ):
        component_code = st.selectbox(
            "Component",
            options=component_codes,
            index=component_codes.index(
                default_component
            ),
            format_func=lambda value: (
                component_labels[value]
            ),
        )

        variant_key = st.text_input(
            "Variant key",
            value=str(
                values.get(
                    "variant_key"
                )
                or ""
            ),
            placeholder="PINK_OBI",
        )

        variant_label = st.text_input(
            "Variant label",
            value=str(
                values.get(
                    "variant_label"
                )
                or ""
            ),
            placeholder="Pink obi issue",
        )

        expectation_state = st.selectbox(
            "Reference state",
            options=list(
                REFERENCE_STATES
            ),
            index=list(
                REFERENCE_STATES
            ).index(
                default_state
            ),
        )

        expected_quantity = st.number_input(
            "Expected quantity",
            min_value=0,
            max_value=100,
            value=int(
                values.get(
                    "expected_quantity"
                )
                if values.get(
                    "expected_quantity"
                ) is not None
                else (
                    0
                    if default_state ==
                        "NOT_INCLUDED"
                    else 1
                )
            ),
            step=1,
        )

        evidence_source = st.selectbox(
            "Reviewed evidence source",
            options=source_keys,
            index=source_keys.index(
                default_source
            ),
            format_func=lambda value: (
                source_labels[value]
            ),
        )

        confidence = st.number_input(
            "Confidence",
            min_value=0.0,
            max_value=1.0,
            value=float(
                values.get(
                    "confidence"
                )
                or 0.90
            ),
            step=0.01,
            format="%.2f",
        )

        notes = st.text_area(
            "Collector notes",
            value=str(
                values.get(
                    "notes"
                )
                or ""
            ),
        )

        actor = st.text_input(
            "Actor or workflow",
            value="STREAMLIT_REFERENCE_ADMIN",
        )

        reason = st.text_area(
            "Reason for this change",
            placeholder=(
                "Reviewed manufacturer catalog scan "
                "and physical complete copy."
            ),
        )

        submitted = st.form_submit_button(
            "Save reference record",
            type="primary",
            width="stretch",
        )

    return (
        {
            "pressing_id":
                pressing_id,
            "component_code":
                component_code,
            "variant_key":
                variant_key,
            "variant_label":
                variant_label,
            "expectation_state":
                expectation_state,
            "expected_quantity":
                expected_quantity,
            "evidence_source":
                evidence_source,
            "confidence":
                confidence,
            "notes":
                notes,
        },
        actor,
        reason,
        submitted,
    )


def _render_create_record(
    engine: Engine,
    pressing_id: int,
    components: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> None:
    """Create a real persisted expectation record."""
    st.subheader("Create a new reference record")

    st.caption(
        "This form inserts a real row into "
        "warehouse.pressing_component_expectation. "
        "It is not merely a worksheet preview."
    )

    payload, actor, reason, submitted = (
        _reference_payload_form(
            form_key=(
                "create-reference-record:"
                f"{pressing_id}"
            ),
            pressing_id=pressing_id,
            components=components,
            sources=sources,
        )
    )

    if not submitted:
        return

    try:
        record = create_reference_record(
            engine,
            payload,
            actor=actor,
            reason=reason,
        )
    except ValueError as error:
        st.error(str(error))
    else:
        _rerun(
            "Reference record created: "
            f"#{record['id']} "
            f"{record['component_code']}."
        )


def _render_manage_records(
    engine: Engine,
    pressing_id: int,
    components: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> None:
    """Edit or delete current persisted records."""
    st.subheader("Current reference records")

    records = list_reference_records(
        engine,
        pressing_id,
    )

    if not records:
        st.info(
            "This pressing has no persisted reference records yet."
        )
        return

    st.dataframe(
        pd.DataFrame(records),
        width="stretch",
        hide_index=True,
    )

    record_by_id = {
        int(row["id"]): row
        for row in records
    }

    record_id = st.selectbox(
        "Reference record",
        options=list(
            record_by_id
        ),
        format_func=lambda value: (
            _record_label(
                record_by_id[value]
            )
        ),
    )

    selected = record_by_id[
        record_id
    ]

    payload, actor, reason, submitted = (
        _reference_payload_form(
            form_key=(
                "edit-reference-record:"
                f"{record_id}"
            ),
            pressing_id=pressing_id,
            components=components,
            sources=sources,
            defaults=selected,
        )
    )

    if submitted:
        try:
            record = update_reference_record(
                engine,
                record_id,
                payload,
                actor=actor,
                reason=reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Reference record updated: "
                f"#{record['id']}."
            )

    st.markdown("#### Delete record")

    st.warning(
        "Deletion removes the current row but preserves its "
        "immutable before-state in audit history."
    )

    delete_actor = st.text_input(
        "Deletion actor",
        value="STREAMLIT_REFERENCE_ADMIN",
        key=f"delete-actor:{record_id}",
    )

    delete_reason = st.text_area(
        "Deletion reason",
        key=f"delete-reason:{record_id}",
    )

    delete_confirmed = st.checkbox(
        "I reviewed the record and intend to delete its current state.",
        key=f"delete-confirm:{record_id}",
    )

    if st.button(
        "Delete current reference record",
        type="secondary",
        width="stretch",
        disabled=not delete_confirmed,
        key=f"delete-record:{record_id}",
    ):
        try:
            deleted = delete_reference_record(
                engine,
                record_id,
                actor=delete_actor,
                reason=delete_reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Reference record deleted with audit history: "
                f"#{deleted['id']}."
            )


def _render_attachments(
    engine: Engine,
    pressing_id: int,
    sources: list[dict[str, Any]],
) -> None:
    """Register and manage evidence attachments."""
    st.subheader("Evidence attachments")

    records = list_reference_records(
        engine,
        pressing_id,
    )

    if not records:
        st.info(
            "Create a reference record before attaching evidence."
        )
        return

    record_by_id = {
        int(row["id"]): row
        for row in records
    }

    record_id = st.selectbox(
        "Attach evidence to record",
        options=list(
            record_by_id
        ),
        format_func=lambda value: (
            _record_label(
                record_by_id[value]
            )
        ),
        key="attachment-record",
    )

    record = record_by_id[
        record_id
    ]

    source_keys = [
        str(row["source_key"])
        for row in sources
    ]

    source_labels = {
        str(row["source_key"]): (
            f"{row['source_key']} — "
            f"{row['display_name']}"
        )
        for row in sources
    }

    with st.form(
        f"attachment-form:{record_id}",
        clear_on_submit=False,
    ):
        source_key = st.selectbox(
            "Evidence source",
            options=source_keys,
            format_func=lambda value: (
                source_labels[value]
            ),
        )

        attachment_kind = st.selectbox(
            "Attachment kind",
            options=list(
                ATTACHMENT_KINDS
            ),
        )

        uri = st.text_input(
            "URI or archive path",
            placeholder=(
                "https://example.org/catalog/page "
                "or archives/catalogs/file.pdf"
            ),
        )

        checksum = st.text_input(
            "SHA-256 checksum",
            placeholder="64 hexadecimal characters",
        )

        mime_type = st.text_input(
            "MIME type",
            placeholder="application/pdf",
        )

        captured_at = st.text_input(
            "Captured timestamp (ISO 8601)",
            placeholder="2026-08-03T15:55:17-04:00",
        )

        page_reference = st.text_input(
            "Page, image, or frame reference",
            placeholder="Page 12",
        )

        notes = st.text_area(
            "Attachment notes",
        )

        actor = st.text_input(
            "Attachment actor",
            value="STREAMLIT_REFERENCE_ADMIN",
        )

        reason = st.text_area(
            "Attachment registration reason",
        )

        submitted = st.form_submit_button(
            "Register evidence attachment",
            type="primary",
            width="stretch",
        )

    if submitted:
        entity_key = {
            "id":
                record["id"],
            "pressing_id":
                record["pressing_id"],
            "component_code":
                record["component_code"],
            "variant_key":
                record["variant_key"],
        }

        try:
            attachment = register_attachment(
                engine,
                {
                    "entity_type":
                        "PRESSING_COMPONENT_EXPECTATION",
                    "entity_key":
                        entity_key,
                    "source_key":
                        source_key,
                    "attachment_kind":
                        attachment_kind,
                    "uri":
                        uri,
                    "sha256":
                        checksum,
                    "mime_type":
                        mime_type,
                    "captured_at":
                        captured_at,
                    "page_reference":
                        page_reference,
                    "notes":
                        notes,
                },
                actor=actor,
                reason=reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Evidence attachment registered: "
                f"#{attachment['id']}."
            )

    attachments = list_attachments(
        engine,
        entity_type=(
            "PRESSING_COMPONENT_EXPECTATION"
        ),
        pressing_id=pressing_id,
        include_inactive=True,
    )

    st.markdown("#### Registered attachments")

    if not attachments:
        st.info(
            "No attachment metadata is registered for this pressing."
        )
        return

    st.dataframe(
        pd.DataFrame(attachments),
        width="stretch",
        hide_index=True,
        column_config={
            "uri":
                st.column_config.LinkColumn(
                    "URI"
                ),
            "active":
                st.column_config.CheckboxColumn(
                    "Active"
                ),
        },
    )

    attachment_by_id = {
        int(row["id"]): row
        for row in attachments
    }

    attachment_id = st.selectbox(
        "Attachment to deactivate",
        options=list(
            attachment_by_id
        ),
        format_func=lambda value: (
            f"#{value} · "
            f"{attachment_by_id[value]['attachment_kind']} · "
            f"{attachment_by_id[value]['uri']}"
        ),
    )

    deactivate_reason = st.text_area(
        "Deactivation reason",
        key=f"attachment-reason:{attachment_id}",
    )

    if st.button(
        "Deactivate attachment",
        width="stretch",
        disabled=not bool(
            attachment_by_id[
                attachment_id
            ]["active"]
        ),
    ):
        try:
            deactivate_attachment(
                engine,
                attachment_id,
                actor="STREAMLIT_REFERENCE_ADMIN",
                reason=deactivate_reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                f"Attachment #{attachment_id} deactivated."
            )


def _render_audit_history(
    engine: Engine,
    pressing_id: int,
) -> None:
    """Display immutable history and reviewed restoration."""
    st.subheader("Immutable audit history")

    entity_type = st.selectbox(
        "Entity history",
        options=[
            "PRESSING_COMPONENT_EXPECTATION",
            "AUCTION_COMPONENT_OBSERVATION",
            "EVIDENCE_SOURCE",
            "EVIDENCE_ATTACHMENT",
        ],
    )

    events = list_audit_events(
        engine,
        entity_type=entity_type,
        pressing_id=(
            pressing_id
            if entity_type in {
                "PRESSING_COMPONENT_EXPECTATION",
                "EVIDENCE_ATTACHMENT",
            }
            else None
        ),
        limit=500,
    )

    if not events:
        st.info(
            "No matching audit events exist yet."
        )
        return

    display_rows = []

    for event in events:
        display_rows.append(
            {
                **event,
                "entity_key":
                    json.dumps(
                        event[
                            "entity_key"
                        ],
                        ensure_ascii=False,
                        default=str,
                    ),
                "before_state":
                    json.dumps(
                        event[
                            "before_state"
                        ],
                        ensure_ascii=False,
                        default=str,
                    )
                    if event[
                        "before_state"
                    ] is not None
                    else None,
                "after_state":
                    json.dumps(
                        event[
                            "after_state"
                        ],
                        ensure_ascii=False,
                        default=str,
                    )
                    if event[
                        "after_state"
                    ] is not None
                    else None,
            }
        )

    st.dataframe(
        pd.DataFrame(
            display_rows
        ),
        width="stretch",
        hide_index=True,
    )

    if entity_type != (
        "PRESSING_COMPONENT_EXPECTATION"
    ):
        return

    restorable = {
        int(event["id"]): event
        for event in events
        if event[
            "after_state"
        ] is not None
    }

    if not restorable:
        return

    st.markdown(
        "#### Restore a reviewed prior after-state"
    )

    event_id = st.selectbox(
        "Audit event",
        options=list(
            restorable
        ),
        format_func=lambda value: (
            f"#{value} · "
            f"{restorable[value]['action']} · "
            f"{restorable[value]['created_at']} · "
            f"{restorable[value]['actor']}"
        ),
    )

    st.json(
        restorable[
            event_id
        ]["after_state"],
        expanded=False,
    )

    restore_actor = st.text_input(
        "Restoration actor",
        value="STREAMLIT_REFERENCE_ADMIN",
    )

    restore_reason = st.text_area(
        "Reason for restoring this revision",
    )

    restore_confirmed = st.checkbox(
        "I reviewed this exact after-state and intend to restore it.",
    )

    if st.button(
        "Restore selected revision",
        type="primary",
        width="stretch",
        disabled=not restore_confirmed,
    ):
        try:
            restored = restore_reference_event(
                engine,
                event_id,
                actor=restore_actor,
                reason=restore_reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Reference revision restored as a new audited event: "
                f"record #{restored['id']}."
            )


def _render_bulk_history(
    engine: Engine,
) -> None:
    """Display bulk-import batch and row history."""
    st.subheader("Bulk observation import history")

    batches = list_bulk_batches(
        engine
    )

    if not batches:
        st.info(
            "No audited bulk observation batch exists yet."
        )
        return

    st.dataframe(
        pd.DataFrame(batches),
        width="stretch",
        hide_index=True,
    )

    batch_by_id = {
        str(row["id"]): row
        for row in batches
    }

    batch_id = st.selectbox(
        "Batch details",
        options=list(
            batch_by_id
        ),
        format_func=lambda value: (
            f"{value} · "
            f"{batch_by_id[value]['status']} · "
            f"{batch_by_id[value]['created_at']}"
        ),
    )

    rows = list_bulk_batch_rows(
        engine,
        batch_id,
    )

    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    """Render the real reference-record administration page."""
    st.title("🗃️ Reference Record Admin")

    st.caption(
        "Create and maintain real component-reference records, "
        "register checksummed evidence attachments, inspect immutable "
        "history, restore reviewed revisions, and inspect audited "
        "bulk-import batches."
    )

    message = st.session_state.pop(
        "reference_record_admin_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    pressings = list_pressings(
        engine
    )

    if not pressings:
        st.warning(
            "Create an exact pressing in Completeness Reference first."
        )
        return

    components = list_active_components(
        engine
    )

    sources = list_active_sources(
        engine
    )

    if not sources:
        st.warning(
            "Create an active evidence source in "
            "Evidence and Bulk Observations first."
        )
        return

    pressing_by_id = {
        int(row["id"]): row
        for row in pressings
    }

    pressing_id = st.selectbox(
        "Exact pressing",
        options=list(
            pressing_by_id
        ),
        format_func=lambda value: (
            _pressing_label(
                pressing_by_id[value]
            )
        ),
    )

    current_records = list_reference_records(
        engine,
        pressing_id,
    )

    metric_columns = st.columns(4)

    metric_columns[0].metric(
        "Pressing ID",
        pressing_id,
    )

    metric_columns[1].metric(
        "Current records",
        len(current_records),
    )

    metric_columns[2].metric(
        "Active components",
        len(components),
    )

    metric_columns[3].metric(
        "Active evidence sources",
        len(sources),
    )

    tabs = st.tabs(
        [
            "Create record",
            "Manage records",
            "Attachments",
            "Audit history",
            "Bulk batch history",
        ]
    )

    with tabs[0]:
        _render_create_record(
            engine,
            pressing_id,
            components,
            sources,
        )

    with tabs[1]:
        _render_manage_records(
            engine,
            pressing_id,
            components,
            sources,
        )

    with tabs[2]:
        _render_attachments(
            engine,
            pressing_id,
            sources,
        )

    with tabs[3]:
        _render_audit_history(
            engine,
            pressing_id,
        )

    with tabs[4]:
        _render_bulk_history(
            engine
        )


main()
