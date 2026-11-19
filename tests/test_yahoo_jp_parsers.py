"""Fixture tests for Yahoo Auctions closedsearch + フリマ sold parsers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from auction_etl.parsers.yahoo_auction import (
    parse_closedsearch_html,
    parse_item_detail_html,
)
from auction_etl.parsers.yahoo_fleamarket import parse_sold_search_html
from auction_etl.services.artist_tracking import (
    build_yahoo_auction_search_url,
    build_yahoo_fleamarket_search_url,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
AUCTION_FIXTURES = FIXTURES / "yahoo_auction"
FLEA_FIXTURES = FIXTURES / "yahoo_fleamarket"


def test_yahoo_auction_url_builder_uses_advanced_va_and_pagination() -> None:
    latin = build_yahoo_auction_search_url("teresa teng")
    query = parse_qs(urlsplit(latin).query)
    assert query["va"] == ["teresa teng"]
    assert query["f_adv"] == ["1"]
    assert query["b"] == ["1"]
    assert query["n"] == ["100"]

    page_two = build_yahoo_auction_search_url("teresa teng", start=101)
    assert parse_qs(urlsplit(page_two).query)["b"] == ["101"]

    japanese = build_yahoo_auction_search_url("山口百恵")
    assert "%E5%B1%B1%E5%8F%A3%E7%99%BE%E6%81%B5" in japanese


def test_yahoo_fleamarket_url_builder_pins_sold_and_endtime() -> None:
    url = build_yahoo_fleamarket_search_url("teresa teng", page=2)
    assert url.startswith(
        "https://paypayfleamarket.yahoo.co.jp/search/teresa%20teng?"
    )
    assert "page=2" in url
    assert "sold=1" in url
    assert "sort=endTime" in url
    assert "order=DESC" in url


def test_parse_closedsearch_money_tax0_and_tax_inclusive() -> None:
    html = (AUCTION_FIXTURES / "closedsearch_teresa_p1.html").read_text(
        encoding="utf-8"
    )
    parsed = parse_closedsearch_html(html)
    assert parsed["parse_ok"] is True
    items = {row["listing_id"]: row for row in parsed["items"]}

    # Screenshot / tax0 card: hammer 43018, Tax 0 yen, start 15000, 27 bids.
    plain = items["p1252469501"]
    assert plain["gross_price_jpy"] == 43018
    assert plain["final_price_jpy"] == 43018
    assert plain["tax_amount_jpy"] == 0
    assert plain["price_includes_tax"] is False
    assert plain["start_price_jpy"] == 15000
    assert plain["bid_count"] == 27

    taxed = items["d1107628457"]
    assert taxed["price_includes_tax"] is True
    assert taxed["gross_price_jpy"] == 100000
    assert taxed["final_price_jpy"] == 90910
    assert taxed["tax_amount_jpy"] == 9090
    assert taxed["tax_rate"] == Decimal("0.10")


def test_parse_closedsearch_drops_fleamarket_embeds() -> None:
    html = (AUCTION_FIXTURES / "closedsearch_teresa_p1.html").read_text(
        encoding="utf-8"
    )
    parsed = parse_closedsearch_html(html)
    assert parsed["total_results_available"] is not None
    items = parsed["items"]
    assert len(items) >= 40
    assert all(row["marketplace"] == "yahoo_auction" for row in items)
    assert all("/jp/auction/" in row["auction_url"] for row in items)


def test_parse_closedsearch_momoe_japanese_query_fixture() -> None:
    html = (AUCTION_FIXTURES / "closedsearch_momoe_p1.html").read_text(
        encoding="utf-8"
    )
    parsed = parse_closedsearch_html(html)
    assert parsed["parse_ok"] is True
    assert len(parsed["items"]) >= 40


def test_parse_fleamarket_sold_has_no_invented_tax() -> None:
    html = (FLEA_FIXTURES / "sold_teresa_p1_endtime.html").read_text(
        encoding="utf-8"
    )
    parsed = parse_sold_search_html(html)
    assert parsed["parse_ok"] is True
    items = parsed["items"]
    assert len(items) == 100
    assert all(row["item_status"] == "SOLD" for row in items)
    assert all(row["tax_amount_jpy"] is None for row in items)
    assert all(row["price_includes_tax"] is None for row in items)
    assert all(row["gross_price_jpy"] == row["final_price_jpy"] for row in items)
    assert all(row["bid_count"] is None for row in items)


def test_auction_detail_tax_inclusive_vs_plain() -> None:
    plain = parse_item_detail_html(
        (AUCTION_FIXTURES / "detail_tax0.html").read_text(encoding="utf-8")
    )
    taxed = parse_item_detail_html(
        (AUCTION_FIXTURES / "detail_tax1.html").read_text(encoding="utf-8")
    )
    assert plain is not None
    assert taxed is not None
    assert plain["gross_price_jpy"] == 43018
    assert plain["final_price_jpy"] == 43018
    assert plain["tax_amount_jpy"] == 0
    assert plain["price_includes_tax"] is False
    assert plain["start_price_jpy"] == 15000
    assert taxed["gross_price_jpy"] == 100000
    assert taxed["final_price_jpy"] == 90910
    assert taxed["tax_amount_jpy"] == 9090
    assert taxed["price_includes_tax"] is True
