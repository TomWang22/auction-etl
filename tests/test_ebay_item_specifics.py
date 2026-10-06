"""eBay About this item specifics become the seller condition sheet."""

from __future__ import annotations

import ast
from pathlib import Path

from app.collector_review_support import parse_seller_report
from auction_etl.parsers.ebay_item import specifics_from_html

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"

ITEM_HTML = """
<html><body>
<section>
  <h2>Item specifics</h2>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Condition</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">Used</span></div>
  </div>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Seller Notes</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">“ORIGINAL OBI INSERT”</span></div>
  </div>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Sleeve Grading</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">E-</span></div>
  </div>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Obi Grading</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">E</span></div>
  </div>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Record Grading</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">E/</span></div>
  </div>
  <div class="ux-labels-values">
    <div class="ux-labels-values__labels"><span class="ux-textspans">Catalog Number</span></div>
    <div class="ux-labels-values__values"><span class="ux-textspans">28TR2092</span></div>
  </div>
</section>
</body></html>
"""

JSON_HTML = """
<html><body><script>
{"name":"Seller Notes","value":"\\"ORIGINAL OBI INSERT\\""}
{"name":"Sleeve Grading","values":["E-"]}
{"name":"Obi Grading","value":"E"}
{"name":"Record Grading","value":"E/"}
{"name":"Condition","value":"Used"}
</script></body></html>
"""


def test_item_specifics_become_the_seller_sheet() -> None:
    parsed = specifics_from_html(ITEM_HTML)
    assert parsed["condition"] == "Used"
    assert parsed["seller_notes"] == "ORIGINAL OBI INSERT"
    assert "Condition:" not in parsed["report"]
    report = parse_seller_report(parsed["report"])
    assert report["obi"] is True
    assert report["insert"] is True
    assert report["cover"] == "E-"
    assert report["media"] == "E"


def test_definition_list_uses_each_sellers_grade_names() -> None:
    html = """
    <html><body>
      <h2>Item specifics</h2>
      <dl>
        <dt>Condition</dt><dd>Used: An item that has been used previously.</dd>
        <dt>Cover Condition</dt><dd>E- (Excellent minus) S (Stain)</dd>
        <dt>OBI Condition</dt><dd>E (Excellent) OS (OBI Stain)</dd>
        <dt>Vinyl Condition</dt><dd>E+ (Excellent Plus) hairline</dd>
      </dl>
    </body></html>
    """
    parsed = specifics_from_html(html)
    assert "Condition:" not in parsed["report"]
    report = parse_seller_report(parsed["report"])
    assert report["cover"] == "E-"
    assert report["obi"] is True
    assert report["media"] == "E+"
    assert "insert" not in report


def test_item_specifics_json_is_enough_when_the_table_is_absent() -> None:
    parsed = specifics_from_html(JSON_HTML)
    report = parse_seller_report(parsed["report"])
    assert report["insert"] is True
    assert report["cover"] == "E-"
    assert report["media"] == "E"
    assert "Used" not in parsed["report"]


def test_latest_refresh_reads_item_specifics_for_new_ebay_sales() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    ast.parse(source, filename=str(RUNNER))
    assert "if ebay_new_listing_ids:" in source
    assert '"scripts/crawl_ebay_item_specifics.py"' in source
    assert "Existing item pages are not revisited" in source
