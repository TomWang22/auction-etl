"""Regression tests for Buyee HTTPS detail extraction."""

from __future__ import annotations

from decimal import Decimal

from scripts.crawl_buyee_http_details import (
    extract_detail_from_html,
)


def test_extract_detail_from_server_rendered_html() -> None:
    """HTTPS HTML must produce the established Buyee detail model."""
    html = """
    <!doctype html>
    <html>
      <body>
        <main>
          <h1>Example Japanese Auction</h1>

          <div>Seller</div>
          <div>example-seller</div>

          <div>Opening Time (JST)</div>
          <div>20 Aug 2026 22:17:03</div>

          <div>Closing Time (JST)</div>
          <div>27 Aug 2026 22:17:03</div>

          <div>Starting Price</div>
          <div>500 YEN</div>

          <div>Current Price</div>
          <div>510 YEN</div>

          <div>Number of Bids</div>
          <div>2</div>

          <div>Item Condition</div>
          <div>A little damaged/dirty</div>

          <div>Auction has ended</div>
        </main>
      </body>
    </html>
    """

    detail = extract_detail_from_html(
        html=html,
        listing_id="k1240637589",
        auction_url=(
            "https://buyee.jp/"
            "item/jdirectitems/auction/"
            "k1240637589"
        ),
    )

    assert (
        detail.listing_id
        == "k1240637589"
    )
    assert (
        detail.title
        == "Example Japanese Auction"
    )
    assert (
        detail.seller_name
        == "example-seller"
    )
    assert (
        detail.auction_status
        == "finished"
    )
    assert (
        detail.starting_price
        == Decimal("500")
    )
    assert (
        detail.current_price_gross
        == Decimal("510")
    )
    assert (
        detail.bid_count
        == 2
    )
    assert (
        detail.condition_text
        == "A little damaged/dirty"
    )
    assert (
        detail.currency
        == "JPY"
    )
    assert (
        detail.detail_status
        == "complete"
    )
