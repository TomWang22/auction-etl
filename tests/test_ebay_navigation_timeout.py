"""Regression tests for resilient eBay result-page navigation."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import crawl_ebay_sources as crawler


@pytest.fixture(autouse=True)
def skip_ebay_home_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit tests stub the home tab; live crawls still load ebay.com first."""
    monkeypatch.setattr(
        crawler,
        "prepare_ebay_search_tab",
        lambda *args, **kwargs: None,
    )


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


def test_aborted_navigation_returns_to_result_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An interruption abort is the same recovery path as a timeout."""

    class AbortedPage:
        def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
            del url, wait_until, timeout
            raise crawler.PlaywrightError(
                "Page.goto: net::ERR_ABORTED"
            )

    response = crawler.navigate_for_results(
        AbortedPage(),
        "https://www.ebay.com/sch/i.html",
        page_number=1,
    )

    assert response is None
    assert "navigation_aborted_nonfatal page=1" in capsys.readouterr().out


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
    """Akamai 403 on page 1 is a one-shot cookie stamp, not the end."""

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
        url = "https://www.ebay.com/sch/i.html"
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

    url = "https://www.ebay.com/sch/i.html"
    _page, response, html, status, count, _context = (
        crawler.load_ebay_results_page(
            Page(),
            url,
            page_number=1,
            wait_seconds=1,
        )
    )

    assert gotos == [url, url]
    assert response is not None
    assert response.status == 200
    assert status == 200
    assert count == 1
    assert "/itm/123456789012" in html


def test_empty_200_error_page_continues_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Akamai can stamp 'Error Page | eBay' with HTTP 200 and zero cards."""

    htmls = [
        "<html><body>Error Page | eBay</body></html>",
        (
            "<html><body>"
            '<a href="https://www.ebay.com/itm/123456789012">item</a>'
            "</body></html>"
        ),
    ]
    responses = [
        FakeResponse(200),
        FakeResponse(200),
    ]
    gotos: list[str] = []

    class Page:
        url = "https://www.ebay.com/sch/i.html"
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

        def title(self) -> str:
            return "Error Page | eBay"

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html"
    _page, response, html, status, count, _context = (
        crawler.load_ebay_results_page(
            Page(),
            url,
            page_number=1,
            wait_seconds=1,
        )
    )

    assert gotos == [url, url]
    assert response is not None
    assert status == 200
    assert count == 1
    assert "/itm/123456789012" in html


def test_page_one_still_blocked_returns_to_homepage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leave the orange jacket so the next artist search is not a cold error URL."""
    homes: list[int | None] = []

    def record_home(*args, **kwargs) -> None:
        del args
        homes.append(kwargs.get("page_number"))

    monkeypatch.setattr(
        crawler,
        "prepare_ebay_search_tab",
        record_home,
    )
    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    class Page:
        url = "https://www.ebay.com/sch/i.html"

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
            return FakeResponse(403)

        def content(self) -> str:
            return "<html><body>Error Page | eBay</body></html>"

        def title(self) -> str:
            return "Error Page | eBay"

    crawler.load_ebay_results_page(
        Page(),
        "https://www.ebay.com/sch/i.html",
        page_number=1,
        wait_seconds=1,
    )

    assert homes == [1, 1, 1]


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
    _page, _response, _html, status, count, _context = (
        crawler.load_ebay_results_page(
            Page(),
            url,
            page_number=1,
            wait_seconds=1,
        )
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
    _page, _response, _html, status, count, _context = (
        crawler.load_ebay_results_page(
            Page(),
            url,
            page_number=2,
            wait_seconds=1,
        )
    )

    assert gotos == [url]
    assert status == 403
    assert count == 0


def test_empty_block_continue_replaces_poisoned_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 cookie stamp must not follow onto the continuation GET."""

    class Page:
        def __init__(
            self,
            html: str,
            status: int,
        ) -> None:
            self._html = html
            self._status = status
            self.closed = False
            self.url = "https://www.ebay.com/sch/i.html"

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
    replaced: list[str] = []
    poisoned_pages: list[str] = []

    class PoisonedContext:
        def new_page(self) -> Page:
            poisoned_pages.append("new")
            raise AssertionError(
                "continuation must not open a tab on the poisoned context"
            )

        def close(self) -> None:
            replaced.append("closed")

    class FreshContext:
        def new_page(self) -> Page:
            replaced.append("new")
            return second

    class Runtime:
        def replace_context(self, profile: str) -> FreshContext:
            assert profile == "ebay-public"
            replaced.append(profile)
            return FreshContext()

    monkeypatch.setattr(
        crawler,
        "browser",
        Runtime(),
    )
    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    url = "https://www.ebay.com/sch/i.html"
    page, response, html, status, count, context = (
        crawler.load_ebay_results_page(
            first,
            url,
            page_number=1,
            wait_seconds=1,
            context=PoisonedContext(),
            profile="ebay-public",
        )
    )

    assert poisoned_pages == []
    assert replaced == ["ebay-public", "new"]
    assert first.closed is True
    assert isinstance(context, FreshContext)
    assert page is second
    assert response is not None
    assert status == 200
    assert count == 1
    assert "/itm/123456789012" in html


def test_later_page_clicks_next_instead_of_opening_pgn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page 2 follows the results Next control. A direct _pgn URL is the orange jacket."""

    class NextLink:
        def __init__(self, page: "ResultsPage") -> None:
            self.page = page
            self.first = self

        def count(self) -> int:
            return 1

        def get_attribute(self, name: str) -> str:
            del name
            return "https://www.ebay.com/sch/i.html?_pgn=2"

        def click(self, timeout: int) -> None:
            del timeout
            self.page.clicked = True
            self.page.html = (
                "<a href='/itm/123456789012'>kept</a>"
            )

    class ResultsPage:
        def __init__(self) -> None:
            self.clicked = False
            self.gotos: list[str] = []
            self.html = "<a class='pagination__next' href='?_pgn=2'></a>"
            self.url = "https://www.ebay.com/sch/i.html"

        def locator(self, selector: str) -> NextLink:
            del selector
            return NextLink(self)

        def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> FakeResponse:
            del wait_until, timeout
            self.gotos.append(url)
            return FakeResponse(403)

        def content(self) -> str:
            return self.html

        def title(self) -> str:
            return "Anita Mui for sale | eBay"

    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )
    page = ResultsPage()
    loaded, _response, html, status, count, _context = (
        crawler.load_ebay_results_page(
            page,
            "https://www.ebay.com/sch/i.html?_nkw=anita+mui&_pgn=2",
            page_number=2,
            wait_seconds=1,
            context=object(),
            profile="ebay-public",
        )
    )

    assert loaded is page
    assert page.clicked is True
    assert page.gotos == []
    assert count == 1
    assert status is None
    assert "/itm/123456789012" in html


def test_later_page_error_does_not_deep_link_after_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teresa Teng _pgn=3 on a fresh jar is the orange jacket error page."""

    class Page:
        def __init__(self) -> None:
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
            return FakeResponse(403)

        def content(self) -> str:
            return "<html><body>Error Page | eBay</body></html>"

        def title(self) -> str:
            return "Error Page | eBay"

        def close(self) -> None:
            self.closed = True

    class Runtime:
        def replace_context(self, profile: str) -> None:
            raise AssertionError(
                "later pages must not rebuild Chrome to retry _pgn"
            )

    monkeypatch.setattr(
        crawler,
        "browser",
        Runtime(),
    )
    monkeypatch.setattr(
        crawler,
        "wait_for_results",
        lambda *args, **kwargs: None,
    )

    first = Page()
    url = "https://www.ebay.com/sch/i.html?_pgn=3"
    page, _response, _html, status, count, _context = (
        crawler.load_ebay_results_page(
            first,
            url,
            page_number=3,
            wait_seconds=1,
            context=object(),
            profile="ebay-public",
        )
    )

    assert page is first
    assert first.closed is False
    assert status == 403
    assert count == 0


def test_empty_block_continue_uses_replace_context() -> None:
    """The continue path must rebuild the browser context from disk."""
    source = inspect.getsource(
        crawler.load_ebay_results_page
    )

    replace_at = source.index("replace_context(")
    new_page_at = source.index("context.new_page()")

    assert replace_at < new_page_at
    assert "EBAY_CRAWL_PHASE=context_replace" in source
    assert "EBAY_CRAWL_PHASE=access_stop" in source
    assert "page_number == 1" in source
    assert "page_number != 1" in source
    first_home = source.index("prepare_ebay_search_tab(")
    first_nav = source.index("navigate_for_results(")
    assert first_home < first_nav
    assert "reuse_browser=1" in (
        Path(__file__).resolve().parents[1]
        / "auction_etl"
        / "browser"
        / "manager.py"
    ).read_text(encoding="utf-8")


def test_pagination_keeps_the_same_results_tab() -> None:
    """Later sold-search pages stay on the live tab; a new tab plus _pgn is the orange jacket."""
    source = inspect.getsource(
        crawler.crawl_source
    )
    loop_at = source.index(
        "for page_number in range("
    )

    assert source.find(
        "context.new_page()",
        loop_at,
    ) == -1
    assert "previous.close()" not in source[loop_at:]


def test_crawl_source_keeps_replaced_context() -> None:
    """Pagination after a 403 continue must use the rebuilt context."""
    source = inspect.getsource(
        crawler.crawl_source
    )

    assert (
        "page, response, html, status, count, context ="
        in source
    )
    assert "profile=source.profile" in source
    assert "persist_ebay_storage_state(context)" in source
