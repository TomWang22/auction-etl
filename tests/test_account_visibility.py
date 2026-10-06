"""Local warehouse visibility stays off the Yahoo identity until attached."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

from auction_etl.services import account_visibility


ROOT = Path(__file__).resolve().parents[1]


def test_production_does_not_attach_warehouse_listings(
    monkeypatch,
) -> None:
    """A production Yahoo login must keep an empty personal workspace."""
    monkeypatch.setenv("AUCTION_ENV", "production")
    monkeypatch.setenv("OIDC_ENV", "production")
    engine = MagicMock()

    added = account_visibility.attach_development_warehouse_visibility(
        engine,
        uuid.uuid4(),
    )

    assert added == 0
    engine.connect.assert_not_called()
    engine.begin.assert_not_called()


def test_streamlit_auth_attaches_local_warehouse_after_yahoo_login() -> None:
    """Development Collector Review maps the local warehouse onto the Yahoo account."""
    source = (
        ROOT / "auction_etl" / "auth" / "streamlit_auth.py"
    ).read_text(encoding="utf-8")
    assert "attach_development_warehouse_visibility" in source
    assert "resolve_or_create_personal_account(engine, principal)" in source
