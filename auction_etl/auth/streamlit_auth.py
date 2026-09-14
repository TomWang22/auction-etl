"""Streamlit OIDC login/logout and account bootstrap."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import streamlit as st
from sqlalchemy.engine import Engine

from auction_etl.auth.context import (
    AccountContext,
    AuthenticatedPrincipal,
)
from auction_etl.auth.oidc_production import (
    OidcRedirectConfigurationError,
    oidc_authorization_diagnostic,
    validate_streamlit_oidc_configuration,
)
from auction_etl.services.account_access import (
    resolve_or_create_personal_account,
)


def _claim(name: str, default: str = "") -> str:
    """Read one OIDC claim as normalized text."""
    value: Any = getattr(st.user, name, default)
    if value is None:
        return default
    return str(value).strip()


def current_principal() -> AuthenticatedPrincipal | None:
    """Return the current normalized OIDC principal."""
    if not st.user.is_logged_in:
        return None

    issuer = _claim("iss")
    subject = _claim("sub")
    email = _claim("email")
    display_name = (
        _claim("name")
        or _claim("preferred_username")
        or email
    )

    if not issuer:
        raise RuntimeError(
            "OIDC authentication succeeded without an 'iss' claim."
        )
    if not subject:
        raise RuntimeError(
            "OIDC authentication succeeded without a 'sub' claim."
        )
    if not email:
        raise RuntimeError(
            "OIDC authentication succeeded without an email claim."
        )

    return AuthenticatedPrincipal(
        provider=issuer,
        subject=subject,
        email=email,
        display_name=display_name,
    )


def _streamlit_auth_section() -> dict[str, Any]:
    """Return a copy of Streamlit's [auth] secrets section."""
    try:
        raw_auth = st.secrets.get("auth", {})
    except Exception:
        return {}
    if not isinstance(raw_auth, Mapping):
        return {}
    copied: dict[str, Any] = {}
    for key, value in raw_auth.items():
        if isinstance(value, Mapping):
            copied[str(key)] = dict(value)
        else:
            copied[str(key)] = value
    return copied


def validate_streamlit_oidc_login() -> None:
    """Fail closed when Streamlit secrets are not the canonical callback."""
    config = validate_streamlit_oidc_configuration(
        environ=os.environ,
        secrets_auth=_streamlit_auth_section(),
    )
    diagnostic = oidc_authorization_diagnostic(config)
    st.session_state["_oidc_authorization_diagnostic"] = diagnostic


def render_login_screen() -> None:
    """Render the unauthenticated landing screen."""
    st.title("Collector Ledger")
    st.write("Your private marketplace-auction research workspace.")
    st.write(
        "Sign in to access your listings, tracked artists, "
        "refresh history, and collection decisions."
    )
    if st.button(
        "Sign in or create account",
        type="primary",
        width="stretch",
    ):
        try:
            validate_streamlit_oidc_login()
        except OidcRedirectConfigurationError as exc:
            st.error(str(exc))
            st.stop()
            raise
        st.login()
    st.stop()


def require_authenticated_account(engine: Engine) -> AccountContext:
    """Require OIDC login and resolve/create the personal account."""
    try:
        validate_streamlit_oidc_login()
    except OidcRedirectConfigurationError as exc:
        st.error(str(exc))
        st.stop()
        raise

    principal = current_principal()
    if principal is None:
        render_login_screen()
        raise RuntimeError("Streamlit stop unexpectedly returned.")

    return resolve_or_create_personal_account(engine, principal)


def render_account_menu(context: AccountContext) -> None:
    """Render account identity and logout in the sidebar."""
    with st.sidebar:
        st.caption(f"Signed in as {context.display_name}")
        st.caption(context.email)
        if st.button("Log out", width="stretch"):
            st.logout()


def require_system_admin(context: AccountContext) -> None:
    """Block global administrative tools for ordinary accounts."""
    if context.is_system_admin:
        return
    st.error(
        "This tool is restricted to Collector Ledger system administrators."
    )
    st.stop()
