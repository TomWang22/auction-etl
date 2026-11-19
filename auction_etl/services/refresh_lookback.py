"""Daily refresh lookback cutoffs from warehouse ending timestamps.

Daily scrapes should focus on sales at or after
``max(ending) - lookback_days`` rather than walking archives
back to the 2010s. Empty warehouses return ``None`` (no cutoff)
so first-time bootstrap can still fill history.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


DEFAULT_LOOKBACK_DAYS = 3

_AUCTION_MARKETPLACES = frozenset(
    {
        "buyee",
        "ebay",
        "yahoo_auction",
        "yahoo_fleamarket",
    }
)


def normalize_lookback_days(value: int | None) -> int:
    """Clamp lookback to a positive day count."""

    if value is None:
        return DEFAULT_LOOKBACK_DAYS
    return max(1, int(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _connect(bind: Engine | Connection) -> tuple[Connection, bool]:
    """Return a connection and whether the caller must close it."""

    if isinstance(bind, Engine):
        return bind.connect(), True
    return bind, False


def auction_ending_cutoff(
    bind: Engine | Connection,
    marketplace: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> datetime | None:
    """Return ``max(ended_at) - lookback`` for one auction marketplace."""

    market = str(marketplace or "").strip().casefold()
    if market not in _AUCTION_MARKETPLACES:
        raise ValueError(f"Unsupported auction marketplace: {marketplace!r}")
    days = normalize_lookback_days(lookback_days)
    connection, owns = _connect(bind)
    try:
        row = connection.execute(
            text(
                """
                SELECT max(ended_at) AS newest
                FROM warehouse.auction
                WHERE marketplace = :marketplace
                  AND ended_at IS NOT NULL
                """
            ),
            {"marketplace": market},
        ).mappings().one()
    finally:
        if owns:
            connection.close()
    newest = row["newest"]
    if newest is None:
        return None
    return _as_utc(newest) - timedelta(days=days)


def gripsweat_sold_cutoff(
    bind: Engine | Connection,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> date | None:
    """Return ``max(sold_at) - lookback`` for Gripsweat archive rows."""

    days = normalize_lookback_days(lookback_days)
    connection, owns = _connect(bind)
    try:
        row = connection.execute(
            text(
                """
                SELECT max(sold_at) AS newest
                FROM warehouse.gripsweat_sale
                WHERE sold_at IS NOT NULL
                """
            )
        ).mappings().one()
    finally:
        if owns:
            connection.close()
    newest = row["newest"]
    if newest is None:
        return None
    if isinstance(newest, datetime):
        newest_date = _as_utc(newest).date()
    else:
        newest_date = newest
    return newest_date - timedelta(days=days)


def marketplace_cutoffs(
    bind: Engine | Connection,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, date | datetime | None]:
    """Compute lookback cutoffs for all five live marketplaces."""

    days = normalize_lookback_days(lookback_days)
    return {
        "buyee": auction_ending_cutoff(
            bind, "buyee", lookback_days=days
        ),
        "ebay": auction_ending_cutoff(
            bind, "ebay", lookback_days=days
        ),
        "gripsweat": gripsweat_sold_cutoff(
            bind, lookback_days=days
        ),
        "yahoo_auction": auction_ending_cutoff(
            bind, "yahoo_auction", lookback_days=days
        ),
        "yahoo_fleamarket": auction_ending_cutoff(
            bind, "yahoo_fleamarket", lookback_days=days
        ),
    }


def coerce_sale_date(value: Any) -> date | None:
    """Normalize scrape/DB sale timestamps to a calendar date."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value).date()
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    if "T" in text_value:
        text_value = text_value.split("T", 1)[0]
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def page_is_at_or_before_cutoff(
    sold_values: list[Any],
    cutoff: date | datetime | None,
) -> bool:
    """True when every dated item on the page is at/before the cutoff.

    Undated items do not trigger a stop — only dated evidence can.
    """

    if cutoff is None:
        return False
    cutoff_date = coerce_sale_date(cutoff)
    if cutoff_date is None:
        return False
    known = [
        parsed
        for parsed in (coerce_sale_date(value) for value in sold_values)
        if parsed is not None
    ]
    if not known:
        return False
    return max(known) <= cutoff_date
