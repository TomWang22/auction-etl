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
