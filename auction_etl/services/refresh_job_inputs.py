from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, text

MAX_EBAY_INPUT_BYTES = 384 * 1024
MAX_REFRESH_REQUEST_BYTES = 512 * 1024
_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ITEM_RE = re.compile(r"^[0-9]{9,15}$")
_URL_ITEM_RE = re.compile(r"/itm/(?:[^/?#]+/)?(?P<item_id>[0-9]{9,15})(?:[/?#]|$)")
_OPTIONAL_FIELDS = (
    "price",
    "shipping",
    "bids",
    "location",
    "seller",
    "seller_feedback",
    "subtitle",
    "ended",
    "image_url",
)


@dataclass(frozen=True, slots=True)
class StructuredEbayJobInput:
    """Validated immutable eBay input owned by one durable refresh job."""

    schema_version: str
    sha256: str
    byte_length: int
    source_name: str
    collector_url: str
    payload: dict[str, Any]


def _optional_string(
    value: Mapping[str, Any],
    key: str,
    *,
    prefix: str = "",
) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{prefix}{key!r} must be a string or null.")
    normalized = raw.strip()
    return normalized or None


def _required_string(
    value: Mapping[str, Any],
    key: str,
    *,
    prefix: str = "",
) -> str:
    result = _optional_string(value, key, prefix=prefix)
    if result is None:
        raise ValueError(f"{prefix}{key!r} must be a nonempty string.")
    return result


def _normalized_listing(record: Mapping[str, Any]) -> tuple[str | None, ...]:
    item_id = _required_string(record, "item_id", prefix="Listing field ")
    if _ITEM_RE.fullmatch(item_id) is None:
        raise ValueError(
            "Listing field 'item_id' must contain 9 to 15 decimal digits."
        )

    url = _required_string(record, "url", prefix="Listing field ")
    parsed = urlsplit(url)
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    if (
        parsed.scheme.casefold() != "https"
        or not (hostname == "ebay.com" or hostname.endswith(".ebay.com"))
    ):
        raise ValueError("Listing field 'url' must be an HTTPS ebay.com URL.")

    match = _URL_ITEM_RE.search(parsed.path)
    if match is None:
        raise ValueError(
            "Listing field 'url' must contain an eBay /itm/<item_id> identity."
        )
    if match.group("item_id") != item_id:
        raise ValueError(
            "Listing field 'url' item identity differs from 'item_id'."
        )

    title = _required_string(record, "title", prefix="Listing field ")
    optional_values = tuple(
        _optional_string(record, field, prefix="Listing field ")
        for field in _OPTIONAL_FIELDS
    )
    return (item_id, url, title, *optional_values)


def validate_structured_ebay_input(value: Any) -> StructuredEbayJobInput:
    """Validate and canonicalize one production structured-eBay input."""

    if not isinstance(value, Mapping):
        raise ValueError("ebay_input must be a JSON object.")

    payload = dict(value)
    source_name = _required_string(payload, "source_name", prefix="ebay_input.")
    if _SOURCE_RE.fullmatch(source_name) is None:
        raise ValueError(
            "ebay_input.source_name must use 1-64 letters, digits, '.', '_' or '-'."
        )

    collector_url = _required_string(
        payload,
        "collector_url",
        prefix="ebay_input.",
    )
    expected_collector_url = f"collector://ebay/{source_name}"
    if collector_url != expected_collector_url:
        raise ValueError(
            "ebay_input.collector_url must exactly match "
            f"{expected_collector_url!r}."
        )

    schema_version = (
        _optional_string(payload, "schema", prefix="ebay_input.")
        or "ebay-structured/v1"
    )
    records = payload.get("listings")
    if not isinstance(records, list) or not records:
        raise ValueError("ebay_input.listings must be a nonempty JSON array.")

    listing_count = payload.get("listing_count")
    if listing_count is not None:
        if isinstance(listing_count, bool) or not isinstance(listing_count, int):
            raise ValueError("ebay_input.listing_count must be an integer.")
        if listing_count != len(records):
            raise ValueError(
                "ebay_input.listing_count does not match the listings array."
            )

    seen: dict[str, tuple[str | None, ...]] = {}
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"ebay_input.listings[{index}] must be an object.")
        normalized = _normalized_listing(raw_record)
        item_id = str(normalized[0])
        prior = seen.get(item_id)
        if prior is None:
            seen[item_id] = normalized
        elif prior != normalized:
            raise ValueError(f"Conflicting duplicate eBay item_id {item_id!r}.")

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(canonical) > MAX_EBAY_INPUT_BYTES:
        raise ValueError("ebay_input exceeds the 384 KiB durable input limit.")

    return StructuredEbayJobInput(
        schema_version=schema_version,
        sha256=hashlib.sha256(canonical).hexdigest(),
        byte_length=len(canonical),
        source_name=source_name,
        collector_url=collector_url,
        payload=payload,
    )


def persist_refresh_job_input(
    connection,
    *,
    job_id: str | uuid.UUID,
    ebay_input: StructuredEbayJobInput,
) -> None:
    """Persist one immutable eBay input inside the job-creation transaction."""

    connection.execute(
        text(
            """
            INSERT INTO ops.refresh_job_input (
                job_id,
                marketplace,
                schema_version,
                sha256,
                byte_length,
                source_name,
                collector_url,
                payload
            )
            VALUES (
                :job_id,
                'ebay',
                :schema_version,
                :sha256,
                :byte_length,
                :source_name,
                :collector_url,
                CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "job_id": uuid.UUID(str(job_id)),
            "schema_version": ebay_input.schema_version,
            "sha256": ebay_input.sha256,
            "byte_length": ebay_input.byte_length,
            "source_name": ebay_input.source_name,
            "collector_url": ebay_input.collector_url,
            "payload": json.dumps(
                ebay_input.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )


def get_refresh_job_input_from_connection(
    connection,
    job_id: str | uuid.UUID,
) -> StructuredEbayJobInput | None:
    """Load the exact eBay input belonging to one refresh job."""

    row = connection.execute(
        text(
            """
            SELECT
                schema_version,
                sha256,
                byte_length,
                source_name,
                collector_url,
                payload
            FROM ops.refresh_job_input
            WHERE job_id = :job_id
              AND marketplace = 'ebay'
            """
        ),
        {"job_id": uuid.UUID(str(job_id))},
    ).mappings().one_or_none()

    if row is None:
        return None

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("Persisted eBay refresh input is not a JSON object.")

    validated = validate_structured_ebay_input(payload)
    if validated.sha256 != str(row["sha256"]):
        raise ValueError("Persisted eBay refresh input SHA-256 does not match.")
    if validated.byte_length != int(row["byte_length"]):
        raise ValueError("Persisted eBay refresh input byte length does not match.")

    return StructuredEbayJobInput(
        schema_version=str(row["schema_version"]),
        sha256=str(row["sha256"]),
        byte_length=int(row["byte_length"]),
        source_name=str(row["source_name"]),
        collector_url=str(row["collector_url"]),
        payload=payload,
    )


def get_refresh_job_input(
    engine: Engine,
    job_id: str | uuid.UUID,
) -> StructuredEbayJobInput | None:
    """Load one refresh-job eBay input using a standalone connection."""

    with engine.connect() as connection:
        return get_refresh_job_input_from_connection(connection, job_id)
