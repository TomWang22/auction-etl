"""Tests for the authenticated Buyee HTTPS raw-page adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts.buyee_http_session import (
    BuyeeHttpResult,
    BuyeeHttpState,
)
from scripts.crawl_buyee_http import (
    BuyeeHttpCrawlError,
    crawl_closed_watchlist,
    persist_raw_page,
    sha256_text,
)


def authenticated_result(
    *,
    body: str = (
        '<a href="/item/jdirectitems/auction/abc123">item</a>'
    ),
    auction_links: tuple[str, ...] = (
        "https://buyee.jp/item/jdirectitems/auction/abc123",
    ),
) -> BuyeeHttpResult:
    """Return a canonical authenticated Buyee HTTPS result."""
    return BuyeeHttpResult(
        state=BuyeeHttpState.AUTHENTICATED,
        status_code=200,
        final_url=(
            "https://buyee.jp/myorders/watchlist/closed"
        ),
        body=body,
        auction_links=auction_links,
    )


def test_sha256_text_is_deterministic() -> None:
    """Hash raw HTML deterministically."""
    assert sha256_text("hello") == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e"
        "1b161e5c1fa7425e73043362938b9824"
    )


def test_persist_raw_page_creates_expected_contract() -> None:
    """Persist the same core contract consumed by parse_latest."""
    session = MagicMock()

    job = SimpleNamespace(
        id=41,
        status="running",
    )

    raw = SimpleNamespace(
        id=73,
        url="https://buyee.jp/myorders/watchlist/closed",
        http_status=200,
        sha256="digest",
    )

    created: list[object] = []

    def add(value: object) -> None:
        created.append(value)

        if len(created) == 1:
            value.id = job.id

        if len(created) == 2:
            value.id = raw.id

    session.add.side_effect = add

    persisted_job, persisted_raw = persist_raw_page(
        session=session,
        url="https://buyee.jp/myorders/watchlist/closed",
        status_code=200,
        html="<html>watchlist</html>",
    )

    assert persisted_job.status == "finished"
    assert persisted_raw.source == "buyee"
    assert persisted_raw.crawl_job_id == 41
    assert persisted_raw.http_status == 200
    assert persisted_raw.html == "<html>watchlist</html>"
    assert len(persisted_raw.sha256) == 64
    assert session.flush.call_count == 2
    session.commit.assert_called_once_with()


def test_crawl_closed_watchlist_persists_authenticated_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated HTTPS results enter the raw-page pipeline."""
    result = authenticated_result()

    monkeypatch.setattr(
        "scripts.crawl_buyee_http.fetch_closed_watchlist",
        lambda **kwargs: result,
    )

    expected = (
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
    )

    persist = MagicMock(
        return_value=expected
    )

    monkeypatch.setattr(
        "scripts.crawl_buyee_http.persist_raw_page",
        persist,
    )

    session = MagicMock()

    actual = crawl_closed_watchlist(
        session=session,
        state_file=Path("/private/state.json"),
    )

    assert actual == expected

    persist.assert_called_once_with(
        session=session,
        url=result.final_url,
        status_code=200,
        html=result.body,
    )


@pytest.mark.parametrize(
    "result",
    (
        BuyeeHttpResult(
            state=BuyeeHttpState.AUTHENTICATION_REQUIRED,
            status_code=200,
            final_url="https://buyee.jp/signup/login",
            body="Login",
            auction_links=(),
        ),
        BuyeeHttpResult(
            state=BuyeeHttpState.ACCESS_BLOCKED,
            status_code=403,
            final_url="https://buyee.jp/",
            body="Forbidden",
            auction_links=(),
        ),
    ),
)
def test_crawl_closed_watchlist_rejects_unusable_session(
    monkeypatch: pytest.MonkeyPatch,
    result: BuyeeHttpResult,
) -> None:
    """Do not write unauthenticated or blocked pages to raw storage."""
    monkeypatch.setattr(
        "scripts.crawl_buyee_http.fetch_closed_watchlist",
        lambda **kwargs: result,
    )

    with pytest.raises(
        BuyeeHttpCrawlError,
        match="not authenticated",
    ):
        crawl_closed_watchlist(
            session=MagicMock(),
            state_file=Path("/private/state.json"),
        )


def test_crawl_closed_watchlist_rejects_zero_auction_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated-looking empty watchlist is not a valid crawl."""
    monkeypatch.setattr(
        "scripts.crawl_buyee_http.fetch_closed_watchlist",
        lambda **kwargs: authenticated_result(
            auction_links=(),
        ),
    )

    with pytest.raises(
        BuyeeHttpCrawlError,
        match="zero auction links",
    ):
        crawl_closed_watchlist(
            session=MagicMock(),
            state_file=Path("/private/state.json"),
        )
