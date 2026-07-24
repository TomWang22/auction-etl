from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from auction_etl.browser.manager import browser
from auction_etl.database.session import engine


JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")

DATETIME_FORMATS = (
    "%d %b %Y %H:%M:%S",
    "%d %B %Y %H:%M:%S",
    "%b %d, %Y %H:%M:%S",
    "%B %d, %Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)

FIELD_PATTERNS = {
    "auction_id": (
        re.compile(
            r"Auction\s+ID\s*[\r\n:]*\s*([A-Za-z0-9_-]+)",
            re.IGNORECASE,
        ),
    ),
    "opening_time": (
        re.compile(
            r"Opening\s+Time\s*\(JST\)\s*[\r\n:]*\s*"
            r"([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}\s+"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2})",
            re.IGNORECASE,
        ),
        re.compile(
            r"Opening\s+Time\s*\(JST\)\s*[\r\n:]*\s*"
            r"([A-Za-z]+\s+[0-9]{1,2},\s+[0-9]{4}\s+"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2})",
            re.IGNORECASE,
        ),
    ),
    "closing_time": (
        re.compile(
            r"Closing\s+Time\s*\(JST\)\s*[\r\n:]*\s*"
            r"([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}\s+"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2})",
            re.IGNORECASE,
        ),
        re.compile(
            r"Closing\s+Time\s*\(JST\)\s*[\r\n:]*\s*"
            r"([A-Za-z]+\s+[0-9]{1,2},\s+[0-9]{4}\s+"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2})",
            re.IGNORECASE,
        ),
    ),
    "starting_price": (
        re.compile(
            r"Starting\s+Price\s*[\r\n:]*\s*"
            r"([0-9][0-9,]*)\s*YEN",
            re.IGNORECASE,
        ),
    ),
    "bid_count": (
        re.compile(
            r"Number\s+of\s+Bids\s*[\r\n:]*\s*"
            r"([0-9][0-9,]*)",
            re.IGNORECASE,
        ),
    ),
    "seller": (
        re.compile(
            r"Seller\s*[\r\n:]+\s*([^\r\n]+)",
            re.IGNORECASE,
        ),
    ),
    "condition": (
        re.compile(
            r"Item\s+Condition\s*[\r\n:]+\s*([^\r\n]+)",
            re.IGNORECASE,
        ),
    ),
    "current_price": (
        re.compile(
            r"Current\s+Price\s*[\r\n:]*\s*"
            r"([0-9][0-9,]*)\s*YEN",
            re.IGNORECASE,
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Buyee detail-page field probe."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--profile",
        default="anonymous",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=8.0,
    )
    parser.add_argument(
        "--listing-id",
        help="Inspect one specific Buyee listing ID.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/buyee_detail_probe.json"),
    )
    return parser.parse_args()


def normalize_visible_text(value: str) -> str:
    lines = []

    for line in value.replace("\xa0", " ").splitlines():
        cleaned = " ".join(line.split())

        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines)


def match_field(
    visible_text: str,
    field: str,
) -> str | None:
    for pattern in FIELD_PATTERNS[field]:
        match = pattern.search(visible_text)

        if match is not None:
            return match.group(1).strip()

    return None


def parse_integer(value: str | None) -> int | None:
    if value is None:
        return None

    return int(value.replace(",", ""))


def parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(value.replace(",", ""))


def parse_jst_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None

    for format_string in DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(
                value,
                format_string,
            )
            return parsed.replace(tzinfo=JST)
        except ValueError:
            continue

    return None


def serialize_datetime(
    value: datetime | None,
) -> dict[str, str | None]:
    if value is None:
        return {
            "jst": None,
            "utc": None,
            "new_york": None,
        }

    return {
        "jst": value.isoformat(),
        "utc": value.astimezone(UTC).isoformat(),
        "new_york": value.astimezone(NEW_YORK).isoformat(),
    }


def load_rows(
    limit: int,
    listing_id: str | None,
) -> list[dict[str, Any]]:
    if listing_id:
        statement = text(
            """
            SELECT
                id,
                listing_id,
                auction_url,
                title,
                seller,
                bid_count,
                start_price,
                final_price,
                tax_amount,
                gross_price,
                currency,
                ended_at
            FROM warehouse.auction
            WHERE marketplace = 'buyee'
              AND listing_id = :listing_id
            LIMIT 1
            """
        )
        parameters = {
            "listing_id": listing_id,
        }
    else:
        statement = text(
            """
            SELECT
                id,
                listing_id,
                auction_url,
                title,
                seller,
                bid_count,
                start_price,
                final_price,
                tax_amount,
                gross_price,
                currency,
                ended_at
            FROM warehouse.auction
            WHERE marketplace = 'buyee'
              AND auction_url IS NOT NULL
              AND auction_url <> ''
            ORDER BY
                ended_at DESC NULLS LAST,
                id DESC
            LIMIT :limit
            """
        )
        parameters = {
            "limit": limit,
        }

    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            parameters,
        ).mappings().all()

    return [dict(row) for row in rows]


def inspect_row(
    page,
    row: dict[str, Any],
    wait_seconds: float,
) -> dict[str, Any]:
    response = page.goto(
        row["auction_url"],
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    page.wait_for_timeout(
        max(2_000, int(wait_seconds * 1_000))
    )

    try:
        page.wait_for_selector(
            "text=Auction ID",
            timeout=30_000,
        )
    except Exception:
        pass

    visible_text = normalize_visible_text(
        page.locator("body").inner_text(
            timeout=15_000
        )
    )

    diagnostic_dir = Path("logs/buyee-detail")
    diagnostic_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    text_path = (
        diagnostic_dir
        / f"{row['listing_id']}.txt"
    )
    html_path = (
        diagnostic_dir
        / f"{row['listing_id']}.html"
    )
    screenshot_path = (
        diagnostic_dir
        / f"{row['listing_id']}.png"
    )

    text_path.write_text(
        visible_text + "\n",
        encoding="utf-8",
    )
    html_path.write_text(
        page.content(),
        encoding="utf-8",
    )
    page.screenshot(
        path=str(screenshot_path),
        full_page=True,
    )

    opening_text = match_field(
        visible_text,
        "opening_time",
    )
    closing_text = match_field(
        visible_text,
        "closing_time",
    )

    opening_jst = parse_jst_datetime(
        opening_text
    )
    closing_jst = parse_jst_datetime(
        closing_text
    )

    starting_price_text = match_field(
        visible_text,
        "starting_price",
    )
    current_price_text = match_field(
        visible_text,
        "current_price",
    )
    bid_count_text = match_field(
        visible_text,
        "bid_count",
    )

    return {
        "warehouse_id": row["id"],
        "listing_id": row["listing_id"],
        "requested_url": row["auction_url"],
        "final_url": page.url,
        "page_title": page.title(),
        "http_status": (
            response.status
            if response is not None
            else None
        ),
        "detail": {
            "auction_id": match_field(
                visible_text,
                "auction_id",
            ),
            "seller": match_field(
                visible_text,
                "seller",
            ),
            "condition": match_field(
                visible_text,
                "condition",
            ),
            "bid_count": parse_integer(
                bid_count_text
            ),
            "starting_price_jpy": (
                str(parse_decimal(starting_price_text))
                if starting_price_text is not None
                else None
            ),
            "current_price_jpy": (
                str(parse_decimal(current_price_text))
                if current_price_text is not None
                else None
            ),
            "opening_time": serialize_datetime(
                opening_jst
            ),
            "closing_time": serialize_datetime(
                closing_jst
            ),
            "raw": {
                "bid_count": bid_count_text,
                "starting_price": starting_price_text,
                "current_price": current_price_text,
                "opening_time": opening_text,
                "closing_time": closing_text,
            },
        },
        "current_database": {
            "seller": row["seller"],
            "bid_count": row["bid_count"],
            "start_price": (
                str(row["start_price"])
                if row["start_price"] is not None
                else None
            ),
            "final_price": (
                str(row["final_price"])
                if row["final_price"] is not None
                else None
            ),
            "tax_amount": (
                str(row["tax_amount"])
                if row["tax_amount"] is not None
                else None
            ),
            "gross_price": (
                str(row["gross_price"])
                if row["gross_price"] is not None
                else None
            ),
            "currency": row["currency"],
            "ended_at": (
                row["ended_at"].isoformat()
                if row["ended_at"] is not None
                else None
            ),
        },
        "diagnostics": {
            "visible_text": str(text_path),
            "html": str(html_path),
            "screenshot": str(screenshot_path),
        },
    }


def main() -> int:
    args = parse_args()

    rows = load_rows(
        args.limit,
        args.listing_id,
    )

    if not rows:
        raise SystemExit(
            "No matching Buyee listings were found."
        )

    context = browser.context(
        args.profile
    )
    page = context.new_page()
    results = []

    try:
        for index, row in enumerate(
            rows,
            start=1,
        ):
            print()
            print(
                f"[{index}/{len(rows)}] "
                f"{row['listing_id']}"
            )
            print(row["auction_url"])

            result = inspect_row(
                page,
                row,
                args.wait_seconds,
            )
            results.append(result)

            detail = result["detail"]

            print("Page title    :", result["page_title"])
            print("Final URL     :", result["final_url"])
            print("Auction ID    :", detail["auction_id"])
            print("Seller        :", detail["seller"])
            print("Condition     :", detail["condition"])
            print("Starting price:", detail["starting_price_jpy"])
            print("Current price :", detail["current_price_jpy"])
            print("Bids          :", detail["bid_count"])
            print("Opening JST   :", detail["opening_time"]["jst"])
            print("Opening NY    :", detail["opening_time"]["new_york"])
            print("Closing JST   :", detail["closing_time"]["jst"])
            print("Closing NY    :", detail["closing_time"]["new_york"])
            print(
                "Text dump     :",
                result["diagnostics"]["visible_text"],
            )
    finally:
        page.close()

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("Read-only probe complete.")
    print("No database rows were changed.")
    print("Output:", args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
