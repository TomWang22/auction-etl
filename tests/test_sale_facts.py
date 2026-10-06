"""Sale type, seller, and opened fields survive warehouse refresh."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.collector_review_support import (
    derive_sale_type,
    display_listing_catalog,
    display_matrix_catalog,
)
from auction_etl.services.warehouse import (
    _conflict_updates,
    _row_values,
    _sale_format,
)


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "auction_etl" / "services" / "warehouse.py"
REVIEW_SUPPORT = ROOT / "app" / "collector_review_support.py"
REVIEW = ROOT / "app" / "collector_review.py"
GRIPSWEAT = ROOT / "auction_etl" / "reporting" / "main_review_integration.py"


def test_card_sync_does_not_blank_start_price() -> None:
    source = WAREHOUSE.read_text(encoding="utf-8")
    assert '"start_price": None' not in source
    assert "COALESCE(EXCLUDED.start_price, warehouse.auction.start_price)" in source
    assert "EXCLUDED.final_price" in source
    assert "warehouse.auction.final_price" in source
    assert "EXCLUDED.gross_price" in source
    assert "COALESCE(EXCLUDED.tax_amount, warehouse.auction.tax_amount)" in source
    assert "FIXED_PRICE_OBO" in source
    assert "promote_classification_facts(" in source
    assert "classify_condition" in source


def test_refresh_sync_keeps_named_buyee_sellers() -> None:
    updates = _conflict_updates(
        {
            "marketplace": "buyee",
            "listing_id": "p1",
            "seller": "B6uqp3pG25ZL1T8XLFwT2Eftsd",
            "title": "LP",
            "start_price": None,
            "auction_format": "AUCTION",
        }
    )
    seller_sql = str(updates["seller"])
    assert "EXCLUDED.seller ~ '^[A-Za-z0-9]{16,}$'" in seller_sql
    assert "warehouse.auction.seller" in seller_sql


def test_row_values_copy_staging_sale_type() -> None:
    listing = SimpleNamespace(
        marketplace="ebay",
        listing_id="123",
        auction_url="https://www.ebay.com/itm/123",
        seller="facerecords",
        title="Teresa Teng LP",
        subtitle=None,
        description=None,
        format="LP",
        disc_count=1,
        edition=None,
        catalog_number=None,
        label=None,
        image_url=None,
        media_condition=None,
        sleeve_condition=None,
        bid_count=3,
        sale_type="AUCTION",
        ended_at=None,
        shipping_price=None,
        payload={},
        final_price=Decimal("12.00"),
        currency="USD",
        price_text="US $12.00",
        tax_amount=None,
        sold_text=None,
    )
    values = _row_values(listing)
    assert values["auction_format"] == "AUCTION"
    assert values["start_price"] is None


def test_best_offer_ask_is_start_price_not_hammer() -> None:
    listing = SimpleNamespace(
        marketplace="ebay",
        listing_id="377493856081",
        auction_url="https://www.ebay.com/itm/377493856081",
        seller="hunts4stuff",
        title="Teresa Teng With Love From LP",
        subtitle=None,
        description=None,
        format="LP",
        disc_count=1,
        edition=None,
        catalog_number=None,
        label=None,
        image_url=None,
        media_condition=None,
        sleeve_condition=None,
        bid_count=0,
        sale_type="FIXED_PRICE_OBO",
        ended_at=None,
        shipping_price=None,
        payload={"start_price": "$50.00 or Best Offer"},
        final_price=None,
        currency="USD",
        price_text="$50.00 or Best Offer",
        tax_amount=None,
        sold_text=None,
    )
    values = _row_values(listing)
    assert values["auction_format"] == "FIXED_PRICE_OBO"
    assert values["start_price"] == Decimal("50.00")
    assert values["final_price"] is None
    assert values["tax_amount"] is None


def test_ebay_usd_hammer_gets_us_sales_tax() -> None:
    listing = SimpleNamespace(
        marketplace="ebay",
        listing_id="326240051289",
        auction_url="https://www.ebay.com/itm/326240051289",
        seller="ryanb714",
        title="TERESA TENG 1976 LP HONG KONG RARE LFLP 486",
        subtitle=None,
        description=None,
        format="LP",
        disc_count=1,
        edition=None,
        catalog_number="LFLP-486",
        label=None,
        image_url=None,
        media_condition=None,
        sleeve_condition=None,
        bid_count=0,
        sale_type="FIXED_PRICE_OBO",
        ended_at=None,
        shipping_price=None,
        payload={"start_price": "$100.00 or Best Offer"},
        final_price=Decimal("80.00"),
        currency="USD",
        price_text="$80.00",
        tax_amount=None,
        sold_text=None,
    )
    values = _row_values(listing)
    assert values["final_price"] == Decimal("80.00")
    assert values["tax_rate"] == Decimal("0.0625")
    assert values["tax_amount"] == Decimal("5.00")
    assert values["gross_price"] == Decimal("85.00")
    assert values["price_includes_tax"] is False


def test_stored_sale_format_beats_missing_bids() -> None:
    assert derive_sale_type(
        manual_value=None,
        title="Anita Mui LP",
        starting_price=None,
        bid_count=0,
        buyout_price=None,
        stored_format="AUCTION",
    ) == "AUCTION"
    assert derive_sale_type(
        manual_value=None,
        title="Pretty jacket lot",
        starting_price=None,
        bid_count=0,
        buyout_price=None,
        stored_format=None,
    ) == "UNKNOWN"


def test_sale_format_normalizes_fixed_price() -> None:
    assert _sale_format("fixed price") == "FIXED_PRICE"


def test_gripsweat_archive_rows_are_auctions() -> None:
    source = GRIPSWEAT.read_text(encoding="utf-8")
    assert '"AUCTION"' in source
    assert '"ARCHIVE"' not in source
    assert '"opening_at": sale.get("first_seen_at")' in source


def test_review_uses_stored_auction_format() -> None:
    source = REVIEW.read_text(encoding="utf-8")
    assert 'stored_format=row.get("auction_format")' in source
    assert "_source_first_seen_at" in source
    assert "stored_format" in REVIEW_SUPPORT.read_text(encoding="utf-8")


def test_review_support_reloads_stale_year_helpers() -> None:
    source = REVIEW_SUPPORT.read_text(encoding="utf-8")
    assert "from auction_etl.services.discogs_identity import (" not in source
    assert "importlib.reload" in source
    from app.collector_review_support import extract_release_year

    assert extract_release_year("日本盤 1975年") == 1975
    assert "canonical_artist_key" in source


def test_pressing_token_ignores_price_and_title_fragments() -> None:
    from app.collector_review_support import (
        derive_pressing_token,
        extract_release_year,
    )

    assert derive_pressing_token(
        override=None,
        catalog_number="PRICE-880",
        title="LP,山口百恵 COSMOS 宇宙 ポスター付き",
    ) == ""
    assert display_listing_catalog(
        stored="SEP-23",
        title="鄧麗君* - 勢不兩立 (LP) (1980) [Used Vinyl]",
    ) == ""
    assert display_matrix_catalog(
        stored_catalog="SOLL-114",
        stored_matrix="SOLL-114A2 / SOLL-114B3",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
    ) == "SOLL-114 · SOLL-114A2 / SOLL-114B3"
    assert display_listing_catalog(
        stored="SEP-23",
        title="Teresa Teng - テレサ・テン・ベスト20 / VINYL / VG+ / 2xLP",
    ) == ""
    assert display_listing_catalog(
        stored="TASL-7920",
        title="テレサ・テン /つぐない／何日君再來～日本語バージョン/TASL-7920",
    ) == "TASL-7920"
    assert "display_listing_catalog" in REVIEW.read_text(encoding="utf-8")
    assert derive_pressing_token(
        override=None,
        catalog_number="SEP-23",
        title="鄧麗君* - 勢不兩立 (LP) (1980) [Used Vinyl]",
    ) == ""
    assert derive_pressing_token(
        override=None,
        catalog_number="SEP-21",
        title="The Best of Teresa Teng 1 3 4 CD Lot 1992 Polygram",
    ) == ""
    assert derive_pressing_token(
        override=None,
        catalog_number=None,
        title="Gripsweat Anita Mui Come On Rock Cantopop 1988 Hong Kong",
    ) == ""
    assert derive_pressing_token(
        override=None,
        catalog_number="UPJY-9092",
        title="美盤 LP テレサ・テン 鄧麗君 夜の乗客 UPJY-9092",
    ) == "UPJY9092"
    assert extract_release_year(
        "美盤 LP テレサ・テン 夜の乗客 1975 2020"
    ) == 1975
    assert extract_release_year(
        "LP テレサ・テン ベスト・アルバム UPJY-9078 2019年復刻盤"
    ) == 2019
    from app.collector_review_support import display_release_year

    assert display_release_year(
        pressing_year=2020,
        title="美盤 LP テレサ・テン 夜の乗客 帯付 日本盤 1975年",
    ) == 1975
    assert display_release_year(
        pressing_year=2020,
        title="美盤 LP テレサ・テン 夜の乗客 UPJY-9092 帯付 日本盤 1975年",
    ) == 2020
    assert display_listing_catalog(
        stored="UPJY-9092",
        title="美盤 LP テレサ・テン 夜の乗客 帯付 日本盤 1975年",
    ) == ""
    assert display_release_year(
        pressing_year=2026,
        title="Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
    ) is None
    assert display_release_year(
        pressing_year=2018,
        title="Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
    ) == 2018
