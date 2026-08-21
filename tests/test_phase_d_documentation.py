"""Phase-D documentation contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_master_architecture_covers_security_and_migration() -> None:
    text = (
        ROOT / "docs" / "PHASE_D_AUTH_ACCOUNT_ARCHITECTURE.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "Authentication versus authorization",
        "Existing-owner backfill",
        "Buyee isolation",
        "Durable refresh ownership",
        "Vercel control-plane security",
        "PostgreSQL RLS",
        "Migration stages",
        "Acceptance criteria",
    ):
        assert phrase in text
    assert text.count("```mermaid") >= 4


def test_runbook_locks_owner_acceptance_counts() -> None:
    text = (
        ROOT / "docs" / "PHASE_D_MIGRATION_RUNBOOK.md"
    ).read_text(encoding="utf-8")
    assert "VISIBLE_LISTING_COUNT=1441" in text
    assert "TRACKED_ARTIST_COUNT=3" in text
    assert "MARKETPLACE_SEARCH_COUNT=5" in text


def test_security_requires_cross_account_denials() -> None:
    text = (
        ROOT / "docs" / "PHASE_D_SECURITY_MODEL.md"
    ).read_text(encoding="utf-8")
    assert "cross-account listing read denied" in text
    assert "cross-account refresh GET denied" in text
    assert "cross-account Buyee reference read denied" in text
