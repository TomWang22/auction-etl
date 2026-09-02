"""Regression tests for verified eBay storage-state export."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "export_ebay_storage_state.py"
)


def load_exporter() -> ModuleType:
    """Load the exporter without executing its command-line entry point."""

    spec = importlib.util.spec_from_file_location(
        "_test_export_ebay_storage_state",
        SCRIPT,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return module


EXPORTER = load_exporter()


class FakeResponse:
    """Represent one fake Playwright response."""

    def __init__(
        self,
        status: int,
    ) -> None:
        self.status = status


class FakeLocator:
    """Represent fake eBay item-link lookup behavior."""

    def __init__(
        self,
        count: int,
    ) -> None:
        self._count = count
        self.first = self

    def wait_for(
        self,
        *,
        state: str,
        timeout: int,
    ) -> None:
        del state
        del timeout

        if self._count < 1:
            raise EXPORTER.PlaywrightTimeoutError(
                "fake timeout"
            )

    def count(self) -> int:
        return self._count


class FakePage:
    """Represent a network-free Playwright page."""

    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        html: str = "<html></html>",
        item_link_count: int = 1,
    ) -> None:
        self.url = final_url
        self.status = status
        self.html = html
        self.item_link_count = item_link_count
        self.goto_calls: list[str] = []

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> FakeResponse:
        del wait_until
        del timeout

        self.goto_calls.append(
            url
        )

        return FakeResponse(
            self.status
        )

    def content(self) -> str:
        return self.html

    def locator(
        self,
        selector: str,
    ) -> FakeLocator:
        assert selector == EXPORTER.ITEM_LINK_SELECTOR

        return FakeLocator(
            self.item_link_count
        )


class FakeContext:
    """Represent a network-free browser context."""

    def __init__(
        self,
        page: FakePage,
        *,
        storage_payload: dict[str, Any] | None = None,
    ) -> None:
        self.pages = [page]
        self.storage_payload = (
            storage_payload
            or {
                "cookies": [
                    {
                        "name": "sid",
                        "value": "fake-test-value",
                        "domain": ".ebay.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }
        )
        self.storage_state_calls = 0

    def new_page(self) -> FakePage:
        return self.pages[0]

    def storage_state(
        self,
        *,
        path: str,
    ) -> None:
        self.storage_state_calls += 1

        Path(path).write_text(
            json.dumps(
                self.storage_payload
            ),
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "value",
    (
        "https://www.ebay.com/",
        "https://ebay.com/",
        "https://signin.ebay.com/",
    ),
)
def test_require_ebay_url_accepts_ebay_https(
    value: str,
) -> None:
    """Allow ordinary HTTPS ebay.com hosts."""

    assert EXPORTER.require_ebay_url(
        value
    ) == value


@pytest.mark.parametrize(
    "value",
    (
        "http://www.ebay.com/",
        "https://example.com/",
        "https://evil-ebay.com/",
        "file:///tmp/example",
        "https://user:password@www.ebay.com/",
        "https://www.ebay.com:444/",
    ),
)
def test_require_ebay_url_rejects_unsafe_values(
    value: str,
) -> None:
    """Reject non-eBay or unsafe URL forms."""

    with pytest.raises(
        EXPORTER.EbayStorageStateError
    ):
        EXPORTER.require_ebay_url(
            value
        )


def test_load_source_url_reads_configured_facerecords(
    tmp_path: Path,
) -> None:
    """Use the repository-style configured source URL."""

    config = tmp_path / "ebay_sources.json"

    config.write_text(
        json.dumps(
            [
                {
                    "name": "facerecords",
                    "enabled": True,
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_ssn=facerecords"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )

    assert EXPORTER.load_source_url(
        config,
        "facerecords",
    ).startswith(
        "https://www.ebay.com/"
    )


def test_verify_source_access_accepts_real_item_links() -> None:
    """Permit export only after genuine result links are visible."""

    source_url = (
        "https://www.ebay.com/sch/i.html"
        "?_ssn=facerecords"
    )

    page = FakePage(
        final_url=source_url,
        status=200,
        item_link_count=7,
    )

    result = EXPORTER.verify_source_access(
        page=page,
        source_url=source_url,
        navigation_timeout_seconds=10,
        result_timeout_seconds=10,
    )

    assert result.item_link_count == 7
    assert result.http_status is None
    assert page.goto_calls == []


def test_verify_source_access_rejects_signin_redirect() -> None:
    """Do not export state from a session redirected to sign-in."""

    page = FakePage(
        final_url=(
            "https://signin.ebay.com/ws/eBayISAPI.dll"
        ),
        status=200,
        item_link_count=0,
    )

    with pytest.raises(
        EXPORTER.EbayAuthenticationRequiredError,
        match="sign-in",
    ):
        EXPORTER.verify_source_access(
            page=page,
            source_url=(
                "https://www.ebay.com/sch/i.html"
                "?_ssn=facerecords"
            ),
            navigation_timeout_seconds=10,
            result_timeout_seconds=10,
        )


@pytest.mark.parametrize(
    "status",
    (
        401,
        403,
        429,
    ),
)
def test_access_block_status_classifier(
    status: int,
) -> None:
    """Preserve blocked-response classification independently of navigation."""

    assert EXPORTER.is_access_block_status(status)
    assert not EXPORTER.is_access_block_status(200)


@pytest.mark.parametrize(
    "message",
    (
        "Verify you are human",
        "Complete the security check",
        "Press and hold",
        "Access denied",
    ),
)
def test_verify_source_access_rejects_security_interstitial(
    message: str,
) -> None:
    """Never export state from an access-verification page."""

    page = FakePage(
        final_url=(
            "https://www.ebay.com/sch/i.html"
            "?_ssn=facerecords"
        ),
        status=200,
        html=f"<html><body>{message}</body></html>",
        item_link_count=1,
    )

    with pytest.raises(
        EXPORTER.EbayAccessBlockedError,
        match="security/access",
    ):
        EXPORTER.verify_source_access(
            page=page,
            source_url=page.url,
            navigation_timeout_seconds=10,
            result_timeout_seconds=10,
        )


def test_verify_source_access_rejects_zero_item_links() -> None:
    """A cookie-bearing page without results is not proof of access."""

    page = FakePage(
        final_url=(
            "https://www.ebay.com/sch/i.html"
            "?_ssn=facerecords"
        ),
        status=200,
        item_link_count=0,
    )

    with pytest.raises(
        EXPORTER.EbayStorageStateError,
        match="no real item links",
    ):
        EXPORTER.verify_source_access(
            page=page,
            source_url=page.url,
            navigation_timeout_seconds=10,
            result_timeout_seconds=10,
        )


def test_export_verifies_before_persisting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Storage-state persistence must occur after source verification."""

    page = FakePage(
        final_url="https://www.ebay.com/",
    )
    context = FakeContext(
        page
    )

    calls: list[str] = []

    verification = EXPORTER.SourceVerification(
        requested_url="https://www.ebay.com/",
        final_url="https://www.ebay.com/",
        http_status=200,
        item_link_count=1,
    )

    def fake_verify_source_access(
        **kwargs: Any,
    ) -> Any:
        del kwargs
        calls.append(
            "verify"
        )
        return verification

    def fake_persist_storage_state(
        **kwargs: Any,
    ) -> tuple[Path, int, int]:
        del kwargs
        calls.append(
            "persist"
        )
        return (
            tmp_path / "state.json",
            1,
            1,
        )

    monkeypatch.setattr(
        EXPORTER,
        "verify_source_access",
        fake_verify_source_access,
    )
    monkeypatch.setattr(
        EXPORTER,
        "persist_storage_state",
        fake_persist_storage_state,
    )

    EXPORTER.export_verified_storage_state(
        context=context,
        source_url="https://www.ebay.com/",
        output_path=tmp_path / "state.json",
        navigation_timeout_seconds=10,
        result_timeout_seconds=10,
    )

    assert calls == [
        "verify",
        "persist",
    ]


def test_failed_verification_never_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Do not create authentication material after a failed verification."""

    page = FakePage(
        final_url="https://signin.ebay.com/",
    )
    context = FakeContext(
        page
    )

    persisted = False

    def fake_verify_source_access(
        **kwargs: Any,
    ) -> Any:
        del kwargs

        raise EXPORTER.EbayAuthenticationRequiredError(
            "sign-in"
        )

    def fake_persist_storage_state(
        **kwargs: Any,
    ) -> tuple[Path, int, int]:
        nonlocal persisted

        del kwargs

        persisted = True

        return (
            tmp_path / "state.json",
            1,
            1,
        )

    monkeypatch.setattr(
        EXPORTER,
        "verify_source_access",
        fake_verify_source_access,
    )
    monkeypatch.setattr(
        EXPORTER,
        "persist_storage_state",
        fake_persist_storage_state,
    )

    with pytest.raises(
        EXPORTER.EbayAuthenticationRequiredError
    ):
        EXPORTER.export_verified_storage_state(
            context=context,
            source_url="https://www.ebay.com/",
            output_path=tmp_path / "state.json",
            navigation_timeout_seconds=10,
            result_timeout_seconds=10,
        )

    assert persisted is False


def test_persist_storage_state_writes_valid_secret_file(
    tmp_path: Path,
) -> None:
    """Persist valid state atomically with private permissions."""

    page = FakePage(
        final_url="https://www.ebay.com/",
    )
    context = FakeContext(
        page
    )

    output = (
        tmp_path
        / "private"
        / "ebay-storage-state.json"
    )

    (
        resolved,
        cookie_count,
        domain_count,
    ) = EXPORTER.persist_storage_state(
        context=context,
        output_path=output,
    )

    assert resolved == output.resolve()
    assert cookie_count == 1
    assert domain_count == 1
    assert context.storage_state_calls == 1
    assert resolved.is_file()

    mode = os.stat(
        resolved
    ).st_mode & 0o777

    assert mode == 0o600


def test_verify_source_access_does_not_navigate_after_operator_confirmation() -> None:
    """Source verification must inspect the operator-prepared page in place."""

    import ast
    from pathlib import Path

    exporter_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "export_ebay_storage_state.py"
    )

    exporter_source = exporter_path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        exporter_source,
        filename=str(exporter_path),
    )

    functions = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            and node.name == "verify_source_access"
        )
    ]

    assert len(functions) == 1

    page_goto_calls = [
        node
        for node in ast.walk(
            functions[0]
        )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "goto"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "page"
        )
    ]

    assert page_goto_calls == []

    assert (
        "EBAY_SOURCE_VERIFICATION_MODE="
        "existing_operator_page"
        in exporter_source
    )
