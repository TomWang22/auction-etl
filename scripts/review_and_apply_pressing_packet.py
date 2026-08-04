#!/usr/bin/env python3
"""Review and atomically apply a pressing curation packet.

Review mode never writes PostgreSQL. Apply mode requires reviewed source
attachments, an explicit confirmation token, a verified pg_dump archive,
a serializable transaction, and exact post-commit database assertions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


REFERENCE_FILE = "stage-04-reference-review.csv"
ATTACHMENT_FILE = "stage-03-attachment-review.csv"
SUMMARY_FILE = "packet-summary.json"
MANIFEST_FILE = "manifest.json"

REFERENCE_ACTIONS = {
    "NO_CHANGE",
    "UPSERT",
    "DELETE",
}

EXPECTATION_STATES = {
    "REQUIRED",
    "NOT_INCLUDED",
    "UNKNOWN",
}

ATTACHMENT_KINDS = {
    "URL",
    "IMAGE",
    "PDF",
    "CATALOG_SCAN",
    "LISTING_CAPTURE",
    "PHYSICAL_COPY",
    "ARCHIVE_FILE",
    "OTHER",
}

DEFINITIVE_STATES = {
    "REQUIRED",
    "NOT_INCLUDED",
}

MINIMUM_REFERENCE_CONFIDENCE = Decimal("0.8000")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
TOKEN_PATTERN = re.compile(r"^[A-Z0-9_]+$")

KNOWN_COMPONENT_CODES = {
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
}


COUNT_QUERIES = {
    "warehouse.auction":
        "SELECT COUNT(*) FROM warehouse.auction",
    "warehouse.release_family":
        "SELECT COUNT(*) FROM warehouse.release_family",
    "warehouse.pressing_identity":
        "SELECT COUNT(*) FROM warehouse.pressing_identity",
    "warehouse.auction_pressing_assignment":
        "SELECT COUNT(*) FROM warehouse.auction_pressing_assignment",
    "warehouse.pressing_component_expectation":
        (
            "SELECT COUNT(*) "
            "FROM warehouse.pressing_component_expectation"
        ),
    "warehouse.auction_component_observation":
        (
            "SELECT COUNT(*) "
            "FROM warehouse.auction_component_observation"
        ),
    "warehouse.auction_condition_normalization":
        (
            "SELECT COUNT(*) "
            "FROM warehouse.auction_condition_normalization"
        ),
    "warehouse.auction_behavior_observation":
        (
            "SELECT COUNT(*) "
            "FROM warehouse.auction_behavior_observation"
        ),
    "warehouse.auction_analysis_input":
        "SELECT COUNT(*) FROM warehouse.auction_analysis_input",
    "system.evidence_attachment":
        "SELECT COUNT(*) FROM system.evidence_attachment",
    "system.reference_audit_event":
        "SELECT COUNT(*) FROM system.reference_audit_event",
    "system.normalization_work_batch":
        "SELECT COUNT(*) FROM system.normalization_work_batch",
    "system.normalization_work_audit_event":
        (
            "SELECT COUNT(*) "
            "FROM system.normalization_work_audit_event"
        ),
}


@dataclass(frozen=True)
class ReferenceIdentity:
    """Unique pressing-component reference identity."""

    component_code: str
    variant_key: str


@dataclass(frozen=True)
class ReferenceInput:
    """One reviewed pressing reference action."""

    row_number: int
    action: str
    component_code: str
    variant_key: str
    variant_label: str | None
    expectation_state: str | None
    expected_quantity: int | None
    evidence_source: str | None
    confidence: Decimal | None
    notes: str | None
    reason: str | None

    @property
    def identity(self) -> ReferenceIdentity:
        """Return the exact reference identity."""
        return ReferenceIdentity(
            component_code=self.component_code,
            variant_key=self.variant_key,
        )


@dataclass(frozen=True)
class AttachmentInput:
    """One reviewed evidence attachment action."""

    row_number: int
    apply: bool
    entity_type: str
    entity_key: dict[str, Any]
    source_key: str | None
    attachment_kind: str
    uri: str
    sha256: str
    mime_type: str | None
    captured_at: datetime | None
    page_reference: str | None
    notes: str | None


@dataclass(frozen=True)
class PlannedMutation:
    """One exact database mutation."""

    entity: str
    operation: str
    identity: dict[str, Any]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    row_number: int


@dataclass(frozen=True)
class PacketReview:
    """Complete packet-review result."""

    packet: str
    catalog: str
    pressing_id: int
    confirmation_token: str
    reference_rows: int
    attachment_rows: int
    requested_reference_actions: int
    requested_attachments: int
    planned_mutations: tuple[PlannedMutation, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest_verified_files: int
    status: str


class PacketError(ValueError):
    """Raised when packet structure is invalid."""


def clean_text(value: Any) -> str:
    """Normalize optional worksheet text."""
    if value is None:
        return ""

    return str(value).strip()


def optional_text(value: Any) -> str | None:
    """Normalize optional worksheet text to None."""
    normalized = clean_text(value)

    return normalized or None


def normalize_token(value: Any) -> str:
    """Normalize an uppercase controlled token."""
    return clean_text(value).upper()


def parse_bool(value: Any) -> bool:
    """Parse a worksheet Boolean."""
    normalized = normalize_token(value)

    if normalized in {
        "TRUE",
        "T",
        "YES",
        "Y",
        "1",
    }:
        return True

    if normalized in {
        "",
        "FALSE",
        "F",
        "NO",
        "N",
        "0",
    }:
        return False

    raise PacketError(
        f"Invalid Boolean value: {value!r}"
    )


def parse_decimal(value: Any) -> Decimal | None:
    """Parse an optional finite decimal."""
    normalized = clean_text(value)

    if not normalized:
        return None

    try:
        result = Decimal(normalized)
    except InvalidOperation as error:
        raise PacketError(
            f"Invalid decimal value: {value!r}"
        ) from error

    if not result.is_finite():
        raise PacketError(
            f"Decimal must be finite: {value!r}"
        )

    return result


def parse_integer(value: Any) -> int | None:
    """Parse an optional integer without rounding."""
    normalized = clean_text(value)

    if not normalized:
        return None

    if not re.fullmatch(r"-?\d+", normalized):
        raise PacketError(
            f"Invalid integer value: {value!r}"
        )

    return int(normalized)


def parse_datetime(value: Any) -> datetime | None:
    """Parse an optional ISO-8601 timestamp."""
    normalized = clean_text(value)

    if not normalized:
        return None

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise PacketError(
            "Captured timestamp must be valid ISO 8601: "
            f"{value!r}"
        ) from error


def parse_json_object(value: Any) -> dict[str, Any]:
    """Parse one required JSON object."""
    normalized = clean_text(value)

    if not normalized:
        raise PacketError(
            "entity_key must be a JSON object."
        )

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as error:
        raise PacketError(
            f"Invalid entity_key JSON: {value!r}"
        ) from error

    if not isinstance(payload, dict):
        raise PacketError(
            "entity_key must decode to a JSON object."
        )

    return payload


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return deterministic JSON text."""
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one UTF-8 CSV worksheet."""
    if not path.is_file():
        raise PacketError(
            f"Missing packet worksheet: {path}"
        )

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        if reader.fieldnames is None:
            raise PacketError(
                f"Worksheet has no header: {path}"
            )

        return [
            {
                str(key): (
                    ""
                    if value is None
                    else str(value)
                )
                for key, value in row.items()
            }
            for row in reader
        ]


def require_columns(
    rows: list[dict[str, str]],
    required: Iterable[str],
    path: Path,
) -> None:
    """Require worksheet columns even when no data rows exist."""
    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])

    missing = sorted(
        set(required) - columns
    )

    if missing:
        raise PacketError(
            f"{path.name} is missing columns: "
            + ", ".join(missing)
        )


def load_summary(packet: Path) -> dict[str, Any]:
    """Load the packet summary."""
    path = packet / SUMMARY_FILE

    if not path.is_file():
        raise PacketError(
            f"Missing packet summary: {path}"
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise PacketError(
            "packet-summary.json must contain an object."
        )

    return payload


def summary_catalog(summary: Mapping[str, Any]) -> str:
    """Extract the packet catalog number."""
    for key in (
        "catalog",
        "catalog_number",
    ):
        value = clean_text(
            summary.get(key)
        )

        if value:
            return value

    raise PacketError(
        "Packet summary does not contain a catalog number."
    )


def summary_pressing_id(summary: Mapping[str, Any]) -> int:
    """Extract the packet pressing ID."""
    value = summary.get(
        "pressing_id"
    )

    try:
        pressing_id = int(value)
    except (
        TypeError,
        ValueError,
    ) as error:
        raise PacketError(
            "Packet summary has no valid pressing_id."
        ) from error

    if pressing_id <= 0:
        raise PacketError(
            "Packet pressing_id must be positive."
        )

    return pressing_id


def parse_reference_rows(
    packet: Path,
) -> list[ReferenceInput]:
    """Parse stage-four shared-reference actions."""
    path = packet / REFERENCE_FILE

    required = {
        "action",
        "component_code",
        "variant_key",
        "variant_label",
        "expectation_state",
        "expected_quantity",
        "evidence_source",
        "confidence",
        "notes",
    }

    rows = read_csv_rows(path)
    require_columns(
        rows,
        required,
        path,
    )

    parsed: list[ReferenceInput] = []

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        action = normalize_token(
            row.get("action")
        )

        if not action:
            action = "NO_CHANGE"

        if action not in REFERENCE_ACTIONS:
            raise PacketError(
                f"{path.name} row {row_number}: "
                f"unsupported action {action!r}."
            )

        component_code = normalize_token(
            row.get("component_code")
        )

        if not component_code:
            raise PacketError(
                f"{path.name} row {row_number}: "
                "component_code is required."
            )

        if not TOKEN_PATTERN.fullmatch(
            component_code
        ):
            raise PacketError(
                f"{path.name} row {row_number}: "
                "component_code is invalid."
            )

        parsed.append(
            ReferenceInput(
                row_number=row_number,
                action=action,
                component_code=component_code,
                variant_key=clean_text(
                    row.get("variant_key")
                ),
                variant_label=optional_text(
                    row.get("variant_label")
                ),
                expectation_state=(
                    normalize_token(
                        row.get(
                            "expectation_state"
                        )
                    )
                    or None
                ),
                expected_quantity=parse_integer(
                    row.get(
                        "expected_quantity"
                    )
                ),
                evidence_source=(
                    normalize_token(
                        row.get(
                            "evidence_source"
                        )
                    )
                    or None
                ),
                confidence=parse_decimal(
                    row.get("confidence")
                ),
                notes=optional_text(
                    row.get("notes")
                ),
                reason=optional_text(
                    row.get("reason")
                ),
            )
        )

    return parsed


def attachment_entity_key(
    row: Mapping[str, str],
    pressing_id: int,
) -> dict[str, Any]:
    """Build an attachment entity key from supported worksheet fields."""
    raw_json = clean_text(
        row.get("entity_key")
    )

    if raw_json:
        return parse_json_object(
            raw_json
        )

    key: dict[str, Any] = {
        "pressing_id":
            pressing_id,
    }

    component_code = normalize_token(
        row.get("component_code")
    )

    variant_key = clean_text(
        row.get("variant_key")
    )

    if component_code:
        key["component_code"] = component_code

    if variant_key:
        key["variant_key"] = variant_key

    return key


def parse_attachment_rows(
    packet: Path,
    pressing_id: int,
) -> list[AttachmentInput]:
    """Parse stage-three attachment actions."""
    path = packet / ATTACHMENT_FILE

    required = {
        "apply",
        "source_key",
        "attachment_kind",
        "uri",
        "sha256",
        "mime_type",
        "captured_at",
        "page_reference",
        "notes",
    }

    rows = read_csv_rows(path)
    require_columns(
        rows,
        required,
        path,
    )

    parsed: list[AttachmentInput] = []

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        apply = parse_bool(
            row.get("apply")
        )

        entity_type = (
            normalize_token(
                row.get("entity_type")
            )
            or "PRESSING_IDENTITY"
        )

        attachment_kind = normalize_token(
            row.get("attachment_kind")
        )

        parsed.append(
            AttachmentInput(
                row_number=row_number,
                apply=apply,
                entity_type=entity_type,
                entity_key=attachment_entity_key(
                    row,
                    pressing_id,
                ),
                source_key=(
                    normalize_token(
                        row.get("source_key")
                    )
                    or None
                ),
                attachment_kind=
                    attachment_kind,
                uri=clean_text(
                    row.get("uri")
                ),
                sha256=clean_text(
                    row.get("sha256")
                ).lower(),
                mime_type=optional_text(
                    row.get("mime_type")
                ),
                captured_at=parse_datetime(
                    row.get("captured_at")
                ),
                page_reference=optional_text(
                    row.get(
                        "page_reference"
                    )
                ),
                notes=optional_text(
                    row.get("notes")
                ),
            )
        )

    return parsed


def file_sha256(path: Path) -> str:
    """Calculate one file SHA-256."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def manifest_entries(
    payload: Any,
) -> list[tuple[str, str]]:
    """Extract recognized path/SHA-256 pairs from a manifest."""
    entries: list[tuple[str, str]] = []

    if isinstance(payload, dict):
        files = payload.get("files")

        if isinstance(files, dict):
            for name, value in files.items():
                if isinstance(value, str):
                    entries.append(
                        (
                            str(name),
                            value,
                        )
                    )
                elif isinstance(value, dict):
                    digest = value.get(
                        "sha256"
                    )

                    if isinstance(
                        digest,
                        str,
                    ):
                        entries.append(
                            (
                                str(name),
                                digest,
                            )
                        )

        elif isinstance(files, list):
            for item in files:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                name = (
                    item.get("path")
                    or item.get("name")
                    or item.get("file")
                )

                digest = item.get(
                    "sha256"
                )

                if isinstance(
                    name,
                    str,
                ) and isinstance(
                    digest,
                    str,
                ):
                    entries.append(
                        (
                            name,
                            digest,
                        )
                    )

    return entries


def verify_manifest(
    packet: Path,
) -> tuple[int, list[str], list[str]]:
    """Verify supported manifest digests."""
    path = packet / MANIFEST_FILE

    if not path.is_file():
        return (
            0,
            [],
            [
                "Packet manifest is absent."
            ],
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    entries = manifest_entries(
        payload
    )

    if not entries:
        return (
            0,
            [],
            [
                "Packet manifest contains no recognized SHA-256 entries."
            ],
        )

    blockers: list[str] = []
    verified = 0

    for relative_name, expected in entries:
        candidate = (
            packet
            / relative_name
        ).resolve()

        try:
            candidate.relative_to(
                packet.resolve()
            )
        except ValueError:
            blockers.append(
                "Manifest path escapes packet directory: "
                f"{relative_name}"
            )
            continue

        if not candidate.is_file():
            blockers.append(
                f"Manifest file is missing: {relative_name}"
            )
            continue

        actual = file_sha256(
            candidate
        )

        if actual.lower() != expected.lower():
            blockers.append(
                "Manifest checksum mismatch: "
                f"{relative_name}"
            )
            continue

        verified += 1

    return (
        verified,
        blockers,
        [],
    )


def validate_uri(value: str) -> bool:
    """Validate evidence attachment URI structure."""
    if not value:
        return False

    parsed = urlparse(value)

    return parsed.scheme.lower() in {
        "http",
        "https",
        "file",
        "s3",
        "archive",
    }


def entity_key_pressing_id(
    entity_key: Mapping[str, Any],
) -> int | None:
    """Extract a pressing ID from an attachment entity key."""
    value = entity_key.get(
        "pressing_id"
    )

    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def attachment_supports_reference(
    attachment: AttachmentInput,
    reference: ReferenceInput,
    pressing_id: int,
) -> bool:
    """Return whether an attachment supports a reference claim."""
    if not attachment.apply:
        return False

    if entity_key_pressing_id(
        attachment.entity_key
    ) != pressing_id:
        return False

    component_code = normalize_token(
        attachment.entity_key.get(
            "component_code"
        )
    )

    variant_key = clean_text(
        attachment.entity_key.get(
            "variant_key"
        )
    )

    if (
        component_code
        and component_code
        != reference.component_code
    ):
        return False

    if (
        variant_key
        and variant_key
        != reference.variant_key
    ):
        return False

    return True


def query_scalar(
    connection: Connection[Any],
    statement: str,
    parameters: tuple[Any, ...] = (),
) -> Any:
    """Return one scalar database value."""
    row = connection.execute(
        statement,
        parameters,
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Expected a scalar database result."
        )

    if isinstance(row, Mapping):
        return next(
            iter(row.values())
        )

    return row[0]



def load_active_component_codes(
    connection: Connection[Any],
) -> set[str]:
    """Discover the authoritative active component registry."""
    relation_rows = connection.execute(
        """
        SELECT
            table_schema,
            table_name
        FROM information_schema.columns
        WHERE table_schema NOT IN (
            'pg_catalog',
            'information_schema'
        )
        GROUP BY
            table_schema,
            table_name
        HAVING COUNT(DISTINCT column_name)
            FILTER (
                WHERE column_name IN (
                    'code',
                    'display_name',
                    'applicable_media',
                    'active'
                )
            ) = 4
        ORDER BY
            CASE
                WHEN table_schema = 'warehouse' THEN 0
                WHEN table_schema = 'system' THEN 1
                ELSE 2
            END,
            table_schema,
            table_name
        """
    ).fetchall()

    candidates: list[
        tuple[
            int,
            int,
            int,
            int,
            str,
            str,
            set[str],
        ]
    ] = []

    preferred_names = {
        "component_type",
        "component_types",
        "component_type_registry",
        "collector_component_type",
    }

    for relation in relation_rows:
        schema_name = str(
            relation["table_schema"]
        )

        table_name = str(
            relation["table_name"]
        )

        statement = sql.SQL(
            """
            SELECT code
            FROM {}.{}
            WHERE active
            ORDER BY code
            """
        ).format(
            sql.Identifier(
                schema_name
            ),
            sql.Identifier(
                table_name
            ),
        )

        try:
            code_rows = connection.execute(
                statement
            ).fetchall()
        except psycopg.Error:
            continue

        codes = {
            normalize_token(
                row["code"]
            )
            for row in code_rows
            if normalize_token(
                row["code"]
            )
        }

        if not codes:
            continue

        known_score = len(
            codes
            & KNOWN_COMPONENT_CODES
        )

        if known_score == 0:
            continue

        candidates.append(
            (
                known_score,
                len(codes),
                int(
                    table_name
                    in preferred_names
                ),
                int(
                    schema_name
                    == "warehouse"
                ),
                schema_name,
                table_name,
                codes,
            )
        )

    if not candidates:
        raise PacketError(
            "No active component registry could be discovered "
            "from the live PostgreSQL schema."
        )

    candidates.sort(
        key=lambda candidate: (
            candidate[0],
            candidate[1],
            candidate[2],
            candidate[3],
            candidate[4],
            candidate[5],
        ),
        reverse=True,
    )

    (
        known_score,
        _,
        _,
        _,
        schema_name,
        table_name,
        codes,
    ) = candidates[0]

    if known_score < 3:
        raise PacketError(
            "The discovered component registry is not credible: "
            f"{schema_name}.{table_name} matched only "
            f"{known_score} known component codes."
        )

    return codes

def load_database_contract(
    connection: Connection[Any],
    pressing_id: int,
) -> dict[str, Any]:
    """Load the exact pressing and controlled registries."""
    pressing = connection.execute(
        """
        SELECT
            pressing.id,
            pressing.catalog_number,
            pressing.media_type,
            family.display_artist,
            family.display_title
        FROM warehouse.pressing_identity AS pressing
        JOIN warehouse.release_family AS family
          ON family.id = pressing.release_family_id
        WHERE pressing.id = %s
        """,
        (
            pressing_id,
        ),
    ).fetchone()

    if pressing is None:
        raise PacketError(
            f"Pressing #{pressing_id} does not exist."
        )

    active_component_codes = load_active_component_codes(
        connection
    )

    source_rows = connection.execute(
        """
        SELECT
            source_key,
            active
        FROM system.evidence_source_registry
        ORDER BY source_key
        """
    ).fetchall()

    expectation_rows = connection.execute(
        """
        SELECT
            id,
            pressing_id,
            component_code,
            variant_key,
            variant_label,
            expectation_state,
            expected_quantity,
            evidence_source,
            confidence,
            notes
        FROM warehouse.pressing_component_expectation
        WHERE pressing_id = %s
        ORDER BY
            component_code,
            variant_key
        """,
        (
            pressing_id,
        ),
    ).fetchall()

    return {
        "pressing":
            dict(pressing),
        "active_components":
            active_component_codes,
        "active_sources":
            {
                normalize_token(
                    row["source_key"]
                )
                for row in source_rows
                if bool(row["active"])
            },
        "expectations":
            [
                dict(row)
                for row in expectation_rows
            ],
    }


def normalize_current_reference(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize a persisted expectation for comparison."""
    return {
        "component_code":
            normalize_token(
                row.get(
                    "component_code"
                )
            ),
        "variant_key":
            clean_text(
                row.get(
                    "variant_key"
                )
            ),
        "variant_label":
            optional_text(
                row.get(
                    "variant_label"
                )
            ),
        "expectation_state":
            normalize_token(
                row.get(
                    "expectation_state"
                )
            ),
        "expected_quantity":
            (
                None
                if row.get(
                    "expected_quantity"
                )
                is None
                else int(
                    row[
                        "expected_quantity"
                    ]
                )
            ),
        "evidence_source":
            (
                normalize_token(
                    row.get(
                        "evidence_source"
                    )
                )
                or None
            ),
        "confidence":
            (
                None
                if row.get(
                    "confidence"
                )
                is None
                else Decimal(
                    str(
                        row["confidence"]
                    )
                )
            ),
        "notes":
            optional_text(
                row.get("notes")
            ),
    }


def desired_reference(
    row: ReferenceInput,
) -> dict[str, Any]:
    """Return the desired persisted reference state."""
    return {
        "component_code":
            row.component_code,
        "variant_key":
            row.variant_key,
        "variant_label":
            row.variant_label,
        "expectation_state":
            row.expectation_state,
        "expected_quantity":
            row.expected_quantity,
        "evidence_source":
            row.evidence_source,
        "confidence":
            row.confidence,
        "notes":
            row.notes,
    }


def validate_attachment(
    row: AttachmentInput,
    pressing_id: int,
    active_sources: set[str],
) -> list[str]:
    """Validate one requested attachment."""
    if not row.apply:
        return []

    errors: list[str] = []
    prefix = (
        f"{ATTACHMENT_FILE} row {row.row_number}: "
    )

    if not row.entity_type:
        errors.append(
            prefix
            + "entity_type is required."
        )

    if entity_key_pressing_id(
        row.entity_key
    ) != pressing_id:
        errors.append(
            prefix
            + "entity_key must contain this packet's pressing_id."
        )

    if not row.source_key:
        errors.append(
            prefix
            + "source_key is required."
        )
    elif row.source_key not in active_sources:
        errors.append(
            prefix
            + "source_key is not active in the evidence registry."
        )

    if row.attachment_kind not in ATTACHMENT_KINDS:
        errors.append(
            prefix
            + "attachment_kind is unsupported."
        )

    if not validate_uri(
        row.uri
    ):
        errors.append(
            prefix
            + "uri must use http, https, file, s3, or archive."
        )

    if not SHA256_PATTERN.fullmatch(
        row.sha256
    ):
        errors.append(
            prefix
            + "sha256 must contain exactly 64 hexadecimal characters."
        )

    if not row.notes or len(
        row.notes
    ) < 12:
        errors.append(
            prefix
            + "review notes must contain at least 12 characters."
        )

    return errors


def validate_reference(
    row: ReferenceInput,
    pressing_id: int,
    active_components: set[str],
    active_sources: set[str],
    attachments: list[AttachmentInput],
) -> list[str]:
    """Validate one requested shared-reference mutation."""
    if row.action == "NO_CHANGE":
        return []

    errors: list[str] = []
    prefix = (
        f"{REFERENCE_FILE} row {row.row_number}: "
    )

    if row.component_code not in active_components:
        errors.append(
            prefix
            + "component_code is not active."
        )

    if row.action == "DELETE":
        reason = row.reason or row.notes

        if not reason or len(
            reason
        ) < 12:
            errors.append(
                prefix
                + "DELETE requires a reviewed reason of at least "
                "12 characters."
            )

        return errors

    if row.expectation_state not in EXPECTATION_STATES:
        errors.append(
            prefix
            + "expectation_state must be REQUIRED, "
            "NOT_INCLUDED, or UNKNOWN."
        )

    if row.expectation_state == "REQUIRED":
        if (
            row.expected_quantity
            is None
            or row.expected_quantity <= 0
        ):
            errors.append(
                prefix
                + "REQUIRED needs an explicit positive expected_quantity."
            )

    if row.expectation_state == "NOT_INCLUDED":
        if row.expected_quantity != 0:
            errors.append(
                prefix
                + "NOT_INCLUDED needs expected_quantity=0."
            )

    if row.expectation_state == "UNKNOWN":
        if row.expected_quantity not in {
            None,
            0,
        }:
            errors.append(
                prefix
                + "UNKNOWN cannot claim a positive expected quantity."
            )

    if not row.evidence_source:
        errors.append(
            prefix
            + "evidence_source is required."
        )
    elif row.evidence_source not in active_sources:
        errors.append(
            prefix
            + "evidence_source is not active in the registry."
        )

    if row.confidence is None:
        errors.append(
            prefix
            + "confidence is required."
        )
    elif not (
        Decimal("0")
        <= row.confidence
        <= Decimal("1")
    ):
        errors.append(
            prefix
            + "confidence must be between 0 and 1."
        )

    if not row.notes or len(
        row.notes
    ) < 20:
        errors.append(
            prefix
            + "review notes must contain at least 20 characters."
        )

    if (
        row.expectation_state
        in DEFINITIVE_STATES
    ):
        if (
            row.confidence is not None
            and row.confidence
            < MINIMUM_REFERENCE_CONFIDENCE
        ):
            errors.append(
                prefix
                + "definitive reference claims require confidence "
                f">= {MINIMUM_REFERENCE_CONFIDENCE}."
            )

        supported = any(
            attachment_supports_reference(
                attachment,
                row,
                pressing_id,
            )
            for attachment in attachments
        )

        if not supported:
            errors.append(
                prefix
                + "definitive reference claims require a matching "
                "stage-three attachment marked apply=TRUE."
            )

    return errors


def build_reference_plan(
    rows: list[ReferenceInput],
    current_rows: list[dict[str, Any]],
) -> list[PlannedMutation]:
    """Build exact expectation insert, update, and delete operations."""
    current = {
        ReferenceIdentity(
            component_code=normalize_token(
                row["component_code"]
            ),
            variant_key=clean_text(
                row["variant_key"]
            ),
        ):
            dict(row)
        for row in current_rows
    }

    planned: list[PlannedMutation] = []

    for row in rows:
        if row.action == "NO_CHANGE":
            continue

        existing = current.get(
            row.identity
        )

        identity = {
            "component_code":
                row.component_code,
            "variant_key":
                row.variant_key,
        }

        if row.action == "DELETE":
            if existing is None:
                continue

            planned.append(
                PlannedMutation(
                    entity=
                        "PRESSING_COMPONENT_EXPECTATION",
                    operation=
                        "DELETE",
                    identity=
                        identity,
                    before=
                        normalize_current_reference(
                            existing
                        ),
                    after=
                        None,
                    row_number=
                        row.row_number,
                )
            )

            continue

        desired = desired_reference(
            row
        )

        if existing is None:
            planned.append(
                PlannedMutation(
                    entity=
                        "PRESSING_COMPONENT_EXPECTATION",
                    operation=
                        "INSERT",
                    identity=
                        identity,
                    before=
                        None,
                    after=
                        desired,
                    row_number=
                        row.row_number,
                )
            )

            continue

        normalized_existing = (
            normalize_current_reference(
                existing
            )
        )

        if normalized_existing == desired:
            continue

        planned.append(
            PlannedMutation(
                entity=
                    "PRESSING_COMPONENT_EXPECTATION",
                operation=
                    "UPDATE",
                identity=
                    identity,
                before=
                    normalized_existing,
                after=
                    desired,
                row_number=
                    row.row_number,
            )
        )

    return planned


def existing_attachment(
    connection: Connection[Any],
    row: AttachmentInput,
) -> dict[str, Any] | None:
    """Load an existing active attachment identity."""
    result = connection.execute(
        """
        SELECT
            id,
            entity_type,
            entity_key,
            source_key,
            attachment_kind,
            uri,
            sha256,
            mime_type,
            captured_at,
            page_reference,
            notes,
            active
        FROM system.evidence_attachment
        WHERE entity_type = %s
          AND md5(entity_key::text) = md5(%s::jsonb::text)
          AND sha256 = %s
          AND uri = %s
          AND active
        LIMIT 1
        """,
        (
            row.entity_type,
            canonical_json(
                row.entity_key
            ),
            row.sha256,
            row.uri,
        ),
    ).fetchone()

    if result is None:
        return None

    return dict(result)


def build_attachment_plan(
    connection: Connection[Any],
    rows: list[AttachmentInput],
) -> list[PlannedMutation]:
    """Build exact attachment insert operations."""
    planned: list[PlannedMutation] = []

    for row in rows:
        if not row.apply:
            continue

        if existing_attachment(
            connection,
            row,
        ) is not None:
            continue

        after = {
            "entity_type":
                row.entity_type,
            "entity_key":
                row.entity_key,
            "source_key":
                row.source_key,
            "attachment_kind":
                row.attachment_kind,
            "uri":
                row.uri,
            "sha256":
                row.sha256,
            "mime_type":
                row.mime_type,
            "captured_at":
                (
                    None
                    if row.captured_at is None
                    else row.captured_at.isoformat()
                ),
            "page_reference":
                row.page_reference,
            "notes":
                row.notes,
        }

        planned.append(
            PlannedMutation(
                entity=
                    "EVIDENCE_ATTACHMENT",
                operation=
                    "INSERT",
                identity={
                    "entity_type":
                        row.entity_type,
                    "entity_key":
                        row.entity_key,
                    "sha256":
                        row.sha256,
                    "uri":
                        row.uri,
                },
                before=
                    None,
                after=
                    after,
                row_number=
                    row.row_number,
            )
        )

    return planned


def review_packet(
    packet: Path,
    expected_catalog: str | None,
    connection: Connection[Any],
) -> tuple[
    PacketReview,
    list[ReferenceInput],
    list[AttachmentInput],
]:
    """Review one packet without changing PostgreSQL."""
    summary = load_summary(
        packet
    )

    catalog = summary_catalog(
        summary
    )

    pressing_id = summary_pressing_id(
        summary
    )

    if (
        expected_catalog
        and catalog.casefold()
        != expected_catalog.casefold()
    ):
        raise PacketError(
            "Packet catalog does not match --catalog: "
            f"{catalog!r} != {expected_catalog!r}"
        )

    reference_rows = parse_reference_rows(
        packet
    )

    attachment_rows = parse_attachment_rows(
        packet,
        pressing_id,
    )

    (
        manifest_verified,
        manifest_blockers,
        manifest_warnings,
    ) = verify_manifest(
        packet
    )

    contract = load_database_contract(
        connection,
        pressing_id,
    )

    pressing_catalog = clean_text(
        contract["pressing"][
            "catalog_number"
        ]
    )

    blockers = list(
        manifest_blockers
    )

    warnings = list(
        manifest_warnings
    )

    if (
        pressing_catalog.casefold()
        != catalog.casefold()
    ):
        blockers.append(
            "Packet catalog does not match the live exact pressing: "
            f"{catalog!r} != {pressing_catalog!r}"
        )

    for row in attachment_rows:
        blockers.extend(
            validate_attachment(
                row,
                pressing_id,
                contract[
                    "active_sources"
                ],
            )
        )

    for row in reference_rows:
        blockers.extend(
            validate_reference(
                row,
                pressing_id,
                contract[
                    "active_components"
                ],
                contract[
                    "active_sources"
                ],
                attachment_rows,
            )
        )

    reference_plan = build_reference_plan(
        reference_rows,
        contract["expectations"],
    )

    attachment_plan = build_attachment_plan(
        connection,
        attachment_rows,
    )

    planned = tuple(
        reference_plan
        + attachment_plan
    )

    requested_reference_actions = sum(
        row.action != "NO_CHANGE"
        for row in reference_rows
    )

    requested_attachments = sum(
        row.apply
        for row in attachment_rows
    )

    if blockers:
        status = "BLOCKED"
    elif planned:
        status = "READY"
    else:
        status = "NO_CHANGES"

    return (
        PacketReview(
            packet=str(
                packet
            ),
            catalog=catalog,
            pressing_id=pressing_id,
            confirmation_token=
                f"{catalog}:{pressing_id}",
            reference_rows=
                len(reference_rows),
            attachment_rows=
                len(attachment_rows),
            requested_reference_actions=
                requested_reference_actions,
            requested_attachments=
                requested_attachments,
            planned_mutations=
                planned,
            blockers=
                tuple(blockers),
            warnings=
                tuple(warnings),
            manifest_verified_files=
                manifest_verified,
            status=status,
        ),
        reference_rows,
        attachment_rows,
    )


def serializable_counts(
    connection: Connection[Any],
) -> dict[str, int]:
    """Load protected table counts."""
    return {
        name:
            int(
                query_scalar(
                    connection,
                    query,
                )
            )
        for name, query in COUNT_QUERIES.items()
    }


def write_review_outputs(
    output_dir: Path,
    review: PacketReview,
) -> None:
    """Write the JSON report and evidence-gap worksheet."""
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        **{
            key: value
            for key, value in asdict(
                review
            ).items()
            if key != "planned_mutations"
        },
        "planned_mutations": [
            asdict(mutation)
            for mutation
            in review.planned_mutations
        ],
        "database_writes":
            0,
    }

    (
        output_dir
        / "packet-review-summary.json"
    ).write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    with (
        output_dir
        / "reference-evidence-gaps.tsv"
    ).open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(
            handle,
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writerow(
            (
                "severity",
                "message",
            )
        )

        for blocker in review.blockers:
            writer.writerow(
                (
                    "BLOCKER",
                    blocker,
                )
            )

        for warning in review.warnings:
            writer.writerow(
                (
                    "WARNING",
                    warning,
                )
            )

    (
        output_dir
        / "apply-command.txt"
    ).write_text(
        (
            "python scripts/review_and_apply_pressing_packet.py \\\n"
            f"  --packet {review.packet!r} \\\n"
            f"  --catalog {review.catalog!r} \\\n"
            "  --apply \\\n"
            f"  --confirm {review.confirmation_token!r} \\\n"
            "  --actor 'REVIEWER_NAME' \\\n"
            "  --reason 'Verified pressing completeness reference "
            "against attached source evidence.'\n"
        ),
        encoding="utf-8",
    )


def create_backup(
    database_url: str,
    backup_dir: Path,
    catalog: str,
) -> Path:
    """Create and validate a custom-format PostgreSQL backup."""
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    safe_catalog = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        catalog,
    ).strip("-")

    destination = (
        backup_dir
        / (
            "auction-warehouse-before-"
            f"{safe_catalog}-{timestamp}.dump"
        )
    )

    subprocess.run(
        (
            "pg_dump",
            "--format=custom",
            "--no-password",
            "--file",
            str(destination),
            database_url,
        ),
        check=True,
    )

    result = subprocess.run(
        (
            "pg_restore",
            "--list",
            str(destination),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if not result.stdout.strip():
        raise RuntimeError(
            "pg_restore --list returned no backup contents."
        )

    return destination


def set_audit_context(
    connection: Connection[Any],
    actor: str,
    reason: str,
) -> None:
    """Set transaction-local audit metadata."""
    connection.execute(
        """
        SELECT set_config(
            'auction_etl.actor',
            %s,
            true
        )
        """,
        (
            actor,
        ),
    )

    connection.execute(
        """
        SELECT set_config(
            'auction_etl.reason',
            %s,
            true
        )
        """,
        (
            reason,
        ),
    )


def apply_reference_mutation(
    connection: Connection[Any],
    pressing_id: int,
    mutation: PlannedMutation,
) -> None:
    """Apply one exact expectation mutation."""
    component_code = str(
        mutation.identity[
            "component_code"
        ]
    )

    variant_key = str(
        mutation.identity[
            "variant_key"
        ]
    )

    if mutation.operation == "DELETE":
        connection.execute(
            """
            DELETE
            FROM warehouse.pressing_component_expectation
            WHERE pressing_id = %s
              AND component_code = %s
              AND variant_key = %s
            """,
            (
                pressing_id,
                component_code,
                variant_key,
            ),
        )

        return

    if mutation.after is None:
        raise AssertionError(
            "Reference INSERT/UPDATE has no after state."
        )

    after = mutation.after

    connection.execute(
        """
        INSERT INTO warehouse.pressing_component_expectation (
            pressing_id,
            component_code,
            variant_key,
            variant_label,
            expectation_state,
            expected_quantity,
            evidence_source,
            confidence,
            notes
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            pressing_id,
            component_code,
            variant_key
        )
        DO UPDATE SET
            variant_label =
                EXCLUDED.variant_label,
            expectation_state =
                EXCLUDED.expectation_state,
            expected_quantity =
                EXCLUDED.expected_quantity,
            evidence_source =
                EXCLUDED.evidence_source,
            confidence =
                EXCLUDED.confidence,
            notes =
                EXCLUDED.notes,
            updated_at =
                now()
        """,
        (
            pressing_id,
            component_code,
            variant_key,
            after["variant_label"],
            after["expectation_state"],
            after["expected_quantity"],
            after["evidence_source"],
            after["confidence"],
            after["notes"],
        ),
    )


def find_attachment_row(
    rows: list[AttachmentInput],
    mutation: PlannedMutation,
) -> AttachmentInput:
    """Find the worksheet attachment behind a planned mutation."""
    for row in rows:
        if row.row_number == mutation.row_number:
            return row

    raise AssertionError(
        "Planned attachment row was not found."
    )


def apply_attachment_mutation(
    connection: Connection[Any],
    row: AttachmentInput,
    actor: str,
) -> None:
    """Insert one reviewed evidence attachment."""
    connection.execute(
        """
        INSERT INTO system.evidence_attachment (
            entity_type,
            entity_key,
            source_key,
            attachment_kind,
            uri,
            sha256,
            mime_type,
            captured_at,
            page_reference,
            notes,
            active,
            created_by
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            true,
            %s
        )
        """,
        (
            row.entity_type,
            Jsonb(
                row.entity_key
            ),
            row.source_key,
            row.attachment_kind,
            row.uri,
            row.sha256,
            row.mime_type,
            row.captured_at,
            row.page_reference,
            row.notes,
            actor,
        ),
    )


def expected_count_deltas(
    mutations: Iterable[PlannedMutation],
) -> dict[str, int]:
    """Calculate exact expected table-count deltas."""
    expectation_delta = 0
    attachment_delta = 0
    audit_delta = 0

    for mutation in mutations:
        audit_delta += 1

        if (
            mutation.entity
            == "PRESSING_COMPONENT_EXPECTATION"
        ):
            if mutation.operation == "INSERT":
                expectation_delta += 1
            elif mutation.operation == "DELETE":
                expectation_delta -= 1

        elif (
            mutation.entity
            == "EVIDENCE_ATTACHMENT"
        ):
            if mutation.operation != "INSERT":
                raise AssertionError(
                    "Only attachment INSERT is supported."
                )

            attachment_delta += 1

    return {
        "warehouse.pressing_component_expectation":
            expectation_delta,
        "system.evidence_attachment":
            attachment_delta,
        "system.reference_audit_event":
            audit_delta,
    }


def assert_count_changes(
    before: Mapping[str, int],
    after: Mapping[str, int],
    expected: Mapping[str, int],
) -> None:
    """Require exact post-commit count changes."""
    errors: list[str] = []

    for name in COUNT_QUERIES:
        expected_delta = int(
            expected.get(
                name,
                0,
            )
        )

        actual_delta = (
            int(after[name])
            - int(before[name])
        )

        if actual_delta != expected_delta:
            errors.append(
                f"{name}: expected delta "
                f"{expected_delta}, found {actual_delta}"
            )

    if errors:
        raise RuntimeError(
            "Unexpected database count changes:\n"
            + "\n".join(errors)
        )


def apply_packet(
    packet: Path,
    expected_catalog: str | None,
    database_url: str,
    actor: str,
    reason: str,
    confirmation: str,
    backup_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Apply a validated packet atomically."""
    if len(actor.strip()) < 2:
        raise PacketError(
            "--actor must identify the reviewer."
        )

    if len(reason.strip()) < 20:
        raise PacketError(
            "--reason must contain at least 20 characters."
        )

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION READ ONLY"
            )

            (
                review,
                _,
                _,
            ) = review_packet(
                packet,
                expected_catalog,
                connection,
            )

    write_review_outputs(
        output_dir,
        review,
    )

    if review.status == "BLOCKED":
        raise PacketError(
            "Packet is blocked:\n"
            + "\n".join(
                review.blockers
            )
        )

    if review.status == "NO_CHANGES":
        return {
            "status":
                "NO_CHANGES",
            "catalog":
                review.catalog,
            "pressing_id":
                review.pressing_id,
            "database_writes":
                0,
            "backup":
                None,
        }

    if confirmation != review.confirmation_token:
        raise PacketError(
            "Confirmation token mismatch. Expected: "
            f"{review.confirmation_token}"
        )

    backup = create_backup(
        database_url,
        backup_dir,
        review.catalog,
    )

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as count_connection:
        before_counts = serializable_counts(
            count_connection
        )

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        with connection.transaction():
            connection.execute(
                """
                SET TRANSACTION
                    ISOLATION LEVEL SERIALIZABLE
                """
            )

            set_audit_context(
                connection,
                actor,
                reason,
            )

            connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                    2276,
                    %s
                )
                """,
                (
                    review.pressing_id,
                ),
            )

            (
                fresh_review,
                _,
                fresh_attachments,
            ) = review_packet(
                packet,
                expected_catalog,
                connection,
            )

            if fresh_review.status != "READY":
                raise PacketError(
                    "Packet changed during apply validation: "
                    f"{fresh_review.status}"
                )

            for mutation in fresh_review.planned_mutations:
                if (
                    mutation.entity
                    == "PRESSING_COMPONENT_EXPECTATION"
                ):
                    apply_reference_mutation(
                        connection,
                        fresh_review.pressing_id,
                        mutation,
                    )
                elif (
                    mutation.entity
                    == "EVIDENCE_ATTACHMENT"
                ):
                    attachment = find_attachment_row(
                        fresh_attachments,
                        mutation,
                    )

                    apply_attachment_mutation(
                        connection,
                        attachment,
                        actor,
                    )
                else:
                    raise AssertionError(
                        "Unsupported planned entity: "
                        f"{mutation.entity}"
                    )

            applied_review = fresh_review

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as count_connection:
        after_counts = serializable_counts(
            count_connection
        )

    expected_deltas = expected_count_deltas(
        applied_review.planned_mutations
    )

    assert_count_changes(
        before_counts,
        after_counts,
        expected_deltas,
    )

    result = {
        "status":
            "APPLIED",
        "catalog":
            applied_review.catalog,
        "pressing_id":
            applied_review.pressing_id,
        "mutations":
            [
                asdict(mutation)
                for mutation
                in applied_review.planned_mutations
            ],
        "expected_count_deltas":
            expected_deltas,
        "database_writes":
            len(
                applied_review.planned_mutations
            ),
        "backup":
            str(backup),
    }

    (
        output_dir
        / "packet-apply-result.json"
    ).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    return result


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Review or atomically apply pressing packet stages "
            "3 and 4."
        )
    )

    parser.add_argument(
        "--packet",
        required=True,
        type=Path,
        help="Exported pressing review packet directory.",
    )

    parser.add_argument(
        "--catalog",
        help="Expected exact catalog number.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Review and apply report directory.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply validated mutations after backup.",
    )

    parser.add_argument(
        "--confirm",
        default="",
        help="Required confirmation token, for example MR2276:2.",
    )

    parser.add_argument(
        "--actor",
        default="",
        help="Reviewer identity recorded in audit history.",
    )

    parser.add_argument(
        "--reason",
        default="",
        help="Reviewed reason recorded in audit history.",
    )

    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Destination for the verified pre-apply backup.",
    )

    return parser.parse_args()


def default_output_dir(
    packet: Path,
) -> Path:
    """Create a timestamped report path beside the packet."""
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    return (
        packet
        / f"safe-review-{timestamp}"
    )


def main() -> int:
    """Run review or explicit apply mode."""
    args = parse_args()

    packet = args.packet.expanduser().resolve()

    if not packet.is_dir():
        raise PacketError(
            f"Packet directory does not exist: {packet}"
        )

    database_url = os.environ.get(
        "PSQL_URL"
    )

    if not database_url:
        raise PacketError(
            "PSQL_URL is required."
        )

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else default_output_dir(
            packet
        )
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if args.apply:
        backup_dir = (
            args.backup_dir.expanduser().resolve()
            if args.backup_dir
            else (
                Path("backups")
                / (
                    "pressing-packet-"
                    + datetime.now().strftime(
                        "%Y%m%d-%H%M%S"
                    )
                )
            ).resolve()
        )

        result = apply_packet(
            packet=packet,
            expected_catalog=
                args.catalog,
            database_url=
                database_url,
            actor=
                args.actor,
            reason=
                args.reason,
            confirmation=
                args.confirm,
            backup_dir=
                backup_dir,
            output_dir=
                output_dir,
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        return 0

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION READ ONLY"
            )

            (
                review,
                _,
                _,
            ) = review_packet(
                packet,
                args.catalog,
                connection,
            )

    write_review_outputs(
        output_dir,
        review,
    )

    payload = {
        **{
            key: value
            for key, value in asdict(
                review
            ).items()
            if key != "planned_mutations"
        },
        "planned_mutations": [
            asdict(mutation)
            for mutation
            in review.planned_mutations
        ],
        "output_dir":
            str(output_dir),
        "database_writes":
            0,
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except (
        PacketError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )

        raise SystemExit(2) from error
