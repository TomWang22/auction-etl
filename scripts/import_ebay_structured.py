"""Import structured eBay listings as parser-compatible raw crawl pages."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from auction_etl.collectors.ebay_compat import (
    EbayListing,
    render_search_page,
)
from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage


DEFAULT_SOURCE_NAME = "external"
DEFAULT_SOURCE_URL = "collector://ebay/external"


class StructuredEbayImportError(ValueError):
    """Raised when structured eBay input cannot be imported safely."""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Import structured eBay listing records into raw.page "
            "using the existing parser-compatible HTML contract."
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
        default=DEFAULT_SOURCE_NAME,
        help="Logical external collector source name.",
    )
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="Source URL stored on the raw eBay page.",
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
    """Return one optional field as a stripped string."""
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


def listing_from_record(
    record: Mapping[str, Any],
) -> EbayListing:
    """Convert one structured record into the compatibility model."""
    return EbayListing(
        item_id=required_string(
            record,
            "item_id",
        ),
        url=required_string(
            record,
            "url",
        ),
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
) -> Sequence[Any]:
    """Extract the listing array from supported JSON payload shapes."""
    records: Any

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


def load_listings(
    path: Path,
) -> list[EbayListing]:
    """Load and validate structured eBay listings from JSON."""
    try:
        payload = json.loads(
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

        listings.append(
            listing
        )

    return listings


def persist_listings(
    *,
    session: Session,
    listings: Sequence[EbayListing],
    source_url: str,
) -> tuple[CrawlJob, RawPage]:
    """Persist one structured eBay import as a normal raw crawl page."""
    normalized_url = source_url.strip()

    if not normalized_url:
        raise StructuredEbayImportError(
            "Source URL must not be empty."
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


def import_structured_ebay(
    *,
    session: Session,
    input_path: Path,
    source_url: str,
) -> tuple[CrawlJob, RawPage]:
    """Load structured eBay JSON and persist one raw parser input."""
    listings = load_listings(
        input_path
    )

    return persist_listings(
        session=session,
        listings=listings,
        source_url=source_url,
    )


def main() -> int:
    """Run one structured eBay import."""
    arguments = parse_arguments()

    source_name = arguments.source_name.strip()

    if not source_name:
        raise StructuredEbayImportError(
            "Source name must not be empty."
        )

    with SessionLocal() as session:
        job, raw_page = import_structured_ebay(
            session=session,
            input_path=arguments.input.expanduser(),
            source_url=arguments.source_url,
        )

    print(
        f"✓ Crawl Job      : {job.id}"
    )
    print(
        f"✓ Raw Page       : {raw_page.id}"
    )
    print(
        f"✓ Source         : ebay/{source_name}"
    )
    print(
        f"✓ Listings       : {raw_page.listing_count}"
    )
    print(
        f"✓ SHA-256        : {raw_page.sha256}"
    )
    print(
        f"✓ URL            : {raw_page.url}"
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
