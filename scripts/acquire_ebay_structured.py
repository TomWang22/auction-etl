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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunsplit,
)

from bs4 import BeautifulSoup

from auction_etl.browser.defaults import (
    CHANNEL,
    COLOR_SCHEME,
    LOCALE,
    TIMEZONE,
    USER_AGENT,
    VIEWPORT,
)
from auction_etl.browser.ebay_owner import (
    EbayOwnerError,
    request as ebay_owner_request,
)
from auction_etl.parsers.ebay import parse_search
from auction_etl.runtime_authority import cloud_runtime_detected


BLOCKED_HTTP_STATUSES = frozenset({401, 403, 429})
ITEM_LINK_SELECTOR = 'a[href*="/itm/"]'

ACCESS_CONTROL_SELECTORS = (
    "iframe[src*='captcha' i]",
    "iframe[title*='captcha' i]",
    "[id*='captcha' i]",
    "[class*='captcha' i]",
    "form[action*='captcha' i]",
    "[data-testid*='captcha' i]",
    "iframe[src*='challenge' i]",
    "[id*='challenge' i]",
    "[data-testid*='challenge' i]",
)

ACCESS_CONTROL_TEXT_MARKERS = (
    "access denied",
    "temporarily blocked",
    "verify you are human",
    "please verify yourself",
    "security measure",
    "complete the security check",
    "press and hold",
    "captcha",
    "unusual traffic",
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SETTLE_SECONDS = 2.0
DEFAULT_MAX_PAGES = 2
ABSOLUTE_MAX_PAGES = 25
NEXT_SELECTORS = (
    "a.pagination__next[href]",
    "a[aria-label='Next page'][href]",
    "a[rel='next'][href]",
)

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


@dataclass(frozen=True, slots=True)
class SearchWindow:
    """Deduplicated newest-first structured acquisition window."""

    source_url: str
    listings: tuple[dict[str, str], ...]
    pages: tuple[dict[str, object], ...]
    stop_reason: str
    first_page: AcquiredPage

    @property
    def page_count(self) -> int:
        """Return how many result pages were fetched."""

        return len(self.pages)

    @property
    def unique_identity_count(self) -> int:
        """Return unique eBay item IDs in newest-first window order."""

        return len(self.listings)


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


def is_access_control_url(value: str) -> bool:
    """Return whether an eBay URL is a known access-control endpoint."""

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    path = parsed.path.casefold().rstrip("/")

    if not EBAY_HOST_PATTERN.search(hostname):
        return False

    return path == "/splashui/challenge"


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


def ebay_access_control_text_present(
    *,
    title: str,
    body: str,
) -> bool:
    """Return whether rendered text proves an eBay access-control page."""

    normalized = " ".join(
        (
            title
            + "\n"
            + body
        ).casefold().split()
    )

    return any(
        marker in normalized
        for marker in ACCESS_CONTROL_TEXT_MARKERS
    )


def visible_ebay_access_control_selector(
    page: Any,
) -> str | None:
    """Return the first visible CAPTCHA/challenge selector."""

    for selector in ACCESS_CONTROL_SELECTORS:
        try:
            locator = page.locator(
                selector
            )
            count = min(
                locator.count(),
                8,
            )
        except Exception:
            continue

        for index in range(
            count
        ):
            try:
                if locator.nth(
                    index
                ).is_visible():
                    return selector
            except Exception:
                continue

    return None


def ebay_access_control_reason(
    page: Any,
    *,
    title: str,
    body: str,
) -> str | None:
    """Return deterministic access-control evidence or None."""

    if is_access_control_url(
        str(getattr(page, "url", ""))
    ):
        return "eBay access-control challenge URL"


    selector = visible_ebay_access_control_selector(
        page
    )

    if selector is not None:
        return (
            "visible access-control element "
            f"{selector!r}"
        )

    if ebay_access_control_text_present(
        title=title,
        body=body,
    ):
        return (
            "rendered eBay access-control text"
        )

    return None


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
    """Canonicalize, validate, and deduplicate parser records in first-seen order."""

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

    return list(
        by_item_id.values()
    )


def require_max_pages(
    max_pages: int,
    *,
    configured_max_pages: int,
) -> int:
    """Require a bounded multi-page window with production minimum 2."""

    if configured_max_pages < DEFAULT_MAX_PAGES:
        raise EbayAcquisitionError(
            "Configured max_pages must be at least 2."
        )

    if max_pages < DEFAULT_MAX_PAGES:
        raise EbayAcquisitionError(
            "Acquisition --max-pages must be at least 2."
        )

    if max_pages > configured_max_pages:
        raise EbayAcquisitionError(
            "Acquisition --max-pages may not exceed configured max_pages."
        )

    return max_pages


def require_search_constraints(
    url: str,
) -> None:
    """Require sold+completed newest-first search without _ipg."""

    require_ebay_url(
        url
    )
    query = parse_qs(
        urlsplit(
            url
        ).query
    )

    if "_ipg" in query:
        raise EbayAcquisitionError(
            "eBay acquisition must not set _ipg."
        )

    if query.get("LH_Sold") != ["1"]:
        raise EbayAcquisitionError(
            "eBay acquisition requires LH_Sold=1."
        )

    if query.get("LH_Complete") != ["1"]:
        raise EbayAcquisitionError(
            "eBay acquisition requires LH_Complete=1."
        )

    if query.get("_sop") != ["13"]:
        raise EbayAcquisitionError(
            "eBay acquisition requires newest-first _sop=13."
        )


def search_page_url(
    url: str,
    page_number: int,
) -> str:
    """Return one sold-search URL for a 1-based result page."""

    require_search_constraints(
        url
    )

    if page_number < 1:
        raise EbayAcquisitionError(
            "page_number must be positive."
        )

    if page_number == 1:
        return url

    parts = urlsplit(
        url
    )
    query = [
        (key, value)
        for key, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
        if key != "_pgn"
    ]
    query.append(
        (
            "_pgn",
            str(
                page_number
            ),
        )
    )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(
                query,
                doseq=True,
            ),
            parts.fragment,
        )
    )


def has_next_page(
    html: str,
) -> bool:
    """Return whether the captured result page exposes a usable next link."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for selector in NEXT_SELECTORS:
        link = soup.select_one(
            selector
        )

        if link is None:
            continue

        href = str(
            link.get(
                "href",
                "",
            )
        ).strip()
        disabled = str(
            link.get(
                "aria-disabled",
                "",
            )
        ).strip().casefold()

        if href and disabled != "true":
            return True

    return False


def merge_window_listings(
    destination: dict[str, dict[str, str]],
    listings: Sequence[Mapping[str, str]],
) -> int:
    """Merge one page into the window, keeping first-seen item IDs."""

    added = 0

    for listing in listings:
        item_id = str(
            listing.get(
                "item_id",
                "",
            )
        ).strip()

        if not item_id:
            raise EbayAcquisitionError(
                "Structured listing has no item_id."
            )

        normalized = {
            str(key): str(value)
            for key, value in listing.items()
        }
        previous = destination.get(
            item_id
        )

        if previous is None:
            destination[item_id] = normalized
            added += 1
            continue

        if previous != normalized:
            raise EbayAcquisitionError(
                "Conflicting cross-page eBay identity "
                f"{item_id}."
            )

    return added


def assemble_search_window(
    *,
    source_url: str,
    source_name: str,
    max_pages: int,
    configured_max_pages: int,
    fetch_page: Callable[[str], AcquiredPage],
    expected_seller: str | None = None,
    collected_at_utc: str | None = None,
) -> SearchWindow:
    """Acquire pages 1..N, stop safely, and deduplicate newest-first."""

    max_pages = require_max_pages(
        max_pages,
        configured_max_pages=configured_max_pages,
    )
    require_search_constraints(
        source_url
    )

    merged: dict[str, dict[str, str]] = {}
    pages: list[dict[str, object]] = []
    first_page: AcquiredPage | None = None
    stop_reason = "max_pages"

    for page_number in range(1, max_pages + 1):
        requested_url = search_page_url(
            source_url,
            page_number,
        )
        acquired = fetch_page(
            requested_url
        )

        if first_page is None:
            first_page = acquired

        payload = build_payload_from_html(
            html=acquired.html,
            source_name=source_name,
            requested_url=requested_url,
            final_url=acquired.final_url,
            http_status=acquired.http_status,
            item_link_count=acquired.item_link_count,
            expected_seller=expected_seller,
            collected_at_utc=collected_at_utc,
        )
        listings = payload[
            "listings"
        ]

        if not isinstance(
            listings,
            list,
        ):
            raise EbayAcquisitionError(
                "Structured page listings are malformed."
            )

        added = merge_window_listings(
            merged,
            listings,
        )
        next_available = has_next_page(
            acquired.html
        )
        pages.append(
            {
                "page_number": page_number,
                "requested_url": requested_url,
                "final_url": acquired.final_url,
                "http_status": acquired.http_status,
                "item_link_count": acquired.item_link_count,
                "listing_count": len(
                    listings
                ),
                "new_unique_listings": added,
                "has_next_page": next_available,
            }
        )

        if added == 0:
            stop_reason = "repeated_page"
            break

        if not next_available:
            stop_reason = "no_next_page"
            break
    else:
        stop_reason = "max_pages"

    if first_page is None or not merged:
        raise EbayAcquisitionError(
            "Acquisition produced zero parser-compatible eBay listings."
        )

    return SearchWindow(
        source_url=source_url,
        listings=tuple(
            merged.values()
        ),
        pages=tuple(
            pages
        ),
        stop_reason=stop_reason,
        first_page=first_page,
    )


def build_window_payload(
    window: SearchWindow,
    *,
    source_name: str,
    expected_seller: str | None = None,
    collected_at_utc: str | None = None,
) -> dict[str, object]:
    """Build one importer-compatible artifact for the acquired window."""

    result: dict[str, object] = {
        "schema": "auction-etl/ebay-structured-acquisition/v1",
        "source_name": source_name.strip(),
        "source_url": window.source_url,
        "collector_url": collector_url_for_source(
            source_name
        ),
        "collected_at_utc": collected_at_utc or utc_now(),
        "page": {
            "final_url": window.first_page.final_url,
            "http_status": window.first_page.http_status,
            "item_link_count": window.first_page.item_link_count,
            "page_count": window.page_count,
            "pages": list(
                window.pages
            ),
            "stop_reason": window.stop_reason,
        },
        "listing_count": window.unique_identity_count,
        "listings": list(
            window.listings
        ),
    }

    seller_filter = normalized_text(
        expected_seller
    )

    if seller_filter is not None:
        result[
            "seller_filter"
        ] = seller_filter

    return result


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


def acquire_page_via_owner(
    *,
    url: str,
    owner_socket: Path,
    timeout_seconds: float,
    settle_seconds: float,
    storage_state: Path | None = None,
) -> AcquiredPage:
    """Acquire one eBay page through the local headed owner process."""

    if cloud_runtime_detected():
        raise EbayAcquisitionError(
            "eBay owner acquisition is not allowed on Vercel or Railway."
        )

    payload: dict[str, object] = {
        "url": url,
        "timeout_seconds": timeout_seconds,
        "settle_seconds": settle_seconds,
    }

    if storage_state is not None:
        payload["storage_state"] = str(
            storage_state.expanduser().resolve()
        )

    try:
        response = ebay_owner_request(
            "acquire_structured",
            payload=payload,
            socket_path=owner_socket,
            timeout_seconds=max(
                timeout_seconds + 60.0,
                90.0,
            ),
        )
    except EbayOwnerError as exc:
        raise EbayAcquisitionError(
            f"eBay owner acquisition failed: {exc}"
        ) from exc

    return AcquiredPage(
        requested_url=str(response.get("requested_url") or url),
        final_url=str(response.get("final_url") or url),
        http_status=(
            int(response["http_status"])
            if response.get("http_status") is not None
            else None
        ),
        item_link_count=int(response.get("item_link_count") or 0),
        html=str(response.get("html") or ""),
    )


def acquire_page(
    *,
    url: str,
    profile_dir: Path | None,
    storage_state: Path | None,
    headless: bool,
    timeout_seconds: float,
    settle_seconds: float,
    browser: Any | None = None,
    owner_socket: Path | None = None,
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

    if owner_socket is not None:
        if headless:
            raise EbayAcquisitionError(
                "Owner acquisition must remain headed."
            )

        if profile_dir is not None:
            raise EbayAcquisitionError(
                "Owner acquisition cannot use a persistent profile directory."
            )

        if browser is not None:
            raise EbayAcquisitionError(
                "Owner acquisition cannot also receive a local browser."
            )

        return acquire_page_via_owner(
            url=requested_url,
            owner_socket=owner_socket,
            timeout_seconds=timeout_seconds,
            settle_seconds=settle_seconds,
            storage_state=storage_state,
        )

    existing_browser = browser

    if headless and existing_browser is not None:
        raise EbayAcquisitionError(
            "Reused eBay owner Chromium must remain headed."
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

        access_control_reason = ebay_access_control_reason(
            page,
            title=page_title,
            body=page_body,
        )

        if access_control_reason is not None:
            raise EbayAccessBlockedError(
                "eBay access control challenge detected before "
                "result extraction: "
                + access_control_reason
                + "."
            )

        if is_signin_url(
            page.url
        ):
            raise EbayAuthenticationRequiredError(
                "eBay redirected the acquisition session to sign-in."
            )

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
        final_title = page.title()

        try:
            final_body = page.locator(
                "body"
            ).inner_text(
                timeout=min(
                    timeout_ms,
                    5_000,
                )
            )
        except PlaywrightError:
            final_body = ""

        final_access_control_reason = ebay_access_control_reason(
            page,
            title=final_title,
            body=final_body,
        )

        if final_access_control_reason is not None:
            raise EbayAccessBlockedError(
                "eBay access control challenge detected after "
                "page settlement: "
                + final_access_control_reason
                + "."
            )

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
        if existing_browser is not None:
            if resolved_profile is not None:
                raise EbayAcquisitionError(
                    "Reused eBay Chromium cannot use a persistent profile."
                )

            if resolved_storage is None:
                raise EbayAcquisitionError(
                    "Storage-state is required for reused eBay Chromium."
                )

            context_options: dict[str, object] = {
                "storage_state": str(resolved_storage),
            }
            context = existing_browser.new_context(
                **context_options
            )

            try:
                page = context.new_page()
                return collect(page)
            finally:
                context.close()

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

            launched_browser = playwright.chromium.launch(
                channel="chrome",
                headless=headless,
            )

            try:
                context_options = {}

                if resolved_storage is not None:
                    context_options["storage_state"] = str(
                        resolved_storage
                    )

                context = launched_browser.new_context(
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
                launched_browser.close()
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
        "--owner-socket",
        type=Path,
        default=None,
        help=(
            "Acquire through the local headed eBay owner instead of "
            "launching a new Chromium process."
        ),
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
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=(
            "Bounded newest-first result pages to acquire. "
            "Minimum 2."
        ),
    )
    parser.add_argument(
        "--configured-max-pages",
        type=int,
        default=ABSOLUTE_MAX_PAGES,
        help="Configured upper bound for --max-pages.",
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
        def fetch_page(
            url: str,
        ) -> AcquiredPage:
            """Fetch one headed result page for the search window."""

            return acquire_page(
                url=url,
                profile_dir=arguments.profile_dir,
                storage_state=arguments.storage_state,
                headless=arguments.headless,
                timeout_seconds=arguments.timeout_seconds,
                settle_seconds=arguments.settle_seconds,
                owner_socket=arguments.owner_socket,
            )

        window = assemble_search_window(
            source_url=arguments.url,
            source_name=source_name,
            max_pages=arguments.max_pages,
            configured_max_pages=arguments.configured_max_pages,
            fetch_page=fetch_page,
            expected_seller=arguments.expected_seller,
        )
        payload = build_window_payload(
            window,
            source_name=source_name,
            expected_seller=arguments.expected_seller,
        )
        acquired = window.first_page

        atomic_write_json(
            arguments.output,
            payload,
        )
    except EbayAccessBlockedError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "EBAY_STRUCTURED_ACQUISITION=ACCESS_BLOCKED",
            file=sys.stderr,
        )
        print(
            "EBAY_ACCESS_CONTROL_REQUIRED=true",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )
        return 20
    except EbayAuthenticationRequiredError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "EBAY_STRUCTURED_ACQUISITION=AUTHENTICATION_REQUIRED",
            file=sys.stderr,
        )
        print(
            "EBAY_AUTHENTICATION_REQUIRED=true",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )
        return 21
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
        print(
            "AUTOMATIC_RETRY=false",
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
        f"PAGES_ACQUIRED={window.page_count}"
    )
    print(
        f"UNIQUE_IDENTITY_COUNT={window.unique_identity_count}"
    )
    print(
        f"ACQUISITION_STOP_REASON={window.stop_reason}"
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
