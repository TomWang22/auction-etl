"""Contracts for persisting extracted record labels on warehouse auctions."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "auction_etl" / "services" / "warehouse.py"
MODEL = ROOT / "auction_etl" / "models" / "warehouse.py"
VIEWS = ROOT / "auction_etl" / "database" / "collector_views.py"
REVISION = (
    ROOT
    / "alembic"
    / "versions"
    / "a1c3e8f7b240_auction_label.py"
)
UP_SQL = (
    ROOT
    / "alembic"
    / "versions"
    / "a1c3e8f7b240_auction_label_up.sql"
)


def test_warehouse_model_and_sync_persist_label() -> None:
    model = MODEL.read_text(encoding="utf-8")
    sync = WAREHOUSE.read_text(encoding="utf-8")

    assert "label:" in model
    assert '"label":' in sync
    assert "listing.label" in sync


def test_collector_views_expose_auction_label() -> None:
    views = VIEWS.read_text(encoding="utf-8")

    assert '    "label",' in views
    assert "a.label," in views
    assert "effective.label," in views


def test_label_migration_follows_current_head() -> None:
    source = REVISION.read_text(encoding="utf-8")
    sql = UP_SQL.read_text(encoding="utf-8")

    assert 'revision = "a1c3e8f7b240"' in source
    assert 'down_revision = "6a8f4d2c9b17"' in source
    assert "ADD COLUMN" in sql
    assert "warehouse.auction" in sql
    assert "label" in sql
