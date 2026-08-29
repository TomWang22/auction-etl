"""Import structured eBay listings as parser-compatible raw crawl pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from auction_etl.collectors.ebay_compat import (
    EbayListing,
    render_search_page,
)
from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage


DEFAULT_SOURCE_NAME = "external"
COLLECTOR_URL_PREFIX = "collector://ebay/"
SOURCE_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)
ITEM_ID_PATTERN = re.compile(r"^[0-9]{9,15}$")
ITEM_URL_ID_PATTERN = re.compile(
    r"/itm/(?:[^/?#]+/)?(?P<item_id>[0-9]{9,15})(?:[/?#]|$)"
)


class StructuredEbayImportError(ValueError):
    """Raised when structured eBay input cannot be imported safely."""


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    """Validated structured acquisition document."""

    listings: tuple[EbayListing, ...]
    source_name: str | None = None
    collector_url: str | None = None
    schema: str | None = None


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Fully validated parser-compatible import plan."""

    listings: tuple[EbayListing, ...]
    source_url: str
    html: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Result of applying one import plan."""

    job: CrawlJob
    raw_page: RawPage
    created: bool


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate or import structured eBay listing records into "
            "raw.page using the existing parser-compatible HTML contract."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "JSON file containing either a listing array or an object "
            "with a 'listings' array."
        ),
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help=(
            "Logical external collector source name. When omitted, "
            "wrapper metadata is used, then 'external'."
        ),
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help=(
            "Collector URL override. It must exactly match "
            "collector://ebay/<source-name>."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write one idempotent raw.page import. Without --apply, "
            "validation is dry-run only and no database session is opened."
        ),
    )

    return parser.parse_args()


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def optional_string(
    record: Mapping[str, Any],
    key: str,
) -> str | None:
    """Return one optional normalized string field."""

    value = record.get(key)

    if value is None:
        return None

    if not isinstance(value, str):
        raise StructuredEbayImportError(
            f"Field {key!r} must be a string or null."
        )

    stripped = value.strip()

    return stripped or None


def required_string(
    record: Mapping[str, Any],
    key: str,
) -> str:
    """Return one required nonempty string field."""

    value = optional_string(
        record,
        key,
    )

    if value is None:
        raise StructuredEbayImportError(
            f"Field {key!r} must be a nonempty string."
        )

    return value


def validate_item_id(value: str) -> str:
    """Validate one legacy numeric eBay item identifier."""

    if not ITEM_ID_PATTERN.fullmatch(value):
        raise StructuredEbayImportError(
            "Field 'item_id' must contain 9 to 15 decimal digits."
        )

    return value


def validate_item_url(
    value: str,
    *,
    item_id: str,
) -> str:
    """Validate one HTTPS ebay.com item URL and exact item identity."""

    parsed = urlsplit(value)
    hostname = (
        parsed.hostname.lower()
        if parsed.hostname is not None
        else ""
    )

    valid_host = (
        hostname == "ebay.com"
        or hostname.endswith(".ebay.com")
    )

    if (
        parsed.scheme.lower() != "https"
        or not valid_host
    ):
        raise StructuredEbayImportError(
            "Field 'url' must be an HTTPS ebay.com URL."
        )

    match = ITEM_URL_ID_PATTERN.search(
        parsed.path
    )

    if match is None:
        raise StructuredEbayImportError(
            "Field 'url' must contain an eBay /itm/<item_id> identity."
        )

    if match.group("item_id") != item_id:
        raise StructuredEbayImportError(
            "Field 'url' contains an eBay item identifier that "
            "differs from field 'item_id'."
        )

    return value




def listing_from_record(
    record: Mapping[str, Any],
) -> EbayListing:
    """Convert one structured record into the compatibility model."""

    item_id = validate_item_id(
        required_string(
            record,
            "item_id",
        )
    )

    url = validate_item_url(
        required_string(
            record,
            "url",
        ),
        item_id=item_id,
    )

    return EbayListing(
        item_id=item_id,
        url=url,
        title=required_string(
            record,
            "title",
        ),
        price=optional_string(
            record,
            "price",
        ),
        shipping=optional_string(
            record,
            "shipping",
        ),
        bids=optional_string(
            record,
            "bids",
        ),
        location=optional_string(
            record,
            "location",
        ),
        seller=optional_string(
            record,
            "seller",
        ),
        seller_feedback=optional_string(
            record,
            "seller_feedback",
        ),
        subtitle=optional_string(
            record,
            "subtitle",
        ),
        ended=optional_string(
            record,
            "ended",
        ),
        image_url=optional_string(
            record,
            "image_url",
        ),
    )


def extract_listing_records(
    payload: Any,
) -> list[Any]:
    """Extract the listing array from supported JSON payload shapes."""

    if isinstance(payload, list):
        records = payload

    elif isinstance(payload, dict):
        if "listings" not in payload:
            raise StructuredEbayImportError(
                "Top-level JSON object must contain a 'listings' field."
            )

        records = payload["listings"]

    else:
        raise StructuredEbayImportError(
            "Top-level JSON must be a listing array or an object "
            "containing a 'listings' array."
        )

    if not isinstance(records, list):
        raise StructuredEbayImportError(
            "'listings' must be a JSON array."
        )

    if not records:
        raise StructuredEbayImportError(
            "Structured eBay input contains zero listings."
        )

    return records


def optional_metadata_string(
    payload: Mapping[str, Any],
    key: str,
) -> str | None:
    """Validate one optional wrapper metadata string."""

    if key not in payload:
        return None

    value = payload[key]

    if value is None:
        return None

    if not isinstance(value, str):
        raise StructuredEbayImportError(
            f"Top-level field {key!r} must be a string or null."
        )

    normalized = value.strip()

    if not normalized:
        raise StructuredEbayImportError(
            f"Top-level field {key!r} must not be empty."
        )

    return normalized


def read_payload(path: Path) -> Any:
    """Read one structured JSON document."""

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as exc:
        raise StructuredEbayImportError(
            f"Input file does not exist: {path}"
        ) from exc
    except OSError as exc:
        raise StructuredEbayImportError(
            f"Could not read input file {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise StructuredEbayImportError(
            f"Invalid JSON in {path}: {exc}"
        ) from exc


def deduplicate_listings(
    listings: Sequence[EbayListing],
) -> list[EbayListing]:
    """Collapse exact duplicates and reject conflicting item identities."""

    by_item_id: dict[str, EbayListing] = {}
    order: list[str] = []

    for listing in listings:
        previous = by_item_id.get(
            listing.item_id
        )

        if previous is None:
            by_item_id[listing.item_id] = listing
            order.append(listing.item_id)
            continue

        if previous != listing:
            raise StructuredEbayImportError(
                "Conflicting duplicate eBay item_id "
                f"{listing.item_id!r}."
            )

    return [
        by_item_id[item_id]
        for item_id in order
    ]


def load_document(
    path: Path,
) -> StructuredDocument:
    """Load listings and optional acquisition metadata."""

    payload = read_payload(path)
    records = extract_listing_records(
        payload
    )

    listings: list[EbayListing] = []

    for index, value in enumerate(
        records,
        start=1,
    ):
        if not isinstance(value, dict):
            raise StructuredEbayImportError(
                f"Listing {index} must be a JSON object."
            )

        try:
            listing = listing_from_record(
                value
            )
        except StructuredEbayImportError as exc:
            raise StructuredEbayImportError(
                f"Listing {index}: {exc}"
            ) from exc

        listings.append(listing)

    listings = deduplicate_listings(
        listings
    )

    source_name: str | None = None
    collector_url: str | None = None
    schema: str | None = None

    if isinstance(payload, dict):
        source_name = optional_metadata_string(
            payload,
            "source_name",
        )
        collector_url = optional_metadata_string(
            payload,
            "collector_url",
        )
        schema = optional_metadata_string(
            payload,
            "schema",
        )

        if "listing_count" in payload:
            listing_count = payload[
                "listing_count"
            ]

            if (
                isinstance(listing_count, bool)
                or not isinstance(listing_count, int)
            ):
                raise StructuredEbayImportError(
                    "Top-level field 'listing_count' must be an integer."
                )

            if listing_count != len(records):
                raise StructuredEbayImportError(
                    "Top-level field 'listing_count' does not match "
                    "the number of listing records."
                )

    return StructuredDocument(
        listings=tuple(listings),
        source_name=source_name,
        collector_url=collector_url,
        schema=schema,
    )


def load_listings(
    path: Path,
) -> list[EbayListing]:
    """Load and validate structured eBay listings from JSON."""

    return list(
        load_document(path).listings
    )


def normalize_source_name(
    value: str | None,
) -> str:
    """Validate a logical operator collector name."""

    normalized = (
        value.strip()
        if value is not None
        else DEFAULT_SOURCE_NAME
    )

    if not normalized:
        raise StructuredEbayImportError(
            "Source name must not be empty."
        )

    if not SOURCE_NAME_PATTERN.fullmatch(
        normalized
    ):
        raise StructuredEbayImportError(
            "Source name must contain only letters, digits, '.', "
            "'_', or '-', must begin with a letter or digit, "
            "and must be at most 64 characters."
        )

    return normalized


def resolve_source_name(
    cli_value: str | None,
    metadata_value: str | None,
) -> str:
    """Resolve CLI and acquisition metadata provenance."""

    cli_name = (
        normalize_source_name(cli_value)
        if cli_value is not None
        else None
    )

    metadata_name = (
        normalize_source_name(metadata_value)
        if metadata_value is not None
        else None
    )

    if (
        cli_name is not None
        and metadata_name is not None
        and cli_name != metadata_name
    ):
        raise StructuredEbayImportError(
            "CLI source name conflicts with structured-document "
            "source_name metadata."
        )

    return (
        cli_name
        or metadata_name
        or DEFAULT_SOURCE_NAME
    )


def expected_collector_url(
    source_name: str,
) -> str:
    """Return the handoff URL for one logical eBay source."""

    return (
        COLLECTOR_URL_PREFIX
        + normalize_source_name(
            source_name
        )
    )


def validate_collector_url(
    value: str,
) -> str:
    """Validate the raw-page URL required by external handoff."""

    normalized = value.strip()

    if not normalized.startswith(
        COLLECTOR_URL_PREFIX
    ):
        raise StructuredEbayImportError(
            "Source URL must use the collector://ebay/ handoff contract."
        )

    suffix = normalized[
        len(COLLECTOR_URL_PREFIX):
    ]

    normalized_suffix = normalize_source_name(
        suffix
    )

    expected = (
        COLLECTOR_URL_PREFIX
        + normalized_suffix
    )

    if normalized != expected:
        raise StructuredEbayImportError(
            "Source URL is not a canonical collector://ebay/<source> URL."
        )

    return normalized


def resolve_collector_url(
    *,
    source_name: str,
    cli_value: str | None,
    metadata_value: str | None,
) -> str:
    """Resolve one exact external raw-page provenance URL."""

    expected = expected_collector_url(
        source_name
    )

    candidates = [
        value.strip()
        for value in (
            cli_value,
            metadata_value,
        )
        if value is not None
    ]

    for candidate in candidates:
        validated = validate_collector_url(
            candidate
        )

        if validated != expected:
            raise StructuredEbayImportError(
                "Collector URL conflicts with resolved source name: "
                f"expected {expected!r}, received {validated!r}."
            )

    return expected


def build_import_plan(
    *,
    document: StructuredDocument,
    source_url: str,
) -> ImportPlan:
    """Build one deterministic artifact with reconciled provenance."""

    normalized_url = validate_collector_url(
        source_url
    )

    if document.source_name is not None:
        metadata_source_url = expected_collector_url(
            document.source_name
        )

        if normalized_url != metadata_source_url:
            raise StructuredEbayImportError(
                "Direct import source URL conflicts with structured-document "
                "source_name metadata."
            )

    if document.collector_url is not None:
        metadata_collector_url = validate_collector_url(
            document.collector_url
        )

        if normalized_url != metadata_collector_url:
            raise StructuredEbayImportError(
                "Direct import source URL conflicts with structured-document "
                "collector_url metadata."
            )

    if not document.listings:
        raise StructuredEbayImportError(
            "At least one eBay listing is required."
        )

    html = render_search_page(
        document.listings
    )

    return ImportPlan(
        listings=document.listings,
        source_url=normalized_url,
        html=html,
        sha256=sha256_text(html),
    )




def persist_listings(
    *,
    session: Session,
    listings: Sequence[EbayListing],
    source_url: str,
) -> tuple[CrawlJob, RawPage]:
    """Persist one structured eBay import as a normal raw crawl page."""

    normalized_url = validate_collector_url(
        source_url
    )

    if not listings:
        raise StructuredEbayImportError(
            "At least one eBay listing is required."
        )

    html = render_search_page(
        listings
    )

    job = CrawlJob(
        source="manual",
        status="running",
    )

    session.add(job)
    session.flush()

    raw_page = RawPage(
        crawl_job_id=job.id,
        source="ebay",
        url=normalized_url,
        sha256=sha256_text(
            html
        ),
        http_status=200,
        html=html,
        listing_count=len(
            listings
        ),
    )

    session.add(raw_page)
    session.flush()

    job.status = "finished"

    session.commit()

    return job, raw_page


def find_existing_import(
    *,
    session: Session,
    plan: ImportPlan,
) -> tuple[CrawlJob, RawPage] | None:
    """Find an already imported identical external raw page."""

    statement = (
        select(RawPage)
        .where(
            RawPage.source == "ebay",
            RawPage.url == plan.source_url,
            RawPage.sha256 == plan.sha256,
        )
        .order_by(
            RawPage.id.desc()
        )
        .limit(1)
    )

    raw_page = session.scalar(
        statement
    )

    if raw_page is None:
        return None

    job = session.get(
        CrawlJob,
        raw_page.crawl_job_id,
    )

    if job is None:
        raise StructuredEbayImportError(
            "Existing identical raw eBay page references a missing crawl job."
        )

    return job, raw_page


def apply_import_plan(
    *,
    session: Session,
    plan: ImportPlan,
) -> ImportResult:
    """Apply one plan once, reusing an identical prior raw page."""

    existing = find_existing_import(
        session=session,
        plan=plan,
    )

    if existing is not None:
        job, raw_page = existing

        return ImportResult(
            job=job,
            raw_page=raw_page,
            created=False,
        )

    job, raw_page = persist_listings(
        session=session,
        listings=plan.listings,
        source_url=plan.source_url,
    )

    return ImportResult(
        job=job,
        raw_page=raw_page,
        created=True,
    )


def import_structured_ebay(
    *,
    session: Session,
    input_path: Path,
    source_url: str,
) -> tuple[CrawlJob, RawPage]:
    """Import a structured file using the idempotent apply path."""

    document = load_document(
        input_path
    )

    plan = build_import_plan(
        document=document,
        source_url=source_url,
    )

    result = apply_import_plan(
        session=session,
        plan=plan,
    )

    return (
        result.job,
        result.raw_page,
    )


def print_plan(
    *,
    source_name: str,
    document: StructuredDocument,
    plan: ImportPlan,
) -> None:
    """Print a non-secret deterministic import summary."""

    print(
        f"✓ Source         : ebay/{source_name}"
    )
    print(
        f"✓ Listings       : {len(plan.listings)}"
    )
    print(
        f"✓ SHA-256        : {plan.sha256}"
    )
    print(
        f"✓ URL            : {plan.source_url}"
    )

    if document.schema is not None:
        print(
            f"✓ Input schema   : {document.schema}"
        )


def main() -> int:
    """Validate by default or explicitly apply one structured import."""

    arguments = parse_arguments()

    document = load_document(
        arguments.input.expanduser()
    )

    source_name = resolve_source_name(
        arguments.source_name,
        document.source_name,
    )

    source_url = resolve_collector_url(
        source_name=source_name,
        cli_value=arguments.source_url,
        metadata_value=document.collector_url,
    )

    plan = build_import_plan(
        document=document,
        source_url=source_url,
    )

    print_plan(
        source_name=source_name,
        document=document,
        plan=plan,
    )

    if not arguments.apply:
        print()
        print(
            "MODE=DRY_RUN"
        )
        print(
            "DATABASE_SESSION_OPENED=false"
        )
        print(
            "DATABASE_WRITE_EXECUTED=false"
        )
        print(
            "STRUCTURED_EBAY_IMPORT_DRY_RUN=PASS"
        )

        return 0

    with SessionLocal() as session:
        result = apply_import_plan(
            session=session,
            plan=plan,
        )

        job_id = result.job.id
        raw_page_id = result.raw_page.id
        listing_count = (
            result.raw_page.listing_count
        )
        raw_page_sha256 = (
            result.raw_page.sha256
        )
        raw_page_url = result.raw_page.url
        created = result.created

    print()
    print(
        f"✓ Crawl Job      : {job_id}"
    )
    print(
        f"✓ Raw Page       : {raw_page_id}"
    )
    print(
        f"✓ Listings       : {listing_count}"
    )
    print(
        f"✓ SHA-256        : {raw_page_sha256}"
    )
    print(
        f"✓ URL            : {raw_page_url}"
    )
    print(
        "IDEMPOTENT_REUSE="
        + str(
            not created
        ).lower()
    )
    print()
    print(
        "STRUCTURED_EBAY_RAWPAGE_IMPORT=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
