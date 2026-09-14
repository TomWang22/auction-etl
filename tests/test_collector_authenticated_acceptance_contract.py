"""Contracts for authenticated Collector Review browser acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.accept_collector_hover_click import AcceptanceError
from scripts import (
    accept_collector_hover_click_authenticated as authenticated,
)


APP_PATH = Path(
    "app/collector_review.py"
)
AUTH_PATH = Path(
    "auction_etl/auth/streamlit_auth.py"
)
ACCEPTANCE_PATH = Path(
    "scripts/accept_collector_hover_click_authenticated.py"
)


def _name_matches(
    value: str,
    name: str,
    exact: bool,
) -> bool:
    if exact:
        return value == name

    return name.casefold() in value.casefold()


class _Locator:
    def __init__(
        self,
        visible: bool,
    ) -> None:
        self._visible = visible

    def count(self) -> int:
        return int(self._visible)

    @property
    def first(self) -> "_Locator":
        return self

    def is_visible(self) -> bool:
        return self._visible


class _Scope:
    def __init__(
        self,
        *,
        headings: tuple[str, ...] = (),
        buttons: tuple[str, ...] = (),
        texts: tuple[str, ...] = (),
        url: str = "",
        title: str = "",
        closed: bool = False,
    ) -> None:
        self.headings = headings
        self.buttons = buttons
        self.texts = texts
        self.url = url
        self._title = title
        self._closed = closed
        self.wait_called = False
        self.screenshot_path: str | None = None
        self.frames: list[Any] = []
        self.iframe: _Scope | None = None
        self.extra_pages: list[_Scope] = []

    def title(self) -> str:
        return self._title

    def is_closed(self) -> bool:
        return self._closed

    def get_by_role(
        self,
        role: str,
        *,
        name: str,
        exact: bool = False,
    ) -> _Locator:
        haystack = ()

        if role == "heading":
            haystack = self.headings
        elif role == "button":
            haystack = self.buttons

        matched = any(
            _name_matches(
                item,
                name,
                exact,
            )
            for item in haystack
        )

        return _Locator(
            matched
        )

    def get_by_text(
        self,
        name: str,
        exact: bool = False,
    ) -> _Locator:
        haystack = (
            self.texts
            + self.headings
            + self.buttons
        )

        matched = any(
            _name_matches(
                item,
                name,
                exact,
            )
            for item in haystack
        )

        return _Locator(
            matched
        )

    def frame_locator(
        self,
        selector: str,
    ) -> _Scope:
        if (
            selector
            == authenticated.STREAMLIT_APP_FRAME_SELECTOR
            and self.iframe is not None
        ):
            return self.iframe

        return _Scope()

    def wait_for_timeout(
        self,
        milliseconds: float,
    ) -> None:
        del milliseconds
        self.wait_called = True

    def screenshot(
        self,
        *,
        path: str,
        full_page: bool = True,
    ) -> None:
        del full_page
        Path(path).write_bytes(
            b""
        )
        self.screenshot_path = path

    def locator(
        self,
        selector: str,
    ) -> _Locator:
        del selector

        return _Locator(
            False
        )


class _Context:
    def __init__(
        self,
        pages: list[_Scope],
    ) -> None:
        self.pages = pages


def _login_iframe() -> _Scope:
    return _Scope(
        headings=(
            "Collector Ledger",
        ),
        buttons=(
            "Sign in or create account",
        ),
        texts=(
            "Review marketplace sales",
            "Sign in to access your listings",
        ),
        url=(
            "https://auction-scout-main-test."
            "streamlit.app/~/+/"
        ),
        title="Review marketplace sales",
    )


def _authenticated_iframe(
    *,
    logout: bool = True,
    signed_in: bool = True,
    heading: bool = True,
    results: bool = True,
) -> _Scope:
    headings = ()
    buttons = ()
    texts = ()

    if heading:
        headings = (
            "🔎 Review marketplace sales",
        )

    if results:
        headings = headings + (
            "Search results",
        )
        texts = texts + (
            "Search results",
        )

    if logout:
        buttons = buttons + (
            "Log out",
        )

    if signed_in:
        texts = texts + (
            "Signed in as Collector",
        )

    return _Scope(
        headings=headings,
        buttons=buttons,
        texts=texts,
        url=(
            "https://auction-scout-main-test."
            "streamlit.app/~/+/"
        ),
        title="Review marketplace sales",
    )


def _cloud_page(
    iframe: _Scope | None,
    *,
    extra_pages: list[_Scope] | None = None,
) -> _Scope:
    page = _Scope(
        headings=(),
        buttons=(),
        texts=(),
        url=(
            "https://auction-scout-main-test."
            "streamlit.app/"
        ),
        title=(
            "Review marketplace sales · Streamlit"
        ),
    )
    page.iframe = iframe
    page.extra_pages = extra_pages or []
    page.context = _Context(
        [
            page,
            *page.extra_pages,
        ]
    )
    page.frames = [
        _Scope(
            url=page.url,
            title=page.title(),
        )
    ]

    if iframe is not None:
        page.frames.append(
            iframe
        )

    return page


def test_authenticated_heading_matches_current_collector_review() -> None:
    """Acceptance must identify the current authenticated review page."""
    app_source = APP_PATH.read_text(
        encoding="utf-8"
    )
    auth_source = AUTH_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        authenticated.AUTHENTICATED_APPLICATION_HEADING
        == "Review marketplace sales"
    )
    assert (
        authenticated.LOGIN_SCREEN_HEADING
        == "Collector Ledger"
    )
    assert (
        authenticated.STREAMLIT_APP_FRAME_SELECTOR
        == 'iframe[title="streamlitApp"]'
    )

    assert (
        'page_title="Review marketplace sales"'
        in app_source
    )
    assert (
        '"🔎 Review marketplace sales"'
        in app_source
    )
    assert (
        '"Search results"'
        in app_source
    )
    assert (
        'st.title("Collector Ledger")'
        in auth_source
    )
    assert "st.login()" in auth_source
    assert 'st.button("Log out"' in auth_source
    assert "Signed in as" in auth_source


def test_stale_authenticated_heading_is_absent() -> None:
    """The retired page title must not remain in the acceptance helper."""
    acceptance_source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    assert "Auction Collector Review" not in acceptance_source


def test_acceptance_inspects_streamlit_app_iframe() -> None:
    """Cloud Collector Review renders inside the Streamlit app iframe."""
    acceptance_source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        'iframe[title="streamlitApp"]'
        in acceptance_source
    )
    assert "frame_locator(" in acceptance_source
    assert "context.pages" in acceptance_source


def test_login_screen_in_iframe_is_not_authenticated() -> None:
    """The Collector Ledger login shell must not satisfy authentication."""
    page = _cloud_page(
        _login_iframe()
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is False
    )

    with pytest.raises(
        AcceptanceError,
        match="did not become visible",
    ):
        authenticated.wait_for_authenticated_application(
            page,
            timeout_seconds=0.01,
        )


def test_outer_page_title_is_not_authenticated() -> None:
    """Document title and sidebar copy are not an authenticated contract."""
    page = _cloud_page(
        None
    )
    page.headings = (
        "Review marketplace sales",
    )
    page.texts = (
        "Review marketplace sales",
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is False
    )


def test_logout_in_app_iframe_is_authenticated() -> None:
    """A visible Log out control inside the app frame is authenticated."""
    page = _cloud_page(
        _authenticated_iframe(
            heading=False,
            results=False,
            signed_in=False,
        )
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is True
    )

    authenticated.wait_for_authenticated_application(
        page,
        timeout_seconds=1.0,
    )


def test_signed_in_marker_in_app_iframe_is_authenticated() -> None:
    """A visible Signed in as caption inside the app frame is authenticated."""
    page = _cloud_page(
        _authenticated_iframe(
            logout=False,
            heading=False,
            results=False,
        )
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is True
    )


def test_authenticated_heading_requires_results_ui() -> None:
    """Review heading without results or account evidence is not enough."""
    page = _cloud_page(
        _authenticated_iframe(
            logout=False,
            signed_in=False,
            results=False,
        )
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is False
    )

    page = _cloud_page(
        _authenticated_iframe(
            logout=False,
            signed_in=False,
            heading=True,
            results=True,
        )
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is True
    )


def test_login_screen_beats_sidebar_review_copy() -> None:
    """Pre-auth navigation copy must not count as Collector Review."""
    iframe = _login_iframe()
    iframe.headings = iframe.headings + (
        "Review marketplace sales",
    )
    page = _cloud_page(
        iframe
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is False
    )


def test_popup_page_can_satisfy_authentication() -> None:
    """OIDC may finish in another page that still hosts the app iframe."""
    popup = _cloud_page(
        _authenticated_iframe()
    )
    page = _cloud_page(
        _login_iframe(),
        extra_pages=[
            popup
        ],
    )

    assert (
        authenticated.application_is_authenticated(
            page
        )
        is True
    )


def test_capture_timeout_writes_sanitized_diagnostics(
    tmp_path: Path,
) -> None:
    """Capture failures must leave screenshot and frame evidence, not secrets."""
    page = _cloud_page(
        _login_iframe()
    )
    evidence_dir = tmp_path / "capture"

    diagnostics_path = (
        authenticated.write_authentication_failure_evidence(
            page=page,
            error=AcceptanceError(
                "Authenticated Collector Review did not become visible."
            ),
            evidence_dir=evidence_dir,
            console_errors=[
                "boom",
            ],
            page_errors=[],
        )
    )

    screenshot = (
        evidence_dir
        / "failure"
        / "failure.png"
    )

    assert screenshot.is_file()
    assert diagnostics_path.is_file()

    payload = diagnostics_path.read_text(
        encoding="utf-8"
    ).casefold()

    for forbidden in (
        "cookie",
        "cookies",
        "localstorage",
        "storage_state",
        "authorization",
        "access_token",
        "password",
    ):
        assert forbidden not in payload

    assert "streamlit.app" in payload
    assert "collector ledger" in payload
    assert "boom" in payload
    assert '"pages"' in payload
    assert '"frames"' in payload
    assert '"headings"' in payload


def test_capture_helper_records_timeout_evidence() -> None:
    """The capture path must persist sanitized diagnostics on timeout."""
    source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    required = (
        "write_authentication_failure_evidence(",
        "application_is_authenticated(",
        "STREAMLIT_APP_FRAME_SELECTOR",
        "LOGIN_SCREEN_HEADING",
        "capture_authentication_state(",
        "STREAMLIT_AUTH_STATE_CONTENT_PRINTED=false",
        "Save collector record",
        "save_button_clicked",
    )

    for fragment in required:
        assert fragment in source

    assert "storage_state(" in source
    assert "STREAMLIT_AUTH_STATE_CONTENT_PRINTED=false" in source
    assert "FORBIDDEN_DIAGNOSTIC_KEYS" in source
