"""Tests for general exact-pressing evidence intake."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from auction_etl.services.evidence_intake import (
    ComponentClaim,
    IntakeRequest,
    validate_request,
    stage_reviewed_intake,
)


def _packet(
    root: Path,
) -> Path:
    """Create a minimal general packet."""
    packet = root / "packet"
    packet.mkdir()

    (
        packet
        / "packet-summary.json"
    ).write_text(
        json.dumps(
            {
                "catalog":
                    "TEST-100",
                "pressing_id":
                    42,
                "pressing": {
                    "pressing_id":
                        42,
                    "catalog_number":
                        "TEST-100",
                    "display_artist":
                        "Test Artist",
                    "display_title":
                        "Test Title",
                },
                "workflow_status":
                    "AWAITING_EVIDENCE",
                "database_writes":
                    0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with (
        packet
        / "stage-03-attachment-review.csv"
    ).open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "apply",
                "source_key",
                "attachment_kind",
                "uri",
                "sha256",
                "mime_type",
                "captured_at",
                "page_reference",
                "notes",
                "actor",
                "reason",
            ),
            lineterminator="\n",
        )

        writer.writeheader()

        writer.writerow(
            {
                "apply":
                    "FALSE",
                "notes":
                    "AWAITING_EVIDENCE",
            }
        )

    with (
        packet
        / "stage-04-reference-review.csv"
    ).open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "action",
                "id",
                "component_code",
                "display_name",
                "variant_key",
                "variant_label",
                "expectation_state",
                "expected_quantity",
                "evidence_source",
                "confidence",
                "notes",
            ),
            lineterminator="\n",
        )

        writer.writeheader()

        writer.writerow(
            {
                "action":
                    "NO_CHANGE",
                "component_code":
                    "OBI",
                "display_name":
                    "Obi",
                "expectation_state":
                    "UNKNOWN",
            }
        )

    (
        packet
        / "manifest.json"
    ).write_text(
        "{}\n",
        encoding="utf-8",
    )

    return packet


def _request(
    packet: Path,
) -> IntakeRequest:
    """Create one valid reviewed request."""
    return IntakeRequest(
        packet_dir=
            packet,
        source_key=
            "CATALOG_ARCHIVE",
        attachment_kind=
            "CATALOG_SCAN",
        uri=
            "file:///archive/test-100.jpg",
        sha256=
            "a" * 64,
        mime_type=
            "image/jpeg",
        captured_at=
            "2026-08-04T13:21:00-04:00",
        page_reference=
            "Page 7",
        evidence_notes=(
            "The exact catalog page lists the obi "
            "as included with this pressing."
        ),
        actor=
            "Test Reviewer",
        reason=(
            "Verify exact-pressing component "
            "requirements from archival evidence."
        ),
        confirms_exact_pressing_scope=
            True,
        claims=(
            ComponentClaim(
                component_code=
                    "OBI",
                expectation_state=
                    "REQUIRED",
                expected_quantity=
                    1,
                confidence=
                    Decimal(
                        "0.9900"
                    ),
                notes=(
                    "The source explicitly lists one obi "
                    "for this exact pressing."
                ),
            ),
        ),
    )


def test_listing_title_source_is_blocked(
    tmp_path: Path,
) -> None:
    """Listing observations cannot become shared references."""
    request = _request(
        _packet(
            tmp_path
        )
    )

    request = IntakeRequest(
        **{
            **request.__dict__,
            "source_key":
                "LISTING_TITLE",
        }
    )

    errors = validate_request(
        request,
        active_source_keys=(
            "LISTING_TITLE",
        ),
        active_component_codes=(
            "OBI",
        ),
    )

    assert any(
        "listing-specific"
        in error.lower()
        for error in errors
    )


def test_reviewed_intake_stages_component_scoped_rows(
    tmp_path: Path,
) -> None:
    """One source creates matching stage-three and stage-four rows."""
    packet = _packet(
        tmp_path
    )

    (
        attachments,
        references,
        manifest_files,
    ) = stage_reviewed_intake(
        _request(
            packet
        ),
        active_source_keys=(
            "CATALOG_ARCHIVE",
        ),
        active_component_codes=(
            "OBI",
        ),
    )

    assert attachments == 1
    assert references == 1
    assert manifest_files >= 3

    with (
        packet
        / "stage-03-attachment-review.csv"
    ).open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(
            csv.DictReader(handle)
        )

    applied = [
        row
        for row in rows
        if row["apply"] == "TRUE"
    ]

    assert len(applied) == 1
    assert (
        applied[0]["entity_type"]
        == "PRESSING_COMPONENT_EXPECTATION"
    )

    entity_key = json.loads(
        applied[0]["entity_key"]
    )

    assert entity_key == {
        "component_code":
            "OBI",
        "pressing_id":
            42,
        "variant_key":
            "",
    }

    with (
        packet
        / "stage-04-reference-review.csv"
    ).open(
        encoding="utf-8",
        newline="",
    ) as handle:
        reference_rows = list(
            csv.DictReader(handle)
        )

    assert reference_rows[0]["action"] == "UPSERT"
    assert (
        reference_rows[0]["expectation_state"]
        == "REQUIRED"
    )
    assert reference_rows[0]["expected_quantity"] == "1"
    assert (
        reference_rows[0]["evidence_source"]
        == "CATALOG_ARCHIVE"
    )
    assert reference_rows[0]["confidence"] == "0.9900"

    summary = json.loads(
        (
            packet
            / "packet-summary.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert summary["workflow_status"] == "REVIEW_READY"
    assert summary["mutation_status"] == "PENDING_SAFE_REVIEW"
    assert summary["database_writes"] == 0


def test_unsupported_components_remain_untouched(
    tmp_path: Path,
) -> None:
    """Intake modifies only explicitly selected components."""
    packet = _packet(
        tmp_path
    )

    stage_4 = (
        packet
        / "stage-04-reference-review.csv"
    )

    with stage_4.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(
            handle,
            lineterminator="\n",
        )

        writer.writerow(
            (
                "NO_CHANGE",
                "",
                "POSTER",
                "Poster",
                "",
                "",
                "UNKNOWN",
                "",
                "",
                "",
                "",
            )
        )

    stage_reviewed_intake(
        _request(
            packet
        ),
        active_source_keys=(
            "CATALOG_ARCHIVE",
        ),
        active_component_codes=(
            "OBI",
            "POSTER",
        ),
    )

    with stage_4.open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(
            csv.DictReader(handle)
        )

    poster = next(
        row
        for row in rows
        if row["component_code"] == "POSTER"
    )

    assert poster["action"] == "NO_CHANGE"
    assert poster["expectation_state"] == "UNKNOWN"
    assert poster["expected_quantity"] == ""
    assert poster["confidence"] == ""
    assert poster["evidence_source"] == ""
