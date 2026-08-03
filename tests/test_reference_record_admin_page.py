"""Real reference-record administration page tests."""

from __future__ import annotations

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/4_Reference_Record_Admin.py"
)

BULK_PAGE = Path(
    "app/pages/3_Evidence_and_Bulk_Observations.py"
)


def test_page_exposes_real_record_crud() -> None:
    """The page creates and updates persisted records."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Create a new reference record",
        "This form inserts a real row",
        "create_reference_record(",
        "update_reference_record(",
        "delete_reference_record(",
        "Current reference records",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_exposes_attachments_and_history() -> None:
    """Checksummed attachments and immutable history are visible."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Evidence attachments",
        "SHA-256 checksum",
        "register_attachment(",
        "Immutable audit history",
        "restore_reference_event(",
        "Bulk observation import history",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_page_has_full_workflow_functions() -> None:
    """Each workflow is a complete rendering function."""
    tree = ast.parse(
        PAGE.read_text(
            encoding="utf-8"
        )
    )

    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    required = {
        "_render_create_record",
        "_render_manage_records",
        "_render_attachments",
        "_render_audit_history",
        "_render_bulk_history",
        "main",
    }

    assert required <= names


def test_existing_bulk_page_uses_audited_service() -> None:
    """The previous bulk page now records batch history."""
    source = BULK_PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "apply_audited_bulk_observations "
        "as apply_bulk_observations"
        in source
    )


# reference-page-widget-regression:start
def test_page_uses_supported_optional_timestamp_input() -> None:
    """The page does not call a nonexistent Streamlit widget."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "st.datetime_input" not in source
    assert (
        "Captured timestamp (ISO 8601)"
        in source
    )
# reference-page-widget-regression:end
