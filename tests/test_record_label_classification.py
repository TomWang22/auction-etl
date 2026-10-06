"""Record-label classification from listing text."""

from __future__ import annotations

from auction_etl.classifiers.labels import extract_record_label


def test_explicit_label_field_wins() -> None:
    text = "Title here\nRecord label: Pony Canyon\nCatalog: 07TR-1115"
    assert extract_record_label(text) == "Pony Canyon"


def test_known_label_token_in_title() -> None:
    title = (
        "TERESA TENG TOKINO NAGARENI MIWO MAKASE "
        "TAURUS 07TR1115 EP"
    )
    assert extract_record_label(title) == "Taurus"


def test_longer_label_wins_over_shorter_token() -> None:
    assert extract_record_label(
        "山口百恵 PONY CANYON 7inch"
    ) == "Pony Canyon"


def test_label_colon_japanese() -> None:
    assert extract_record_label("レーベル：キャニオン") == "キャニオン"


def test_yen_currency_is_not_a_record_label() -> None:
    assert extract_record_label("テレサ・テン LP 1000 Yen") is None
    assert extract_record_label("Buyee 500Yen shipping") is None


def test_yen_records_token_still_matches() -> None:
    assert extract_record_label("YMO Technopolis Yen Records") == "Yen Records"


def test_title_ban_label_is_artist_agnostic() -> None:
    assert extract_record_label(
        "台湾盤 KUOPIN盤 テレサ・テン 「鄧麗君 心にのこる夜の唄」 KP-8142"
    ) == "Kuopin"
    assert extract_record_label("Teresa Teng Best Vol. 4 Vinyl Stereo Sound") == "Stereo Sound"
    assert extract_record_label(
        "TERESA TENG Taiwan space record vol 11 vinyl lp"
    ) == "Space Record"
    assert extract_record_label("台湾盤 鄧麗君 LP") is None
