"""Production Yahoo/OIDC redirect_uri must be explicit and non-local."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.base_client.sync_app import OAuth2Mixin
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from authlib.oauth2.rfc6749.errors import MismatchingStateException
from authlib.oauth2.rfc6749.parameters import parse_authorization_code_response
from authlib.oidc.core.claims import CodeIDToken
from joserfc.errors import InvalidClaimError
from streamlit.web.server.starlette import starlette_auth_routes

from auction_etl.auth.oidc_production import (
    YAHOO_AUTHORIZATION_ENDPOINT,
    OidcAuthorizationConfig,
    OidcRedirectConfigurationError,
    classify_oidc_runtime,
    oidc_authorization_diagnostic,
    resolve_oidc_redirect_uri,
    validate_streamlit_oidc_configuration,
)


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CALLBACK = (
    "https://collector-ledger.example.test/oauth2callback"
)
LOCAL_CALLBACK = "http://localhost:8501/oauth2callback"
LOCAL_HTTPS_CALLBACK = "https://localhost:8501/oauth2callback"
YAHOO_METADATA = (
    "https://api.login.yahoo.com/.well-known/openid-configuration"
)
FAKE_CLIENT_ID = "dj0yJmk9ExampleClientId"


def production_environ(**extra: str) -> dict[str, str]:
    """Return one production-shaped environment."""
    values = {"AUCTION_ENV": "production"}
    values.update(extra)
    return values


def production_secrets(**extra: Any) -> dict[str, Any]:
    """Return one production-shaped Streamlit auth section."""
    values: dict[str, Any] = {
        "redirect_uri": PRODUCTION_CALLBACK,
        "cookie_secret": "cookie-secret-not-for-logs",
        "client_id": FAKE_CLIENT_ID,
        "client_secret": "super-secret-client-value",
        "server_metadata_url": YAHOO_METADATA,
        "client_kwargs": {
            "scope": "openid email profile",
            "response_type": "code",
            "prompt": "consent",
        },
    }
    values.update(extra)
    return values


def generate_authlib_authorization_request(
    config: Any,
) -> dict[str, str]:
    """Observe one Authlib authorize_redirect Yahoo authorization request."""

    class Framework:
        async def set_state_data(self, session, state, data):
            session[state] = data

        async def get_state_data(self, session, state):
            return session.get(state)

    class Request:
        def __init__(self) -> None:
            self.session: dict[str, Any] = {}

    async def authorize() -> dict[str, str]:
        app = StarletteOAuth2App(
            Framework(),
            name="yahoo",
            client_id=config.client_id,
            authorize_url=YAHOO_AUTHORIZATION_ENDPOINT,
            client_kwargs={
                "scope": config.scope,
                "response_type": config.response_type,
                "prompt": config.prompt,
            },
        )
        request = Request()
        response = await app.authorize_redirect(
            request,
            config.redirect_uri,
        )
        location = str(response.headers["location"])
        query = parse_qs(urlparse(location).query)
        return {
            "url": location,
            "state": query["state"][0],
            "nonce": query["nonce"][0],
        }

    return asyncio.run(authorize())


def authorization_query(result: dict[str, str]) -> dict[str, list[str]]:
    """Parse one generated authorization URL."""
    return parse_qs(urlparse(result["url"]).query)


def test_production_runtime_is_not_development() -> None:
    """Production and development OIDC runtimes stay deliberately separated."""
    assert classify_oidc_runtime(production_environ()) == "production"
    assert (
        classify_oidc_runtime({"AUCTION_ENV": "development"})
        == "development"
    )


def test_explicit_production_overrides_local_redirect_escape_hatch() -> None:
    """OIDC_ENV=production must not be downgraded by OIDC_ALLOW_LOCAL_REDIRECT."""
    assert (
        classify_oidc_runtime(
            {
                "OIDC_ENV": "production",
                "OIDC_ALLOW_LOCAL_REDIRECT": "true",
            }
        )
        == "production"
    )
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="loopback|localhost",
    ):
        resolve_oidc_redirect_uri(
            environ={
                "OIDC_ENV": "production",
                "OIDC_ALLOW_LOCAL_REDIRECT": "true",
                "OIDC_REDIRECT_URI": LOCAL_CALLBACK,
            },
            secrets_auth=production_secrets(
                redirect_uri=LOCAL_CALLBACK,
            ),
        )


def test_conflicting_oidc_and_auction_env_fails_closed() -> None:
    """Explicit OIDC_ENV and AUCTION_ENV must not silently pick one runtime."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="OIDC_ENV conflicts with AUCTION_ENV",
    ):
        classify_oidc_runtime(
            {
                "OIDC_ENV": "development",
                "AUCTION_ENV": "production",
            }
        )


def test_matching_oidc_and_auction_env_aliases_agree() -> None:
    """Equivalent production and development aliases may be set together."""
    assert (
        classify_oidc_runtime(
            {
                "OIDC_ENV": "prod",
                "AUCTION_ENV": "production",
            }
        )
        == "production"
    )
    assert (
        classify_oidc_runtime(
            {
                "OIDC_ENV": "dev",
                "AUCTION_ENV": "development",
            }
        )
        == "development"
    )


def test_production_redirect_uri_equals_canonical_callback() -> None:
    """Production uses the Streamlit secret that matches OIDC_REDIRECT_URI."""
    uri = resolve_oidc_redirect_uri(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(
            redirect_uri=PRODUCTION_CALLBACK,
        ),
    )
    assert uri == PRODUCTION_CALLBACK


def test_production_rejects_legacy_yahoo_redirect_uri_alone() -> None:
    """YAHOO_REDIRECT_URI cannot satisfy production without OIDC_REDIRECT_URI."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="OIDC_REDIRECT_URI",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                YAHOO_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth=production_secrets(
                redirect_uri=PRODUCTION_CALLBACK,
            ),
        )


def test_production_rejects_conflicting_yahoo_redirect_uri() -> None:
    """A stale YAHOO_REDIRECT_URI must not diverge from OIDC_REDIRECT_URI."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="YAHOO_REDIRECT_URI conflicts",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
                YAHOO_REDIRECT_URI=LOCAL_CALLBACK,
            ),
            secrets_auth=production_secrets(
                redirect_uri=PRODUCTION_CALLBACK,
            ),
        )


def test_matching_yahoo_redirect_uri_is_tolerated_in_production() -> None:
    """YAHOO_REDIRECT_URI may exist only when it equals OIDC_REDIRECT_URI."""
    uri = resolve_oidc_redirect_uri(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            YAHOO_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(
            redirect_uri=PRODUCTION_CALLBACK,
        ),
    )
    assert uri == PRODUCTION_CALLBACK


def test_production_rejects_secret_that_differs_from_oidc_redirect_uri() -> None:
    """Do not silently repair a localhost Streamlit secret at runtime."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="does not match",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth=production_secrets(
                redirect_uri=LOCAL_CALLBACK,
            ),
        )


def test_production_localhost_redirect_is_rejected() -> None:
    """Production must never select a localhost callback."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="loopback|localhost",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=LOCAL_CALLBACK,
            ),
            secrets_auth=production_secrets(
                redirect_uri=LOCAL_CALLBACK,
            ),
        )


def test_production_loopback_redirect_is_rejected() -> None:
    """Production must never select 127.0.0.1."""
    loopback = "http://127.0.0.1:8501/oauth2callback"
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="loopback|127",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=loopback,
            ),
            secrets_auth=production_secrets(
                redirect_uri=loopback,
            ),
        )


@pytest.mark.parametrize(
    "loopback_uri",
    [
        "https://2130706433/oauth2callback",
        "https://0x7f000001/oauth2callback",
        "https://0177.0.0.1/oauth2callback",
        "https://[::1]/oauth2callback",
        "https://[::ffff:127.0.0.1]/oauth2callback",
    ],
)
def test_production_rejects_equivalent_loopback_encodings(
    loopback_uri: str,
) -> None:
    """Production must reject numeric and IPv6-mapped loopback callbacks."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="loopback|localhost|127",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=loopback_uri,
            ),
            secrets_auth=production_secrets(
                redirect_uri=loopback_uri,
            ),
        )


def test_production_http_redirect_is_rejected() -> None:
    """Production callbacks must be HTTPS."""
    insecure = "http://collector-ledger.example.test/oauth2callback"
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="HTTPS",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=insecure,
            ),
            secrets_auth=production_secrets(
                redirect_uri=insecure,
            ),
        )


def test_missing_production_redirect_uri_fails_closed() -> None:
    """Absent production callback configuration is a hard failure."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="OIDC_REDIRECT_URI",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(),
            secrets_auth={
                "client_id": FAKE_CLIENT_ID,
                "client_secret": "super-secret-client-value",
                "server_metadata_url": YAHOO_METADATA,
            },
        )


def test_production_does_not_use_vercel_url() -> None:
    """Vercel preview/host env vars must not become the Yahoo callback."""
    with pytest.raises(OidcRedirectConfigurationError):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                VERCEL_URL="auction-etl-git-feature.vercel.app",
                VERCEL_ENV="preview",
            ),
            secrets_auth={
                "client_id": FAKE_CLIENT_ID,
                "client_secret": "super-secret-client-value",
                "server_metadata_url": YAHOO_METADATA,
            },
        )


def test_production_rejects_vercel_preview_hostname() -> None:
    """Yahoo login is not owned by Vercel preview deployments."""
    preview = (
        "https://auction-etl-git-feature.vercel.app/oauth2callback"
    )
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="vercel",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=preview,
            ),
            secrets_auth=production_secrets(
                redirect_uri=preview,
            ),
        )


def test_production_rejects_request_host_override() -> None:
    """Browser/request Host headers cannot choose the callback."""
    with pytest.raises(OidcRedirectConfigurationError):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                HTTP_HOST="evil.example.test",
                HOST="evil.example.test",
            ),
            secrets_auth={
                "client_id": FAKE_CLIENT_ID,
                "client_secret": "super-secret-client-value",
                "server_metadata_url": YAHOO_METADATA,
            },
            request_host="evil.example.test",
        )


def test_development_may_use_explicit_localhost() -> None:
    """Local OIDC remains available only when development is explicit."""
    uri = resolve_oidc_redirect_uri(
        environ={"AUCTION_ENV": "development"},
        secrets_auth=production_secrets(
            redirect_uri=LOCAL_CALLBACK,
        ),
    )
    assert uri == LOCAL_CALLBACK


def test_development_may_use_explicit_https_localhost() -> None:
    """Development accepts HTTPS loopback; production still rejects it."""
    uri = resolve_oidc_redirect_uri(
        environ={"AUCTION_ENV": "development"},
        secrets_auth=production_secrets(
            redirect_uri=LOCAL_HTTPS_CALLBACK,
        ),
    )
    assert uri == LOCAL_HTTPS_CALLBACK

    config = validate_streamlit_oidc_configuration(
        environ={
            "AUCTION_ENV": "development",
            "OIDC_ENV": "development",
            "OIDC_REDIRECT_URI": LOCAL_HTTPS_CALLBACK,
        },
        secrets_auth=production_secrets(
            redirect_uri=LOCAL_HTTPS_CALLBACK,
        ),
    )
    assert config.runtime == "development"
    assert config.redirect_uri == LOCAL_HTTPS_CALLBACK

    with pytest.raises(
        OidcRedirectConfigurationError,
        match="loopback",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=LOCAL_HTTPS_CALLBACK,
            ),
            secrets_auth=production_secrets(
                redirect_uri=LOCAL_HTTPS_CALLBACK,
            ),
        )


def test_yahoo_production_requires_consent_prompt_in_secrets() -> None:
    """prompt=consent is a Yahoo compatibility override, not a runtime patch."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="prompt=consent",
    ):
        validate_streamlit_oidc_configuration(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth=production_secrets(
                client_kwargs={
                    "scope": "openid email profile",
                    "response_type": "code",
                    "prompt": "select_account",
                },
            ),
        )


def test_authlib_generates_exact_yahoo_authorization_url() -> None:
    """Authlib, not pinned config, generates the Yahoo authorization request."""
    config = validate_streamlit_oidc_configuration(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(),
    )
    result = generate_authlib_authorization_request(config)
    parsed = urlparse(result["url"])
    query = authorization_query(result)

    assert parsed.scheme == "https"
    assert parsed.netloc == "api.login.yahoo.com"
    assert parsed.path == "/oauth2/request_auth"
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [PRODUCTION_CALLBACK]
    assert query["client_id"] == [FAKE_CLIENT_ID]
    assert "openid" in query["scope"][0].split()
    assert query["prompt"] == ["consent"]
    assert query["state"][0]
    assert query["nonce"][0]
    assert query["state"][0] == result["state"]
    assert query["nonce"][0] == result["nonce"]
    assert "redirect_url" not in query
    assert "client_secret" not in query
    assert "super-secret-client-value" not in result["url"]


def test_authlib_state_and_nonce_are_fresh_not_pinned() -> None:
    """Each authorization request gets a new session-bound state and nonce."""
    config = validate_streamlit_oidc_configuration(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(),
    )
    first = generate_authlib_authorization_request(config)
    second = generate_authlib_authorization_request(config)
    assert first["state"]
    assert first["nonce"]
    assert first["state"] != second["state"]
    assert first["nonce"] != second["nonce"]
    assert config.state_handling == "delegated_to_streamlit_authlib"
    assert config.nonce_handling == "delegated_to_streamlit_authlib"
    assert not hasattr(config, "state") or not isinstance(
        getattr(config, "state", None),
        str,
    )


def test_token_exchange_reuses_the_same_redirect_uri() -> None:
    """Code exchange must not reconstruct a different callback."""
    config = validate_streamlit_oidc_configuration(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(),
    )
    assert config.token_exchange_redirect_uri == PRODUCTION_CALLBACK
    assert config.token_exchange["grant_type"] == "authorization_code"
    assert config.token_exchange["redirect_uri"] == config.redirect_uri
    diagnostic = oidc_authorization_diagnostic(config)
    assert diagnostic["token_exchange_redirect_match"] == "true"


def test_diagnostic_token_exchange_match_uses_value_equality() -> None:
    """Yahoo requires the same complete redirect URL, not object identity."""
    uri = PRODUCTION_CALLBACK
    duplicate = (uri + ".")[:-1]
    assert uri == duplicate
    assert uri is not duplicate
    config = OidcAuthorizationConfig(
        redirect_uri=uri,
        token_exchange_redirect_uri=duplicate,
        client_id=FAKE_CLIENT_ID,
        response_type="code",
        scope="openid email profile",
        prompt="consent",
        state_handling="delegated_to_streamlit_authlib",
        nonce_handling="delegated_to_streamlit_authlib",
        pkce_status="not_asserted",
        redirect_uri_status="accepted",
        runtime="production",
        yahoo_prompt_is_compatibility_override=True,
        authorization_endpoint="https://api.login.yahoo.com/oauth2/request_auth",
        token_endpoint="https://api.login.yahoo.com/oauth2/get_token",
        token_exchange={
            "grant_type": "authorization_code",
            "redirect_uri": duplicate,
        },
        client_id_fingerprint="deadbeef",
    )
    diagnostic = oidc_authorization_diagnostic(config)
    assert diagnostic["token_exchange_redirect_match"] == "true"


def test_yahoo_keeps_openid_scope_and_documents_consent_override() -> None:
    """Yahoo OIDC needs openid; consent is an explicit Yahoo override."""
    config = validate_streamlit_oidc_configuration(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(),
    )
    assert "openid" in config.scope.split()
    assert config.prompt == "consent"
    assert config.yahoo_prompt_is_compatibility_override is True
    assert config.pkce_status == "not_asserted"
    assert config.state_handling == "delegated_to_streamlit_authlib"
    assert config.nonce_handling == "delegated_to_streamlit_authlib"
    assert config.redirect_uri_status == "accepted"


def test_authlib_callback_rejects_invalid_state() -> None:
    """Invalid callback state is rejected by Authlib, not app-owned logic."""
    with pytest.raises(MismatchingStateException):
        parse_authorization_code_response(
            f"{PRODUCTION_CALLBACK}?code=example-code&state=other",
            state="expected-state",
        )
    with pytest.raises(MismatchingStateError):
        OAuth2Mixin._format_state_params(
            None,
            {"code": "example-code", "state": "missing-session"},
        )


def test_authlib_callback_rejects_invalid_nonce() -> None:
    """Invalid ID-token nonce is rejected by Authlib, not app-owned logic."""
    claims = CodeIDToken(
        {
            "iss": "https://api.login.yahoo.com",
            "sub": "subject-1",
            "aud": FAKE_CLIENT_ID,
            "exp": 4102444800,
            "iat": 1,
            "nonce": "issued-nonce",
        },
        {},
        {},
        {"nonce": "session-nonce"},
    )
    with pytest.raises(InvalidClaimError):
        claims.validate_nonce()


def test_installed_streamlit_validates_authlib_state_and_nonce() -> None:
    """Installed Streamlit/Authlib must retain state and nonce validation."""
    streamlit_source = Path(
        starlette_auth_routes.__file__
    ).read_text(encoding="utf-8")

    authlib_source = Path(
        inspect.getfile(StarletteOAuth2App)
    ).read_text(encoding="utf-8")

    assert "authorize_access_token" in streamlit_source
    assert "oauth2callback" in streamlit_source
    assert "_clear_auth_cookie" in streamlit_source

    assert "code_challenge_methods_supported" in streamlit_source
    assert "S256" in streamlit_source

    assert "get_state_data" in authlib_source
    assert "_format_state_params" in authlib_source
    assert "nonce" in authlib_source
    assert "state_data" in authlib_source


def test_diagnostics_omit_secrets_and_tokens() -> None:
    """Diagnostics may fingerprint the client ID but must not leak secrets."""
    config = validate_streamlit_oidc_configuration(
        environ=production_environ(
            OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
        ),
        secrets_auth=production_secrets(),
    )
    diagnostic = oidc_authorization_diagnostic(config)
    rendered = " ".join(
        f"{key}={value}" for key, value in diagnostic.items()
    )

    assert diagnostic["authorization_endpoint_host"] == "api.login.yahoo.com"
    assert diagnostic["redirect_uri"] == PRODUCTION_CALLBACK
    assert diagnostic["redirect_uri_status"] == "accepted"
    assert diagnostic["runtime"] == "production"
    assert diagnostic["response_type"] == "code"
    assert "openid" in str(diagnostic["scope"])
    assert diagnostic["STATE_HANDLING"] == "delegated_to_streamlit_authlib"
    assert diagnostic["NONCE_HANDLING"] == "delegated_to_streamlit_authlib"
    assert diagnostic["PKCE_status"] == "not_asserted"
    assert "STATE_GENERATED_AND_VALIDATED" not in diagnostic
    assert "NONCE_GENERATED_AND_VALIDATED" not in diagnostic
    assert "PKCE_follows_provider_metadata" not in diagnostic
    assert diagnostic["client_id_fingerprint"]
    assert FAKE_CLIENT_ID not in rendered
    assert "super-secret-client-value" not in rendered
    assert "cookie-secret-not-for-logs" not in rendered
    assert "authorization_code_value" not in rendered
    assert "access_token" not in rendered
    assert "refresh_token" not in rendered
    assert "client_secret" not in rendered
    assert "cryptographic-test-state" not in rendered


def test_streamlit_login_validates_canonical_redirect_before_provider() -> None:
    """Validate Streamlit secrets before st.login(); do not overlay them."""
    source = (
        ROOT / "auction_etl" / "auth" / "streamlit_auth.py"
    ).read_text(encoding="utf-8")
    validate = source.index("validate_streamlit_oidc_login(")
    login = source.index("st.login()")
    assert validate < login
    assert "merge_programmatic_secrets" not in source
    assert "apply_canonical_oidc_auth_section" not in source


def test_example_secrets_document_yahoo_consent_override() -> None:
    """The committed example must not teach a production localhost callback."""
    example = (
        ROOT / ".streamlit" / "secrets.toml.example"
    ).read_text(encoding="utf-8")
    section_marker = "\n[auth]\n"
    assert section_marker in example
    auth_section = example.split(section_marker, 1)[1]
    redirect_lines = [
        line.strip()
        for line in auth_section.splitlines()
        if line.strip().startswith("redirect_uri")
    ]
    assert redirect_lines == [
        'redirect_uri = "https://YOUR-STREAMLIT-HOST/oauth2callback"'
    ]
    assert "https://" in example
    assert "oauth2callback" in example
    assert "OIDC_REDIRECT_URI" in example
    assert "OIDC_ENV" in example
    assert "Conflicting" in example
    assert "api.login.yahoo.com" in example
    assert "response_type" in example
    assert "openid" in example
    assert 'prompt = "consent"' in example
    assert "Yahoo compatibility" in example


def test_example_secrets_document_local_http_or_https_callbacks() -> None:
    """Local guidance must match the validator: HTTP or HTTPS on loopback."""
    example = (
        ROOT / ".streamlit" / "secrets.toml.example"
    ).read_text(encoding="utf-8")
    comments = example.split("\n[auth]\n", 1)[0]
    assert "Use an explicit local HTTP callback" not in example
    assert "HTTP or HTTPS" in comments
    assert LOCAL_HTTPS_CALLBACK in comments
    assert "sslCertFile" in comments
    assert "sslKeyFile" in comments
    assert "rejects loopback" in comments


@pytest.mark.parametrize(
    "scope",
    [
        "",
        "email profile",
        "openid_email profile",
        "emailopenid profile",
    ],
)
def test_production_requires_openid_as_a_scope_token(scope: str) -> None:
    """openid must be a whole scope token, not a substring."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="scope=openid",
    ):
        validate_streamlit_oidc_configuration(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth=production_secrets(
                client_kwargs={
                    "scope": scope,
                    "response_type": "code",
                    "prompt": "consent",
                },
            ),
        )


@pytest.mark.parametrize(
    ("env_uri", "secret_uri"),
    [
        (
            "https://app.streamlit.app/oauth2callback",
            "https://app.streamlit.app/oauth2callback/",
        ),
        (
            "https://app.streamlit.app/oauth2callback",
            "https://app.streamlit.app/oauth2callback?x=1",
        ),
        (
            "https://app.streamlit.app/oauth2callback",
            "https://other.streamlit.app/oauth2callback",
        ),
    ],
)
def test_production_redirect_mismatch_is_character_for_character(
    env_uri: str,
    secret_uri: str,
) -> None:
    """Production owns one exact redirect_uri string."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="does not match",
    ) as caught:
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=env_uri,
            ),
            secrets_auth=production_secrets(
                redirect_uri=secret_uri,
            ),
        )
    message = str(caught.value)
    assert "super-secret-client-value" not in message
    assert "cookie-secret-not-for-logs" not in message


def test_production_rejects_matching_trailing_slash_callback() -> None:
    """Exact /oauth2callback is required even when env and secrets agree."""
    slashed = f"{PRODUCTION_CALLBACK}/"
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="oauth2callback",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=slashed,
            ),
            secrets_auth=production_secrets(
                redirect_uri=slashed,
            ),
        )


def test_production_rejects_redirect_userinfo() -> None:
    """A callback must not embed a username or password."""
    embedded = (
        "https://oauth-user:oauth-password@"
        "collector-ledger.example.test/oauth2callback"
    )
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="username or password",
    ) as caught:
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=embedded,
            ),
            secrets_auth=production_secrets(
                redirect_uri=embedded,
            ),
        )
    assert "oauth-password" not in str(caught.value)


def test_production_requires_streamlit_secret_when_env_is_set() -> None:
    """Missing [auth].redirect_uri fails closed in production."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match=r"\[auth\]\.redirect_uri",
    ):
        resolve_oidc_redirect_uri(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth={
                "client_id": FAKE_CLIENT_ID,
                "client_secret": "super-secret-client-value",
                "server_metadata_url": YAHOO_METADATA,
            },
        )


def test_production_requires_yahoo_discovery_url() -> None:
    """Production Yahoo login must use Yahoo's OpenID discovery document."""
    with pytest.raises(
        OidcRedirectConfigurationError,
        match="openid-configuration",
    ):
        validate_streamlit_oidc_configuration(
            environ=production_environ(
                OIDC_REDIRECT_URI=PRODUCTION_CALLBACK,
            ),
            secrets_auth=production_secrets(
                server_metadata_url=(
                    "https://accounts.example.test/.well-known/"
                    "openid-configuration"
                ),
            ),
        )


def test_mismatched_state_cannot_create_streamlit_login() -> None:
    """Auth callback failure must clear auth state before login creation."""
    source = Path(
        starlette_auth_routes.__file__
    ).read_text(encoding="utf-8")

    callback_start = source.index("async def _auth_callback")
    routes_start = source.index(
        "def create_auth_routes",
        callback_start,
    )

    callback = source[
        callback_start:routes_start
    ]

    authorize_index = callback.index(
        "authorize_access_token"
    )

    clear_cookie_index = callback.index(
        "_clear_auth_cookie",
        authorize_index,
    )

    user_token_index = callback.index(
        "user = token.get",
        authorize_index,
    )

    assert authorize_index < clear_cookie_index
    assert clear_cookie_index < user_token_index

    failure_region = callback[
        authorize_index:user_token_index
    ]

    assert "_clear_auth_cookie" in failure_region
    assert "is_logged_in=True" not in failure_region


def test_login_does_not_proceed_after_validation_failure() -> None:
    """A failed OIDC validator must terminate before st.login()."""
    source = (
        ROOT
        / "auction_etl"
        / "auth"
        / "streamlit_auth.py"
    ).read_text(encoding="utf-8")

    button_start = source.index(
        "if st.button("
    )

    function_end = source.index(
        "def require_authenticated_account",
        button_start,
    )

    button = source[
        button_start:function_end
    ]

    validation_index = button.index(
        "validate_streamlit_oidc_login("
    )

    login_index = button.index(
        "st.login()"
    )

    exception_index = button.index(
        "except OidcRedirectConfigurationError",
        validation_index,
    )

    stop_index = button.index(
        "st.stop()",
        exception_index,
    )

    assert validation_index < exception_index
    assert exception_index < stop_index
    assert stop_index < login_index

    failure_region = button[
        exception_index:login_index
    ]

    assert "st.stop()" in failure_region
    assert "st.login()" not in failure_region
