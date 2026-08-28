from __future__ import annotations
import os

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.marketplace_access import (
    MarketplaceAccessState,
    classify_ebay_page,
)
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.browser.manager import browser
from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.services.ingest import ingest_raw_page


DEFAULT_CONFIG = Path(os.environ.get("AUCTION_EBAY_SOURCES_CONFIG", "config/ebay_sources.json"))

BLOCK_MARKERS = (
    "pardon our interruption",
    "verify yourself",
    "security measure",
    "captcha",
    "robot check",
    "access denied",
    "please verify",
    "checking your browser",
)

ITEM_SELECTORS = (
    "li.s-item[data-view]",
    "li.s-item",
    "[data-testid='item-card']",
)

ITEM_LINK_SELECTORS = (
    "a[href*='/itm/']",
    "a.s-item__link[href]",
)

NEXT_SELECTORS = (
    "a.pagination__next[href]",
    "a[aria-label='Next page'][href]",
    "a[rel='next'][href]",
)


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    seller: str
    url: str
    profile: str
    enabled: bool
    max_pages: int
    wait_seconds: float
    min_items: int


@dataclass(slots=True)
class CrawlStats:
    sources: int = 0
    pages_loaded: int = 0
    pages_processed: int = 0
    listings_seen: int = 0
    blocked_sources: int = 0
    failed_sources: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl configured eBay completed-listing searches "
            "with persistent browser profiles."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--source",
        help="Run only one configured source.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "Wait for manual login or verification when the first "
            "results page does not initially contain listings."
        ),
    )
    parser.add_argument(
        "--incremental-newest-first",
        action="store_true",
        help=(
            "Stop after a bounded trailing run of warehouse-known "
            "listing IDs. Use only for newest-first source URLs."
        ),
    )
    parser.add_argument(
        "--known-stop-threshold",
        type=int,
        default=20,
        help=(
            "Consecutive warehouse-known IDs required before an "
            "incremental newest-first crawl stops."
        ),
    )
    parser.add_argument(
        "--incremental-stats-file",
        type=Path,
        help="Optional JSON output for incremental counters.",
    )
    return parser.parse_args()


def load_sources(path: Path) -> list[Source]:
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}"
        )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, list):
        raise ValueError(
            "Source config must contain a JSON list."
        )

    sources: list[Source] = []

    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError(
                "Every source entry must be an object."
            )

        name = str(entry["name"])

        sources.append(
            Source(
                name=name,
                seller=str(entry["seller"]),
                url=str(entry["url"]),
                profile=str(
                    entry.get("profile", name)
                ),
                enabled=bool(
                    entry.get("enabled", True)
                ),
                max_pages=max(
                    1,
                    int(entry.get("max_pages", 25)),
                ),
                wait_seconds=max(
                    0.0,
                    float(
                        entry.get(
                            "wait_seconds",
                            4.0,
                        )
                    ),
                ),
                min_items=max(
                    1,
                    int(entry.get("min_items", 1)),
                ),
            )
        )

    return sources


def page_url(
    url: str,
    page_number: int,
) -> str:
    if page_number == 1:
        return url

    parts = urlsplit(url)
    query = dict(
        parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
    )
    query["_pgn"] = str(page_number)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def blocked_reason(
    page: Page,
    title: str,
    current_url: str,
    card_count: int,
) -> str | None:
    if card_count > 0:
        return None

    challenge_selectors = (
        "iframe[src*='captcha']",
        "iframe[title*='captcha' i]",
        "[id*='captcha' i]",
        "[class*='captcha' i]",
        "form[action*='captcha']",
        "[data-testid*='captcha' i]",
    )

    for selector in challenge_selectors:
        try:
            if page.locator(selector).count() > 0:
                return f"challenge element: {selector}"
        except Exception:
            continue

    try:
        visible_text = page.locator("body").inner_text(
            timeout=5_000
        )
    except Exception:
        visible_text = ""

    combined = "\n".join(
        (
            title,
            current_url,
            visible_text[:50_000],
        )
    ).casefold()

    visible_markers = (
        "pardon our interruption",
        "please verify yourself",
        "verify you are human",
        "complete the security check",
        "security measure",
        "robot check",
        "access denied",
        "press and hold",
    )

    for marker in visible_markers:
        if marker in combined:
            return marker

    return None


def listing_count(html: str) -> int:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    item_ids: set[str] = set()

    patterns = (
        re.compile(
            r"/itm/(?:[^/?#]+/)?([0-9]{9,15})(?:[/?#]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"[?&]item=([0-9]{9,15})(?:[&#]|$)",
            re.IGNORECASE,
        ),
    )

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")

        if "/itm/" not in href and "item=" not in href:
            continue

        for pattern in patterns:
            match = pattern.search(href)

            if match:
                item_ids.add(match.group(1))
                break

    return len(item_ids)


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for selector in NEXT_SELECTORS:
        link = soup.select_one(selector)

        if link is None:
            continue

        aria_disabled = str(
            link.get("aria-disabled", "")
        ).casefold()

        classes = {
            str(value).casefold()
            for value in link.get(
                "class",
                [],
            )
        }

        if aria_disabled == "true":
            return False

        if (
            "pagination__next--disabled"
            in classes
        ):
            return False

        if link.get("href"):
            return True

    return False


def wait_for_results(
    page: Page,
    seconds: float,
) -> None:
    timeout_ms = max(
        15_000,
        int(seconds * 1_000),
    )

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    item_links = page.locator(
        "a[href*='/itm/']"
    )

    try:
        item_links.first.wait_for(
            state="attached",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    if item_links.count() > 0:
        page.wait_for_timeout(2_000)
        return

    for _ in range(8):
        page.evaluate(
            "window.scrollBy(0, 1200)"
        )
        page.wait_for_timeout(750)

    page.evaluate(
        "window.scrollTo(0, 0)"
    )
    page.wait_for_timeout(2_000)


def page_payload(
    url: str,
    status: int,
    html: str,
) -> dict[str, Any]:
    return {
        "url": url,
        "status": status,
        "html": html,
        "sha256": hashlib.sha256(
            html.encode("utf-8")
        ).hexdigest(),
    }



def _warehouse_known_ebay_listing_ids(
    session,
) -> set[str]:
    """Return eBay IDs already present in the warehouse."""

    rows = (
        session.connection()
        .exec_driver_sql(
            """
            SELECT listing_id
            FROM warehouse.auction
            WHERE lower(btrim(marketplace)) = 'ebay'
              AND listing_id IS NOT NULL
            """
        )
        .fetchall()
    )

    return {
        str(row[0]).strip()
        for row in rows
        if row[0] is not None
        and str(row[0]).strip()
    }


def _extract_incremental_ebay_listing_ids(
    html: str,
) -> list[str]:
    """Extract ordered unique IDs from eBay item links."""

    import re

    patterns = (
        re.compile(
            r"""(?ix)
            (?:https?:)?//[^"'\s<>]*ebay\.[^"'\s<>]*
            /itm/
            (?:[^/"'\s<>]+/)?
            (?P<id>\d{9,15})
            """
        ),
        re.compile(
            r"""(?ix)
            ["']
            /itm/
            (?:[^/"'\s<>]+/)?
            (?P<id>\d{9,15})
            """
        ),
    )

    positioned: list[
        tuple[int, str]
    ] = []

    for pattern in patterns:
        for match in pattern.finditer(
            html
        ):
            positioned.append(
                (
                    match.start(),
                    match.group(
                        "id"
                    ),
                )
            )

    positioned.sort(
        key=lambda item: item[0]
    )

    seen: set[str] = set()
    result: list[str] = []

    for _position, listing_id in positioned:
        if listing_id in seen:
            continue

        seen.add(
            listing_id
        )
        result.append(
            listing_id
        )

    return result


def _new_incremental_ebay_counters() -> dict[str, object]:
    """Create one incremental counter state."""

    return {
        "discovered": 0,
        "already_known": 0,
        "new": 0,
        "detail_scraped": 0,
        "detail_skipped": 0,
        "discovery_pages": 0,
        "consecutive_known_at_stop": 0,
        "_seen_ids": set(),
        "_consecutive_known": 0,
    }


def _record_incremental_ebay_page(
    counters: dict[str, object],
    listing_ids: list[str],
    known_listing_ids: set[str],
) -> int:
    """Record one page and return its trailing known-ID run."""

    counters[
        "discovery_pages"
    ] = (
        int(
            counters[
                "discovery_pages"
            ]
        )
        + 1
    )

    seen = counters[
        "_seen_ids"
    ]

    if not isinstance(
        seen,
        set,
    ):
        raise RuntimeError(
            "Invalid eBay incremental seen-ID state."
        )

    consecutive_known = int(
        counters[
            "_consecutive_known"
        ]
    )

    for listing_id in listing_ids:
        if listing_id not in seen:
            seen.add(
                listing_id
            )

            counters[
                "discovered"
            ] = (
                int(
                    counters[
                        "discovered"
                    ]
                )
                + 1
            )

            if (
                listing_id
                in known_listing_ids
            ):
                counters[
                    "already_known"
                ] = (
                    int(
                        counters[
                            "already_known"
                        ]
                    )
                    + 1
                )
            else:
                counters[
                    "new"
                ] = (
                    int(
                        counters[
                            "new"
                        ]
                    )
                    + 1
                )

        if (
            listing_id
            in known_listing_ids
        ):
            consecutive_known += 1
        else:
            consecutive_known = 0

    counters[
        "_consecutive_known"
    ] = consecutive_known

    return consecutive_known


def _public_incremental_ebay_counters(
    counters: dict[str, object],
) -> dict[str, int]:
    """Return persisted production counters."""

    new_count = int(
        counters[
            "new"
        ]
    )
    known_count = int(
        counters[
            "already_known"
        ]
    )

    return {
        "discovered": int(
            counters[
                "discovered"
            ]
        ),
        "already_known": known_count,
        "new": new_count,
        "detail_scraped": new_count,
        "detail_skipped": known_count,
        "discovery_pages": int(
            counters[
                "discovery_pages"
            ]
        ),
        "consecutive_known_at_stop": int(
            counters[
                "consecutive_known_at_stop"
            ]
        ),
    }


def _write_incremental_ebay_stats(
    path: Path,
    counters: dict[str, object],
) -> None:
    """Persist eBay incremental counters."""

    import json

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            _public_incremental_ebay_counters(
                counters
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def crawl_source(
    source: Source,
    stats: CrawlStats,
    *,
    interactive: bool = False,
    incremental_newest_first: bool = False,
    known_stop_threshold: int = 20,
    incremental_counters: dict[str, object] | None = None,
) -> None:
    print()
    print(f"Source : {source.name}")
    print(f"Seller : {source.seller}")
    print(f"Profile: {source.profile}")

    context = browser.context(
        source.profile
    )
    page = context.new_page()

    previous_digest: str | None = None
    source_pages = 0
    source_items = 0

    try:
        with SessionLocal() as session:
            known_listing_ids = (
                _warehouse_known_ebay_listing_ids(
                    session
                )
                if incremental_newest_first
                else set()
            )

            source_consecutive_known = 0

            if (
                incremental_newest_first
                and incremental_counters
                is not None
            ):
                incremental_counters[
                    "_consecutive_known"
                ] = 0

            job = CrawlJob(
                source=f"ebay:{source.name}",
                status="running",
            )

            session.add(job)
            session.flush()

            try:
                for page_number in range(
                    1,
                    source.max_pages + 1,
                ):
                    url = page_url(
                        source.url,
                        page_number,
                    )

                    print(
                        f"Loading page "
                        f"{page_number}: {url}"
                    )

                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )

                    stats.pages_loaded += 1

                    status = (
                        response.status
                        if response is not None
                        else None
                    )

                    wait_for_results(
                        page,
                        source.wait_seconds,
                    )

                    html = page.content()
                    title = page.title()
                    current_url = page.url

                    if "signin.ebay." in current_url.casefold():
                        raise RuntimeError(
                            "eBay unexpectedly redirected the anonymous "
                            "completed-search page to sign-in."
                        )

                    try:
                        body = page.locator(
                            "body"
                        ).inner_text(
                            timeout=5_000
                        )
                    except Exception:
                        body = html

                    page_result = classify_ebay_page(
                        status_code=status,
                        title=title,
                        body=body,
                    )

                    if (
                        page_result.state
                        is MarketplaceAccessState.ACCESS_BLOCKED
                    ):
                        stats.blocked_sources += 1

                        diagnostic_dir = Path(
                            "logs"
                        )
                        diagnostic_dir.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        screenshot_path = (
                            diagnostic_dir
                            / f"ebay_block_{source.name}.png"
                        )
                        html_path = (
                            diagnostic_dir
                            / f"ebay_block_{source.name}.html"
                        )

                        page.screenshot(
                            path=str(
                                screenshot_path
                            ),
                            full_page=True,
                        )
                        html_path.write_text(
                            html,
                            encoding="utf-8",
                        )

                        raise RuntimeError(
                            page_result.message
                            + " "
                            + f"Screenshot: {screenshot_path}"
                        )

                    if (
                        page_result.state
                        is MarketplaceAccessState.UNKNOWN_ERROR
                    ):
                        raise RuntimeError(
                            page_result.message
                        )

                    count = listing_count(html)


                    digest = hashlib.sha256(
                        html.encode("utf-8")
                    ).hexdigest()

                    if digest == previous_digest:
                        if page_number == 1:
                            raise RuntimeError(
                                "First page repeated "
                                "unexpectedly."
                            )

                        print(
                            "Stopping: repeated page."
                        )
                        break

                    previous_digest = digest

                    if (
                        count < source.min_items
                        and page_number == 1
                        and interactive
                    ):
                        print()
                        print("No listings are visible yet.")
                        print(
                            "Use the open browser to log in or complete "
                            "normal verification."
                        )
                        print(
                            "Return to the configured Face Records "
                            "completed-sales URL."
                        )
                        print(
                            "Press Enter only after actual listing rows "
                            "are visible."
                        )
                        print()

                        input(
                            "Press Enter after completed listings are visible..."
                        )

                        try:
                            page.wait_for_load_state(
                                "domcontentloaded",
                                timeout=30_000,
                            )
                        except PlaywrightTimeoutError:
                            pass

                        page.wait_for_timeout(5_000)

                        for _ in range(12):
                            page.mouse.wheel(0, 1_200)
                            page.wait_for_timeout(750)

                        page.mouse.wheel(0, -20_000)
                        page.wait_for_timeout(2_000)

                        html = page.content()
                        title = page.title()
                        current_url = page.url
                        count = listing_count(html)

                        print()
                        print(
                            "After manual continuation: "
                            f"title={title!r}"
                        )
                        print(
                            "After manual continuation: "
                            f"url={current_url}"
                        )
                        print(
                            "After manual continuation: "
                            f"items={count}"
                        )

                    if count < source.min_items:
                        diagnostic_dir = Path("logs")
                        diagnostic_dir.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        screenshot_path = (
                            diagnostic_dir
                            / f"ebay_zero_items_{source.name}_"
                            f"page_{page_number}.png"
                        )
                        html_path = (
                            diagnostic_dir
                            / f"ebay_zero_items_{source.name}_"
                            f"page_{page_number}.html"
                        )

                        page.screenshot(
                            path=str(screenshot_path),
                            full_page=True,
                        )
                        html_path.write_text(
                            html,
                            encoding="utf-8",
                        )

                        link_count = page.locator(
                            "a[href]"
                        ).count()

                        item_link_count = page.locator(
                            "a[href*='/itm/']"
                        ).count()

                        print(
                            f"Debug: all links={link_count}, "
                            f"item links={item_link_count}"
                        )
                        print(
                            f"Saved screenshot: {screenshot_path}"
                        )
                        print(
                            f"Saved HTML      : {html_path}"
                        )

                        if page_number == 1:
                            raise RuntimeError(
                                "No valid eBay item IDs found "
                                "on the first page."
                            )

                        print(
                            "Stopping: no additional listings."
                        )
                        break

                    stop_for_known_overlap = False

                    if (
                        incremental_newest_first
                        and incremental_counters
                        is not None
                    ):
                        page_listing_ids = (
                            _extract_incremental_ebay_listing_ids(
                                html
                            )
                        )

                        if page_listing_ids:
                            source_consecutive_known = (
                                _record_incremental_ebay_page(
                                    incremental_counters,
                                    page_listing_ids,
                                    known_listing_ids,
                                )
                            )

                            stop_for_known_overlap = (
                                len(
                                    page_listing_ids
                                )
                                >= known_stop_threshold
                                and source_consecutive_known
                                >= known_stop_threshold
                            )
                        else:
                            print(
                                "Incremental overlap stop was not "
                                "evaluated because no ordered item IDs "
                                "were extracted from this page."
                            )

                    raw = ingest_raw_page(
                        session=session,
                        job=job,
                        page=page_payload(
                            current_url,
                            status,
                            html,
                        ),
                        source="ebay",
                    )

                    session.flush()

                    source_pages += 1
                    source_items += count
                    stats.pages_processed += 1
                    stats.listings_seen += count

                    print(
                        f"Processed raw page "
                        f"{raw.id}; cards: {count}"
                    )

                    if stop_for_known_overlap:
                        if (
                            incremental_counters
                            is not None
                        ):
                            incremental_counters[
                                "consecutive_known_at_stop"
                            ] = max(
                                int(
                                    incremental_counters[
                                        "consecutive_known_at_stop"
                                    ]
                                ),
                                source_consecutive_known,
                            )

                        print(
                            "Stopping incremental eBay discovery: "
                            f"{source_consecutive_known} consecutive "
                            "warehouse-known IDs reached the bounded "
                            "newest-first overlap threshold."
                        )
                        break

                    if not has_next_page(html):
                        print(
                            "Stopping: no enabled "
                            "next-page link."
                        )
                        break

                    time.sleep(
                        source.wait_seconds
                    )

                if source_pages == 0:
                    raise RuntimeError(
                        "No pages were accepted."
                    )

                job.status = "finished"
                session.commit()

            except Exception:
                session.rollback()
                raise

    finally:
        page.close()

    print(
        f"Finished {source.name}: "
        f"{source_pages} page(s), "
        f"{source_items} listing card(s)."
    )


def main() -> int:
    args = parse_args()
    sources = load_sources(args.config)

    selected = [
        source
        for source in sources
        if source.enabled
        and (
            args.source is None
            or source.name == args.source
        )
    ]

    if not selected:
        print(
            "No enabled matching sources.",
            file=sys.stderr,
        )
        return 2

    stats = CrawlStats()
    incremental_counters = (
        _new_incremental_ebay_counters()
    )

    if (
        args.incremental_newest_first
        and args.known_stop_threshold < 1
    ):
        print(
            "--known-stop-threshold must be at least 1.",
            file=sys.stderr,
        )
        return 2

    for source in selected:
        stats.sources += 1

        try:
            crawl_source(
                source,
                stats,
                interactive=args.interactive,
                incremental_newest_first=(
                    args.incremental_newest_first
                ),
                known_stop_threshold=(
                    args.known_stop_threshold
                ),
                incremental_counters=(
                    incremental_counters
                ),
            )
        except Exception as exc:
            stats.failed_sources += 1

            print(
                f"ERROR {source.name}: {exc}",
                file=sys.stderr,
            )

    print()
    print("Crawl summary")
    print("-------------")
    print(
        f"Sources         : {stats.sources}"
    )
    print(
        f"Pages loaded    : {stats.pages_loaded}"
    )
    print(
        f"Pages processed : {stats.pages_processed}"
    )
    print(
        f"Cards seen      : {stats.listings_seen}"
    )
    print(
        f"Blocked         : {stats.blocked_sources}"
    )
    print(
        f"Failed          : {stats.failed_sources}"
    )

    if args.incremental_newest_first:
        incremental_public = (
            _public_incremental_ebay_counters(
                incremental_counters
            )
        )

        print()
        print("Incremental eBay counters")
        print("-------------------------")

        for key, value in (
            incremental_public.items()
        ):
            print(
                f"{key}={value}"
            )

        if (
            args.incremental_stats_file
            is not None
        ):
            _write_incremental_ebay_stats(
                args.incremental_stats_file,
                incremental_counters,
            )

    if (
        stats.blocked_sources
        or stats.failed_sources
        or stats.pages_processed == 0
    ):
        print(
            "Crawl failed; reports will "
            "not be refreshed.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
