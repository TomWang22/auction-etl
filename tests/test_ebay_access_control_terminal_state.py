"""Regression coverage for terminal eBay access-control handling."""

from __future__ import annotations

import inspect

import scripts.acquire_ebay_structured as acquire
import scripts.produce_ebay_external_handoff as producer


class FakeElement:
    """Minimal Playwright-like element used for visibility tests."""

    def __init__(
        self,
        visible: bool,
    ) -> None:
        self._visible = visible

    def is_visible(
        self,
    ) -> bool:
        """Return configured visibility."""

        return self._visible


class FakeLocator:
    """Minimal Playwright-like locator used for selector tests."""

    def __init__(
        self,
        visibility: list[bool],
    ) -> None:
        self._visibility = visibility

    def count(
        self,
    ) -> int:
        """Return configured element count."""

        return len(
            self._visibility
        )

    def nth(
        self,
        index: int,
    ) -> FakeElement:
        """Return one configured element."""

        return FakeElement(
            self._visibility[
                index
            ]
        )


class FakePage:
    """Minimal page exposing selector visibility."""

    def __init__(
        self,
        visible_selector: str | None,
        *,
        hidden_selector: str | None = None,
    ) -> None:
        self._visible_selector = visible_selector
        self._hidden_selector = hidden_selector

    def locator(
        self,
        selector: str,
    ) -> FakeLocator:
        """Return one synthetic locator."""

        if (
            self._visible_selector is not None
            and selector == self._visible_selector
        ):
            return FakeLocator(
                [True]
            )

        if (
            self._hidden_selector is not None
            and selector == self._hidden_selector
        ):
            return FakeLocator(
                [False]
            )

        return FakeLocator(
            []
        )


def test_visible_captcha_element_is_access_control() -> None:
    """A visible CAPTCHA DOM element must stop acquisition."""

    selector = acquire.ACCESS_CONTROL_SELECTORS[
        0
    ]

    page = FakePage(
        selector
    )

    assert (
        acquire.visible_ebay_access_control_selector(
            page
        )
        == selector
    )

    reason = acquire.ebay_access_control_reason(
        page,
        title="Teresa Teng in Vinyl Records for sale | eBay",
        body="Search for anything Shop by category",
    )

    assert reason is not None
    assert "visible access-control element" in reason


def test_hidden_captcha_element_does_not_false_positive() -> None:
    """Dormant hidden CAPTCHA markup alone must not block a normal page."""

    selector = acquire.ACCESS_CONTROL_SELECTORS[
        0
    ]

    page = FakePage(
        None,
        hidden_selector=selector,
    )

    assert (
        acquire.visible_ebay_access_control_selector(
            page
        )
        is None
    )


def test_access_control_text_is_detected() -> None:
    """Rendered eBay verification text must fail closed."""

    assert (
        acquire.ebay_access_control_text_present(
            title="Security Check",
            body="Please verify you are human to continue.",
        )
        is True
    )

    assert (
        acquire.ebay_access_control_text_present(
            title="Teresa Teng in Vinyl Records for sale | eBay",
            body="Search for anything Shop by category",
        )
        is False
    )


def test_generic_ebay_error_is_not_mislabeled_as_captcha() -> None:
    """Generic eBay service errors remain separate from access control."""

    assert (
        acquire.is_ebay_generic_error_page(
            title="Error Page | eBay",
            body=(
                "Something went wrong on our end. "
                "Please go back and try again."
            ),
        )
        is True
    )

    assert (
        acquire.ebay_access_control_text_present(
            title="Error Page | eBay",
            body=(
                "Something went wrong on our end. "
                "Please go back and try again."
            ),
        )
        is False
    )


def test_access_control_precedes_signin_interpretation() -> None:
    """CAPTCHA/access control must win before sign-in classification."""

    source = inspect.getsource(
        acquire.acquire_page
    )

    collect_start = source.index(
        "def collect("
    )

    collect_end = source.index(
        "try:\n"
        "        with sync_playwright()",
        collect_start,
    )

    collect = source[
        collect_start:collect_end
    ]

    access_position = collect.index(
        "access_control_reason = "
        "ebay_access_control_reason("
    )

    signin_position = collect.index(
        "if is_signin_url("
    )

    assert (
        access_position
        < signin_position
    )


def test_signin_detection_does_not_scan_arbitrary_query_text() -> None:
    """A query value containing 'signin' must not become an auth redirect."""

    assert (
        acquire.is_signin_url(
            "https://www.ebay.com/sch/i.html?next=signin"
        )
        is False
    )

    assert (
        acquire.is_signin_url(
            "https://signin.ebay.com/ws/eBayISAPI.dll"
        )
        is True
    )


def test_acquirer_has_distinct_terminal_exit_states() -> None:
    """Direct acquisition must expose access and auth failures separately."""

    source = inspect.getsource(
        acquire.main
    )

    access_position = source.index(
        "except EbayAccessBlockedError"
    )

    auth_position = source.index(
        "except EbayAuthenticationRequiredError"
    )

    generic_position = source.index(
        "except (\n"
        "        EbayAcquisitionError"
    )

    assert (
        access_position
        < auth_position
        < generic_position
    )

    assert (
        "EBAY_STRUCTURED_ACQUISITION=ACCESS_BLOCKED"
        in source
    )

    assert (
        "EBAY_ACCESS_CONTROL_REQUIRED=true"
        in source
    )

    assert "return 20" in source
    assert "return 21" in source


def test_external_producer_has_distinct_terminal_exit_states() -> None:
    """Producer must preserve access-control state instead of generic FAIL."""

    source = inspect.getsource(
        producer.main
    )

    access_position = source.index(
        "except EbayAccessBlockedError"
    )

    auth_position = source.index(
        "except EbayAuthenticationRequiredError"
    )

    generic_position = source.index(
        "except (\n"
        "        EbayAcquisitionError"
    )

    assert (
        access_position
        < auth_position
        < generic_position
    )

    required = (
        "EBAY_EXTERNAL_HANDOFF_PRODUCER=ACCESS_BLOCKED",
        "EBAY_EXTERNAL_ACCESS_CONTROL_REQUIRED=true",
        "EBAY_EXTERNAL_HANDOFF_PRODUCER=AUTHENTICATION_REQUIRED",
        "EBAY_EXTERNAL_AUTHENTICATION_REQUIRED=true",
        "EXTERNAL_RAW_PAGE_CREATED=false",
        "REFRESH_EXECUTED=false",
        "AUTOMATIC_RETRY=false",
    )

    for marker in required:
        assert marker in source


def test_persistent_profile_path_remains_required() -> None:
    """Access-control handling must not replace the established profile."""

    producer_source = inspect.getsource(
        producer.main
    )

    acquire_source = inspect.getsource(
        acquire.acquire_page
    )

    assert (
        "profile = profile_directory("
        in producer_source
    )

    assert (
        "profile_dir=profile"
        in producer_source
    )

    assert (
        "launch_persistent_context("
        in acquire_source
    )


def test_apply_remains_explicit() -> None:
    """The access-control patch must not introduce automatic database apply."""

    source = inspect.getsource(
        producer.main
    )

    assert (
        "if not arguments.apply:"
        in source
    )

    assert (
        "run_importer(\n"
        "            output,\n"
        "            source.name,\n"
        "            apply=False,"
        in source
    )

    assert (
        "run_importer(\n"
        "            output,\n"
        "            source.name,\n"
        "            apply=True,"
        in source
    )
