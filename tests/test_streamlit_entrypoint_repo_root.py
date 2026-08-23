"""Regression contract for Streamlit Community Cloud repository imports."""

from __future__ import annotations

from pathlib import Path


ENTRYPOINT = Path(
    "app/collector_review.py"
)


def test_streamlit_entrypoint_bootstraps_repository_root() -> None:
    """Local repository packages must be importable before app startup."""
    source = ENTRYPOINT.read_text(
        encoding="utf-8",
    )

    assert "import sys" in source
    assert "from pathlib import Path" in source

    assert (
        "ROOT = Path(__file__).resolve().parents[1]"
        in source
    )

    assert (
        "if str(ROOT) not in sys.path:"
        in source
    )

    assert (
        "sys.path.insert("
        in source
    )

    bootstrap = source.index(
        "sys.path.insert("
    )

    auction_import = source.index(
        "from auction_etl.auth.context import AccountContext"
    )

    app_import = source.index(
        "from app.collector_analytics_editor import ("
    )

    assert bootstrap < auction_import
    assert bootstrap < app_import


def test_streamlit_entrypoint_uses_repository_packages() -> None:
    """The entrypoint still consumes the Phase-D application packages."""
    source = ENTRYPOINT.read_text(
        encoding="utf-8",
    )

    required = (
        "from auction_etl.auth.context import AccountContext",
        "from auction_etl.auth.streamlit_auth import (",
        "from auction_etl.services.account_scope import account_transaction",
        "from app.collector_analytics_editor import (",
        "from app.navigation import render_navigation",
    )

    for fragment in required:
        assert fragment in source
