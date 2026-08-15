"""Regression tests for stable-reference evidence schema compatibility."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[
    1
]

RUNNER = (
    REPOSITORY_ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py"
)


def stable_reference_function_source() -> str:
    """Return stable_reference_evidence() source."""

    source = RUNNER.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(RUNNER),
    )

    functions = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name
            == "stable_reference_evidence"
        )
    ]

    assert len(functions) == 1

    return (
        ast.get_source_segment(
            source,
            functions[0],
        )
        or ""
    )


def test_stable_reference_query_uses_schema_tolerant_optional_fields() -> None:
    """Avoid requiring optional warehouse columns to exist physically."""

    source = stable_reference_function_source()

    required = (
        "to_jsonb(auction)->>'label'",
        "to_jsonb(auction)->>'record_label'",
        "to_jsonb(auction)->>'release_country'",
        "to_jsonb(auction)->>'release_format'",
        "to_jsonb(auction)->>'media_type'",
        "to_jsonb(auction)->>'release_year'",
        "to_jsonb(auction)->'payload'",
        "FROM warehouse.auction AS auction",
    )

    missing = [
        value
        for value in required
        if value not in source
    ]

    assert not missing, (
        "Missing schema-tolerant evidence fields: "
        + ", ".join(
            missing
        )
    )


def test_stable_reference_query_has_no_direct_optional_column_selects() -> None:
    """Prevent optional evidence fields from becoming required columns."""

    source = stable_reference_function_source()

    forbidden = (
        "\n            label,\n",
        "\n            format,\n",
        "\n            year,\n",
        "\n            payload\n",
    )

    remaining = [
        value
        for value in forbidden
        if value in source
    ]

    assert not remaining


def test_stable_reference_query_keeps_required_identity_columns() -> None:
    """Keep stable marketplace identity fields as required columns."""

    source = stable_reference_function_source()

    required = (
        "btrim(marketplace)",
        "listing_id,",
        "title,",
        "catalog_number,",
    )

    missing = [
        value
        for value in required
        if value not in source
    ]

    assert not missing
