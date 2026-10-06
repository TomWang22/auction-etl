"""Operator surfaces keep the tracked collection, not seller inventory."""

from __future__ import annotations

from pathlib import Path


REVIEW = Path(__file__).resolve().parents[1] / "app" / "collector_review.py"
COMPLETENESS = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "pages"
    / "10_Listing_Completeness_Review.py"
)
FILL = (
    Path(__file__).resolve().parents[1]
    / "auction_etl"
    / "services"
    / "discogs_fill.py"
)


def test_review_and_completeness_scope_to_tracked_artists() -> None:
    review = REVIEW.read_text(encoding="utf-8")
    completeness = COMPLETENESS.read_text(encoding="utf-8")
    fill = FILL.read_text(encoding="utf-8")
    assert "listing_belongs_to_tracked_artists" in review
    assert "enabled_tracked_artist_names" in review
    assert "tracked_listing_scope" in review
    assert "account_id=page_account_context.account_id" in completeness
    assert "_unfill_untracked_auto_identities" in fill
    assert "_rows_for_tracked_artists" in fill
