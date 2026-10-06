"""Sold-card money is a local display amount, not automatically USD."""

from __future__ import annotations

from decimal import Decimal

from auction_etl.services.parse import parse_sold_money, sold_card_hammer


def test_explicit_us_dollar_is_usd() -> None:
    amount, currency = parse_sold_money("US $15.99")
    assert amount == Decimal("15.99")
    assert currency == "USD"


def test_gbp_and_eur_are_not_usd() -> None:
    amount, currency = parse_sold_money("GBP 36.45")
    assert amount == Decimal("36.45")
    assert currency == "GBP"

    amount, currency = parse_sold_money("£21.81")
    assert amount == Decimal("21.81")
    assert currency == "GBP"

    amount, currency = parse_sold_money("€20.00")
    assert amount == Decimal("20.00")
    assert currency == "EUR"


def test_australian_and_canadian_dollars_are_not_usd() -> None:
    amount, currency = parse_sold_money("AU $32.00")
    assert amount == Decimal("32.00")
    assert currency == "AUD"

    amount, currency = parse_sold_money("C $18.50")
    assert amount == Decimal("18.50")
    assert currency == "CAD"


def test_bare_dollar_is_unconfirmed_display_currency() -> None:
    """ebay.com sold cards often show $, which is not official USD."""

    amount, currency = parse_sold_money("$348.27")
    assert amount == Decimal("348.27")
    assert currency is None


def test_first_amount_wins_on_sold_plus_strikethrough() -> None:
    amount, currency = parse_sold_money("US $39.38 $43.27")
    assert amount == Decimal("39.38")
    assert currency == "USD"


def test_best_offer_sold_card_is_not_the_hammer() -> None:
    amount, currency = sold_card_hammer("FIXED_PRICE_OBO", "$50.00")
    assert amount is None
    assert currency is None

    amount, currency = sold_card_hammer("FIXED_PRICE", "US $79.99")
    assert amount == Decimal("79.99")
    assert currency == "USD"


def test_ebay_us_tax_is_six_and_a_quarter_percent() -> None:
    from auction_etl.services.parse import apply_ebay_us_tax

    hammer, tax, gross, rate = apply_ebay_us_tax(
        Decimal("160.00"),
        currency="USD",
    )
    assert hammer == Decimal("160.00")
    assert rate == Decimal("0.0625")
    assert tax == Decimal("10.00")
    assert gross == Decimal("170.00")
    empty = apply_ebay_us_tax(None, currency="USD")
    assert empty == (None, None, None, None)


def test_parse_accepts_ebay_image_url_key() -> None:
    from auction_etl.services.parse import _listing_image_url
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "auction_etl" / "services" / "parse.py").read_text(
        encoding="utf-8"
    )
    assert "image_url=_listing_image_url(listing)" in source
    assert _listing_image_url({"image_url": "https://i.ebayimg.com/x.jpg"}) == (
        "https://i.ebayimg.com/x.jpg"
    )
    assert _listing_image_url({"image": "https://buyee.example/x.jpg"}) == (
        "https://buyee.example/x.jpg"
    )
