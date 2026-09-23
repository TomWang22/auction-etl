"""Catalog tokens, dead-on classification, and Discogs release mapping."""

from __future__ import annotations

import json
from pathlib import Path

from auction_etl.services.discogs_identity import (
    artist_overlaps,
    catalog_token,
    classify_search_hits,
    fold_catalog,
    map_release_payload,
    parse_search_hits,
    prefers_japan,
    unique_hit_can_auto_fill,
)


ROOT = Path(__file__).resolve().parents[1]
RELEASE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "discogs" / "release_10320765.json"
)


SOLL_HIT = {
    "id": 10320765,
    "type": "release",
    "title": "山口百恵* - 15才",
    "catno": "SOLL-114",
    "year": "1974",
    "country": "Japan",
    "format": ["Vinyl", "LP", "Album", "Stereo"],
    "label": ["CBS/Sony", "Golden New Year '75"],
    "thumb": "https://example.invalid/thumb.jpg",
    "uri": "/release/10320765",
}

SECOND_VINYL_HIT = {
    **SOLL_HIT,
    "id": 99999999,
    "title": "Other Artist - Same Catno",
    "country": "Japan",
}


def test_fold_catalog_equates_hyphen_space_and_plain() -> None:
    assert fold_catalog("SOLL114") == "SOLL114"
    assert fold_catalog("SOLL-114") == "SOLL114"
    assert fold_catalog("soll 114") == "SOLL114"


def test_ebay_title_yields_soll114_token() -> None:
    token = catalog_token(
        catalog_number=None,
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
    )
    assert token is not None
    assert fold_catalog(token) == "SOLL114"


def test_catalog_field_wins_over_title() -> None:
    token = catalog_token(
        catalog_number="SOLL-114",
        title="Random text without a useful token",
    )
    assert fold_catalog(token) == "SOLL114"


def test_missing_token_is_none() -> None:
    assert catalog_token(title="Pretty vinyl lot no catalog") is None


def test_artist_overlap_latin_and_japanese() -> None:
    names = ["Momoe Yamaguchi", "山口百恵"]
    assert artist_overlaps(
        listing_artist=None,
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        discogs_names=names,
    )
    assert artist_overlaps(
        listing_artist="山口百恵",
        listing_title="15才 CBS/SONY SOLL-114",
        discogs_names=names,
    )
    assert not artist_overlaps(
        listing_artist="Teresa Teng",
        listing_title="Island of Teresa",
        discogs_names=names,
    )


def test_prefers_japan_for_jp_titles() -> None:
    assert prefers_japan(
        listing_title="山口百恵 15才 LP",
        listing_artist=None,
    )
    assert prefers_japan(
        listing_title="Momoe Yamaguchi Japan pressing",
        listing_artist=None,
    )
    assert not prefers_japan(
        listing_title="Beatles UK stereo",
        listing_artist="The Beatles",
    )


def test_unique_catno_vinyl_hit_is_dead_on() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765
    assert result.hits[0].catno == "SOLL-114"


def test_two_vinyl_hits_stay_needs_review() -> None:
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT, SECOND_VINYL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "needs_review"
    assert result.chosen is None
    assert len(result.hits) == 2


def test_missing_token_is_unmatched() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="Pretty jacket photo lot",
        artist=None,
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi"],
    )
    assert result.status == "unmatched"
    assert result.chosen is None


def test_unique_japanese_search_title_promotes_with_release_artists() -> None:
    result = classify_search_hits(
        catalog_number="SOLL114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist=None,
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
    )
    assert result.status == "needs_review"
    assert result.reason == "artist_mismatch"
    assert unique_hit_can_auto_fill(
        result,
        listing_artist=None,
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        release_artist_names=("Momoe Yamaguchi", "山口百恵"),
    )
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    draft = map_release_payload(payload)

    assert draft.discogs_release_id == 10320765
    assert draft.discogs_master_id == 1918614
    assert draft.label_name == "CBS/Sony"
    assert draft.discogs_label_id == 33078
    assert draft.catalog_number == "SOLL-114"
    assert draft.country == "Japan"
    assert draft.region == "Japan"
    assert draft.release_year == 1974
    assert draft.media_type == "LP"
    assert draft.disc_count == 1
    assert draft.generation == "UNKNOWN"
    assert draft.requires_label_choice is False
    assert "SOLL-114A2" in draft.matrix_number
    assert "SOLL-114B3" in draft.matrix_number
    assert draft.component_expectations == ()
    assert "lyric sheet" in (draft.notes_hint or "")


def test_two_label_entities_require_explicit_choice() -> None:
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    payload["labels"] = [
        {
            "id": 33078,
            "name": "CBS/Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
        {
            "id": 1,
            "name": "Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
    ]
    draft = map_release_payload(payload)
    assert draft.requires_label_choice is True
    assert len(draft.labels) == 2


def test_promo_description_sets_generation_not_first_press() -> None:
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    payload["formats"] = [
        {
            "name": "Vinyl",
            "qty": "1",
            "descriptions": ["LP", "Promo"],
        }
    ]
    draft = map_release_payload(payload)
    assert draft.generation == "PROMO"
    assert draft.is_first_press is False
