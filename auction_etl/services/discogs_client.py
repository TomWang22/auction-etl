"""Authenticated Discogs HTTP client with pacing and no credential logs."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from auction_etl.services.discogs_identity import parse_search_hits, SearchHit


USER_AGENT = "auction-etl/1.0"
API_ROOT = "https://api.discogs.com"
DEFAULT_SECRETS = (
    Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"
)


class DiscogsRateLimitError(RuntimeError):
    """Raised after a single 429 backoff instead of retry-storming."""


class DiscogsUnavailableError(RuntimeError):
    """Raised when a page search stops because Discogs did not answer."""


class DiscogsClient:
    """Thin Discogs API wrapper. Never log Authorization headers."""

    def __init__(
        self,
        *,
        key: str | None = None,
        secret: str | None = None,
        token: str | None = None,
        min_interval_seconds: float | None = None,
        timeout: float = 12.0,
    ) -> None:
        auth = _resolve_auth(key=key, secret=secret, token=token)
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.discogs.v2.discogs+json",
        }
        if auth.get("token"):
            self._headers["Authorization"] = f"Discogs token={auth['token']}"
        elif auth.get("key") and auth.get("secret"):
            self._headers["Authorization"] = (
                f"Discogs key={auth['key']}, secret={auth['secret']}"
            )
        authenticated = "Authorization" in self._headers
        self._min_interval = (
            min_interval_seconds
            if min_interval_seconds is not None
            else (1.05 if authenticated else 3.2)
        )
        self._timeout = timeout
        self._last_request_at = 0.0
        self._retried_rate_limit = False

    @property
    def authenticated(self) -> bool:
        return "Authorization" in self._headers

    def search_releases(
        self,
        *,
        catno: str | None = None,
        artist: str | None = None,
        query: str | None = None,
        title: str | None = None,
        format_name: str | None = "Vinyl",
    ) -> tuple[SearchHit, ...]:
        params: dict[str, str] = {"type": "release"}
        if catno:
            params["catno"] = catno
        if artist:
            params["artist"] = artist
        if title:
            params["title"] = title
        if query:
            params["q"] = query
        if format_name:
            params["format"] = format_name
        # Discogs returns one page unless asked. A title search is often
        # several pages, and the later pages are the other pressings.
        params["per_page"] = "100"
        found: list[SearchHit] = []
        seen: set[int] = set()
        for page in range(1, 6):
            params["page"] = str(page)
            try:
                payload = self._get("/database/search", params=params)
            except DiscogsRateLimitError:
                if found:
                    break
                raise
            batch = parse_search_hits(payload.get("results") or [])
            added = 0
            for hit in batch:
                if hit.discogs_id in seen:
                    continue
                seen.add(hit.discogs_id)
                found.append(hit)
                added += 1
            if added == 0:
                break
            pagination = payload.get("pagination") or {}
            try:
                pages = int(pagination.get("pages") or page)
            except (TypeError, ValueError):
                pages = page
            if page >= pages:
                break
        return tuple(found)

    def get_release(self, release_id: int) -> dict[str, Any]:
        return self._get(f"/releases/{int(release_id)}")

    def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        _server_retry: bool = True,
    ) -> dict[str, Any]:
        self._wait()
        url = f"{API_ROOT}{path}"
        response = httpx.get(
            url,
            params=params,
            headers=self._headers,
            timeout=self._timeout,
        )
        self._last_request_at = time.monotonic()
        if response.status_code in {500, 502, 503} and _server_retry:
            time.sleep(2.0)
            return self._get(path, params=params, _server_retry=False)
        if response.status_code == 429:
            if self._retried_rate_limit:
                raise DiscogsRateLimitError(
                    "Discogs rate limit persisted after one backoff."
                )
            retry_after = response.headers.get("Retry-After", "60")
            try:
                delay = max(1.0, float(retry_after))
            except ValueError:
                delay = 60.0
            # A long Retry-After must not freeze the review page for a minute.
            if delay > 8:
                raise DiscogsRateLimitError(
                    "Discogs rate limit; retry after the window."
                )
            self._retried_rate_limit = True
            time.sleep(delay)
            return self._get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Discogs returned a non-object JSON payload.")
        return payload

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)


def load_discogs_credentials(
    *,
    secrets_path: Path | None = None,
) -> dict[str, str]:
    """Load key/secret/token from env or Streamlit secrets. Never log values."""
    credentials = {
        "key": os.environ.get("DISCOGS_KEY", "").strip(),
        "secret": os.environ.get("DISCOGS_SECRET", "").strip(),
        "token": os.environ.get("DISCOGS_TOKEN", "").strip(),
    }
    if any(credentials.values()):
        return {key: value for key, value in credentials.items() if value}

    path = secrets_path or DEFAULT_SECRETS
    parsed = _read_toml_section(path, "discogs")
    return {
        key: str(parsed.get(key, "")).strip()
        for key in ("key", "secret", "token")
        if str(parsed.get(key, "")).strip()
    }


def _resolve_auth(
    *,
    key: str | None,
    secret: str | None,
    token: str | None,
) -> dict[str, str]:
    if token and token.strip():
        return {"token": token.strip()}
    if key and secret and key.strip() and secret.strip():
        return {"key": key.strip(), "secret": secret.strip()}
    loaded = load_discogs_credentials()
    if loaded.get("token"):
        return {"token": loaded["token"]}
    if loaded.get("key") and loaded.get("secret"):
        return {"key": loaded["key"], "secret": loaded["secret"]}
    return {}


def _read_toml_section(path: Path, section: str) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    block = payload.get(section) or {}
    return block if isinstance(block, dict) else {}
