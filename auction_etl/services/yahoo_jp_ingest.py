"""HTTPS acquire + upsert for Yahoo Auctions closedsearch and フリマ sold."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.parsers.yahoo_auction import parse_closedsearch_html
from auction_etl.parsers.yahoo_fleamarket import parse_sold_search_html
from auction_etl.services.refresh_lookback import auction_ending_cutoff
from auction_etl.services.artist_tracking import (
    build_yahoo_auction_search_url,
    build_yahoo_fleamarket_search_url,
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_AUCTION_PAUSE_S = 0.35
DEFAULT_FLEA_PAUSE_S = 0.8
DEFAULT_MAX_PAGES = 5

UPSERT = text(
    """
    INSERT INTO warehouse.auction (
        marketplace,
        listing_id,
        auction_url,
        seller,
        title,
        bid_count,
        start_price,
        final_price,
        tax_amount,
        currency,
        ended_at,
        closing_at,
        opening_at,
        gross_price,
        tax_rate,
        price_includes_tax,
        image_url
    )
    VALUES (
        :marketplace,
        :listing_id,
        :auction_url,
        :seller,
        :title,
        :bid_count,
        :start_price,
        :final_price,
        :tax_amount,
        :currency,
        :ended_at,
        :closing_at,
        :opening_at,
        :gross_price,
        :tax_rate,
        :price_includes_tax,
        :image_url
    )
    ON CONFLICT (marketplace, listing_id)
    DO UPDATE SET
        auction_url = EXCLUDED.auction_url,
        seller = COALESCE(EXCLUDED.seller, warehouse.auction.seller),
        title = EXCLUDED.title,
        bid_count = COALESCE(EXCLUDED.bid_count, warehouse.auction.bid_count),
        start_price = COALESCE(EXCLUDED.start_price, warehouse.auction.start_price),
        final_price = EXCLUDED.final_price,
        tax_amount = EXCLUDED.tax_amount,
        currency = EXCLUDED.currency,
        ended_at = COALESCE(EXCLUDED.ended_at, warehouse.auction.ended_at),
        closing_at = COALESCE(EXCLUDED.closing_at, warehouse.auction.closing_at),
        opening_at = COALESCE(EXCLUDED.opening_at, warehouse.auction.opening_at),
        gross_price = EXCLUDED.gross_price,
        tax_rate = EXCLUDED.tax_rate,
        price_includes_tax = EXCLUDED.price_includes_tax,
        image_url = COALESCE(EXCLUDED.image_url, warehouse.auction.image_url)
    """
)

KNOWN_IDS_SQL = text(
    """
    SELECT listing_id, closing_at
    FROM warehouse.auction
    WHERE marketplace = :marketplace
      AND listing_id IS NOT NULL
      AND btrim(listing_id) <> ''
    """
)

AUCTION_IDS_SQL = text(
    """
    SELECT listing_id
    FROM warehouse.auction
    WHERE marketplace = 'yahoo_auction'
      AND listing_id IS NOT NULL
      AND btrim(listing_id) <> ''
    """
)

ENABLED_QUERIES_SQL = text(
    """
    SELECT DISTINCT
        COALESCE(
            NULLIF(btrim(marketplace.search_query), ''),
            NULLIF(btrim(artist.name), '')
        ) AS query
    FROM account.tracked_artist AS artist
    JOIN account.artist_marketplace AS marketplace
      ON marketplace.tracked_artist_id = artist.id
    WHERE artist.enabled IS TRUE
      AND marketplace.enabled IS TRUE
      AND marketplace.marketplace = :marketplace
    ORDER BY 1
    """
)


class YahooRateLimited(RuntimeError):
    """Raised when a Yahoo host returns HTTP 429/503."""


class YahooFetchError(RuntimeError):
    """Raised when a Yahoo fetch fails for a non-rate-limit reason."""


def fetch_html(url: str, *, timeout: float = 45.0) -> str:
    """GET one Yahoo search page over HTTPS."""

    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 503}:
            raise YahooRateLimited(
                f"HTTP {exc.code} for {url}"
            ) from exc
        raise YahooFetchError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise YahooFetchError(f"URL error for {url}: {exc}") from exc


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        return None


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def row_params(item: dict[str, Any]) -> dict[str, Any]:
    """Map a parser card into warehouse.auction upsert parameters."""

    closing = _parse_time(item.get("closing_at"))
    opening = _parse_time(item.get("start_at") or item.get("open_at"))
    return {
        "marketplace": item["marketplace"],
        "listing_id": item["listing_id"],
        "auction_url": item.get("auction_url"),
        "seller": item.get("seller_id"),
        "title": item.get("title"),
        "bid_count": item.get("bid_count"),
        "start_price": _money(item.get("start_price_jpy")),
        "final_price": _money(item.get("final_price_jpy")),
        "tax_amount": _money(item.get("tax_amount_jpy")),
        "currency": item.get("currency") or "JPY",
        "ended_at": closing,
        "closing_at": closing,
        "opening_at": opening,
        "gross_price": _money(item.get("gross_price_jpy")),
        "tax_rate": _money(item.get("tax_rate")),
        "price_includes_tax": item.get("price_includes_tax"),
        "image_url": item.get("image_url"),
    }


def upsert_items(engine: Engine, items: list[dict[str, Any]]) -> int:
    """Upsert parsed Yahoo JP cards into warehouse.auction."""

    if not items:
        return 0
    with engine.begin() as connection:
        for item in items:
            connection.execute(UPSERT, row_params(item))
    return len(items)


def load_known_listings(
    engine: Engine,
    marketplace: str,
) -> tuple[set[str], datetime | None]:
    """Return known listing ids and newest closing_at watermark."""

    with engine.connect() as connection:
        rows = connection.execute(
            KNOWN_IDS_SQL,
            {"marketplace": marketplace},
        ).mappings().all()

    known: set[str] = set()
    watermark: datetime | None = None
    for row in rows:
        listing_id = str(row["listing_id"] or "").strip()
        if listing_id:
            known.add(listing_id)
        closing = row.get("closing_at")
        if isinstance(closing, datetime):
            if closing.tzinfo is None:
                closing = closing.replace(tzinfo=timezone.utc)
            if watermark is None or closing > watermark:
                watermark = closing
    return known, watermark


def load_yahoo_auction_ids(engine: Engine) -> set[str]:
    """Return Yahoo Auctions listing ids already in the warehouse."""

    with engine.connect() as connection:
        rows = connection.execute(AUCTION_IDS_SQL).all()
    return {
        str(listing_id).strip()
        for (listing_id,) in rows
        if listing_id is not None and str(listing_id).strip()
    }


def page_is_fully_known(
    item_ids: list[str],
    known_ids: set[str],
) -> bool:
    """True when a nonempty page contains only already-stored identities."""

    return bool(item_ids) and all(item_id in known_ids for item_id in item_ids)


def page_is_all_older_or_equal(
    items: list[dict[str, Any]],
    watermark: datetime | None,
) -> bool:
    """True when every card closes at or before the warehouse watermark."""

    if watermark is None or not items:
        return False
    for item in items:
        closing = _parse_time(item.get("closing_at"))
        if closing is None:
            return False
        if closing.tzinfo is None:
            closing = closing.replace(tzinfo=watermark.tzinfo)
        if closing > watermark:
            return False
    return True


def page_is_at_or_before_lookback(
    items: list[dict[str, Any]],
    lookback_cutoff: datetime | None,
) -> bool:
    """True when every dated card closes at/before the daily lookback floor."""

    if lookback_cutoff is None or not items:
        return False
    cutoff = lookback_cutoff
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    known = 0
    for item in items:
        closing = _parse_time(item.get("closing_at"))
        if closing is None:
            continue
        known += 1
        if closing.tzinfo is None:
            closing = closing.replace(tzinfo=cutoff.tzinfo)
        if closing > cutoff:
            return False
    return known > 0


def enabled_yahoo_queries(
    engine: Engine,
    marketplace: str,
) -> list[str]:
    """Return distinct enabled artist queries for one Yahoo marketplace."""

    with engine.connect() as connection:
        rows = connection.execute(
            ENABLED_QUERIES_SQL,
            {"marketplace": marketplace},
        ).all()
    queries: list[str] = []
    seen: set[str] = set()
    for (query,) in rows:
        normalized = " ".join(str(query or "").split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        queries.append(normalized)
    return queries


def ingest_yahoo_auctions(
    engine: Engine,
    *,
    query: str,
    pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 100,
    pause_s: float = DEFAULT_AUCTION_PAUSE_S,
    known_ids: set[str] | None = None,
    watermark: datetime | None = None,
    lookback_cutoff: datetime | None = None,
    stop_on_novelty: bool = True,
) -> dict[str, Any]:
    """Paginate closedsearch newest-first and upsert auction comps."""

    if known_ids is None:
        known_ids, loaded_watermark = load_known_listings(
            engine,
            "yahoo_auction",
        )
        if watermark is None:
            watermark = loaded_watermark
    elif watermark is None:
        _, watermark = load_known_listings(engine, "yahoo_auction")

    seen: set[str] = set()
    upserted = 0
    new_count = 0
    already_known = 0
    pages_fetched = 0
    total: int | None = None
    stopped_reason = "max_pages"
    rate_limited = False

    try:
        for page_index in range(max(1, pages)):
            start = 1 + page_index * page_size
            url = build_yahoo_auction_search_url(
                query,
                start=start,
                page_size=page_size,
            )
            html = fetch_html(url)
            parsed = parse_closedsearch_html(html)
            if not parsed["parse_ok"]:
                raise RuntimeError(f"closedsearch parse failed for {url}")
            if total is None:
                total = parsed["total_results_available"]
            items = list(parsed["items"])
            page_ids = [row["listing_id"] for row in items]
            overlap = seen.intersection(page_ids)
            if overlap:
                raise RuntimeError(
                    "yahoo_auction pagination overlap: "
                    + ", ".join(sorted(overlap)[:5])
                )
            seen.update(page_ids)
            pages_fetched += 1

            page_new = [
                row for row in items if row["listing_id"] not in known_ids
            ]
            page_known = len(items) - len(page_new)
            already_known += page_known
            new_count += len(page_new)
            upserted += upsert_items(engine, items)
            known_ids.update(page_ids)

            if stop_on_novelty and page_known == len(items) and items:
                stopped_reason = "novelty"
                break
            if stop_on_novelty and page_is_all_older_or_equal(items, watermark):
                stopped_reason = "watermark"
                break
            if page_is_at_or_before_lookback(items, lookback_cutoff):
                stopped_reason = "lookback"
                break
            if not items:
                stopped_reason = "empty"
                break
            if page_index + 1 < pages:
                time.sleep(pause_s)
        else:
            stopped_reason = "max_pages"
    except YahooRateLimited:
        rate_limited = True
        stopped_reason = "rate_limited"

    return {
        "marketplace": "yahoo_auction",
        "query": query,
        "upserted": upserted,
        "unique_ids": len(seen),
        "new_count": new_count,
        "already_known": already_known,
        "discovery_pages": pages_fetched,
        "total_results_available": total,
        "stopped_reason": stopped_reason,
        "rate_limited": rate_limited,
    }


def ingest_yahoo_fleamarket(
    engine: Engine,
    *,
    query: str,
    pages: int = DEFAULT_MAX_PAGES,
    pause_s: float = DEFAULT_FLEA_PAUSE_S,
    known_ids: set[str] | None = None,
    watermark: datetime | None = None,
    lookback_cutoff: datetime | None = None,
    stop_on_novelty: bool = True,
) -> dict[str, Any]:
    """Paginate フリマ sold search (search-only) and upsert comps."""

    if known_ids is None:
        known_ids, loaded_watermark = load_known_listings(
            engine,
            "yahoo_fleamarket",
        )
        if watermark is None:
            watermark = loaded_watermark
    elif watermark is None:
        _, watermark = load_known_listings(engine, "yahoo_fleamarket")

    seen: set[str] = set()
    upserted = 0
    new_count = 0
    already_known = 0
    pages_fetched = 0
    total: int | None = None
    stopped_reason = "max_pages"
    rate_limited = False
    # Same Yahoo auction id can appear on フリマ search; auction wins.
    auction_ids = load_yahoo_auction_ids(engine)

    try:
        for page in range(1, max(1, pages) + 1):
            url = build_yahoo_fleamarket_search_url(query, page=page)
            html = fetch_html(url)
            parsed = parse_sold_search_html(html)
            if not parsed["parse_ok"]:
                raise RuntimeError(f"flea sold parse failed for {url}")
            if total is None:
                total = parsed["total_results_available"]
            items = [
                row
                for row in list(parsed["items"])
                if row["listing_id"] not in auction_ids
            ]
            page_ids = [row["listing_id"] for row in items]
            overlap = seen.intersection(page_ids)
            if overlap:
                raise RuntimeError(
                    "yahoo_fleamarket pagination overlap: "
                    + ", ".join(sorted(overlap)[:5])
                )
            seen.update(page_ids)
            pages_fetched += 1

            page_new = [
                row for row in items if row["listing_id"] not in known_ids
            ]
            page_known = len(items) - len(page_new)
            already_known += page_known
            new_count += len(page_new)
            upserted += upsert_items(engine, items)
            known_ids.update(page_ids)

            if stop_on_novelty and page_known == len(items) and items:
                stopped_reason = "novelty"
                break
            if stop_on_novelty and page_is_all_older_or_equal(items, watermark):
                stopped_reason = "watermark"
                break
            if page_is_at_or_before_lookback(items, lookback_cutoff):
                stopped_reason = "lookback"
                break
            if not items:
                stopped_reason = "empty"
                break
            if page < pages:
                time.sleep(pause_s)
        else:
            stopped_reason = "max_pages"
    except YahooRateLimited:
        rate_limited = True
        stopped_reason = "rate_limited"

    return {
        "marketplace": "yahoo_fleamarket",
        "query": query,
        "upserted": upserted,
        "unique_ids": len(seen),
        "new_count": new_count,
        "already_known": already_known,
        "discovery_pages": pages_fetched,
        "total_results_available": total,
        "stopped_reason": stopped_reason,
        "rate_limited": rate_limited,
    }


def ingest_yahoo_jp_for_queries(
    engine: Engine,
    *,
    queries: list[str],
    auction_pages: int = DEFAULT_MAX_PAGES,
    flea_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 100,
    auction_pause_s: float = DEFAULT_AUCTION_PAUSE_S,
    flea_pause_s: float = DEFAULT_FLEA_PAUSE_S,
    include_auction: bool = True,
    include_fleamarket: bool = True,
    stop_on_novelty: bool = True,
) -> dict[str, Any]:
    """Run enabled Yahoo JP adapters for each search query."""

    results: list[dict[str, Any]] = []
    for query in queries:
        normalized = " ".join(str(query).split())
        if not normalized:
            continue
        if include_auction:
            results.append(
                ingest_yahoo_auctions(
                    engine,
                    query=normalized,
                    pages=auction_pages,
                    page_size=page_size,
                    pause_s=auction_pause_s,
                    stop_on_novelty=stop_on_novelty,
                )
            )
            if results[-1].get("rate_limited"):
                break
        if include_fleamarket:
            results.append(
                ingest_yahoo_fleamarket(
                    engine,
                    query=normalized,
                    pages=flea_pages,
                    pause_s=flea_pause_s,
                    stop_on_novelty=stop_on_novelty,
                )
            )
            if results[-1].get("rate_limited"):
                break
    return {
        "queries": len(queries),
        "steps": results,
        "upserted": sum(int(step.get("upserted") or 0) for step in results),
        "new_count": sum(int(step.get("new_count") or 0) for step in results),
        "rate_limited": any(bool(step.get("rate_limited")) for step in results),
    }


def refresh_yahoo_marketplace_for_account(
    engine: Engine,
    *,
    marketplace: str,
    pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 100,
    pause_s: float | None = None,
    stop_on_novelty: bool = True,
    lookback_days: int | None = 3,
    fallback_queries: list[str] | None = None,
) -> dict[str, Any]:
    """Refresh one Yahoo marketplace from enabled artist targets."""

    if marketplace not in {"yahoo_auction", "yahoo_fleamarket"}:
        raise ValueError(f"Unsupported Yahoo marketplace: {marketplace}")

    queries = enabled_yahoo_queries(engine, marketplace)
    if not queries and fallback_queries:
        queries = [
            " ".join(str(query).split())
            for query in fallback_queries
            if " ".join(str(query).split())
        ]
    if not queries:
        return {
            "marketplace": marketplace,
            "state": "skipped",
            "stopped_reason": "disabled",
            "queries": 0,
            "steps": [],
            "upserted": 0,
            "new_count": 0,
            "already_known": 0,
            "discovery_pages": 0,
            "rate_limited": False,
        }

    known_ids, watermark = load_known_listings(engine, marketplace)
    lookback_cutoff = None
    if lookback_days is not None:
        lookback_cutoff = auction_ending_cutoff(
            engine,
            marketplace,
            lookback_days=lookback_days,
        )
    steps: list[dict[str, Any]] = []
    rate_limited = False
    for query in queries:
        try:
            if marketplace == "yahoo_auction":
                step = ingest_yahoo_auctions(
                    engine,
                    query=query,
                    pages=pages,
                    page_size=page_size,
                    pause_s=(
                        DEFAULT_AUCTION_PAUSE_S if pause_s is None else pause_s
                    ),
                    known_ids=known_ids,
                    watermark=watermark,
                    lookback_cutoff=lookback_cutoff,
                    stop_on_novelty=stop_on_novelty,
                )
            else:
                step = ingest_yahoo_fleamarket(
                    engine,
                    query=query,
                    pages=pages,
                    pause_s=(
                        DEFAULT_FLEA_PAUSE_S if pause_s is None else pause_s
                    ),
                    known_ids=known_ids,
                    watermark=watermark,
                    lookback_cutoff=lookback_cutoff,
                    stop_on_novelty=stop_on_novelty,
                )
        except YahooFetchError as exc:
            steps.append(
                {
                    "marketplace": marketplace,
                    "query": query,
                    "upserted": 0,
                    "unique_ids": 0,
                    "new_count": 0,
                    "already_known": 0,
                    "discovery_pages": 0,
                    "stopped_reason": "fetch_error",
                    "rate_limited": False,
                    "error": str(exc),
                }
            )
            continue
        steps.append(step)
        if step.get("rate_limited"):
            rate_limited = True
            break

    state = "rate_limited" if rate_limited else "done"
    return {
        "marketplace": marketplace,
        "state": state,
        "stopped_reason": (
            "rate_limited"
            if rate_limited
            else (
                steps[-1].get("stopped_reason")
                if steps
                else "empty"
            )
        ),
        "queries": len(queries),
        "steps": steps,
        "upserted": sum(int(step.get("upserted") or 0) for step in steps),
        "new_count": sum(int(step.get("new_count") or 0) for step in steps),
        "already_known": sum(
            int(step.get("already_known") or 0) for step in steps
        ),
        "discovery_pages": sum(
            int(step.get("discovery_pages") or 0) for step in steps
        ),
        "rate_limited": rate_limited,
    }
