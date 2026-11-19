#!/usr/bin/env python3
"""Live smoke: paginate Yahoo Auctions + フリマ sold into warehouse.auction.

Example:
  .venv/bin/python scripts/smoke_yahoo_jp_ingest.py \\
    --database-url 'postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse' \\
    --query 'teresa teng' --auction-pages 2 --flea-pages 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auction_etl.services.yahoo_jp_ingest import (
    ingest_yahoo_auctions,
    ingest_yahoo_fleamarket,
)


def report_overlap(engine) -> None:
    with engine.connect() as connection:
        overlap = connection.execute(
            text(
                """
                SELECT count(*)
                FROM warehouse.auction AS yahoo
                JOIN warehouse.auction AS buyee
                  ON buyee.marketplace = 'buyee'
                 AND buyee.listing_id = yahoo.listing_id
                WHERE yahoo.marketplace = 'yahoo_auction'
                """
            )
        ).scalar_one()
        counts = connection.execute(
            text(
                """
                SELECT marketplace, count(*)
                FROM warehouse.auction
                WHERE marketplace IN (
                    'yahoo_auction', 'yahoo_fleamarket', 'buyee'
                )
                GROUP BY marketplace
                ORDER BY marketplace
                """
            )
        ).all()
        sample = connection.execute(
            text(
                """
                SELECT listing_id, start_price, final_price, gross_price,
                       tax_amount, price_includes_tax, bid_count
                FROM warehouse.auction
                WHERE marketplace = 'yahoo_auction'
                ORDER BY closing_at DESC NULLS LAST
                LIMIT 5
                """
            )
        ).mappings().all()
    print("warehouse counts:", dict(counts))
    print("buyee ∩ yahoo_auction listing_id:", int(overlap))
    print("yahoo_auction sample:")
    for row in sample:
        print(" ", dict(row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=(
            "postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse"
        ),
    )
    parser.add_argument("--query", default="teresa teng")
    parser.add_argument("--auction-pages", type=int, default=2)
    parser.add_argument("--flea-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--pause-s", type=float, default=0.35)
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    auction = ingest_yahoo_auctions(
        engine,
        query=args.query,
        pages=args.auction_pages,
        page_size=args.page_size,
        pause_s=args.pause_s,
    )
    flea = ingest_yahoo_fleamarket(
        engine,
        query=args.query,
        pages=args.flea_pages,
        pause_s=args.pause_s,
    )
    print("auction ingest:", auction)
    print("flea ingest:", flea)
    report_overlap(engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
