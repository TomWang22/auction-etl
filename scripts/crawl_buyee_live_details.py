#!/usr/bin/env python3
"""Live Buyee detail enrichment for recovered Auction ETL listings."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from sqlalchemy import text

from auction_etl.database.session import engine
from auction_etl.browser.buyee_cdp import open_buyee_context


DEFAULT_EXPECTED_DATABASE_NAME = "auction_warehouse"
DEFAULT_EXPECTED_DATABASE_USER = "auction"
JAPAN_TIMEZONE = ZoneInfo("Asia/Tokyo")
DEFAULT_LOG_DIR = Path("logs/buyee/live-detail")
TAX_RATE = Decimal("0.10")


@dataclass(slots=True)
class BuyeeDetail:
    """Normalized fields extracted from one rendered Buyee page."""

    marketplace: str
    listing_id: str
    auction_url: str
    title: str | None
    seller_name: str | None
    auction_status: str | None
    opening_at: datetime | None
    closing_at: datetime | None
    starting_price: Decimal | None
    current_price_gross: Decimal | None
    buyout_price_gross: Decimal | None
    bid_count: int | None
    condition_text: str | None
    currency: str | None
    tax_included: bool | None
    fetched_at: datetime
    detail_status: str
    error_message: str | None = None


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Render Buyee listing pages and extract live auction details."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write extracted values to PostgreSQL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of listings to process.",
    )
    parser.add_argument(
        "--listing-id",
        action="append",
        default=[],
        help="Process one listing ID. May be repeated.",
    )
    parser.add_argument(
        "--first-seen-source",
        default=None,
        help=(
            "Restrict candidates to one durable ingestion source, "
            "for example new-only-export."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Revisit listings that already have detail data.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while crawling.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "profiles"
            / "anonymous"
        ),
        help="Persistent authenticated Buyee browser profile.",
    )
    parser.add_argument(
        "--authentication-timeout-minutes",
        type=int,
        default=30,
        help="Maximum headed wait for login or two-factor verification.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay between listings in seconds.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Page timeout in seconds.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="HTML, screenshot, and JSON diagnostics directory.",
    )

    arguments = parser.parse_args()

    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be at least 1.")

    if arguments.delay < 0:
        parser.error("--delay cannot be negative.")

    if arguments.timeout < 1:
        parser.error("--timeout must be at least 1.")

    if arguments.authentication_timeout_minutes < 1:
        parser.error(
            "--authentication-timeout-minutes must be at least 1."
        )

    return arguments



def expected_database_identity() -> tuple[str, str]:
    """Return the database identity authorized for write operations."""
    database_name = os.environ.get(
        "AUCTION_EXPECTED_DATABASE_NAME",
        DEFAULT_EXPECTED_DATABASE_NAME,
    ).strip()

    database_user = os.environ.get(
        "AUCTION_EXPECTED_DATABASE_USER",
        DEFAULT_EXPECTED_DATABASE_USER,
    ).strip()

    if not database_name:
        raise RuntimeError(
            "AUCTION_EXPECTED_DATABASE_NAME cannot be empty."
        )

    if not database_user:
        raise RuntimeError(
            "AUCTION_EXPECTED_DATABASE_USER cannot be empty."
        )

    return database_name, database_user


def normalize_space(value: str | None) -> str | None:
    """Collapse whitespace and return None for empty values."""

    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def parse_yen(value: str | None) -> Decimal | None:
    """Parse the first displayed Japanese-yen amount."""

    if not value:
        return None

    patterns = (
        r"([0-9][0-9,]*)\s*YEN",
        r"¥\s*([0-9][0-9,]*)",
        r"JPY\s*([0-9][0-9,]*)",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        )

        if match is not None:
            return Decimal(match.group(1).replace(",", ""))

    return None


def parse_integer(value: str | None) -> int | None:
    """Parse the first integer from text."""

    if not value:
        return None

    match = re.search(r"\d+", value.replace(",", ""))

    if match is None:
        return None

    return int(match.group(0))


def parse_jst_datetime(value: str | None) -> datetime | None:
    """Parse a Buyee JST timestamp and normalize it to UTC."""

    if not value:
        return None

    cleaned = normalize_space(value)

    if cleaned is None:
        return None

    formats = (
        "%d %b %Y %H:%M:%S",
        "%d %B %Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    )

    for date_format in formats:
        try:
            local_value = datetime.strptime(
                cleaned,
                date_format,
            ).replace(tzinfo=JAPAN_TIMEZONE)

            return local_value.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def line_after_label(
    lines: list[str],
    labels: tuple[str, ...],
) -> str | None:
    """Return the first nonempty line after a matching label."""

    normalized_labels = {
        normalize_space(label).casefold()
        for label in labels
        if normalize_space(label)
    }

    for index, line in enumerate(lines):
        normalized_line = normalize_space(line)

        if normalized_line is None:
            continue

        if normalized_line.casefold() not in normalized_labels:
            continue

        for candidate in lines[index + 1 : index + 6]:
            normalized_candidate = normalize_space(candidate)

            if normalized_candidate:
                return normalized_candidate

    return None


def text_block_after_label(
    lines: list[str],
    labels: tuple[str, ...],
    *,
    maximum_lines: int = 4,
) -> str | None:
    """Return a short block after a matching label."""

    normalized_labels = {
        normalize_space(label).casefold()
        for label in labels
        if normalize_space(label)
    }

    for index, line in enumerate(lines):
        normalized_line = normalize_space(line)

        if normalized_line is None:
            continue

        if normalized_line.casefold() not in normalized_labels:
            continue

        collected: list[str] = []

        for candidate in lines[index + 1 :]:
            normalized_candidate = normalize_space(candidate)

            if normalized_candidate is None:
                continue

            if normalized_candidate.casefold() in normalized_labels:
                break

            collected.append(normalized_candidate)

            if len(collected) >= maximum_lines:
                break

        return normalize_space(" ".join(collected))

    return None


def first_heading(page: Page) -> str | None:
    """Return the most likely rendered listing title."""

    selectors = (
        "h1",
        "main h2",
        ".item-name",
        ".product-title",
        "[class*='itemTitle']",
        "[class*='item-title']",
    )

    for selector in selectors:
        locator = page.locator(selector)

        if locator.count() < 1:
            continue

        try:
            value = normalize_space(locator.first.inner_text(timeout=2_000))
        except PlaywrightTimeoutError:
            continue

        if value:
            return value

    return None


def first_link_text(
    page: Page,
    patterns: tuple[str, ...],
) -> str | None:
    """Return text from the first link matching a URL fragment."""

    for pattern in patterns:
        locator = page.locator(f"a[href*='{pattern}']")

        if locator.count() < 1:
            continue

        try:
            value = normalize_space(locator.first.inner_text(timeout=2_000))
        except PlaywrightTimeoutError:
            continue

        if value:
            return value

    return None


def detect_status(body_text: str) -> str | None:
    """Classify the displayed auction status."""
    lowered = body_text.casefold()

    if any(
        marker in lowered
        for marker in (
            "auction has ended",
            "auction ended",
            "this auction is closed",
            "finished",
            "closed auction",
        )
    ):
        return "finished"

    if any(
        marker in lowered
        for marker in (
            "time remaining",
            "current bid",
            "place bid",
        )
    ):
        return "active"

    if (
        "cancelled" in lowered
        or "canceled" in lowered
    ):
        return "cancelled"

    return None



def extract_detail(
    page: Page,
    *,
    listing_id: str,
    auction_url: str,
) -> BuyeeDetail:
    """Extract fields from a rendered Buyee listing page."""

    body_text = page.locator("body").inner_text(timeout=10_000)
    lines = body_text.splitlines()

    title = first_heading(page)

    if not title:
        title = line_after_label(
            lines,
            (
                "Item Name",
                "Title",
            ),
        )

    seller_name = line_after_label(
        lines,
        (
            "Seller",
            "Seller Name",
        ),
    )

    if not seller_name:
        seller_name = first_link_text(
            page,
            (
                "seller",
                "user",
            ),
        )

    opening_text = line_after_label(
        lines,
        (
            "Opening Time (JST)",
            "Opening Time",
            "Start Time (JST)",
            "Start Time",
        ),
    )
    closing_text = line_after_label(
        lines,
        (
            "Closing Time (JST)",
            "Closing Time",
            "End Time (JST)",
            "End Time",
        ),
    )
    starting_text = text_block_after_label(
        lines,
        (
            "Starting Price",
            "Start Price",
        ),
    )
    current_text = text_block_after_label(
        lines,
        (
            "Current Price",
            "Winning Bid",
            "Winning Price",
        ),
    )
    buyout_text = text_block_after_label(
        lines,
        (
            "Buyout Price",
            "Buy It Now Price",
        ),
    )
    bid_text = line_after_label(
        lines,
        (
            "Number of Bids",
            "Bids",
        ),
    )
    condition_text = line_after_label(
        lines,
        (
            "Item Condition",
            "Condition",
        ),
    )

    combined_price_text = " ".join(
        value
        for value in (
            starting_text,
            current_text,
            buyout_text,
        )
        if value
    )

    tax_included: bool | None = None

    if "price including tax" in combined_price_text.casefold():
        tax_included = True
    elif combined_price_text:
        tax_included = False

    status = detect_status(body_text)

    return BuyeeDetail(
        marketplace="buyee",
        listing_id=listing_id,
        auction_url=auction_url,
        title=title,
        seller_name=seller_name,
        auction_status=status,
        opening_at=parse_jst_datetime(opening_text),
        closing_at=parse_jst_datetime(closing_text),
        starting_price=parse_yen(starting_text),
        current_price_gross=parse_yen(current_text),
        buyout_price_gross=parse_yen(buyout_text),
        bid_count=parse_integer(bid_text),
        condition_text=condition_text,
        currency=(
            "JPY"
            if "YEN" in body_text.upper()
            or "¥" in body_text
            else None
        ),
        tax_included=tax_included,
        fetched_at=datetime.now(timezone.utc),
        detail_status="complete",
    )


def ensure_schema() -> None:
    """Create non-destructive detail storage and missing auction columns."""

    statements = (
        """
        CREATE TABLE IF NOT EXISTS warehouse.auction_detail (
            id bigserial PRIMARY KEY,
            marketplace varchar NOT NULL,
            listing_id varchar NOT NULL,
            auction_url text,
            title text,
            seller_name text,
            auction_status varchar,
            opening_at timestamptz,
            closing_at timestamptz,
            starting_price numeric,
            current_price_gross numeric,
            buyout_price_gross numeric,
            bid_count integer,
            condition_text text,
            currency varchar,
            tax_included boolean,
            detail_status varchar NOT NULL DEFAULT 'pending',
            error_message text,
            fetched_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_auction_detail_marketplace_listing
        ON warehouse.auction_detail (
            marketplace,
            listing_id
        )
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS opening_at timestamptz
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS closing_at timestamptz
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS current_price_gross numeric
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS buyout_price_gross numeric
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS detail_status varchar
        """,
        """
        ALTER TABLE warehouse.auction
        ADD COLUMN IF NOT EXISTS detail_fetched_at timestamptz
        """,
    )

    expected_database_name, expected_database_user = (
        expected_database_identity()
    )

    with engine.begin() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        database_user = connection.execute(
            text("SELECT current_user")
        ).scalar_one()

        if database_name != expected_database_name:
            raise RuntimeError(
                "Refusing to modify unexpected database: "
                f"{database_name}; expected {expected_database_name}."
            )

        if database_user != expected_database_user:
            raise RuntimeError(
                "Refusing to modify database as unexpected user: "
                f"{database_user}; expected {expected_database_user}."
            )

        for statement in statements:
            connection.execute(text(statement))


def load_candidates(
    *,
    listing_ids: tuple[str, ...],
    first_seen_source: str | None,
    refresh: bool,
    limit: int | None,
) -> list[dict[str, str]]:
    """Load Buyee listings that need authenticated detail enrichment."""
    conditions = [
        "a.marketplace = 'buyee'",
        "a.auction_url IS NOT NULL",
        "BTRIM(a.auction_url) <> ''",
    ]
    parameters: dict[str, Any] = {}

    if listing_ids:
        conditions.append(
            "a.listing_id = ANY(:listing_ids)"
        )
        parameters["listing_ids"] = list(
            listing_ids
        )

    if first_seen_source:
        conditions.append(
            "audit.first_seen_source = :first_seen_source"
        )
        parameters[
            "first_seen_source"
        ] = first_seen_source

    if not refresh:
        conditions.append(
            """
            (
                d.listing_id IS NULL
                OR d.detail_status <> 'complete'
                OR d.opening_at IS NULL
                OR d.closing_at IS NULL
                OR d.starting_price IS NULL
            )
            """
        )

    limit_clause = ""

    if limit is not None:
        limit_clause = "LIMIT :limit"
        parameters["limit"] = limit

    statement = text(
        f"""
        SELECT
            a.listing_id,
            a.auction_url
        FROM warehouse.auction AS a
        LEFT JOIN warehouse.auction_detail AS d
          ON d.marketplace = a.marketplace
         AND d.listing_id = a.listing_id
        LEFT JOIN system.auction_ingestion_identity AS audit
          ON audit.marketplace = a.marketplace
         AND audit.listing_id = a.listing_id
        WHERE {" AND ".join(conditions)}
        ORDER BY
            COALESCE(
                audit.first_seen_at,
                a.created_at
            ) DESC,
            a.id DESC
        {limit_clause}
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            parameters,
        ).mappings().all()

    return [
        {
            "listing_id": str(
                row["listing_id"]
            ),
            "auction_url": str(
                row["auction_url"]
            ),
        }
        for row in rows
    ]



def pre_tax_price(
    gross_price: Decimal | None,
    *,
    tax_included: bool | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Derive a Japanese pre-tax hammer and tax amount."""

    if gross_price is None:
        return None, None

    if tax_included is not True:
        return gross_price, Decimal("0")

    base_price = (
        gross_price / (Decimal("1") + TAX_RATE)
    ).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )

    tax_amount = gross_price - base_price
    return base_price, tax_amount


def save_detail(detail: BuyeeDetail) -> None:
    """Upsert one detail row and enrich its warehouse auction row."""

    final_price: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_price: Decimal | None = None

    if (
        detail.auction_status == "finished"
        and detail.current_price_gross is not None
    ):
        final_price, tax_amount = pre_tax_price(
            detail.current_price_gross,
            tax_included=detail.tax_included,
        )
        gross_price = detail.current_price_gross

    parameters = asdict(detail)
    parameters.update(
        {
            "final_price": final_price,
            "tax_amount": tax_amount,
            "gross_price": gross_price,
            "tax_rate": TAX_RATE,
        }
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_detail (
                    marketplace,
                    listing_id,
                    auction_url,
                    title,
                    seller_name,
                    auction_status,
                    opening_at,
                    closing_at,
                    starting_price,
                    current_price_gross,
                    buyout_price_gross,
                    bid_count,
                    condition_text,
                    currency,
                    tax_included,
                    detail_status,
                    error_message,
                    fetched_at,
                    updated_at
                )
                VALUES (
                    :marketplace,
                    :listing_id,
                    :auction_url,
                    :title,
                    :seller_name,
                    :auction_status,
                    :opening_at,
                    :closing_at,
                    :starting_price,
                    :current_price_gross,
                    :buyout_price_gross,
                    :bid_count,
                    :condition_text,
                    :currency,
                    :tax_included,
                    :detail_status,
                    :error_message,
                    :fetched_at,
                    now()
                )
                ON CONFLICT (
                    marketplace,
                    listing_id
                )
                DO UPDATE SET
                    auction_url = EXCLUDED.auction_url,
                    title = EXCLUDED.title,
                    seller_name = EXCLUDED.seller_name,
                    auction_status = EXCLUDED.auction_status,
                    opening_at = EXCLUDED.opening_at,
                    closing_at = EXCLUDED.closing_at,
                    starting_price = EXCLUDED.starting_price,
                    current_price_gross =
                        EXCLUDED.current_price_gross,
                    buyout_price_gross =
                        EXCLUDED.buyout_price_gross,
                    bid_count = EXCLUDED.bid_count,
                    condition_text = EXCLUDED.condition_text,
                    currency = EXCLUDED.currency,
                    tax_included = EXCLUDED.tax_included,
                    detail_status = EXCLUDED.detail_status,
                    error_message = EXCLUDED.error_message,
                    fetched_at = EXCLUDED.fetched_at,
                    updated_at = now()
                """
            ),
            parameters,
        )

        connection.execute(
            text(
                """
                UPDATE warehouse.auction
                SET
                    title = COALESCE(
                        :title,
                        title
                    ),
                    seller = COALESCE(
                        :seller_name,
                        seller
                    ),
                    opening_at = COALESCE(
                        :opening_at,
                        opening_at
                    ),
                    closing_at = COALESCE(
                        :closing_at,
                        closing_at
                    ),
                    ended_at = CASE
                        WHEN :auction_status = 'finished'
                        THEN COALESCE(
                            :closing_at,
                            ended_at
                        )
                        ELSE ended_at
                    END,
                    start_price = COALESCE(
                        :starting_price,
                        start_price
                    ),
                    current_price_gross = COALESCE(
                        :current_price_gross,
                        current_price_gross
                    ),
                    buyout_price_gross = COALESCE(
                        :buyout_price_gross,
                        buyout_price_gross
                    ),
                    bid_count = COALESCE(
                        :bid_count,
                        bid_count
                    ),
                    condition_media = COALESCE(
                        condition_media,
                        :condition_text
                    ),
                    final_price = COALESCE(
                        :final_price,
                        final_price
                    ),
                    tax_rate = CASE
                        WHEN :currency = 'JPY'
                        THEN :tax_rate
                        ELSE tax_rate
                    END,
                    tax_amount = COALESCE(
                        :tax_amount,
                        tax_amount
                    ),
                    gross_price = COALESCE(
                        :gross_price,
                        gross_price
                    ),
                    currency = COALESCE(
                        :currency,
                        currency
                    ),
                    price_includes_tax = COALESCE(
                        :tax_included,
                        price_includes_tax
                    ),
                    detail_status = :detail_status,
                    detail_fetched_at = :fetched_at
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            parameters,
        )


def save_failure(
    *,
    listing_id: str,
    auction_url: str,
    error_message: str,
) -> None:
    """Store a failed detail attempt without changing auction prices."""

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_detail (
                    marketplace,
                    listing_id,
                    auction_url,
                    detail_status,
                    error_message,
                    fetched_at,
                    updated_at
                )
                VALUES (
                    'buyee',
                    :listing_id,
                    :auction_url,
                    'error',
                    :error_message,
                    now(),
                    now()
                )
                ON CONFLICT (
                    marketplace,
                    listing_id
                )
                DO UPDATE SET
                    auction_url = EXCLUDED.auction_url,
                    detail_status = 'error',
                    error_message = EXCLUDED.error_message,
                    fetched_at = now(),
                    updated_at = now()
                """
            ),
            {
                "listing_id": listing_id,
                "auction_url": auction_url,
                "error_message": error_message[:4_000],
            },
        )


def serialize_detail(detail: BuyeeDetail) -> dict[str, Any]:
    """Convert a detail result into JSON-safe values."""

    payload = asdict(detail)

    for key, value in tuple(payload.items()):
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif isinstance(value, Decimal):
            payload[key] = str(value)

    return payload


def create_context(
    browser: Browser,
) -> BrowserContext:
    """Create an isolated browser context."""

    return browser.new_context(
        locale="en-US",
        timezone_id="Asia/Tokyo",
        viewport={
            "width": 1600,
            "height": 1200,
        },
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
    )


def crawl_candidate(
    *,
    page: Page,
    listing_id: str,
    auction_url: str,
    log_dir: Path,
    timeout_seconds: int,
) -> BuyeeDetail:
    """Render and extract one authenticated Buyee detail page."""
    response = page.goto(
        auction_url,
        wait_until="domcontentloaded",
        timeout=timeout_seconds * 1_000,
    )

    if response is not None and response.status >= 400:
        raise RuntimeError(
            f"HTTP {response.status} for {auction_url}"
        )

    if any(
        marker in page.url.casefold()
        for marker in (
            "/signup/login",
            "/signup/twofactor",
        )
    ):
        raise RuntimeError(
            "Buyee authentication expired during detail crawl."
        )

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=min(
                timeout_seconds * 1_000,
                15_000,
            ),
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(2_000)

    item_dir = log_dir / listing_id
    item_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (item_dir / "page.html").write_text(
        page.content(),
        encoding="utf-8",
    )

    page.screenshot(
        path=str(item_dir / "page.png"),
        full_page=True,
    )

    detail = extract_detail(
        page,
        listing_id=listing_id,
        auction_url=auction_url,
    )

    telemetry = (
        detail.opening_at,
        detail.closing_at,
        detail.starting_price,
        detail.current_price_gross,
        detail.bid_count,
    )

    if all(
        value is None
        for value in telemetry
    ):
        raise RuntimeError(
            "The rendered detail page yielded no auction telemetry."
        )

    if (
        detail.opening_at is None
        or detail.closing_at is None
        or detail.starting_price is None
    ):
        detail.detail_status = "partial"

    (item_dir / "detail.json").write_text(
        json.dumps(
            serialize_detail(detail),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return detail



def print_result(
    index: int,
    total: int,
    detail: BuyeeDetail,
) -> None:
    """Print one concise crawl result."""

    print()
    print(
        f"[{index}/{total}] "
        f"{detail.listing_id} · "
        f"{detail.detail_status}"
    )
    print(f"Title       : {detail.title or '—'}")
    print(f"Status      : {detail.auction_status or '—'}")
    print(f"Opening UTC : {detail.opening_at or '—'}")
    print(f"Closing UTC : {detail.closing_at or '—'}")
    print(f"Starting JPY: {detail.starting_price or '—'}")
    print(
        "Current gross: "
        f"{detail.current_price_gross or '—'}"
    )
    print(
        "Buyout gross : "
        f"{detail.buyout_price_gross or '—'}"
    )
    print(f"Bids        : {detail.bid_count}")
    print(f"Condition   : {detail.condition_text or '—'}")


WATCHLIST_URL = (
    "https://buyee.jp/"
    "myorders/watchlist/closed"
)


def authentication_required(
    url: str,
) -> bool:
    """Return whether Buyee is showing login or two-factor verification."""
    lowered = url.casefold()

    return any(
        marker in lowered
        for marker in (
            "/signup/login",
            "/signup/twofactor",
        )
    )


def wait_for_authenticated_profile(
    context: BrowserContext,
    *,
    headed: bool,
    timeout_seconds: float,
    navigation_timeout_seconds: float,
) -> Page:
    """Require the persistent profile to reach the closed watchlist.

    Headed callers may use a long timeout to allow interactive login.
    Unattended callers should pass their normal bounded page timeout.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")

    if navigation_timeout_seconds <= 0:
        raise ValueError(
            "navigation_timeout_seconds must be positive."
        )

    deadline = time.monotonic() + timeout_seconds
    last_message = 0.0

    def remaining_seconds() -> float:
        return max(
            0.0,
            deadline - time.monotonic(),
        )

    def remaining_timeout_ms() -> int:
        remaining = remaining_seconds()

        if remaining <= 0:
            return 1

        bounded = min(
            remaining,
            navigation_timeout_seconds,
        )

        return max(
            1,
            int(bounded * 1_000),
        )

    def goto_watchlist(page: Page) -> None:
        if remaining_seconds() <= 0:
            return

        try:
            page.goto(
                WATCHLIST_URL,
                wait_until="domcontentloaded",
                timeout=remaining_timeout_ms(),
            )
        except PlaywrightTimeoutError:
            pass

    page = (
        context.pages[-1]
        if context.pages
        else context.new_page()
    )

    goto_watchlist(page)

    while remaining_seconds() > 0:
        page = (
            context.pages[-1]
            if context.pages
            else context.new_page()
        )

        if authentication_required(page.url):
            if not headed:
                raise RuntimeError(
                    "Buyee authentication is required. "
                    "Run again with --headed."
                )

            now = time.monotonic()

            if now - last_message >= 10:
                remaining = max(
                    0,
                    int(deadline - now),
                )

                print(
                    "Waiting for Buyee login or two-factor "
                    f"verification ({remaining}s remaining)..."
                )

                last_message = now

            page.wait_for_timeout(
                min(
                    1_000,
                    max(
                        1,
                        int(
                            remaining_seconds()
                            * 1_000
                        ),
                    ),
                )
            )
            continue

        if "/myorders/watchlist/closed" not in page.url:
            goto_watchlist(page)

            if remaining_seconds() <= 0:
                break

            page.wait_for_timeout(
                min(
                    1_000,
                    max(
                        1,
                        int(
                            remaining_seconds()
                            * 1_000
                        ),
                    ),
                )
            )
            continue

        link_count = page.locator(
            'a[href*="/item/jdirectitems/auction/"]'
        ).count()

        if link_count > 0:
            print(
                "✓ Authenticated Buyee profile verified: "
                f"{link_count} visible auction links."
            )

            return page

        page.wait_for_timeout(
            min(
                1_000,
                max(
                    1,
                    int(
                        remaining_seconds()
                        * 1_000
                    ),
                ),
            )
        )

    raise RuntimeError(
        "Timed out waiting for authenticated Buyee access."
    )

def main() -> int:
    """Run the authenticated live Buyee detail crawler."""
    arguments = parse_arguments()
    arguments.log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    profile_dir = (
        arguments.profile_dir
        .expanduser()
        .resolve()
    )

    if not profile_dir.is_dir():
        raise RuntimeError(
            f"Buyee profile is missing: {profile_dir}"
        )

    if arguments.apply:
        ensure_schema()

    candidates = load_candidates(
        listing_ids=tuple(
            arguments.listing_id
        ),
        first_seen_source=(
            arguments.first_seen_source
        ),
        refresh=arguments.refresh,
        limit=arguments.limit,
    )

    print()
    print("Live Buyee detail crawl")
    print("=======================")
    print(f"Candidates : {len(candidates)}")
    print(f"Apply      : {arguments.apply}")
    print(f"Refresh    : {arguments.refresh}")
    print(f"Profile    : {profile_dir}")
    print(f"Diagnostics: {arguments.log_dir}")

    if not candidates:
        print()
        print(
            "No matching Buyee listings require enrichment."
        )
        return 0

    results: list[dict[str, Any]] = []
    failures = 0

    with sync_playwright() as playwright:
        context, owns_context, _cdp_browser = open_buyee_context(
            playwright,
            profile_dir=profile_dir,
            headless=not arguments.headed,
            launch_options={
                "locale": "en-US",
                "timezone_id": "Asia/Tokyo",
                "viewport": {
                    "width": 1600,
                    "height": 1200,
                },
                "user_agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
            },
        )

        try:
            page = wait_for_authenticated_profile(
                context,
                headed=arguments.headed,
                timeout_seconds=(
                    arguments.authentication_timeout_minutes * 60
                    if arguments.headed
                    else arguments.timeout
                ),
                navigation_timeout_seconds=arguments.timeout,
            )
            page.set_default_timeout(
                arguments.timeout * 1_000
            )

            for index, candidate in enumerate(
                candidates,
                start=1,
            ):
                listing_id = candidate[
                    "listing_id"
                ]
                auction_url = candidate[
                    "auction_url"
                ]

                try:
                    detail = crawl_candidate(
                        page=page,
                        listing_id=listing_id,
                        auction_url=auction_url,
                        log_dir=arguments.log_dir,
                        timeout_seconds=(
                            arguments.timeout
                        ),
                    )
                    print_result(
                        index,
                        len(candidates),
                        detail,
                    )
                    results.append(
                        serialize_detail(detail)
                    )

                    if arguments.apply:
                        save_detail(detail)
                except Exception as error:
                    failures += 1
                    message = (
                        f"{type(error).__name__}: {error}"
                    )

                    print()
                    print(
                        f"[{index}/{len(candidates)}] "
                        f"{listing_id} · ERROR"
                    )
                    print(message)

                    results.append(
                        {
                            "marketplace": "buyee",
                            "listing_id": listing_id,
                            "auction_url": auction_url,
                            "detail_status": "error",
                            "error_message": message,
                        }
                    )

                    if (
                        arguments.apply
                        and "authentication" not in message.casefold()
                    ):
                        save_failure(
                            listing_id=listing_id,
                            auction_url=auction_url,
                            error_message=message,
                        )

                if (
                    index < len(candidates)
                    and arguments.delay > 0
                ):
                    time.sleep(
                        arguments.delay
                    )
        finally:
            if owns_context:
                context.close()

    summary_path = (
        arguments.log_dir
        / "crawl_summary.json"
    )
    summary_path.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("Crawl summary")
    print("=============")
    print(f"Processed: {len(results)}")
    print(f"Failures : {failures}")
    print(f"Summary  : {summary_path}")

    if not arguments.apply:
        print()
        print("DRY RUN ONLY")
        print(
            "No database writes were performed."
        )

    return 1 if failures else 0



if __name__ == "__main__":
    raise SystemExit(main())
