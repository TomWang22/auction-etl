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
    assert "NULLIF(pressing.catalog_number, '')" in views
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
    assert "run_discogs_identity_pass(" in source
    ebay = source.index("Safely synchronize eBay without pruning")
    buyee = source.index("Safely synchronize Buyee without pruning")
    assert source.index("run_discogs_identity_pass(", ebay) > ebay
    assert source.index("run_discogs_identity_pass(", buyee) > buyee


def test_ingest_and_review_have_no_identity_modal() -> None:
    ingest = INGEST.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    assert "st.modal(" not in ingest
    assert "st.dialog(" not in ingest
    assert "st.modal(" not in review
    assert "identity_fill" in ingest
    assert "Needs review" in review
    assert "Use this" in review
    assert "Listing photo" in review
    assert "filled ·" in review


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


def test_cli_identity_command_is_registered() -> None:
    main = (ROOT / "auction_etl" / "cli" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "identity_app" in main
    assert 'name="identity"' in main
