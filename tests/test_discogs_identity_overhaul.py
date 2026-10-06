"""Contracts for Discogs identity fill, ingest copy, and collector display."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "auction_etl" / "services" / "discogs_identity.py"
FILL = ROOT / "auction_etl" / "services" / "discogs_fill.py"
CLIENT = ROOT / "auction_etl" / "services" / "discogs_client.py"
VIEWS = ROOT / "auction_etl" / "database" / "collector_views.py"
WAREHOUSE = ROOT / "auction_etl" / "services" / "warehouse.py"
MODEL = ROOT / "auction_etl" / "models" / "warehouse.py"
REFRESH = ROOT / "scripts" / "run_latest_auction_refresh.py"
INGEST = ROOT / "app" / "pages" / "15_Ingest_New_Auctions.py"
REVIEW = ROOT / "app" / "collector_review.py"
SECRETS = ROOT / ".streamlit" / "secrets.toml.example"
REVISION = ROOT / "alembic" / "versions" / "b7e4c1a9d352_discogs_identity.py"


def test_warehouse_promotes_listing_image_url() -> None:
    model = MODEL.read_text(encoding="utf-8")
    sync = WAREHOUSE.read_text(encoding="utf-8")
    assert "image_url:" in model
    assert '"image_url":' in sync
    assert "listing.image_url" in sync


def test_collector_views_prefer_pressing_identity() -> None:
    views = VIEWS.read_text(encoding="utf-8")
    assert "effective_label" in views
    assert "effective_release_year" in views
    assert "listing.year" in views
    assert "pressing.release_year" in views
    assert "staging.listing listing" in views
    assert "NULLIF(pressing.catalog_number, '')" in views
    assert "effective_matrix_number" in views
    assert "NULLIF(pressing.matrix_number, '')" in views
    assert "warehouse.auction_pressing_assignment" in views
    assert "warehouse.label canonical_label" in views
    assert "a.identity_status" in views


def test_identity_migration_follows_label_head() -> None:
    source = REVISION.read_text(encoding="utf-8")
    assert 'revision = "b7e4c1a9d352"' in source
    assert 'down_revision = "a1c3e8f7b240"' in source


def test_refresh_runs_identity_pass_after_warehouse() -> None:
    source = REFRESH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "run_discogs_identity_pass" in names
    assert source.count("run_discogs_identity_pass(") == 2
    assert (
        "fill_unmatched_identities(\n            warehouse_engine,\n            retune=False,"
        in source
        or "fill_unmatched_identities(warehouse_engine, retune=False)" in source
    )
    assert "Matching new listings" in source
    gripsweat_done = source.index('"Gripsweat",\n            "done"')
    ebay = source.index("Safely synchronize eBay without pruning")
    buyee = source.index("Safely synchronize Buyee without pruning")
    identity = source.index("run_discogs_identity_pass(", gripsweat_done)
    assert identity > gripsweat_done
    assert identity > ebay
    assert identity > buyee


def test_ingest_and_review_have_no_identity_modal() -> None:
    ingest = INGEST.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    assert "st.modal(" not in ingest
    assert "st.dialog(" not in ingest
    assert "st.modal(" not in review
    assert "identity_fill" in ingest
    assert "Needs review" in review
    assert "Use this" in review
    assert "discogs_format_label" in review
    assert "Different format than this listing" in review
    assert "if compatible and st.button(" not in review
    assert "on_click=_commit_discogs_choice" in review
    assert "research_listing_identity" in review
    assert "Searching Discogs for this sale" in review
    assert "Search Discogs" in review
    assert "Search catalog" in review
    assert "search_user_catalog" in review
    catalog_box = review.split("def _render_catalog_search", 1)[1].split(
        "def _commit_discogs_choice", 1
    )[0]
    assert "_render_choice_cards" not in catalog_box
    identity_body = review.split("def render_identity_shortlist", 1)[1].split(
        "def render_listing_editor", 1
    )[0]
    assert 'key_prefix="catalog-choose"' in identity_body
    assert "listing_identity_catalog" in review
    assert "EBAY_US_TAX_RATE" in review
    assert "clean_text(selected.get(\"catalog_number\"))" in review
    assert "clean_text(selected.get('release_year_display'))" in review
    assert "album_name_in_listing" in review
    assert "manual_purchased" in review
    assert "load_records.clear()" in review
    assert "visible_shortlist_hits" in review
    assert "No listing photo stored." in review
    assert "identity_mix_caption" in review


def test_secrets_example_documents_discogs_without_real_keys() -> None:
    example = SECRETS.read_text(encoding="utf-8")
    assert "[discogs]" in example
    assert "DISCOGS_CONSUMER_KEY" in example
    assert "DISCOGS_CONSUMER_SECRET" in example
    assert "VinylPriceAnalyzer" not in example


def test_discogs_client_does_not_log_authorization() -> None:
    client = CLIENT.read_text(encoding="utf-8")
    fill = FILL.read_text(encoding="utf-8")
    identity = IDENTITY.read_text(encoding="utf-8")
    for source in (client, fill, identity):
        assert "logger.info" not in source or "Authorization" not in source
        assert "print(" not in source
    assert 'logger.info(\n        "Discogs identity fill' in REFRESH.read_text(
        encoding="utf-8"
    )
    assert "Authorization" not in REFRESH.read_text(encoding="utf-8")


def test_fill_does_not_write_component_expectations() -> None:
    fill = FILL.read_text(encoding="utf-8")
    assert "pressing_component_expectation" not in fill
    assert "component_expectations=()" in IDENTITY.read_text(encoding="utf-8")


def test_fill_searches_artist_format_and_title() -> None:
    fill = FILL.read_text(encoding="utf-8")
    identity = IDENTITY.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")
    assert "artist=artist" in fill or 'artist=params.get("artist")' in fill
    assert "format_name=format_name" in fill
    assert "query=query" in fill or 'query=params.get("query")' in fill
    assert "require_catalog_token" in fill
    assert "require_catalog_token" in identity
    assert "_clear_currency_labels" in fill
    assert "_reset_unmatched_for_retune" in fill
    assert "_clear_junk_catalogs" in fill
    assert "_promote_unmatched_shortlists" in fill
    assert "_promote_cover_matches" in fill
    assert "backfill_images_from_payload" in fill
    assert 'source="discogs"' in fill
    assert "draft_for_operator_choice" in fill
    assert "This release has more than one label" not in fill
    assert "if retune:" in fill
    assert "catno" in client
    assert "artist" in client
    assert "format" in client


def test_known_labels_do_not_treat_yen_currency_as_a_label() -> None:
    labels = (
        ROOT / "auction_etl" / "classifiers" / "labels.py"
    ).read_text(encoding="utf-8")
    assert '"Yen Records"' in labels
    assert '"Yen",' not in labels


def test_cli_identity_command_is_registered() -> None:
    main = (ROOT / "auction_etl" / "cli" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "identity_app" in main
    assert 'name="identity"' in main
