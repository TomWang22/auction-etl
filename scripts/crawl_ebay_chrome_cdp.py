from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.services.ingest import ingest_raw_page


DEFAULT_URL = (
    "https://www.ebay.com/sch/i.html?"
    "_dkr=1"
    "&iconV2Request=true"
    "&_blrs=recall_filtering"
    "&_ssn=facerecords"
    "&store_cat=0"
    "&store_name=facerecords"
    "&_oac=1"
    "&_nkw=teresa+teng"
    "&rt=nc"
    "&LH_Complete=1"
)

CHROME_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT = 9223
DEBUG_ENDPOINT = f"http://127.0.0.1:{DEBUG_PORT}/json/version"

ITEM_PATTERNS = (
    re.compile(
        r"/itm/(?:[^/?#]+/)?([0-9]{9,15})(?:[/?#]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"[?&]item=([0-9]{9,15})(?:[&#]|$)",
        re.IGNORECASE,
    ),
)

BLOCK_MARKERS = (
    "pardon our interruption",
    "verify you are human",
    "please verify yourself",
    "complete the security check",
    "access denied",
    "press and hold",
)


@dataclass(slots=True)
class CrawlStats:
    pages_seen: int = 0
    pages_accepted: int = 0
    cards_seen: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl eBay completed listings through installed Google Chrome."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path("profiles/chrome-cdp-facerecords"),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="Maximum time to wait for real result links.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
    )
    return parser.parse_args()


def build_page_url(
    base_url: str,
    page_number: int,
) -> str:
    if page_number == 1:
        return base_url

    parts = urlsplit(base_url)

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


def extract_item_ids(
    html: str,
) -> set[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    item_ids: set[str] = set()

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")

        for pattern in ITEM_PATTERNS:
            match = pattern.search(href)

            if match:
                item_ids.add(match.group(1))
                break

    return item_ids


def visible_block_reason(
    page: Page,
) -> str | None:
    try:
        body_text = page.locator("body").inner_text(
            timeout=5_000
        )
    except Exception:
        body_text = ""

    combined = "\n".join(
        (
            page.title(),
            page.url,
            body_text[:50_000],
        )
    ).casefold()

    for marker in BLOCK_MARKERS:
        if marker in combined:
            return marker

    return None


def has_next_page(
    html: str,
) -> bool:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    selectors = (
        "a.pagination__next[href]",
        "a[aria-label='Next page'][href]",
        "a[rel='next'][href]",
    )

    for selector in selectors:
        link = soup.select_one(selector)

        if link is None:
            continue

        if str(
            link.get("aria-disabled", "")
        ).casefold() == "true":
            return False

        classes = {
            str(value).casefold()
            for value in link.get("class", [])
        }

        if "pagination__next--disabled" in classes:
            return False

        return bool(link.get("href"))

    return False


def launch_chrome(
    profile_dir: Path,
    url: str,
) -> subprocess.Popen[bytes]:
    profile_dir = profile_dir.resolve()
    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        [
            "pkill",
            "-f",
            str(profile_dir),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(2)

    command = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--new-window",
        url,
    ]

    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_debug_endpoint(
    timeout: int = 30,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                DEBUG_ENDPOINT,
                timeout=2,
            ) as response:
                payload = json.load(response)

            if payload.get("webSocketDebuggerUrl"):
                return

        except Exception:
            time.sleep(1)

    raise RuntimeError(
        "Google Chrome DevTools endpoint did not become available."
    )


def wait_for_listing_results(
    page: Page,
    exact_url: str,
    timeout_seconds: int,
) -> tuple[str, set[str]]:
    deadline = time.monotonic() + timeout_seconds
    last_url = ""

    while time.monotonic() < deadline:
        current_url = page.url

        if "signin.ebay." in current_url.casefold():
            if current_url != last_url:
                print()
                print("Chrome was redirected to eBay sign-in.")
                print("Do not enter credentials.")
                print(
                    "Replace the address bar with the exact Face Records URL:"
                )
                print(exact_url)
                print()
                last_url = current_url

        try:
            html = page.content()
        except Exception:
            page.wait_for_timeout(1_000)
            continue

        item_ids = extract_item_ids(html)

        if item_ids:
            return html, item_ids

        reason = visible_block_reason(page)

        if reason:
            print(
                f"Waiting through visible eBay challenge: {reason}"
            )

        page.wait_for_timeout(2_000)

    diagnostic_dir = Path("logs")
    diagnostic_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    screenshot = (
        diagnostic_dir
        / "ebay_chrome_cdp_no_results.png"
    )
    html_path = (
        diagnostic_dir
        / "ebay_chrome_cdp_no_results.html"
    )

    page.screenshot(
        path=str(screenshot),
        full_page=True,
    )

    html_path.write_text(
        page.content(),
        encoding="utf-8",
    )

    raise RuntimeError(
        "No eBay item links appeared before timeout. "
        f"Screenshot: {screenshot}"
    )


def page_payload(
    page: Page,
    html: str,
) -> dict[str, Any]:
    return {
        "url": page.url,
        "status": 200,
        "html": html,
        "sha256": hashlib.sha256(
            html.encode("utf-8")
        ).hexdigest(),
    }


def choose_page(
    browser_context,
    expected_url: str,
) -> Page:
    pages = browser_context.pages

    for page in pages:
        if "ebay." in page.url.casefold():
            return page

    page = browser_context.new_page()
    page.goto(
        expected_url,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    return page


def crawl(
    url: str,
    profile_dir: Path,
    max_pages: int,
    wait_seconds: int,
    delay: float,
) -> CrawlStats:
    stats = CrawlStats()
    chrome_process = launch_chrome(
        profile_dir,
        url,
    )

    try:
        wait_for_debug_endpoint()

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{DEBUG_PORT}"
            )

            if not browser.contexts:
                raise RuntimeError(
                    "Chrome exposed no browser context."
                )

            context = browser.contexts[0]
            page = choose_page(
                context,
                url,
            )

            with SessionLocal() as session:
                job = CrawlJob(
                    source="ebay:facerecords:chrome",
                    status="running",
                )

                session.add(job)
                session.flush()

                try:
                    previous_ids: set[str] | None = None

                    for page_number in range(
                        1,
                        max_pages + 1,
                    ):
                        target_url = build_page_url(
                            url,
                            page_number,
                        )

                        print()
                        print(
                            f"Loading Face Records page {page_number}"
                        )
                        print(target_url)

                        if page.url != target_url:
                            page.goto(
                                target_url,
                                wait_until="domcontentloaded",
                                timeout=120_000,
                            )

                        stats.pages_seen += 1

                        html, item_ids = wait_for_listing_results(
                            page,
                            target_url,
                            wait_seconds,
                        )

                        if previous_ids == item_ids:
                            print(
                                "Stopping: repeated listing set."
                            )
                            break

                        previous_ids = item_ids

                        raw = ingest_raw_page(
                            session=session,
                            job=job,
                            page=page_payload(
                                page,
                                html,
                            ),
                            source="ebay",
                        )

                        session.flush()

                        stats.pages_accepted += 1
                        stats.cards_seen += len(item_ids)

                        print(
                            f"Accepted raw page {raw.id}; "
                            f"unique item IDs: {len(item_ids)}"
                        )

                        if not has_next_page(html):
                            print(
                                "Stopping: no enabled next-page link."
                            )
                            break

                        time.sleep(max(delay, 0.0))

                    if stats.pages_accepted == 0:
                        raise RuntimeError(
                            "No eBay pages were accepted."
                        )

                    job.status = "finished"
                    session.commit()

                except Exception:
                    session.rollback()
                    raise

            browser.close()

    finally:
        if chrome_process.poll() is None:
            chrome_process.terminate()

    return stats


def main() -> int:
    args = parse_args()

    if args.max_pages < 1:
        print(
            "--max-pages must be at least 1.",
            file=sys.stderr,
        )
        return 2

    try:
        stats = crawl(
            url=args.url,
            profile_dir=args.profile_dir,
            max_pages=args.max_pages,
            wait_seconds=args.wait_seconds,
            delay=args.delay,
        )
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print("Chrome crawl summary")
    print("--------------------")
    print(f"Pages seen     : {stats.pages_seen}")
    print(f"Pages accepted : {stats.pages_accepted}")
    print(f"Item IDs seen  : {stats.cards_seen}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
