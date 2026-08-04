"""Filesystem-only evidence intake for exact-pressing review packets."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from sqlalchemy import Engine, text


ATTACHMENT_KINDS = (
    "CATALOG_SCAN",
    "PHYSICAL_COPY",
    "ARCHIVE_FILE",
    "IMAGE",
    "PDF",
    "URL",
    "LISTING_CAPTURE",
    "OTHER",
)

REFERENCE_STATES = (
    "REQUIRED",
    "NOT_INCLUDED",
)

LISTING_ONLY_SOURCE_KEYS = {
    "LISTING_TITLE",
    "AUCTION_TITLE_STATES",
    "AUCTION_TITLE_STATES_",
}

SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)


@dataclass(frozen=True)
class PacketOption:
    """One exact-pressing review packet."""

    path: Path
    catalog: str
    pressing_id: int
    artist: str
    title: str
    workflow_status: str
    modified_at: datetime

    @property
    def label(self) -> str:
        """Return a human-readable packet label."""
        return (
            f"Pressing #{self.pressing_id} · "
            f"{self.artist} · {self.title} · "
            f"{self.catalog} · {self.workflow_status}"
        )


@dataclass(frozen=True)
class EvidenceSource:
    """One active evidence-source registry entry."""

    source_key: str
    display_name: str
    source_type: str

    @property
    def label(self) -> str:
        """Return a human-readable source label."""
        return (
            f"{self.display_name} "
            f"({self.source_key}; {self.source_type})"
        )


@dataclass(frozen=True)
class ComponentType:
    """One active collector component type."""

    code: str
    display_name: str

    @property
    def label(self) -> str:
        """Return a human-readable component label."""
        return f"{self.display_name} ({self.code})"


@dataclass(frozen=True)
class ComponentClaim:
    """One reviewed exact-pressing component claim."""

    component_code: str
    expectation_state: str
    expected_quantity: int
    confidence: Decimal
    variant_key: str = ""
    variant_label: str = ""
    notes: str = ""


@dataclass(frozen=True)
class IntakeRequest:
    """One reviewed evidence-intake request."""

    packet_dir: Path
    source_key: str
    attachment_kind: str
    uri: str
    sha256: str
    mime_type: str
    captured_at: str
    page_reference: str
    evidence_notes: str
    actor: str
    reason: str
    confirms_exact_pressing_scope: bool
    claims: tuple[ComponentClaim, ...]


@dataclass(frozen=True)
class IntakeResult:
    """Filesystem staging and safe-review result."""

    packet_dir: Path
    attachment_rows_added: int
    reference_rows_updated: int
    manifest_files: int
    workflow_status: str
    review_status: str
    blockers: tuple[str, ...]
    planned_mutation_count: int
    database_writes: int


class EvidenceIntakeError(ValueError):
    """Raised when reviewed intake data is unsafe or incomplete."""


def _clean(value: Any) -> str:
    """Normalize optional text."""
    if value is None:
        return ""

    return str(value).strip()


def _token(value: Any) -> str:
    """Normalize one controlled token."""
    return _clean(value).upper()


def _decimal(value: Any) -> Decimal:
    """Parse one finite confidence value."""
    try:
        result = Decimal(
            _clean(value)
        )
    except InvalidOperation as error:
        raise EvidenceIntakeError(
            f"Invalid confidence value: {value!r}"
        ) from error

    if not result.is_finite():
        raise EvidenceIntakeError(
            "Confidence must be finite."
        )

    return result


def _canonical_json(
    value: Mapping[str, Any],
) -> str:
    """Return deterministic JSON text."""
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_csv(
    path: Path,
) -> tuple[list[str], list[dict[str, str]]]:
    """Read a UTF-8 CSV worksheet."""
    if not path.is_file():
        raise EvidenceIntakeError(
            f"Missing packet worksheet: {path}"
        )

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        if reader.fieldnames is None:
            raise EvidenceIntakeError(
                f"Worksheet has no header: {path}"
            )

        return (
            list(reader.fieldnames),
            [
                {
                    str(key): value or ""
                    for key, value in row.items()
                }
                for row in reader
            ],
        )


def _write_csv(
    path: Path,
    fieldnames: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Write one deterministic UTF-8 CSV worksheet."""
    columns = list(
        dict.fromkeys(
            str(field)
            for field in fieldnames
        )
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            lineterminator="\n",
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    column:
                        ""
                        if row.get(column) is None
                        else str(row.get(column))
                    for column in columns
                }
            )


def _load_summary(
    packet_dir: Path,
) -> dict[str, Any]:
    """Load and validate packet summary metadata."""
    path = (
        packet_dir
        / "packet-summary.json"
    )

    if not path.is_file():
        raise EvidenceIntakeError(
            f"Missing packet summary: {path}"
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise EvidenceIntakeError(
            "packet-summary.json must contain an object."
        )

    return payload


def _packet_identity(
    summary: Mapping[str, Any],
) -> tuple[str, int, str, str]:
    """Extract exact-pressing identity from packet metadata."""
    pressing = summary.get(
        "pressing"
    )

    pressing_payload = (
        pressing
        if isinstance(
            pressing,
            Mapping,
        )
        else {}
    )

    catalog = _clean(
        summary.get(
            "catalog",
            summary.get(
                "catalog_number",
                pressing_payload.get(
                    "catalog_number"
                ),
            ),
        )
    )

    raw_pressing_id = summary.get(
        "pressing_id",
        pressing_payload.get(
            "pressing_id"
        ),
    )

    try:
        pressing_id = int(
            raw_pressing_id
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise EvidenceIntakeError(
            "Packet has no valid pressing_id."
        ) from error

    artist = _clean(
        pressing_payload.get(
            "display_artist"
        )
    )

    title = _clean(
        pressing_payload.get(
            "display_title"
        )
    )

    if not catalog:
        raise EvidenceIntakeError(
            "Packet has no catalog number."
        )

    return (
        catalog,
        pressing_id,
        artist,
        title,
    )


def discover_packets(
    root: Path = Path("logs"),
) -> list[PacketOption]:
    """Discover all complete exact-pressing packets."""
    packets: list[PacketOption] = []

    if not root.exists():
        return packets

    required = (
        "packet-summary.json",
        "manifest.json",
        "stage-03-attachment-review.csv",
        "stage-04-reference-review.csv",
    )

    for summary_path in root.rglob(
        "packet-summary.json"
    ):
        packet_dir = summary_path.parent

        if not all(
            (
                packet_dir
                / filename
            ).is_file()
            for filename in required
        ):
            continue

        try:
            summary = _load_summary(
                packet_dir
            )

            (
                catalog,
                pressing_id,
                artist,
                title,
            ) = _packet_identity(
                summary
            )
        except (
            EvidenceIntakeError,
            json.JSONDecodeError,
            OSError,
        ):
            continue

        modified_timestamp = max(
            (
                packet_dir
                / filename
            ).stat().st_mtime
            for filename in required
        )

        packets.append(
            PacketOption(
                path=packet_dir,
                catalog=catalog,
                pressing_id=pressing_id,
                artist=artist,
                title=title,
                workflow_status=_clean(
                    summary.get(
                        "workflow_status",
                        "UNSPECIFIED",
                    )
                ),
                modified_at=datetime.fromtimestamp(
                    modified_timestamp,
                    tz=timezone.utc,
                ),
            )
        )

    packets.sort(
        key=lambda packet: (
            packet.modified_at,
            str(packet.path),
        ),
        reverse=True,
    )

    return packets


def list_active_sources(
    engine: Engine,
) -> list[EvidenceSource]:
    """Load active evidence sources."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    source_key,
                    display_name,
                    source_type
                FROM system.evidence_source_registry
                WHERE active
                ORDER BY
                    display_name,
                    source_key
                """
            )
        ).mappings().all()

    return [
        EvidenceSource(
            source_key=_token(
                row["source_key"]
            ),
            display_name=_clean(
                row["display_name"]
            ),
            source_type=_token(
                row["source_type"]
            ),
        )
        for row in rows
    ]


def list_active_components(
    engine: Engine,
) -> list[ComponentType]:
    """Load active collector component types."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    code,
                    display_name
                FROM system.component_type
                WHERE active
                ORDER BY
                    display_name,
                    code
                """
            )
        ).mappings().all()

    return [
        ComponentType(
            code=_token(
                row["code"]
            ),
            display_name=_clean(
                row["display_name"]
            ),
        )
        for row in rows
    ]


def clone_packet(
    source: Path,
    destination_root: Path = Path("logs"),
) -> Path:
    """Create a timestamped working packet copy."""
    source = source.resolve()

    summary = _load_summary(
        source
    )

    (
        catalog,
        pressing_id,
        _,
        _,
    ) = _packet_identity(
        summary
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    safe_catalog = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        catalog,
    ).strip("-").lower()

    destination = (
        destination_root
        / (
            "evidence-intake-"
            f"{timestamp}"
        )
        / (
            f"{safe_catalog}-"
            f"pressing-{pressing_id}-packet"
        )
    ).resolve()

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copytree(
        source,
        destination,
    )

    return destination


def store_uploaded_evidence(
    packet_dir: Path,
    filename: str,
    payload: bytes,
) -> tuple[str, str]:
    """Store uploaded evidence inside the working packet."""
    if not payload:
        raise EvidenceIntakeError(
            "Uploaded evidence file is empty."
        )

    digest = hashlib.sha256(
        payload
    ).hexdigest()

    safe_name = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        Path(filename).name,
    ).strip("-")

    if not safe_name:
        safe_name = "evidence.bin"

    evidence_dir = (
        packet_dir
        / "evidence"
    )

    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        evidence_dir
        / f"{digest}-{safe_name}"
    )

    if destination.exists():
        existing_digest = hashlib.sha256(
            destination.read_bytes()
        ).hexdigest()

        if existing_digest != digest:
            raise EvidenceIntakeError(
                "Existing packet evidence file has a "
                "different checksum."
            )
    else:
        destination.write_bytes(
            payload
        )

    return (
        destination.resolve().as_uri(),
        digest,
    )


def validate_request(
    request: IntakeRequest,
    active_source_keys: Iterable[str],
    active_component_codes: Iterable[str],
) -> tuple[str, ...]:
    """Validate reviewed evidence and exact-pressing claims."""
    errors: list[str] = []

    source_keys = {
        _token(value)
        for value in active_source_keys
    }

    component_codes = {
        _token(value)
        for value in active_component_codes
    }

    source_key = _token(
        request.source_key
    )

    if source_key not in source_keys:
        errors.append(
            "Evidence source is not active in the registry."
        )

    if source_key in LISTING_ONLY_SOURCE_KEYS:
        errors.append(
            "Listing-title evidence is listing-specific and cannot "
            "establish a shared exact-pressing completeness reference."
        )

    if request.attachment_kind not in ATTACHMENT_KINDS:
        errors.append(
            "Attachment kind is unsupported."
        )

    parsed_uri = urlparse(
        request.uri
    )

    if parsed_uri.scheme.lower() not in {
        "file",
        "http",
        "https",
        "s3",
        "archive",
    }:
        errors.append(
            "Evidence URI must use file, http, https, s3, "
            "or archive."
        )

    if not SHA256_PATTERN.fullmatch(
        request.sha256.lower()
    ):
        errors.append(
            "Evidence SHA-256 must contain 64 hexadecimal characters."
        )

    if len(
        _clean(
            request.evidence_notes
        )
    ) < 20:
        errors.append(
            "Evidence notes must contain at least 20 characters."
        )

    if len(
        _clean(
            request.actor
        )
    ) < 2:
        errors.append(
            "Reviewer identity is required."
        )

    if len(
        _clean(
            request.reason
        )
    ) < 20:
        errors.append(
            "Review reason must contain at least 20 characters."
        )

    if not request.confirms_exact_pressing_scope:
        errors.append(
            "Exact-pressing evidence scope must be confirmed."
        )

    if not request.claims:
        errors.append(
            "Select at least one explicitly supported component."
        )

    seen: set[tuple[str, str]] = set()

    for claim in request.claims:
        code = _token(
            claim.component_code
        )

        identity = (
            code,
            _clean(
                claim.variant_key
            ),
        )

        if identity in seen:
            errors.append(
                f"Duplicate component claim: {code}."
            )

        seen.add(
            identity
        )

        if code not in component_codes:
            errors.append(
                f"Inactive or unknown component: {code}."
            )

        if claim.expectation_state not in REFERENCE_STATES:
            errors.append(
                f"{code}: state must be REQUIRED or NOT_INCLUDED."
            )

        if (
            claim.expectation_state
            == "REQUIRED"
            and claim.expected_quantity <= 0
        ):
            errors.append(
                f"{code}: REQUIRED needs a positive quantity."
            )

        if (
            claim.expectation_state
            == "NOT_INCLUDED"
            and claim.expected_quantity != 0
        ):
            errors.append(
                f"{code}: NOT_INCLUDED needs quantity 0."
            )

        if not (
            Decimal("0.8000")
            <= claim.confidence
            <= Decimal("1.0000")
        ):
            errors.append(
                f"{code}: confidence must be between "
                "0.8000 and 1.0000."
            )

        if len(
            _clean(
                claim.notes
            )
        ) < 20:
            errors.append(
                f"{code}: claim notes must contain at least "
                "20 characters."
            )

    return tuple(
        errors
    )


def _regenerate_manifest(
    packet_dir: Path,
) -> int:
    """Regenerate deterministic packet checksums."""
    summary = _load_summary(
        packet_dir
    )

    (
        catalog,
        pressing_id,
        _,
        _,
    ) = _packet_identity(
        summary
    )

    manifest_path = (
        packet_dir
        / "manifest.json"
    )

    files: dict[str, str] = {}

    for path in sorted(
        packet_dir.rglob("*")
    ):
        if not path.is_file():
            continue

        if path == manifest_path:
            continue

        digest = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        files[
            path.relative_to(
                packet_dir
            ).as_posix()
        ] = digest

    manifest = {
        "schema_version":
            1,
        "algorithm":
            "sha256",
        "catalog":
            catalog,
        "pressing_id":
            pressing_id,
        "workflow_status":
            _clean(
                summary.get(
                    "workflow_status",
                    "UNSPECIFIED",
                )
            ),
        "files":
            files,
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return len(
        files
    )


def stage_reviewed_intake(
    request: IntakeRequest,
    active_source_keys: Iterable[str],
    active_component_codes: Iterable[str],
) -> tuple[int, int, int]:
    """Write reviewed packet rows without writing PostgreSQL."""
    packet_dir = request.packet_dir.resolve()

    errors = validate_request(
        request,
        active_source_keys,
        active_component_codes,
    )

    if errors:
        raise EvidenceIntakeError(
            "Evidence intake is blocked:\n"
            + "\n".join(
                errors
            )
        )

    summary = _load_summary(
        packet_dir
    )

    (
        _,
        pressing_id,
        _,
        _,
    ) = _packet_identity(
        summary
    )

    stage_3_path = (
        packet_dir
        / "stage-03-attachment-review.csv"
    )

    stage_4_path = (
        packet_dir
        / "stage-04-reference-review.csv"
    )

    stage_3_fields, stage_3_rows = _read_csv(
        stage_3_path
    )

    stage_3_required_fields = (
        "apply",
        "entity_type",
        "entity_key",
        "component_code",
        "variant_key",
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
    )

    stage_3_fields = list(
        dict.fromkeys(
            [
                *stage_3_fields,
                *stage_3_required_fields,
            ]
        )
    )

    attachment_rows_added = 0

    existing_attachment_keys = {
        (
            _clean(
                row.get(
                    "entity_key"
                )
            ),
            _clean(
                row.get(
                    "uri"
                )
            ),
            _clean(
                row.get(
                    "sha256"
                )
            ).lower(),
        )
        for row in stage_3_rows
        if _token(
            row.get(
                "apply"
            )
        ) == "TRUE"
    }

    for claim in request.claims:
        entity_key = _canonical_json(
            {
                "pressing_id":
                    pressing_id,
                "component_code":
                    _token(
                        claim.component_code
                    ),
                "variant_key":
                    _clean(
                        claim.variant_key
                    ),
            }
        )

        attachment_identity = (
            entity_key,
            request.uri,
            request.sha256.lower(),
        )

        if attachment_identity in existing_attachment_keys:
            continue

        stage_3_rows.append(
            {
                "apply":
                    "TRUE",
                "entity_type":
                    "PRESSING_COMPONENT_EXPECTATION",
                "entity_key":
                    entity_key,
                "component_code":
                    _token(
                        claim.component_code
                    ),
                "variant_key":
                    _clean(
                        claim.variant_key
                    ),
                "source_key":
                    _token(
                        request.source_key
                    ),
                "attachment_kind":
                    request.attachment_kind,
                "uri":
                    request.uri,
                "sha256":
                    request.sha256.lower(),
                "mime_type":
                    _clean(
                        request.mime_type
                    ),
                "captured_at":
                    _clean(
                        request.captured_at
                    ),
                "page_reference":
                    _clean(
                        request.page_reference
                    ),
                "notes":
                    request.evidence_notes,
                "actor":
                    request.actor,
                "reason":
                    request.reason,
            }
        )

        existing_attachment_keys.add(
            attachment_identity
        )

        attachment_rows_added += 1

    _write_csv(
        stage_3_path,
        stage_3_fields,
        stage_3_rows,
    )

    stage_4_fields, stage_4_rows = _read_csv(
        stage_4_path
    )

    stage_4_required_fields = (
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
        "reason",
    )

    stage_4_fields = list(
        dict.fromkeys(
            [
                *stage_4_fields,
                *stage_4_required_fields,
            ]
        )
    )

    reference_rows_updated = 0

    for claim in request.claims:
        code = _token(
            claim.component_code
        )

        variant_key = _clean(
            claim.variant_key
        )

        matching_rows = [
            row
            for row in stage_4_rows
            if (
                _token(
                    row.get(
                        "component_code"
                    )
                )
                == code
                and _clean(
                    row.get(
                        "variant_key"
                    )
                )
                == variant_key
            )
        ]

        if len(matching_rows) != 1:
            raise EvidenceIntakeError(
                "Expected exactly one stage-four row for "
                f"{code}/{variant_key!r}; found "
                f"{len(matching_rows)}."
            )

        row = matching_rows[0]

        row["action"] = "UPSERT"
        row["expectation_state"] = (
            claim.expectation_state
        )
        row["expected_quantity"] = str(
            claim.expected_quantity
        )
        row["evidence_source"] = _token(
            request.source_key
        )
        row["confidence"] = format(
            claim.confidence,
            ".4f",
        )
        row["variant_label"] = _clean(
            claim.variant_label
        )
        row["notes"] = claim.notes
        row["reason"] = request.reason

        reference_rows_updated += 1

    _write_csv(
        stage_4_path,
        stage_4_fields,
        stage_4_rows,
    )

    summary["workflow_status"] = "REVIEW_READY"
    summary["mutation_status"] = "PENDING_SAFE_REVIEW"
    summary["last_evidence_intake_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )
    summary["last_evidence_intake_actor"] = (
        request.actor
    )
    summary["last_evidence_intake_claims"] = (
        reference_rows_updated
    )
    summary["database_writes"] = 0

    (
        packet_dir
        / "packet-summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest_files = _regenerate_manifest(
        packet_dir
    )

    return (
        attachment_rows_added,
        reference_rows_updated,
        manifest_files,
    )


def run_safe_review(
    packet_dir: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the existing packet reviewer without apply mode."""
    packet_dir = packet_dir.resolve()

    if output_dir is None:
        output_dir = (
            packet_dir
            / "latest-safe-review"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = (
        sys.executable,
        "scripts/review_and_apply_pressing_packet.py",
        "--packet",
        str(packet_dir),
        "--catalog",
        _packet_identity(
            _load_summary(
                packet_dir
            )
        )[0],
        "--output-dir",
        str(output_dir),
    )

    environment = os.environ.copy()

    if not environment.get(
        "PSQL_URL"
    ):
        raise EvidenceIntakeError(
            "PSQL_URL is required for safe review."
        )

    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )

    summary_path = (
        output_dir
        / "packet-review-summary.json"
    )

    if not summary_path.is_file():
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Safe reviewer produced no summary."
        )

        raise EvidenceIntakeError(
            message
        )

    payload = json.loads(
        summary_path.read_text(
            encoding="utf-8"
        )
    )

    if result.returncode not in {
        0,
        2,
    }:
        raise EvidenceIntakeError(
            result.stderr.strip()
            or "Safe review failed."
        )

    return payload


def stage_and_review(
    request: IntakeRequest,
    active_source_keys: Iterable[str],
    active_component_codes: Iterable[str],
    review_output_dir: Path | None = None,
) -> IntakeResult:
    """Stage packet changes and run read-only validation."""
    (
        attachments,
        references,
        manifest_files,
    ) = stage_reviewed_intake(
        request,
        active_source_keys,
        active_component_codes,
    )

    review = run_safe_review(
        request.packet_dir,
        review_output_dir,
    )

    blockers = tuple(
        str(value)
        for value in review.get(
            "blockers",
            [],
        )
    )

    planned = review.get(
        "planned_mutations",
        [],
    )

    return IntakeResult(
        packet_dir=request.packet_dir.resolve(),
        attachment_rows_added=attachments,
        reference_rows_updated=references,
        manifest_files=manifest_files,
        workflow_status=(
            "REVIEW_READY"
            if not blockers
            else "BLOCKED"
        ),
        review_status=_clean(
            review.get(
                "status"
            )
        ),
        blockers=blockers,
        planned_mutation_count=len(
            planned
            if isinstance(
                planned,
                list,
            )
            else []
        ),
        database_writes=0,
    )


def evidence_packet_root() -> Path:
    """Return the configurable packet-discovery root."""
    configured = os.environ.get(
        "EVIDENCE_INTAKE_PACKET_ROOT",
        "logs",
    )

    return Path(
        configured
    ).expanduser()


def latest_packet_for_pressing(
    pressing_id: int,
    root: Path | None = None,
) -> PacketOption | None:
    """Return the newest complete packet for one exact pressing."""
    packet_root = (
        root
        if root is not None
        else evidence_packet_root()
    )

    matches = [
        packet
        for packet in discover_packets(
            packet_root
        )
        if packet.pressing_id
        == int(
            pressing_id
        )
    ]

    if not matches:
        return None

    return matches[0]
