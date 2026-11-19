"""Purchase-page reading for My collection."""

import inspect
import io
import shutil
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from auction_etl.services.collection_shelf import PressingChoice
from auction_etl.services.collection_import import (
    _attach_item_prices,
    _buyee_column_customs,
    _buyee_leading_item_prices,
    _buyee_price_bands,
    _buyee_title_for_auction,
    _buyee_visual_amount,
    _buyee_won_list_visual_titles_from_words,
    _merge_buyee_won_title,
    _short_buyee_title,
    arrange_lot_columns,
    buyee_package_display_lines,
    buyee_package_landed_extras,
    buyee_tax_included,
    package_charge_share,
    _with_included_consumption_tax,
    included_consumption_tax,
    bill_text_from_bytes,
    bill_usd_rate,
    combine_bill_pages,
    extract_screenshot_bill_text,
    harvest_screenshot_bills,
    is_screenshot_bytes,
    copy_cost_currency,
    copy_costs,
    copy_refund,
    describe_lot,
    lot_tally,
    purchase_media,
    buyee_invoice_lines,
    hold_import_purchases,
    extract_pdf_text,
    fill_record_city_catalogs,
    is_collected_music,
    logged_purchase,
    note_with_copy_costs,
    note_with_printed_usd_rate,
    parse_logged_table,
    listing_title_is_chrome,
    listing_title_is_ocr_junk,
    listing_catalog_is_structured,
    ocr_promo_item_price,
    owned_copy_shows_on_shelf,
    line_price_replaces_shelf,
    parse_purchase_export,
    parse_purchase_pages,
    ParsedPurchase,
    shelf_charge_amounts,
    to_usd,
    yen_rate_anchor,
    _date_bearing_ocr_lines,
    _ebay_page_is_fragment,
    _buyee_pages_are_one_invoice,
    _extracted_bill_has_charges,
    _buyee_merge_ocr_passes,
    _buyee_ids_are_twins,
)
import app.collector_review_support as collector_review_support
from auction_etl.services.collection_shelf import (
    _classify_one,
    _owned_copy_values,
    _promote_owned_copy,
    _single_bill_pressing,
    anatomy_values_from_choice,
    ensure_anatomy_copy,
    bill_copy_identity,
    pressing_for_edited_catalog,
    propagate_catalog_identity_to_siblings,
    catalog_identity_groups,
    unique_catalog_release_id,
    fill_same_catalog_identities,
    listing_url_for_copy,
    apply_common_record_fields,
    save_billing_note,
    save_copy_anatomy,
    stub_auction_url,
)
from auction_etl.services.discogs_fill import assign_known_pressing
from auction_etl.services.discogs_identity import fold_catalog


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


def test_record_city_order_history_splits_estimated_shipping() -> None:
    page = """
    1 LP JP ¥ 8480 Teresa Teng - Best Hit Album (POLYDOR) (MR 3037) (3224142)
    1 LP JP ¥ 6480 Teresa Teng - Airport (POLYDOR) (MR 2259) (3390905)
    [Subtotal] JP ¥ 14960
    [Estimated Shipping Fee] JP ¥ 2808
    [Total] JP ¥ 17768
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "recordcity"
    by_id = {row.external_id: row for row in parsed.purchases}
    best = by_id["3224142"]
    airport = by_id["3390905"]
    assert best.paid_amount == Decimal("8480")
    assert airport.paid_amount == Decimal("6480")
    assert best.paid_currency == "JPY"
    assert "MR" in (best.catalog_number or "").upper()
    assert "3037" in (best.catalog_number or "")
    assert "2259" in (airport.catalog_number or "")
    assert best.title.startswith("Teresa Teng - Best Hit Album")
    ships = [
        copy_costs(best.billing_note)["shipping"],
        copy_costs(airport.billing_note)["shipping"],
    ]
    assert all(amount is not None for amount in ships)
    assert sum(ships, Decimal("0")) == Decimal("2808")
    assert "Order total 17768 JPY" in best.billing_note
    assert "Format: LP" in best.billing_note
    assert purchase_media(best.title, best.billing_note) == "LP"
    match = _classify_one(
        airport,
        listings={},
        owned=set(),
        purchased={("ebay", "226500068370")},
        owned_catalogs={fold_catalog("MR-2259")},
        pressings={},
    )
    assert match.status == "new_copy"
    assert match.listing_id == ""


def test_record_city_bill_backfills_the_owned_copy_without_the_line_id() -> None:
    """A receipt that lost the shop id still finds the copy by catalog and yen."""

    purchase = ParsedPurchase(
        source="recordcity",
        external_id="SOLL170:2025-07-22:579.00",
        title="Momoe Yamaguchi - Hit Zenkyokusyu",
        seller="Record City",
        paid_amount=Decimal("579"),
        paid_currency="JPY",
        paid_on=date(2025, 7, 22),
        catalog_number="SOLL-170",
        billing_note="Shipping 400 JPY\nOrder total 27719 JPY",
    )
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs={fold_catalog("SOLL-170")},
        pressings={},
        owned_rows=[
            {
                "marketplace": "recordcity",
                "listing_id": "2503945",
                "catalog_number": "SOLL-170",
                "paid": Decimal("579"),
                "paid_on": date(2025, 7, 22),
            }
        ],
    )
    assert match.status == "backfill"
    assert match.marketplace == "recordcity"
    assert match.listing_id == "2503945"


def test_record_city_invoice_keeps_line_ids_and_splits_shipping() -> None:
    """A long Record City history uses [Shipping] and [Invoice Total]."""

    page = """
    1 LP JP ¥ 180 Tomoko/Momoe Yamaguchi - Shinkiroku (CBS/SONY) (SOLL 175) (3211116)
    1 LP JP ¥ 120 Momoe Yamaguchi, Tomokazu Miura - Zesshou (CBS/SONY) (25AH 428) (2943145)
    1 LP JP ¥ 450 Momoe Yamaguchi - Best Of Best (CBS/SONY) (25AH 1-10) (2474002)
    [Purchase Total] JP ¥ 750
    [Shipping] JP ¥ 2700
    [Invoice Total] JP ¥ 3450
    """
    assert _extracted_bill_has_charges([page]) is True
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"3211116", "2943145", "2474002"}
    assert by_id["3211116"].paid_amount == Decimal("180")
    assert by_id["3211116"].catalog_number == "SOLL-175"
    assert by_id["2943145"].catalog_number == "25AH-428"
    assert by_id["2474002"].catalog_number == "25AH-1~10"
    assert by_id["2474002"].paid_amount == Decimal("450")
    ships = [copy_costs(row.billing_note)["shipping"] for row in parsed.purchases]
    assert all(amount is not None for amount in ships)
    assert sum(ships, Decimal("0")) == Decimal("2700")
    assert "Order total 3450 JPY" in by_id["3211116"].billing_note
    assert "Purchase" not in by_id["3211116"].billing_note


def test_record_city_order_keeps_every_lp_and_the_order_date() -> None:
    """July 22, 2025 is the order time. The LP before the totals is still a copy."""

    page = """
    [Order Number] 1695240418
    [Order Time] July 22, 2025 14:12:17
    [Payment Method] PayPal
    1 LP JP ¥ 549 Momoe Yamaguchi - Utaitsugareteiku 73 77 (CBS SONY) (40AH1167-8) (3563964)
    1 LP JP ¥ 1780 Momoe Yamaguchi - Utai Tsugarete yuku 78-80 (CBS SONY) (40AH 1169-70) (3532885)
    1 LP JP ¥ 380 Momoe Yamaguchi - Akai Giawaku (CBS SONY) (SOLL 218) (3552212)
    1 LP JP ¥ 680 Momoe Yamaguchi - Akai Giawaku (CBS SONY) (SOLL 218) (2587202)
    1 LP JP ¥ 580 Momoe Yamaguchi - Hit Zenkyokusyu (CBS SONY) (25AH81) (2562286)
    (Purchase Total] JP ¥ 3969
    [Shipping] JP ¥ 23750
    [Invoice Total] JP ¥ 27719
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 5
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"3563964", "3532885", "3552212", "2587202", "2562286"}
    assert by_id["2562286"].paid_on == date(2025, 7, 22)
    assert by_id["2562286"].order_id == "1695240418"
    assert by_id["3563964"].catalog_number == "40AH-1167~8"
    assert by_id["3532885"].catalog_number == "40AH-1169~70"
    ships = [copy_costs(row.billing_note)["shipping"] for row in parsed.purchases]
    assert sum(ships, Decimal("0")) == Decimal("23750")
    assert "Order total 27719 JPY" in by_id["2562286"].billing_note


def test_record_city_smudged_yen_still_counts_every_lp() -> None:
    """A yen mark read as JPY or JPV¥ is still that LP, not part of the line above."""

    page = """
    [Order Number] 1695240418
    [Order Time] July 22, 2025 14:12:17
    1 LP JP ¥ 1380 Tomokazu Miura/Momoe Yamaguchi - Shunkinsho (CBS SONY) (25AH-191) (3211316)
    1 LP JP¥<480 Momoe Yamaguchi - Zessyo (CBS SONY) (SOLL 208) (3600619)
    1 LP JPY¥579 Momoe Yamaguchi - Hit Zenkyokusyu (CBS SONY) (SOLL-170) (2503945)
    1 LP JPY 780 Momoe Yamaguchi - Aoi Kajitsu (CBS SONY) (SOLL 57) (3452161)
    1 LP JPV¥980 Momoe Yamaguchi - Momoe no Kisetsu (CBS SONY) (SOLL-65) (3452162)
    1 LP JP¥5S79 Momoe Yamaguchi - Jyu Nanasai (CBS SONY) (SOLL 213) (3452172)
    [Shipping] JP ¥ 23750
    [Invoice Total] JP ¥ 61213
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 6
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["3600619"].paid_amount == Decimal("480")
    assert by_id["2503945"].paid_amount == Decimal("579")
    assert by_id["3452161"].paid_amount == Decimal("780")
    assert by_id["3452162"].paid_amount == Decimal("980")
    assert by_id["3452172"].paid_amount == Decimal("579")
    assert "1 LP" not in by_id["3211316"].title
    assert sum(row.paid_amount for row in parsed.purchases) == Decimal("4778")


def test_record_city_order_keeps_the_seven_inch_singles() -> None:
    """A 7-inch line is a copy. The LPs in the same order do not replace it."""

    page = """
    [Order Number] 7880514
    [Order Time] August 13, 2025 11:54:25
    [Payment Method] Credit card
    1 7" JP ¥ 449 Momoe Yamaguchi - Aizomebashi / Innocent(Jyunsui) (CBS SONY) (06SH 662) (3562328)
    1 7" JP ¥ 770 Momoe Yamaguchi - Hatsukoi (CBS/Sony) (06EH 27) (1790886)
    1 7" JP ¥ 820 Momoe Yamaguchi - Hatsukoi (CBS/Sony) (06EH 27) (1419252)
    1 LP JP ¥ 579 Momoe Yamaguchi - Sasayakana Yokubou (CBS SONY) (SOLL 195) (2800668)
    1 LP JP ¥ 480 Momoe Yamaguchi - Sasayakana Yokubou (CBS SONY) (SOLL 195) (3486632)
    [Purchase Total] JP ¥ 3098
    [Shipping] JP ¥ 10416
    [Invoice Total] JP ¥ 13514
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 5
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"3562328", "1790886", "1419252", "2800668", "3486632"}
    single = by_id["3562328"]
    assert single.paid_on == date(2025, 8, 13)
    assert single.order_id == "7880514"
    assert single.catalog_number == "06SH-662"
    assert 'Format: 7"' in single.billing_note
    assert purchase_media(single.title, single.billing_note) == "EP_7_INCH"
    assert "Format: LP" in by_id["2800668"].billing_note
    assert by_id["1790886"].catalog_number == by_id["1419252"].catalog_number == "06EH-27"
    ships = [copy_costs(row.billing_note)["shipping"] for row in parsed.purchases]
    assert sum(ships, Decimal("0")) == Decimal("10416")


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


BUYEE_ENKA_OCR = """
Shopping Site(ID) JDirectItems Auction(m1
233352030)
Item Name テレサ・テン / 演歌のメッセージ 国内盤 (帯付)
Quantity 1
Item Price 16,335
Coupon discount -1,960
Total Amount 14,375
Other Service Fees
Plan Fee 500
Buyee Service Fee 500
Domestic Shipping Fee(From seller to Buyee) 770
Shipping Expenses
International Shipping Fee 3,860
Total Amount 3,860
"""


def test_buyee_screenshot_ocr_updates_the_auction_already_on_the_shelf() -> None:
    """A wrapped JDirectItems id is still Enka. That bill backfills, it does not add a copy."""

    parsed = parse_purchase_export(BUYEE_ENKA_OCR)
    assert parsed.source == "buyee"
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "m1233352030"
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("3860")
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("500")
    assert costs["domestic_shipping"] == Decimal("770")
    assert _extracted_bill_has_charges([BUYEE_ENKA_OCR]) is True
    match = _classify_one(
        row,
        listings={},
        owned=set(),
        purchased={("buyee", "m1233352030")},
        owned_catalogs=set(),
        pressings={},
    )
    assert match.status == "backfill"
    assert match.marketplace == "buyee"
    assert match.listing_id == "m1233352030"
    one_line = (
        "Shopping Site(—ID) _|JDirectItems Auction(m1233352030) |__ "
        "ItemName Coupon discount -1,960) Total Amount 14,375) "
        "(Currency: YEN) Other Service Fees Plan Fee 500 Buyee Service Fee 500 "
        "Domestic Shipping Fee(From seller to Buyee) 770 Customs Clearance Fee 1,200 "
        "Total Amount 2,970 Shipping Expenses International Shipping Fee 3,860 "
        "Customs Duty 1,852 Grand Total Payment Amount 23,057YEN"
    )
    flat = parse_purchase_export(one_line).purchases[0]
    assert flat.external_id == "m1233352030"
    costs = copy_costs(flat.billing_note)
    assert costs["shipping"] == Decimal("3860")
    assert costs["domestic_shipping"] == Decimal("770")
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("500")
    assert costs["clearance"] == Decimal("1200")
    assert costs["customs"] == Decimal("1852")
    shipping, tax, fees = shelf_charge_amounts(
        billing_note=flat.billing_note,
    )
    assert shipping == Decimal("4630")
    assert tax == Decimal("1852")
    assert fees == Decimal("2200")


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


def test_buyee_single_ep_uses_the_400_hammer_not_the_first_card_charge() -> None:
    """9/05 is one EP. 1,200 is item+plan+service, not the hammer. 6,008 is postage."""

    page = """
    Item Price
    Shopping Site(ID) JDirectItems Auction(n1194698212)
    Item Name 【EP】山口百恵「夢先案内人」「イミテーション・ゴールド」ゴールデン・シングル
    Quantity 1
    Item Price 400
    Total Amount 400
    Other Service Fees
    Plan Fee 500
    Buyee Service Fee 300
    Domestic Shipping Fee(From seller to Buyee) 180
    Total Amount 980
    Shipping Expenses
    International Shipping Fee 6,008
    Total Amount 6,008
    Customs Duties and Value-Added Tax
    Customs Duty 80
    Total Amount 80
    Grand Total Payment Amount
    7,468YEN
    * Breakdown of Payment amount
    2025/08/29 1,200
    2025/09/05 6,268
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "n1194698212"
    assert row.paid_amount == Decimal("400")
    assert row.paid_on == date(2025, 9, 5)
    assert "夢先案内人" in (row.title or "")
    assert purchase_media(row.title) == "EP_7_INCH"
    costs = copy_costs(row.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["domestic_shipping"] == Decimal("180")
    assert costs["shipping"] == Decimal("6008")
    assert costs["customs"] == Decimal("80")
    assert "Grand total 7,468 JPY" in row.billing_note
    assert "Payment 2025/08/29 1,200 JPY" in row.billing_note
    assert "Payment 2025/09/05 6,268 JPY" in row.billing_note
    assert "Package" not in row.billing_note
    assert (
        row.paid_amount
        + costs["plan_fee"]
        + costs["service_fee"]
        + costs["domestic_shipping"]
        + costs["shipping"]
        + costs["customs"]
        == Decimal("7468")
    )


def test_buyee_single_ep_column_notes_still_keep_the_400_hammer() -> None:
    """Tesseract drops the right-hand 400 and keeps the 1,200 card charge and 6,008 postage."""

    page = """
    JDirectItems Auction(n1194698212)
    (EP) 山口百恵「夢先案内人」「イミテーション・ゴールド」ゴールデン・シングル
    Quantity
    Shipping Expenses
    International Shipping Fee
    Customs Duties and Value-Added Tax
    Grand Total Payment Amount
    7.468YEN
    * Breakdown of Payment amount
    2025/08/29 1,200
    2025/09/05 6,268
    Column item 400
    Column item 300
    Column item 980
    Column item 6008
    Column item 1200
    Column item 6268
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.external_id == "n1194698212"
    assert row.paid_amount == Decimal("400")
    assert row.paid_on == date(2025, 9, 5)
    costs = copy_costs(row.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["domestic_shipping"] == Decimal("180")
    assert costs["shipping"] == Decimal("6008")
    assert costs["customs"] == Decimal("80")
    assert (
        row.paid_amount
        + costs["plan_fee"]
        + costs["service_fee"]
        + costs["domestic_shipping"]
        + costs["shipping"]
        + costs["customs"]
        == Decimal("7468")
    )


def test_buyee_stacked_payment_dates_are_not_a_2025_yen_hammer() -> None:
    """OCR puts 2025/09/05 under 2025/08/29. The year is not the item price."""

    page = """
    JDirectItems Auction(n1194698212)
    【EP】山口百恵「夢先案内人」「イミテーション・ゴールド」ゴールデン・シングル
    International Shipping Fee 6,008
    Grand Total Payment Amount 7,468YEN
    * Breakdown of Payment amount
    2025/08/29
    2025/09/05
    1,200
    6,268
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.external_id == "n1194698212"
    assert row.paid_amount != Decimal("2025")
    assert row.paid_amount == Decimal("400")
    assert row.paid_on == date(2025, 9, 5)
    costs = copy_costs(row.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["shipping"] == Decimal("6008")


def test_buyee_single_ep_does_not_treat_the_shipping_card_charge_as_postage() -> None:
    """6,268 is the second card charge (domestic+intl+customs), not international."""

    page = """
    JDirectItems Auction(n1194698212)
    (EP) 山口百恵「夢先案内人」ゴールデン・シングル
    Quantity
    International Shipping Fee
    Grand Total Payment Amount
    7.468YEN
    * Breakdown of Payment amount
    2025/08/29 1,200
    Column item 400
    Column item 300
    Column item 980
    Column item 6008
    Column item 1200
    Column item 6268
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    costs = copy_costs(row.billing_note)
    assert row.paid_amount == Decimal("400")
    assert costs["shipping"] == Decimal("6008")
    assert costs["customs"] == Decimal("80")


def _assert_pearl_color_compact_ep(page: str) -> None:
    """375 hammer + 500/300/185 + 3,217 postage = 4,577. No customs on this bill."""

    assert _extracted_bill_has_charges([page]) is True
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "d1195885358"
    assert row.paid_amount == Decimal("375")
    costs = copy_costs(row.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["domestic_shipping"] == Decimal("185")
    assert costs["shipping"] == Decimal("3217")
    assert costs["customs"] is None
    assert "Customs 0" not in (row.billing_note or "")
    assert (
        row.paid_amount
        + costs["plan_fee"]
        + costs["service_fee"]
        + costs["domestic_shipping"]
        + costs["shipping"]
        == Decimal("4577")
    )


def test_buyee_invoice_without_jdirectitems_is_still_a_bill() -> None:
    """Messy OCR often drops JDirectItems and keeps Auction(id) plus the fee table."""

    page = """
    Item Price
    Shopping Site(ID) Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて/甘い裏切り/横須賀ストーリー/いま目覚めた子供のように '76
    コンパクト盤 即決 EPレコード 50810
    Quantity 1
    Item Price 375
    Total Amount 375
    Other Service Fees
    Plan Fee 500
    Buyee Service Fee 300
    Domestic Shipping Fee(From seller to Buyee) 185
    Total Amount 985
    Shipping Expenses
    International Shipping Fee 3,217
    Total Amount 3,217
    Grand Total Payment Amount
    4,577YEN
    """
    _assert_pearl_color_compact_ep(page)


def test_buyee_truncated_fee_labels_still_read_the_one_copy_bill() -> None:
    """Tesseract clips Plan/Buyee/Domestic/International on a tall fee table."""

    page = """
    Shopping Site(ID) Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて '76 コンパクト盤 EP 50810
    Quantity 1
    Item Price 375
    Total Amount 375
    Other Service Fees
    n Fee 500
    jee Service Fee 300
    nestic Shipping Fee(From seller to Buyee) 185
    Total Amount 985
    Shipping Expenses
    rnational Shipping Fee 3,217
    Total Amount 3,217
    Grand Total Payment Amount
    4,577YEN
    """
    _assert_pearl_color_compact_ep(page)


def test_buyee_one_copy_column_notes_rebuild_the_375_invoice() -> None:
    """The wide read keeps the auction and grand total; the yen column still has the rest."""

    page = """
    Shopping Site(ID) JDirectItems Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて '76 コンパクト盤 EP 50810
    Other Service Fees
    n Fee
    ree Service Fee
    nestic Shipping Fee(From seller to Buyee)
    Total Amount 985
    Shipping Expenses
    rnational Shipping Fee
    Grand Total Payment Amount
    4,577YEN
    Column item 375
    Column item 375
    Column item 500
    Column item 300
    Column item 185
    Column item 985
    Column item 3217
    Column item 3217
    """
    _assert_pearl_color_compact_ep(page)


def test_buyee_other_fees_total_is_not_domestic_shipping() -> None:
    """985 is plan+service+domestic. 185 is the postage from seller to Buyee."""

    page = """
    Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて
    Item Price 375
    Other Service Fees
    Plan Fee 500
    Buyee Service Fee 300
    Domestic Shipping Fee 985
    Total Amount 985
    International Shipping Fee 3,217
    Grand Total Payment Amount 4,577YEN
    """
    _assert_pearl_color_compact_ep(page)


def test_buyee_international_cannot_exceed_grand_total() -> None:
    """OCR junk 27 and the 985 other-fees total must not glue into 27,985 postage."""

    page = """
    JDirectItems Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて '76 コンパクト盤 EP 50810
    Item Price 375
    Plan Fee 500
    Buyee Service Fee 300
    Domestic Shipping Fee 185
    27/57
    International Shipping Fee
    Total Amount 985
    27
    Grand Total Payment Amount 4,577YEN
    Column item 3217
    """
    _assert_pearl_color_compact_ep(page)


def test_buyee_ocr_passes_merge_auction_and_fee_column() -> None:
    """One Tesseract pass keeps the id; the sparse pass keeps the right-hand yen."""

    auction_pass = """
    Item Price
    Shopping Site(ID) JDirectItems Auction(d1195885358)
    Item Name 山口百恵 パールカラーにゆれて '76 コンパクト盤 EP 50810
    Grand Total Payment Amount
    4,577YEN
    """
    amount_pass = """
    Item Price 375
    n Fee 500
    jee Service Fee 300
    nestic Shipping Fee 185
    rnational Shipping Fee 3,217
    Total Amount 3,217
    """
    merged = _buyee_merge_ocr_passes(auction_pass, amount_pass)
    _assert_pearl_color_compact_ep(merged)


def test_buyee_digit_only_auction_id_still_reads_the_two_disc_lp() -> None:
    """Buyee prints Auction(1196236907) with no letter. 1.500 is 1,500 yen."""

    page = """
    Item Price
    Shopping Site(ID) JDirectItems Auction(1196236907)
    Item Name [7k42] 2枚組 LP 『山口百恵 / 歌い継がれてゆく 歌のように '73~'77』
    Quantity
    1
    Item Price
    1.500
    Total Amount
    1.500
    Other Service Fees
    Plan Fee
    500
    Buyee Service Fee
    300
    Domestic Shipping Fee(From seller to Buyee)
    920
    Total Amount
    1,720
    Shipping Expenses
    International Shipping Fee
    3,772
    Total Amount
    3,772
    Grand Total Payment Amount
    6,992YEN
    """
    assert _extracted_bill_has_charges([page]) is True
    parsed = parse_purchase_export(page)
    assert parsed.source == "buyee"
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "1196236907"
    assert row.paid_amount == Decimal("1500")
    assert "山口百恵" in (row.title or "")
    costs = copy_costs(row.billing_note)
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("300")
    assert costs["domestic_shipping"] == Decimal("920")
    assert costs["shipping"] == Decimal("3772")
    assert costs["customs"] is None
    assert (
        row.paid_amount
        + costs["plan_fee"]
        + costs["service_fee"]
        + costs["domestic_shipping"]
        + costs["shipping"]
        == Decimal("6992")
    )


def test_buyee_lettered_id_is_a_twin_of_the_digit_only_print() -> None:
    assert _buyee_ids_are_twins("u1196236907", "1196236907")
    assert _buyee_ids_are_twins("1196236907", "d1196236907")
    assert not _buyee_ids_are_twins("u1196236907", "1196236908")


def test_buyee_invoice_keeps_domestic_and_international_as_their_own_lines() -> None:
    """eBay is one Shipping amount. Buyee prints domestic and international separately."""

    note = parse_purchase_export(ONE_AUCTION_INVOICE).purchases[0].billing_note
    lines = dict(buyee_invoice_lines(note))
    assert lines["Domestic"] == Decimal("770")
    assert lines["International"] == Decimal("3860")
    assert lines["Plan fee"] == Decimal("500")
    assert lines["Service fee"] == Decimal("500")
    assert lines["Clearance"] == Decimal("1200")
    assert lines["Customs"] == Decimal("1852")
    ebay = buyee_invoice_lines("Shipping 6.50 USD\nTax 10.00 USD")
    assert ebay == ()


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
    assert quiet.package_shipping == Decimal("13818")
    assert loud.package_tax == Decimal("1395")
    assert "13818" not in str(quiet.paid_amount)
    assert "13818" not in quiet.billing_note
    quiet_costs = copy_costs(quiet.billing_note)
    loud_costs = copy_costs(loud.billing_note)
    assert quiet_costs["plan_fee"] == Decimal("500")
    assert quiet_costs["service_fee"] == Decimal("300")
    assert quiet_costs["domestic_shipping"] == Decimal("880")
    assert quiet_costs["shipping"] is None
    assert loud_costs["shipping"] is None
    assert quiet_costs["customs"] is None
    assert loud_costs["customs"] is None


def test_buyee_two_screenshots_split_the_package_fees_across_both_lps() -> None:
    """A 2-LP Buyee invoice is an item screenshot plus a fee screenshot."""

    first = """
    Item Price
    Shopping Site(ID) JDirectItems Auction(m1230351293)
    Item Name 【希少品】☆香港盤☆LP/鄧麗君 テレサ・テン/鄧麗君十五週年/817 132/817 133/見開き/2LP
    Quantity 1
    Item Price 38,800
    Total Amount 38,800
    """
    second = """
    Shopping Site(ID) JDirectItems Auction(h1230354706)
    Item Name 【希少品】☆香港盤☆LP/TERESA TENG GREATEST HITSVOL.7/817
    Quantity 1
    Item Price 36,500
    Total Amount 36,500
    """
    fees = """
    Other Service Fees
    Plan Fee 1,000
    Buyee Service Fee 1,000
    Domestic Shipping Fee(From seller to Buyee) 1,960
    Customs Clearance Fee 1,200
    Total Amount 5,160
    (Currency: YEN)
    Shipping Expenses
    International Shipping Fee 6,952
    Total Amount 6,952
    """
    parsed = parse_purchase_pages([first, second, fees])
    assert parsed.source == "buyee"
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"m1230351293", "h1230354706"}
    assert by_id["m1230351293"].paid_amount == Decimal("38800")
    assert by_id["h1230354706"].paid_amount == Decimal("36500")
    assert "817" in (by_id["m1230351293"].title)
    costs = [copy_costs(row.billing_note) for row in by_id.values()]

    def _sum(key: str) -> Decimal:
        return sum((row[key] or Decimal("0") for row in costs), Decimal("0"))

    assert by_id["m1230351293"].package_shipping == Decimal("6952")
    assert _sum("shipping") == Decimal("0")
    assert _sum("plan_fee") == Decimal("1000")
    assert _sum("service_fee") == Decimal("1000")
    assert _sum("domestic_shipping") == Decimal("1960")
    assert _sum("clearance") == Decimal("1200")
    assert _extracted_bill_has_charges([first, second, fees]) is True
    alone = parse_purchase_pages([first + second, fees])
    assert {row.external_id for row in alone.purchases} == set(by_id)


def test_buyee_screenshot_ocr_joins_the_fee_page_when_labels_and_amounts_split() -> None:
    """The item screenshot stops at the fee heading. Amounts are the next picture."""

    items = """
    Shopping Site(—ID) JDirectItems Auction(m1 230351293) Item Name
    (irik) SEH LP/ BIB FL + Fy / SBR GF /817 132/817 133/ Fup & /2LP/ 38,800 38,800
    Shopping Site(ID) JDirectItems Auction(h1230354706) Item Name
    TERESA TENG GREATEST HITSVOL.7 36,500 36,500
    Other Service Fees
    """
    fees = """
    Other Service Fees
    Plan Fee
    1,000
    Buyee Service Fee
    1,000
    Domestic Shipping Fee(From seller to Buyee)
    1,960
    Customs Clearance Fee
    1,200
    Total Amount
    5,160
    Shipping Expenses
    International Shipping Fee
    6,952
    Total Amount
    6,952
    """
    assert _extracted_bill_has_charges([items, fees]) is True
    parsed = parse_purchase_pages([items, fees])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"m1230351293", "h1230354706"}
    assert by_id["m1230351293"].paid_amount == Decimal("38800")
    assert by_id["h1230354706"].paid_amount == Decimal("36500")
    assert "GREATEST" in by_id["h1230354706"].title
    costs = [copy_costs(row.billing_note) for row in by_id.values()]

    def _sum(key: str) -> Decimal:
        return sum((row[key] or Decimal("0") for row in costs), Decimal("0"))

    assert _sum("plan_fee") == Decimal("1000")
    assert _sum("service_fee") == Decimal("1000")
    assert _sum("domestic_shipping") == Decimal("1960")
    assert _sum("clearance") == Decimal("1200")
    assert by_id["m1230351293"].package_shipping == Decimal("6952")
    assert _sum("shipping") == Decimal("0")


def test_buyee_fee_screenshot_survives_plan_pee_and_dotted_thousands() -> None:
    """Tesseract reads Plan Fee 1,000 as Plan Pee 1.000) and glues BuyeeServiceFee."""

    items = (
        "Shopping Site(—ID) _|JDirectItems Auction(m1 230351293) Item Name "
        "(irik) SEH LP/ BIB FL + Fy / SBR GF /817 132/817 133/ Fup & /2LP/ "
        "AeeR Ein / fe ely OD 38,800 38,800 "
        "Shopping Site(ID) _|JDirectItems Auction(h1230354706) Item Name "
        "TERESA TENG GREATEST HITSVOL.7 Item Price 36,500 Total Amount 36,500"
    )
    fees = """
    Plan Pee 1.000)
    BuyeeServiceFee 1000)
    Domestic Shipping Fee(From sellertoBuyee) 1.960)
    Customs Clearance Fee 1.200)
    International Shipping Fee
    6.952
    """
    assert _extracted_bill_has_charges([items, fees]) is True
    parsed = parse_purchase_pages([items, fees])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["m1230351293"].paid_amount == Decimal("38800")
    assert by_id["h1230354706"].paid_amount == Decimal("36500")
    costs = [copy_costs(row.billing_note) for row in by_id.values()]

    def _sum(key: str) -> Decimal:
        return sum((row[key] or Decimal("0") for row in costs), Decimal("0"))

    assert _sum("plan_fee") == Decimal("1000")
    assert _sum("service_fee") == Decimal("1000")
    assert _sum("domestic_shipping") == Decimal("1960")
    assert _sum("clearance") == Decimal("1200")
    assert by_id["m1230351293"].package_shipping == Decimal("6952")
    assert _sum("shipping") == Decimal("0")


def test_buyee_invoice_uses_the_breakdown_and_not_the_grand_total() -> None:
    """¥95,476 is the payment total. Postage is ¥6,952, split with the printed fees."""

    summary = """
    Shopping Site(ID) JDirectItems Auction(m1230351293)
    Item Name 鄧麗君十五週年 817 132 817 133 2LP
    Quantity 1
    Item Price 38,800
    Total Amount 38,800
    Shopping Site(ID) JDirectItems Auction(h1230354706)
    Item Name TERESA TENG GREATEST HITSVOL.7
    Quantity 1
    Item Price 36,500
    Total Amount 36,500
    Other Service Fees
    Plan Fee 1,000
    Buyee Service Fee 1,000
    Domestic Shipping Fee(From seller to Buyee) 1,960
    Customs Clearance Fee 1,200
    Total Amount 5,160
    Shipping Expenses
    International Shipping Fee 6,952
    Total Amount 6,952
    Customs Duties and Value-Added Tax
    Customs Duty 8,064
    Total Amount 8,064
    Grand Total Payment Amount
    95,476YEN
    """
    breakdown = """
    Domestic Shipping Fee 1,960
    JDirectItems Auction(m1230351293)
    980
    JDirectItems Auction(h1230354706)
    980
    Plan Fee 1,000
    JDirectItems Auction(m1230351293)
    500
    JDirectItems Auction(h1230354706)
    500
    Buyee Service Fee 1,000
    JDirectItems Auction(m1230351293)
    500
    JDirectItems Auction(h1230354706)
    500
    """
    parsed = parse_purchase_pages([summary, breakdown])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"m1230351293", "h1230354706"}
    first = copy_costs(by_id["m1230351293"].billing_note)
    second = copy_costs(by_id["h1230354706"].billing_note)
    assert first["plan_fee"] == Decimal("500")
    assert second["plan_fee"] == Decimal("500")
    assert first["service_fee"] == Decimal("500")
    assert second["service_fee"] == Decimal("500")
    assert first["domestic_shipping"] == Decimal("980")
    assert second["domestic_shipping"] == Decimal("980")
    assert by_id["m1230351293"].package_shipping == Decimal("6952")
    assert by_id["m1230351293"].package_tax == Decimal("8064")
    assert first["shipping"] is None
    assert second["customs"] is None
    assert (first["clearance"] or 0) + (second["clearance"] or 0) == Decimal("1200")
    for costs in (first, second):
        postage = (costs["shipping"] or 0) + (costs["domestic_shipping"] or 0)
        assert postage < Decimal("20000")
    assert "95476" not in by_id["m1230351293"].billing_note
    assert by_id["m1230351293"].package_total == Decimal("95476")
    missing_postage = summary.replace("International Shipping Fee 6,952", "International Shipping Fee")
    missing_postage = missing_postage.replace("Total Amount 6,952", "Total Amount")
    missed = parse_purchase_pages([missing_postage])
    assert missed.purchases
    for row in missed.purchases:
        assert copy_costs(row.billing_note)["shipping"] is None

    alone = parse_purchase_pages([summary])
    assert alone.purchases[0].package_shipping == Decimal("6952")
    alone_costs = [copy_costs(row.billing_note) for row in alone.purchases]
    assert sum((row["shipping"] or 0 for row in alone_costs), Decimal("0")) == Decimal("0")
    rewritten = note_with_copy_costs(
        by_id["m1230351293"].billing_note,
        shipping=first["shipping"],
        domestic_shipping=first["domestic_shipping"],
    )
    assert copy_costs(rewritten)["shipping"] == first["shipping"]


def test_buyee_long_invoice_keeps_every_auction_past_the_fee_heading() -> None:
    """Six LPs across several screenshots are one bill. A continuation still joins."""

    items = """
    Shopping Site(ID) JDirectItems Auction(f 1204890335)
    Item Name ベストヒッツ CBS/SONY SOLL170 LP
    Quantity 1
    Item Price 440
    Total Amount 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Quantity 1
    Item Price 1,001
    Total Amount 1,001
    Shopping Site(ID) JDirectItems Auction(ul 204905847)
    Item Name 16才のテーマ CBS/SONY SOLL141 LP
    Quantity 1
    Item Price 440
    Total Amount 440
    """
    later = """
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Quantity 1
    Item Price 1,001
    Total Amount 1,001
    Shopping Site(ID) JDirectItems Auction(j 1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS S GAME CBS/SONY 25AH974 LP
    Quantity 1
    Item Price 4,290
    Total Amount 4,290
    Shopping Site(ID) JDirectItems Auction(b1 205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Quantity 1
    Item Price 671
    Total Amount 671
    """
    fees = """
    Other Service Fees
    Plan Fee 3,000
    Buyee Service Fee 1,800
    Domestic Shipping Fee(From seller to Buyee) 4,400
    Total Amount 9,200
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    """
    breakdown = """
    Domestic Shipping Fee
    SOLL170 LP 880
    JDirectItems Auction(f1204890335)
    70AH1141 LP 880
    JDirectItems Auction(r1205744646)
    SOLL141 LP 880
    JDirectItems Auction(u1204905847)
    70AH1141 LP 880
    JDirectItems Auction(j1205768066)
    70AH1141 LP 880
    JDirectItems Auction(b1205857894)
    Plan Fee
    SOLL170 LP 500
    JDirectItems Auction(f1204890335)
    500
    JDirectItems Auction(r1205744646)
    500
    JDirectItems Auction(u1204905847)
    500
    JDirectItems Auction(j1205768066)
    500
    JDirectItems Auction(j1204895542)
    500
    JDirectItems Auction(b1205857894)
    Buyee Service Fee
    300
    JDirectItems Auction(f1204890335)
    300
    JDirectItems Auction(r1205744646)
    300
    JDirectItems Auction(u1204905847)
    300
    JDirectItems Auction(j1205768066)
    300
    JDirectItems Auction(j1204895542)
    300
    JDirectItems Auction(b1205857894)
    """
    continuation = """
    JDirectItems Auction(f1204890335)
    880
    """
    pages = [fees, "not part of the bill", continuation, items, later, breakdown]
    assert _buyee_pages_are_one_invoice(pages) is True
    assert _extracted_bill_has_charges(pages) is True
    parsed = parse_purchase_pages(pages)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "25AH" in (by_id["j1204895542"].catalog_number or "")
    costs = {auction_id: copy_costs(row.billing_note) for auction_id, row in by_id.items()}
    for auction_id in by_id:
        assert costs[auction_id]["plan_fee"] == Decimal("500")
        assert costs[auction_id]["service_fee"] == Decimal("300")
    for auction_id in (
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "b1205857894",
    ):
        assert costs[auction_id]["domestic_shipping"] == Decimal("880")
    assert costs["j1204895542"]["domestic_shipping"] is None
    for row in costs.values():
        assert row["customs"] is None
        assert row["shipping"] is None
    assert by_id["f1204890335"].package_tax == Decimal("1105")
    assert by_id["f1204890335"].package_total == Decimal("28324")


def test_buyee_visual_titles_take_the_price_column_in_row_order() -> None:
    """The catalog stays on the auction when the price column is a separate list."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name stew
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name stew
    Visual auction f1204890335 title CBS SONY SOLL170 LP price
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price
    Column item 440
    Column item 1001
    Plan Fee 1,000
    Buyee Service Fee 600
    Customs Duty 200
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    assert "SOLL" in (by_id["f1204890335"].catalog_number or "")
    assert by_id["r1205744646"].paid_amount == Decimal("1001")
    assert "70AH1141" in by_id["r1205744646"].title


def test_buyee_plan_rows_before_the_heading_still_land_on_each_auction() -> None:
    """The Plan Fee heading is on the previous screenshot. The 500s are already here."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name SOLL141 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name 70AH1141 LP
    Item Price 1,001
    500
    JDirectItems Auction(r1205744646)
    SOLL141 LP 500
    JDirectItems Auction(u1204905847)
    500
    JDirectItems Auction(j1205768066)
    Buyee Service Fee 1,800
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
    }
    for row in by_id.values():
        assert copy_costs(row.billing_note)["plan_fee"] == Decimal("500")
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["f1204890335"].package_shipping == Decimal("10176")


def test_buyee_item_page_outranks_a_partial_screenshot() -> None:
    """A later page that priced the whole table replaces a cropped page's prices."""

    partial = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name stew
    Visual auction f1204890335 title CBS SONY SOLL141 LP price 1001 rows 3
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 4290 rows 3
    Visual auction u1204905847 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 671 rows 3
    """
    full = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name stew
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 6
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440 rows 6
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 6
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 6
    Plan Fee 3,000
    Buyee Service Fee 1,800
    Domestic Shipping Fee 4,400
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    """
    parsed = parse_purchase_pages([partial, full])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["r1205744646"].paid_amount == Decimal("1001")
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert copy_costs(by_id["f1204890335"].billing_note)["plan_fee"] == Decimal("500")
    assert copy_costs(by_id["f1204890335"].billing_note)["service_fee"] == Decimal("300")
    assert by_id["f1204890335"].package_shipping == Decimal("10176")
    assert by_id["f1204890335"].package_total == Decimal("28324")


def test_buyee_split_item_block_continues_on_the_next_screenshot() -> None:
    """The auction id can end one screenshot. The name and price start the next.

    Fee-table repeats of the same ids are not extra purchases. Three copies
    of 70AH1141 stay separate.
    """

    item_page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Total Amount 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    """
    next_page = """
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Quantity 1
    Item Price 4,290
    Total Amount 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    Plan Fee 3,000
    Buyee Service Fee 1,800
    Domestic Shipping Fee 4,400
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    """
    fee_page = """
    Domestic Shipping Fee
    Auction(f1204890335)
    880
    Auction(r1205744646)
    880
    Auction(u1204905847)
    880
    Auction(j1205768066)
    880
    Auction(b1205857894)
    880
    Plan Fee
    Auction(f1204890335)
    500
    Buyee Service Fee 1,800
    """
    parsed = parse_purchase_pages([item_page, next_page, fee_page])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    assert "25AH" in (by_id["j1204895542"].catalog_number or "")
    assert [by_id[key].paid_amount for key in ("r1205744646", "j1205768066", "b1205857894")] == [
        Decimal("1001"),
        Decimal("1001"),
        Decimal("671"),
    ]
    assert sum(row.paid_amount or 0 for row in parsed.purchases) == Decimal("7843")
    assert by_id["f1204890335"].package_shipping == Decimal("10176")
    assert by_id["f1204890335"].package_tax == Decimal("1105")
    assert by_id["f1204890335"].package_total == Decimal("28324")
    assert copy_costs(by_id["f1204890335"].billing_note)["plan_fee"] == Decimal("500")
    assert copy_costs(by_id["f1204890335"].billing_note)["service_fee"] == Decimal("300")
    assert copy_costs(by_id["j1204895542"].billing_note)["domestic_shipping"] is None
    assert copy_costs(by_id["b1205857894"].billing_note)["domestic_shipping"] == Decimal("880")
    included = {
        "f1204890335": Decimal("40"),
        "r1205744646": Decimal("91"),
        "u1204905847": Decimal("40"),
        "j1205768066": Decimal("91"),
        "j1204895542": Decimal("390"),
        "b1205857894": Decimal("61"),
    }
    for auction_id, portion in included.items():
        costs = copy_costs(by_id[auction_id].billing_note)
        assert costs["tax"] is None
        assert costs["tax_included"] == portion


def test_buyee_invoice_payment_date_is_the_lot_paid_on() -> None:
    """A shipping invoice's payment row is the order date for every auction."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Plan Fee 1,000
    Buyee Service Fee 600
    Domestic Shipping Fee 1,760
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    Payment 2025/08/20 28324
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"f1204890335", "r1205744646"}
    for row in by_id.values():
        assert row.paid_on == date(2025, 8, 20)
        assert row.package_shipping == Decimal("10176")
        assert row.package_tax == Decimal("1105")
        assert row.package_total == Decimal("28324")
        assert row.package_item == Decimal("1441")
        assert row.order_id == "package:f1204890335+r1205744646"
    lines = buyee_package_display_lines(
        by_id["f1204890335"].billing_note,
        package_shipping=Decimal("10176"),
        package_tax=Decimal("1105"),
    )
    by_label = dict(lines)
    assert by_label["International"] == Decimal("10176")
    assert by_label["Customs"] == Decimal("1105")
    assert by_label["Domestic"] == Decimal("880")
    assert package_charge_share(
        Decimal("440"),
        Decimal("1441"),
        Decimal("10176"),
    ) == Decimal("3107")


def test_owned_buyee_copy_bills_under_the_auction_id() -> None:
    """A shop order that was never scraped still has a bill identity."""

    purchase = ParsedPurchase(
        source="buyee",
        external_id="f1204890335",
        title="CBS SONY SOLL170 LP",
        seller="Buyee",
        paid_amount=Decimal("440"),
        paid_currency="JPY",
        paid_on=date(2025, 8, 20),
        catalog_number="SOLL-170",
    )
    assert bill_copy_identity("", "", purchase) == ("buyee", "f1204890335")
    assert bill_copy_identity("buyee", "f1204890335", purchase) == (
        "buyee",
        "f1204890335",
    )


def test_ebay_combined_order_does_not_add_buyee_lot_postage_to_landed() -> None:
    """eBay line shipping is already the share. Buyee lots add international and customs."""

    ebay_intl, ebay_customs = buyee_package_landed_extras(
        "Shipping 5.53 USD\nTax 11.25 USD",
        marketplace="gripsweat",
        paid=Decimal("179.99"),
        package_item=Decimal("339.98"),
        package_shipping=Decimal("10.44"),
        package_tax=Decimal("21.25"),
    )
    assert ebay_intl is None
    assert ebay_customs is None
    buyee_intl, buyee_customs = buyee_package_landed_extras(
        "Plan fee 500 JPY\nService fee 300 JPY\nDomestic shipping 880 JPY",
        marketplace="buyee",
        paid=Decimal("440"),
        package_item=Decimal("7843"),
        package_shipping=Decimal("10176"),
        package_tax=Decimal("1105"),
    )
    assert buyee_intl == Decimal("571")
    assert buyee_customs == Decimal("62")


def test_buyee_unpaired_duplicate_price_stays_a_row() -> None:
    """A 440 whose total is not beside it is still a row. It is not dropped."""

    flat = [
        (0, Decimal("440")),
        (120, Decimal("1001")),
        (128, Decimal("1001")),
        (210, Decimal("1001")),
        (250, Decimal("440")),
        (360, Decimal("4290")),
        (368, Decimal("4290")),
        (480, Decimal("671")),
        (488, Decimal("671")),
    ]
    amounts = [amount for _top, amount in _buyee_price_bands(flat)]
    assert amounts.count(Decimal("440")) == 2
    assert amounts.count(Decimal("1001")) == 2
    assert Decimal("4290") in amounts
    assert Decimal("671") in amounts


def test_buyee_catalog_tail_is_not_a_domestic_fee() -> None:
    """70AH1 141 is the catalog, not domestic shipping of 141."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Domestic Shipping Fee
    Auction(f1204890335)
    880
    xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    BUDOKAN AT LAST CBS/SONY 70AH1 141
    Auction(r1205744646)
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert copy_costs(by_id["f1204890335"].billing_note)["domestic_shipping"] == Decimal("880")
    assert copy_costs(by_id["r1205744646"].billing_note)["domestic_shipping"] is None


def test_buyee_title_stops_before_the_next_record() -> None:
    """The next LP's words do not join this title. 70AH stays Budokan."""

    title = _buyee_title_for_auction(
        "Auction(j1205768066) BUDOKAN AT LAST CBS SONY 70AH1141 LP "
        "MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP",
        "j1205768066",
    )
    assert "70AH1141" in title
    assert "MOBIUS" not in title
    assert "25AH" not in title


def test_buyee_misread_fee_id_is_not_a_seventh_copy() -> None:
    """b1205857804 is b1205857894 with one digit changed. It is not a purchase."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 6
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440 rows 6
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 6
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 6
    Visual auction b1205857804 title BUDOKAN AT LAST CBS SONY 70AH1141 price  rows 6
    Plan Fee 3,000
    Buyee Service Fee 1,800
    """
    parsed = parse_purchase_export(page)
    assert [row.external_id for row in parsed.purchases] == [
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    ]
    assert [row.paid_amount for row in parsed.purchases] == [
        Decimal("440"),
        Decimal("1001"),
        Decimal("440"),
        Decimal("1001"),
        Decimal("4290"),
        Decimal("671"),
    ]


def test_buyee_domestic_rows_match_when_the_letter_was_dropped() -> None:
    """The fee table dropped the auction's letter. The digits still name it.

    Mobius is not in that table, so it does not get an 880.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    Domestic Shipping Fee 4,400
    (1204890335)
    880
    (1205744646)
    880
    (w1204905847)
    880
    1205768066)
    880
    (b1205857894)
    880
    Column fee 4400 880
    Column fee 4400 880
    Column fee 4400 880
    Column fee 4400 880
    Column fee 4400 880
    """
    parsed = parse_purchase_export(page)
    costs = {
        row.external_id: copy_costs(row.billing_note)["domestic_shipping"]
        for row in parsed.purchases
    }
    assert costs["j1204895542"] is None
    assert costs["f1204890335"] == Decimal("880")
    assert costs["u1204905847"] == Decimal("880")
    assert costs["b1205857894"] == Decimal("880")
    assert sum(amount or 0 for amount in costs.values()) == Decimal("4400")


def test_buyee_inserted_digit_is_not_another_copy() -> None:
    """r11205744646 is r1205744646 with a digit inserted.

    The second 1,001 is in the price column. The item line for that Budokan
    lost its price, and 671 must not be read as the customs duty.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Total Amount
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    Customs Duties and Value-Added Tax 671
    International Shipping Fee 10,176
    Grand Total Payment Amount
    28,324YEN
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 6
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 price 141 rows 6
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440 rows 6
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1800 rows 6
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 6
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 6
    Visual auction r11205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 price  rows 6
    Column item 440
    Column item 1001
    Column item 440
    Column item 1001
    Column item 4290
    Column item 671
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    Column fee 1800 300
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["j1205768066"].paid_amount == Decimal("1001")
    assert by_id["j1204895542"].package_tax is None
    assert sum(row.paid_amount or 0 for row in parsed.purchases) == Decimal("7843")
    assert by_id["r1205744646"].title.endswith("LP")
    assert purchase_media(by_id["r1205744646"].title) == "LP"


def test_buyee_shared_price_stays_on_the_row_that_printed_it() -> None:
    """4290 belongs to Mobius. The Budokan above it keeps 1,001."""

    page = """
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY MOMOE YAMAGUCHI MOBIUS GAME 70AH1141 price 4290 rows 2
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 2
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"j1205768066", "j1204895542"}
    assert by_id["j1205768066"].paid_amount == Decimal("1001")
    assert "70AH" in (by_id["j1205768066"].catalog_number or "")
    assert "MOBIUS" not in by_id["j1205768066"].title
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    assert "25AH" in (by_id["j1204895542"].catalog_number or "")


def test_buyee_truncated_catalog_does_not_replace_the_visual_one() -> None:
    """SOLLI4T is SOLL141 with a digit dropped, not a different release."""

    page = """
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLLI4T LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440 rows 2
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 2
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["u1204905847"].title == "CBS SONY SOLL141 LP"
    assert by_id["u1204905847"].catalog_number == "SOLL-141"


def test_buyee_lot_shows_international_once_and_keeps_domestic_on_the_row() -> None:
    """Shipping on a Buyee bulk invoice is the lot's international postage."""

    columns = arrange_lot_columns(
        [
            "Keep",
            "Paid",
            "Delivered",
            "Shipping",
            "Tax",
            "Plan fee",
            "Service fee",
            "Domestic shipping",
        ],
        package_shipping=Decimal("10176"),
        has_copy_shipping=False,
    )
    assert columns.index("Domestic shipping") < columns.index("International")
    assert columns.index("International") < columns.index("Plan fee")
    assert "Shipping" not in columns

    per_copy = arrange_lot_columns(
        ["Keep", "Delivered", "Shipping", "Tax"],
        package_shipping=None,
        has_copy_shipping=True,
    )
    assert "Shipping" in per_copy
    assert "International" not in per_copy


def test_buyee_hammer_includes_ten_percent_consumption_tax() -> None:
    """The printed bid stays the item price. Tax is the 10/110 already inside it."""

    hammers = (
        Decimal("440"),
        Decimal("1001"),
        Decimal("440"),
        Decimal("1001"),
        Decimal("4290"),
        Decimal("671"),
    )
    portions = [included_consumption_tax(amount) for amount in hammers]
    assert portions == [
        Decimal("40"),
        Decimal("91"),
        Decimal("40"),
        Decimal("91"),
        Decimal("390"),
        Decimal("61"),
    ]
    assert sum(portions, Decimal("0")) == Decimal("713")
    assert sum(hammers, Decimal("0")) - Decimal("713") == Decimal("7130")
    purchase = ParsedPurchase(
        source="buyee",
        external_id="f1204890335",
        title="CBS SONY SOLL170 LP",
        seller="Buyee",
        paid_amount=Decimal("440"),
        paid_currency="JPY",
        paid_on=None,
        catalog_number="SOLL-170",
        billing_note="Item price 440 JPY\nPlan fee 500 JPY",
    )
    assert buyee_tax_included(purchase) == Decimal("40")
    stored = _with_included_consumption_tax(purchase)
    assert "Tax included 40 JPY" in stored.billing_note
    assert copy_costs(stored.billing_note)["tax"] is None
    assert copy_costs(stored.billing_note)["tax_included"] == Decimal("40")
    kept = note_with_copy_costs(
        stored.billing_note,
        plan_fee=Decimal("500"),
        currency="JPY",
    )
    assert "Plan fee 500 JPY" in kept
    assert "Tax included 40 JPY" in kept
    taxed = ParsedPurchase(
        source="buyee",
        external_id="f1204890335",
        title="CBS SONY SOLL170 LP",
        seller="Buyee",
        paid_amount=Decimal("440"),
        paid_currency="JPY",
        paid_on=None,
        catalog_number="SOLL-170",
        billing_note="Tax 40 JPY",
    )
    assert buyee_tax_included(taxed) is None
    parked = ParsedPurchase(
        source="buyee",
        external_id="f1204890335",
        title="CBS SONY SOLL170 LP",
        seller="Buyee",
        paid_amount=Decimal("440"),
        paid_currency="JPY",
        paid_on=None,
        catalog_number="SOLL-170",
        billing_note="Item price 440 JPY\nPlan fee 500 JPY",
    )
    held = hold_import_purchases([], [parked], set())
    assert copy_costs(held[0].billing_note)["tax_included"] == Decimal("40")
    assert copy_costs(held[0].billing_note)["tax"] is None
    assert "Tax included 40 JPY" in held[0].billing_note
    columns = arrange_lot_columns(
        ["Delivered", "International", "Tax included", "Tax", "Plan fee"],
        package_shipping=Decimal("10176"),
        has_copy_shipping=False,
    )
    assert (
        columns.index("International")
        < columns.index("Tax included")
        < columns.index("Tax")
    )


def test_buyee_customs_column_is_the_amount_under_international_shipping() -> None:
    amount = _buyee_column_customs(
        [
            (10, Decimal("440")),
            (20, Decimal("10176")),
            (30, Decimal("1105")),
            (40, Decimal("4400")),
        ],
        Decimal("10176"),
        {Decimal("440")},
    )
    assert amount == Decimal("1105")


def test_buyee_catalog_under_the_id_names_the_row() -> None:
    """The catalog above the id is the previous LP. The one under the id is this row."""

    title = _buyee_title_for_auction(
        "MOMOE 25AH974 LP Auction(b1205857894) BUDOKAN 70AH1141 LP",
        "b1205857894",
    )
    assert "70AH" in title
    assert "25AH" not in title


def test_buyee_previous_catalog_does_not_replace_the_priced_visual_title() -> None:
    """The item name starts with the previous LP. 671 stays the Budokan visual row."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 4
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 4
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 4
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 4
    Plan Fee 2,000
    Buyee Service Fee 1,200
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "70AH" in by_id["b1205857894"].title
    assert "25AH" not in by_id["b1205857894"].title
    assert "25AH" in by_id["j1204895542"].title


def test_buyee_visual_rows_survive_when_the_plain_text_missed_their_ids() -> None:
    """Item Name lines are three records. The price column already has all six."""

    page = """
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 6
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440 rows 6
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001 rows 6
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290 rows 6
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 6
    Plan Fee 3,000
    Buyee Service Fee 1,800
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert by_id["u1204905847"].title == "CBS SONY SOLL141 LP"
    assert by_id["r1205744646"].paid_amount == Decimal("1001")
    assert by_id["j1205768066"].paid_amount == Decimal("1001")
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "70AH" in by_id["b1205857894"].title
    assert copy_costs(by_id["f1204890335"].billing_note)["plan_fee"] == Decimal("500")
    assert copy_costs(by_id["f1204890335"].billing_note)["service_fee"] == Decimal("300")
    assert by_id["f1204890335"].package_shipping == Decimal("10176")
    assert by_id["f1204890335"].package_total == Decimal("28324")


def test_buyee_unpriced_fee_line_does_not_rename_a_priced_row() -> None:
    """The fee page calls b SOLL170. That line has no price, so 671 stays Budokan."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name stew
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name stew
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440 rows 4
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671 rows 4
    Visual auction b1205857894 title CBS SONY SOLL170 LP price  rows 6
    Plan Fee 1,000
    Buyee Service Fee 600
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "70AH" in by_id["b1205857894"].title
    assert "SOLL" not in by_id["b1205857894"].title


def test_buyee_misread_parenthesis_is_not_an_extra_copy() -> None:
    """A stray ``(i1201805542)`` is not a seventh record."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    25AH974 LP
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    (i1201805542)
    Plan Fee 1,500
    Buyee Service Fee 900
    """
    parsed = parse_purchase_export(page)
    assert "i1201805542" not in {row.external_id for row in parsed.purchases}
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "70AH" in by_id["b1205857894"].title
    assert "25AH" not in by_id["b1205857894"].title


def test_buyee_partial_price_page_keeps_the_other_auctions() -> None:
    """Three priced rows must not drop the auctions whose price is on another page."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671
    Plan Fee 3,000
    Buyee Service Fee 1,800
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    assert by_id["u1204905847"].title == "CBS SONY SOLL141 LP"
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert copy_costs(by_id["f1204890335"].billing_note)["plan_fee"] == Decimal("500")


def test_buyee_item_name_wins_when_the_visual_price_is_on_the_wrong_catalog() -> None:
    """A priced visual row can carry the next LP. The item name stays with its auction."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOMOE YAMAGUCHI MOBIUS GAME CBS/SONY 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 671
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440
    Visual auction r1205744646 title CBS SONY SOLL141 LP price 1001
    Visual auction j1204895542 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 4290
    Visual auction b1205857894 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 671
    Plan Fee 3,000
    Buyee Service Fee 1,800
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["r1205744646"].title == "BUDOKAN AT LAST CBS SONY 70AH1141 LP"
    assert by_id["r1205744646"].paid_amount == Decimal("1001")
    assert by_id["u1204905847"].title == "CBS SONY SOLL141 LP"
    assert by_id["j1204895542"].title == "MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP"
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    assert by_id["b1205857894"].title == "BUDOKAN AT LAST CBS SONY 70AH1141 LP"
    assert by_id["b1205857894"].paid_amount == Decimal("671")


def test_buyee_fee_row_does_not_replace_the_item_name() -> None:
    """A fee screenshot puts the next LP's catalog on this auction. The item name stays."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name CBS/SONY SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN AT LAST CBS/SONY 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name CBS/SONY SOLL141 LP
    Item Price 440
    Visual auction f1204890335 title CBS SONY SOLL141 LP price
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001
    Visual auction u1204905847 title CBS SONY SOLL141 LP price
    Plan Fee 1,500
    Buyee Service Fee 900
    Customs Duty 200
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert "SOLL" in (by_id["f1204890335"].catalog_number or "")
    assert "141" not in (by_id["f1204890335"].catalog_number or "")
    assert by_id["u1204905847"].title == "CBS SONY SOLL141 LP"
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert copy_costs(by_id["f1204890335"].billing_note)["plan_fee"] == Decimal("500")


def test_buyee_plan_total_still_splits_when_an_item_price_is_missing() -> None:
    """Plan Fee 3,000 is 500 on each auction even when one item price was not read."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name SOLL141 LP
    Visual auction f1204890335 title CBS SONY SOLL170 LP price 440
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001
    Visual auction u1204905847 title CBS SONY SOLL141 LP price
    Visual auction j1205768066 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001
    Visual auction j1204895542 title MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP price 4290
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671
    Shopping Site(ID) JDirectItems Auction(j1205768066)
    Item Name 70AH1141 LP
    Item Price 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name 70AH1141 LP
    Item Price 671
    Other Service Fees
    Plan Fee 3,000
    Buyee Service Fee 1,800
    International Shipping Fee 10,176
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "f1204890335",
        "r1205744646",
        "u1204905847",
        "j1205768066",
        "j1204895542",
        "b1205857894",
    }
    assert by_id["u1204905847"].paid_amount is None
    for row in by_id.values():
        costs = copy_costs(row.billing_note)
        assert costs["plan_fee"] == Decimal("500")
        assert costs["service_fee"] == Decimal("300")
    assert by_id["f1204890335"].package_shipping == Decimal("10176")


def test_buyee_title_does_not_swallow_the_next_records_catalog() -> None:
    """A fee row that runs into the next LP keeps the first catalog only."""

    swallowed = _short_buyee_title(
        "MOMOE YAMAGUCHI/MOBIUS ' S GAME/CBS/SONY 25AH974 LP "
        "BUDOKAN... AT LAST/CBS/SONY 70AH1141 LP"
    )
    assert swallowed == "MOMOE YAMAGUCHI MOBIUS GAME CBS SONY 25AH974 LP"
    soll = _short_buyee_title(
        "CBS/SONY SOLL170 LP BUDOKAN... AT LAST/CBS/SONY 70AH1141 LP"
    )
    assert soll == "CBS SONY SOLL170 LP"


def test_buyee_visual_rows_keep_each_price_on_its_auction() -> None:
    """A price column in reading order must not be zipped onto a different id order."""

    page = """
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name stew without a catalog
    Item Price 1001
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name stew without a catalog
    Item Price 4290
    Shopping Site(ID) JDirectItems Auction(u1204905847)
    Item Name stew without a catalog
    Item Price 671
    Visual auction b1205857894 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 671
    Visual auction r1205744646 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1001
    Visual auction u1204905847 title CBS SONY SOLL141 LP price 440
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    Domestic Shipping Fee 2,640
    Customs Duty 1,105
    Grand Total Payment Amount
    20,000YEN
    Buyee Service Fee
    JDirectItems Auction(b1205857894)
    6
    JDirectItems Auction(r1205744646)
    7
    JDirectItems Auction(u1204905847)
    7
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert "70AH1141" in by_id["b1205857894"].title
    assert "70AH" in (by_id["b1205857894"].catalog_number or "")
    assert by_id["r1205744646"].paid_amount == Decimal("1001")
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert "SOLL141" in by_id["u1204905847"].title
    costs = {auction_id: copy_costs(row.billing_note) for auction_id, row in by_id.items()}
    for auction_id in by_id:
        assert costs[auction_id]["service_fee"] == Decimal("300")
        assert costs[auction_id]["shipping"] is None


def test_buyee_ocr_stew_keeps_the_catalog_printed_on_the_bill() -> None:
    """The Japanese name is unreadable. The catalog on the bill is the title."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name s/f & FRE LUILTETR/-X 2 bE 7/CBS/SONY SOLL170 LP
    Quantity 1
    Item Price 440
    Total Amount 440
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name PARE ILI FL fake Blas BUDOKAN AT LAST/CBS/SONY 70AH1141 LP
    Quantity 1
    Item Price 1,001
    Total Amount 1,001
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name qq zz vv nn
    Quantity 1
    Item Price 4,290
    Total Amount 4,290
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    Domestic Shipping Fee
    SOLL170 LP 880
    JDirectItems Auction(f1204890335)
    70AH1141 LP 880
    JDirectItems Auction(r1205744646)
    25AH974 LP
    JDirectItems Auction(j1204895542)
    Customs Duty 1,105
    Grand Total Payment Amount
    20,000YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["f1204890335"].title == "CBS SONY SOLL170 LP"
    misread = parse_purchase_export(
        page.replace("SOLL170", "SOLLI70", 1)
    )
    misread_f = next(row for row in misread.purchases if row.external_id == "f1204890335")
    assert "SOLL170" in misread_f.title
    assert "SOLL" in (by_id["f1204890335"].catalog_number or "")
    assert "70AH1141" in by_id["r1205744646"].title
    assert "BUDOKAN" in by_id["r1205744646"].title
    assert "LUILTETR" not in by_id["f1204890335"].title
    assert by_id["j1204895542"].title == "25AH974 LP"
    assert "25AH" in (by_id["j1204895542"].catalog_number or "")


def test_buyee_long_bill_does_not_collapse_into_the_first_auction() -> None:
    """Package headings are not one record's postage, and a blank shipping label stays blank."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name SOLL170 LP
    Shopping Site(ID) JDirectItems Auction(r1205744646)
    Item Name BUDOKAN 70AH1141 LP
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOBIUS 25AH974 LP
    Other Service Fees
    Plan Fee 3,000
    Buyee Service Fee 1,800
    Domestic Shipping Fee(From seller to Buyee) 4,400
    International Shipping Fee
    (Currency: YEN)
    10,176
    Customs Duties and Value-Added Tax
    1,105
    Grand Total Payment Amount
    28,324YEN
    """
    parsed = parse_purchase_export(page)
    assert [row.external_id for row in parsed.purchases] == [
        "f1204890335",
        "r1205744646",
        "j1204895542",
    ]
    for row in parsed.purchases:
        costs = copy_costs(row.billing_note)
        assert costs["domestic_shipping"] is None
        assert costs["shipping"] is None
        assert costs["customs"] is None
        assert row.package_total == Decimal("28324")
        assert row.package_shipping == Decimal("10176")
        assert "10,176" not in row.billing_note
        assert "10176" not in row.billing_note


def test_buyee_september_lot_rejects_stray_21_and_tallies() -> None:
    """A 9/30 Buyee lot must not treat OCR 21 as postage, and the sheet must add up."""

    page = """
    Shopping Site(ID) JDirectItems Auction(h1200193589)
    Item Name CBS SONY 25AH673 LP
    Quantity 1
    Item Price 561
    Total Amount 561
    Shopping Site(ID) JDirectItems Auction(u1200253398)
    Item Name CBS SONY 25AH662 LP
    Quantity 1
    Item Price 352
    Total Amount 352
    Shopping Site(ID) JDirectItems Auction(w1200194825)
    Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
    Quantity 1
    Item Price 1,001
    Total Amount 1,001
    Shopping Site(ID) JDirectItems Auction(i1200245569)
    Item Name CBS SONY 27AH1173 LP
    Quantity 1
    Item Price 440
    Total Amount 440
    Visual auction w1200194825 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price  rows 4
    Visual auction i1200245569 title CBS SONY 27AH1173 LP price  rows 4
    Other Service Fees
    Plan Fee 2,000
    Buyee Service Fee 1,200
    Domestic Shipping Fee(From seller to Buyee) 1,760
    Plan Fee
    JDirectItems Auction(h1200193589)
    500
    JDirectItems Auction(u1200253398)
    500
    JDirectItems Auction(w1200194825)
    500
    JDirectItems Auction(i1200245569)
    500
    Buyee Service Fee
    JDirectItems Auction(h1200193589)
    300
    JDirectItems Auction(u1200253398)
    500
    JDirectItems Auction(w1200194825)
    300
    Domestic Shipping Fee
    JDirectItems Auction(h1200193589)
    880
    JDirectItems Auction(u1200253398)
    880
    Shipping Expenses
    International Shipping Fee
    (Currency: YEN) 21
    18,642
    Total Amount 18,642
    Customs Duties and Value-Added Tax
    Customs Duty 1,105
    Grand Total Payment Amount
    27,061YEN
    * Breakdown of Payment amount
    2026/09/30
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "h1200193589",
        "u1200253398",
        "w1200194825",
        "i1200245569",
    }
    assert by_id["h1200193589"].paid_amount == Decimal("561")
    assert by_id["u1200253398"].paid_amount == Decimal("352")
    assert by_id["w1200194825"].paid_amount == Decimal("1001")
    assert by_id["i1200245569"].paid_amount == Decimal("440")
    for row in parsed.purchases:
        assert row.paid_on == date(2026, 9, 30)
        assert row.package_shipping == Decimal("18642")
        assert row.package_tax == Decimal("1105")
        assert row.package_total == Decimal("27061")
        costs = copy_costs(row.billing_note)
        assert costs["plan_fee"] == Decimal("500")
        assert costs["service_fee"] == Decimal("300")
        assert costs["shipping"] is None
    assert copy_costs(by_id["h1200193589"].billing_note)["domestic_shipping"] == Decimal(
        "880"
    )
    assert copy_costs(by_id["w1200194825"].billing_note)["domestic_shipping"] is None
    tally = lot_tally(parsed.purchases)
    assert tally.missing_prices == 0
    assert tally.balanced is True
    assert tally.international == Decimal("18642")
    assert tally.grand == Decimal("27061")
    assert "tallies" in tally.caption().lower()
    assert "21" not in describe_lot(parsed.purchases)
    assert "2026-09-30" in describe_lot(parsed.purchases)


def test_buyee_september_eighth_lot_keeps_the_1500_hammer_and_the_order_date() -> None:
    """A 9/08 Buyee lot has an item at 1,500 and protective packaging at 1,500.

    That hammer is not the packaging total. Plan 5,500 and service 3,300 are
    500 and 300 on every copy. The whole order is paid 2026-09-08.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 HIT PACK SERIES 山口百恵
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(d1194852974)
    Item Name 山口百恵 さよならの向う側 EP
    Item Price 399
    Shopping Site(ID) JDirectItems Auction(n1148641695)
    Item Name 山口百恵 春風のいたずら EP
    Item Price 500
    Shopping Site(ID) JDirectItems Auction(n1195916122)
    Item Name 山口百恵 6枚セット
    Item Price 700
    Shopping Site(ID) JDirectItems Auction(b1197144157)
    Item Name C00097077/EP 愛に走って
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(f1197129190)
    Item Name C00145878/EP ちっぽけな感傷
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name 7inch 山口百恵 MOMOE YAMAGUCHI EP
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    Item Name 山口百恵 愛に走って EP
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(n1054308529)
    Item Name 山口百恵 Hit Pack Series EP
    Item Price 1,280
    Shopping Site(ID) JDirectItems Auction(f1104283743)
    Item Name EP 0825 ゴールデンシングル 山口百恵
    Item Price 400
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    Item Name 山口百恵 冬の色 EP
    Item Price 160
    Visual auction x728495200 title EP-003 HIT PACK SERIES price 1500 rows 4
    Other Service Fees
    Plan Fee 5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee) 2,680
    Protective Packaging Fee 1,500
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    * Breakdown of Payment amount
    2026/09/08 31900
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "x728495200",
        "d1194852974",
        "n1148641695",
        "n1195916122",
        "b1197144157",
        "f1197129190",
        "s1073507969",
        "d1196280358",
        "n1054308529",
        "f1104283743",
        "m1178811814",
    }
    assert by_id["x728495200"].paid_amount == Decimal("1500")
    assert by_id["d1194852974"].paid_amount == Decimal("399")
    assert by_id["m1178811814"].paid_amount == Decimal("160")
    for row in parsed.purchases:
        assert row.paid_on == date(2026, 9, 8)
        assert row.package_shipping == Decimal("10521")
        assert row.package_tax == Decimal("1400")
        assert row.package_total == Decimal("31900")
        costs = copy_costs(row.billing_note)
        assert costs["plan_fee"] == Decimal("500")
        assert costs["service_fee"] == Decimal("300")
    tally = lot_tally(parsed.purchases)
    assert tally.missing_prices == 0
    assert tally.balanced is True
    assert tally.grand == Decimal("31900")
    assert tally.line_sum == Decimal("31900")
    assert "2026-09-08" in describe_lot(parsed.purchases)
    assert "missing a plan fee" not in tally.caption()
    assert "Order date is missing" not in tally.caption()


def test_buyee_keeps_an_item_section_auction_without_price_labels() -> None:
    """A 9/08 row Tesseract left unlabeled still belongs on the lot."""

    page = """
    JDirectItems Auction(x728495200)
    Item Name HIT PACK EP
    Item Price 1500
    JDirectItems Auction(d1194852974)
    レア盤 EP
    JDirectItems Auction(n1148641695)
    Item Name 春風 EP
    Item Price 500
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    Column item 1500
    Column item 399
    Column item 500
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"x728495200", "d1194852974", "n1148641695"}
    assert by_id["d1194852974"].paid_amount == Decimal("399")


def test_buyee_ocr_spaced_id_survives_a_shifted_visual_table() -> None:
    """The 9/08 visual pass skipped Auction(d1 194852974). Column 399 is that copy.

    Trusting ten priced visual rows is how the lot became ten copies, lost
    the plan split, and tallied 23,051 against 31,900.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 HIT PACK SERIES
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(d1 194852974)
    レア盤 EP
    Shopping Site(ID) JDirectItems Auction(n1148641695)
    Item Name 春風のいたずら EP
    Item Price 500
    Shopping Site(ID) JDirectItems Auction(n1195916122)
    Item Name 山口百恵 6枚セット
    Item Price 700
    Shopping Site(ID) JDirectItems Auction(b1197144157)
    Item Name C00097077/EP 愛に走って
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(f1197129190)
    Item Name C00145878/EP ちっぽけな感傷
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name 7inch MOMOE YAMAGUCHI EP
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    Item Name 愛に走って EP
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(n1054308529)
    Item Name Hit Pack Series EP
    Item Price 1,280
    Shopping Site(ID) JDirectItems Auction(f1104283743)
    Item Name EP 0825 ゴールデンシングル
    Item Price 400
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    Item Name 冬の色 EP
    Item Price 160
    Other Service Fees
    Plan Fee 5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee) 2,680
    Protective Packaging Fee 1,500
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    Visual auction x728495200 title  price 1500 rows 10
    Visual auction n1148641695 title  price 700 rows 10
    Visual auction n1195916122 title  price 310 rows 10
    Visual auction b1197144157 title  price 310 rows 10
    Visual auction f1197129190 title  price 930 rows 10
    Visual auction s1073507969 title  price 1000 rows 10
    Visual auction d1196280358 title  price 1280 rows 10
    Visual auction n1054308529 title  price 250 rows 10
    Visual auction f1104283743 title  price 140 rows 10
    Visual auction m1178811814 title  price 160 rows 10
    Column item 1500
    Column item 399
    Column item 500
    Column item 700
    Column item 380
    Column item 380
    Column item 1000
    Column item 300
    Column item 1280
    Column item 400
    Column item 160
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "x728495200",
        "d1194852974",
        "n1148641695",
        "n1195916122",
        "b1197144157",
        "f1197129190",
        "s1073507969",
        "d1196280358",
        "n1054308529",
        "f1104283743",
        "m1178811814",
    }
    assert by_id["x728495200"].paid_amount == Decimal("1500")
    assert by_id["d1194852974"].paid_amount == Decimal("399")
    assert by_id["n1148641695"].paid_amount == Decimal("500")
    assert by_id["n1195916122"].paid_amount == Decimal("700")
    assert by_id["b1197144157"].paid_amount == Decimal("380")
    assert by_id["f1197129190"].paid_amount == Decimal("380")
    assert by_id["s1073507969"].paid_amount == Decimal("1000")
    assert by_id["d1196280358"].paid_amount == Decimal("300")
    assert by_id["n1054308529"].paid_amount == Decimal("1280")
    assert by_id["f1104283743"].paid_amount == Decimal("400")
    assert by_id["m1178811814"].paid_amount == Decimal("160")
    for row in parsed.purchases:
        assert row.paid_on == date(2026, 9, 8)
        costs = copy_costs(row.billing_note)
        assert costs["plan_fee"] == Decimal("500")
        assert costs["service_fee"] == Decimal("300")
    tally = lot_tally(parsed.purchases)
    assert tally.missing_prices == 0
    assert tally.balanced is True
    assert tally.grand == Decimal("31900")
    assert tally.line_sum == Decimal("31900")
    assert "missing a plan fee" not in tally.caption()
    assert "Order date is missing" not in tally.caption()


def test_buyee_august_lot_keeps_labeled_hammers_not_domestic_as_item_price() -> None:
    """828 invoice: visual 150 and 1,280 are domestic rows. The hammers are 500 and 473."""

    page = """
    Shopping Site(ID) JDirectItems Auction(x1195871432)
    Item Name TIME MN'77 EP 50810
    Item Price 950
    Shopping Site(ID) JDirectItems Auction(j1195183759)
    Item Name 国内盤 山口百恵 赤い絆 08EH-46
    Item Price 880
    Shopping Site(ID) JDirectItems Auction(e1190680873)
    Item Name EP1366 09EH-68 4曲入り
    Item Price 500
    Shopping Site(ID) JDirectItems Auction(q1133210991)
    Item Name 4曲入 EP 山口百恵 愛に走って SOLD-90
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(j1146786944)
    Item Name 7 Momoe Yamaguchi SOLD81
    Item Price 1,298
    Shopping Site(ID) JDirectItems Auction(u1196509850)
    Item Name 7inch 山口百恵 湖の決心 冬の色 SOLD65
    Item Price 473
    Shopping Site(ID) JDirectItems Auction(u1192404280)
    Item Name
    Item Price 500
    Shopping Site(ID) JDirectItems Auction(v1193158317)
    Item Name EP 山口百恵 としごろ デビュー曲
    Item Price 600
    Shopping Site(ID) JDirectItems Auction(s1189805169)
    Item Name EP 山口百恵 9枚セット
    Item Price 540
    Shopping Site(ID) JDirectItems Auction(u1196885982)
    Item Name EP 山口百恵 13枚セット
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(u1168015627)
    Item Name 即決 EP 山口百恵 10枚セット
    Item Price 1,400
    Other Service Fees
    Plan Fee 5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee) 4,115
    Protective Packaging Fee 1,500
    International Shipping Fee 7,730
    Grand Total Payment Amount
    30,586YEN
    Visual auction e1190680873 title EP1366 09EH-68 price 150 rows 11
    Visual auction u1196509850 title 湖の決心 price 1280 rows 11
    Visual auction u1192404280 title  price 500 rows 11
    Domestic Shipping Fee
    JDirectItems Auction(u1192404280)
    コンパクト盤 山口百恵 春風のいたずら 180
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert len(parsed.purchases) == 11
    assert by_id["e1190680873"].paid_amount == Decimal("500")
    assert by_id["u1196509850"].paid_amount == Decimal("473")
    assert by_id["j1146786944"].paid_amount == Decimal("1298")
    assert "春風" in (by_id["u1192404280"].title or "")
    assert by_id["u1192404280"].title.lower() != "u1192404280"
    tally = lot_tally(parsed.purchases)
    assert tally.items == Decimal("8441")
    assert tally.international == Decimal("7730")
    assert tally.packaging == Decimal("1500")
    assert tally.domestic_shipping == Decimal("4115")
    assert tally.grand == Decimal("30586")
    assert tally.line_sum == Decimal("30586")
    assert "does not match grand" not in tally.caption()


def test_buyee_september_eighth_breakdown_domestic_stays_on_the_lot() -> None:
    """The 9/08 sheet prints 2,680 once under Breakdown, then the item table again.

    That table is not per-copy domestic. Protective packaging is 1,500 with
    no amount on the heading.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 HIT PACK SERIES
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(d1194852974)
    Item Name さよならの向う側 EP
    Item Price 399
    Shopping Site(ID) JDirectItems Auction(n1148641695)
    Item Name 春風のいたずら EP
    Item Price 500
    Shopping Site(ID) JDirectItems Auction(n1195916122)
    Item Name 6枚セット
    Item Price 700
    Shopping Site(ID) JDirectItems Auction(b1197144157)
    Item Name C00097077/EP
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(f1197129190)
    Item Name C00145878/EP
    Item Price 380
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name 7inch MOMOE YAMAGUCHI EP
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    Item Name 愛に走って EP
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(n1054308529)
    Item Name Hit Pack Series EP
    Item Price 1,280
    Shopping Site(ID) JDirectItems Auction(f1104283743)
    Item Name EP 0825
    Item Price 400
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    Item Name 冬の色 EP
    Item Price 160
    Other Service Fees
    5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee)
    Protective Packaging Fee
    International Shipping Fee
    10,521
    Customs Duties and Value-Added Tax 1400
    Grand Total Payment Amount
    31,900YEN
    * Breakdown of Other Service Fees
    Domestic Shipping Fee 2,680
    Shopping Site Item Name Price
    (ID)
    JDirectItems Auction(x728495200)
    310
    JDirectItems Auction(d1194852974)
    50
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 5500 500
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    Column fee 3300 300
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 11
    for row in parsed.purchases:
        costs = copy_costs(row.billing_note)
        assert costs["plan_fee"] == Decimal("500")
        assert costs["service_fee"] == Decimal("300")
        assert costs["domestic_shipping"] is None
        assert "Package domestic shipping 2680 JPY" in row.billing_note
        assert "Package protective packaging 1500 JPY" in row.billing_note
    tally = lot_tally(parsed.purchases)
    assert tally.balanced is True
    assert tally.grand == Decimal("31900")
    assert tally.line_sum == Decimal("31900")


def test_buyee_junk_latin_is_not_kept_when_the_invoice_has_the_japanese_name() -> None:
    """English Tesseract stew is not a title. The Item Name on the bill is."""

    page = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 4曲入EP 山口百恵 HIT PACK SERIES
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(d1194852974)
    Item Name 山口百恵 さよならの向う側 EP
    Item Price 399
    Other Service Fees
    Plan Fee 1,000
    Buyee Service Fee 600
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    Visual auction x728495200 title Uri Sickie WG UO SkeSOMIM price 1500 rows 2
    Visual auction d1194852974 title [ee onto - ZOEY a price 399 rows 2
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert "HIT PACK" in by_id["x728495200"].title
    assert "山口百恵" in by_id["x728495200"].title
    assert "さよなら" in by_id["d1194852974"].title
    assert "Uri Sickie" not in by_id["x728495200"].title
    assert purchase_media(by_id["x728495200"].title) == "EP_7_INCH"
    assert purchase_media(by_id["d1194852974"].title) == "EP_7_INCH"
    assert by_id["x728495200"].catalog_number == "EP-003"


def test_buyee_won_list_item_name_column_keeps_wrapped_japanese_titles() -> None:
    """Order numbers sit in the middle of a wrapped Item Name. Use the right column."""

    words = [
        (8.0, 39.0, "Shop"),
        (8.0, 70.0, "Name"),
        (8.0, 168.5, "Order"),
        (8.0, 351.0, "Name"),
        (16.0, 500.0, "Insured"),
        (16.0, 530.0, "Delivery"),
        (45.0, 325.0, "EP-003"),
        (45.0, 400.0, "4曲入EP"),
        (45.0, 470.0, "山口百恵"),
        (62.0, 325.0, "HIT"),
        (62.0, 360.0, "PACK"),
        (62.0, 410.0, "SERIES"),
        (89.5, 168.5, "R25082301242"),
        (180.0, 325.0, "山口百恵"),
        (180.0, 400.0, "さよならの向う側"),
        (199.0, 325.0, "ep"),
        (199.0, 360.0, "レコード"),
        (183.0, 168.5, "R25082301823"),
        (420.0, 324.0, "C00097077/EP1枚組-33RPM"),
        (436.0, 325.0, "山口百恵"),
        (436.0, 400.0, "愛に走って"),
        (437.5, 168.5, "R25082506047"),
        (584.0, 338.5, "7inch"),
        (584.0, 400.0, "山口百恵"),
        (600.0, 325.0, "MOMOE"),
        (600.0, 400.0, "YAMAGUCHI"),
        (608.0, 168.5, "R25082902565"),
    ]
    titles = _buyee_won_list_visual_titles_from_words(words)
    assert len(titles) == 4
    assert "EP-003" in titles[0] and "HIT PACK" in titles[0] and "山口百恵" in titles[0]
    assert "さよなら" in titles[1]
    assert "C00097077" in titles[2] and "愛に走って" in titles[2]
    assert "7inch" in titles[3] and "YAMAGUCHI" in titles[3]
    assert all("R250" not in title for title in titles)
    assert purchase_media(titles[0]) == "EP_7_INCH"
    assert purchase_media(titles[2]) == "EP_7_INCH"
    assert purchase_media(titles[3]) == "EP_7_INCH"


def test_buyee_won_title_keeps_song_and_ep_from_either_ocr_pass() -> None:
    """A clipped Item Name crop still keeps さよなら / EP from the word boxes."""

    sayonara = _merge_buyee_won_title(
        "レア盤 多数出品中 最安値 死と詩 ep レコード",
        "レコ さよなら の ド",
    )
    assert "さよなら" in sayonara
    assert purchase_media(sayonara) == "EP_7_INCH"
    lot = _merge_buyee_won_title(
        "6枚セット いい日旅立ち、ひと夏の経験",
        "即決 EP レコード 6枚セット 赤い衝撃他",
    )
    assert "6枚セット" in lot
    assert purchase_media(lot) == "EP_7_INCH"
    clover = _merge_buyee_won_title(
        "OA EPL A—k 33回転4 愛に走って ありがとう 白い約束",
        "曲入り 愛に走って バー・シリーズ",
    )
    assert "愛に走って" in clover
    assert purchase_media(clover) == "EP_7_INCH"


def test_buyee_won_list_titles_overlay_the_invoice_in_print_order() -> None:
    """The won-auction PNG names the copies. Zip those names onto the invoice."""

    invoice = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name [ee onto - ZOEY a
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(d1194852974)
    Item Name Uri Sickie WG UO SkeSOMIM
    Item Price 399
    Shopping Site(ID) JDirectItems Auction(b1197144157)
    Item Name b1197144157
    Item Price 380
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    """
    won = """
    Shop Name Order Number Item Name
    JDirectItems Auction R25082301242
    EP-003 4曲入EP 山口百恵 HIT PACK SERIES
    JDirectItems Auction R25082301823
    レア盤 山口百恵 さよならの向う側 ep レコード
    JDirectItems Auction R25082506047
    C00097077/EP1枚組-33RPM/山口百恵「愛に走って/白い約束 (4曲入)」
    """
    parsed = parse_purchase_pages([invoice, won])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"x728495200", "d1194852974", "b1197144157"}
    assert "HIT PACK" in by_id["x728495200"].title
    assert "さよなら" in by_id["d1194852974"].title
    assert "愛に走って" in by_id["b1197144157"].title
    assert "C00097077" in by_id["b1197144157"].title
    assert purchase_media(by_id["b1197144157"].title) == "EP_7_INCH"


def test_buyee_won_list_replaces_short_invoice_cjk() -> None:
    """Invoice OCR can keep まで or Name. The won-list Item Name is the copy."""

    invoice = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 4曲入EP
    Item Price 1,500
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name Name . 。 / 【7inch】山口百恵 春風のいたずら MOMOE YAMAGUCHI EP
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    Item Name d1196280358
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    Item Name まで
    Item Price 160
    Other Service Fees
    Plan Fee 2,000
    Buyee Service Fee 1,200
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    """
    won = """
    Won title EP-003 4曲入EP 山口百恵 HIT PACK SERIES
    Won title 【7inch】山口百恵 春風のいたずら 禁じられた遊び MOMOE YAMAGUCHI / EP
    Won title 山口百恵 EPレコード 愛に走って クローバー
    Won title 即決 EP レコード 山口百恵 冬の色 湖の決心
    """
    parsed = parse_purchase_pages([invoice, won])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert "HIT PACK" in by_id["x728495200"].title
    assert "7inch" in by_id["s1073507969"].title
    assert "Name" not in by_id["s1073507969"].title
    assert "愛に走って" in by_id["d1196280358"].title
    assert by_id["d1196280358"].title.lower() != "d1196280358"
    assert "冬の色" in by_id["m1178811814"].title
    assert "まで" not in by_id["m1178811814"].title
    assert purchase_media(by_id["d1196280358"].title) == "EP_7_INCH"
    assert purchase_media(by_id["m1178811814"].title) == "EP_7_INCH"


def test_buyee_invoice_drops_name_chrome_and_made_fragment() -> None:
    """The Item Name header and 枚まで送料 are not the record."""

    page = """
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name Name . 。 / 【7inch】山口百恵 春風のいたずら MOMOE YAMAGUCHI EP
    Item Price 1,000
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    a all aia り 愛に走って ありがとう あなた 白い約束 山鳩
    Item Name
    Item Price 300
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    18 lz 枚 EP 送料 メール 140 山口百恵 冬の色 湖の決心 ゴールデンシングル
    Item Name まで
    Item Price 160
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert "7inch" in by_id["s1073507969"].title
    assert "Name" not in by_id["s1073507969"].title
    assert by_id["d1196280358"].title.startswith("愛に走って")
    assert "aia" not in by_id["d1196280358"].title.lower()
    assert by_id["d1196280358"].title.lower() != "d1196280358"
    assert "冬の色" in by_id["m1178811814"].title
    assert "まで" not in by_id["m1178811814"].title
    assert "送料" not in by_id["m1178811814"].title
    assert "メール" not in by_id["m1178811814"].title
    assert "140" not in by_id["m1178811814"].title
    assert "由" not in by_id["m1178811814"].title
    assert purchase_media(by_id["d1196280358"].title) == "EP_7_INCH"
    assert purchase_media(by_id["m1178811814"].title) == "EP_7_INCH"


def test_buyee_column_hammers_win_when_visual_prices_miss_the_grand() -> None:
    """11 visual prices can still be the breakdown (310, 230, 140). The column is the hammers."""

    page = """
    Shopping Site(ID) JDirectItems Auction(x728495200)
    Item Name EP-003 HIT PACK SERIES
    Shopping Site(ID) JDirectItems Auction(d1194852974)
    Item Name さよならの向う側 EP
    Shopping Site(ID) JDirectItems Auction(n1148641695)
    Item Name 春風のいたずら EP
    Shopping Site(ID) JDirectItems Auction(n1195916122)
    Item Name 6枚セット
    Shopping Site(ID) JDirectItems Auction(b1197144157)
    Item Name C00097077/EP
    Shopping Site(ID) JDirectItems Auction(f1197129190)
    Item Name C00145878/EP
    Shopping Site(ID) JDirectItems Auction(s1073507969)
    Item Name 7inch MOMOE YAMAGUCHI EP
    Shopping Site(ID) JDirectItems Auction(d1196280358)
    Item Name 愛に走って EP
    Shopping Site(ID) JDirectItems Auction(n1054308529)
    Item Name Hit Pack Series EP
    Shopping Site(ID) JDirectItems Auction(f1104283743)
    Item Name EP 0825
    Shopping Site(ID) JDirectItems Auction(m1178811814)
    Item Name 冬の色 EP
    Other Service Fees
    Plan Fee 5,500
    Buyee Service Fee 3,300
    Domestic Shipping Fee(From seller to Buyee) 2,680
    Protective Packaging Fee 1,500
    International Shipping Fee 10,521
    Customs Duty 1,400
    Grand Total Payment Amount
    31,900YEN
    Visual auction x728495200 title  price 1500 rows 11
    Visual auction d1194852974 title  price 230 rows 11
    Visual auction n1148641695 title  price 700 rows 11
    Visual auction n1195916122 title  price 310 rows 11
    Visual auction b1197144157 title  price 380 rows 11
    Visual auction f1197129190 title  price 380 rows 11
    Visual auction s1073507969 title  price 1000 rows 11
    Visual auction d1196280358 title  price 1280 rows 11
    Visual auction n1054308529 title  price 250 rows 11
    Visual auction f1104283743 title  price 140 rows 11
    Visual auction m1178811814 title  price 160 rows 11
    Column item 1500
    Column item 399
    Column item 500
    Column item 700
    Column item 380
    Column item 380
    Column item 1000
    Column item 300
    Column item 1280
    Column item 400
    Column item 160
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["d1194852974"].paid_amount == Decimal("399")
    assert by_id["n1148641695"].paid_amount == Decimal("500")
    assert by_id["n1195916122"].paid_amount == Decimal("700")
    assert by_id["d1196280358"].paid_amount == Decimal("300")
    assert by_id["n1054308529"].paid_amount == Decimal("1280")
    assert by_id["f1104283743"].paid_amount == Decimal("400")
    tally = lot_tally(parsed.purchases)
    assert tally.balanced is True
    assert tally.line_sum == Decimal("31900")
    assert tally.grand == Decimal("31900")


def test_buyee_ep_title_picks_the_ep_when_the_catalog_is_on_lp_and_ep() -> None:
    """Same catalog on an LP and an EP: the bill says EP, so that pressing wins."""

    purchase = ParsedPurchase(
        source="buyee",
        external_id="b1197144157",
        title="山口百恵 愛に走って EP 09SH-894",
        seller="Buyee",
        paid_amount=Decimal("380"),
        paid_currency="JPY",
        paid_on=None,
        catalog_number="09SH-894",
    )
    assert purchase_media(purchase.title) == "EP_7_INCH"
    lp = PressingChoice(
        pressing_id=10,
        catalog_number="09SH-894",
        artist_name="Momoe Yamaguchi",
        album_title="Ai ni Hashitte",
        media_type="LP",
    )
    ep = PressingChoice(
        pressing_id=11,
        catalog_number="09SH-894",
        artist_name="Momoe Yamaguchi",
        album_title="Ai ni Hashitte",
        media_type="EP_7_INCH",
    )
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={fold_catalog("09SH-894"): (lp, ep)},
    )
    assert match.status == "new_copy"
    assert match.pressings == (ep,)


def test_buyee_price_column_keeps_500_and_300_hammers_before_plan_total() -> None:
    """500 and 300 in the item run are hammers. 5,500 after eleven copies is plan."""

    rows = [
        (0, Decimal("1500")),
        (10, Decimal("399")),
        (20, Decimal("500")),
        (30, Decimal("700")),
        (40, Decimal("380")),
        (50, Decimal("380")),
        (60, Decimal("1000")),
        (70, Decimal("300")),
        (80, Decimal("1280")),
        (90, Decimal("400")),
        (100, Decimal("160")),
        (110, Decimal("5500")),
        (120, Decimal("3300")),
        (130, Decimal("2680")),
        (140, Decimal("1500")),
    ]
    assert _buyee_leading_item_prices(rows) == [
        Decimal("1500"),
        Decimal("399"),
        Decimal("500"),
        Decimal("700"),
        Decimal("380"),
        Decimal("380"),
        Decimal("1000"),
        Decimal("300"),
        Decimal("1280"),
        Decimal("400"),
        Decimal("160"),
    ]


def test_buyee_price_bands_keep_a_sandwiched_500_hammer() -> None:
    """A 500 printed once between doubled hammers is still an item price."""

    flat = [
        (0, Decimal("1500")),
        (8, Decimal("1500")),
        (40, Decimal("399")),
        (48, Decimal("399")),
        (80, Decimal("500")),
        (120, Decimal("700")),
        (128, Decimal("700")),
        (160, Decimal("300")),
        (200, Decimal("1280")),
        (208, Decimal("1280")),
    ]
    amounts = [amount for _top, amount in _buyee_price_bands(flat)]
    assert Decimal("500") in amounts
    assert Decimal("300") in amounts
    assert Decimal("399") in amounts


def test_buyee_lot_tally_flags_missing_prices_and_tiny_postage() -> None:
    """The 19-copy extract is not add-ready while prices are blank and postage is 21."""

    rows = (
        ParsedPurchase(
            source="buyee",
            external_id="h1200193589",
            title="CBS SONY 25AH673 LP",
            seller="Buyee",
            paid_amount=Decimal("561"),
            paid_currency="JPY",
            paid_on=None,
            catalog_number="25AH-673",
            billing_note="Item price 561 JPY\nPlan fee 500 JPY\nService fee 300 JPY\nDomestic shipping 880 JPY",
            order_id="package:h+u+w",
            package_item=Decimal("561"),
            package_shipping=Decimal("21"),
            package_tax=None,
            package_total=Decimal("25148"),
        ),
        ParsedPurchase(
            source="buyee",
            external_id="u1200253398",
            title="CBS SONY 25AH662 LP",
            seller="Buyee",
            paid_amount=Decimal("352"),
            paid_currency="JPY",
            paid_on=None,
            catalog_number="25AH-662",
            billing_note="Item price 352 JPY\nPlan fee 500 JPY\nDomestic shipping 880 JPY",
            order_id="package:h+u+w",
            package_item=Decimal("561"),
            package_shipping=Decimal("21"),
            package_total=Decimal("25148"),
        ),
        ParsedPurchase(
            source="buyee",
            external_id="w1200194825",
            title="BUDOKAN AT LAST CBS SONY 70AH1141 LP",
            seller="Buyee",
            paid_amount=None,
            paid_currency="JPY",
            paid_on=None,
            catalog_number="70AH-1141",
            billing_note="Plan fee 500 JPY\nService fee 300 JPY",
            order_id="package:h+u+w",
            package_shipping=Decimal("21"),
            package_total=Decimal("25148"),
        ),
    )
    tally = lot_tally(rows)
    assert tally.copies == 3
    assert tally.missing_prices == 1
    assert tally.international == Decimal("21")
    assert tally.balanced is False
    caption = tally.caption()
    assert "missing an item price" in caption
    assert "70AH-1141" in caption
    assert "Remainder" in caption
    assert "Order date is missing" in caption
    assert "too small" in caption
    assert "does not match grand total" not in caption
    described = describe_lot(rows)
    assert "missing an item price" in described
    assert "too small" in described
    blank_postage = lot_tally(
        tuple(replace(row, package_shipping=None) for row in rows)
    )
    assert "international shipping is missing" in blank_postage.caption()


def test_buyee_unpriced_copies_take_leftover_column_prices() -> None:
    """Fee-page ids stay on the bill. The item column still has their hammers."""

    page = """
    Shopping Site(ID) JDirectItems Auction(h1200193589)
    Item Name CBS SONY 25AH673 LP
    Item Price 561
    Shopping Site(ID) JDirectItems Auction(u1200253398)
    Item Name CBS SONY 25AH662 LP
    Item Price 352
    Visual auction w1200194825 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price  rows 2
    Visual auction i1200245569 title CBS SONY 27AH1173 LP price  rows 2
    Plan Fee 2,000
    JDirectItems Auction(w1200194825)
    500
    JDirectItems Auction(i1200245569)
    500
    JDirectItems Auction(h1200193589)
    500
    JDirectItems Auction(u1200253398)
    500
    Buyee Service Fee 1,200
    International Shipping Fee 18,642
    Customs Duty 1,105
    Grand Total Payment Amount 27,061YEN
    Column item 561
    Column item 1,001
    Column item 352
    Column item 440
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["h1200193589"].paid_amount == Decimal("561")
    assert by_id["u1200253398"].paid_amount == Decimal("352")
    assert by_id["w1200194825"].paid_amount == Decimal("1001")
    assert by_id["i1200245569"].paid_amount == Decimal("440")
    assert lot_tally(parsed.purchases).missing_prices == 0


def test_buyee_catalog_digits_are_not_the_hammer_when_another_amount_is_there() -> None:
    """70AH1141 / 27AH1173 in the price column are the catalog. The yen is next."""

    assert _buyee_visual_amount(
        "BUDOKAN AT LAST CBS SONY 70AH1141 LP",
        [Decimal("1141"), Decimal("1001")],
    ) == Decimal("1001")
    assert _buyee_visual_amount(
        "CBS SONY 27AH1173 LP",
        [Decimal("1173"), Decimal("440")],
    ) == Decimal("440")
    assert _buyee_visual_amount(
        "CBS SONY 25AH424 LP",
        [Decimal("424"), Decimal("352")],
    ) == Decimal("352")
    assert _buyee_visual_amount(
        "AT CBS SONY SOLL57 LP",
        [Decimal("57"), Decimal("561")],
    ) == Decimal("561")
    assert _buyee_visual_amount(
        "BUDOKAN AT LAST CBS SONY 70AH1141 LP",
        [Decimal("1141")],
    ) is None
    assert _buyee_visual_amount(
        "CBS SONY 25AH550 LP",
        [Decimal("550")],
    ) == Decimal("550")
    assert _buyee_visual_amount("春風のいたずら EP", [Decimal("500")]) == Decimal("500")
    assert _buyee_visual_amount("愛に走って EP", [Decimal("300")]) == Decimal("300")


def test_buyee_unpriced_catalog_rows_take_leftover_hammers_not_catalog_digits() -> None:
    """Visual OCR of 70AH1141 as 1,141 is dropped. Column 1,001 is the bill."""

    page = """
    Shopping Site(ID) JDirectItems Auction(w1200194825)
    Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
    Shopping Site(ID) JDirectItems Auction(i1200245569)
    Item Name CBS SONY 27AH1173 LP
    Visual auction w1200194825 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 1141 rows 4
    Visual auction i1200245569 title CBS SONY 27AH1173 LP price 1173 rows 4
    Visual auction h1200193589 title CBS SONY 25AH673 LP price 561 rows 4
    Visual auction u1200253398 title CBS SONY 25AH662 LP price 352 rows 4
    Plan Fee 2,000
    Buyee Service Fee 1,200
    International Shipping Fee 18,642
    Grand Total Payment Amount 27,061YEN
    Column item 561
    Column item 352
    Column item 1,001
    Column item 440
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["w1200194825"].paid_amount == Decimal("1001")
    assert by_id["i1200245569"].paid_amount == Decimal("440")
    assert by_id["h1200193589"].paid_amount == Decimal("561")
    assert by_id["u1200253398"].paid_amount == Decimal("352")


def test_buyee_catalog_row_without_item_name_still_keeps_the_hammer() -> None:
    """Item Name / Item Price dropped. Catalog and the doubled yen are still the row."""

    page = """
    JDirectItems Auction(w1200194825)
    BUDOKAN AT LAST CBS SONY 70AH1141 LP
    1,001
    1,001
    JDirectItems Auction(i1200245569)
    CBS SONY 27AH1173 LP
    440
    440
    JDirectItems Auction(e1199280461)
    AT LAST CBS SONY 70AH1141 LP
    671
    671
    JDirectItems Auction(s1200000057)
    AT CBS SONY SOLL57 LP
    561
    561
    Plan Fee 2,000
    Buyee Service Fee 1,200
    International Shipping Fee 18,642
    Customs Duty 1,105
    Grand Total Payment Amount 24,891YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["w1200194825"].paid_amount == Decimal("1001")
    assert by_id["i1200245569"].paid_amount == Decimal("440")
    assert by_id["e1199280461"].paid_amount == Decimal("671")
    assert by_id["s1200000057"].paid_amount == Decimal("561")


def test_buyee_letter_twin_keeps_one_copy_and_the_hammer() -> None:
    """OCR reads u1200194825 as w1200194825. That is one Budokan, not two."""

    page = """
    Shopping Site(ID) JDirectItems Auction(h1200193589)
    Item Name CBS SONY 25AH673 LP
    Item Price 561
    Shopping Site(ID) JDirectItems Auction(u1200194825)
    Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
    Shopping Site(ID) JDirectItems Auction(k1197487045)
    Item Name CBS SONY 25AH424 LP
    Shopping Site(ID) JDirectItems Auction(l1200245569)
    Item Name CBS SONY 27AH1173 LP
    Visual auction w1200194825 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price  rows 4
    Visual auction u1200194825 title CBS SONY 25AH424 LP price 550 rows 4
    Visual auction i1200245569 title CBS SONY 27AH1173 LP price  rows 4
    Visual auction l1200245569 title BUDOKAN AT LAST CBS SONY 70AH1141 LP price 352 rows 4
    Plan Fee 2,000
    Buyee Service Fee 1,200
    Domestic Shipping Fee 3,520
    International Shipping Fee 18,642
    Customs Duty 1,105
    Grand Total Payment Amount 27,930YEN
    Column item 561
    Column item 550
    Column item 281
    Column item 352
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "h1200193589",
        "u1200194825",
        "k1197487045",
        "l1200245569",
    }
    assert by_id["h1200193589"].paid_amount == Decimal("561")
    assert by_id["u1200194825"].paid_amount == Decimal("550")
    assert by_id["k1197487045"].paid_amount == Decimal("281")
    assert by_id["l1200245569"].paid_amount == Decimal("352")
    assert "70AH1141" in (by_id["u1200194825"].title or "").replace("-", "")
    assert "27AH1173" in (by_id["l1200245569"].title or "").replace("-", "")


def test_buyee_plan_and_service_totals_are_not_item_prices() -> None:
    """8,000 and 4,800 are the package plan and service totals, not hammers."""

    page = """
    Shopping Site(ID) JDirectItems Auction(t1200181464)
    Item Name CBS SONY 25AH550 LP
    Item Price 550
    Shopping Site(ID) JDirectItems Auction(d1200258354)
    Item Name CBS SONY 25AH250 LP
    Item Price 352
    Visual auction t1200181464 title CBS SONY 25AH550 LP price 8000 rows 2
    Visual auction d1200258354 title CBS SONY 25AH250 LP price 4800 rows 2
    Plan Fee 8,000
    Buyee Service Fee 4,800
    Domestic Shipping Fee 14,080
    Protective Packaging Fee 1,500
    International Shipping Fee 26,121
    Customs Duty 1,045
    Grand Total Payment Amount 56,448YEN
    Column item 550
    Column item 352
    Column item 8000
    Column item 4800
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["t1200181464"].paid_amount == Decimal("550")
    assert by_id["d1200258354"].paid_amount == Decimal("352")


def test_buyee_customs_in_the_price_column_is_not_a_leftover_hammer() -> None:
    """1,045 under the hammers is customs, not a 17th item price."""

    page = """
    Shopping Site(ID) JDirectItems Auction(n1199280461)
    Item Name AT LAST CBS SONY 70AH1141 LP
    Shopping Site(ID) JDirectItems Auction(m1197484840)
    Item Name MOBIUS GAME CBS SONY 25AH974 LP
    Shopping Site(ID) JDirectItems Auction(h1200193589)
    Item Name CBS SONY 25AH673 LP
    Item Price 561
    Visual auction n1199280461 title AT LAST CBS SONY 70AH1141 LP price  rows 3
    Visual auction m1197484840 title MOBIUS GAME CBS SONY 25AH974 LP price  rows 3
    Visual auction h1200193589 title CBS SONY 25AH673 LP price 561 rows 3
    Plan Fee 1,500
    Buyee Service Fee 900
    International Shipping Fee 18,642
    Customs Duty 1,045
    Grand Total Payment Amount 22,891YEN
    Column item 440
    Column item 303
    Column item 561
    Column item 1045
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["n1199280461"].paid_amount == Decimal("440")
    assert by_id["m1197484840"].paid_amount == Decimal("303")
    assert by_id["h1200193589"].paid_amount == Decimal("561")


def test_buyee_mai_set_rows_do_not_keep_the_auction_id_or_a_neighbor_catalog() -> None:
    """16枚セット / 19枚セット are lots, not the 25AH974 LP above them."""

    page = """
    Shopping Site(ID) JDirectItems Auction(e1200184568)
    Item Name CBS SONY 25AH974 LP
    Item Price 550
    Shopping Site(ID) JDirectItems Auction(e1200237291)
    Item Name 7 UT 1 6B yb
    Item Price 704
    Shopping Site(ID) JDirectItems Auction(n1200244324)
    Item Name 7 WUT RE/ 1 9B 7
    Item Price 704
    Visual auction e1200184568 title CBS SONY 25AH974 LP price 550 rows 3
    Visual auction e1200237291 title CBS SONY 25AH974 LP price 704 rows 3
    Visual auction n1200244324 title n1200244324 price 704 rows 3
    Plan Fee 1,500
    Buyee Service Fee 900
    International Shipping Fee 18,642
    Grand Total Payment Amount 22,000YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    sixteen = by_id["e1200237291"]
    nineteen = by_id["n1200244324"]
    assert sixteen.paid_amount == Decimal("704")
    assert nineteen.paid_amount == Decimal("704")
    assert "25AH" not in (sixteen.title or "")
    assert sixteen.catalog_number in {None, ""}
    assert "16" in (sixteen.title or "")
    assert nineteen.title != "n1200244324"
    assert "19" in (nineteen.title or "")
    assert nineteen.catalog_number in {None, ""}
    assert purchase_media(sixteen.title) == "EP_7_INCH"
    assert purchase_media(nineteen.title) == "EP_7_INCH"
    assert by_id["e1200184568"].catalog_number == "25AH-974"


def test_buyee_item_block_keeps_a_hammer_without_the_item_price_label() -> None:
    """OCR often drops Item Price and leaves the yen on its own line."""

    page = """
    Shopping Site(ID) JDirectItems Auction(w1200194825)
    Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
    Quantity 1
    1001
    Total Amount 1001
    Shopping Site(ID) JDirectItems Auction(i1200245569)
    Item Name CBS SONY 27AH1173 LP
    Quantity 1
    440
    Total Amount 440
    Plan Fee 1,000
    Buyee Service Fee 600
    International Shipping Fee 18,642
    Grand Total Payment Amount 21,083YEN
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["w1200194825"].paid_amount == Decimal("1001")
    assert by_id["i1200245569"].paid_amount == Decimal("440")


def test_buyee_price_column_attaches_when_the_row_text_never_says_item_price() -> None:
    """The wide read can keep the auction id and lose the words Item Price."""

    mashed = """
    Shopping Site(ID) JDirectItems Auction(f1204890335) | SOLL170 LP
    Shopping Site(ID) JDirectItems Auction(u1204905847) | SOLL141 LP
    Shopping Site(ID) JDirectItems Auction(b1205857894) | 70AH1141 LP
    """
    attached = _attach_item_prices(
        mashed, [Decimal("440"), Decimal("440"), Decimal("671")]
    )
    assert attached is not None
    parsed = parse_purchase_export(
        attached
        + """
        Plan Fee 1,500
        Buyee Service Fee 900
        Customs Duty 1,105
        """
    )
    by_id = {row.external_id: row for row in parsed.purchases}
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert by_id["b1205857894"].paid_amount == Decimal("671")
    assert by_id["f1204890335"].package_tax == Decimal("1105")
    assert all(
        copy_costs(row.billing_note)["customs"] is None for row in parsed.purchases
    )


def test_buyee_price_column_fills_truncated_rows_and_skips_a_missing_domestic() -> None:
    """A wide screenshot loses the price column. The column read puts it back.

    Plan and service are on every auction. Domestic is only on the auctions
    in that breakdown. The grand total is the check sum, not the postage.
    """

    page = """
    Shopping Site(ID) JDirectItems Auction(f1 204890335)
    Item Name SOLL170 LP
    ltemPrice 4
    Shopping Site(ID) JDirectItems Auction(ul 204905847)
    ItemName SOLL141 LP
    Quantity 1
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOBIUS S GAME 25AH974 LP
    Item Price 4,290
    Other Service Fees
    Plan Fee 1,500
    Buyee Service Fee 900
    Domestic Shipping Fee(From seller to Buyee) 1,760
    Customs Duty 1,105
    Grand Total Payment Amount
    28,324YEN
    Domestic Shipping Fee
    SOLL170 LP 880
    (f1204890335)
    SOLL141 LP 880
    (1204905847)
    Column item 440
    Column item 440
    Column item 4290
    Column fee 1500 500
    Column fee 1500 500
    Column fee 1500 500
    Column fee 900 300
    Column fee 900 300
    Column fee 900 300
    Column fee 1760 880
    Column fee 1760 880
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert [row.external_id for row in parsed.purchases] == [
        "f1204890335",
        "u1204905847",
        "j1204895542",
    ]
    assert by_id["f1204890335"].paid_amount == Decimal("440")
    assert by_id["u1204905847"].paid_amount == Decimal("440")
    assert by_id["j1204895542"].paid_amount == Decimal("4290")
    costs = {auction_id: copy_costs(row.billing_note) for auction_id, row in by_id.items()}
    for auction_id in by_id:
        assert costs[auction_id]["plan_fee"] == Decimal("500")
        assert costs[auction_id]["service_fee"] == Decimal("300")
        assert costs[auction_id]["shipping"] is None
    assert costs["f1204890335"]["domestic_shipping"] == Decimal("880")
    assert costs["u1204905847"]["domestic_shipping"] == Decimal("880")
    assert costs["j1204895542"]["domestic_shipping"] is None
    for row in costs.values():
        assert row["customs"] is None
    assert by_id["f1204890335"].package_tax == Decimal("1105")
    assert by_id["f1204890335"].package_total == Decimal("28324")


def test_buyee_duties_and_a_swallowed_domestic_total_still_split() -> None:
    """'Customs Duties' is the tax. 9,200 is the fee block, not one record's postage."""

    page = """
    Shopping Site(ID) JDirectItems Auction(f1204890335)
    Item Name SOLL170 LP
    Item Price 440
    Shopping Site(ID) JDirectItems Auction(j1204895542)
    Item Name MOBIUS 25AH974 LP
    Item Price 4,290
    Shopping Site(ID) JDirectItems Auction(b1205857894)
    Item Name 70AH1141 LP
    Item Price 671
    Domestic Shipping Fee(From seller to Buyee)
    Total Amount 9,200
    Customs Duties and Value-Added Tax
    1,105
    Grand Total Payment Amount
    28,324YEN
    Domestic Shipping Fee
    SOLL170 LP 880
    Auction(f1204890335)
    70AH1141 LP 880
    Auction(b1205857894)
    Column fee 1760 880
    Column fee 1760 880
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    costs = {auction_id: copy_costs(row.billing_note) for auction_id, row in by_id.items()}
    assert costs["f1204890335"]["domestic_shipping"] == Decimal("880")
    assert costs["b1205857894"]["domestic_shipping"] == Decimal("880")
    assert costs["j1204895542"]["domestic_shipping"] is None
    for row in costs.values():
        assert row["customs"] is None
    assert by_id["f1204890335"].package_tax == Decimal("1105")
    assert all(row["shipping"] is None for row in costs.values())


def test_two_complete_buyee_invoices_stay_separate() -> None:
    first = """
    Shopping Site(ID) JDirectItems Auction(m1233352030)
    Item Name Enka LP
    Item Price 16,335
    Plan Fee 500
    International Shipping Fee 3,860
    """
    second = """
    Shopping Site(ID) JDirectItems Auction(h1230354706)
    Item Name Hits LP
    Item Price 36,500
    Plan Fee 800
    International Shipping Fee 1,000
    """
    parsed = parse_purchase_pages([first, second])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"m1233352030", "h1230354706"}
    assert copy_costs(by_id["m1233352030"].billing_note)["plan_fee"] == Decimal("500")
    assert copy_costs(by_id["h1230354706"].billing_note)["plan_fee"] == Decimal("800")
    assert copy_costs(by_id["m1233352030"].billing_note)["shipping"] == Decimal("3860")
    assert copy_costs(by_id["h1230354706"].billing_note)["shipping"] == Decimal("1000")


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


def test_ocr_ebay_card_without_dollar_signs_is_still_a_bill() -> None:
    page = """
    litem 100.00
    Shipping 4.47 Tax* 6.25
    Order total 110.72
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    row = parsed.purchases[0]
    assert row.paid_amount == Decimal("100.00")
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("4.47")
    assert costs["tax"] == Decimal("6.25")
    assert row.package_total == Decimal("110.72")


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


def test_ebay_order_details_skips_the_feedback_prompt() -> None:
    page = """
    How do you like our order details page?
    Time placed Aug 8, 2025 at 9:14 PM
    Order number 10-13426-54807
    Sold by nakameshi
    Momoe Legend Model Number 00AH 1021 5 CBS SONY $157.00
    Item number: 336089377666
    1 item        $157.00
    Shipping      $7.77
    Tax*          $9.81
    Order total   $174.58
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.external_id == "336089377666"
    assert listing_title_is_chrome(row.title) is False
    assert "How do you like" not in row.title
    assert "Item number" not in row.title
    assert "Legend" in row.title
    assert row.catalog_number == "00AH-1021"
    assert copy_costs(row.billing_note)["shipping"] == Decimal("7.77")


def test_ebay_purchase_history_extracts_titles_when_the_listing_is_gone() -> None:
    page = """
    Delivered
    Order date: Aug 18, 2025 · Order total: US $12.75 · Order number: 09-13469-73751
    Delivered on Mon, Aug 25
    Return Window Closed on Sep 24.
    Momoe Yamaguchi - Zettai Zetsumei (Hopeless Situation) Record Japan Import
    US $12.75
    Sold by: retronippon_games
    View order details
    View similar items
    Delivered
    Order date: Aug 08, 2025 · Order total: US $174.58 · Order number: 10-13426-54807
    Delivered on Sat, Aug 23
    Return Window Closed on Sep 22.
    Momoe Legend Model Number 00AH 1021 5 CBS SONY
    US $174.58
    Sold by: nakameshi
    View order details
    Delivered
    Order date: Jul 31, 2025 · Order total: US $98.81 · Order number: 09-13393-63262
    Delivered on Wed, Aug 6
    Return Window Closed on Sep 5.
    Yamaguchi Momoe Legend Star LP 5-Disc Set, 60 Songs k5
    US $98.81
    Sold by: hanabi358
    """
    parsed = parse_purchase_pages([page])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {
        "09-13469-73751",
        "10-13426-54807",
        "09-13393-63262",
    }
    hopeless = by_id["09-13469-73751"]
    legend = by_id["10-13426-54807"]
    star = by_id["09-13393-63262"]
    assert "Zettai Zetsumei" in hopeless.title
    assert "How do you like" not in hopeless.title
    assert hopeless.paid_amount == Decimal("12.75")
    assert hopeless.paid_on == date(2025, 8, 18)
    assert hopeless.delivered_on == date(2025, 8, 25)
    assert legend.delivered_on == date(2025, 8, 23)
    assert star.delivered_on == date(2025, 8, 6)
    assert "Legend" in legend.title
    assert legend.catalog_number == "00AH-1021"
    assert legend.paid_amount == Decimal("174.58")
    assert "Legend Star" in star.title
    assert star.paid_amount == Decimal("98.81")
    assert listing_title_is_chrome(
        "Item number: 336089377666 How do you like our order details page?"
    )
    assert listing_title_is_chrome(legend.title) is False


def test_purchase_history_keeps_each_order_date_from_the_card() -> None:
    """A history screenshot is evidence. Later cards must not inherit Oct 1."""

    combined = """
    Combined shipping: Delivered.
    Order date: Jan 16, 2025 · Order total: US $404.73 · Order number: 02-12597-42736
    Teresa Teng/Airport /Yukigeshou MR2259 Used LP
    US $45.79
    Sold by: recordshop_shibuya
    Teresa Teng/Aijin 28TR2062 Used LP
    US $72.15
    Sold by: recordshop_shibuya
    Teresa Teng/Feng Er Yu Er 28MX1026 Used LP
    US $239.42
    Sold by: recordshop_shibuya
    """
    later = """
    Delivered
    Order date: Jan 12, 2025 · Order total: US $84.36 · Order number: 16-12566-32738
    Teresa Teng - Love Songs of the Island Vol. 3 Light Rain MRM1003 Japan
    US $84.36
    Sold by: ajfl463
    Delivered
    Order date: Dec 07, 2024 · Order total: US $253.09 · Order number: 26-12409-47504
    Teresa Teng Fujian Famous Songs Album Hong Kong LP
    US $253.09
    Sold by: vds_tokyo
    """
    october = """
    Order info Time placed Oct 1, 2024 at 7:15 PM
    Delivered
    Order date: Oct 01, 2024 · Order total: US $87.51 · Order number: 17-12134-37331
    梅艷芳夢裡共醉
    US $87.51
    Sold by: chitunhuangggg
    """
    glued = parse_purchase_pages([combined, later, october])
    airport = next(row for row in glued.purchases if "MR2259" in row.title)
    aijin = next(row for row in glued.purchases if "28TR2062" in row.title)
    feng = next(row for row in glued.purchases if "28MX1026" in row.title)
    assert airport.paid_on == date(2025, 1, 16)
    assert aijin.paid_on == date(2025, 1, 16)
    assert feng.paid_on == date(2025, 1, 16)
    assert airport.paid_amount == Decimal("45.79")
    assert aijin.paid_amount == Decimal("72.15")
    assert feng.paid_amount == Decimal("239.42")
    island = next(row for row in glued.purchases if "Island" in row.title)
    fujian = next(row for row in glued.purchases if "Fujian" in row.title)
    assert island.paid_on == date(2025, 1, 12)
    assert island.paid_amount == Decimal("84.36")
    assert fujian.paid_on == date(2024, 12, 7)
    assert fujian.paid_amount == Decimal("253.09")
    dream = next(row for row in glued.purchases if "夢裡共醉" in row.title)
    assert dream.paid_on == date(2024, 10, 1)
    assert dream.paid_amount == Decimal("87.51")
    assert "Time placed" not in dream.title
    assert len([row for row in glued.purchases if row.order_id == "02-12597-42736"]) == 3
    assert _ebay_page_is_fragment(later) is False
    assert glued.source == "ebay"


def test_ebay_order_details_item_number_is_the_listing() -> None:
    page = """
    Time placed Sep 13, 2026 at 10:56 PM
    Order number 09-15165-64209
    Total $41.58 (1 item)
    Sold by billygantiquesect
    1 item        $35.00
    Shipping      $4.39
    Tax*          $2.19
    Order total   $41.58
    Teresa Teng With Love From... Teresa Teng 12" Black Vinyl LP $35.00
    Item number: 377493856081
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    row = parsed.purchases[0]
    assert row.external_id == "377493856081"
    assert row.paid_amount == Decimal("35.00")
    assert row.order_id == "09-15165-64209"
    assert row.seller == "billygantiquesect"
    assert row.paid_on == date(2026, 9, 13)
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("4.39")
    assert costs["tax"] == Decimal("2.19")


def test_ebay_one_item_order_card_keeps_shipping_and_the_order_number() -> None:
    page = """
    Time placed Sep 15, 2026 at 11:38 PM
    Order number 21-15152-88132
    Total $105.00 (1 item)
    Sold by conduit200
    1 item        $80.00
    Shipping      $20.00
    Tax*          $5.00
    Order total   $105.00
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.paid_amount == Decimal("80.00")
    assert row.paid_on == date(2026, 9, 15)
    assert row.seller == "conduit200"
    assert row.order_id == "21-15152-88132"
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("20.00")
    assert costs["tax"] == Decimal("5.00")
    assert "Order total 105 USD" in row.billing_note or "Order total 105.00 USD" in row.billing_note


def test_ebay_order_without_shipping_line_is_free_shipping() -> None:
    """A picture that states tax but no shipping is free shipping, not a blank."""

    page = """
    1 item        $12.00
    Tax*          $0.75
    Order total   $12.75
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("0")
    assert costs["tax"] == Decimal("0.75")
    shipping, tax, fees = shelf_charge_amounts(
        shipping_amount=None,
        tax_amount=None,
        fee_amount=None,
        billing_note=row.billing_note,
    )
    assert shipping == Decimal("0")
    assert tax == Decimal("0.75")
    assert fees == Decimal("0")


def test_shelf_charges_keep_tax_out_of_the_shipping_column() -> None:
    shipping, tax, fees = shelf_charge_amounts(
        shipping_amount=None,
        tax_amount=None,
        fee_amount=None,
        billing_note="Tax 5.81 USD\nOrder total 98.81 USD",
    )
    assert shipping == Decimal("0")
    assert tax == Decimal("5.81")
    assert fees == Decimal("0")
    shipping, tax, fees = shelf_charge_amounts(
        shipping_amount=Decimal("7.77"),
        tax_amount=Decimal("9.81"),
        fee_amount=None,
        billing_note="",
    )
    assert shipping == Decimal("7.77")
    assert tax == Decimal("9.81")
    assert fees == Decimal("0")


def test_ebay_order_details_keep_the_160_card() -> None:
    page = """
    1 item        $160.00
    Shipping      $6.50
    Tax*          $10.00
    Order total   $176.50
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.paid_amount == Decimal("160.00")
    assert "Shipping 6.50 USD" in row.billing_note
    assert "Tax 10 USD" in row.billing_note
    assert "Order total 176.50 USD" in row.billing_note
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("6.50")
    assert costs["tax"] == Decimal("10.00")


def test_ebay_au_totals_card_ocr_reads_shipping_and_tax() -> None:
    """The usual second screenshot is the AU totals card. litem is 1 item."""

    ocr = """
    Ending in 2368 © 132:19
    Tom Wang AU 197.63
    Dec 4 at 7:03 PM
    litem AU 150.00
    Shipping AU 38.25 Tax* AU 9.38
    Order total AU 197.63
    """
    assert _extracted_bill_has_charges([ocr]) is True
    parsed = parse_purchase_export(ocr)
    assert parsed.source == "ebay"
    row = parsed.purchases[0]
    assert row.paid_amount == Decimal("150.00")
    assert row.paid_currency == "AUD"
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("38.25")
    assert costs["tax"] == Decimal("9.38")
    assert copy_cost_currency(row.billing_note) == "AUD"
    clean = """
    1 item        AU $150.00
    Shipping      AU $38.25
    Tax*          AU $9.38
    Order total   AU $197.63
    """
    billed = parse_purchase_export(clean).purchases[0]
    assert billed.paid_amount == Decimal("150.00")
    assert billed.paid_currency == "AUD"
    assert copy_costs(billed.billing_note)["shipping"] == Decimal("38.25")


def test_ebay_au_totals_card_stamp_is_paid_on() -> None:
    """The AU card date is 'Dec 4 at 7:03 PM', not a leftover Oct 1 Time placed."""

    ocr = """
    Ending in 2368 © 132:19
    Tom Wang AU 197.63
    Dec 4 at 7:03 PM
    litem AU 150.00
    Shipping AU 38.25 Tax* AU 9.38
    Order total AU 197.63
    """
    row = parse_purchase_export(ocr).purchases[0]
    today = date.today()
    year = today.year if date(today.year, 12, 4) <= today else today.year - 1
    assert row.paid_on == date(year, 12, 4)


def test_ebay_au_details_ocr_recovers_paid_date_from_poid_and_dec_amp() -> None:
    """Usual full order screenshot. Tesseract psm 6 reads Paid as Poid and Dec 4 as Dec&."""

    ocr = """
    Delivery info Delivered on Fri, Dec 20, 2024 [a] Ening in 2368 Os
    Poid Tracking Delivered cada
    Dec& available Dec 20
    Decs item AU$i60.00
    Shipping AU $38.25
    Tracking details Tex Au $9.38
    Anita Mui Bad Girl Capital Artists AU $150.00
    CAL-04-1029 1986 Hong Kong
    Item number: 146230842586
    """
    parsed = parse_purchase_export(ocr)
    row = parsed.purchases[0]
    assert row.paid_on == date(2024, 12, 4)
    assert row.external_id == "146230842586"
    assert row.paid_amount == Decimal("150.00")
    assert copy_costs(row.billing_note)["shipping"] == Decimal("38.25")
    assert copy_costs(row.billing_note)["tax"] == Decimal("9.38")


def test_ebay_au_sparse_ocr_stamp_plus_block_ocr_charges() -> None:
    """psm 11 keeps Dec 4 at 7:08PM; psm 6 keeps Shipping AU $38.25. Join both."""

    block = """
    Delivery info Delivered on Fri, Dec 20, 2024
    Poid Tracking Delivered cada
    Dec& available Dec 20
    Shipping AU $38.25
    Tax* AU $9.38
    Order total AU $197.63
    1 item AU $150.00
    Item number: 146230842586
    """
    sparse = """
    Delivered on Fri, Dec 20, 2024
    Dec 4 at 7:08PM
    Paid
    Shipping Au $98.25
    Tax Au $938
    Order total Au $197.63
    """
    row = parse_purchase_export(block + "\n" + sparse).purchases[0]
    assert row.paid_on == date(2024, 12, 4)
    assert copy_costs(row.billing_note)["shipping"] == Decimal("38.25")


def test_ebay_sparse_ocr_date_lines_do_not_split_the_item() -> None:
    """A second Tesseract pass may repeat Item number and invent $98.25 shipping."""

    block = """
    Shipping AU $38.25
    Tax* AU $9.38
    Order total AU $197.63
    1 item AU $150.00
    Item number: 146230842586
    """
    sparse = """
    Delivered on Fri, Dec 20, 2024
    Dec 4 at 7:08PM
    Paid
    Shipping Au $98.25
    Tax Au $938
    Order total Au $197.63
    Item number: 146230842586
    """
    text = block + "\n" + _date_bearing_ocr_lines(sparse)
    parsed = parse_purchase_export(text)
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.paid_on == date(2024, 12, 4)
    assert row.external_id == "146230842586"
    assert copy_costs(row.billing_note)["shipping"] == Decimal("38.25")
    assert copy_costs(row.billing_note)["tax"] == Decimal("9.38")


def test_ebay_au_order_stamp_uses_delivered_year_not_delivered_day() -> None:
    """Usual details page: Paid/card stamp Dec 4, year from Delivered on 2024."""

    page = """
    Delivered on Fri, Dec 20, 2024
    Dec 4 at 7:03 PM
    1 item AU $150.00
    Shipping AU $38.25
    Tax* AU $9.38
    Order total AU $197.63
    Anita Mui Bad Girl CAL-04-1029
    Item number: 146230842586
    """
    row = parse_purchase_export(page).purchases[0]
    assert row.paid_on == date(2024, 12, 4)
    assert row.external_id == "146230842586"
    assert copy_costs(row.billing_note)["shipping"] == Decimal("38.25")


def test_ebay_refund_after_payment_is_a_price_cut_not_item() -> None:
    """Item stays $80. The $24.06 PayPal refund comes off landed."""

    page = """
    You got a refund! A total of $24.06 was sent on May 11, 2025.
    Time placed May 11, 2025 at 6:48 PM
    Order number 02-13075-83859
    Total $88.94 (1 item)
    Sold by kwax
    k) TERESA TENG Hong Kong Taiwan Chinese PROJECT 24 Japan LP with lyrics sheet $80.00
    Item number: 356885503887
    Return window closed on Jun 14, 2025.
    Tell us what you think
    1 Item $80.00
    Shipping $28.00
    Tax* $5.00
    Amount paid $113.00
    Total refunded** -$24.06
    Order total $88.94
    How do you like our order details page?
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.external_id == "356885503887"
    assert row.paid_amount == Decimal("80.00")
    assert "PROJECT 24" in row.title
    assert listing_title_is_chrome(row.title) is False
    assert "Return window" not in row.title
    assert "Tell us what you think" not in row.title
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("28.00")
    assert costs["tax"] == Decimal("5.00")
    assert costs["refund"] == Decimal("-24.06")
    assert copy_refund(
        row.billing_note,
        item=Decimal("80.00"),
        shipping=Decimal("28.00"),
        tax=Decimal("5.00"),
        fees=Decimal("0"),
    ) == Decimal("-24.06")
    already = (
        "Shipping 28 USD\n"
        "Tax 5 USD\n"
        "Order total 88.94 USD"
    )
    assert copy_refund(
        already,
        item=Decimal("80.00"),
        shipping=Decimal("28.00"),
        tax=Decimal("5.00"),
        fees=Decimal("0"),
    ) == Decimal("-24.06")
    package = (
        "Shipping 19.60 USD\n"
        "Tax 7.53 USD\n"
        "Order total 371.67 USD"
    )
    assert copy_refund(
        package,
        item=Decimal("120.50"),
        shipping=Decimal("19.60"),
        tax=Decimal("7.53"),
        fees=Decimal("0"),
    ) is None
    assert listing_title_is_chrome(
        "TAI Return window closed on Jun 14, 2025. Tell us what you think"
    )


def test_billing_panel_shows_refund_on_landed() -> None:
    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    view = source.split("def _copy_price_view", 1)[1].split("def _landed_label", 1)[0]
    panel = source.split("def _show_billing_panel", 1)[1].split(
        "def _show_record_panel", 1
    )[0]
    assert "copy_refund" in view
    assert '"Refund"' in panel


def test_two_standalone_ebay_orders_stay_two_purchases() -> None:
    first = """
    Time placed Feb 9, 2026 at 8:10 PM
    Order number 11-11111-11111
    Sold by vinylshop
    TERESA TENG GOODBYE MY LOVE POLYDOR 2488304 Hong Kong INSERT VINYL LP $91.00
    Item number: 366150834599
    1 item        $91.00
    Shipping      $14.80
    Tax*          $5.69
    Order total   $111.49
    """
    second = """
    Time placed Sep 13, 2026 at 10:56 PM
    Order number 09-15165-64209
    Sold by billygantiquesect
    Teresa Teng With Love From... Teresa Teng 12" Black Vinyl LP $35.00
    Item number: 377493856081
    1 item        $35.00
    Shipping      $4.39
    Tax*          $2.19
    Order total   $41.58
    """
    glued = parse_purchase_export(combine_bill_pages([first, second]))
    assert {row.external_id for row in glued.purchases} != {
        "366150834599",
        "377493856081",
    } or any(
        copy_costs(row.billing_note).get("shipping")
        not in {Decimal("14.80"), Decimal("4.39")}
        for row in glued.purchases
    )
    parsed = parse_purchase_pages([first, second])
    glued_pages = parse_purchase_pages([combine_bill_pages([first, second])])
    assert {row.external_id for row in glued_pages.purchases} == {
        "366150834599",
        "377493856081",
    }
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"366150834599", "377493856081"}
    goodbye = by_id["366150834599"]
    love = by_id["377493856081"]
    assert goodbye.paid_amount == Decimal("91.00")
    assert copy_costs(goodbye.billing_note)["shipping"] == Decimal("14.80")
    assert copy_costs(goodbye.billing_note)["tax"] == Decimal("5.69")
    assert love.paid_amount == Decimal("35.00")
    assert copy_costs(love.billing_note)["shipping"] == Decimal("4.39")
    assert copy_costs(love.billing_note)["tax"] == Decimal("2.19")


def test_combined_ebay_pages_still_join_as_one_order() -> None:
    totals = """
    2 items                 $339.98
    Shipping                $10.44
    Tax*                    $21.25
    Order total             $371.67
    """
    item = """
    Number 9434608106244817193389
    Item info
    Teresa Teng Greatest Hits Vol. 3 鄧麗君 Vinyl Record LP 1982 Polydor Hong Kong $179.99
    Item number: 326150009894
    Returns not accepted.
    """
    parsed = parse_purchase_pages([totals, item])
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "326150009894"
    assert copy_costs(row.billing_note)["shipping"] == Decimal("5.53")


def test_ebay_two_item_totals_card_is_a_package_not_the_selected_copy() -> None:
    page = """
    Order date: Feb 14, 2026
    2 items                 $339.98
    Shipping                $10.44
    Tax*                    $21.25
    Order total             $371.67
    """
    parsed = parse_purchase_export(page)
    row = parsed.purchases[0]
    assert row.external_id.startswith("package:2:")
    assert row.paid_amount == Decimal("339.98")
    assert row.paid_on == date(2026, 2, 14)
    assert "Shipping 10.44 USD" in row.billing_note
    assert "Tax 21.25 USD" in row.billing_note


def test_ebay_totals_card_plus_item_info_is_that_copy_share() -> None:
    totals = """
    2 items                 $339.98
    Shipping                $10.44
    Tax*                    $21.25
    Order total             $371.67
    """
    item = """
    Number 9434608106244817193389
    Item info
    Teresa Teng Greatest Hits Vol. 3 鄧麗君 Vinyl Record LP 1982 Polydor Hong Kong $179.99
    Item number: 326150009894
    Returns not accepted.
    """
    parsed = parse_purchase_export(combine_bill_pages([totals, item]))
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "326150009894"
    assert row.paid_amount == Decimal("179.99")
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("5.53")
    assert costs["tax"] == Decimal("11.25")
    item_only = parse_purchase_export(item)
    assert item_only.purchases
    assert all(
        value is None
        for value in copy_costs(item_only.purchases[0].billing_note).values()
    )


def test_one_item_number_on_a_two_item_ebay_order_gets_its_share() -> None:
    page = """
    Delivered on Sat, Feb 21, 2026
    Paid Feb 14
    Teresa Teng Greatest Hits Vol. 3 鄧麗君 Vinyl Record LP 1982 Polydor Hong Kong $179.99
    Item number: 326150009894
    2 items $339.98
    Shipping $10.44
    Tax* $21.25
    Order total $371.67
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 1
    row = parsed.purchases[0]
    assert row.external_id == "326150009894"
    assert row.paid_amount == Decimal("179.99")
    assert row.paid_on == date(2026, 2, 14)
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("5.53")
    assert costs["tax"] == Decimal("11.25")


def test_two_pages_of_one_ebay_order_match_item_numbers_and_split_postage() -> None:
    page_one = """
    Delivered on Sat, Feb 21, 2026
    Paid Feb 14
    Teresa Teng Greatest Hits Vol. 3 鄧麗君 Vinyl Record LP 1982 Polydor Hong Kong $179.99
    Item number: 326150009894
    2 items $339.98
    Shipping $10.44
    Tax* $21.25
    Order total $371.67
    """
    page_two = """
    Time placed Feb 14, 2026 at 10:10 PM
    Order number 20-14224-85378
    Sold by professorsells
    Teresa Teng 鄧麗君 償還 Vinyl Record LP Polydor 825 403-1 Polygram Hong Kong 1985 $159.99
    Item number: 326150109657
    """
    parsed = parse_purchase_pages([page_one, page_two])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"326150009894", "326150109657"}
    hits = by_id["326150009894"]
    repaid = by_id["326150109657"]
    assert hits.paid_amount == Decimal("179.99")
    assert repaid.paid_amount == Decimal("159.99")
    ships = [
        copy_costs(hits.billing_note)["shipping"] or Decimal("0"),
        copy_costs(repaid.billing_note)["shipping"] or Decimal("0"),
    ]
    taxes = [
        copy_costs(hits.billing_note)["tax"] or Decimal("0"),
        copy_costs(repaid.billing_note)["tax"] or Decimal("0"),
    ]
    assert sum(ships, Decimal("0")) == Decimal("10.44")
    assert sum(taxes, Decimal("0")) == Decimal("21.25")
    assert hits.paid_on == date(2026, 2, 14)
    assert repaid.paid_on == date(2026, 2, 14)
    assert hits.seller == "professorsells"
    assert repaid.seller == "professorsells"


def test_ebay_two_item_details_ignore_leftover_one_item_order_info() -> None:
    """Oct 1 7:18 2-item $165.14 card, plus leftover Order info $87.51 / 17-12134-37331."""

    two_item = """
    Delivered on Mon, Oct 7, 2024
    Paid
    Oct 1
    Tracking details
    Number 9449008105463011110843
    陳慧嫻反叛首版黑膠唱片12寸vinyl $68.00
    的$100三張特價
    Item number: 335585657869
    Returns not accepted.
    Oct 1 at 7:18 PM
    2 items $146.00
    Shipping $10.01
    Tax* $9.13
    Order total $165.14
    Order info
    Time placed Oct 1, 2024 at 7:15 PM
    Order number 17-12134-37331
    Total $87.51 (1 item)
    Sold by chitunhuangggg
    """
    sibling = """
    Order info
    Time placed Oct 1, 2024 at 7:15 PM
    Order number 17-12134-37331
    Total $87.51 (1 item)
    Sold by chitunhuangggg
    Delivered on Mon, Oct 7, 2024
    Paid
    Oct 1
    Tracking details
    Number 9449008105463011110843
    梅艷芳夢裡共醉首版黑膠唱片 $78.00
    的$100三張特價
    Item number: 335598379065
    Returns not accepted.
    """
    parsed = parse_purchase_pages([two_item, sibling])
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"335585657869", "335598379065"}
    priscilla = by_id["335585657869"]
    anita = by_id["335598379065"]
    assert priscilla.paid_amount == Decimal("68.00")
    assert anita.paid_amount == Decimal("78.00")
    assert priscilla.paid_on == date(2024, 10, 1)
    assert anita.paid_on == date(2024, 10, 1)
    ships = [
        copy_costs(priscilla.billing_note)["shipping"] or Decimal("0"),
        copy_costs(anita.billing_note)["shipping"] or Decimal("0"),
    ]
    taxes = [
        copy_costs(priscilla.billing_note)["tax"] or Decimal("0"),
        copy_costs(anita.billing_note)["tax"] or Decimal("0"),
    ]
    assert sum(ships, Decimal("0")) == Decimal("10.01")
    assert sum(taxes, Decimal("0")) == Decimal("9.13")
    assert "陳慧嫻" in priscilla.title
    assert "夢裡共醉" in anita.title
    assert "9449008105463011110843" not in priscilla.title
    assert "Time placed" not in anita.title
    assert listing_title_is_chrome("Order info Time placed Oct 1, 2024 at 7:15 PM")


def test_ocr_junk_titles_are_not_the_record_or_the_catalog() -> None:
    assert listing_title_is_ocr_junk(
        "Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00"
    )
    assert listing_title_is_ocr_junk(
        "P< || SBS SEAM SS BIH 12I vinyl HERA N4SLA © $78.00"
    )
    assert listing_title_is_ocr_junk("we HBHG8855 RIES OSS IB A 12sl vinyl lh AE")
    assert listing_title_is_ocr_junk(
        "we HBHG8855 RIES OSS IB A 12sI vinyl ih AE BA UE LABL45 $58.00 "
        "*We're required by law to collect sales tax and"
    )
    assert ocr_promo_item_price(
        "we HBHG8855 RIES OSS IB A 12sI vinyl ih AE BA UE LABL45 $58.00 "
        "*We're required by law to collect sales tax and",
        Decimal("100"),
    ) == Decimal("58.00")
    assert listing_title_is_ocr_junk(
        "Order info Time placed Oct 1, 2024 at 7:15 PM"
    )
    assert listing_title_is_ocr_junk("Teresa Teng vinyl LP $50.00") is False
    assert listing_title_is_ocr_junk(
        "TERESA TENG ZAI SHUI YI FANG POLYDOR 2427329 Hong Kong INSERT VINYL LP $120.50"
    ) is False
    assert listing_title_is_ocr_junk("陳慧嫻反叛首版黑膠唱片12寸vinyl $68.00") is False
    assert owned_copy_shows_on_shelf(
        "Order info Time placed Oct 1, 2024 at 7:15 PM"
    ) is False
    assert owned_copy_shows_on_shelf(
        "Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00"
    ) is True
    assert listing_catalog_is_structured("HBHG-8855")
    assert listing_catalog_is_structured("BIH 12I") is False
    assert ocr_promo_item_price(
        "Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00",
        Decimal("100"),
    ) == Decimal("68.00")
    assert ocr_promo_item_price(
        "Teresa Teng Fujian Famous Songs Album Hon",
        Decimal("217.50"),
    ) is None


def test_ebay_ocr_stew_does_not_keep_promo_100_or_invented_catalogs() -> None:
    """English Tesseract of $100 三張特價 listings is not the album or the catno."""

    page = """
    Delivered on Mon, Oct 7, 2024
    Paid
    Oct 1
    Tracking details
    Number 9449008105463011110843
    Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00
    的$100三張特價
    Item number: 335585657869
    P< || SBS SEAM SS BIH 12I vinyl HERA N4SLA © $78.00
    的$100三張特價
    Item number: 335598379065
    2 items $146.00
    Shipping $10.01
    Tax* $9.13
    Order total $165.14
    Order info
    Time placed Oct 1, 2024 at 7:15 PM
    Order number 17-12134-37331
    Total $87.51 (1 item)
    Sold by chitunhuangggg
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"335585657869", "335598379065"}
    priscilla = by_id["335585657869"]
    anita = by_id["335598379065"]
    assert priscilla.paid_amount == Decimal("68.00")
    assert anita.paid_amount == Decimal("78.00")
    assert priscilla.title == ""
    assert anita.title == ""
    assert not priscilla.catalog_number
    assert not anita.catalog_number
    assert "BIH" not in (anita.catalog_number or "")
    assert listing_title_is_ocr_junk(priscilla.title) is False


def test_ebay_order_info_chrome_is_left_out() -> None:
    purchase = ParsedPurchase(
        source="ebay",
        external_id="17-12134-37331",
        title="Order info Time placed Oct 1, 2024 at 7:15 PM",
        seller="chitunhuangggg",
        paid_amount=Decimal("87.51"),
        paid_currency="USD",
        paid_on=date(2024, 10, 1),
        catalog_number=None,
        billing_note="Shipping 1.76 USD\nTax 0.22 USD\nOrder total 87.51 USD",
    )
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={},
    )
    assert match.status == "left_out"


def test_owned_copy_values_replace_promo_100_on_ocr_junk() -> None:
    purchase = ParsedPurchase(
        source="ebay",
        external_id="335585657869",
        title="Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00",
        seller="x",
        paid_amount=Decimal("68.00"),
        paid_currency="USD",
        paid_on=date(2024, 10, 1),
        catalog_number="BIH 12I",
    )
    title, catalog, paid = _owned_copy_values(
        purchase,
        catalog_number="",
        paid_amount=Decimal("100"),
        current_title="Zoos PRIS IRS ARABI A 12st vinyl dh ERI RAE © $68.00",
        current_catalog="BIH 12I",
        current_paid=Decimal("100"),
    )
    assert title == ""
    assert catalog is None
    assert paid == Decimal("68.00")
    hbhg_title = (
        "we HBHG8855 RIES OSS IB A 12sI vinyl ih AE BA UE LABL45 $58.00 "
        "*We're required by law to collect sales tax and"
    )
    hbhg = ParsedPurchase(
        source="ebay",
        external_id="335556522751",
        title=hbhg_title,
        seller="x",
        paid_amount=Decimal("100"),
        paid_currency="USD",
        paid_on=date(2024, 10, 1),
        catalog_number="HBHG-8855",
    )
    title, catalog, paid = _owned_copy_values(
        hbhg,
        catalog_number="",
        paid_amount=Decimal("100"),
        current_title=hbhg_title,
        current_catalog="HBHG-8855",
        current_paid=Decimal("100"),
    )
    assert title == ""
    assert catalog == "HBHG-8855"
    assert paid == Decimal("58.00")


def test_save_billing_note_writes_paid_on_and_never_matches_catalog() -> None:
    source = inspect.getsource(save_billing_note)
    assert "manual_purchase_date" in source
    assert "CAST(:paid_on AS date)" in source
    assert "_update_owned_copy_bill" in source
    assert "if updated == 0 and folded" not in source


def test_ebay_delivery_info_keeps_the_delivered_day() -> None:
    """The green Delivered on line is the delivery date. Paid stays the card stamp."""

    page = """
    Delivery info
    Delivered on Fri, Dec 13, 2024
    Paid Dec 7
    Tracking available Dec 10
    Delivered Dec 13
    Teresa Teng Fujian Famous Songs Album Hong Kong LP $217.50
    Item number: 356335023487
    Return window closed on Jan 12, 2025.
    Dec 7 at 8:26 PM
    1 item $217.50
    Shipping $22.00
    Tax* $13.59
    Order total $253.09
    """
    row = parse_purchase_export(page).purchases[0]
    assert row.external_id == "356335023487"
    assert row.paid_on == date(2024, 12, 7)
    assert row.delivered_on == date(2024, 12, 13)
    assert row.paid_amount == Decimal("217.50")


def test_ebay_two_item_order_keeps_each_line_price_and_the_discount() -> None:
    page = """
    Time placed Mar 29, 2025 at 7:44 PM
    Order number 15-12885-06541
    Total $211.35 (2 items)
    Sold by facerecords
    Delivered on Wed, Apr 2, 2025
    TERESA TENG LOVE IN HONG KONG POLYDOR MRM1004 $137.99
    Item number: 335878825166
    TERESA TENG FURUSATO HA DOKO DESUKA POLYDOR $68.99
    Item number: 365420143314
    2 items $206.98
    Item discount -$31.05
    Shipping $36.00
    Tax* $11.00
    Amount paid $222.93
    Total refunded** -$11.58
    Order total $211.35
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    hong_kong = by_id["335878825166"]
    furusato = by_id["365420143314"]
    assert hong_kong.paid_amount == Decimal("137.99")
    assert furusato.paid_amount == Decimal("68.99")
    assert hong_kong.paid_on == date(2025, 3, 29)
    assert hong_kong.delivered_on == date(2025, 4, 2)
    assert furusato.paid_on == date(2025, 3, 29)
    assert furusato.delivered_on == date(2025, 4, 2)
    assert {row.paid_amount for row in parsed.purchases} != {Decimal("211.35")}
    costs = [copy_costs(row.billing_note) for row in (hong_kong, furusato)]
    assert sum(item["shipping"] or 0 for item in costs) == Decimal("36.00")
    assert sum(item["tax"] or 0 for item in costs) == Decimal("11.00")
    assert sum(item["discount"] or 0 for item in costs) == Decimal("-31.05")
    assert sum(item["refund"] or 0 for item in costs) == Decimal("-11.58")
    assert line_price_replaces_shelf(Decimal("137.99"), hong_kong.billing_note)
    assert not line_price_replaces_shelf(Decimal("211.35"), hong_kong.billing_note)
    assert not line_price_replaces_shelf(Decimal("211.36"), hong_kong.billing_note)


def test_ebay_combined_item_numbers_allocate_shipping() -> None:
    page = """
    3 items $332.00
    Shipping $54.00
    Tax* $20.75
    Order total $406.75
    TERESA TENG ZAI SHUI YI FANG POLYDOR 2427329 Hong Kong INSERT VINYL LP $120.50
    Item number: 236601326474
    TERESA TENG JIN XIAO YE YUE YUAN POLYDOR 2427374 Hong Kong INSERT VINYL LP $120.50
    Item number: 366150834599
    TERESA TENG GREATEST HITS POLYDOR 2427375 Hong Kong INSERT VINYL LP $91.00
    Item number: 236601327666
    """
    parsed = parse_purchase_export(page)
    assert parsed.source == "ebay"
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"236601326474", "366150834599", "236601327666"}
    assert by_id["236601326474"].paid_amount == Decimal("120.50")
    ships = [copy_costs(row.billing_note)["shipping"] or Decimal("0") for row in parsed.purchases]
    taxes = [copy_costs(row.billing_note)["tax"] or Decimal("0") for row in parsed.purchases]
    assert sum(ships, Decimal("0")) == Decimal("54.00")
    assert sum(taxes, Decimal("0")) == Decimal("20.75")
    assert ships[0] == ships[1]


def _one_item_card_png() -> bytes:
    image = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            28,
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text(
        (24, 24),
        "\n".join(
            (
                "Time placed Sep 15, 2026 at 11:38 PM",
                "Order number 21-15152-88132",
                "Sold by conduit200",
                "1 item        $80.00",
                "Shipping      $20.00",
                "Tax*          $5.00",
                "Order total   $105.00",
            )
        ),
        fill="black",
        font=font,
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_screenshot_reads_a_one_item_ebay_card() -> None:
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is required to extract a bill screenshot")
    text = extract_screenshot_bill_text(_one_item_card_png())
    parsed = parse_purchase_export(text)
    row = parsed.purchases[0]
    assert row.paid_on == date(2026, 9, 15)
    assert row.paid_amount == Decimal("80.00")
    costs = copy_costs(row.billing_note)
    assert costs["shipping"] == Decimal("20.00")
    assert costs["tax"] == Decimal("5.00")


def _plain_text_png(message: str) -> bytes:
    image = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            28,
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 48), message, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_harvest_keeps_the_screenshot_when_ocr_has_no_charges() -> None:
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is required to extract a bill screenshot")
    png = _plain_text_png("Just a cover photo")
    harvested = harvest_screenshot_bills([png], [])
    assert harvested.shots == (png,)
    assert harvested.pages == ()
    assert harvested.error is not None
    assert "shipping" in harvested.error.casefold()


def test_harvest_drops_screenshots_only_after_a_real_bill() -> None:
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is required to extract a bill screenshot")
    png = _one_item_card_png()
    harvested = harvest_screenshot_bills([png], [])
    assert harvested.shots == ()
    assert harvested.error is None
    parsed = parse_purchase_export(combine_bill_pages(list(harvested.pages)))
    costs = copy_costs(parsed.purchases[0].billing_note)
    assert costs["shipping"] == Decimal("20.00")
    assert costs["tax"] == Decimal("5.00")


def test_bill_text_from_bytes_refuses_a_screenshot() -> None:
    png = b"\x89PNG\r\n\x1a\nnot-a-bill"
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    assert is_screenshot_bytes(png)
    assert is_screenshot_bytes(jpeg)
    assert is_screenshot_bytes(b"RIFF....WEBP....")
    assert not is_screenshot_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError, match="Paste the order text"):
        bill_text_from_bytes(png)
    with pytest.raises(ValueError, match="Paste the order text"):
        bill_text_from_bytes(jpeg)


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


def test_ebay_purchase_history_combined_order_keeps_both_albums() -> None:
    page = """
    Order date: Feb 14, 2026
    Order number: 20-14224-85378
    Teresa Teng Greatest Hits Vol. 3 鄧麗君 Vinyl Record LP 1982 Polydor Hong Kong $179.99
    https://www.ebay.com/itm/326150009894
    Teresa Teng 鄧麗君 償還 Vinyl Record LP Polydor 825 403-1 Polygram Hong Kong 1985 $159.99
    https://www.ebay.com/itm/326150109657
    Sold by: professorsells
    2 items $339.98
    Shipping $10.44
    Tax* $21.25
    Order total: US $371.67
    """
    parsed = parse_purchase_export(page)
    by_id = {row.external_id: row for row in parsed.purchases}
    assert set(by_id) == {"326150009894", "326150109657"}
    hits = by_id["326150009894"]
    repaid = by_id["326150109657"]
    assert hits.paid_amount == Decimal("179.99")
    assert repaid.paid_amount == Decimal("159.99")
    assert hits.paid_on == date(2026, 2, 14)
    assert repaid.paid_on == date(2026, 2, 14)
    ships = [
        copy_costs(hits.billing_note)["shipping"] or Decimal("0"),
        copy_costs(repaid.billing_note)["shipping"] or Decimal("0"),
    ]
    taxes = [
        copy_costs(hits.billing_note)["tax"] or Decimal("0"),
        copy_costs(repaid.billing_note)["tax"] or Decimal("0"),
    ]
    assert sum(ships, Decimal("0")) == Decimal("10.44")
    assert sum(taxes, Decimal("0")) == Decimal("21.25")
    assert hits.order_id == "20-14224-85378"
    assert repaid.order_id == "20-14224-85378"
    assert hits.package_item == Decimal("339.98")
    assert hits.package_shipping == Decimal("10.44")
    assert hits.package_tax == Decimal("21.25")
    assert hits.package_total == Decimal("371.67")


def test_ebay_package_mate_is_ready_on_the_gripsweat_listing() -> None:
    purchase = parse_purchase_export(
        """
        Order date: Feb 14, 2026
        Order number: 20-14224-85378
        Teresa Teng 鄧麗君 償還 Vinyl Record LP Polydor 825 403-1 $159.99
        https://www.ebay.com/itm/326150109657
        Sold by: professorsells
        Shipping $4.91
        Tax* $10.00
        Order total: US $174.90
        """
    ).purchases[0]
    match = _classify_one(
        purchase,
        listings={
            ("gripsweat", "326150109657"): {
                "marketplace": "gripsweat",
                "listing_id": "326150109657",
                "visible": True,
            }
        },
        owned=set(),
        purchased={("gripsweat", "326150009894")},
        owned_catalogs={fold_catalog("2484 175")},
        pressings={},
    )
    assert match.status == "ready"
    assert match.marketplace == "gripsweat"
    assert match.listing_id == "326150109657"


def test_ebay_item_without_ocr_catalog_is_still_a_new_copy() -> None:
    purchase = parse_purchase_export(
        """
        Teresa Teng vinyl LP $50.00
        Item number: 333333333333
        1 item $50.00
        Shipping $4.00
        Tax* $2.00
        Order total $56.00
        """
    ).purchases[0]
    assert purchase.catalog_number is None
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={},
    )
    assert match.status == "new_copy"
    assert match.purchase.external_id == "333333333333"


def test_ebay_bill_for_purchased_gripsweat_copy_is_backfill() -> None:
    purchase = parse_purchase_export(
        """
        Teresa Teng Greatest Hits Vol. 3 $179.99
        Item number: 326150009894
        2 items $339.98
        Shipping $10.44
        Tax* $21.25
        Order total $371.67
        """
    ).purchases[0]
    match = _classify_one(
        purchase,
        listings={
            ("gripsweat", "326150009894"): {
                "marketplace": "gripsweat",
                "listing_id": "326150009894",
                "visible": True,
            }
        },
        owned=set(),
        purchased={("gripsweat", "326150009894")},
        owned_catalogs={fold_catalog("2484 175")},
        pressings={},
    )
    assert match.status == "backfill"
    assert match.marketplace == "gripsweat"
    assert match.listing_id == "326150009894"


def test_january_order_keeps_both_airport_copies() -> None:
    page = """
    Delivered on Wed, Jan 22, 2025
    Teresa Teng/Airport /Yukigeshou MR2259 Used LP $25.92
    Item number: 226500068370
    Teresa Teng/Aijin 28TR2062 Used LP $71.27
    Item number: 226500068760
    Teresa Teng/Feng Er Yu Er 28MX1026 Used LP $246.19
    Item number: 226516454358
    Teresa Teng/Airport /Yukigeshou MR2259 Used LP $45.35
    Item number: 226516455888
    4 items $388.73
    Item discount -$38.87
    Shipping $33.00
    Tax* $21.87
    Order total $404.73
    Jan 16 at 6:35 AM
    """
    parsed = parse_purchase_export(page)
    assert len(parsed.purchases) == 4
    second = next(row for row in parsed.purchases if row.external_id == "226516455888")
    assert second.paid_amount == Decimal("45.35")
    assert second.paid_on == date(2025, 1, 16)
    assert second.delivered_on == date(2025, 1, 22)
    assert second.catalog_number == "MR-2259"
    match = _classify_one(
        second,
        listings={},
        owned=set(),
        purchased={("ebay", "226500068370")},
        owned_catalogs={fold_catalog("MR 2259")},
        pressings={},
    )
    assert match.status == "new_copy"
    assert "MR-2259" in describe_lot(parsed.purchases)
    assert "4 copies" in describe_lot(parsed.purchases)
    assert is_collected_music("Teresa Teng Young Magazine 1978")
    assert is_collected_music("Teresa Teng 7 inch EP")
    assert is_collected_music("Anita Mui poster") is False


def test_buyee_single_lp_does_not_take_the_box_set_pressing() -> None:
    """70AH1141 on the bill is the single LP when both pressings exist."""

    purchase = parse_purchase_export(
        """
        Shopping Site(ID) JDirectItems Auction(b1205857894)
        Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
        Item Price 671
        Shopping Site(ID) JDirectItems Auction(f1204890335)
        Item Name CBS SONY SOLL170 LP
        Item Price 440
        Plan Fee 1,000
        """
    ).purchases[0]
    assert purchase.catalog_number == "70AH-1141"
    single = PressingChoice(
        pressing_id=99,
        catalog_number="70AH-1141",
        artist_name="Momoe Yamaguchi",
        album_title="Budokan At Last",
    )
    box = PressingChoice(
        pressing_id=156,
        catalog_number="70AH 1141~3",
        artist_name="Momoe Yamaguchi",
        album_title="Densetsu kara Shinwa he",
    )
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={fold_catalog("70AH1141"): (single, box)},
    )
    assert match.status == "new_copy"
    assert match.pressings == (single,)


def test_only_pressing_for_a_catalog_is_used_even_if_it_is_a_range() -> None:
    """Budokan on Buyee prints 70AH1141. The only identity is the 3LP box."""

    purchase = parse_purchase_export(
        """
        Shopping Site(ID) JDirectItems Auction(b1205857894)
        Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
        Item Price 671
        Shopping Site(ID) JDirectItems Auction(f1204890335)
        Item Name CBS SONY SOLL170 LP
        Item Price 440
        """
    ).purchases[0]
    box = PressingChoice(
        pressing_id=156,
        catalog_number="70AH 1141~3",
        artist_name="Momoe Yamaguchi",
        album_title="Densetsu kara Shinwa he",
    )
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs=set(),
        pressings={fold_catalog("70AH1141"): (box,)},
    )
    assert match.pressings == (box,)
    catalog, pressing_id = pressing_for_edited_catalog(box, "70AH-1141")
    assert catalog == "70AH 1141~3"
    assert pressing_id == 156


def test_second_copy_uses_the_pressing_already_on_the_shelf() -> None:
    """A later Cosmos copy skips Discogs when this catalog already has one pressing."""

    first = PressingChoice(
        pressing_id=305,
        catalog_number="25AH 424",
        artist_name="Momoe Yamaguchi",
        album_title="Cosmos = 宇宙",
        media_type="LP",
    )
    reissue = PressingChoice(
        pressing_id=612,
        catalog_number="25AH 424",
        artist_name="Momoe Yamaguchi",
        album_title="Cosmos = 宇宙",
        media_type="LP",
    )
    purchase = ParsedPurchase(
        source="buyee",
        external_id="s1247815641",
        title="山口百恵 COSMOS 宇宙 25AH-424 LP",
        seller="Buyee",
        paid_amount=Decimal("780"),
        paid_currency="JPY",
        paid_on=None,
        catalog_number="25AH-424",
    )
    picked = _single_bill_pressing(
        purchase,
        (first, reissue),
        owned_choices=(first,),
    )
    assert picked == (first,)
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs={fold_catalog("25AH 424")},
        pressings={fold_catalog("25AH 424"): (first, reissue)},
        owned_pressings={fold_catalog("25AH 424"): (first,)},
    )
    assert match.status == "new_copy"
    assert match.pressings == (first,)


def test_discogs_use_this_copies_identity_to_same_catalog_siblings() -> None:
    """A second Cosmos does not pay another Discogs get_release."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    lookup = source.split("def _render_discogs_lookup", 1)[1].split("\ndef ", 1)[0]
    save = source.split("def _save_billing_and_record", 1)[1].split("\ndef ", 1)[0]
    assert "propagate_catalog_identity_to_siblings" in lookup
    assert "propagate_catalog_identity_to_siblings" in save
    assert "apply_release_choice" in lookup
    copied = inspect.getsource(propagate_catalog_identity_to_siblings)
    assigned = inspect.getsource(assign_known_pressing)
    assert "assign_known_pressing" in copied
    assert "get_release" not in copied
    assert "manual_condition_media" not in copied
    assert "manual_verdict" not in copied
    assert "get_release" not in assigned
    assert "_row_pressing_id" in source
    assert "sale.pressing_id" in source
    assert "owned.pressing_id" in source


def test_catalog_identity_groups_copy_one_pressing_and_search_the_rest() -> None:
    """Same Cosmos copies inherit. An unfilled L.A. Blue needs one Discogs search."""

    groups = {
        group.folded: group
        for group in catalog_identity_groups(
            [
                {
                    "marketplace": "buyee",
                    "listing_id": "a",
                    "catalog_number": "25AH 424",
                    "pressing_id": 305,
                    "discogs_thumb_url": "http://thumb",
                    "manual_media_type": "LP",
                    "manual_disc_count": 1,
                },
                {
                    "marketplace": "buyee",
                    "listing_id": "b",
                    "catalog_number": "25AH-424",
                    "pressing_id": None,
                },
                {
                    "marketplace": "buyee",
                    "listing_id": "c",
                    "catalog_number": "25AH 769",
                    "pressing_id": None,
                    "artist_name": "山口百恵",
                    "album_title": "L.A. Blue",
                },
                {
                    "marketplace": "buyee",
                    "listing_id": "lot",
                    "catalog_number": "MIX-1",
                    "manual_media_type": "LP_BULK_LOT",
                    "pressing_id": None,
                },
            ]
        )
    }
    cosmos = groups["25AH424"]
    assert cosmos.pressing_id == 305
    assert cosmos.needs_search is False
    assert ("buyee", "b") in cosmos.copies
    assert cosmos.thumb_url == "http://thumb"
    blue = groups["25AH769"]
    assert blue.needs_search is True
    assert blue.pressing_id is None
    assert "MIX1" not in groups


def test_unique_catalog_release_id_needs_one_locking_hit() -> None:
    hits = [
        {"id": 111, "catno": "25AH 424", "title": "山口百恵 - 秋桜"},
        {"id": 222, "catno": "25AH 769", "title": "山口百恵 - L.A. Blue"},
    ]
    assert unique_catalog_release_id(hits, catalog="25AH 424") == 111
    assert unique_catalog_release_id(hits, catalog="NOPE") is None
    assert unique_catalog_release_id(
        [
            {"id": 1, "catno": "25AH 424"},
            {"id": 2, "catno": "25AH 424"},
        ],
        catalog="25AH 424",
    ) is None


def test_fill_same_catalogs_searches_each_missing_catalog_once() -> None:
    source = inspect.getsource(fill_same_catalog_identities)
    assert "catalog_identity_groups" in source
    assert "assign_known_pressing" in source
    assert "search_user_catalog" in source
    assert "apply_release_choice" in source
    assert "propagate_catalog_identity_to_siblings" in source
    assert "get_release" not in source


def test_buyee_auction_of_an_owned_catalog_is_a_new_copy() -> None:
    """70AH1141 is already the Record City box. This auction is another copy."""

    purchase = parse_purchase_export(
        """
        Shopping Site(ID) JDirectItems Auction(j1205768066)
        Item Name BUDOKAN AT LAST CBS SONY 70AH1141 LP
        Item Price 1,001
        Plan Fee 500
        Buyee Service Fee 300
        Domestic Shipping Fee 880
        """
    ).purchases[0]
    assert purchase.external_id == "j1205768066"
    match = _classify_one(
        purchase,
        listings={},
        owned={("recordcity", "2882749")},
        purchased=set(),
        owned_catalogs={fold_catalog("70AH 1141~3")},
        pressings={},
    )
    assert match.status == "new_copy"
    same = _classify_one(
        purchase,
        listings={},
        owned={("buyee", "j1205768066")},
        purchased=set(),
        owned_catalogs={fold_catalog("70AH1141")},
        pressings={},
    )
    assert same.status == "backfill"


def test_second_ebay_copy_of_an_owned_catalog_is_new() -> None:
    """Item 226462608927 is another MR 2267, not the copy already on the shelf."""

    purchase = parse_purchase_export(
        """
        Delivered on Mon, Dec 16, 2024
        Paid Dec 3
        Delivered Dec 16
        TERESA TENG Yoru No Jokyaku 1975 JAPAN Orig. LP MR 2267 $50.99
        Item number: 226462608927
        Dec 3 at 6:32 AM
        1 item $50.99
        Shipping $22.00
        Tax* $3.19
        Order total $76.18
        """
    ).purchases[0]
    assert purchase.external_id == "226462608927"
    assert purchase.paid_on == date(2024, 12, 3)
    assert purchase.delivered_on == date(2024, 12, 16)
    assert purchase.paid_amount == Decimal("50.99")
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased={("ebay", "405711156123")},
        owned_catalogs={fold_catalog("MR-2267")},
        pressings={},
    )
    assert match.status == "new_copy"
    assert match.listing_id == ""


def test_bill_on_owned_catalog_is_a_backfill() -> None:
    purchase = parse_purchase_export(
        """
        1 item        $160.00
        Shipping      $6.50
        Tax*          $10.00
        Order total   $176.50
        TERESA TENG JIN XIAO YE YUE YUAN POLYDOR 2427374 LP
        """
    ).purchases[0]
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs={fold_catalog("2427374")},
        pressings={},
    )
    assert match.status == "backfill"


def test_owned_catalog_without_charges_stays_already() -> None:
    purchase = logged_purchase(
        where="Shop",
        catalog="2427374",
        title="Teresa Teng LP",
        paid="160",
        currency="USD",
        paid_on=None,
    )
    assert purchase is not None
    match = _classify_one(
        purchase,
        listings={},
        owned=set(),
        purchased=set(),
        owned_catalogs={fold_catalog("2427374")},
        pressings={},
    )
    assert match.status == "already"


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


def test_owned_ebay_copy_gets_a_stub_listing_url() -> None:
    assert stub_auction_url("ebay", "336089377666") == (
        "https://www.ebay.com/itm/336089377666"
    )
    assert listing_url_for_copy(
        marketplace="buyee",
        listing_id="s1247815641",
        stored="",
    ) == "https://buyee.jp/item/jdirectitems/auction/s1247815641"
    assert listing_url_for_copy(
        marketplace="ebay",
        listing_id="336089377666",
        stored="",
    ) == ""
    assert listing_url_for_copy(
        marketplace="ebay",
        listing_id="336089377666",
        stored="https://www.ebay.com/itm/336089377666",
    ) == "https://www.ebay.com/itm/336089377666"
    source = (
        inspect.getsource(save_copy_anatomy)
        + inspect.getsource(ensure_anatomy_copy)
        + inspect.getsource(_promote_owned_copy)
    )
    assert "_promote_owned_copy" in inspect.getsource(save_copy_anatomy)
    assert "owned_copy" in source
    assert "INSERT INTO warehouse.auction" in source
    assert "currency" in inspect.getsource(_promote_owned_copy)
    assert "account.auction_listing" in source
    assert "_LISTING_MARKETS" in inspect.getsource(_promote_owned_copy)
    assert "manual_delivered_on" in inspect.getsource(_promote_owned_copy)
    assert "manual_purchased" in source


def test_shop_order_record_panel_does_not_require_a_listing() -> None:
    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    panel = source.split("def _show_record_panel", 1)[1].split("\ndef ", 1)[0]
    assert "Not linked to a listing." not in panel
    assert "_render_anatomy_form" in panel
    assert "_render_discogs_lookup" in panel
    assert "listing_url_for_copy" in panel
    billing = source.split("def _show_billing_panel", 1)[1].split("\ndef ", 1)[0]
    assert "listing_url_for_copy" in billing


def test_collection_record_form_uses_shelf_media_types() -> None:
    """CD, DVD, cassette, laserdisc, EP, LP, box set, and bulk lots like Review."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    form = source.split("def _render_anatomy_form", 1)[1].split("\ndef ", 1)[0]
    lot = source.split("def _render_lot_counts", 1)[1].split("\ndef ", 1)[0]
    assert "Media type" in form
    assert "COLLECTION_MEDIA_LABELS" in form
    assert "Box set" in source
    assert "Laserdisc" in source
    assert "Bulk lot" in source
    assert "Formats in this lot" in lot
    assert "_render_lot_counts" in form
    assert "collection_bulk_lot" in form
    assert "lot_mix_from_title" in lot
    assert "Disc count" in form
    assert "single sleeve" in form
    assert "gatefold" in form
    assert "manual_media_type" in inspect.getsource(save_copy_anatomy)
    assert 'st.selectbox(\n            "Record"' not in form
    assert "media_label" in form
    values = source.split("def _anatomy_values_from_state", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "manual_media_type" in values
    assert "collection-anatomy-format" in values
    assert "notes_with_lot_mix" in values
    panel = source.split("def _show_record_panel", 1)[1].split("\ndef ", 1)[0]
    assert "collection_bulk_lot" in panel


def test_speed_fill_writes_only_media_type_and_disc_count() -> None:
    """Many selected copies get the common fields. Grades stay on each copy."""

    source = inspect.getsource(apply_common_record_fields)
    assert "manual_media_type" in source
    assert "manual_disc_count" in source
    assert "manual_condition_media" not in source
    assert "save_copy_anatomy" in source
    assert "ensure_anatomy_copy" in source
    page = COLLECTION_PAGE.read_text(encoding="utf-8")
    grid = page.split("response = AgGrid(", 1)[1].split("key=", 1)[0]
    assert '"mode": "multiRow"' in grid
    assert '"headerCheckbox": True' in grid
    assert "Speed fill" in page
    assert "apply_common_record_fields" in page
    assert "_aggrid_selected_rows" in page
    assert "_render_speed_fill" in page


def test_discogs_choice_fills_catalog_region_and_disc_count() -> None:
    values = anatomy_values_from_choice(
        {
            "catalog_number": "248X-358",
            "country": "Hong Kong",
            "disc_count": 1,
            "release_year": 1976,
        }
    )
    assert values["manual_catalog_number"] == "248X-358"
    assert values["manual_region"] == "Hong Kong"
    assert values["manual_disc_count"] == 1
    assert values["manual_pressing_type"] == "FIRST_PRESSING"
    dual = anatomy_values_from_choice(
        {
            "catalog_number": "MRM 1001",
            "label_catnos": ("MRM 1001", "2488 304"),
            "country": "Hong Kong",
            "disc_count": 1,
            "release_year": 1975,
        },
        printed_catalog="2488 304",
    )
    assert dual["manual_catalog_number"] == "2488 304"
    singapore = anatomy_values_from_choice(
        {
            "catalog_number": "248X-358",
            "country": "Singapore & Malaysia",
            "disc_count": None,
            "generation": "REISSUE",
            "release_year": 1976,
        }
    )
    assert singapore["manual_region"] == "Singapore"
    assert singapore["manual_disc_count"] == 1
    assert singapore["manual_pressing_type"] == "REISSUE"


def test_one_save_writes_billing_and_the_record() -> None:
    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    save = source.split('if st.button("Save this record"', 1)[1].split("\ndef ", 1)[0]
    facts = source.split("if save_facts:", 1)[1].split("confirm_key", 1)[0]
    together = source.split("def _save_billing_and_record", 1)[1].split("\ndef ", 1)[0]
    status = source.split("def _show_fill_status", 1)[1].split("\ndef ", 1)[0]
    assert "_save_billing_and_record" in save
    assert "_save_billing_and_record" in facts
    assert "save_shelf_facts" in together
    assert "save_copy_anatomy" in together
    assert "manual_media_type" in together
    assert "propagate_catalog_identity_to_siblings" in together
    assert "shelf_copy_filled" in together
    assert "_advance_to_closest_open" in together
    assert "This copy is filled" in status
    assert "Still needs" in status
    assert '"Filled"' in source


def test_edition_form_packs_insert_poster_and_pinup() -> None:
    both = collector_review_support.edition_values_from_form(
        insert="Yes",
        poster="Yes",
        notes="",
    )
    assert both["manual_insert_present"] is True
    assert both["manual_poster_present"] is True
    insert_only = collector_review_support.edition_values_from_form(
        insert="Insert only",
        poster="Yes",
        notes="obi worn",
    )
    assert insert_only["manual_insert_present"] is True
    assert insert_only["manual_poster_present"] is False
    assert collector_review_support.INSERT_ONLY_NOTE in insert_only["manual_completeness_notes"]
    assert "obi worn" in insert_only["manual_completeness_notes"]
    pinup_insert = collector_review_support.edition_values_from_form(
        insert="Pin-up is the insert",
        poster="Yes",
        notes="",
    )
    assert pinup_insert["manual_insert_present"] is True
    assert pinup_insert["manual_poster_present"] is False
    assert (
        collector_review_support.PINUP_INSERT_NOTE
        in pinup_insert["manual_completeness_notes"]
    )
    pinup_poster = collector_review_support.edition_values_from_form(
        insert="Factory no insert",
        poster="Pin-up is the poster",
        notes="",
    )
    assert pinup_poster["manual_insert_present"] is False
    assert pinup_poster["manual_poster_present"] is False
    assert (
        collector_review_support.FACTORY_NO_INSERT_NOTE
        in pinup_poster["manual_completeness_notes"]
    )
    assert collector_review_support.insert_owns_poster("Factory no insert") is True


def test_non_mint_grades_cannot_be_sealed() -> None:
    assert collector_review_support.sealed_allowed_for_grades("M", "M") is True
    assert collector_review_support.sealed_allowed_for_grades("S", "S") is True
    assert collector_review_support.sealed_allowed_for_grades("S", "M") is True
    assert collector_review_support.sealed_allowed_for_grades("EX", "VG+") is False
    assert collector_review_support.sealed_allowed_for_grades("M", "EX") is False
    assert collector_review_support.sealed_allowed_for_grades(
        "Automatic / unset",
        "M",
    ) is False
    assert collector_review_support.sealed_choice_for_grades(
        "EX",
        "VG+",
        "Yes",
    ) == "No"
    assert collector_review_support.sealed_choice_for_grades(
        "M",
        "M",
        "Yes",
    ) == "Yes"


def test_shelf_grid_selects_by_listing_identity() -> None:
    """Index-based row ids save the bill onto the wrong copy when the shelf moves."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    show = source.split("def _show_collected", 1)[1].split("def _show_missing", 1)[0]
    assert 'f"{index}:' not in show
    assert '"marketplace"' in show
    assert '"listing_id"' in show
    assert "_shelf_row_from_grid" in show
    assert "onRowDataUpdated" not in show
    page = COLLECTION_PAGE.read_text(encoding="utf-8")
    joined = page.split("pd.concat([collected, owned]", 1)[1].split(
        "pressings = load_pressings", 1
    )[0]
    assert "_sections_then_oldest" in joined
    assert "paid_on" in joined


def test_buyee_lot_editor_shows_included_consumption_tax() -> None:
    """The Bring-in table must surface the 10% already inside a Buyee hammer."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    editor = source.split("def _batch_editor", 1)[1].split("def _purchase_from_edit", 1)[0]
    assert "buyee_tax_included" in editor
    assert "tax_included" in editor
    assert 'costs["customs"]' in editor
    assert "Tax included" in editor
    assert "The price you see is 110%" in editor
    assert "tax-inside-v2:" in editor
    view = source.split("def _copy_price_view", 1)[1].split("def _landed_label", 1)[0]
    assert "_scan_amount(tax_usd, shown_tax, charge_code)" in view
    review = source.split("def _review_purchases", 1)[1].split("def _render_log", 1)[0]
    assert "The item price includes 10% consumption tax" in review
    assert "lot_tally" in review
    assert "st.warning" in review


def test_buyee_billing_shows_domestic_and_international_apart_from_ebay() -> None:
    """eBay keeps Item / Shipping / Tax / Fees. Buyee also lines up the invoice."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    panel = source.split("def _show_billing_panel", 1)[1].split(
        "def _show_record_panel", 1
    )[0]
    assert "buyee_lines" in panel
    assert '"Domestic"' in panel
    assert '"International"' in panel
    assert '"Plan fee"' in panel
    assert '"Service fee"' in panel
    assert '"Clearance"' in panel
    assert '"Customs"' in panel
    show = source.split("def _show_collected", 1)[1].split("def _show_missing", 1)[0]
    assert "buyee_package_display_lines" in show
    assert '"Domestic"' in show
    assert '"Intl"' in show
    assert "seller to warehouse" in source.lower() or "domestic" in show.lower()


def _hold_purchase(external_id: str, *, catalog: str | None = None, title: str = "Teng") -> ParsedPurchase:
    return ParsedPurchase(
        source="ebay",
        external_id=external_id,
        title=title,
        seller="seller",
        paid_amount=Decimal("10.00"),
        paid_currency="USD",
        paid_on=date(2026, 1, 1),
        catalog_number=catalog,
    )


def test_held_import_batch_survives_a_partial_reparse() -> None:
    """Catalog Add must not drop the ready copies if the drop re-parses as two orders."""

    held = [_hold_purchase(str(n)) for n in range(1, 10)]
    done = {"9"}
    remaining = [row for row in held if row.external_id != "9"]
    partial = [_hold_purchase("2"), _hold_purchase("9")]
    kept = hold_import_purchases(partial, remaining, done)
    assert [row.external_id for row in kept] == [str(n) for n in range(1, 9)]
    empty = hold_import_purchases([], remaining, done)
    assert [row.external_id for row in empty] == [str(n) for n in range(1, 9)]
    skipped = hold_import_purchases(
        held,
        remaining,
        {"9", "8"},
    )
    assert [row.external_id for row in skipped] == [str(n) for n in range(1, 8)]


def test_catalog_pick_add_keeps_the_ready_batch() -> None:
    """Adding the one that needs a catalog must not void the other extracted copies."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    review = source.split("def _review_purchases", 1)[1].split("\ndef _render_log", 1)[0]
    picks = review.split("Needs a catalog", 1)[1]
    pick_add = picks.split("if add_pick:", 1)[1]
    assert "_remove_pending_purchases" in pick_add
    assert "_clear_import_drop" not in picks
    assert "Leave out" in picks
    assert "collection-import-pending" in source
    assert "collection-import-done" in source
    assert "hold_import_purchases" in source
    assert "on hold" in review.lower()
    ready = review.split('f"Add these {len(ready)} copies"', 1)[1].split("else:", 1)[0]
    assert "_remove_pending_purchases" in ready
    assert "bill_copy_identity" in ready
    assert "if match.marketplace and match.listing_id:" not in ready


def test_anatomy_form_does_not_rewrite_locked_widgets_every_rerun() -> None:
    """Writing session_state for Sealed/Poster on every run extra-reruns Streamlit."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    anatomy = source.split("def _render_anatomy_form", 1)[1].split("\ndef ", 1)[0]
    assert "_set_widget_if_changed" in anatomy
    assert 'st.session_state[sealed_key] = "No"' not in anatomy
    assert 'st.session_state[poster_key] = "No"' not in anatomy
    grid = source.split("response = AgGrid(", 1)[1].split("key=", 1)[0]
    assert 'update_on=["selectionChanged"]' in grid
    assert "rowClicked" not in grid


def test_collection_page_reloads_identity_before_acquisition() -> None:
    """canonical_artist_display must exist before acquisition reloads."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    block = source.split("reload_modules_if_changed(", 1)[1].split(
        "cache_key=", 1
    )[0]
    assert "_auction_etl_collection_reload_v2" in source
    identity = block.index("discogs_identity")
    fill = block.index("discogs_fill")
    acquisition = block.index("collection_acquisition")
    informal = block.index("informal_lot")
    imported = block.index("collection_import")
    shelf = block.index("collection_shelf")
    assert identity < fill < acquisition < informal < imported < shelf


def test_shelf_update_message_prefers_catalog_over_listing_id() -> None:
    """After save, Next open copy should say the matrix / catalog, not buyee:j…."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    label = source.split("def _shelf_copy_label", 1)[1].split("\ndef ", 1)[0]
    record = source.split("def _record_label", 1)[1].split("\ndef ", 1)[0]
    close = source.split("def _close_shelf_copy", 1)[1].split("\ndef ", 1)[0]
    printed = source.split("def _printed_matrix", 1)[1].split("\ndef ", 1)[0]
    assert "manual_catalog_number" in printed
    assert "_printed_matrix" in label
    assert "_printed_matrix" in close
    assert "shown_catalog" in record
    assert "Catalog / matrix first" in record


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
        "reload_modules_if_changed",
        "Save these bills",
        "Backfill a copy already on the shelf",
        "Pick a copy on the shelf",
        "index=None",
        "matched_ids",
        "This item number is not on the shelf",
        "Fill in the breakdown",
        "Landed is in US dollars",
        "Drop the Buyee invoice PDF",
        "Charge lines only",
        "The record title stays as it is",
        "Drop the Buyee invoice PDF",
        "Yen stays yen",
        "pdf",
        "Click a row",
        "multiRow",
        "Speed fill",
        "apply_common_record_fields",
        "suppressCellFocus",
        "enableClickSelection",
        "AgGrid",
        "Open listing",
        "listing_url_for_copy",
        "link_button",
        "Media type",
        "Laserdisc",
        "Box set",
        "Bulk lot",
        "Formats in this lot",
        "manual_media_type",
        "media_asks_disc_count",
        "Record anatomy",
        "Billing",
        "collection_bill",
        "Save this bill on these copies",
        "Paste the order text, or type shipping and tax",
        "In process or delivered",
        "Delivered",
        "Save this copy",
        "Remove from shelf",
        "Not delivered yet",
        "Save those delivery dates",
        "Use these dates on the selected copies",
        "Also these copies",
        "stamp_lot_dates",
        "purchases_with_lot_paid_on",
        "backfill_lot_paid_on",
        "lot_package_id",
        "align_lot_dates",
        "inherit_lot_dates",
        "closest_unfilled_copy",
        "extracted_delivered_on",
        "_known_delivered_on",
        "_advance_to_closest_open",
        "Item prices stay as they are",
        "Acquisition",
        "Auction, fixed, and OBO",
        "EPs, sleeves, gatefolds, and box sets",
        "Fill same catalogs",
        "fill_same_catalog_identities",
        "reload_modules_if_changed",
        "Look up on Discogs",
        "apply_release_choice",
        "anatomy_values_from_choice",
        "ensure_anatomy_copy",
        "propagate_catalog_identity_to_siblings",
        "ready to add",
        "caption=\"Listing\"",
        "caption=\"Discogs\"",
        "Save this record",
        "Insert only",
        "Pin-up is the insert",
        "Pin-up is the poster",
        "Poster / pin-up",
        "_close_shelf_copy",
        "edition_values_from_form",
        "Record is filled",
        "Filled",
        "sealed_allowed_for_grades",
        "sealed_choice_for_grades",
        "jpg",
        "jpeg",
        "png",
        "Search Discogs",
        "search_user_catalog",
        "shortlist_field",
        "Paid on becomes the order date",
        "No order date on this bill",
        "Paid on {purchase.paid_on.isoformat()} from this bill.",
        "Item number",
        "Add this page to the bill",
        "2 items totals",
        "every album in that package",
        "Share of combined order",
        "Extract bill from screenshots",
        "accept_multiple_files",
        "Next unfilled",
        "Screenshot removed",
        "harvest_screenshot_bills",
        "collection-import-pages",
        "collection-import-upload-seq",
        "parse_purchase_pages",
        "several eBay orders",
        "listing_title_is_chrome",
        "listing_title_is_ocr_junk",
        "listing_catalog_is_structured",
        "owned_copy_shows_on_shelf",
        "ocr_promo_item_price",
        "buyee_package_display_lines",
        "buyee_package_landed_extras",
        "bill_copy_identity",
    )
    missing = [value for value in required if value not in source]
    assert not missing, ", ".join(missing)
    incoming = source.split("def _render_incoming_lot", 1)[1].split(
        "def _batch_editor", 1
    )[0]
    assert "stamp_lot_dates" in incoming
    assert "explicit=adjusting" in incoming
    assert "if len(ready) < 2:" not in incoming
    assert 'st.date_input(\n        "Order date"' in incoming
    assert "Not delivered yet" in incoming
    assert "st.form(" not in incoming
    assert "st.dialog" not in source
    assert "LinkColumn" not in source
    assert 'selection_mode="single-row"' not in source
    assert "page_limit" not in source
