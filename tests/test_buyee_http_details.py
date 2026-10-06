"""Regression tests for Buyee HTTPS detail extraction."""

from __future__ import annotations

from decimal import Decimal

from scripts.crawl_buyee_http_details import (
    contains_aws_waf_challenge,
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
    assert detail.description is None


def test_item_explanation_is_stored_for_later_ingest() -> None:
    """The translated condition sheet is kept with the detail row."""
    html = """
    <html><body>
      <h1>Teresa Teng single</h1>
      <div>Seller</div><div>vin-store</div>
      <div>Opening Time (JST)</div><div>8 Sep 2026 22:05:10</div>
      <div>Closing Time (JST)</div><div>15 Sep 2026 22:05:10</div>
      <div>Starting Price</div><div>320 YEN</div>
      <div>Item Condition</div><div>A little damaged/dirty</div>
      <h2>Item Explanation</h2>
      <div>Condition Details</div>
      <div>Catalog number 07TR-1086</div>
      <div>/ Jacket: EX- Some scuffs, overall in good condition.</div>
      <div>/ Record condition: EX Only minor scuffs.</div>
    </body></html>
    """
    detail = extract_detail_from_html(
        html=html,
        listing_id="l1242006639",
        auction_url="https://buyee.jp/item/jdirectitems/auction/l1242006639",
    )
    assert detail.condition_text == "A little damaged/dirty"
    assert detail.description is not None
    assert "Jacket: EX-" in detail.description
    assert "Record condition: EX" in detail.description

def test_contains_aws_waf_challenge_detects_buyee_challenge() -> None:
    """Recognize the AWS WAF JavaScript page returned by Buyee."""
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title></title>
        <script type="text/javascript">
          window.awsWafCookieDomainList = [
            'www.buyee.jp',
            'buyee.jp'
          ];
          window.gokuProps = {
            "key": "example",
            "iv": "example",
            "context": "example"
          };
        </script>
        <script
          src="https://example.token.awswaf.com/example/challenge.js"
        ></script>
      </head>
      <body>
        <div id="challenge-container"></div>
        <script>
          AwsWafIntegration.getToken().then(() => {
            window.location.reload(true);
          });
        </script>
        <noscript>
          In order to continue, we need to verify that you're not a robot.
        </noscript>
      </body>
    </html>
    """

    assert contains_aws_waf_challenge(html) is True
