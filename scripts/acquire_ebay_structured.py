#!/usr/bin/env python3
"""Acquire eBay search results as importer-compatible structured JSON.

This module performs acquisition only. It never writes to the application
database, staging tables, or warehouse tables. HTTP access blocks and
authentication redirects fail closed instead of attempting circumvention.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urljoin, urlparse

from auction_etl.browser.defaults import (
    CHANNEL,
    COLOR_SCHEME,
    LOCALE,
    TIMEZONE,
    USER_AGENT,
    VIEWPORT,
)
from auction_etl.parsers.ebay import parse_search


BLOCKED_HTTP_STATUSES = frozenset({401, 403, 429})
ITEM_LINK_SELECTOR = 'a[href*="/itm/"]'
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SETTLE_SECONDS = 2.0

OPTIONAL_LISTING_FIELDS = (
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

ITEM_ID_PATTERN = re.compile(
    r"/itm/(?:[^/?#]+/)?(?P<item_id>[0-9]{9,15})(?:[/?#]|$)"
)

EBAY_HOST_PATTERN = re.compile(
    r"(?:^|\.)ebay\.[a-z.]+$",
    re.IGNORECASE,
)


class EbayAcquisitionError(RuntimeError):
    """Raised when a structured eBay artifact cannot be produced safely."""


class EbayAccessBlockedError(EbayAcquisitionError):
    """Raised when eBay explicitly rejects the acquisition request."""


class EbayAuthenticationRequiredError(EbayAcquisitionError):
    """Raised when the acquisition session is redirected to sign-in."""


@dataclass(frozen=True)
class AcquiredPage:
    """Browser result needed to construct one structured artifact."""

    requested_url: str
    final_url: str
    http_status: int | None
    item_link_count: int
    html: str


def utc_now() -> str:
    """Return current UTC time in stable second precision."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalized_text(value: object) -> str | None:
    """Return normalized text or None for an empty value."""

    if value is None:
        return None

    text = str(value).strip()

    return text or None


def is_ebay_url(value: str) -> bool:
    """Return whether a URL is an HTTPS eBay URL."""

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()

    return (
        parsed.scheme.casefold() == "https"
        and bool(hostname)
        and bool(EBAY_HOST_PATTERN.search(hostname))
    )


def require_ebay_url(value: str) -> str:
    """Validate and return one eBay HTTPS URL."""

    normalized = value.strip()

    if not is_ebay_url(normalized):
        raise EbayAcquisitionError(
            f"Expected an HTTPS eBay URL; received {value!r}."
        )

    return normalized


def is_signin_url(value: str) -> bool:
    """Return whether an eBay URL represents a sign-in endpoint."""

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()

    if not EBAY_HOST_PATTERN.search(hostname):
        return False

    return "signin" in hostname or "/signin" in path


def is_access_block_status(status: int | None) -> bool:
    """Return whether an HTTP status is an explicit access block."""

    return status in BLOCKED_HTTP_STATUSES


def is_ebay_generic_error_page(
    *,
    title: str,
    body: str,
) -> bool:
    """Return whether eBay rendered its generic HTTP-200 error page."""

    normalized_title = " ".join(
        title.split()
    ).casefold()

    normalized_body = " ".join(
        body.split()
    ).casefold()

    if normalized_title == "error page | ebay":
        return True

    return (
        "something went wrong on our end"
        in normalized_body
        and "please go back and try again"
        in normalized_body
    )


def collector_url_for_source(source_name: str) -> str:
    """Return the raw-page URI expected by the external eBay handoff."""

    normalized = source_name.strip()

    if not normalized:
        raise EbayAcquisitionError(
            "Source name must not be empty."
        )

    encoded = quote(
        normalized,
        safe="-_.~",
    )

    return f"collector://ebay/{encoded}"


def item_id_from_url(url: str) -> str | None:
    """Extract a legacy numeric eBay item identifier from an item URL."""

    match = ITEM_ID_PATTERN.search(url)

    if match is None:
        return None

    return match.group("item_id")


def canonical_item_url(value: str) -> str:
    """Return one absolute eBay item URL."""

    absolute = urljoin(
        "https://www.ebay.com/",
        value.strip(),
    )

    if not is_ebay_url(absolute):
        raise EbayAcquisitionError(
            f"Listing URL is not an eBay URL: {value!r}."
        )

    return absolute


def canonical_listing(
    record: Mapping[str, Any],
) -> dict[str, str]:
    """Convert one parser record to the structured importer contract."""

    raw_url = normalized_text(
        record.get("url")
    )

    if raw_url is None:
        raise EbayAcquisitionError(
            "Parsed eBay listing has no URL."
        )

    url = canonical_item_url(
        raw_url
    )

    item_id = normalized_text(
        record.get("item_id")
    )

    if item_id is None:
        item_id = item_id_from_url(
            url
        )

    if item_id is None:
        raise EbayAcquisitionError(
            f"Could not determine item_id for {url}."
        )

    title = normalized_text(
        record.get("title")
    )

    if title is None:
        raise EbayAcquisitionError(
            f"Parsed eBay listing {item_id} has no title."
        )

    result: dict[str, str] = {
        "item_id": item_id,
        "url": url,
        "title": title,
    }

    for field in OPTIONAL_LISTING_FIELDS:
        value = normalized_text(
            record.get(field)
        )

        if value is not None:
            result[field] = value

    return result



def records_for_expected_seller(
    records: Sequence[Mapping[str, Any]],
    expected_seller: str | None,
) -> list[Mapping[str, Any]]:
    """Return records belonging exactly to the configured seller."""

    expected = normalized_text(
        expected_seller
    )

    if expected is None:
        return list(
            records
        )

    expected_key = expected.casefold()

    matches = [
        record
        for record in records
        if (
            normalized_text(
                record.get(
                    "seller"
                )
            )
            or ""
        ).casefold()
        == expected_key
    ]

    if not matches:
        raise EbayAcquisitionError(
            "Acquisition produced zero parser-compatible listings "
            f"for expected seller {expected!r}."
        )

    return matches


def canonical_listings(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Canonicalize, validate, deduplicate, and sort parser records."""

    by_item_id: dict[str, dict[str, str]] = {}

    for record in records:
        listing = canonical_listing(
            record
        )
        item_id = listing["item_id"]

        previous = by_item_id.get(
            item_id
        )

        if previous is None:
            by_item_id[item_id] = listing
            continue

        if previous != listing:
            raise EbayAcquisitionError(
                "Conflicting duplicate eBay item_id "
                f"{item_id} appeared in one acquisition."
            )

    if not by_item_id:
        raise EbayAcquisitionError(
            "Acquisition produced zero parser-compatible eBay listings."
        )

    return [
        by_item_id[item_id]
        for item_id in sorted(
            by_item_id
        )
    ]


def build_payload_from_html(
    *,
    html: str,
    source_name: str,
    requested_url: str,
    final_url: str,
    http_status: int | None,
    item_link_count: int,
    expected_seller: str | None = None,
    collected_at_utc: str | None = None,
) -> dict[str, object]:
    """Parse browser HTML and construct one seller-scoped structured import artifact."""

    if not html.strip():
        raise EbayAcquisitionError(
            "Acquired eBay page HTML is empty."
        )

    parsed_records = parse_search(
        html
    )

    scoped_records = records_for_expected_seller(
        parsed_records,
        expected_seller,
    )

    listings = canonical_listings(
        scoped_records
    )

    result: dict[str, object] = {
        "schema": "auction-etl/ebay-structured-acquisition/v1",
        "source_name": source_name.strip(),
        "source_url": requested_url,
        "collector_url": collector_url_for_source(
            source_name
        ),
        "collected_at_utc": collected_at_utc or utc_now(),
        "page": {
            "final_url": final_url,
            "http_status": http_status,
            "item_link_count": item_link_count,
        },
        "listing_count": len(
            listings
        ),
        "listings": listings,
    }

    seller_filter = normalized_text(
        expected_seller
    )

    if seller_filter is not None:
        result[
            "seller_filter"
        ] = seller_filter

    return result


def atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    """Atomically write a deterministic UTF-8 JSON artifact."""

    output = path.expanduser().resolve()
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )

    temporary = output.with_name(
        f".{output.name}.{os.getpid()}.tmp"
    )

    try:
        with temporary.open(
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                raw
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary,
            output,
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def persistent_profile_context_options(
    *,
    profile_dir: Path,
    headless: bool,
) -> dict[str, object]:
    """Return BrowserManager-equivalent persistent-context options."""

    options: dict[str, object] = {
        "user_data_dir": str(
            profile_dir
        ),
        "headless": headless,
        "viewport": dict(
            VIEWPORT
        ),
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
        "color_scheme": COLOR_SCHEME,
    }

    if USER_AGENT is not None:
        options[
            "user_agent"
        ] = USER_AGENT

    if CHANNEL is not None:
        options[
            "channel"
        ] = CHANNEL

    return options


def acquire_page(
    *,
    url: str,
    profile_dir: Path | None,
    storage_state: Path | None,
    headless: bool,
    timeout_seconds: float,
    settle_seconds: float,
) -> AcquiredPage:
    """Acquire one eBay page through ordinary Playwright navigation."""

    requested_url = require_ebay_url(
        url
    )

    if timeout_seconds <= 0:
        raise EbayAcquisitionError(
            "Timeout must be greater than zero."
        )

    if settle_seconds < 0:
        raise EbayAcquisitionError(
            "Settle time must not be negative."
        )

    resolved_profile: Path | None = None
    resolved_storage: Path | None = None

    if profile_dir is not None:
        resolved_profile = (
            profile_dir
            .expanduser()
            .resolve()
        )

        if not resolved_profile.is_dir():
            raise EbayAcquisitionError(
                "Existing browser profile directory does not exist: "
                f"{resolved_profile}"
            )

    if storage_state is not None:
        resolved_storage = (
            storage_state
            .expanduser()
            .resolve()
        )

        if not resolved_storage.is_file():
            raise EbayAcquisitionError(
                "Storage-state file does not exist: "
                f"{resolved_storage}"
            )

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise EbayAcquisitionError(
            "Playwright is unavailable in this Python environment."
        ) from exc

    timeout_ms = int(
        timeout_seconds * 1000
    )
    settle_ms = int(
        settle_seconds * 1000
    )

    def collect(page: Any) -> AcquiredPage:
        response = page.goto(
            requested_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        http_status = (
            response.status
            if response is not None
            else None
        )

        if is_access_block_status(
            http_status
        ):
            raise EbayAccessBlockedError(
                "eBay rejected the acquisition request "
                f"with HTTP {http_status}."
            )

        if is_signin_url(
            page.url
        ):
            raise EbayAuthenticationRequiredError(
                "eBay redirected the acquisition session to sign-in."
            )

        page_title = page.title()

        try:
            page_body = page.locator(
                "body"
            ).inner_text(
                timeout=min(
                    timeout_ms,
                    5_000,
                )
            )
        except PlaywrightError:
            page_body = ""

        if is_ebay_generic_error_page(
            title=page_title,
            body=page_body,
        ):
            raise EbayAcquisitionError(
                "eBay returned its generic Error Page for the "
                "configured search URL."
            )

        try:
            page.locator(
                ITEM_LINK_SELECTOR
            ).first.wait_for(
                state="attached",
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise EbayAcquisitionError(
                "Timed out waiting for an eBay item link."
            ) from exc

        if settle_ms:
            page.wait_for_timeout(
                settle_ms
            )

        final_url = page.url

        if is_signin_url(
            final_url
        ):
            raise EbayAuthenticationRequiredError(
                "eBay redirected the acquisition session to sign-in."
            )

        item_link_count = page.locator(
            ITEM_LINK_SELECTOR
        ).count()

        html = page.content()

        return AcquiredPage(
            requested_url=requested_url,
            final_url=final_url,
            http_status=http_status,
            item_link_count=item_link_count,
            html=html,
        )

    try:
        with sync_playwright() as playwright:
            if resolved_profile is not None:
                context = (
                    playwright.chromium
                    .launch_persistent_context(
                        **persistent_profile_context_options(
                            profile_dir=resolved_profile,
                            headless=headless,
                        )
                    )
                )

                try:
                    page = (
                        context.pages[0]
                        if context.pages
                        else context.new_page()
                    )

                    return collect(
                        page
                    )
                finally:
                    context.close()

            browser = playwright.chromium.launch(
                headless=headless,
            )

            try:
                context_options: dict[str, object] = {}

                if resolved_storage is not None:
                    context_options["storage_state"] = str(
                        resolved_storage
                    )

                context = browser.new_context(
                    **context_options
                )

                try:
                    page = context.new_page()

                    return collect(
                        page
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except (
        EbayAcquisitionError,
        EbayAccessBlockedError,
        EbayAuthenticationRequiredError,
    ):
        raise
    except PlaywrightError as exc:
        raise EbayAcquisitionError(
            f"Playwright acquisition failed: {exc}"
        ) from exc


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire one eBay search page into structured JSON accepted "
            "by scripts/import_ebay_structured.py. This command performs "
            "no database writes."
        )
    )

    parser.add_argument(
        "--url",
        required=True,
        help="HTTPS eBay search/results URL to acquire.",
    )
    parser.add_argument(
        "--source-name",
        default="facerecords",
        help="Logical eBay source name.",
    )
    parser.add_argument(
        "--expected-seller",
        default=None,
        help=(
            "Fail closed unless parsed listings belong to this "
            "exact eBay seller."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination JSON artifact.",
    )

    authentication = parser.add_mutually_exclusive_group()

    authentication.add_argument(
        "--profile-dir",
        type=Path,
        help=(
            "Existing Playwright persistent browser profile directory. "
            "The command will not create a replacement profile."
        ),
    )
    authentication.add_argument(
        "--storage-state",
        type=Path,
        help="Existing Playwright storage-state JSON file.",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium headlessly.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Navigation/result timeout.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=DEFAULT_SETTLE_SECONDS,
        help="Short wait after the first item link appears.",
    )

    return parser.parse_args()


def main() -> int:
    """Acquire and persist one structured JSON artifact."""

    arguments = parse_arguments()

    source_name = arguments.source_name.strip()

    if not source_name:
        print(
            "ERROR: source name must not be empty.",
            file=sys.stderr,
        )
        return 1

    try:
        acquired = acquire_page(
            url=arguments.url,
            profile_dir=arguments.profile_dir,
            storage_state=arguments.storage_state,
            headless=arguments.headless,
            timeout_seconds=arguments.timeout_seconds,
            settle_seconds=arguments.settle_seconds,
        )

        payload = build_payload_from_html(
            html=acquired.html,
            source_name=source_name,
            requested_url=acquired.requested_url,
            final_url=acquired.final_url,
            http_status=acquired.http_status,
            item_link_count=acquired.item_link_count,
            expected_seller=arguments.expected_seller,
        )

        atomic_write_json(
            arguments.output,
            payload,
        )
    except (
        EbayAcquisitionError,
        OSError,
        ValueError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "EBAY_STRUCTURED_ACQUISITION=FAIL",
            file=sys.stderr,
        )
        return 1

    print(
        f"source_name={payload['source_name']}"
    )
    print(
        f"collector_url={payload['collector_url']}"
    )
    print(
        f"http_status={acquired.http_status}"
    )
    print(
        f"item_links={acquired.item_link_count}"
    )
    print(
        f"listings={payload['listing_count']}"
    )
    print(
        f"output={arguments.output.expanduser().resolve()}"
    )
    print()
    print(
        "DATABASE_REQUEST_EXECUTED=false"
    )
    print(
        "WAREHOUSE_WRITE_EXECUTED=false"
    )
    print(
        "SCROLL_EXECUTED=false"
    )
    print(
        "EBAY_STRUCTURED_ACQUISITION=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
