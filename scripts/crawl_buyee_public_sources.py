#!/usr/bin/env python3
"""Acquire public per-artist Buyee completed-auction pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage
from auction_etl.parsers.buyee import parse_search
from auction_etl.services.artist_tracking import build_buyee_search_url
from auction_etl.services.marketplace_browser_runtime import browser


ACCESS_BLOCKED_EXIT = 20
AUTHENTICATION_REDIRECT_EXIT = 21
NO_USABLE_RESULTS_EXIT = 22

BLOCKED_STATUSES = {
    401,
    403,
    429,
}

CHALLENGE_SELECTORS = (
    "iframe[title*='captcha' i]",
    "iframe[src*='captcha' i]",
    "[id*='captcha' i]",
    "[class*='captcha' i]",
)

CHALLENGE_TEXT = (
    "verify you are human",
    "security check",
    "access denied",
    "unusual traffic",
    "captcha",
)


class BuyeePublicError(RuntimeError):
    """Base error for public Buyee acquisition."""


class BuyeeAccessBlockedError(BuyeePublicError):
    """Raised when Buyee presents access control."""


class BuyeeAuthenticationRedirectError(BuyeePublicError):
    """Raised when a public request is redirected to authentication."""


class BuyeeNoResultsError(BuyeePublicError):
    """Raised when a healthy-looking page yields no usable auction records."""


@dataclass(frozen=True)
class Source:
    """One generated artist-search source."""

    name: str
    query: str
    url: str
    profile: str
    max_pages: int
    wait_seconds: float
    min_items: int


@dataclass(frozen=True)
class AcquiredPage:
    """One acquired raw page retained until the complete run succeeds."""

    source_name: str
    requested_url: str
    final_url: str
    status_code: int
    html: str
    listing_ids: tuple[str, ...]


def parse_arguments() -> argparse.Namespace:
    """Parse crawler options."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire public Buyee completed-auction artist searches. "
            "Database writes require explicit --apply."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            os.environ.get(
                "AUCTION_BUYEE_SOURCES_CONFIG",
                "config/buyee_sources.json",
            )
        ),
    )

    parser.add_argument(
        "--query",
        default=None,
        help=(
            "DB-free one-off artist probe. "
            "When supplied, generated config entries are ignored."
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=35.0,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Persist successful pages to raw.page. "
            "Without this flag the crawler is a DB-free probe."
        ),
    )

    arguments = parser.parse_args()

    if arguments.max_pages is not None:
        if arguments.max_pages < 1:
            parser.error(
                "--max-pages must be at least 1."
            )

    if arguments.timeout_seconds <= 0:
        parser.error(
            "--timeout-seconds must be positive."
        )

    return arguments


def positive_integer(
    value: Any,
    *,
    default: int,
) -> int:
    """Return a positive integer."""

    if value is None:
        return default

    result = int(
        value
    )

    if result < 1:
        raise ValueError(
            "Expected a positive integer."
        )

    return result


def nonnegative_float(
    value: Any,
    *,
    default: float,
) -> float:
    """Return a non-negative float."""

    if value is None:
        return default

    result = float(
        value
    )

    if result < 0:
        raise ValueError(
            "Expected a non-negative number."
        )

    return result


def validate_url(
    url: str,
    *,
    require_query: bool = True,
) -> None:
    """Validate a public completed-search URL."""

    parsed = urlsplit(
        url
    )

    hostname = (
        parsed.hostname
        or ""
    ).casefold()

    if (
        parsed.scheme.casefold()
        != "https"
        or not (
            hostname == "buyee.jp"
            or hostname.endswith(
                ".buyee.jp"
            )
        )
    ):
        raise ValueError(
            "Buyee public source must use HTTPS buyee.jp."
        )

    if "/myorders/" in parsed.path.casefold():
        raise ValueError(
            "Public artist acquisition cannot use an authenticated /myorders/ URL."
        )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    if query.get(
        "closed"
    ) != ["1"]:
        raise ValueError(
            "Buyee public source must request closed/completed results."
        )

    if require_query:
        artist_query = (
            query.get(
                "query",
                [""],
            )[0]
            .strip()
        )

        if not artist_query:
            raise ValueError(
                "Buyee public source has no artist query."
            )


def source_from_row(
    row: dict[str, Any],
) -> Source:
    """Validate one runtime source."""

    name = str(
        row.get(
            "name",
            "",
        )
    ).strip()

    query = str(
        row.get(
            "query",
            "",
        )
    ).strip()

    url = str(
        row.get(
            "url",
            "",
        )
    ).strip()

    profile = str(
        row.get(
            "profile",
            "buyee-public",
        )
    ).strip()

    if not name:
        raise ValueError(
            "Buyee source name is empty."
        )

    if not query:
        raise ValueError(
            f"Buyee source {name!r} has no artist query."
        )

    if profile.casefold() != "buyee-public":
        raise ValueError(
            "Public Buyee acquisition must use profile='buyee-public'."
        )

    validate_url(
        url
    )

    return Source(
        name=name,
        query=query,
        url=url,
        profile=profile,
        max_pages=positive_integer(
            row.get(
                "max_pages"
            ),
            default=3,
        ),
        wait_seconds=nonnegative_float(
            row.get(
                "wait_seconds"
            ),
            default=2.0,
        ),
        min_items=positive_integer(
            row.get(
                "min_items"
            ),
            default=1,
        ),
    )


def load_sources(
    path: Path,
) -> list[Source]:
    """Load enabled generated sources."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        payload,
        list,
    ):
        raise ValueError(
            "Buyee runtime config must contain a JSON list."
        )

    return [
        source_from_row(
            row
        )
        for row in payload
        if (
            isinstance(
                row,
                dict,
            )
            and row.get(
                "enabled",
                True,
            )
            is not False
        )
    ]


def one_off_source(
    query: str,
) -> Source:
    """Build one DB-free public probe source."""

    normalized = " ".join(
        query.strip().split()
    )

    if not normalized:
        raise ValueError(
            "--query cannot be empty."
        )

    return Source(
        name="probe",
        query=normalized,
        url=build_buyee_search_url(
            normalized
        ),
        profile="buyee-public",
        max_pages=1,
        wait_seconds=2.0,
        min_items=1,
    )


def page_url(
    base_url: str,
    page_number: int,
) -> str:
    """Return one page of the same artist query."""

    parsed = urlsplit(
        base_url
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    query[
        "page"
    ] = [
        str(
            page_number
        )
    ]

    flattened: list[
        tuple[str, str]
    ] = []

    for key, values in query.items():
        for value in values:
            flattened.append(
                (
                    key,
                    value,
                )
            )

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(
                flattened
            ),
            parsed.fragment,
        )
    )


def authentication_redirect(
    url: str,
) -> bool:
    """Return whether a final URL is authentication-oriented."""

    parsed = urlsplit(
        url
    )

    normalized = (
        parsed.path
        + "?"
        + parsed.query
    ).casefold()

    return any(
        marker in normalized
        for marker in (
            "/login",
            "/signin",
            "/member",
            "login=",
        )
    )


def challenge_visible(
    page,
    body_text: str,
) -> str | None:
    """Return the first observed access-control signal."""

    for selector in CHALLENGE_SELECTORS:
        try:
            if page.locator(
                selector
            ).first.is_visible(
                timeout=500
            ):
                return (
                    "visible access-control element "
                    f"{selector!r}"
                )
        except Exception:
            continue

    normalized = (
        body_text
        .casefold()
    )

    for marker in CHALLENGE_TEXT:
        if marker in normalized:
            return (
                "access-control text "
                f"{marker!r}"
            )

    return None


def acquire_source(
    source: Source,
    *,
    timeout_seconds: float,
    max_pages_override: int | None,
) -> list[AcquiredPage]:
    """Acquire one source without persisting until all pages validate."""

    page_limit = (
        max_pages_override
        if max_pages_override is not None
        else source.max_pages
    )

    context = browser.context(
        source.profile
    )

    page = context.new_page()

    timeout_ms = int(
        timeout_seconds
        * 1000
    )

    page.set_default_timeout(
        timeout_ms
    )

    page.set_default_navigation_timeout(
        timeout_ms
    )

    result: list[
        AcquiredPage
    ] = []

    seen_item_ids: set[
        str
    ] = set()

    try:
        for page_number in range(
            1,
            page_limit + 1,
        ):
            requested_url = page_url(
                source.url,
                page_number,
            )

            try:
                response = page.goto(
                    requested_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
            except PlaywrightTimeoutError as error:
                raise BuyeeAccessBlockedError(
                    "Buyee public navigation timed out."
                ) from error

            if source.wait_seconds:
                page.wait_for_timeout(
                    int(
                        source.wait_seconds
                        * 1000
                    )
                )

            final_url = page.url

            if authentication_redirect(
                final_url
            ):
                raise BuyeeAuthenticationRedirectError(
                    "Buyee public artist search redirected to authentication."
                )

            status_code = (
                response.status
                if response is not None
                else 0
            )

            if status_code in BLOCKED_STATUSES:
                raise BuyeeAccessBlockedError(
                    "Buyee rejected the public worker request "
                    f"with HTTP {status_code}."
                )

            if (
                status_code < 200
                or status_code >= 400
            ):
                raise BuyeePublicError(
                    "Unexpected Buyee HTTP status "
                    f"{status_code}."
                )

            body_text = ""

            try:
                body_text = page.locator(
                    "body"
                ).inner_text(
                    timeout=3000
                )
            except Exception:
                pass

            challenge = challenge_visible(
                page,
                body_text,
            )

            if challenge is not None:
                raise BuyeeAccessBlockedError(
                    "Buyee access-control challenge detected: "
                    + challenge
                )

            html = page.content()

            listings = parse_search(
                html
            )

            page_item_ids = tuple(
                str(
                    listing.get(
                        "item_id",
                        "",
                    )
                ).strip()
                for listing in listings
                if str(
                    listing.get(
                        "item_id",
                        "",
                    )
                ).strip()
            )

            unique_new = [
                item_id
                for item_id in page_item_ids
                if item_id
                not in seen_item_ids
            ]

            if page_number == 1:
                if len(
                    page_item_ids
                ) < source.min_items:
                    raise BuyeeNoResultsError(
                        "Buyee page loaded without enough parseable "
                        f"auction results for {source.query!r}."
                    )
            elif not page_item_ids:
                break

            if not unique_new:
                if page_number == 1:
                    raise BuyeeNoResultsError(
                        "Buyee returned no new auction identities."
                    )

                break

            seen_item_ids.update(
                unique_new
            )

            result.append(
                AcquiredPage(
                    source_name=source.name,
                    requested_url=requested_url,
                    final_url=final_url,
                    status_code=status_code,
                    html=html,
                    listing_ids=page_item_ids,
                )
            )

            print(
                "BUYEE_PUBLIC_PAGE="
                + json.dumps(
                    {
                        "source":
                            source.name,
                        "query":
                            source.query,
                        "page":
                            page_number,
                        "status":
                            status_code,
                        "listings":
                            len(
                                page_item_ids
                            ),
                        "new_unique":
                            len(
                                unique_new
                            ),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ),
                flush=True,
            )

    finally:
        page.close()

    return result


def sha256_text(
    value: str,
) -> str:
    """Return a UTF-8 SHA-256 digest."""

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def persist(
    pages_by_source: list[
        tuple[
            Source,
            list[
                AcquiredPage
            ],
        ]
    ],
) -> list[int]:
    """Persist validated pages in one transaction."""

    raw_page_ids: list[
        int
    ] = []

    with SessionLocal() as session:
        for source, pages in pages_by_source:
            job = CrawlJob(
                source=(
                    "buyee:"
                    + source.name
                ),
                status="running",
            )

            session.add(
                job
            )

            session.flush()

            for acquired in pages:
                raw_page = RawPage(
                    crawl_job_id=job.id,
                    source="buyee",
                    url=acquired.final_url,
                    sha256=sha256_text(
                        acquired.html
                    ),
                    http_status=(
                        acquired.status_code
                    ),
                    html=acquired.html,
                )

                session.add(
                    raw_page
                )

                session.flush()

                raw_page_ids.append(
                    int(
                        raw_page.id
                    )
                )

            job.status = "finished"

        session.commit()

    return raw_page_ids


def main() -> int:
    """Run one fail-closed public Buyee acquisition."""

    arguments = parse_arguments()

    os.environ[
        "AUCTION_MARKETPLACE_BROWSER_MODE"
    ] = "ephemeral"

    for variable in (
        "AUCTION_BUYEE_STORAGE_STATE",
        "AUCTION_BUYEE_STORAGE_STATE_B64",
        "BUYEE_COOKIE",
        "BUYEE_COOKIES",
    ):
        os.environ.pop(
            variable,
            None,
        )

    try:
        if arguments.query is not None:
            sources = [
                one_off_source(
                    arguments.query
                )
            ]
        else:
            sources = load_sources(
                arguments.config
                .expanduser()
                .resolve()
            )

        if not sources:
            print(
                "BUYEE_PUBLIC_SKIPPED=true"
            )
            print(
                "BUYEE_PUBLIC_SOURCES=PASS"
            )
            print(
                "DATABASE_WRITE=false"
            )

            return 0

        acquired: list[
            tuple[
                Source,
                list[
                    AcquiredPage
                ],
            ]
        ] = []

        total_pages = 0
        unique_ids: set[
            str
        ] = set()

        for source in sources:
            pages = acquire_source(
                source,
                timeout_seconds=(
                    arguments.timeout_seconds
                ),
                max_pages_override=(
                    arguments.max_pages
                ),
            )

            acquired.append(
                (
                    source,
                    pages,
                )
            )

            total_pages += len(
                pages
            )

            for acquired_page in pages:
                unique_ids.update(
                    acquired_page.listing_ids
                )

        raw_page_ids: list[
            int
        ] = []

        if arguments.apply:
            if arguments.query is not None:
                raise ValueError(
                    "--query is a DB-free probe and cannot be combined with --apply."
                )

            raw_page_ids = persist(
                acquired
            )

        print()
        print(
            f"BUYEE_PUBLIC_SOURCES={len(sources)}"
        )
        print(
            f"BUYEE_PUBLIC_PAGES={total_pages}"
        )
        print(
            f"BUYEE_PUBLIC_LISTINGS={len(unique_ids)}"
        )
        print(
            "BUYEE_PUBLIC_RAW_PAGE_IDS="
            + ",".join(
                str(
                    value
                )
                for value in raw_page_ids
            )
        )
        print(
            "BUYEE_PUBLIC_MODE="
            + (
                "APPLY"
                if arguments.apply
                else "DRY_RUN"
            )
        )
        print(
            "DATABASE_WRITE="
            + (
                "true"
                if arguments.apply
                else "false"
            )
        )
        print(
            "AUTOMATIC_RETRY=false"
        )
        print(
            "BUYEE_PUBLIC_SOURCES=PASS"
        )

        return 0

    except BuyeeAccessBlockedError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            "BUYEE_PUBLIC_RESULT=ACCESS_BLOCKED",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )

        return ACCESS_BLOCKED_EXIT

    except BuyeeAuthenticationRedirectError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            "BUYEE_PUBLIC_RESULT=AUTHENTICATION_REDIRECT",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )

        return AUTHENTICATION_REDIRECT_EXIT

    except BuyeeNoResultsError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            "BUYEE_PUBLIC_RESULT=NO_USABLE_RESULTS",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )

        return NO_USABLE_RESULTS_EXIT

    except (
        BuyeePublicError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            "BUYEE_PUBLIC_RESULT=FAIL",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )

        return 1

    finally:
        browser.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
