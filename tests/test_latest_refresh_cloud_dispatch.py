"""Cloud dispatch contract for Latest Auction Refresh."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT
    / "app"
    / "pages"
    / "3_Latest_Auction_Refresh.py"
)


def test_latest_refresh_uses_postgres_dispatch() -> None:
    """Latest Refresh no longer owns machine-local worker state."""
    source = UI.read_text(
        encoding="utf-8"
    )

    assert "create_refresh_job" in source
    assert "get_latest_refresh_job" in source
    assert "list_refresh_jobs" in source

    assert "subprocess.Popen" not in source
    assert "logs/latest-refresh" not in source
    assert "launch_latest_refresh_job.py" not in source
    assert "STATUS_PATH" not in source


def test_latest_refresh_preserves_user_controls() -> None:
    """Cloud dispatch keeps the established collector-facing labels."""
    source = UI.read_text(
        encoding="utf-8"
    )

    assert "Inspect recent ingestion" in source
    assert "Run Buyee, eBay, and Gripsweat" in source
    assert "render_marketplace_progress" in source
    assert "if job_running:" in source
    assert "st.rerun()" in source

def test_latest_refresh_preserves_explicit_confirmation_disable_contract() -> None:
    """Durable dispatch keeps the established explicit RUN safety gate."""
    source = UI.read_text(
        encoding="utf-8"
    )

    assert 'confirmation.strip().upper() == "RUN"' in source
    assert "and not job_running" in source
    assert '"coordination_ready"' in source
    assert "disabled=not refresh_enabled" in source
