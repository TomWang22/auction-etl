"""Day, week, and latest-run filters for catalog additions."""

from datetime import date, datetime, timezone

import pandas as pd

from auction_etl.reporting.ingestion_activity import (
    WINDOW_THIS_RUN,
    WINDOW_THIS_WEEK,
    WINDOW_TODAY,
    filter_catalog_additions,
    ingestion_day_chart,
    week_counts,
)


def additions() -> pd.DataFrame:
    created = [
        datetime(2026, 10, 4, 12, 41, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
    ]
    frame = pd.DataFrame(
        {
            "marketplace": ["ebay", "buyee", "gripsweat"],
            "listing_id": ["1", "2", "3"],
            "title": ["a", "b", "c"],
            "catalog_number": ["", "", ""],
            "created_at": pd.to_datetime(created, utc=True),
        }
    )
    frame["local_day"] = frame["created_at"].dt.tz_convert(
        "America/New_York"
    ).dt.date
    return frame


def test_this_run_keeps_rows_added_during_the_refresh() -> None:
    selected = filter_catalog_additions(
        additions(),
        WINDOW_THIS_RUN,
        today=date(2026, 10, 4),
        run_start=datetime(2026, 10, 4, 12, 40, tzinfo=timezone.utc),
        run_end=datetime(2026, 10, 4, 12, 51, tzinfo=timezone.utc),
    )
    assert list(selected["listing_id"]) == ["1"]


def test_today_and_week_counts_use_local_days() -> None:
    frame = additions()
    today = date(2026, 10, 4)
    assert list(
        filter_catalog_additions(frame, WINDOW_TODAY, today=today)["listing_id"]
    ) == ["1"]
    week = filter_catalog_additions(frame, WINDOW_THIS_WEEK, today=today)
    assert set(week["listing_id"]) == {"1", "2"}
    assert week_counts(frame, today=today) == (2, 1)


def test_day_chart_counts_each_marketplace() -> None:
    chart = ingestion_day_chart(additions(), today=date(2026, 10, 4), days=14)
    october_4 = chart.loc[chart["Day"].eq("2026-10-04")].iloc[0]
    assert int(october_4["eBay"]) == 1
    assert int(october_4["Buyee"]) == 0
    assert int(chart["Gripsweat"].sum()) == 1
