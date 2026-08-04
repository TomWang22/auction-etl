"""Tests for safe pressing-packet review and application."""

from __future__ import annotations

from decimal import Decimal

from scripts.review_and_apply_pressing_packet import (
    AttachmentInput,
    ReferenceInput,
    attachment_supports_reference,
    parse_bool,
    validate_reference,
)


def reference(
    *,
    state: str = "REQUIRED",
    confidence: Decimal = Decimal("0.9900"),
) -> ReferenceInput:
    """Build one reviewed reference input."""
    return ReferenceInput(
        row_number=2,
        action="UPSERT",
        component_code="OBI",
        variant_key="",
        variant_label=None,
        expectation_state=state,
        expected_quantity=(
            1
            if state == "REQUIRED"
            else 0
        ),
        evidence_source="CATALOG_SCAN",
        confidence=confidence,
        notes=(
            "Verified against the attached collector "
            "catalog source."
        ),
        reason=None,
    )


def attachment(
    *,
    apply: bool = True,
    component_code: str = "OBI",
) -> AttachmentInput:
    """Build one reviewed source attachment."""
    return AttachmentInput(
        row_number=2,
        apply=apply,
        entity_type="PRESSING_IDENTITY",
        entity_key={
            "pressing_id":
                2,
            "component_code":
                component_code,
        },
        source_key="CATALOG_SCAN",
        attachment_kind="CATALOG_SCAN",
        uri="file:///collector/reference/mr2276-page.jpg",
        sha256="a" * 64,
        mime_type="image/jpeg",
        captured_at=None,
        page_reference="Page 12",
        notes="Verified catalog scan for the exact pressing.",
    )


def test_parse_bool_supports_packet_values() -> None:
    """Packet Boolean values are deterministic."""
    assert parse_bool("TRUE") is True
    assert parse_bool("yes") is True
    assert parse_bool("FALSE") is False
    assert parse_bool("") is False


def test_definitive_reference_requires_attachment() -> None:
    """Required or excluded components need matching evidence."""
    errors = validate_reference(
        reference(),
        pressing_id=2,
        active_components={
            "OBI",
        },
        active_sources={
            "CATALOG_SCAN",
        },
        attachments=[],
    )

    assert any(
        "matching stage-three attachment"
        in error
        for error in errors
    )


def test_matching_attachment_supports_reference() -> None:
    """A pressing/component attachment supports that exact claim."""
    assert attachment_supports_reference(
        attachment(),
        reference(),
        pressing_id=2,
    )


def test_other_component_attachment_does_not_support_reference() -> None:
    """Evidence for one component cannot support another."""
    assert not attachment_supports_reference(
        attachment(
            component_code="POSTER"
        ),
        reference(),
        pressing_id=2,
    )


def test_low_confidence_definitive_claim_is_blocked() -> None:
    """Definitive claims require the configured minimum confidence."""
    errors = validate_reference(
        reference(
            confidence=Decimal("0.7000")
        ),
        pressing_id=2,
        active_components={
            "OBI",
        },
        active_sources={
            "CATALOG_SCAN",
        },
        attachments=[
            attachment()
        ],
    )

    assert any(
        "confidence >="
        in error
        for error in errors
    )


def test_complete_verified_reference_is_accepted() -> None:
    """A complete source-backed reference has no blockers."""
    errors = validate_reference(
        reference(),
        pressing_id=2,
        active_components={
            "OBI",
        },
        active_sources={
            "CATALOG_SCAN",
        },
        attachments=[
            attachment()
        ],
    )

    assert errors == []


def test_not_included_requires_zero_quantity() -> None:
    """Excluded components cannot claim a positive quantity."""
    row = ReferenceInput(
        row_number=2,
        action="UPSERT",
        component_code="POSTER",
        variant_key="",
        variant_label=None,
        expectation_state="NOT_INCLUDED",
        expected_quantity=1,
        evidence_source="CATALOG_SCAN",
        confidence=Decimal("0.9900"),
        notes=(
            "Verified against an exact catalog "
            "component inventory."
        ),
        reason=None,
    )

    errors = validate_reference(
        row,
        pressing_id=2,
        active_components={
            "POSTER",
        },
        active_sources={
            "CATALOG_SCAN",
        },
        attachments=[
            attachment(
                component_code="POSTER"
            )
        ],
    )

    assert any(
        "expected_quantity=0"
        in error
        for error in errors
    )


def test_legacy_stage_three_defaults_to_pressing_identity(
    tmp_path,
) -> None:
    """Legacy pressing-scoped packets need no entity_type column."""
    import csv

    from scripts.review_and_apply_pressing_packet import (
        parse_attachment_rows,
    )

    packet = tmp_path
    worksheet = (
        packet
        / "stage-03-attachment-review.csv"
    )

    fieldnames = (
        "apply",
        "source_key",
        "attachment_kind",
        "uri",
        "sha256",
        "mime_type",
        "captured_at",
        "page_reference",
        "notes",
    )

    with worksheet.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )

        writer.writeheader()

        writer.writerow(
            {
                "apply":
                    "FALSE",
                "source_key":
                    "",
                "attachment_kind":
                    "",
                "uri":
                    "",
                "sha256":
                    "",
                "mime_type":
                    "",
                "captured_at":
                    "",
                "page_reference":
                    "",
                "notes":
                    "",
            }
        )

    rows = parse_attachment_rows(
        packet,
        pressing_id=2,
    )

    assert len(rows) == 1
    assert rows[0].entity_type == "PRESSING_IDENTITY"
    assert rows[0].entity_key == {
        "pressing_id":
            2,
    }
    assert rows[0].apply is False


def test_explicit_stage_three_entity_type_is_preserved(
    tmp_path,
) -> None:
    """Newer packet schemas may still provide an explicit target."""
    import csv

    from scripts.review_and_apply_pressing_packet import (
        parse_attachment_rows,
    )

    worksheet = (
        tmp_path
        / "stage-03-attachment-review.csv"
    )

    fieldnames = (
        "apply",
        "entity_type",
        "source_key",
        "attachment_kind",
        "uri",
        "sha256",
        "mime_type",
        "captured_at",
        "page_reference",
        "notes",
    )

    with worksheet.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )

        writer.writeheader()

        writer.writerow(
            {
                "apply":
                    "FALSE",
                "entity_type":
                    "PRESSING_COMPONENT_EXPECTATION",
                "source_key":
                    "",
                "attachment_kind":
                    "",
                "uri":
                    "",
                "sha256":
                    "",
                "mime_type":
                    "",
                "captured_at":
                    "",
                "page_reference":
                    "",
                "notes":
                    "",
            }
        )

    rows = parse_attachment_rows(
        tmp_path,
        pressing_id=2,
    )

    assert (
        rows[0].entity_type
        == "PRESSING_COMPONENT_EXPECTATION"
    )


def test_component_registry_is_discovered_from_schema() -> None:
    """The packet reviewer cannot assume a nonexistent table."""
    import inspect

    from scripts.review_and_apply_pressing_packet import (
        KNOWN_COMPONENT_CODES,
        load_active_component_codes,
        load_database_contract,
    )

    discovery_source = inspect.getsource(
        load_active_component_codes
    )

    contract_source = inspect.getsource(
        load_database_contract
    )

    assert "information_schema.columns" in discovery_source
    assert "sql.Identifier" in discovery_source
    assert "display_name" in discovery_source
    assert "applicable_media" in discovery_source
    assert "active" in discovery_source
    assert "load_active_component_codes(" in contract_source

    combined_source = (
        discovery_source
        + contract_source
    )

    assert (
        "FROM warehouse.component_type"
        not in combined_source
    )

    assert {
        "OBI",
        "INSERT",
        "LYRIC_SHEET",
        "POSTER",
        "PINUP",
        "BOOKLET",
        "J_CARD",
        "INNER_SLEEVE",
        "BOX",
        "STICKER",
        "SHRINK_WRAP",
        "BONUS_MEDIA",
        "OTHER",
    } == KNOWN_COMPONENT_CODES
