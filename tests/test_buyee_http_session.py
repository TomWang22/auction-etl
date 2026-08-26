"""Tests for authenticated Buyee HTTPS access."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.buyee_http_session import (
    BuyeeHttpSessionError,
    BuyeeHttpState,
    DEFAULT_WATCHLIST_URL,
    classify_response,
    extract_auction_links,
    fetch_closed_watchlist,
    is_buyee_domain,
    load_buyee_cookie_jar,
)


def write_storage_state(
    path: Path,
    *,
    cookies: list[dict[str, object]],
) -> None:
    """Write a minimal Playwright-compatible storage-state file."""
    path.write_text(
        json.dumps(
            {
                "cookies": cookies,
                "origins": [],
            }
        ),
        encoding="utf-8",
    )


def buyee_cookie() -> dict[str, object]:
    """Return one valid Buyee storage-state cookie."""
    return {
        "name": "session",
        "value": "private-value",
        "domain": ".buyee.jp",
        "path": "/",
        "expires": -1,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }


@pytest.mark.parametrize(
    ("domain", "expected"),
    (
        ("buyee.jp", True),
        (".buyee.jp", True),
        ("www.buyee.jp", True),
        (".www.buyee.jp", True),
        ("example.com", False),
        ("notbuyee.jp", False),
    ),
)
def test_is_buyee_domain(
    domain: str,
    expected: bool,
) -> None:
    """Recognize only Buyee cookie domains."""
    assert is_buyee_domain(domain) is expected


def test_default_watchlist_url_is_raw_https() -> None:
    """Keep Markdown link syntax out of application URLs."""
    assert DEFAULT_WATCHLIST_URL == (
        "https://buyee.jp/myorders/watchlist/closed"
    )

    assert "[" not in DEFAULT_WATCHLIST_URL
    assert "](" not in DEFAULT_WATCHLIST_URL


@pytest.mark.parametrize(
    ("status_code", "final_url", "body", "expected"),
    (
        (
            403,
            "https://buyee.jp/",
            "Forbidden",
            BuyeeHttpState.ACCESS_BLOCKED,
        ),
        (
            200,
            "https://buyee.jp/",
            "Access Denied",
            BuyeeHttpState.ACCESS_BLOCKED,
        ),
        (
            200,
            "https://buyee.jp/",
            "Site Maintenance",
            BuyeeHttpState.MAINTENANCE,
        ),
        (
            200,
            "https://buyee.jp/signup/login",
            "Login",
            BuyeeHttpState.AUTHENTICATION_REQUIRED,
        ),
        (
            200,
            "https://buyee.jp/myorders/watchlist/closed",
            "Watchlist",
            BuyeeHttpState.AUTHENTICATED,
        ),
        (
            200,
            "https://buyee.jp/",
            "Home",
            BuyeeHttpState.INDETERMINATE,
        ),
    ),
)
def test_classify_response(
    status_code: int,
    final_url: str,
    body: str,
    expected: BuyeeHttpState,
) -> None:
    """Classify canonical Buyee response states."""
    assert (
        classify_response(
            status_code=status_code,
            final_url=final_url,
            body=body,
        )
        is expected
    )


def test_access_block_has_priority_over_other_states() -> None:
    """An explicit block response must not look authenticated."""
    state = classify_response(
        status_code=403,
        final_url=(
            "https://buyee.jp/myorders/watchlist/closed"
        ),
        body="Site Maintenance",
    )

    assert state is BuyeeHttpState.ACCESS_BLOCKED


def test_maintenance_has_priority_over_authenticated_url() -> None:
    """A maintenance page must not look authenticated."""
    state = classify_response(
        status_code=200,
        final_url=(
            "https://buyee.jp/myorders/watchlist/closed"
        ),
        body="Currently unavailable due to maintenance",
    )

    assert state is BuyeeHttpState.MAINTENANCE


def test_extract_auction_links_normalizes_and_deduplicates() -> None:
    """Extract stable absolute auction URLs."""
    body = """
    <a href="/item/jdirectitems/auction/abc123">one</a>
    <a href="/item/jdirectitems/auction/abc123">duplicate</a>
    <a href="https://buyee.jp/item/jdirectitems/auction/xyz789">two</a>
    """

    assert extract_auction_links(body) == (
        "https://buyee.jp/item/jdirectitems/auction/abc123",
        "https://buyee.jp/item/jdirectitems/auction/xyz789",
    )


def test_extract_auction_links_ignores_unrelated_links() -> None:
    """Ignore links outside the Buyee auction-detail path."""
    body = """
    <a href="/myorders/watchlist/closed">watchlist</a>
    <a href="https://example.com/">other</a>
    """

    assert extract_auction_links(body) == ()


def test_load_cookie_jar_filters_non_buyee_domains(
    tmp_path: Path,
) -> None:
    """Load only Buyee cookies."""
    path = tmp_path / "state.json"

    write_storage_state(
        path,
        cookies=[
            buyee_cookie(),
            {
                "name": "other",
                "value": "ignored",
                "domain": ".example.com",
                "path": "/",
                "expires": -1,
                "secure": True,
            },
        ],
    )

    jar = load_buyee_cookie_jar(path)

    cookies = list(jar)

    assert len(cookies) == 1
    assert cookies[0].name == "session"
    assert cookies[0].domain == ".buyee.jp"


def test_load_cookie_jar_rejects_missing_file(
    tmp_path: Path,
) -> None:
    """Reject a missing storage-state file."""
    path = tmp_path / "missing.json"

    with pytest.raises(
        BuyeeHttpSessionError,
        match="missing",
    ):
        load_buyee_cookie_jar(path)


def test_load_cookie_jar_rejects_invalid_json(
    tmp_path: Path,
) -> None:
    """Reject malformed JSON."""
    path = tmp_path / "state.json"
    path.write_text(
        "{not-json",
        encoding="utf-8",
    )

    with pytest.raises(
        BuyeeHttpSessionError,
        match="could not be read",
    ):
        load_buyee_cookie_jar(path)


def test_load_cookie_jar_rejects_invalid_cookie_payload(
    tmp_path: Path,
) -> None:
    """Reject a non-list cookies field."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "cookies": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        BuyeeHttpSessionError,
        match="cookies payload is invalid",
    ):
        load_buyee_cookie_jar(path)


def test_load_cookie_jar_rejects_state_without_buyee_cookies(
    tmp_path: Path,
) -> None:
    """Reject storage state without a reusable Buyee session."""
    path = tmp_path / "state.json"

    write_storage_state(
        path,
        cookies=[
            {
                "name": "other",
                "value": "ignored",
                "domain": ".example.com",
                "path": "/",
                "expires": -1,
                "secure": True,
            }
        ],
    )

    with pytest.raises(
        BuyeeHttpSessionError,
        match="no Buyee cookies",
    ):
        load_buyee_cookie_jar(path)


def test_fetch_closed_watchlist_returns_authenticated_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build an authenticated result from a successful HTTPS response."""
    path = tmp_path / "state.json"

    write_storage_state(
        path,
        cookies=[
            buyee_cookie(),
        ],
    )

    response = MagicMock()
    response.status = 200
    response.geturl.return_value = (
        "https://buyee.jp/myorders/watchlist/closed"
    )
    response.read.return_value = (
        b'<a href="/item/jdirectitems/auction/abc123">item</a>'
    )

    context_manager = MagicMock()
    context_manager.__enter__.return_value = response

    opener = MagicMock()
    opener.open.return_value = context_manager

    monkeypatch.setattr(
        "scripts.buyee_http_session.urllib.request.build_opener",
        lambda *args: opener,
    )

    result = fetch_closed_watchlist(
        storage_state_path=path,
    )

    assert result.state is BuyeeHttpState.AUTHENTICATED
    assert result.status_code == 200
    assert result.final_url == (
        "https://buyee.jp/myorders/watchlist/closed"
    )
    assert result.auction_links == (
        "https://buyee.jp/item/jdirectitems/auction/abc123",
    )


def test_fetch_closed_watchlist_classifies_http_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classify an HTTP error response instead of crashing."""
    path = tmp_path / "state.json"

    write_storage_state(
        path,
        cookies=[
            buyee_cookie(),
        ],
    )

    error = urllib.error.HTTPError(
        url="https://buyee.jp/",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,
    )

    error.read = MagicMock(
        return_value=b"403 Forbidden"
    )

    opener = MagicMock()
    opener.open.side_effect = error

    monkeypatch.setattr(
        "scripts.buyee_http_session.urllib.request.build_opener",
        lambda *args: opener,
    )

    result = fetch_closed_watchlist(
        storage_state_path=path,
    )

    assert result.state is BuyeeHttpState.ACCESS_BLOCKED
    assert result.status_code == 403


def test_fetch_closed_watchlist_wraps_network_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose transport failures through the stable session exception."""
    path = tmp_path / "state.json"

    write_storage_state(
        path,
        cookies=[
            buyee_cookie(),
        ],
    )

    opener = MagicMock()
    opener.open.side_effect = urllib.error.URLError(
        "network unavailable"
    )

    monkeypatch.setattr(
        "scripts.buyee_http_session.urllib.request.build_opener",
        lambda *args: opener,
    )

    with pytest.raises(
        BuyeeHttpSessionError,
        match="HTTPS request failed",
    ):
        fetch_closed_watchlist(
            storage_state_path=path,
        )
