"""Repair Gripsweat identities and enrich stored detail pages."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy import text

from auction_etl.services.marketplace_browser_runtime import browser
from auction_etl.database.session import engine


DEFAULT_PROBE = Path(
    "logs/gripsweat/probe/gripsweat_probe.json"
)
DEFAULT_OUTPUT = Path(
    "logs/gripsweat/detail/gripsweat_detail_results.json"
)
DEFAULT_DIAGNOSTICS = Path(
    "logs/gripsweat/detail"
)

ITEM_ID_PATTERN = re.compile(
    r"/item/([0-9]{6,20})(?:/|$)",
    re.IGNORECASE,
)

EBAY_PATTERNS = (
    re.compile(
        r"(?:ebay\.[^/]+/itm/(?:[^/?#]+/)?)([0-9]{9,15})",
        re.IGNORECASE,
    ),
    re.compile(
        r"[?&](?:item|itemid)=([0-9]{9,15})(?:[&#]|$)",
        re.IGNORECASE,
    ),
)

PRICE_PATTERN = re.compile(
    r"(?:(?:US\s*)?\$|USD\s*)"
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)

DATE_PATTERNS = (
    re.compile(
        r"(?:Sold|Sale|Ended|End)\s*(?:Date|On)?\s*:?\s*"
        r"([A-Za-z]{3,9}\s+[0-9]{1,2},\s+[0-9]{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Sold|Sale|Ended|End)\s*(?:Date|On)?\s*:?\s*"
        r"([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Sold|Sale|Ended|End)\s*(?:Date|On)?\s*:?\s*"
        r"([0-9]{4}-[0-9]{2}-[0-9]{2})",
        re.IGNORECASE,
    ),
)

DATE_FORMATS = (
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y-%m-%d",
)


@dataclass(frozen=True, slots=True)
class StoredSale:
    id: int
    source_name: str
    configured_artist: str
    gripsweat_url: str
    gripsweat_item_id: str


@dataclass(slots=True)
class DetailResult:
    sale_id: int
    source_name: str
    configured_artist: str
    gripsweat_item_id: str
    requested_url: str
    final_url: str | None = None
    http_status: int | None = None
    title: str | None = None
    sold_at: datetime | None = None
    sold_price: Decimal | None = None
    currency: str | None = None
    image_url: str | None = None
    original_url: str | None = None
    original_marketplace: str | None = None
    original_listing_id: str | None = None
    complete: bool = False
    error: str | None = None
    html_path: str | None = None
    screenshot_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "source_name": self.source_name,
            "configured_artist": self.configured_artist,
            "gripsweat_item_id": self.gripsweat_item_id,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "http_status": self.http_status,
            "title": self.title,
            "sold_at": (
                self.sold_at.isoformat()
                if self.sold_at is not None
                else None
            ),
            "sold_price": (
                str(self.sold_price)
                if self.sold_price is not None
                else None
            ),
            "currency": self.currency,
            "image_url": self.image_url,
            "original_url": self.original_url,
            "original_marketplace": self.original_marketplace,
            "original_listing_id": self.original_listing_id,
            "complete": self.complete,
            "error": self.error,
            "html_path": self.html_path,
            "screenshot_path": self.screenshot_path,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair Gripsweat numeric identities and enrich detail pages."
        )
    )
    parser.add_argument(
        "--probe",
        type=Path,
        default=DEFAULT_PROBE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=DEFAULT_DIAGNOSTICS,
    )
    parser.add_argument(
        "--source",
        help="Process only one configured source name.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum detail pages. Zero means all.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help=(
            "Maximum attempts for transient navigation failures."
        ),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=10.0,
        help=(
            "Base seconds between transient navigation retries."
        ),
    )
    parser.add_argument(
        "--profile",
        default="gripsweat",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write repaired and enriched values to PostgreSQL.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Return success when records were ingested but some "
            "detail pages remain incomplete."
        ),
    )
    parser.add_argument(
        "--refresh-complete",
        action="store_true",
        help="Revisit rows that already have title and sold date.",
    )
    parser.add_argument(
        "--item-id-file",
        type=Path,
        help=(
            "Optional newline-delimited Gripsweat item-ID allowlist. "
            "Manual/backfill behavior remains unchanged when omitted."
        ),
    )
    return parser.parse_args()


def item_id_from_url(url: str) -> str | None:
    match = ITEM_ID_PATTERN.search(url)
    return match.group(1) if match else None


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = " ".join(str(value).replace("\xa0", " ").split())
    return cleaned or None


def decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None

    cleaned = re.sub(
        r"[^0-9.\-]",
        "",
        str(value),
    )

    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(value: Any) -> datetime | None:
    cleaned = normalize_text(value)

    if not cleaned:
        return None

    iso_candidate = cleaned.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(
                cleaned,
                date_format,
            )
        except ValueError:
            continue

    return None


def first_value(
    mapping: dict[str, Any],
    keys: Iterable[str],
) -> Any:
    for key in keys:
        value = mapping.get(key)

        if value not in (None, "", [], {}):
            return value

    return None


def iter_json_ld(
    soup: BeautifulSoup,
) -> Iterable[dict[str, Any]]:
    for script in soup.select(
        "script[type='application/ld+json']"
    ):
        raw = script.string or script.get_text()

        if not raw.strip():
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates: list[Any]

        if isinstance(payload, list):
            candidates = payload
        else:
            candidates = [payload]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            graph = candidate.get("@graph")

            if isinstance(graph, list):
                for graph_item in graph:
                    if isinstance(graph_item, dict):
                        yield graph_item

            yield candidate


def meta_content(
    soup: BeautifulSoup,
    *selectors: str,
) -> str | None:
    for selector in selectors:
        element = soup.select_one(selector)

        if element is None:
            continue

        value = element.get("content")

        if value:
            return normalize_text(value)

    return None


def extract_title(
    soup: BeautifulSoup,
    json_ld: list[dict[str, Any]],
) -> str | None:
    for payload in json_ld:
        value = first_value(
            payload,
            ("name", "headline"),
        )

        cleaned = normalize_text(value)

        if cleaned:
            return cleaned

    meta_title = meta_content(
        soup,
        "meta[property='og:title']",
        "meta[name='twitter:title']",
    )

    if meta_title:
        return meta_title

    heading = soup.select_one("h1")

    if heading is not None:
        cleaned = normalize_text(
            heading.get_text(" ", strip=True)
        )

        if cleaned:
            return cleaned

    if soup.title is not None:
        return normalize_text(soup.title.get_text())

    return None


def extract_image(
    soup: BeautifulSoup,
    json_ld: list[dict[str, Any]],
    page_url: str,
) -> str | None:
    for payload in json_ld:
        image = payload.get("image")

        if isinstance(image, list) and image:
            image = image[0]

        if isinstance(image, dict):
            image = first_value(
                image,
                ("url", "contentUrl"),
            )

        cleaned = normalize_text(image)

        if cleaned:
            return urljoin(page_url, cleaned)

    meta_image = meta_content(
        soup,
        "meta[property='og:image']",
        "meta[name='twitter:image']",
    )

    if meta_image:
        return urljoin(page_url, meta_image)

    image = soup.select_one(
        "main img[src], article img[src], .item img[src]"
    )

    if image is not None:
        source = normalize_text(image.get("src"))

        if source:
            return urljoin(page_url, source)

    return None


def extract_offer(
    soup: BeautifulSoup,
    json_ld: list[dict[str, Any]],
    visible_text: str,
) -> tuple[Decimal | None, str | None]:
    for payload in json_ld:
        offers = payload.get("offers")

        if isinstance(offers, list):
            candidates = offers
        elif isinstance(offers, dict):
            candidates = [offers]
        else:
            candidates = []

        for offer in candidates:
            price = decimal_value(
                first_value(
                    offer,
                    (
                        "price",
                        "lowPrice",
                        "highPrice",
                    ),
                )
            )
            currency = normalize_text(
                first_value(
                    offer,
                    (
                        "priceCurrency",
                        "currency",
                    ),
                )
            )

            if price is not None:
                return price, currency or "USD"

    meta_price = meta_content(
        soup,
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
    )
    meta_currency = meta_content(
        soup,
        "meta[property='product:price:currency']",
        "meta[itemprop='priceCurrency']",
    )

    price = decimal_value(meta_price)

    if price is not None:
        return price, meta_currency or "USD"

    match = PRICE_PATTERN.search(visible_text)

    if match:
        return decimal_value(match.group(1)), "USD"

    return None, None


def extract_sold_at(
    soup: BeautifulSoup,
    json_ld: list[dict[str, Any]],
    visible_text: str,
) -> datetime | None:
    for payload in json_ld:
        for key in (
            "endDate",
            "dateSold",
        ):
            parsed = parse_date(payload.get(key))

            if parsed is not None:
                return parsed

        offers = payload.get("offers")

        if isinstance(offers, dict):
            parsed = parse_date(
                first_value(
                    offers,
                    (
                        "priceValidUntil",
                        "endDate",
                    ),
                )
            )

            if parsed is not None:
                return parsed

    for element in soup.select("time[datetime]"):
        nearby = normalize_text(
            element.parent.get_text(
                " ",
                strip=True,
            )
            if element.parent is not None
            else ""
        )

        if nearby and any(
            marker in nearby.casefold()
            for marker in (
                "sold",
                "ended",
                "sale date",
                "end date",
            )
        ):
            parsed = parse_date(
                element.get("datetime")
            )

            if parsed is not None:
                return parsed

    for pattern in DATE_PATTERNS:
        match = pattern.search(visible_text)

        if match:
            parsed = parse_date(match.group(1))

            if parsed is not None:
                return parsed

    return None


def extract_original_listing(
    soup: BeautifulSoup,
    page_url: str,
) -> tuple[str | None, str | None, str | None]:
    fallback_url: str | None = None

    for link in soup.select("a[href]"):
        href = normalize_text(link.get("href"))

        if not href:
            continue

        absolute_url = urljoin(page_url, href)
        hostname = (
            urlparse(absolute_url).hostname or ""
        ).casefold()

        if "ebay." not in hostname:
            continue

        fallback_url = fallback_url or absolute_url

        for pattern in EBAY_PATTERNS:
            match = pattern.search(absolute_url)

            if match:
                return (
                    absolute_url,
                    "ebay",
                    match.group(1),
                )

    if fallback_url:
        return fallback_url, "ebay", None

    return None, None, None


def visible_body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(
            timeout=10_000
        )
    except Exception:
        return ""


def save_diagnostics(
    page: Page,
    html: str,
    item_id: str,
    diagnostics_dir: Path,
) -> tuple[str, str]:
    diagnostics_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    html_path = diagnostics_dir / f"{item_id}.html"
    screenshot_path = diagnostics_dir / f"{item_id}.png"

    html_path.write_text(
        html,
        encoding="utf-8",
    )

    try:
        page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )
    except Exception:
        screenshot_path = diagnostics_dir / (
            f"{item_id}.screenshot-failed"
        )
        screenshot_path.write_text(
            "Screenshot capture failed.\n",
            encoding="utf-8",
        )

    return str(html_path), str(screenshot_path)


def ensure_schema() -> None:
    statements = (
        """
        ALTER TABLE warehouse.gripsweat_sale
        ADD COLUMN IF NOT EXISTS gripsweat_item_id VARCHAR(32)
        """,
        """
        ALTER TABLE warehouse.gripsweat_sale
        ADD COLUMN IF NOT EXISTS original_url TEXT
        """,
        """
        ALTER TABLE warehouse.gripsweat_sale
        ADD COLUMN IF NOT EXISTS detail_checked_at TIMESTAMPTZ
        """,
        """
        ALTER TABLE warehouse.gripsweat_sale
        ADD COLUMN IF NOT EXISTS detail_status VARCHAR(32)
        """,
        """
        ALTER TABLE warehouse.gripsweat_sale
        ADD COLUMN IF NOT EXISTS detail_error TEXT
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_gripsweat_sale_source_item_id
        ON warehouse.gripsweat_sale (
            source_name,
            gripsweat_item_id
        )
        WHERE gripsweat_item_id IS NOT NULL
        """,
    )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def repair_existing_identity() -> int:
    statement = text(
        """
        UPDATE warehouse.gripsweat_sale
        SET
            gripsweat_item_id = (
                regexp_match(
                    gripsweat_url,
                    '/item/([0-9]{6,20})(?:/|$)'
                )
            )[1],
            gripsweat_item_key = (
                regexp_match(
                    gripsweat_url,
                    '/item/([0-9]{6,20})(?:/|$)'
                )
            )[1]
        WHERE gripsweat_url ~
            '/item/[0-9]{6,20}(?:/|$)'
          AND (
              gripsweat_item_id IS DISTINCT FROM (
                  regexp_match(
                      gripsweat_url,
                      '/item/([0-9]{6,20})(?:/|$)'
                  )
              )[1]
              OR gripsweat_item_key IS DISTINCT FROM (
                  regexp_match(
                      gripsweat_url,
                      '/item/([0-9]{6,20})(?:/|$)'
                  )
              )[1]
          )
        """
    )

    with engine.begin() as connection:
        result = connection.execute(statement)

    return int(result.rowcount or 0)


def probe_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    pages = payload.get("pages", [])

    if not isinstance(pages, list):
        raise ValueError(
            "Probe JSON does not contain a pages list."
        )

    items: list[dict[str, Any]] = []

    for page in pages:
        if not isinstance(page, dict):
            continue

        if page.get("error"):
            continue

        page_items = page.get("items", [])

        if not isinstance(page_items, list):
            continue

        for item in page_items:
            if isinstance(item, dict):
                items.append(item)

    return items


def unique_probe_sale_id(
    matching_ids: Iterable[int],
    *,
    source_name: str,
    item_id: str,
) -> int:
    """Require probe identities to resolve exactly one stored sale."""

    unique_ids = sorted(
        {
            int(value)
            for value in matching_ids
        }
    )

    if not unique_ids:
        raise RuntimeError(
            "No existing Gripsweat sale row resolved for "
            f"{source_name}/{item_id} across URL, "
            "source/item, or original-listing identity."
        )

    if len(unique_ids) != 1:
        raise RuntimeError(
            "Gripsweat probe identities resolve to different "
            "existing sale rows for "
            f"{source_name}/{item_id}: "
            + ", ".join(
                str(value)
                for value in unique_ids
            )
        )

    return unique_ids[0]


def reimport_probe_rows(path: Path) -> tuple[int, int]:
    """Refresh probe fields on one canonically resolved stored sale.

    GRIPSWEAT_UPDATE_ONLY_DETAIL_REIMPORT_V2
    """

    items = probe_items(path)
    updated = 0
    invalid = 0

    identity_statement = text(
        """
        SELECT id
        FROM warehouse.gripsweat_sale
        WHERE
            gripsweat_url = :gripsweat_url
            OR (
                source_name = :source_name
                AND gripsweat_item_key = :gripsweat_item_key
            )
            OR (
                original_marketplace = :original_marketplace
                AND original_listing_id = :original_listing_id
            )
        ORDER BY id
        FOR UPDATE
        """
    )

    update_statement = text(
        """
        UPDATE warehouse.gripsweat_sale
        SET
            configured_artist = :configured_artist,
            gripsweat_item_key = :gripsweat_item_key,
            gripsweat_item_id = :gripsweat_item_id,
            gripsweat_url = :gripsweat_url,
            title = COALESCE(
                :title,
                title
            ),
            sold_price = COALESCE(
                :sold_price,
                sold_price
            ),
            currency = COALESCE(
                :currency,
                currency
            ),
            image_url = COALESCE(
                :image_url,
                image_url
            ),
            original_marketplace = COALESCE(
                :original_marketplace,
                original_marketplace
            ),
            original_listing_id = COALESCE(
                :original_listing_id,
                original_listing_id
            )
        WHERE id = :sale_id
        """
    )

    with engine.begin() as connection:
        for item in items:
            url = normalize_text(
                first_value(
                    item,
                    (
                        "gripsweat_url",
                        "url",
                        "listing_url",
                    ),
                )
            )

            source_name = normalize_text(
                item.get(
                    "source_name"
                )
            )

            configured_artist = normalize_text(
                first_value(
                    item,
                    (
                        "configured_artist",
                        "artist",
                        "source_artist",
                    ),
                )
            )

            if not url or not source_name:
                invalid += 1
                continue

            item_id = item_id_from_url(
                url
            )

            if not item_id:
                invalid += 1
                continue

            parameters = {
                "source_name":
                    source_name,
                "configured_artist": (
                    configured_artist
                    or source_name
                ),
                "gripsweat_item_key":
                    item_id,
                "gripsweat_item_id":
                    item_id,
                "gripsweat_url":
                    url,
                "title":
                    normalize_text(
                        item.get(
                            "title"
                        )
                    ),
                "sold_price":
                    decimal_value(
                        first_value(
                            item,
                            (
                                "sold_price",
                                "price",
                            ),
                        )
                    ),
                "currency":
                    normalize_text(
                        item.get(
                            "currency"
                        )
                    ),
                "image_url":
                    normalize_text(
                        first_value(
                            item,
                            (
                                "image_url",
                                "image",
                            ),
                        )
                    ),
                "original_marketplace":
                    normalize_text(
                        item.get(
                            "original_marketplace"
                        )
                    ),
                "original_listing_id":
                    normalize_text(
                        item.get(
                            "original_listing_id"
                        )
                    ),
            }

            matching_ids = connection.execute(
                identity_statement,
                parameters,
            ).scalars().all()

            sale_id = unique_probe_sale_id(
                matching_ids,
                source_name=source_name,
                item_id=item_id,
            )

            result = connection.execute(
                update_statement,
                {
                    **parameters,
                    "sale_id":
                        sale_id,
                },
            )

            affected = int(
                result.rowcount
                or 0
            )

            if affected != 1:
                raise RuntimeError(
                    "Resolved Gripsweat sale row "
                    f"id={sale_id} for "
                    f"{source_name}/{item_id}, "
                    f"but update affected {affected} rows."
                )

            updated += 1

    return updated, invalid



def load_sales(
    source: str | None,
    limit: int,
    refresh_complete: bool,
) -> list[StoredSale]:
    conditions = [
        "gripsweat_url IS NOT NULL",
        "gripsweat_url <> ''",
        "gripsweat_item_id IS NOT NULL",
    ]
    parameters: dict[str, Any] = {}

    if source:
        conditions.append(
            "source_name = :source_name"
        )
        parameters["source_name"] = source

    if not refresh_complete:
        conditions.append(
            """
            (
                title IS NULL
                OR sold_at IS NULL
                OR detail_status IS DISTINCT FROM 'complete'
            )
            """
        )

    limit_clause = ""

    if limit > 0:
        limit_clause = "LIMIT :limit"
        parameters["limit"] = limit

    where_clause = "\nAND ".join(conditions)

    statement = text(
        f"""
        SELECT
            id,
            source_name,
            configured_artist,
            gripsweat_url,
            gripsweat_item_id
        FROM warehouse.gripsweat_sale
        WHERE {where_clause}
        ORDER BY
            configured_artist,
            id
        {limit_clause}
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            parameters,
        ).mappings().all()

    return [
        StoredSale(
            id=int(row["id"]),
            source_name=str(row["source_name"]),
            configured_artist=str(
                row["configured_artist"]
            ),
            gripsweat_url=str(row["gripsweat_url"]),
            gripsweat_item_id=str(
                row["gripsweat_item_id"]
            ),
        )
        for row in rows
    ]


def retryable_navigation_error(
    error: str | None,
) -> bool:
    """Return whether a detail navigation failure is transient."""

    if not error:
        return False

    lowered = error.casefold()

    if "page.goto:" not in lowered:
        return False

    markers = (
        "timeout",
        "err_network_io_suspended",
        "err_connection_reset",
        "err_timed_out",
        "err_network_changed",
        "err_http2_protocol_error",
        "err_connection_closed",
    )

    return any(
        marker in lowered
        for marker in markers
    )


def inspect_sale_with_retry(
    context: BrowserContext,
    sale: StoredSale,
    wait_seconds: float,
    diagnostics_dir: Path,
    attempts: int,
    retry_delay: float,
) -> DetailResult:
    """Inspect one sale with bounded transient-navigation retries."""

    if attempts < 1:
        raise ValueError(
            "attempts must be at least 1."
        )

    result: DetailResult | None = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        page = context.new_page()

        try:
            result = inspect_sale(
                page,
                sale,
                wait_seconds,
                diagnostics_dir,
            )
        finally:
            try:
                page.close()
            except Exception:
                pass

        if result.complete:
            return result

        if not retryable_navigation_error(
            result.error
        ):
            return result

        if attempt >= attempts:
            return result

        delay = min(
            60.0,
            max(
                0.0,
                retry_delay,
            )
            * (
                2
                ** (
                    attempt - 1
                )
            ),
        )

        print()
        print(
            "Transient Gripsweat navigation failure; "
            f"retrying {sale.gripsweat_item_id} "
            f"after {delay:.1f}s "
            f"(attempt {attempt + 1}/{attempts})."
        )

        time.sleep(
            delay
        )

    if result is None:
        raise RuntimeError(
            "Detail retry loop produced no result."
        )

    return result


def inspect_sale(
    page: Page,
    sale: StoredSale,
    wait_seconds: float,
    diagnostics_dir: Path,
) -> DetailResult:
    result = DetailResult(
        sale_id=sale.id,
        source_name=sale.source_name,
        configured_artist=sale.configured_artist,
        gripsweat_item_id=sale.gripsweat_item_id,
        requested_url=sale.gripsweat_url,
    )

    try:
        response = page.goto(
            sale.gripsweat_url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        result.http_status = (
            response.status
            if response is not None
            else None
        )
        result.final_url = page.url

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=max(
                    5_000,
                    int(wait_seconds * 1_000),
                ),
            )
        except PlaywrightTimeoutError:
            page.wait_for_timeout(
                max(
                    2_000,
                    int(wait_seconds * 1_000),
                )
            )

        html = page.content()
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        json_ld = list(iter_json_ld(soup))
        visible_text = visible_body_text(page)

        result.title = extract_title(
            soup,
            json_ld,
        )
        result.image_url = extract_image(
            soup,
            json_ld,
            page.url,
        )
        (
            result.sold_price,
            result.currency,
        ) = extract_offer(
            soup,
            json_ld,
            visible_text,
        )
        result.sold_at = extract_sold_at(
            soup,
            json_ld,
            visible_text,
        )
        (
            result.original_url,
            result.original_marketplace,
            result.original_listing_id,
        ) = extract_original_listing(
            soup,
            page.url,
        )

        result.complete = (
            result.title is not None
            and result.sold_at is not None
            and result.sold_price is not None
        )

        if not result.complete:
            (
                result.html_path,
                result.screenshot_path,
            ) = save_diagnostics(
                page,
                html,
                sale.gripsweat_item_id,
                diagnostics_dir,
            )

            missing = [
                name
                for name, value in (
                    ("title", result.title),
                    ("sold_at", result.sold_at),
                    ("sold_price", result.sold_price),
                )
                if value is None
            ]

            result.error = (
                "Missing required detail fields: "
                + ", ".join(missing)
            )

    except Exception as exc:
        result.error = str(exc)

        try:
            html = page.content()
            (
                result.html_path,
                result.screenshot_path,
            ) = save_diagnostics(
                page,
                html,
                sale.gripsweat_item_id,
                diagnostics_dir,
            )
        except Exception:
            pass

    return result


def apply_result(result: DetailResult) -> None:
    statement = text(
        """
        UPDATE warehouse.gripsweat_sale
        SET
            title = COALESCE(
                :title,
                title
            ),
            sold_at = COALESCE(
                :sold_at,
                sold_at
            ),
            sold_price = COALESCE(
                :sold_price,
                sold_price
            ),
            currency = COALESCE(
                :currency,
                currency
            ),
            image_url = COALESCE(
                :image_url,
                image_url
            ),
            original_url = COALESCE(
                :original_url,
                original_url
            ),
            original_marketplace = COALESCE(
                :original_marketplace,
                original_marketplace
            ),
            original_listing_id = COALESCE(
                :original_listing_id,
                original_listing_id
            ),
            detail_checked_at = now(),
            detail_status = :detail_status,
            detail_error = :detail_error
        WHERE id = :sale_id
        """
    )

    with engine.begin() as connection:
        connection.execute(
            statement,
            {
                "sale_id": result.sale_id,
                "title": result.title,
                "sold_at": result.sold_at,
                "sold_price": result.sold_price,
                "currency": result.currency,
                "image_url": result.image_url,
                "original_url": result.original_url,
                "original_marketplace": (
                    result.original_marketplace
                ),
                "original_listing_id": (
                    result.original_listing_id
                ),
                "detail_status": (
                    "complete"
                    if result.complete
                    else "incomplete"
                ),
                "detail_error": result.error,
            },
        )


def print_result(
    index: int,
    total: int,
    result: DetailResult,
) -> None:
    print()
    print(
        f"[{index}/{total}] "
        f"{result.configured_artist} "
        f"{result.gripsweat_item_id}"
    )
    print("URL        :", result.requested_url)
    print("HTTP       :", result.http_status)
    print("Final URL  :", result.final_url)
    print("Title      :", result.title)
    print("Sold date  :", result.sold_at)
    print("Price      :", result.sold_price)
    print("Currency   :", result.currency)
    print("Image      :", result.image_url)
    print("Original   :", result.original_url)
    print("Original ID:", result.original_listing_id)
    print("Complete   :", result.complete)

    if result.error:
        print("Issue      :", result.error)

    if result.html_path:
        print("HTML       :", result.html_path)

    if result.screenshot_path:
        print("Screenshot :", result.screenshot_path)


def print_database_summary() -> None:
    statement = text(
        """
        SELECT
            configured_artist,
            COUNT(*) AS rows,
            COUNT(DISTINCT gripsweat_item_id)
                AS unique_item_ids,
            COUNT(title) AS titles,
            COUNT(sold_price) AS prices,
            COUNT(sold_at) AS sold_dates,
            COUNT(image_url) AS images,
            COUNT(original_listing_id)
                AS original_listing_ids,
            COUNT(*) FILTER (
                WHERE detail_status = 'complete'
            ) AS complete_details,
            COUNT(*) FILTER (
                WHERE detail_status = 'incomplete'
            ) AS incomplete_details
        FROM warehouse.gripsweat_sale
        GROUP BY configured_artist
        ORDER BY configured_artist
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(
            statement
        ).mappings().all()

    print()
    print("Gripsweat database coverage")
    print("---------------------------")

    for row in rows:
        print()
        print(row["configured_artist"])
        print("  Rows             :", row["rows"])
        print(
            "  Unique item IDs  :",
            row["unique_item_ids"],
        )
        print("  Titles           :", row["titles"])
        print("  Prices           :", row["prices"])
        print("  Sold dates       :", row["sold_dates"])
        print("  Images           :", row["images"])
        print(
            "  Original IDs     :",
            row["original_listing_ids"],
        )
        print(
            "  Complete details :",
            row["complete_details"],
        )
        print(
            "  Incomplete       :",
            row["incomplete_details"],
        )


def main() -> int:
    args = parse_args()

    if not args.probe.exists():
        raise SystemExit(
            f"Probe file not found: {args.probe}"
        )

    ensure_schema()

    if args.apply:
        repaired = repair_existing_identity()
        reimported, invalid = reimport_probe_rows(
            args.probe
        )

        print()
        print("Identity repair")
        print("---------------")
        print("Existing rows repaired :", repaired)
        print("Probe rows processed   :", reimported)
        print("Invalid probe rows     :", invalid)
    else:
        print()
        print("DRY RUN")
        print("-------")
        print(
            "Enrichment schema was verified. "
            "No Gripsweat sale rows will be updated."
        )

    rows = load_sales(
        args.source,
        args.limit,
        args.refresh_complete,
    )

    if args.item_id_file is not None:
        if not args.item_id_file.is_file():
            raise SystemExit(
                "Gripsweat item-ID allowlist not found: "
                f"{args.item_id_file}"
            )

        allowed_item_ids = {
            line.strip()
            for line in (
                args.item_id_file
                .read_text(
                    encoding="utf-8"
                )
                .splitlines()
            )
            if line.strip()
        }

        rows = [
            sale
            for sale in rows
            if sale.gripsweat_item_id
            in allowed_item_ids
        ]

        print()
        print(
            "Incremental Gripsweat detail policy"
        )
        print(
            "-----------------------------------"
        )
        print(
            "Allowlisted new item IDs :",
            len(
                allowed_item_ids
            ),
        )
        print(
            "Detail pages selected    :",
            len(
                rows
            ),
        )

    if not rows:
        print("No matching detail pages require processing.")
        print_database_summary()
        return 0

    args.diagnostics_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if args.attempts < 1:
        raise SystemExit(
            "--attempts must be at least 1."
        )

    if args.retry_delay < 0:
        raise SystemExit(
            "--retry-delay cannot be negative."
        )

    context = browser.context(
        args.profile
    )

    results: list[DetailResult] = []

    for index, sale in enumerate(
        rows,
        start=1,
    ):
        result = inspect_sale_with_retry(
            context,
            sale,
            args.wait_seconds,
            args.diagnostics_dir,
            args.attempts,
            args.retry_delay,
        )

        results.append(
            result
        )

        print_result(
            index,
            len(rows),
            result,
        )

        if args.apply:
            apply_result(
                result
            )

        if index < len(rows):
            time.sleep(
                max(
                    0.0,
                    args.delay,
                )
            )

    args.output.write_text(
        json.dumps(
            [
                result.as_dict()
                for result in results
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    complete = sum(
        result.complete
        for result in results
    )
    incomplete = len(results) - complete

    print()
    print("Detail enrichment summary")
    print("-------------------------")
    print("Pages processed :", len(results))
    print("Complete        :", complete)
    print("Incomplete      :", incomplete)
    print("Applied         :", args.apply)
    print("Output          :", args.output)

    print_database_summary()

    if incomplete > 0 and args.allow_incomplete:
        print()
        print(
            "Incomplete detail records remain durable and "
            "can be enriched later."
        )
        print(
            "GRIPSWEAT_INCOMPLETE_DETAIL_POLICY=CONTINUE"
        )
        return 0

    return 0 if incomplete == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
