"""Regression tests for resilient eBay result-page navigation."""

from __future__ import annotations

import inspect

import pytest

from scripts import crawl_ebay_sources as crawler


class FakeResponse:
    """Minimal Playwright response substitute."""

    def __init__(self, status: int = 200) -> None:
        self.status = status


class SuccessfulPage:
    """Record the navigation contract."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                str,
                str,
                int,
            ]
        ] = []

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> FakeResponse:
        self.calls.append(
            (
                url,
                wait_until,
                timeout,
            )
        )

        return FakeResponse()


class TimeoutPage:
    """Simulate a Playwright navigation timeout."""

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        del url
        del wait_until
        del timeout

        raise crawler.PlaywrightTimeoutError(
            "synthetic navigation timeout"
        )


class FailurePage:
    """Simulate an unrelated navigation failure."""

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        del url
        del wait_until
        del timeout

        raise RuntimeError(
            "synthetic non-timeout failure"
        )


def test_ebay_navigation_uses_commit_state() -> None:
    """Initial navigation waits only for browser commit."""
    page = SuccessfulPage()

    response = crawler.navigate_for_results(
        page,
        "https://www.ebay.com/sch/i.html",
        page_number=3,
    )

    assert response is not None
    assert response.status == 200

    assert page.calls == [
        (
            "https://www.ebay.com/sch/i.html",
            "commit",
            crawler.EBAY_NAVIGATION_TIMEOUT_MS,
        )
    ]


def test_ebay_navigation_timeout_is_nonfatal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A navigation timeout returns control to result validation."""
    response = crawler.navigate_for_results(
        TimeoutPage(),
        "https://www.ebay.com/sch/i.html",
        page_number=1,
    )

    assert response is None

    output = capsys.readouterr().out

    assert (
        "EBAY_CRAWL_PHASE="
        "navigation_timeout_nonfatal "
        "page=1"
        in output
    )


def test_non_timeout_navigation_failure_propagates() -> None:
    """Only Playwright navigation timeouts are suppressed."""
    with pytest.raises(
        RuntimeError,
        match="synthetic non-timeout failure",
    ):
        crawler.navigate_for_results(
            FailurePage(),
            "https://www.ebay.com/sch/i.html",
            page_number=1,
        )


def test_crawl_source_uses_resilient_navigation_helper() -> None:
    """The production crawl path must delegate navigation."""
    source = inspect.getsource(
        crawler.crawl_source
    )

    assert "load_ebay_results_page(" in source
    assert "page.goto(" not in source
    assert 'wait_until="domcontentloaded"' not in source


def test_empty_http_block_reloads_same_url_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Akamai 403 on a later page is a one-shot cookie stamp, not the end."""

    htmls = [
        "<html><body>Error Page | eBay</body></html>",
        (
            "<html><body>"
            '<a href="https://www.ebay.com/itm/123456789012">item</a>'
            "</body></html>"
        ),
    ]
    responses = [
        FakeResponse(403),
        FakeResponse(200),
    ]
    gotos: list[str] = []

    class Page:
        url = "https://www.ebay.com/sch/i.html?_pgn=2"
        _html = htmls[0]

        def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> FakeResponse:
            del wait_until
            del timeout
            index = len(gotos)
            gotos.append(url)
            self._html = htmls[index]
            return responses[index]

        def content(self) -> str:
            return self._html

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html?_pgn=2"
    _page, response, html, status, count = crawler.load_ebay_results_page(
        Page(),
        url,
        page_number=2,
        wait_seconds=1,
    )

    assert gotos == [url, url]
    assert response is not None
    assert response.status == 200
    assert status == 200
    assert count == 1
    assert "/itm/123456789012" in html


def test_block_with_listings_does_not_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 that already rendered cards must not be fetched again."""

    gotos: list[str] = []

    class Page:
        url = "https://www.ebay.com/sch/i.html"
        _html = (
            "<html><body>"
            '<a href="https://www.ebay.com/itm/123456789012">item</a>'
            "</body></html>"
        )

        def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> FakeResponse:
            del wait_until
            del timeout
            gotos.append(url)
            return FakeResponse(403)

        def content(self) -> str:
            return self._html

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html"
    _page, _response, _html, status, count = crawler.load_ebay_results_page(
        Page(),
        url,
        page_number=1,
        wait_seconds=1,
    )

    assert gotos == [url]
    assert status == 403
    assert count == 1


def test_empty_block_reload_happens_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second empty 403 stays empty; do not loop."""

    gotos: list[str] = []

    class Page:
        url = "https://www.ebay.com/sch/i.html?_pgn=2"
        _html = "<html><body>Error Page | eBay</body></html>"

        def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> FakeResponse:
            del wait_until
            del timeout
            gotos.append(url)
            return FakeResponse(403)

        def content(self) -> str:
            return self._html

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html?_pgn=2"
    _page, _response, _html, status, count = crawler.load_ebay_results_page(
        Page(),
        url,
        page_number=2,
        wait_seconds=1,
    )

    assert gotos == [url, url]
    assert status == 403
    assert count == 0


def test_empty_block_continue_uses_fresh_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poisoned 403 tab must not be reused for the continuation GET."""

    class Page:
        def __init__(
            self,
            html: str,
            status: int,
        ) -> None:
            self._html = html
            self._status = status
            self.closed = False
            self.url = "https://www.ebay.com/sch/i.html?_pgn=3"

        def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> FakeResponse:
            del url
            del wait_until
            del timeout
            return FakeResponse(self._status)

        def content(self) -> str:
            return self._html

        def close(self) -> None:
            self.closed = True

        def set_default_timeout(self, value: int) -> None:
            del value

        def set_default_navigation_timeout(self, value: int) -> None:
            del value

    first = Page(
        "<html><body>Error Page | eBay</body></html>",
        403,
    )
    second = Page(
        (
            "<html><body>"
            '<a href="https://www.ebay.com/itm/123456789012">item</a>'
            "</body></html>"
        ),
        200,
    )
    created: list[str] = []

    class Context:
        def new_page(self) -> Page:
            created.append("new")
            return second

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html?_pgn=3"
    page, response, html, status, count = crawler.load_ebay_results_page(
        first,
        url,
        page_number=3,
        wait_seconds=1,
        context=Context(),
    )

    assert created == ["new"]
    assert first.closed is True
    assert page is second
    assert response is not None
    assert status == 200
    assert count == 1
    assert "/itm/123456789012" in html


def test_pagination_opens_a_fresh_tab_per_page() -> None:
    """Each _pgn must load in a new tab so a prior 403 cannot poison page 2."""
    source = inspect.getsource(
        crawler.crawl_source
    )
    loop_at = source.index(
        "for page_number in range("
    )

    assert source.find(
        "context.new_page()",
        loop_at,
    ) != -1
    assert source.find(
        "page.close()",
        loop_at,
    ) != -1
