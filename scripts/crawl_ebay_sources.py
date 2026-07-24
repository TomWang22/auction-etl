from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.browser.manager import browser
from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.services.ingest import ingest_raw_page


DEFAULT_CONFIG = Path("config/ebay_sources.json")

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

    try:
        page.locator(
            "a[href*='/itm/']"
        ).first.wait_for(
            state="attached",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    for _ in range(8):
        page.mouse.wheel(
            0,
            1_200,
        )
        page.wait_for_timeout(750)

    page.mouse.wheel(
        0,
        -10_000,
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


def crawl_source(
    source: Source,
    stats: CrawlStats,
    *,
    interactive: bool = False,
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
                        else 0
                    )

                    if status in {
                        401,
                        403,
                        429,
                        503,
                    }:
                        stats.blocked_sources += 1

                        raise RuntimeError(
                            f"Blocked HTTP status "
                            f"{status}"
                        )

                    if status >= 400:
                        raise RuntimeError(
                            f"HTTP status {status}"
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

                    count = listing_count(html)

                    reason = blocked_reason(
                        page,
                        title,
                        current_url,
                        count,
                    )

                    if reason:
                        stats.blocked_sources += 1

                        diagnostic_dir = Path("logs")
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
                            path=str(screenshot_path),
                            full_page=True,
                        )
                        html_path.write_text(
                            html,
                            encoding="utf-8",
                        )

                        raise RuntimeError(
                            "Verification or block page "
                            f"detected: {reason}. "
                            f"Screenshot: {screenshot_path}"
                        )

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

    for source in selected:
        stats.sources += 1

        try:
            crawl_source(
                source,
                stats,
                interactive=args.interactive,
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
