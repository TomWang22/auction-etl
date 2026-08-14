"""Read-only audit of Gripsweat search-result pagination."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.browser.manager import browser


DEFAULT_CONFIG = Path("config/gripsweat_sources.json")
DEFAULT_OUTPUT = Path(
    "logs/gripsweat/pagination-audit/"
    "gripsweat_pagination_audit.json"
)
DEFAULT_DIAGNOSTICS = Path(
    "logs/gripsweat/pagination-audit"
)


@dataclass(frozen=True, slots=True)
class Source:
    """One configured Gripsweat artist search."""

    name: str
    artist: str
    query: str
    url_template: str
    enabled: bool
    max_pages: int
    delay_seconds: float


@dataclass(slots=True)
class PageAudit:
    """Observed state for one Gripsweat result page."""

    source_name: str
    artist: str
    requested_page: int
    requested_url: str
    final_url: str | None = None
    final_page_parameter: str | None = None
    http_status: int | None = None
    title: str | None = None
    item_count: int = 0
    unique_item_count: int = 0
    new_item_count: int = 0
    repeated_item_count: int = 0
    repeated_previous_page: bool = False
    repeated_any_page: bool = False
    page_signature: str | None = None
    item_ids: list[str] | None = None
    item_urls: list[str] | None = None
    html_path: str | None = None
    screenshot_path: str | None = None
    error: str | None = None


@dataclass(slots=True)
class SourceAudit:
    """Pagination audit summary for one artist source."""

    source_name: str
    artist: str
    pages_requested: int = 0
    pages_loaded: int = 0
    pages_with_items: int = 0
    total_item_links: int = 0
    unique_item_ids: int = 0
    repeated_item_links: int = 0
    stopped_reason: str | None = None
    pages: list[PageAudit] | None = None


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit Gripsweat pagination without database writes."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--source",
        help="Audit one configured source name.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=10,
        help="Maximum pages to inspect per source.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help=(
            "Override the configured delay between pages."
        ),
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=6.0,
    )
    parser.add_argument(
        "--profile",
        default="gripsweat-audit",
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
        "--empty-page-limit",
        type=int,
        default=2,
        help=(
            "Stop after this many consecutive pages add "
            "no new numeric item IDs."
        ),
    )
    return parser.parse_args()


def load_sources(path: Path) -> list[Source]:
    """Load and validate Gripsweat source configuration."""
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}"
        )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, list):
        raise ValueError(
            "Gripsweat config must contain a JSON list."
        )

    sources: list[Source] = []

    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError(
                "Every Gripsweat source must be an object."
            )

        sources.append(
            Source(
                name=str(entry["name"]),
                artist=str(entry["artist"]),
                query=str(entry["query"]),
                url_template=str(entry["url_template"]),
                enabled=bool(
                    entry.get("enabled", True)
                ),
                max_pages=max(
                    1,
                    int(entry.get("max_pages", 1)),
                ),
                delay_seconds=max(
                    0.0,
                    float(
                        entry.get(
                            "delay_seconds",
                            3.0,
                        )
                    ),
                ),
            )
        )

    return sources


def build_page_url(
    source: Source,
    page_number: int,
) -> str:
    """Build one Gripsweat search URL."""
    if page_number < 1:
        raise ValueError(
            "Page number must be at least one."
        )

    return source.url_template.format(
        query=quote_plus(source.query),
        page=page_number,
    )


def numeric_item_id(url: str) -> str | None:
    """Extract the stable numeric Gripsweat item ID."""
    parsed = urlparse(url)
    segments = [
        segment
        for segment in parsed.path.split("/")
        if segment
    ]

    if len(segments) < 2:
        return None

    try:
        item_position = segments.index("item")
    except ValueError:
        return None

    if item_position + 1 >= len(segments):
        return None

    candidate = segments[item_position + 1]

    if (
        candidate.isdigit()
        and 6 <= len(candidate) <= 20
    ):
        return candidate

    return None


def normalized_item_url(
    url: str,
) -> str | None:
    """Return an absolute Gripsweat item URL."""
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return None

    hostname = (
        parsed.hostname or ""
    ).casefold()

    if hostname not in {
        "gripsweat.com",
        "www.gripsweat.com",
    }:
        return None

    if numeric_item_id(url) is None:
        return None

    return url


def extract_items(
    page: Page,
) -> tuple[list[str], list[str]]:
    """Extract numeric IDs and URLs from the rendered page."""
    links = page.locator(
        "a[href*='/item/']"
    )

    item_urls_by_id: dict[str, str] = {}

    for index in range(links.count()):
        link = links.nth(index)

        try:
            href = link.get_attribute("href")
        except Exception:
            continue

        if not href:
            continue

        absolute_url = page.url

        try:
            absolute_url = link.evaluate(
                """
                element => new URL(
                    element.href,
                    document.baseURI
                ).href
                """
            )
        except Exception:
            if href.startswith("http"):
                absolute_url = href
            elif href.startswith("/"):
                absolute_url = (
                    "https://gripsweat.com"
                    + href
                )
            else:
                continue

        normalized = normalized_item_url(
            str(absolute_url)
        )

        if not normalized:
            continue

        item_id = numeric_item_id(normalized)

        if not item_id:
            continue

        item_urls_by_id.setdefault(
            item_id,
            normalized,
        )

    item_ids = sorted(item_urls_by_id)
    item_urls = [
        item_urls_by_id[item_id]
        for item_id in item_ids
    ]

    return item_ids, item_urls


def page_parameter(url: str) -> str | None:
    """Return the final page query-string value."""
    query = parse_qs(
        urlparse(url).query
    )
    values = query.get("page")

    if not values:
        return None

    return values[0]


def signature(item_ids: list[str]) -> str:
    """Build a stable signature for a page's item set."""
    payload = "\n".join(item_ids).encode(
        "utf-8"
    )

    return hashlib.sha256(payload).hexdigest()


def save_diagnostics(
    page: Page,
    html: str,
    source: Source,
    page_number: int,
    diagnostics_dir: Path,
) -> tuple[str, str]:
    """Save HTML and a screenshot for one result page."""
    source_dir = (
        diagnostics_dir
        / source.name
    )
    source_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    html_path = (
        source_dir
        / f"page_{page_number:03d}.html"
    )
    screenshot_path = (
        source_dir
        / f"page_{page_number:03d}.png"
    )

    html_path.write_text(
        html,
        encoding="utf-8",
    )

    try:
        page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )
    except Exception as exc:
        screenshot_path = (
            source_dir
            / (
                f"page_{page_number:03d}"
                ".screenshot-error.txt"
            )
        )
        screenshot_path.write_text(
            f"{exc}\n",
            encoding="utf-8",
        )

    return (
        str(html_path),
        str(screenshot_path),
    )


def inspect_page(
    page: Page,
    source: Source,
    page_number: int,
    wait_seconds: float,
    diagnostics_dir: Path,
    seen_ids: set[str],
    previous_signature: str | None,
    seen_signatures: set[str],
) -> PageAudit:
    """Inspect one rendered Gripsweat results page."""
    requested_url = build_page_url(
        source,
        page_number,
    )

    result = PageAudit(
        source_name=source.name,
        artist=source.artist,
        requested_page=page_number,
        requested_url=requested_url,
    )

    try:
        response = page.goto(
            requested_url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        result.http_status = (
            response.status
            if response is not None
            else None
        )
        result.final_url = page.url
        result.final_page_parameter = (
            page_parameter(page.url)
        )

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

        result.title = page.title()

        item_ids, item_urls = extract_items(
            page
        )

        result.item_ids = item_ids
        result.item_urls = item_urls
        result.item_count = len(item_urls)
        result.unique_item_count = len(item_ids)

        current_ids = set(item_ids)
        new_ids = current_ids - seen_ids

        result.new_item_count = len(new_ids)
        result.repeated_item_count = (
            len(current_ids) - len(new_ids)
        )

        current_signature = signature(
            item_ids
        )

        result.page_signature = (
            current_signature
        )
        result.repeated_previous_page = (
            previous_signature
            == current_signature
        )
        result.repeated_any_page = (
            current_signature
            in seen_signatures
        )

        html = page.content()

        (
            result.html_path,
            result.screenshot_path,
        ) = save_diagnostics(
            page,
            html,
            source,
            page_number,
            diagnostics_dir,
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
                source,
                page_number,
                diagnostics_dir,
            )
        except Exception:
            pass

    return result


def print_page_result(
    result: PageAudit,
    cumulative_unique: int,
) -> None:
    """Print one compact pagination result."""
    print()
    print(
        f"Page {result.requested_page}"
    )
    print(
        "  Requested :",
        result.requested_url,
    )
    print(
        "  Final     :",
        result.final_url,
    )
    print(
        "  Page arg  :",
        result.final_page_parameter,
    )
    print(
        "  HTTP      :",
        result.http_status,
    )
    print(
        "  Item IDs  :",
        result.unique_item_count,
    )
    print(
        "  New IDs   :",
        result.new_item_count,
    )
    print(
        "  Repeated  :",
        result.repeated_item_count,
    )
    print(
        "  Cumulative:",
        cumulative_unique,
    )
    print(
        "  Same prev :",
        result.repeated_previous_page,
    )
    print(
        "  Seen page :",
        result.repeated_any_page,
    )

    if result.error:
        print(
            "  Error     :",
            result.error,
        )


def audit_source(
    page: Page,
    source: Source,
    maximum_pages: int,
    wait_seconds: float,
    delay_seconds: float,
    empty_page_limit: int,
    diagnostics_dir: Path,
) -> SourceAudit:
    """Audit sequential pagination for one source."""
    summary = SourceAudit(
        source_name=source.name,
        artist=source.artist,
        pages=[],
    )

    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()
    previous_signature: str | None = None
    consecutive_no_new = 0

    page_limit = min(
        source.max_pages,
        maximum_pages,
    )

    print()
    print("=" * 72)
    print(source.artist)
    print("=" * 72)

    for page_number in range(
        1,
        page_limit + 1,
    ):
        summary.pages_requested += 1

        result = inspect_page(
            page,
            source,
            page_number,
            wait_seconds,
            diagnostics_dir,
            seen_ids,
            previous_signature,
            seen_signatures,
        )

        summary.pages.append(result)

        if result.error:
            summary.stopped_reason = (
                f"page error: {result.error}"
            )
            print_page_result(
                result,
                len(seen_ids),
            )
            break

        summary.pages_loaded += 1
        summary.total_item_links += (
            result.item_count
        )
        summary.repeated_item_links += (
            result.repeated_item_count
        )

        if result.unique_item_count > 0:
            summary.pages_with_items += 1

        current_ids = set(
            result.item_ids or []
        )
        seen_ids.update(current_ids)
        summary.unique_item_ids = len(
            seen_ids
        )

        print_page_result(
            result,
            len(seen_ids),
        )

        if result.unique_item_count == 0:
            consecutive_no_new += 1
        elif result.new_item_count == 0:
            consecutive_no_new += 1
        else:
            consecutive_no_new = 0

        current_signature = (
            result.page_signature
        )

        if result.repeated_previous_page:
            summary.stopped_reason = (
                "current page exactly repeats "
                "the previous page"
            )
            break

        if result.repeated_any_page:
            summary.stopped_reason = (
                "current page exactly repeats "
                "an earlier page"
            )
            break

        if (
            consecutive_no_new
            >= empty_page_limit
        ):
            summary.stopped_reason = (
                f"{consecutive_no_new} consecutive "
                "pages added no new item IDs"
            )
            break

        if current_signature:
            seen_signatures.add(
                current_signature
            )
            previous_signature = (
                current_signature
            )

        if page_number < page_limit:
            time.sleep(
                max(0.0, delay_seconds)
            )

    if summary.stopped_reason is None:
        summary.stopped_reason = (
            "configured audit page limit reached"
        )

    print()
    print("Source summary")
    print("--------------")
    print(
        "Pages loaded :",
        summary.pages_loaded,
    )
    print(
        "Unique IDs   :",
        summary.unique_item_ids,
    )
    print(
        "Repeated IDs :",
        summary.repeated_item_links,
    )
    print(
        "Stopped      :",
        summary.stopped_reason,
    )

    return summary


def main() -> int:
    """Run the read-only pagination audit."""
    args = parse_args()

    sources = [
        source
        for source in load_sources(
            args.config
        )
        if source.enabled
        and (
            args.source is None
            or source.name == args.source
        )
    ]

    if not sources:
        raise SystemExit(
            "No matching enabled Gripsweat sources."
        )

    if args.pages < 1:
        raise SystemExit(
            "--pages must be at least one."
        )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.diagnostics_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("Gripsweat pagination audit")
    print("==========================")
    print("READ ONLY: no database writes.")
    print(
        "Maximum pages per source:",
        args.pages,
    )

    context = browser.context(
        args.profile
    )
    page = context.new_page()

    summaries: list[SourceAudit] = []

    try:
        for source in sources:
            delay = (
                args.delay
                if args.delay is not None
                else source.delay_seconds
            )

            summaries.append(
                audit_source(
                    page,
                    source,
                    args.pages,
                    args.wait_seconds,
                    delay,
                    args.empty_page_limit,
                    args.diagnostics_dir,
                )
            )
    finally:
        page.close()

    payload = {
        "read_only": True,
        "database_writes": False,
        "sources": [
            {
                **asdict(summary),
                "pages": [
                    asdict(page_result)
                    for page_result
                    in summary.pages or []
                ],
            }
            for summary in summaries
        ],
    }

    args.output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("Overall summary")
    print("=" * 72)

    total_unique = sum(
        summary.unique_item_ids
        for summary in summaries
    )
    total_pages = sum(
        summary.pages_loaded
        for summary in summaries
    )

    for summary in summaries:
        print(
            f"{summary.artist:20} "
            f"{summary.pages_loaded:3} page(s) | "
            f"{summary.unique_item_ids:4} unique item IDs | "
            f"{summary.stopped_reason}"
        )

    print()
    print("Loaded pages :", total_pages)
    print("Unique IDs   :", total_unique)
    print("Output       :", args.output)
    print(
        "Diagnostics  :",
        args.diagnostics_dir,
    )
    print("Database     : unchanged")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
