"""Pressing curation packet exporter tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from scripts.export_pressing_curation_packet import (
    attachment_template,
    comparable_review_rows,
    normalized_catalog,
    reference_review_rows,
)


SCRIPT = Path(
    "scripts/export_pressing_curation_packet.py"
)


def test_catalog_normalization_is_exact_and_general() -> None:
    """Spaces and punctuation do not alter catalog matching."""
    assert normalized_catalog(
        "MR 2276"
    ) == "MR2276"

    assert normalized_catalog(
        "TATL-2314〜5"
    ) == "TATL23145"


def test_reference_rows_are_disabled_by_default() -> None:
    """Exported shared-reference rows cannot apply themselves."""
    rows = reference_review_rows(
        [
            {
                "id":
                    None,
                "component_code":
                    "OBI",
                "display_name":
                    "Obi",
                "expectation_state":
                    "UNKNOWN",
            }
        ]
    )

    assert rows[0][
        "action"
    ] == "NO_CHANGE"

    assert rows[0][
        "expectation_state"
    ] == "UNKNOWN"


def test_attachment_template_requires_content_checksum() -> None:
    """Attachment review remains explicitly disabled."""
    row = attachment_template()[0]

    assert row["apply"] == "FALSE"
    assert row["sha256"] == ""
    assert "content checksum" in row["notes"]


def test_comparable_export_is_read_only() -> None:
    """Comparable packet creation does not call the save service."""
    source = inspect.getsource(
        comparable_review_rows
    )

    assert "list_comparable_candidates" in source
    assert "save_comparable_review" not in source
    assert '"apply":\n                        "FALSE"' in source


def test_exporter_contains_no_database_mutation_sql() -> None:
    """The exporter performs only SELECT-based database work."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    ).upper()

    prohibited = (
        "INSERT INTO ",
        "UPDATE WAREHOUSE.",
        "DELETE FROM ",
        "TRUNCATE ",
        "ALTER TABLE ",
        "DROP TABLE ",
    )

    for fragment in prohibited:
        assert fragment not in source


def test_exporter_has_complete_entry_point() -> None:
    """The packet exporter is directly executable."""
    tree = ast.parse(
        SCRIPT.read_text(
            encoding="utf-8"
        )
    )

    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert {
        "main",
        "resolve_pressing",
        "write_readme",
        "readiness_rows",
        "verdict_rows",
    } <= function_names
