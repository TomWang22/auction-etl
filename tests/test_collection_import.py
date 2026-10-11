"""Purchase-page reading for My collection."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from auction_etl.services.collection_import import (
    bill_usd_rate,
    copy_cost_currency,
    copy_costs,
    extract_pdf_text,
    fill_record_city_catalogs,
    is_collected_music,
    logged_purchase,
    note_with_printed_usd_rate,
    parse_logged_table,
    parse_purchase_export,
    to_usd,
    yen_rate_anchor,
)
from auction_etl.services.collection_shelf import _classify_one


ROOT = Path(__file__).resolve().parents[1]
COLLECTION_PAGE = ROOT / "app" / "pages" / "17_My_Collection.py"


def test_ebay_purchase_page_keeps_the_record_and_drops_the_poster() -> None:
    page = """
    <html><body>
      <div>
        <a href="https://www.ebay.com/itm/326240051289">Teresa Teng LP LFLP-486</a>
        Seller: ryanb714
        <span>$80.00</span>
        <span>Sep 30, 2026</span>
      </div>
      <div>
        <a href="https://www.ebay.com/itm/111111111111">Anita Mui poster</a>
        <span>$20.00</span>
        <span>Sep 30, 2026</span>
      </div>
    </body></html>
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    assert parsed.note == ""
    by_id = {row.external_id: row for row in parsed.purchases}
    record = by_id["326240051289"]
    assert record.paid_amount == Decimal("80.00")
    assert record.paid_currency == "USD"
    assert record.paid_on == date(2026, 9, 30)
    assert record.seller == "ryanb714"
    assert record.catalog_number
    assert is_collected_music(record.title)
    assert is_collected_music(by_id["111111111111"].title) is False


def test_ebay_purchase_csv_reads_item_number_and_total() -> None:
    table = """
Sale Date,Item Title,Item Number,Seller Username,Item Price,Total Price
2026-09-30,Teresa Teng cassette,326240058248,ryanb714,250.00,160.00
""".strip()
    parsed = parse_purchase_export(table)
    assert parsed.source == "ebay"
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "326240058248"
    assert row.paid_amount == Decimal("160.00")
    assert row.paid_on == date(2026, 9, 30)
    assert row.seller == "ryanb714"
    assert is_collected_music(row.title)


def test_buyee_win_page_reads_the_auction_id_and_yen() -> None:
    page = """
    <html><body>
      <div>
        <a href="https://buyee.jp/item/jdirectitems/auction/e1238051623">鄧麗君 LP</a>
        <span>¥12,800</span>
        <span>2026-09-01</span>
      </div>
    </body></html>
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    row = parsed.purchases[0]
    assert row.external_id == "e1238051623"
    assert row.paid_amount == Decimal("12800")
    assert row.paid_currency == "JPY"
    assert row.paid_on == date(2026, 9, 1)


def test_record_city_order_row_matches_on_the_printed_catalog() -> None:
    page = """
    <html><body>
      <p>https://www.recordcity.jp/mypage</p>
      <table>
        <tr><td>LFLP-486</td><td>Anita Mui LP</td><td>¥3,500</td><td>2026-08-01</td></tr>
      </table>
    </body></html>
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "recordcity"
    row = parsed.purchases[0]
    assert row.catalog_number
    assert "LFLP" in row.catalog_number.upper()
    assert row.paid_amount == Decimal("3500")
    assert row.paid_currency == "JPY"
    assert row.paid_on == date(2026, 8, 1)
    assert row.seller == "Record City"


class _Hit:
    def __init__(self, title: str, catno: str, formats: tuple[str, ...]) -> None:
        self.title = title
        self.catno = catno
        self.formats = formats


def test_record_city_history_keeps_the_title_and_yen_without_a_catalog() -> None:
    page = """
    https://www.recordcity.jp/mypage
    7"
    Aizomebashi / Innocent(Jyunsui) JP ¥ 449
    LP
    Airport JP ¥ 6480
    LP
    Momoe Hakusyo JP ¥ 379
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "recordcity"
    by_title = {row.title: row for row in parsed.purchases}
    assert by_title["Airport"].catalog_number is None
    assert by_title["Airport"].paid_amount == Decimal("6480")
    assert by_title["Airport"].paid_currency == "JPY"
    assert 'Format: 7"' in by_title["Aizomebashi / Innocent(Jyunsui)"].billing_note
    assert "Format: LP" in by_title["Momoe Hakusyo"].billing_note
    assert by_title["Momoe Hakusyo"].paid_amount == Decimal("379")


def test_record_city_discogs_fills_one_catalog_and_leaves_a_tie_blank() -> None:
    page = """
    https://www.recordcity.jp/mypage
    LP
    Momoe Hakusyo JP ¥ 379
    LP
    Airport JP ¥ 6480
    """
    parsed = parse_purchase_export(page)
    asked: list[str] = []

    def search(title: str, format_name: str):
        assert format_name == "LP"
        asked.append(title)
        if title == "百恵白書":
            return (
                _Hit("山口百恵 - 百恵白書", "SOLL-114", ("Vinyl", "LP")),
                _Hit("山口百恵 - 百恵白書", "SOLL-114", ("Vinyl", "LP", "Reissue")),
            )
        return (
            _Hit("Teresa Teng - Airport", "28MX-1001", ("Vinyl", "LP")),
            _Hit("Someone Else - Airport", "MR-2259", ("Vinyl", "LP")),
        )

    filled = {row.title: row for row in fill_record_city_catalogs(parsed.purchases, search)}
    assert "百恵白書" in asked
    assert "Momoe Hakusyo" not in asked
    assert filled["Momoe Hakusyo"].catalog_number == "SOLL-114"
    assert "Catalog from Discogs: SOLL-114" in filled["Momoe Hakusyo"].billing_note
    assert filled["Airport"].catalog_number is None


def test_record_city_discogs_uses_the_discogs_title_not_the_shop_spelling() -> None:
    page = """
    https://www.recordcity.jp/mypage
    LP
    Fushicyou Densetsu JP ¥ 980
    LP
    Zessyo JP ¥ 580
    LP
    Sasayakana Yokubou JP ¥ 579
    LP
    Hanazakari JP ¥ 879
    7"
    Cosmos / Saigo no Page JP ¥ 349
    7"
    Hatsukoizoushi/orange Blossom Blues/akaishougeki/kimininamidanokuchizukeo JP ¥ 770
    7"
    Aizomebashi / Innocent(Jyunsui) JP ¥ 449
    """
    parsed = parse_purchase_export(page)

    def search(title: str, format_name: str):
        if title == "不死鳥伝説" and format_name == "LP":
            return (_Hit("山口百恵 - 不死鳥伝説", "38AH 1039～40", ("Vinyl", "LP")),)
        if title == "絶唱" and format_name == "LP":
            return (
                _Hit("山口百恵 - 絶唱", "SOLL 208", ("Vinyl", "LP")),
                _Hit("野坂昭如 - 絶唱! 野坂昭如", "CD-7146", ("Vinyl", "LP")),
            )
        if title == "ささやかな欲望" and format_name == "LP":
            return (
                _Hit("山口百恵 - ささやかな欲望", "SOLL 195", ("Vinyl", "LP")),
                _Hit(
                    "クラウン・オーケストラ - ささやかな欲望・ふたりの旅路 = Big Hit",
                    "GW-3075~6",
                    ("Vinyl", "LP"),
                ),
            )
        if title == "花ざかり" and format_name == "LP":
            return (
                _Hit("山口百恵 - 花ざかり", "25AH 371", ("Vinyl", "LP")),
                _Hit("村下孝蔵 - 花ざかり", "28AH 1811", ("Vinyl", "LP")),
            )
        if title == "秋桜" and format_name == '7"':
            return (
                _Hit("山口百恵 - 秋桜", "06SH 218", ("Vinyl", '7"')),
                _Hit("山口百恵 - 赤い絆／あまりりす／秋桜／寒椿", "08EH 46", ("Vinyl", '7"')),
            )
        if title == "初恋草紙" and format_name == '7"':
            return (
                _Hit("山口百恵 - 初恋草紙", "06SH 108", ("Vinyl", '7"')),
                _Hit(
                    "山口百恵 - 初恋草紙／オレンジ・ブロッサム・ブルース／赤い衝撃／君に涙のくちづけを",
                    "08EH 27",
                    ("Vinyl", '7"'),
                ),
            )
        if title == "愛染橋" and format_name == '7"':
            return (
                _Hit("山口百恵 - 愛染橋", "06SH 682", ("Vinyl", '7"')),
                _Hit("藍恭子 - 愛染橋", "064R 10036", ("Vinyl", '7"')),
            )
        return ()

    filled = {row.title: row for row in fill_record_city_catalogs(parsed.purchases, search)}
    assert filled["Fushicyou Densetsu"].catalog_number == "38AH 1039～40"
    assert filled["Zessyo"].catalog_number == "SOLL 208"
    assert filled["Sasayakana Yokubou"].catalog_number == "SOLL 195"
    assert filled["Hanazakari"].catalog_number is None
    assert filled["Cosmos / Saigo no Page"].catalog_number == "06SH 218"
    four = "Hatsukoizoushi/orange Blossom Blues/akaishougeki/kimininamidanokuchizukeo"
    assert filled[four].catalog_number == "08EH 27"
    assert filled["Aizomebashi / Innocent(Jyunsui)"].catalog_number is None


def test_unknown_page_asks_for_an_order_page() -> None:
    parsed = parse_purchase_export("hello there, nothing to import")
    assert parsed.purchases == ()
    assert "eBay purchase history" in parsed.note


def test_ebay_purchase_history_uses_the_item_price_and_skips_the_address() -> None:
    page = """
    Delivered
    Order date: Sep 15, 2026 · Order total: US $105.00 (Auto-paid) · Order number: 21-15152-88132
    TERESA TENG 鄧麗君 1977 HONG KONG GOLDEN HITS LFLP 497 VINYL
    LP
    Used
    US $105.00
    Sold by: conduit200
    Partially refunded
    Order date: Sep 15, 2026 · Order total: US $62.68 (Auto-paid) · Order number: 16-15162-39158
    TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp
    US $73.13
    Sold by: conduit200
    Ship to: Tom Wang, 123 Main Street
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    by_id = {row.external_id: row for row in parsed.purchases}
    golden = by_id["21-15152-88132"]
    assert golden.paid_amount == Decimal("105.00")
    assert golden.paid_on == date(2026, 9, 15)
    assert golden.seller == "conduit200"
    assert "LFLP" in (golden.catalog_number or "").upper()
    assert "LP" in golden.title
    refunded = by_id["16-15162-39158"]
    assert refunded.paid_amount == Decimal("73.13")
    assert "62.68" in refunded.billing_note
    assert "Tom Wang" not in refunded.title
    assert "Main Street" not in refunded.billing_note
    assert is_collected_music(golden.title)


def test_buyee_order_card_keeps_the_yen_total_and_the_bill() -> None:
    page = """
    R26093000227
    Won date : 29 Sep 2026 14:31
    テレサ・テン（鄧麗君） / 演歌のメッセージ 国内盤(帯付)
    Total Amount 15,375 YEN (US$102.40)
    Shopping Site(ID) JDirectItems Auction(m1233352030)
    Item Price 16,335
    Coupon discount -1,960
    International Shipping Fee 3,860
    Customs Duty 1,852
    Grand Total Payment Amount 23,057YEN
    Ship to: Tom Wang, 123 Main Street
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    row = parsed.purchases[0]
    assert row.external_id == "m1233352030"
    assert row.paid_amount == Decimal("15375")
    assert row.paid_currency == "JPY"
    assert row.paid_on == date(2026, 9, 29)
    assert "演歌" in row.title
    assert "Item price 16,335 JPY" in row.billing_note
    assert "Coupon -1,960 JPY" in row.billing_note
    assert "Grand total 23,057 JPY" in row.billing_note
    assert "US$102.40" in row.billing_note
    assert "Tom Wang" not in row.title
    assert "Main Street" not in row.billing_note
    assert "Order R26093000227" in row.billing_note
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("3860")
    assert costs["customs"] == Decimal("1852")
    assert copy_cost_currency(row.billing_note) == "JPY"
    printed = bill_usd_rate(row.billing_note)
    assert printed is not None
    assert printed[0] == "JPY"
    shipping_usd = to_usd(Decimal("3860"), printed[1])
    customs_usd = to_usd(Decimal("1852"), printed[1])
    assert shipping_usd == Decimal("25.71")
    assert customs_usd == Decimal("12.33")
    assert Decimal("102.40") + shipping_usd + customs_usd == Decimal("140.44")


ONE_AUCTION_INVOICE = """
Item Price
Shopping Site(ID) JDirectItems Auction(m1233352030)
Item Name テレサ・テン（鄧麗君） / 演歌のメッセージ 国内盤(帯付)
Quantity 1
Item Price 16,335
Coupon discount -1,960
Total Amount 14,375
Other Service Fees
Plan Fee 500
Buyee Service Fee 500
Domestic Shipping Fee(From seller to Buyee) 770
Customs Clearance Fee 1,200
Total Amount 2,970
Shipping Expenses
International Shipping Fee 3,860
Total Amount 3,860
Customs Duties and Value-Added Tax
Customs Duty 1,852
Total Amount 1,852
Grand Total Payment Amount 23,057YEN
* Breakdown of Payment amount
2026/09/30 15,375
2026/10/02 6,482
Breakdown of Expenses are shown in Japanese Yen.
Actual billing amount is the currency of your payments, please check credit card/PayPal/Alipay billing for details.
"""


def test_buyee_one_auction_invoice_keeps_labeled_charges_only() -> None:
    parsed = parse_purchase_export(ONE_AUCTION_INVOICE)
    assert parsed.source == "buyee"
    row = parsed.purchases[0]
    assert row.external_id == "m1233352030"
    note = row.billing_note
    assert "国内盤" not in note
    assert "Item Name" not in note
    assert "Japanese Yen" not in note
    assert "PayPal" not in note
    assert "Item price 16,335 JPY" in note
    assert "Coupon -1,960 JPY" in note
    assert "Plan fee 500 JPY" in note
    assert "Service fee 500 JPY" in note
    assert "Domestic shipping 770 JPY" in note
    assert "Customs clearance 1,200 JPY" in note
    assert "International shipping 3,860 JPY" in note
    assert "Customs 1,852 JPY" in note
    assert "Grand total 23,057 JPY" in note
    assert "Payment 2026/09/30 15,375 JPY" in note
    assert "Payment 2026/10/02 6,482 JPY" in note
    assert "Package" not in note
    costs = copy_costs(note)
    assert costs["shipping"] == Decimal("3860")
    assert costs["domestic_shipping"] == Decimal("770")
    assert costs["customs"] == Decimal("1852")
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("500")
    assert costs["clearance"] == Decimal("1200")
    shipping = (costs["shipping"] or 0) + (costs["domestic_shipping"] or 0)
    tax = costs["customs"]
    fees = (
        (costs["plan_fee"] or 0)
        + (costs["service_fee"] or 0)
        + (costs["clearance"] or 0)
    )
    assert shipping == Decimal("4630")
    assert tax == Decimal("1852")
    assert fees == Decimal("2200")
    assert yen_rate_anchor(note) == Decimal("15375")
    with_rate = note_with_printed_usd_rate(
        note,
        usd=Decimal("102.40"),
        yen=Decimal("15375"),
    )
    assert "Item price 16,335 JPY" in with_rate
    printed = bill_usd_rate(with_rate)
    assert printed is not None
    assert printed[0] == "JPY"
    assert to_usd(Decimal("4630"), printed[1]) == Decimal("30.84")
    assert "Drag and drop" not in note


def test_extract_pdf_text_rejects_non_pdf() -> None:
    with pytest.raises(ValueError, match="PDF"):
        extract_pdf_text(b"not a pdf")


def test_buyee_shipping_pdf_keeps_each_records_fees_and_the_package_totals() -> None:
    page = """
    Item Price
    Shopping Site(ID) JDirectItems Auction(l1202474120)
    Item Name 帯付き 国内盤 山口百恵/潮騒/CBS/SONY 25AH428 LP
    Quantity 1
    Item Price 110
    Total Amount 110
    Shopping Site(ID) JDirectItems Auction(w1202458018)
    Item Name 帯 国内盤 山口百恵/ゴールデンフライト/CBS/SONY 25AH250 LP
    Quantity 1
    Item Price 1,650
    Total Amount 1,650
    Other Service Fees
    Plan Fee 5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee) 9,680
    Shipping Expenses
    International Shipping Fee 13,818
    Customs Duty 1,395
    Domestic Shipping Fee 9,680
    JDirectItems Auction (l1202474120)
    帯付き 国内盤 山口百恵/潮騒/CBS/SONY 25AH428 LP
    880
    JDirectItems Auction (w1202458018)
    帯 国内盤 山口百恵/ゴールデンフライト/CBS/SONY 25AH250 LP
    880
    Plan Fee 5,500
    JDirectItems Auction (l1202474120)
    500
    JDirectItems Auction (w1202458018)
    500
    Buyee Service Fee 3,300
    JDirectItems Auction (l1202474120)
    300
    JDirectItems Auction (w1202458018)
    300
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"l1202474120", "w1202458018"}
    quiet = by_id["l1202474120"]
    loud = by_id["w1202458018"]
    assert quiet.paid_amount == Decimal("110")
    assert loud.paid_amount == Decimal("1650")
    assert quiet.paid_currency == "JPY"
    assert "25AH428" in (quiet.catalog_number or "").upper().replace(" ", "").replace("-", "")
    assert "25AH250" in (loud.catalog_number or "").upper().replace(" ", "").replace("-", "")
    assert "Plan fee 500 JPY" in quiet.billing_note
    assert "Service fee 300 JPY" in quiet.billing_note
    assert "Domestic shipping 880 JPY" in quiet.billing_note
    assert "Package international shipping 13818 JPY" in quiet.billing_note
    assert "Package customs 1395 JPY" in loud.billing_note
    assert "13818" not in str(quiet.paid_amount)
    costs = copy_costs(quiet.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["domestic_shipping"] == Decimal("880")
    assert costs["shipping"] is None
    assert costs["customs"] is None


def test_ebay_purchase_with_only_a_short_title_stays_editable() -> None:
    page = """
    Delivered
    Order date: May 16, 2026 · Order total: US $110.72 · Order number: 05-14654-73809
    鄧麗君LP
    US $110.72
    Sold by: chitunhuangggg
    Delivered
    Order date: Feb 14, 2026 · Order total: US $175.21 · Order number: 20-14224-85378
    Teresa Teng Vinyl Record LP Polydor 825 403-1
    US $175.21
    Sold by: professorsells
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    sparse = by_id["05-14654-73809"]
    assert sparse.title == "鄧麗君LP"
    assert sparse.catalog_number is None
    assert sparse.paid_amount == Decimal("110.72")
    assert sparse.paid_on == date(2026, 5, 16)
    assert sparse.seller == "chitunhuangggg"
    detailed = by_id["20-14224-85378"]
    assert "825" in (detailed.catalog_number or "")
    assert detailed.paid_amount == Decimal("175.21")


def test_ebay_order_details_split_item_shipping_and_tax() -> None:
    page = """
    1 item                 $103.50
    Shipping               $5.13
    Tax*                   $6.47
    Order total            $115.10
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    row = parsed.purchases[0]
    assert row.paid_amount == Decimal("103.50")
    assert row.paid_currency == "USD"
    assert "Shipping 5.13 USD" in row.billing_note
    assert "Tax 6.47 USD" in row.billing_note
    assert "Order total 115.10 USD" in row.billing_note


def test_discogs_order_splits_item_shipping_and_tax() -> None:
    page = """
    3736486117
    鄧麗君* - 一見你就笑 (LP, Album) (Yeu Jow Record - AWK-014)
    Media Condition: Near Mint (NM or M-)
    Sleeve Condition: Near Mint (NM or M-)
    Subtotal for 1 item SEK500.00
    Shipping (Standard - PostNord) SEK100.00
    Tax (Sales Tax (MA)) SEK31.25
    Total SEK631.25
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "discogs"
    row = parsed.purchases[0]
    assert row.external_id == "3736486117"
    assert row.paid_amount == Decimal("500.00")
    assert row.paid_currency == "SEK"
    assert "AWK" in (row.catalog_number or "").upper()
    assert "一見你就笑" in row.title
    assert "Shipping 100 SEK" in row.billing_note
    assert "Tax 31.25 SEK" in row.billing_note
    assert "Order total 631.25 SEK" in row.billing_note
    assert row.paid_amount + Decimal("100") + Decimal("31.25") == Decimal("631.25")


def test_logged_table_keeps_what_was_typed() -> None:
    table = """
    Where, Catalog, Title, Paid, Currency, Date
    Disc Union, LFLP-497, , 105.00, USD, 2026-09-15
    Friend, , Airport, 500, JPY, 2024-01-02
    Shop, , Anita Mui poster, 20, USD, 2024-01-03
    """
    by_seller = {row.seller: row for row in parse_logged_table(table)}
    golden = by_seller["Disc Union"]
    assert golden.catalog_number
    assert "LFLP" in golden.catalog_number.upper()
    assert golden.paid_amount == Decimal("105.00")
    assert golden.paid_currency == "USD"
    assert golden.paid_on == date(2026, 9, 15)
    assert golden.external_id.startswith("log:")
    airport = by_seller["Friend"]
    assert airport.title == "Airport"
    assert airport.catalog_number is None
    assert airport.paid_amount == Decimal("500.00")
    assert airport.paid_currency == "JPY"
    assert _logged_status(airport) == "new_copy"
    assert _logged_status(by_seller["Shop"]) == "left_out"
    assert logged_purchase(
        where="",
        catalog="",
        title="",
        paid="",
        currency="USD",
        paid_on=None,
    ) is None


def _logged_status(purchase) -> str:
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={},
    )
    return match.status


def test_collection_page_is_an_intake() -> None:
    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    required = (
        "Bring in purchases",
        "Log a copy",
        "Where it came from",
        "Add one copy",
        "file_uploader",
        "Add these",
        "owned_copy",
        "Your shelf",
        "importlib.reload",
        "Save these bills",
        "Backfill a copy already on the shelf",
        "Fill in the breakdown",
        "Landed is in US dollars",
        "Drop the Buyee invoice PDF",
        "Charge lines only",
        "The record title stays as it is",
        "Drag and drop the Buyee invoice PDF here",
        "Yen stays yen",
        "pdf",
    )
    missing = [value for value in required if value not in source]
    assert not missing, ", ".join(missing)
    assert "st.dialog" not in source
