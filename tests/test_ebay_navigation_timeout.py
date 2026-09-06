"""Regression tests for resilient eBay result-page navigation."""

from __future__ import annotations

import inspect

import pytest

from scripts import crawl_ebay_sources as crawler


class FakeResponse:
    """Minimal Playwright response substitute."""

    status = 200


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

    assert "navigate_for_results(" in source
    assert "page.goto(" not in source
    assert 'wait_until="domcontentloaded"' not in source
