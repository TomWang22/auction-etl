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


def test_readme_contains_current_and_target_architecture() -> None:
    """README exposes current and target runtime generations."""

    value = read(README)

    assert "Current production" in value
    assert "Target cloud architecture" in value
    assert "```mermaid" in value
    assert "Durable refresh jobs" in value
    assert "Persistent Playwright" in value


def test_architecture_separates_control_plane_and_worker() -> None:
    """Long-running browser work remains outside web execution."""

    value = read(ARCHITECTURE)

    assert "Vercel control plane" in value
    assert "Persistent worker platform" in value
    assert "Managed PostgreSQL" in value
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


def test_docs_do_not_claim_cloud_production_is_complete() -> None:
    """Target architecture remains distinct from current production."""

    readme = read(README)
    deployment = read(DEPLOYMENT)

    assert "Cloud cutover is not complete" in readme
    assert "Cloud production cutover is not yet approved." in deployment
