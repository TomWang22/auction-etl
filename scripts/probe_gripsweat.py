"""Read-only Gripsweat search probe with saved diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.browser.manager import browser


DEFAULT_CONFIG = Path("config/gripsweat_sources.json")
DEFAULT_OUTPUT = Path("logs/gripsweat/probe/gripsweat_probe.json")
DEFAULT_DIAGNOSTIC_DIR = Path("logs/gripsweat")

ITEM_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?gripsweat\.com/item/[^?#]+",
    re.IGNORECASE,
)

EBAY_ITEM_PATTERNS = (
    re.compile(
        r"(?:ebay\.[^/]+/itm/(?:[^/?#]+/)?)"
        r"(?P<item_id>[0-9]{9,15})",
        re.IGNORECASE,
    ),
    re.compile(
        r"[?&](?:item|itemid|item_id)="
        r"(?P<item_id>[0-9]{9,15})(?:[&#]|$)",
        re.IGNORECASE,
    ),
)

PRICE_PATTERNS = (
    re.compile(
        r"(?P<currency>US\s*\$|USD|\$)\s*"
        r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>£|GBP)\s*"
        r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>€|EUR)\s*"
        r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>¥|JPY)\s*"
        r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
)

DATE_PATTERNS = (
    re.compile(
        r"(?:sold|ended|completed|sale\s+date)\s*[:\-]?\s*"
        r"(?P<date>[A-Za-z]{3,9}\s+[0-9]{1,2},\s+[0-9]{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:sold|ended|completed|sale\s+date)\s*[:\-]?\s*"
        r"(?P<date>[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:sold|ended|completed|sale\s+date)\s*[:\-]?\s*"
        r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})",
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

CARD_SELECTORS = (
    "article",
    "li[class*='item']",
    "div[class*='item']",
    "div[class*='result']",
    "div[class*='auction']",
    "div[class*='listing']",
    ".search-result",
    ".product",
)

NEXT_SELECTORS = (
    "a[rel='next'][href]",
    "a[aria-label*='Next' i][href]",
    "a.next[href]",
    ".pagination a.next[href]",
    ".pagination-next a[href]",
)


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    artist: str
    query: str
    url_template: str
    enabled: bool
    max_pages: int
    delay_seconds: float
    sort_by: str


@dataclass(slots=True)
class ProbeItem:
    source_name: str
    configured_artist: str
    source_query: str
    page_number: int
    position: int
    gripsweat_item_key: str
    gripsweat_url: str
    title: str | None
    sold_price: str | None
    currency: str | None
    sold_at_text: str | None
    sold_at: str | None
    image_url: str | None
    original_marketplace: str | None
    original_listing_id: str | None
    raw_text: str | None


@dataclass(slots=True)
class PageProbe:
    source_name: str
    configured_artist: str
    page_number: int
    requested_url: str
    final_url: str
    http_status: int | None
    page_title: str
    redirected: bool
    html_sha256: str
    html_path: str
    screenshot_path: str
    selector_counts: dict[str, int]
    next_page_detected: bool
    item_count: int
    items: list[ProbeItem] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class ProbeSummary:
    started_at: str
    completed_at: str | None
    database_writes: int
    sources_requested: int
    pages_loaded: int
    pages_accepted: int
    items_found: int
    repeated_pages: int
    empty_pages: int
    failures: int
    pages: list[PageProbe] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Gripsweat paginated search probe."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help="Run only this source name. Repeatable.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override configured maximum pages.",
    )
    parser.add_argument(
        "--profile",
        default="gripsweat-probe",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--diagnostic-dir",
        type=Path,
        default=DEFAULT_DIAGNOSTIC_DIR,
    )
    return parser.parse_args()


def load_sources(path: Path) -> list[Source]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, list):
        raise ValueError("Source configuration must contain a JSON list.")

    sources: list[Source] = []
    seen_names: set[str] = set()

    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Every source entry must be an object.")

        source = Source(
            name=str(entry["name"]).strip(),
            artist=str(entry["artist"]).strip(),
            query=str(entry["query"]).strip(),
            url_template=str(entry["url_template"]).strip(),
            enabled=bool(entry.get("enabled", True)),
            max_pages=max(1, int(entry.get("max_pages", 1))),
            delay_seconds=max(
                0.0,
                float(entry.get("delay_seconds", 3.0)),
            ),
            sort_by=str(entry.get("sort_by", "date")).strip(),
        )

        if source.name in seen_names:
            raise ValueError(f"Duplicate source name: {source.name}")

        if "{query}" not in source.url_template:
            raise ValueError(
                f"{source.name}: URL template requires {{query}}."
            )

        if "{page}" not in source.url_template:
            raise ValueError(
                f"{source.name}: URL template requires {{page}}."
            )

        seen_names.add(source.name)
        sources.append(source)

    return sources


def build_page_url(source: Source, page_number: int) -> str:
    if page_number < 1:
        raise ValueError("Page number must be at least one.")

    return source.url_template.format(
        query=quote_plus(source.query),
        page=page_number,
        sort_by=quote_plus(source.sort_by),
    )


def normalize_space(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = " ".join(value.replace("\xa0", " ").split())
    return cleaned or None


def canonicalize_url(value: str, base_url: str) -> str:
    absolute = urljoin(base_url, value)
    parts = urlsplit(absolute)

    return parts._replace(
        query="",
        fragment="",
    ).geturl().rstrip("/")


def item_key_from_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")

    candidate = path.rsplit("/", 1)[-1].strip()

    if candidate:
        return candidate

    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def extract_original_ebay_id(
    *values: str | None,
) -> tuple[str | None, str | None]:
    for value in values:
        if not value:
            continue

        for pattern in EBAY_ITEM_PATTERNS:
            match = pattern.search(value)

            if match:
                return "ebay", match.group("item_id")

    return None, None


def parse_price(
    *values: str | None,
) -> tuple[str | None, str | None]:
    currency_map = {
        "$": "USD",
        "US$": "USD",
        "US $": "USD",
        "USD": "USD",
        "£": "GBP",
        "GBP": "GBP",
        "€": "EUR",
        "EUR": "EUR",
        "¥": "JPY",
        "JPY": "JPY",
    }

    for value in values:
        if not value:
            continue

        for pattern in PRICE_PATTERNS:
            match = pattern.search(value)

            if match is None:
                continue

            amount_text = match.group("amount").replace(",", "")
            currency_text = re.sub(
                r"\s+",
                " ",
                match.group("currency").upper(),
            )

            try:
                amount = Decimal(amount_text)
            except InvalidOperation:
                continue

            currency = currency_map.get(
                currency_text,
                currency_text,
            )

            return format(amount, "f"), currency

    return None, None


def parse_sale_date(
    *values: str | None,
) -> tuple[str | None, str | None]:
    for value in values:
        if not value:
            continue

        for pattern in DATE_PATTERNS:
            match = pattern.search(value)

            if match is None:
                continue

            raw_date = normalize_space(match.group("date"))

            if raw_date is None:
                continue

            for format_string in DATE_FORMATS:
                try:
                    parsed = datetime.strptime(
                        raw_date,
                        format_string,
                    )
                    return raw_date, parsed.date().isoformat()
                except ValueError:
                    continue

            return raw_date, None

    return None, None


def iter_json_ld_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value

        graph = value.get("@graph")

        if graph is not None:
            yield from iter_json_ld_objects(graph)

        item_list = value.get("itemListElement")

        if item_list is not None:
            yield from iter_json_ld_objects(item_list)

        item = value.get("item")

        if item is not None:
            yield from iter_json_ld_objects(item)

    elif isinstance(value, list):
        for item in value:
            yield from iter_json_ld_objects(item)


def extract_json_ld_items(
    soup: BeautifulSoup,
    source: Source,
    page_number: int,
    base_url: str,
) -> list[ProbeItem]:
    items: list[ProbeItem] = []
    seen_urls: set[str] = set()

    for script in soup.select(
        "script[type='application/ld+json']"
    ):
        payload_text = script.string or script.get_text()

        if not payload_text.strip():
            continue

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        for position, obj in enumerate(
            iter_json_ld_objects(payload),
            start=1,
        ):
            url_value = obj.get("url")

            if not isinstance(url_value, str):
                continue

            canonical_url = canonicalize_url(
                url_value,
                base_url,
            )

            if "/item/" not in canonical_url.casefold():
                continue

            if canonical_url in seen_urls:
                continue

            seen_urls.add(canonical_url)

            title = normalize_space(
                str(obj.get("name"))
                if obj.get("name") is not None
                else None
            )

            image_value = obj.get("image")
            image_url: str | None = None

            if isinstance(image_value, str):
                image_url = urljoin(base_url, image_value)
            elif isinstance(image_value, list) and image_value:
                image_url = urljoin(
                    base_url,
                    str(image_value[0]),
                )

            offers = obj.get("offers")
            price_value: str | None = None
            currency_value: str | None = None

            if isinstance(offers, dict):
                if offers.get("price") is not None:
                    price_value = str(offers["price"])

                if offers.get("priceCurrency") is not None:
                    currency_value = str(
                        offers["priceCurrency"]
                    ).upper()

            raw_json = json.dumps(
                obj,
                ensure_ascii=False,
                default=str,
            )

            if price_value is None:
                price_value, detected_currency = parse_price(
                    raw_json
                )
                currency_value = (
                    currency_value or detected_currency
                )

            sold_at_text, sold_at = parse_sale_date(raw_json)

            original_marketplace, original_listing_id = (
                extract_original_ebay_id(
                    canonical_url,
                    raw_json,
                )
            )

            items.append(
                ProbeItem(
                    source_name=source.name,
                    configured_artist=source.artist,
                    source_query=source.query,
                    page_number=page_number,
                    position=position,
                    gripsweat_item_key=item_key_from_url(
                        canonical_url
                    ),
                    gripsweat_url=canonical_url,
                    title=title,
                    sold_price=price_value,
                    currency=currency_value,
                    sold_at_text=sold_at_text,
                    sold_at=sold_at,
                    image_url=image_url,
                    original_marketplace=original_marketplace,
                    original_listing_id=original_listing_id,
                    raw_text=normalize_space(raw_json[:4000]),
                )
            )

    return items


def card_candidate(link: Tag) -> Tag:
    for parent in link.parents:
        if not isinstance(parent, Tag):
            continue

        if parent.name in {"article", "li"}:
            return parent

        classes = " ".join(
            str(value)
            for value in parent.get("class", [])
        ).casefold()

        if any(
            marker in classes
            for marker in (
                "item",
                "result",
                "auction",
                "listing",
                "product",
                "card",
            )
        ):
            return parent

    return link


def extract_dom_items(
    soup: BeautifulSoup,
    source: Source,
    page_number: int,
    base_url: str,
) -> list[ProbeItem]:
    items: list[ProbeItem] = []
    seen_urls: set[str] = set()

    links = soup.select("a[href]")

    for link in links:
        href = str(link.get("href") or "")

        if "/item/" not in href.casefold():
            continue

        canonical_url = canonicalize_url(
            href,
            base_url,
        )

        if not ITEM_URL_PATTERN.match(canonical_url):
            continue

        if canonical_url in seen_urls:
            continue

        seen_urls.add(canonical_url)

        card = card_candidate(link)
        card_text = normalize_space(
            card.get_text(" ", strip=True)
        )

        title = normalize_space(
            str(link.get("title") or "")
        )

        if not title:
            title = normalize_space(
                link.get_text(" ", strip=True)
            )

        if not title and isinstance(card, Tag):
            heading = card.select_one(
                "h1, h2, h3, h4, [class*='title']"
            )

            if heading is not None:
                title = normalize_space(
                    heading.get_text(" ", strip=True)
                )

        image_url: str | None = None

        if isinstance(card, Tag):
            image = card.select_one("img")

            if image is not None:
                for attribute in (
                    "src",
                    "data-src",
                    "data-lazy-src",
                    "srcset",
                ):
                    candidate = image.get(attribute)

                    if not candidate:
                        continue

                    candidate_text = str(candidate).split(",")[0]
                    candidate_text = candidate_text.split()[0]
                    image_url = urljoin(
                        base_url,
                        candidate_text,
                    )
                    break

        sold_price, currency = parse_price(
            card_text,
            title,
        )
        sold_at_text, sold_at = parse_sale_date(
            card_text,
            title,
        )

        original_marketplace, original_listing_id = (
            extract_original_ebay_id(
                canonical_url,
                href,
                card_text,
            )
        )

        items.append(
            ProbeItem(
                source_name=source.name,
                configured_artist=source.artist,
                source_query=source.query,
                page_number=page_number,
                position=len(items) + 1,
                gripsweat_item_key=item_key_from_url(
                    canonical_url
                ),
                gripsweat_url=canonical_url,
                title=title,
                sold_price=sold_price,
                currency=currency,
                sold_at_text=sold_at_text,
                sold_at=sold_at,
                image_url=image_url,
                original_marketplace=original_marketplace,
                original_listing_id=original_listing_id,
                raw_text=card_text,
            )
        )

    return items


def merge_items(
    primary: list[ProbeItem],
    secondary: list[ProbeItem],
) -> list[ProbeItem]:
    by_url: dict[str, ProbeItem] = {
        item.gripsweat_url: item
        for item in primary
    }

    for candidate in secondary:
        existing = by_url.get(candidate.gripsweat_url)

        if existing is None:
            by_url[candidate.gripsweat_url] = candidate
            continue

        for attribute in (
            "title",
            "sold_price",
            "currency",
            "sold_at_text",
            "sold_at",
            "image_url",
            "original_marketplace",
            "original_listing_id",
            "raw_text",
        ):
            if getattr(existing, attribute) is None:
                setattr(
                    existing,
                    attribute,
                    getattr(candidate, attribute),
                )

    merged = list(by_url.values())

    for position, item in enumerate(merged, start=1):
        item.position = position

    return merged


def selector_counts(
    page: Page,
) -> dict[str, int]:
    selectors = (
        *CARD_SELECTORS,
        "a[href*='/item/']",
        "script[type='application/ld+json']",
        *NEXT_SELECTORS,
    )

    counts: dict[str, int] = {}

    for selector in selectors:
        try:
            counts[selector] = page.locator(selector).count()
        except Exception:
            counts[selector] = -1

    return counts


def next_page_detected(
    soup: BeautifulSoup,
    current_page: int,
) -> bool:
    for selector in NEXT_SELECTORS:
        link = soup.select_one(selector)

        if link is None:
            continue

        disabled = str(
            link.get("aria-disabled", "")
        ).casefold()

        classes = " ".join(
            str(value)
            for value in link.get("class", [])
        ).casefold()

        if disabled == "true" or "disabled" in classes:
            continue

        if link.get("href"):
            return True

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")
        query = parse_qs(urlsplit(href).query)

        page_values = query.get("page", [])

        if not page_values:
            continue

        try:
            candidate_page = int(page_values[0])
        except ValueError:
            continue

        if candidate_page == current_page + 1:
            return True

    return False


def wait_for_page(page: Page, seconds: float) -> None:
    timeout_ms = max(
        5_000,
        int(seconds * 1_000),
    )

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=min(timeout_ms, 15_000),
        )
    except PlaywrightTimeoutError:
        pass

    try:
        page.locator(
            "a[href*='/item/']"
        ).first.wait_for(
            state="attached",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(1_500)


def safe_name(value: str) -> str:
    return re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        value,
    ).strip("-")


def probe_source(
    page: Page,
    source: Source,
    *,
    max_pages: int,
    wait_seconds: float,
    diagnostic_dir: Path,
    summary: ProbeSummary,
) -> None:
    html_dir = diagnostic_dir / "html"
    screenshot_dir = diagnostic_dir / "screenshots"

    html_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    previous_digest: str | None = None
    previous_item_keys: set[str] | None = None

    for page_number in range(1, max_pages + 1):
        requested_url = build_page_url(
            source,
            page_number,
        )

        print()
        print(
            f"[{source.name}] page {page_number}: "
            f"{requested_url}"
        )

        try:
            response = page.goto(
                requested_url,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            summary.pages_loaded += 1
            wait_for_page(page, wait_seconds)

            final_url = page.url
            status = (
                response.status
                if response is not None
                else None
            )
            title = page.title()
            html = page.content()
            digest = hashlib.sha256(
                html.encode("utf-8")
            ).hexdigest()

            stem = (
                f"{safe_name(source.name)}-"
                f"page-{page_number:03d}"
            )
            html_path = html_dir / f"{stem}.html"
            screenshot_path = (
                screenshot_dir / f"{stem}.png"
            )

            html_path.write_text(
                html,
                encoding="utf-8",
            )
            page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            json_ld_items = extract_json_ld_items(
                soup,
                source,
                page_number,
                final_url,
            )
            dom_items = extract_dom_items(
                soup,
                source,
                page_number,
                final_url,
            )
            items = merge_items(
                json_ld_items,
                dom_items,
            )

            item_keys = {
                item.gripsweat_item_key
                for item in items
            }

            next_detected = next_page_detected(
                soup,
                page_number,
            )

            page_probe = PageProbe(
                source_name=source.name,
                configured_artist=source.artist,
                page_number=page_number,
                requested_url=requested_url,
                final_url=final_url,
                http_status=status,
                page_title=title,
                redirected=final_url != requested_url,
                html_sha256=digest,
                html_path=str(html_path),
                screenshot_path=str(screenshot_path),
                selector_counts=selector_counts(page),
                next_page_detected=next_detected,
                item_count=len(items),
                items=items,
            )

            summary.pages.append(page_probe)

            print(f"HTTP status : {status}")
            print(f"Final URL   : {final_url}")
            print(f"Title       : {title}")
            print(f"Items       : {len(items)}")
            print(f"Next page   : {next_detected}")
            print(f"HTML        : {html_path}")
            print(f"Screenshot  : {screenshot_path}")

            if digest == previous_digest:
                summary.repeated_pages += 1
                print("Stopping source: repeated HTML digest.")
                break

            if (
                previous_item_keys is not None
                and item_keys
                and item_keys == previous_item_keys
            ):
                summary.repeated_pages += 1
                print("Stopping source: repeated item set.")
                break

            if not items:
                summary.empty_pages += 1
                print("Stopping source: no item records found.")
                break

            summary.pages_accepted += 1
            summary.items_found += len(items)
            previous_digest = digest
            previous_item_keys = item_keys

            if not next_detected:
                print("Stopping source: no next page detected.")
                break

            time.sleep(source.delay_seconds)

        except Exception as exc:
            summary.failures += 1

            error_probe = PageProbe(
                source_name=source.name,
                configured_artist=source.artist,
                page_number=page_number,
                requested_url=requested_url,
                final_url=page.url,
                http_status=None,
                page_title="",
                redirected=page.url != requested_url,
                html_sha256="",
                html_path="",
                screenshot_path="",
                selector_counts={},
                next_page_detected=False,
                item_count=0,
                items=[],
                error=str(exc),
            )

            summary.pages.append(error_probe)

            print(
                f"ERROR {source.name} page {page_number}: "
                f"{exc}",
                file=sys.stderr,
            )
            break


def main() -> int:
    args = parse_args()
    sources = load_sources(args.config)

    selected_names = set(args.sources or [])

    selected = [
        source
        for source in sources
        if source.enabled
        and (
            not selected_names
            or source.name in selected_names
        )
    ]

    if not selected:
        print(
            "No enabled matching Gripsweat sources.",
            file=sys.stderr,
        )
        return 2

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.diagnostic_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary = ProbeSummary(
        started_at=datetime.now().astimezone().isoformat(),
        completed_at=None,
        database_writes=0,
        sources_requested=len(selected),
        pages_loaded=0,
        pages_accepted=0,
        items_found=0,
        repeated_pages=0,
        empty_pages=0,
        failures=0,
    )

    context = browser.context(args.profile)
    page = context.new_page()

    try:
        for source in selected:
            configured_pages = source.max_pages
            max_pages = (
                max(1, args.max_pages)
                if args.max_pages is not None
                else configured_pages
            )

            probe_source(
                page,
                source,
                max_pages=max_pages,
                wait_seconds=max(
                    0.0,
                    args.wait_seconds,
                ),
                diagnostic_dir=args.diagnostic_dir,
                summary=summary,
            )
    finally:
        page.close()

    summary.completed_at = (
        datetime.now().astimezone().isoformat()
    )

    args.output.write_text(
        json.dumps(
            asdict(summary),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("Read-only Gripsweat probe")
    print("-------------------------")
    print(f"Sources requested : {summary.sources_requested}")
    print(f"Pages loaded      : {summary.pages_loaded}")
    print(f"Pages accepted    : {summary.pages_accepted}")
    print(f"Items found       : {summary.items_found}")
    print(f"Repeated pages    : {summary.repeated_pages}")
    print(f"Empty pages       : {summary.empty_pages}")
    print(f"Failures          : {summary.failures}")
    print(f"Database writes   : {summary.database_writes}")
    print(f"Output            : {args.output}")

    successful_sources = {
        page_probe.source_name
        for page_probe in summary.pages
        if page_probe.item_count > 0
        and page_probe.error is None
    }

    missing_sources = {
        source.name
        for source in selected
    } - successful_sources

    if missing_sources:
        print(
            "No usable records for: "
            + ", ".join(sorted(missing_sources)),
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
