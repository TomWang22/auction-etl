"""Phase-D authentication contract."""

from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_oidc_surface_exists() -> None:
    source = (
        ROOT / "auction_etl" / "auth" / "streamlit_auth.py"
    ).read_text(encoding="utf-8")
    assert "st.login()" in source
    assert "st.logout()" in source
    assert "st.user.is_logged_in" in source
    assert "require_authenticated_account" in source


def test_real_streamlit_secrets_are_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in gitignore

    example = (
        ROOT / ".streamlit" / "secrets.toml.example"
    ).read_text(encoding="utf-8")
    assert "OIDC_CLIENT_SECRET" in example
    assert "GENERATE_A_LONG_RANDOM_SECRET" in example



def test_current_principal_uses_issuer_subject_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stable external identity is the OIDC issuer and subject."""
    from auction_etl.auth import streamlit_auth

    fake_streamlit = SimpleNamespace(
        user=SimpleNamespace(
            is_logged_in=True,
            iss="https://issuer.example.test",
            sub="subject-123",
            email="collector@example.test",
            name="Collector",
        )
    )

    monkeypatch.setattr(
        streamlit_auth,
        "st",
        fake_streamlit,
    )

    principal = streamlit_auth.current_principal()

    assert principal is not None
    assert principal.provider == "https://issuer.example.test"
    assert principal.subject == "subject-123"
    assert principal.email == "collector@example.test"
    assert principal.display_name == "Collector"


def test_current_principal_rejects_missing_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subject without its OIDC issuer is not a complete identity."""
    from auction_etl.auth import streamlit_auth

    fake_streamlit = SimpleNamespace(
        user=SimpleNamespace(
            is_logged_in=True,
            sub="subject-123",
            email="collector@example.test",
            name="Collector",
        )
    )

    monkeypatch.setattr(
        streamlit_auth,
        "st",
        fake_streamlit,
    )

    with pytest.raises(
        RuntimeError,
        match="without an 'iss' claim",
    ):
        streamlit_auth.current_principal()


def test_current_principal_rejects_missing_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An issuer without the OIDC subject is not a complete identity."""
    from auction_etl.auth import streamlit_auth

    fake_streamlit = SimpleNamespace(
        user=SimpleNamespace(
            is_logged_in=True,
            iss="https://issuer.example.test",
            email="collector@example.test",
            name="Collector",
        )
    )

    monkeypatch.setattr(
        streamlit_auth,
        "st",
        fake_streamlit,
    )

    with pytest.raises(
        RuntimeError,
        match="without a 'sub' claim",
    ):
        streamlit_auth.current_principal()


def test_streamlit_auth_has_no_generic_provider_fallback() -> None:
    """Runtime identity must preserve the actual OIDC issuer namespace."""
    source = (
        ROOT / "auction_etl" / "auth" / "streamlit_auth.py"
    ).read_text(encoding="utf-8")

    assert 'issuer = _claim("iss")' in source
    assert 'subject = _claim("sub")' in source
    assert "provider=issuer" in source
    assert "COLLECTOR_LEDGER_OIDC_PROVIDER" not in source
