"""Yahoo and Japanese listing text map onto Goldmine-style grades."""

from __future__ import annotations

from auction_etl.classifiers.condition import classify_condition, is_canonical_grade


def test_yahoo_phrases_map_to_grades() -> None:
    assert classify_condition("A little damaged/dirty").media_grade == "VG"
    assert classify_condition("No obvious damages/dirt").media_grade == "VG+"
    assert classify_condition("Unused").media_grade == "NM"
    assert classify_condition("Damaged/dirty").media_grade == "G"
    assert classify_condition("In bad condition overall").media_grade == "F"


def test_japanese_title_grades() -> None:
    assert classify_condition("山口百恵 LP 美品 帯付き").media_grade == "EX"
    assert classify_condition("未開封 新品").media_grade == "M"
    assert classify_condition("ジャンク まとめ CD").media_grade == "P"


def test_seller_sheet_keeps_minus_grades() -> None:
    report = classify_condition(
        "Sleeve Grading: E-\nObi Grading: NONE\nRecord Grading: E-/"
    )
    assert report.cover_grade == "E-"
    assert report.media_grade == "E-"
    vin = classify_condition(
        "Jacket: EX- some scuffs\nRecord condition: EX minor scuffs"
    )
    assert vin.cover_grade == "EX-"
    assert vin.media_grade == "EX"
    assert classify_condition("盤質：VG++").media_grade == "VG++"
    assert is_canonical_grade("E-")
    assert is_canonical_grade("EX-")
    cd = classify_condition(
        "○ケース：C 少し傷み /帯無し\n"
        "○ディスク：B 概ね良好\n"
        "レコードグレーディング\nEX+\t美品\nVG++\t概ね良好\n"
        "CDグレーディング\nS 新品 A 美品 B 概ね良好 C 少し傷み D 全体的傷み"
    )
    assert cd.cover_grade == "C"
    assert cd.media_grade == "B"
    assert is_canonical_grade("B")
    assert is_canonical_grade("S")


def test_goldmine_token_in_title() -> None:
    assert classify_condition("TERESA TENG LP VG+ OBI").media_grade == "VG+"
    assert is_canonical_grade("VG+")
    assert not is_canonical_grade("A little damaged/dirty")
