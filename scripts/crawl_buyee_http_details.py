"""Fetch authenticated Buyee auction details directly over HTTPS."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from scripts.buyee_http_session import (
    BLOCK_MARKERS,
    DEFAULT_USER_AGENT,
    LOGIN_MARKERS,
    MAINTENANCE_MARKERS,
    load_buyee_cookie_jar,
    normalize_text,
)
from scripts.crawl_buyee_live_details import (
    BuyeeDetail,
    detect_status,
    ensure_schema,
    line_after_label,
    load_candidates,
    normalize_space,
    parse_integer,
    parse_jst_datetime,
    parse_yen,
    print_result,
    save_detail,
    save_failure,
    serialize_detail,
    text_block_after_label,
)


DEFAULT_STATE_FILE = Path(
    "/data/buyee-profile/.auction-etl/private/buyee-storage-state.json"
)

DEFAULT_LOG_DIR = Path(
    "logs/buyee/http-detail"
)

MAX_RESPONSE_BYTES = 4_000_000


class BuyeeHttpDetailError(RuntimeError):
    """Raised when authenticated Buyee detail HTTPS access fails."""


class BuyeeHtmlDocument(HTMLParser):
    """Extract visible text, headings, and links from Buyee HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._heading_depth = 0
        self._anchor_depth = 0
        self._heading_parts: list[str] = []
        self._anchor_parts: list[str] = []
        self._current_anchor_href = ""

        self.text_fragments: list[str] = []
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.casefold()

        if lowered in {
            "script",
            "style",
            "noscript",
            "template",
        }:
            self._ignored_depth += 1
            return

        if self._ignored_depth:
            return

        if lowered in {
            "h1",
            "h2",
            "h3",
        }:
            self._heading_depth += 1

        if lowered == "a":
            self._anchor_depth += 1
            attributes = dict(attrs)
            self._current_anchor_href = (
                attributes.get("href")
                or ""
            )
            self._anchor_parts = []

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        lowered = tag.casefold()

        if lowered in {
            "script",
            "style",
            "noscript",
            "template",
        }:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return

        if self._ignored_depth:
            return

        if (
            lowered
            in {
                "h1",
                "h2",
                "h3",
            }
            and self._heading_depth
        ):
            self._heading_depth -= 1

            heading = normalize_space(
                " ".join(self._heading_parts)
            )

            if heading:
                self.headings.append(
                    heading
                )

            self._heading_parts = []

        if (
            lowered == "a"
            and self._anchor_depth
        ):
            self._anchor_depth -= 1

            text = normalize_space(
                " ".join(self._anchor_parts)
            )

            if text:
                self.links.append(
                    (
                        self._current_anchor_href,
                        text,
                    )
                )

            self._anchor_parts = []
            self._current_anchor_href = ""

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._ignored_depth:
            return

        for raw_line in data.splitlines():
            value = normalize_space(
                raw_line
            )

            if not value:
                continue

            self.text_fragments.append(
                value
            )

            if self._heading_depth:
                self._heading_parts.append(
                    value
                )

            if self._anchor_depth:
                self._anchor_parts.append(
                    value
                )


def parse_arguments() -> argparse.Namespace:
    """Parse HTTPS detail crawler arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch authenticated Buyee listing details "
            "directly over HTTPS."
        )
    )

    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
    )
    parser.add_argument(
        "--listing-id",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--first-seen-source",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
    )
    parser.add_argument(
        "--limit",
        type=int,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
    )

    arguments = parser.parse_args()

    if (
        arguments.limit is not None
        and arguments.limit < 1
    ):
        parser.error(
            "--limit must be at least 1."
        )

    if arguments.delay < 0:
        parser.error(
            "--delay cannot be negative."
        )

    if arguments.timeout <= 0:
        parser.error(
            "--timeout must be positive."
        )

    return arguments


def build_authenticated_opener(
    state_file: Path,
) -> urllib.request.OpenerDirector:
    """Build one reusable authenticated Buyee HTTPS opener."""
    jar = load_buyee_cookie_jar(
        state_file
    )

    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(
            jar
        )
    )


def fetch_detail_html(
    *,
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout_seconds: float,
) -> tuple[
    int,
    str,
    str,
]:
    """Fetch one authenticated Buyee detail page."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
        },
    )

    try:
        with opener.open(
            request,
            timeout=timeout_seconds,
        ) as response:
            status_code = int(
                response.status
            )
            final_url = response.geturl()
            body = response.read(
                MAX_RESPONSE_BYTES
            ).decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as error:
        status_code = int(
            error.code
        )
        final_url = error.geturl()
        body = error.read(
            MAX_RESPONSE_BYTES
        ).decode(
            "utf-8",
            errors="replace",
        )

    except (
        urllib.error.URLError,
        TimeoutError,
    ) as error:
        raise BuyeeHttpDetailError(
            f"Buyee HTTPS request failed for {url}."
        ) from error

    normalized_url = final_url.casefold()
    normalized_body = normalize_text(
        body
    )

    if (
        status_code
        in {
            401,
            403,
            429,
        }
        or any(
            marker in normalized_body
            for marker in BLOCK_MARKERS
        )
    ):
        raise BuyeeHttpDetailError(
            "Buyee HTTPS detail access was blocked: "
            f"HTTP {status_code} {final_url}"
        )

    if any(
        marker in normalized_url
        for marker in LOGIN_MARKERS
    ):
        raise BuyeeHttpDetailError(
            "Buyee HTTPS authentication expired."
        )

    if any(
        marker in normalized_body
        for marker in MAINTENANCE_MARKERS
    ):
        raise BuyeeHttpDetailError(
            "Buyee maintenance page returned."
        )

    if status_code >= 400:
        raise BuyeeHttpDetailError(
            f"HTTP {status_code} for {final_url}"
        )

    if not body.strip():
        raise BuyeeHttpDetailError(
            f"Empty Buyee detail response for {final_url}."
        )

    return (
        status_code,
        final_url,
        body,
    )


def seller_from_links(
    document: BuyeeHtmlDocument,
) -> str | None:
    """Return the most likely seller link text."""
    for href, text in document.links:
        lowered = href.casefold()

        if (
            "seller" in lowered
            or "user" in lowered
        ):
            return text

    return None


def extract_detail_from_html(
    *,
    html: str,
    listing_id: str,
    auction_url: str,
) -> BuyeeDetail:
    """Extract Buyee auction telemetry from server-rendered HTML."""
    document = BuyeeHtmlDocument()
    document.feed(
        html
    )
    document.close()

    lines = document.text_fragments
    body_text = "\n".join(
        lines
    )

    if not body_text.strip():
        raise BuyeeHttpDetailError(
            "Buyee detail HTML contained no visible text."
        )

    title = (
        document.headings[0]
        if document.headings
        else None
    )

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
        seller_name = seller_from_links(
            document
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

    if (
        "price including tax"
        in combined_price_text.casefold()
    ):
        tax_included = True
    elif combined_price_text:
        tax_included = False

    detail = BuyeeDetail(
        marketplace="buyee",
        listing_id=listing_id,
        auction_url=auction_url,
        title=title,
        seller_name=seller_name,
        auction_status=detect_status(
            body_text
        ),
        opening_at=parse_jst_datetime(
            opening_text
        ),
        closing_at=parse_jst_datetime(
            closing_text
        ),
        starting_price=parse_yen(
            starting_text
        ),
        current_price_gross=parse_yen(
            current_text
        ),
        buyout_price_gross=parse_yen(
            buyout_text
        ),
        bid_count=parse_integer(
            bid_text
        ),
        condition_text=condition_text,
        currency=(
            "JPY"
            if (
                "YEN" in body_text.upper()
                or "¥" in body_text
                or "JPY" in body_text.upper()
            )
            else None
        ),
        tax_included=tax_included,
        fetched_at=datetime.now(
            timezone.utc
        ),
        detail_status="complete",
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
        raise BuyeeHttpDetailError(
            "Buyee HTTPS detail page yielded no auction telemetry."
        )

    if (
        detail.opening_at is None
        or detail.closing_at is None
        or detail.starting_price is None
    ):
        detail.detail_status = (
            "partial"
        )

    return detail


def crawl_candidate(
    *,
    opener: urllib.request.OpenerDirector,
    listing_id: str,
    auction_url: str,
    log_dir: Path,
    timeout_seconds: float,
) -> BuyeeDetail:
    """Fetch, persist diagnostics, and extract one detail page."""
    _, final_url, html = fetch_detail_html(
        opener=opener,
        url=auction_url,
        timeout_seconds=timeout_seconds,
    )

    item_dir = (
        log_dir
        / listing_id
    )

    item_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        item_dir
        / "page.html"
    ).write_text(
        html,
        encoding="utf-8",
    )

    detail = extract_detail_from_html(
        html=html,
        listing_id=listing_id,
        auction_url=final_url,
    )

    (
        item_dir
        / "detail.json"
    ).write_text(
        json.dumps(
            serialize_detail(
                detail
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return detail


def main() -> int:
    """Run authenticated Buyee detail enrichment over HTTPS."""
    arguments = parse_arguments()

    state_file = (
        arguments.state_file
        .expanduser()
        .resolve()
    )

    if not state_file.is_file():
        raise BuyeeHttpDetailError(
            "Buyee authenticated storage state is missing: "
            f"{state_file}"
        )

    arguments.log_dir.mkdir(
        parents=True,
        exist_ok=True,
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
    print(
        "Buyee HTTPS detail crawl"
    )
    print(
        "========================"
    )
    print(
        f"Candidates : {len(candidates)}"
    )
    print(
        f"Apply      : {arguments.apply}"
    )
    print(
        f"Refresh    : {arguments.refresh}"
    )
    print(
        f"State      : {state_file}"
    )
    print(
        f"Diagnostics: {arguments.log_dir}"
    )

    if not candidates:
        print()
        print(
            "No matching Buyee listings require enrichment."
        )
        return 0

    opener = build_authenticated_opener(
        state_file
    )

    results: list[
        dict[str, Any]
    ] = []

    failures = 0

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
                opener=opener,
                listing_id=listing_id,
                auction_url=auction_url,
                log_dir=arguments.log_dir,
                timeout_seconds=arguments.timeout,
            )

            print_result(
                index,
                len(candidates),
                detail,
            )

            results.append(
                serialize_detail(
                    detail
                )
            )

            if arguments.apply:
                save_detail(
                    detail
                )

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
            print(
                message
            )

            results.append(
                {
                    "marketplace": "buyee",
                    "listing_id": listing_id,
                    "auction_url": auction_url,
                    "detail_status": "error",
                    "error_message": message,
                }
            )

            if arguments.apply:
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
    print(
        "Crawl summary"
    )
    print(
        "============="
    )
    print(
        f"Processed: {len(results)}"
    )
    print(
        f"Failures : {failures}"
    )
    print(
        f"Summary  : {summary_path}"
    )

    if not arguments.apply:
        print()
        print(
            "DRY RUN ONLY"
        )

    return (
        1
        if failures
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
