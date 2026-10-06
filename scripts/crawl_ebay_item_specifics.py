"""Save eBay About this item grades onto the listing.

Search results only store Used or Pre-Owned. The item page holds Seller
Notes, Sleeve Grading, Obi Grading, and Record Grading. A latest refresh
reads that block for new eBay sales, the same way Buyee reads its sheet.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from auction_etl.browser.ebay_owner import (  # noqa: E402
    EbayOwnerError,
    health,
    owner_socket_path,
)
from auction_etl.database.session import engine  # noqa: E402
from auction_etl.parsers.ebay_item import specifics_from_html  # noqa: E402
from scripts.acquire_ebay_structured import (  # noqa: E402
    EbayAccessBlockedError,
    EbayAcquisitionError,
    EbayAuthenticationRequiredError,
    acquire_page,
)

_MISSING_DESCRIPTION = """
SELECT
    auction.listing_id,
    COALESCE(
        NULLIF(btrim(auction.auction_url), ''),
        'https://www.ebay.com/itm/' || auction.listing_id
    ) AS auction_url
FROM warehouse.auction AS auction
LEFT JOIN warehouse.auction_detail AS detail
  ON detail.marketplace = auction.marketplace
 AND detail.listing_id = auction.listing_id
WHERE auction.marketplace = 'ebay'
  AND (
    detail.description IS NULL
    OR btrim(detail.description) = ''
    OR (
      detail.description !~* 'seller notes'
      AND detail.description !~* 'obi grading'
      AND detail.description !~* 'sleeve grading'
      AND detail.description !~* 'record grading'
      AND detail.description !~* '帯'
    )
  )
ORDER BY auction.listing_id
"""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read eBay item specifics and store the seller condition sheet."
        )
    )
    parser.add_argument("--listing-id", action="append", default=[])
    parser.add_argument(
        "--missing",
        action="store_true",
        help="Read eBay sales whose condition sheet is not stored yet.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args()


def load_candidates(
    listing_ids: tuple[str, ...],
    *,
    missing: bool,
    limit: int,
) -> list[dict[str, str]]:
    """eBay sales that still need the item-page condition sheet."""
    if listing_ids:
        statement = text(
            """
            SELECT
                auction.listing_id,
                COALESCE(
                    NULLIF(btrim(auction.auction_url), ''),
                    'https://www.ebay.com/itm/' || auction.listing_id
                ) AS auction_url
            FROM warehouse.auction AS auction
            WHERE auction.marketplace = 'ebay'
              AND auction.listing_id = ANY(:listing_ids)
            ORDER BY auction.listing_id
            """
        )
        parameters: dict[str, Any] = {"listing_ids": list(listing_ids)}
    elif missing:
        statement = text(_MISSING_DESCRIPTION)
        parameters = {}
    else:
        return []
    with engine.connect() as connection:
        rows = connection.execute(statement, parameters).mappings().all()
    chosen = [dict(row) for row in rows]
    if limit > 0:
        return chosen[:limit]
    return chosen


def save_report(
    *,
    listing_id: str,
    auction_url: str,
    report: str,
    seller_notes: str,
) -> None:
    """Store the sheet. A saved grade sheet is left in place."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_detail (
                    marketplace,
                    listing_id,
                    auction_url,
                    condition_text,
                    description,
                    detail_status,
                    error_message,
                    fetched_at,
                    updated_at
                )
                VALUES (
                    'ebay',
                    :listing_id,
                    :auction_url,
                    NULLIF(:seller_notes, ''),
                    :description,
                    'complete',
                    NULL,
                    now(),
                    now()
                )
                ON CONFLICT (marketplace, listing_id)
                DO UPDATE SET
                    auction_url = COALESCE(
                        EXCLUDED.auction_url,
                        warehouse.auction_detail.auction_url
                    ),
                    condition_text = COALESCE(
                        NULLIF(EXCLUDED.condition_text, ''),
                        warehouse.auction_detail.condition_text
                    ),
                    description = EXCLUDED.description,
                    detail_status = 'complete',
                    error_message = NULL,
                    fetched_at = now(),
                    updated_at = now()
                WHERE btrim(COALESCE(warehouse.auction_detail.description, '')) = ''
                   OR warehouse.auction_detail.description !~* 'sleeve grading|obi grading|record grading|seller notes|帯'
                """
            ),
            {
                "listing_id": listing_id,
                "auction_url": auction_url,
                "seller_notes": seller_notes,
                "description": report,
            },
        )


def save_failure(listing_id: str, auction_url: str, message: str) -> None:
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
                    'ebay',
                    :listing_id,
                    :auction_url,
                    'error',
                    :error_message,
                    now(),
                    now()
                )
                ON CONFLICT (marketplace, listing_id)
                DO UPDATE SET
                    detail_status = CASE
                        WHEN btrim(COALESCE(warehouse.auction_detail.description, '')) = ''
                        THEN 'error'
                        ELSE warehouse.auction_detail.detail_status
                    END,
                    error_message = EXCLUDED.error_message,
                    fetched_at = now(),
                    updated_at = now()
                """
            ),
            {
                "listing_id": listing_id,
                "auction_url": auction_url,
                "error_message": message[:4000],
            },
        )


def read_item_page(url: str, timeout_seconds: float) -> str:
    acquired = acquire_page(
        url=url,
        profile_dir=None,
        storage_state=None,
        headless=False,
        timeout_seconds=timeout_seconds,
        settle_seconds=1.5,
        owner_socket=owner_socket_path(),
    )
    return acquired.html


def main() -> int:
    arguments = parse_arguments()
    listing_ids = tuple(
        item.strip()
        for item in arguments.listing_id
        if item and item.strip()
    )
    if not listing_ids and not arguments.missing:
        print("Pass --listing-id or --missing.")
        return 2
    try:
        health()
    except EbayOwnerError as error:
        print(f"eBay owner is not available: {error}")
        return 1
    candidates = load_candidates(
        listing_ids,
        missing=arguments.missing,
        limit=arguments.limit,
    )
    print("eBay item specifics")
    print("===================")
    print(f"Candidates : {len(candidates)}")
    print(f"Apply      : {arguments.apply}")
    if not candidates:
        print("specifics_saved=0")
        return 0
    saved = 0
    failures = 0
    for index, candidate in enumerate(candidates, start=1):
        listing_id = str(candidate["listing_id"])
        auction_url = str(candidate["auction_url"])
        if index > 1 and arguments.delay > 0:
            time.sleep(arguments.delay)
        try:
            html = read_item_page(auction_url, arguments.timeout)
            parsed = specifics_from_html(html)
            report = str(parsed["report"] or "")
        except (
            EbayAccessBlockedError,
            EbayAuthenticationRequiredError,
            EbayAcquisitionError,
            EbayOwnerError,
        ) as error:
            failures += 1
            message = f"{type(error).__name__}: {error}"
            print(f"[{index}/{len(candidates)}] {listing_id} · {message}")
            if arguments.apply:
                save_failure(listing_id, auction_url, message)
            continue
        if not report:
            print(f"[{index}/{len(candidates)}] {listing_id} · no item specifics")
            continue
        print(f"[{index}/{len(candidates)}] {listing_id}")
        for line in report.splitlines():
            print(f"  {line}")
        if arguments.apply:
            save_report(
                listing_id=listing_id,
                auction_url=auction_url,
                report=report,
                seller_notes=str(parsed["seller_notes"] or ""),
            )
            saved += 1
    print(f"specifics_saved={saved}")
    print(f"specifics_failed={failures}")
    return 1 if failures and saved == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
