"""Collector Review keeps magazines off the main record scene."""

from __future__ import annotations

from pathlib import Path


REVIEW = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "collector_review.py"
)


def test_main_collection_has_scene_filter_defaulting_off_magazines() -> None:
    source = REVIEW.read_text(encoding="utf-8")
    assert "Collection scene" in source
    assert "SCENE_OPTIONS" in source
    assert "media_matches_scene" in source
    assert '"MAGAZINE"' in source
    assert "Main records shows LP, CD, cassette" in source
    assert "title_classification" in source
    assert "MEDIA_GROUP_OPTIONS" in source
    assert "listing_belongs_to_tracked_artists" in source
    assert "enabled_tracked_artist_names" in source
    assert "tracked_listing_scope" in source
    assert "media_matches_group" in source
    assert "classify_media_details" in source
    assert "catalog_token" in source


def test_title_classification_is_importable_without_collector_review() -> None:
    from app.collector_review_support import title_classification

    media, catalog, bulk = title_classification(
        "Teresa Teng LP Polydor 2427 333"
    )
    assert media == "LP"
    assert catalog == "2427 333"
    assert bulk is False


def test_media_helpers_expose_job_lot() -> None:
    from app.collector_review_support import _media_helpers

    classify_media_details, is_job_lot = _media_helpers()
    assert classify_media_details("4 CD Lot Teresa Teng").bulk_lot is True
    assert is_job_lot("4 CD Lot Teresa Teng") is True
    assert is_job_lot("テレサ・テン CD 2枚組 TACL-2395") is False


def test_media_helpers_reloads_stale_streamlit_module() -> None:
    import importlib

    import auction_etl.classifiers.media as module
    from app.collector_review_support import _media_helpers

    saved = module.is_job_lot
    del module.is_job_lot
    try:
        classify_media_details, is_job_lot = _media_helpers()
        assert classify_media_details is not None
        assert is_job_lot("The Best of Teresa Teng 4 CD Lot") is True
    finally:
        module.is_job_lot = saved
        importlib.reload(module)
