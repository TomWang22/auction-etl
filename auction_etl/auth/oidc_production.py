"""Canonical production OIDC/Yahoo redirect_uri validation.

Streamlit native login owns the Yahoo authorization-code flow. Production
must configure one explicit HTTPS callback in Streamlit secrets and in
OIDC_REDIRECT_URI. Those values must match. This module never derives the
callback from localhost, loopback, Vercel hosts, or request headers, and
it never mutates Streamlit secrets at runtime.

OIDC_ENV and AUCTION_ENV are classified independently. If both are set to
different runtimes, configuration fails closed. Authlib/Streamlit generate
and validate per-request state and nonce; this module does not claim that
those checks already succeeded.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

OidcRuntime = Literal["production", "development"]

YAHOO_AUTHORIZATION_ENDPOINT = (
    "https://api.login.yahoo.com/oauth2/request_auth"
)
YAHOO_TOKEN_ENDPOINT = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_METADATA_URL = (
    "https://api.login.yahoo.com/.well-known/openid-configuration"
)
CALLBACK_PATH = "/oauth2callback"
YAHOO_COMPATIBILITY_PROMPT = "consent"
RESPONSE_TYPE = "code"
GRANT_TYPE = "authorization_code"
STATE_HANDLING_DELEGATED = "delegated_to_streamlit_authlib"
NONCE_HANDLING_DELEGATED = "delegated_to_streamlit_authlib"
PKCE_STATUS_NOT_ASSERTED = "not_asserted"
REDIRECT_URI_STATUS_ACCEPTED = "accepted"

_DEVELOPMENT_ENVIRONMENTS = frozenset(
    {"development", "dev", "local"}
)
_PRODUCTION_ENVIRONMENTS = frozenset(
    {"production", "prod"}
)
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]"}
)


class OidcRedirectConfigurationError(RuntimeError):
    """Raised when production Yahoo/OIDC callback configuration is invalid."""


@dataclass(frozen=True, slots=True)
class OidcAuthorizationConfig:
    """Validated static OIDC settings. State and nonce are not stored here."""

    redirect_uri: str
    token_exchange_redirect_uri: str
    client_id: str
    response_type: str
    scope: str
    prompt: str
    state_handling: str
    nonce_handling: str
    pkce_status: str
    redirect_uri_status: str
    runtime: OidcRuntime
    yahoo_prompt_is_compatibility_override: bool
    authorization_endpoint: str
    token_endpoint: str
    token_exchange: dict[str, str]
    client_id_fingerprint: str


def classify_oidc_runtime(
    environ: Mapping[str, str] | None = None,
) -> OidcRuntime:
    """Return the OIDC runtime. Conflicting explicit envs fail closed."""
    values = _environ(environ)
    oidc_runtime = _explicit_runtime(values.get("OIDC_ENV"))
    auction_runtime = _explicit_runtime(values.get("AUCTION_ENV"))

    if (
        oidc_runtime is not None
        and auction_runtime is not None
        and oidc_runtime != auction_runtime
    ):
        raise OidcRedirectConfigurationError(
            "OIDC_ENV conflicts with AUCTION_ENV. "
            "Set both to the same runtime or omit one of them."
        )

    explicit = oidc_runtime or auction_runtime
    if explicit is not None:
        return explicit

    if _truthy(values.get("OIDC_ALLOW_LOCAL_REDIRECT")):
        return "development"

    return "production"


def resolve_oidc_redirect_uri(
    *,
    environ: Mapping[str, str] | None = None,
    secrets_auth: Mapping[str, Any] | None = None,
    request_host: str | None = None,
) -> str:
    """Return the Streamlit callback after matching any explicit env URI."""
    del request_host
    values = _environ(environ)
    runtime = classify_oidc_runtime(values)
    canonical = str(
        values.get("OIDC_REDIRECT_URI")
        or ""
    ).strip()
    legacy_yahoo_uri = str(
        values.get("YAHOO_REDIRECT_URI")
        or ""
    ).strip()
    secret_uri = _secret_text(secrets_auth, "redirect_uri")

    if runtime == "production":
        if not canonical:
            raise OidcRedirectConfigurationError(
                "OIDC_REDIRECT_URI is required for production Yahoo OAuth. "
                "Set the canonical HTTPS callback, for example "
                "https://<canonical-streamlit-host>/oauth2callback."
            )

        if (
            legacy_yahoo_uri
            and legacy_yahoo_uri != canonical
        ):
            raise OidcRedirectConfigurationError(
                "YAHOO_REDIRECT_URI conflicts with OIDC_REDIRECT_URI. "
                "OIDC_REDIRECT_URI is the canonical production callback."
            )

        if not secret_uri:
            raise OidcRedirectConfigurationError(
                "Streamlit [auth].redirect_uri is required and must match "
                "OIDC_REDIRECT_URI."
            )

        if canonical != secret_uri:
            raise OidcRedirectConfigurationError(
                "Streamlit [auth].redirect_uri does not match "
                "OIDC_REDIRECT_URI. Update the Streamlit secret to the "
                "canonical HTTPS callback instead of repairing it at runtime."
            )

        return _validate_redirect_uri(secret_uri, runtime)

    if runtime == "development":
        if (
            canonical
            and legacy_yahoo_uri
            and canonical != legacy_yahoo_uri
        ):
            raise OidcRedirectConfigurationError(
                "YAHOO_REDIRECT_URI conflicts with OIDC_REDIRECT_URI."
            )

        environment_uri = canonical or legacy_yahoo_uri
        configured = secret_uri or environment_uri

        if not configured:
            raise OidcRedirectConfigurationError(
                "Development Yahoo OAuth requires [auth].redirect_uri."
            )

        if (
            environment_uri
            and secret_uri
            and environment_uri != secret_uri
        ):
            raise OidcRedirectConfigurationError(
                "Streamlit [auth].redirect_uri does not match "
                "OIDC_REDIRECT_URI."
            )

        return _validate_redirect_uri(configured, runtime)

    unreachable: Any = runtime
    raise OidcRedirectConfigurationError(
        f"Unhandled OIDC runtime: {unreachable}."
    )


def validate_streamlit_oidc_configuration(
    *,
    environ: Mapping[str, str] | None = None,
    secrets_auth: Mapping[str, Any] | None = None,
    request_host: str | None = None,
) -> OidcAuthorizationConfig:
    """Validate Streamlit OIDC secrets without mutating them."""
    auth = _mapping_as_dict(secrets_auth)
    redirect_uri = resolve_oidc_redirect_uri(
        environ=environ,
        secrets_auth=auth,
        request_host=request_host,
    )
    client_id = _secret_text(auth, "client_id")
    if not client_id:
        raise OidcRedirectConfigurationError(
            "OIDC client_id is required for Yahoo authorization."
        )

    metadata_url = _secret_text(auth, "server_metadata_url")
    runtime = classify_oidc_runtime(environ)
    if runtime == "production" and metadata_url != YAHOO_METADATA_URL:
        raise OidcRedirectConfigurationError(
            "Production Yahoo OAuth requires server_metadata_url "
            f"{YAHOO_METADATA_URL}."
        )
    yahoo = _is_yahoo_metadata(metadata_url)
    client_kwargs = _mapping_as_dict(auth.get("client_kwargs"))
    scope = _normalized_scope(client_kwargs.get("scope"))
    response_type = str(
        client_kwargs.get("response_type") or ""
    ).strip()
    prompt = str(client_kwargs.get("prompt") or "").strip()

    if yahoo:
        if "openid" not in scope.split():
            raise OidcRedirectConfigurationError(
                "Yahoo OpenID Connect requires scope=openid in "
                "[auth.client_kwargs]."
            )
        if response_type != RESPONSE_TYPE:
            raise OidcRedirectConfigurationError(
                "Yahoo authorization requires "
                "[auth.client_kwargs] response_type=code."
            )
        if prompt != YAHOO_COMPATIBILITY_PROMPT:
            raise OidcRedirectConfigurationError(
                "Yahoo compatibility override requires "
                "[auth.client_kwargs] prompt=consent. "
                "Streamlit's default prompt=select_account is not used."
            )

    token_exchange = {
        "grant_type": GRANT_TYPE,
        "redirect_uri": redirect_uri,
    }
    return OidcAuthorizationConfig(
        redirect_uri=redirect_uri,
        token_exchange_redirect_uri=redirect_uri,
        client_id=client_id,
        response_type=RESPONSE_TYPE if yahoo else response_type,
        scope=scope,
        prompt=prompt,
        state_handling=STATE_HANDLING_DELEGATED,
        nonce_handling=NONCE_HANDLING_DELEGATED,
        pkce_status=PKCE_STATUS_NOT_ASSERTED,
        redirect_uri_status=REDIRECT_URI_STATUS_ACCEPTED,
        runtime=runtime,
        yahoo_prompt_is_compatibility_override=yahoo
        and prompt == YAHOO_COMPATIBILITY_PROMPT,
        authorization_endpoint=(
            YAHOO_AUTHORIZATION_ENDPOINT if yahoo else ""
        ),
        token_endpoint=YAHOO_TOKEN_ENDPOINT if yahoo else "",
        token_exchange=token_exchange,
        client_id_fingerprint=_client_id_fingerprint(client_id),
    )


def oidc_authorization_diagnostic(
    config: OidcAuthorizationConfig,
) -> dict[str, str]:
    """Return a non-secret summary of the configured authorization request."""
    host = urlparse(config.authorization_endpoint).hostname or ""
    return {
        "authorization_endpoint_host": host,
        "redirect_uri": config.redirect_uri,
        "redirect_uri_status": config.redirect_uri_status,
        "runtime": config.runtime,
        "response_type": config.response_type,
        "scope": config.scope,
        "STATE_HANDLING": config.state_handling,
        "NONCE_HANDLING": config.nonce_handling,
        "PKCE_status": config.pkce_status,
        "client_id_fingerprint": config.client_id_fingerprint,
        "prompt": config.prompt,
        "token_exchange_grant_type": config.token_exchange["grant_type"],
        "token_exchange_redirect_match": (
            "true"
            if (
                config.token_exchange["redirect_uri"]
                == config.redirect_uri
            )
            else "false"
        ),
    }


def _environ(
    environ: Mapping[str, str] | None,
) -> Mapping[str, str]:
    """Return the provided mapping or the process environment."""
    if environ is None:
        return os.environ
    return environ


def _truthy(value: str | None) -> bool:
    """Return whether a configuration flag is enabled."""
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _explicit_runtime(value: str | None) -> OidcRuntime | None:
    """Classify one explicit environment value, or None if unset."""
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in _DEVELOPMENT_ENVIRONMENTS:
        return "development"
    if text in _PRODUCTION_ENVIRONMENTS:
        return "production"
    raise OidcRedirectConfigurationError(
        "OIDC environment must be production or development."
    )


def _secret_text(
    secrets_auth: Mapping[str, Any] | None,
    key: str,
) -> str:
    """Read one non-empty auth-section string."""
    if not secrets_auth:
        return ""
    return str(secrets_auth.get(key) or "").strip()


def _mapping_as_dict(value: Any) -> dict[str, Any]:
    """Copy a mapping, including nested Streamlit AttrDict sections."""
    if not isinstance(value, Mapping):
        return {}
    copied: dict[str, Any] = {}
    for key, nested in value.items():
        if isinstance(nested, Mapping):
            copied[str(key)] = _mapping_as_dict(nested)
        else:
            copied[str(key)] = nested
    return copied


def _is_yahoo_metadata(metadata_url: str) -> bool:
    """Return whether the configured OIDC provider is Yahoo discovery."""
    return metadata_url == YAHOO_METADATA_URL


def _normalized_scope(scope: Any) -> str:
    """Return a space-delimited scope string."""
    if isinstance(scope, (list, tuple)):
        tokens = [str(item).strip() for item in scope if str(item).strip()]
    else:
        tokens = [
            token
            for token in str(scope or "").split()
            if token
        ]
    if not tokens:
        return ""
    return " ".join(tokens)


def _client_id_fingerprint(client_id: str) -> str:
    """Return a short non-reversible client-ID fingerprint."""
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    return digest[:8]


def _validate_redirect_uri(value: str, runtime: OidcRuntime) -> str:
    """Reject localhost, loopback, HTTP, and Vercel callbacks in production."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    path = parsed.path or ""
    local_ok = _local_redirect_allowed(runtime)

    if parsed.scheme not in {"http", "https"} or not host:
        raise OidcRedirectConfigurationError(
            "OIDC redirect_uri must be an absolute http(s) URL "
            f"ending in {CALLBACK_PATH}."
        )
    if parsed.query or parsed.fragment:
        raise OidcRedirectConfigurationError(
            "OIDC redirect_uri must not include a query string or fragment."
        )
    if parsed.username or parsed.password:
        raise OidcRedirectConfigurationError(
            "OIDC redirect_uri must not include a username or password."
        )
    if path != CALLBACK_PATH:
        raise OidcRedirectConfigurationError(
            f"OIDC redirect_uri path must be {CALLBACK_PATH}."
        )
    if _host_is_loopback(host) or host.startswith("127."):
        if not local_ok:
            raise OidcRedirectConfigurationError(
                "Production Yahoo OAuth cannot use a loopback callback."
            )
    if host == "vercel.app" or host.endswith(".vercel.app"):
        raise OidcRedirectConfigurationError(
            "Yahoo OAuth cannot use a vercel hostname as redirect_uri."
        )
    if runtime == "production" and parsed.scheme != "https":
        raise OidcRedirectConfigurationError(
            "Production Yahoo OAuth redirect_uri must use HTTPS."
        )
    if runtime == "development":
        return value
    if runtime == "production":
        return value
    unreachable: Any = runtime
    raise OidcRedirectConfigurationError(
        f"Unhandled OIDC runtime: {unreachable}."
    )


def _local_redirect_allowed(runtime: OidcRuntime) -> bool:
    """Return whether a loopback callback is permitted."""
    if runtime == "development":
        return True
    if runtime == "production":
        return False
    unreachable: Any = runtime
    raise OidcRedirectConfigurationError(
        f"Unhandled OIDC runtime: {unreachable}."
    )


def _host_is_loopback(host: str) -> bool:
    """Return whether a hostname is localhost or an equivalent loopback IP."""
    folded = host.casefold().rstrip(".")
    if folded in _LOCAL_HOSTS or folded.endswith(".localhost"):
        return True
    address = _parse_ip_literal(folded)
    if address is None:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def _parse_ip_literal(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a hostname as an IP, including alternate IPv4 encodings."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return _parse_alternate_ipv4(host)


def _parse_alternate_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Parse decimal, hex, or dotted-octal IPv4 loopback encodings."""
    if host.startswith("0x"):
        try:
            value = int(host, 16)
        except ValueError:
            return None
        if 0 <= value <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(value)
        return None
    if host.isdigit():
        value = int(host, 10)
        if 0 <= value <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(value)
        return None
    parts = host.split(".")
    if len(parts) != 4:
        return None
    try:
        octets = [_parse_ipv4_component(part) for part in parts]
    except ValueError:
        return None
    if any(octet > 255 for octet in octets):
        return None
    return ipaddress.IPv4Address(bytes(octets))


def _parse_ipv4_component(part: str) -> int:
    """Parse one IPv4 dotted component as decimal, octal, or hex."""
    if not part:
        raise ValueError("empty IPv4 component")
    if part.startswith("0x"):
        return int(part, 16)
    if (
        len(part) > 1
        and part.startswith("0")
        and all(character in "01234567" for character in part)
    ):
        return int(part, 8)
    return int(part, 10)
