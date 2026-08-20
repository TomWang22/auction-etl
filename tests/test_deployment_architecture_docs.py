"""Deployment and cloud architecture documentation contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

README = ROOT / "README.md"
ARCHITECTURE = ROOT / "docs" / "ARCHITECTURE.md"
DEPLOYMENT = ROOT / "docs" / "DEPLOYMENT.md"
DATABASE = ROOT / "docs" / "DATABASE_DEPLOYMENT.md"


def read(path: Path) -> str:
    """Read UTF-8 repository documentation."""
    return path.read_text(encoding="utf-8")


def test_readme_contains_collector_ledger_architecture() -> None:
    """README exposes the accepted Collector Ledger architecture."""
    value = read(README)

    assert "# Collector Ledger" in value
    assert "## Architecture overview" in value
    assert "```mermaid" in value
    assert "Vercel" in value
    assert "Neon PostgreSQL" in value
    assert "refresh worker" in value
    assert "Railway" in value


def test_architecture_separates_control_plane_and_worker() -> None:
    """Long-running browser work remains outside web execution."""
    value = read(ARCHITECTURE)

    assert "Vercel control plane" in value
    assert "Logical refresh execution role" in value
    assert "Neon PostgreSQL" in value
    assert "spawn detached ingestion processes" in value
    assert "treat local files as shared refresh state" in value


def test_architecture_preserves_incremental_marketplace_contracts() -> None:
    """Documentation preserves the three incremental policies."""
    value = read(ARCHITECTURE)

    assert "calculate new warehouse IDs" in value
    assert "bounded known-overlap threshold" in value
    assert "enrich only new identities" in value


def test_deployment_preserves_buyee_browser_contract() -> None:
    """Cloud deployment retains validated Buyee compatibility."""
    value = read(DEPLOYMENT)

    assert "headed Chromium" in value
    assert "offscreen placement" in value
    assert "persistent browser context" in value
    assert "Do not silently re-enable true headless mode." in value


def test_database_plan_separates_runtime_and_migrations() -> None:
    """Runtime and migration connection purposes are documented."""
    value = read(DATABASE)

    assert "DATABASE_URL=<managed PostgreSQL application connection>" in value
    assert (
        "DATABASE_URL_MIGRATIONS=<direct non-pooled PostgreSQL connection>"
        in value
    )
    assert "Alembic migrations use the direct migration URL." in value


def test_database_plan_contains_durable_refresh_schema() -> None:
    """Cloud refresh state is database-backed."""
    value = read(DATABASE)

    assert "ops.refresh_job" in value
    assert "ops.refresh_marketplace" in value
    assert "ops.refresh_event" in value
    assert "FOR UPDATE SKIP LOCKED" in value
    assert "lease_expires_at" in value


def test_docs_keep_production_cutover_explicit() -> None:
    """Source promotion does not silently claim production cutover."""
    readme = read(README)
    deployment = read(DEPLOYMENT)

    assert (
        "Production runtime/data cutover remains a separate explicit operation."
        in readme
    )
    assert "Cloud production cutover is not yet approved." in deployment
    assert (
        "Cloud cutover is not complete until these are implemented and accepted:"
        not in readme
    )
