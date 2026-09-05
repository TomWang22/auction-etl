#!/usr/bin/env python3
"""Probe anonymous eBay sold search without touching PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit


ROOT = Path(
    __file__
).resolve().parents[1]

if str(
    ROOT
) not in sys.path:
    sys.path.insert(
        0,
        str(
            ROOT
        ),
    )

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from auction_etl.services.marketplace_browser_runtime import browser
from scripts.marketplace_access import (
    MarketplaceAccessState,
    classify_ebay_page,
)


NAVIGATION_TIMEOUT_MS = 25_000
RESULT_TIMEOUT_MS = 8_000
PROFILE = "ebay-public"

ITEM_PATTERNS = (
    re.compile(
        r"""
        /itm/
        (?:[^/?#"'<>\\s]+/)?
        (?P<item_id>[0-9]{9,15})
        (?=[/?#"'<>\\s]|$)
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        [?&]item=
        (?P<item_id>[0-9]{9,15})
        (?=[&#"'<>\\s]|$)
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(
        description=(
            "Probe anonymous eBay sold/completed "
            "search through the production browser runtime."
        )
    )

    parser.add_argument(
        "--query",
        default="teresa teng",
        help="Artist/search phrase. Default: %(default)s",
    )

    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
    )

    arguments = parser.parse_args()

    if not arguments.query.strip():
        parser.error(
            "--query cannot be empty."
        )

    if arguments.sample_size < 1:
        parser.error(
            "--sample-size must be at least 1."
        )

    return arguments


def build_url(
    query: str,
) -> str:
    """Build one anonymous sold/completed eBay search URL."""

    return (
        "https://www.ebay.com/sch/i.html?"
        + urlencode(
            {
                "_nkw": query.strip(),
                "LH_Complete": "1",
                "LH_Sold": "1",
                "_sop": "13",
            }
        )
    )


def extract_item_ids(
    html: str,
) -> list[str]:
    """Extract ordered unique eBay item IDs."""

    positioned: list[
        tuple[int, str]
    ] = []

    for pattern in ITEM_PATTERNS:
        for match in pattern.finditer(
            html
        ):
            positioned.append(
                (
                    match.start(),
                    match.group(
                        "item_id"
                    ),
                )
            )

    positioned.sort(
        key=lambda value: value[0]
    )

    seen: set[str] = set()
    result: list[str] = []

    for _, item_id in positioned:
        if item_id in seen:
            continue

        seen.add(
            item_id
        )

        result.append(
            item_id
        )

    return result


def is_signin_url(
    url: str,
) -> bool:
    """Detect an unexpected eBay sign-in redirect."""

    parsed = urlsplit(
        url
    )

    hostname = (
        parsed.hostname
        or ""
    ).casefold()

    path = parsed.path.casefold()
    query = parsed.query.casefold()

    return (
        "signin.ebay." in hostname
        or "/signin" in path
        or (
            "ebayisapi.dll" in path
            and "signin" in query
        )
    )


def main() -> int:
    """Run one anonymous browser-access probe."""

    arguments = parse_arguments()

    requested_url = build_url(
        arguments.query
    )

    os.environ[
        "AUCTION_MARKETPLACE_BROWSER_MODE"
    ] = "ephemeral"

    os.environ.pop(
        "AUCTION_EBAY_STORAGE_STATE_B64",
        None,
    )

    context = browser.context(
        PROFILE
    )

    page = context.new_page()

    page.set_default_timeout(
        RESULT_TIMEOUT_MS
    )

    page.set_default_navigation_timeout(
        NAVIGATION_TIMEOUT_MS
    )

    response = None
    navigation_timeout = False

    try:
        try:
            response = page.goto(
                requested_url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            navigation_timeout = True

        try:
            page.locator(
                "a[href*='/itm/']"
            ).first.wait_for(
                state="attached",
                timeout=RESULT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            pass

        final_url = page.url
        title = page.title()

        try:
            body = page.locator(
                "body"
            ).inner_text(
                timeout=5_000
            )
        except Exception:
            body = ""

        html = page.content()

        item_ids = extract_item_ids(
            html
        )

        status = (
            response.status
            if response is not None
            else None
        )

        classification = classify_ebay_page(
            status_code=status,
            title=title,
            body=body,
            listing_count=len(
                item_ids
            ),
        )

        if is_signin_url(
            final_url
        ):
            result = (
                "SIGNIN_REDIRECT"
            )
            exit_code = 3

        elif (
            classification.state
            is MarketplaceAccessState.ACCESS_BLOCKED
        ):
            result = (
                "ACCESS_BLOCKED"
            )
            exit_code = 2

        elif (
            classification.state
            is MarketplaceAccessState.AVAILABLE
            and item_ids
        ):
            result = "PASS"
            exit_code = 0

        else:
            result = (
                "NO_RESULTS"
            )
            exit_code = 4

        print(
            json.dumps(
                {
                    "result": result,
                    "query": arguments.query.strip(),
                    "requested_url": requested_url,
                    "final_url": final_url,
                    "http_status": status,
                    "navigation_timeout": navigation_timeout,
                    "classifier_state": classification.state.value,
                    "classifier_message": classification.message,
                    "item_count": len(
                        item_ids
                    ),
                    "sample_item_ids": item_ids[
                        : arguments.sample_size
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )

        return exit_code

    except Exception as exc:
        print(
            json.dumps(
                {
                    "result": "PROBE_ERROR",
                    "error_type": type(
                        exc
                    ).__name__,
                    "message": str(
                        exc
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )

        return 5

    finally:
        try:
            page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
