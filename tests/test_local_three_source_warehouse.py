"""Local warehouse contracts for Buyee, eBay, and Gripsweat."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


DEFAULT_URL = (
    "postgresql+psycopg://auction:auction@"
    "127.0.0.1:5544/auction_warehouse"
)


def _engine():
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url)


def _reachable() -> bool:
    try:
        with _engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(),
    reason="local warehouse 5544 is not reachable",
)


def test_buyee_every_row_has_listing_identity_and_jpy_price() -> None:
    """Buyee watchlist identities stay in the warehouse with a JPY sold price."""

    with _engine().connect() as connection:
        missing = connection.execute(
            text(
                """
                SELECT count(*) FROM warehouse.auction
                WHERE marketplace = 'buyee'
                  AND (
                    listing_id IS NULL
                    OR btrim(listing_id) = ''
                    OR title IS NULL
                    OR btrim(title) = ''
                    OR final_price IS NULL
                    OR upper(coalesce(currency, '')) <> 'JPY'
                  )
                """
            )
        ).scalar_one()
        total = connection.execute(
            text(
                """
                SELECT count(*) FROM warehouse.auction
                WHERE marketplace = 'buyee'
                """
            )
        ).scalar_one()

    assert total > 0
    assert missing == 0


def test_three_sources_are_present_locally() -> None:
    """Buyee, eBay, and Gripsweat all have warehouse rows on the local loop."""

    with _engine().connect() as connection:
        buyee = connection.execute(
            text("SELECT count(*) FROM warehouse.auction WHERE marketplace = 'buyee'")
        ).scalar_one()
        ebay = connection.execute(
            text("SELECT count(*) FROM warehouse.auction WHERE marketplace = 'ebay'")
        ).scalar_one()
        gripsweat = connection.execute(
            text("SELECT count(*) FROM warehouse.gripsweat_sale")
        ).scalar_one()

    assert buyee > 0
    assert ebay > 0
    assert gripsweat > 0
