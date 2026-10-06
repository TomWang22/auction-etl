"""Day, week, and latest-run counts for listings added to the catalog."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


LOCAL_ZONE = ZoneInfo("America/New_York")
MARKETPLACES = ("Buyee", "eBay", "Gripsweat")
WINDOW_THIS_RUN = "This run"
WINDOW_TODAY = "Today"
WINDOW_THIS_WEEK = "This week"
WINDOW_LAST_14 = "Last 14 days"
WINDOWS = (
    WINDOW_THIS_RUN,
    WINDOW_TODAY,
    WINDOW_THIS_WEEK,
    WINDOW_LAST_14,
)


def load_recent_catalog_additions(
    engine: Engine,
    account_id: str,
    *,
    days: int = 21,
) -> pd.DataFrame:
    """Return catalog rows this account received in the recent window."""
    query = text(
        """
        SELECT
            a.marketplace,
            a.listing_id,
            a.title,
            a.catalog_number,
            a.created_at
        FROM warehouse.auction AS a
        JOIN account.auction_listing AS visible
          ON visible.marketplace = a.marketplace
         AND visible.listing_id = a.listing_id
         AND visible.account_id = CAST(:account_id AS uuid)
        WHERE a.created_at >= now() - (:days * INTERVAL '1 day')
        ORDER BY a.created_at DESC
        """
    )
    with engine.connect() as connection:
        frame = pd.read_sql_query(
            query,
            connection,
            params={
                "account_id": account_id,
                "days": int(days),
            },
        )
    if frame.empty:
        return frame
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True)
    frame["local_day"] = frame["created_at"].dt.tz_convert(LOCAL_ZONE).dt.date
    return frame


def filter_catalog_additions(
    frame: pd.DataFrame,
    window: str,
    *,
    today: date,
    run_start: datetime | None = None,
    run_end: datetime | None = None,
) -> pd.DataFrame:
    """Keep additions for one customer-facing window."""
    if frame is None or frame.empty:
        return frame.iloc[0:0].copy() if frame is not None else pd.DataFrame()
    if window == WINDOW_THIS_RUN:
        start = pd.Timestamp(run_start) if run_start is not None else None
        end = pd.Timestamp(run_end) if run_end is not None else None
        if start is None or pd.isna(start):
            return frame.iloc[0:0].copy()
        if start.tzinfo is None:
            start = start.tz_localize(timezone.utc)
        if end is None or pd.isna(end):
            end = pd.Timestamp.now(tz=timezone.utc)
        elif end.tzinfo is None:
            end = end.tz_localize(timezone.utc)
        selected = frame.loc[
            frame["created_at"].ge(start) & frame["created_at"].le(end)
        ]
        return selected.copy()
    if window == WINDOW_TODAY:
        return frame.loc[frame["local_day"].eq(today)].copy()
    if window == WINDOW_THIS_WEEK:
        week_start = today - timedelta(days=today.weekday())
        return frame.loc[
            frame["local_day"].ge(week_start) & frame["local_day"].le(today)
        ].copy()
    return frame.loc[
        frame["local_day"].ge(today - timedelta(days=13))
        & frame["local_day"].le(today)
    ].copy()


def ingestion_day_chart(
    frame: pd.DataFrame,
    *,
    today: date,
    days: int = 14,
) -> pd.DataFrame:
    """One row per day, with a count for each marketplace."""
    start = today - timedelta(days=days - 1)
    days_index = [start + timedelta(days=offset) for offset in range(days)]
    counts = {
        label: [0 for _day in days_index]
        for label in MARKETPLACES
    }
    if frame is not None and not frame.empty:
        for day, marketplace in zip(
            frame["local_day"],
            frame["marketplace"],
            strict=False,
        ):
            if day not in set(days_index):
                continue
            label = _marketplace_label(marketplace)
            if label is None:
                continue
            counts[label][days_index.index(day)] += 1
    chart = pd.DataFrame({"Day": [day.isoformat() for day in days_index]})
    for label, values in counts.items():
        chart[label] = values
    return chart


def week_counts(
    frame: pd.DataFrame,
    *,
    today: date,
) -> tuple[int, int]:
    """Return additions this week and the previous week."""
    this_start = today - timedelta(days=today.weekday())
    previous_start = this_start - timedelta(days=7)
    previous_end = this_start - timedelta(days=1)
    if frame is None or frame.empty:
        return 0, 0
    this_week = int(
        (
            frame["local_day"].ge(this_start)
            & frame["local_day"].le(today)
        ).sum()
    )
    previous_week = int(
        (
            frame["local_day"].ge(previous_start)
            & frame["local_day"].le(previous_end)
        ).sum()
    )
    return this_week, previous_week


def _marketplace_label(value: Any) -> str | None:
    text = str(value or "").casefold()
    if text == "buyee":
        return "Buyee"
    if text == "ebay":
        return "eBay"
    if text == "gripsweat":
        return "Gripsweat"
    return None
