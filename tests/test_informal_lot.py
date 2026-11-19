"""Informal HK seller-list lot intake: parser, allocation, UI guards."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

from auction_etl.services.collection_import import (
    anatomy_values_from_lot_line,
    allocate_lot_payments,
    hk_condition_to_grade,
    looks_like_informal_seller_list,
    parse_informal_seller_list,
    purchase_from_lot_line,
)
from auction_etl.services.informal_lot import LotDraftLine, LotDraftPackage

COLLECTION_PAGE = Path(__file__).resolve().parents[1] / "app/pages/17_My_Collection.py"
ANALYTICS_PAGE = (
    Path(__file__).resolve().parents[1] / "app/pages/2_Pressing_Analytics.py"
)

SAMPLE_LIST = """
O2 蔓莉蔓莉我愛你 9成新 $590
O25 忘不了初戀的情人 近95成新 $470
O36 轟動閩南語歌曲 85成新 碟有擦痕 $260
O49 迷人歌聲處處聞 近95成新 ¥$180
L9 彩雲飛 近95成新 $180
L10 暢銷歌曲第五集 9成新 碟有輕微污跡 $650
L11 麗風之星紀念金唱片 9成新 $210
L43 水漣漪 9成新 $260
L44 近水樓台 9成新 $290
LP5874 寶麗星5號 近95成新 帶歌詞 $90
LP6077 寶麗星3號 近95成新 $120
LP6337 寶麗星7號 近95成新 $120
LP6374 紅歌星處處聞 9成新 $140
運費$1476
好啦，$4300+10%=$4730
"""


def test_parse_informal_seller_list_sample() -> None:
    package = parse_informal_seller_list(SAMPLE_LIST, currency="HKD", shop="HK seller")
    assert looks_like_informal_seller_list(SAMPLE_LIST)
    assert len(package.lines) == 13
    assert package.shipping == Decimal("1476")
    assert package.merchandise == Decimal("4300")
    assert package.fee_amount == Decimal("430.00")
    assert package.package_total == Decimal("4730")
    assert package.currency == "HKD"
    first = package.lines[0]
    assert first.seller_sku == "O2"
    assert first.title == "蔓莉蔓莉我愛你"
    assert first.list_amount == Decimal("590")
    assert first.condition_hint == "9成新"
    assert first.condition_media == "VG+"
    assert sum((line.list_amount or 0) for line in package.lines) == Decimal("3560")
    assert sum((line.paid_amount or 0) for line in package.lines) == Decimal("4300.00")
    assert "List 590 HKD" in first.billing_note
    assert "Allocated" in first.billing_note
    assert "Shipping 1476 HKD (package, fixed)" in first.billing_note
    assert "Package fee 430.00 HKD" in first.billing_note
    assert all("(package, fixed)" in (line.billing_note or "") for line in package.lines)


def test_hk_condition_token_to_grade() -> None:
    assert hk_condition_to_grade("9成新") == "VG+"
    assert hk_condition_to_grade("近95成新") == "EX+"
    assert hk_condition_to_grade("85成新") == "VG"
    assert hk_condition_to_grade("全新") == "NM"
    assert hk_condition_to_grade("") is None


def test_allocate_lot_payments_weights_by_list_price() -> None:
    package = LotDraftPackage(
        currency="HKD",
        merchandise=Decimal("100"),
        shipping=Decimal("10"),
        lines=[
            LotDraftLine(line_id="a", list_amount=Decimal("60")),
            LotDraftLine(line_id="b", list_amount=Decimal("40")),
        ],
    )
    allocated = allocate_lot_payments(package)
    assert [line.paid_amount for line in allocated.lines] == [
        Decimal("60.00"),
        Decimal("40.00"),
    ]
    assert sum(line.paid_amount or 0 for line in allocated.lines) == Decimal("100.00")
    assert allocated.lines[0].list_amount == Decimal("60")


def test_purchase_from_lot_line_keeps_allocated_paid() -> None:
    package = parse_informal_seller_list(
        "O2 蔓莉蔓莉我愛你 9成新 $590\n運費$100\n好啦，$500+10%=$550\n",
        currency="HKD",
        shop="Chat seller",
    )
    purchase = purchase_from_lot_line(package, package.lines[0])
    assert purchase.source == "Chat seller"
    assert purchase.paid_currency == "HKD"
    assert purchase.paid_amount == Decimal("500.00")
    assert purchase.catalog_number == "O2"
    assert "List 590 HKD" in purchase.billing_note
    anatomy = anatomy_values_from_lot_line(package.lines[0])
    assert anatomy["manual_condition_media"] == "VG+"
    assert anatomy["manual_catalog_number"] == "O2"


def test_log_tab_exposes_lot_mode_and_confirm_path() -> None:
    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    assert "Lot / seller list" in source
    assert "_render_lot_wizard" in source
    assert "_confirm_informal_lot" in source
    assert "Confirm lot" in source
    assert "parse_informal_seller_list" in source
    assert "_stamp_manual_usd" in source
    # LotDraftLine must come from informal_lot after that module reloads.
    assert "LotDraftLine = informal_lot.LotDraftLine" in source
    assert "informal_lot," in source.split("reload_modules_if_changed(", 1)[1].split(
        "collection_import,", 1
    )[0]
    confirm = source.split("def _confirm_informal_lot", 1)[1].split(
        "\ndef _apply_discogs_to_lot_line", 1
    )[0]
    assert "save_owned_copy" in confirm
    assert "save_copy_anatomy" in confirm
    assert "save_package_bill" in confirm
    assert "anatomy_values_from_lot_line" in confirm
    assert "purchase_from_lot_line" in confirm
    assert "_stamp_manual_usd" in confirm
    one_copy = source.split("def _render_one_copy_log", 1)[1].split(
        "\ndef _render_log", 1
    )[0]
    assert "_stamp_manual_usd" in one_copy
    assert "Paid (original currency)" in one_copy
    assert "USD conversion preview" in one_copy
    wizard = source.split("def _render_lot_wizard", 1)[1].split(
        "\ndef _render_one_copy_log", 1
    )[0]
    assert "Shipping (fixed)" in wizard
    assert "USD conversion" in wizard or "USD rate" in wizard or "stamps a USD" in wizard
    assert "_render_lot_add_panel" in wizard
    assert "collection-lot-confirm" in wizard
    assert '"TWD"' in source or "'TWD'" in source
    assert '"CNY"' in source or "'CNY'" in source
    assert '"SGD"' in source or "'SGD'" in source
    panel = source.split("def _render_lot_add_panel", 1)[1].split(
        "\ndef _render_lot_line_roster", 1
    )[0]
    assert "Add to lot" in panel
    assert "Update in lot" in panel
    assert "not HKD-only" in panel
    form = source.split("def _collect_lot_form_line", 1)[1].split(
        "\ndef _render_lot_add_panel", 1
    )[0]
    assert "Look up on Discogs" in form
    assert "Pressing identification" in form
    assert "Condition and assessment" in form
    assert "Edition and completeness" in form
    assert "Original / sticker" in form
    assert 'key="collection-lot-currency"' in form
    assert "_usd_preview" in form
    assert "Use this" in form
    assert "ensure_anatomy_copy" not in form


def test_pressing_analytics_colors_bought_vs_market() -> None:
    source = ANALYTICS_PAGE.read_text(encoding="utf-8")
    assert 'dataframe["ownership"]' in source
    history = source.split("def render_price_history", 1)[1].split(
        "\ndef render_price_distribution", 1
    )[0]
    assert 'title="Ownership"' in history
    assert '"Bought"' in history
    assert '"Market"' in history
    distribution = source.split("def render_price_distribution", 1)[1].split(
        "\ndef render_monthly_activity", 1
    )[0]
    assert "ownership:N" in distribution


def test_informal_lot_module_exports_are_stable() -> None:
    assert callable(parse_informal_seller_list)
    assert callable(allocate_lot_payments)
    assert "hk_condition_to_grade" in inspect.getsource(
        __import__("auction_etl.services.informal_lot", fromlist=["hk_condition_to_grade"])
    )


def test_load_owned_batches_cover_lookup() -> None:
    """Owned-copy covers must not scan every sale once per row."""

    source = COLLECTION_PAGE.read_text(encoding="utf-8")
    owned = source.split("def load_owned", 1)[1].split("def load_pressings", 1)[0]
    assert "effective_catalog_number = ANY(:catalogs)" in owned
    assert "LIMIT 1\n        ) cover ON TRUE" not in owned


def test_note_with_printed_usd_rate_supports_hkd() -> None:
    from auction_etl.services.collection_import import note_with_printed_usd_rate

    note = note_with_printed_usd_rate(
        "List 590 HKD",
        usd=Decimal("75.52"),
        foreign=Decimal("590"),
        currency="HKD",
    )
    assert "USD rate 75.52 for 590 HKD" in note
    # Existing Buyee call shape still works.
    yen_note = note_with_printed_usd_rate(
        "Item price 1000",
        usd=Decimal("6.80"),
        yen=Decimal("1000"),
    )
    assert "USD rate 6.80 for 1000 JPY" in yen_note
