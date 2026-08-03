"""Factory-sealed completeness exception contracts."""

from __future__ import annotations

import ast

import inspect
from pathlib import Path

import pytest

from auction_etl.services.completeness_reference import (
    FACTORY_SEALED_VARIANT_KEY,
    infer_factory_sealed_title_evidence,
    delete_factory_sealed_observation,
    save_factory_sealed_observation,
    validate_factory_sealed_evidence,
)


MIGRATION_UP = Path(
    "alembic/versions/f2a7c9e4b610_factory_sealed_completeness_exception_up.sql"
)

EDITOR = Path(
    "app/collector_analytics_editor.py"
)


def test_factory_sealed_validation_requires_explicit_evidence() -> None:
    """Source, URL, and high confidence are mandatory."""
    with pytest.raises(
        ValueError,
        match="evidence source",
    ):
        validate_factory_sealed_evidence(
            "",
            "https://example.test/item",
            "0.99",
        )

    with pytest.raises(
        ValueError,
        match="evidence URL",
    ):
        validate_factory_sealed_evidence(
            "LISTING_TITLE",
            "",
            "0.99",
        )

    with pytest.raises(
        ValueError,
        match="at least 0.90",
    ):
        validate_factory_sealed_evidence(
            "LISTING_TITLE",
            "https://example.test/item",
            "0.89",
        )


def test_factory_sealed_validation_builds_exact_identity() -> None:
    """The exception uses one explicit component variant."""
    evidence = validate_factory_sealed_evidence(
        "LISTING_TITLE",
        "https://example.test/item",
        "0.99",
        "Title explicitly says factory sealed.",
    )

    assert evidence["component_code"] == "SHRINK_WRAP"
    assert (
        evidence["variant_key"]
        == FACTORY_SEALED_VARIANT_KEY
    )
    assert evidence["observation_state"] == "PRESENT"
    assert evidence["observed_quantity"] == 1


def test_factory_sealed_writer_is_atomic_and_narrow() -> None:
    """Saving cannot replace unrelated observations."""
    source = inspect.getsource(
        save_factory_sealed_observation
    )

    assert "SERIALIZABLE" in source
    assert "auction_pressing_assignment" in source
    assert "component_code = 'SHRINK_WRAP'" in source
    assert "variant_key = 'FACTORY_SEALED'" in source
    assert "observation_state = 'ABSENT'" in source
    assert "pressing_component_expectation" not in source


def test_factory_sealed_delete_is_narrow() -> None:
    """Removal targets only the factory-sealed identity."""
    source = inspect.getsource(
        delete_factory_sealed_observation
    )

    assert "component_code = 'SHRINK_WRAP'" in source
    assert "variant_key = 'FACTORY_SEALED'" in source


def test_migration_preserves_unverified_hidden_components() -> None:
    """The SQL classifies without inventing observations."""
    source = MIGRATION_UP.read_text(
        encoding="utf-8"
    )

    assert "'FACTORY_SEALED_EXCEPTION'" in source
    assert "variant_key = 'FACTORY_SEALED'" in source
    assert "observation.confidence >= 0.9000" in source
    assert "seal.seal_contradiction" in source
    assert "unverified_components" in source
    assert "INSERT INTO" not in source
    assert "UPDATE warehouse" not in source


def test_factory_sealed_exception_is_not_complete() -> None:
    """Ordinary complete remains stricter than the exception."""
    source = MIGRATION_UP.read_text(
        encoding="utf-8"
    )

    complete_expression = source.split(
        "END AS completeness_status,",
        maxsplit=1,
    )[1]

    assert "FACTORY_SEALED_EXCEPTION" not in complete_expression
    assert "present_required_component_count" in complete_expression
    assert "unverified_components" in complete_expression


def test_editor_exposes_reviewed_exception_workflow() -> None:
    """The editor exposes reviewed evidence and safe autofill."""
    source = EDITOR.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    editor_function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_component_editor"
        ),
        None,
    )

    assert editor_function is not None

    call_names: set[str] = set()
    string_values: list[str] = []

    for node in ast.walk(editor_function):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            string_values.append(node.value)

        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name):
            call_names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            call_names.add(node.func.attr)

    rendered_text = "\n".join(string_values)

    assert (
        "Factory-sealed completeness exception"
        in rendered_text
    )
    assert (
        "Save factory-sealed evidence"
        in rendered_text
    )
    assert (
        "Remove factory-sealed evidence"
        in rendered_text
    )
    assert "SHRINK_WRAP" in rendered_text
    assert "FACTORY_SEALED" in rendered_text
    assert "Hidden inserts remain unverified" in rendered_text
    assert "does not set complete=true" in rendered_text
    assert (
        "does not automatically unlock normalized pricing"
        in rendered_text
    )
    assert (
        "automatically filled from"
        in rendered_text
    )

    assert "build_factory_sealed_prefill" in call_names
    assert "save_factory_sealed_observation" in call_names
    assert "delete_factory_sealed_observation" in call_names

    assert "record SEALED as " not in source


def test_factory_sealed_english_title_autofills() -> None:
    """Explicit English wording supplies safe defaults."""
    result = infer_factory_sealed_title_evidence(
        "Teresa Teng LP FACTORY SEALED MR2276",
        "https://example.test/item",
    )

    assert result["eligible"] is True
    assert result["evidence_source"] == "LISTING_TITLE"
    assert result["evidence_url"] == "https://example.test/item"
    assert str(result["confidence"]) == "0.9900"
    assert "FACTORY SEALED" in result["notes"]


def test_factory_sealed_japanese_title_autofills() -> None:
    """Explicit unopened Japanese wording supplies defaults."""
    result = infer_factory_sealed_title_evidence(
        "テレサ・テン LP 新品未開封",
        "https://example.test/jp-item",
    )

    assert result["eligible"] is True
    assert result["evidence_source"] == "LISTING_TITLE"
    assert result["matched_text"] == "新品未開封"


def test_factory_sealed_contradiction_blocks_autofill() -> None:
    """Opened or resealed evidence defeats positive wording."""
    result = infer_factory_sealed_title_evidence(
        "SEALED STYLE SLEEVE - OPENED COPY",
        "https://example.test/opened",
    )

    assert result["eligible"] is False
    assert result["evidence_source"] == ""
    assert "contradictory" in result["blocker"]
