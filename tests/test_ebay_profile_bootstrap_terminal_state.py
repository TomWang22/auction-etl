"""Regression tests for fail-closed manual eBay profile clearance."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(
    __file__
).resolve().parents[1]

BOOTSTRAP = (
    ROOT
    / "scripts"
    / "bootstrap_ebay_profile.py"
)


def load_bootstrap() -> ModuleType:
    """Load the bootstrap module from its repository path."""

    spec = importlib.util.spec_from_file_location(
        "bootstrap_ebay_profile_under_test",
        BOOTSTRAP,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[
        spec.name
    ] = module

    spec.loader.exec_module(
        module
    )

    return module


def test_http_403_generic_error_is_terminal_block() -> None:
    """The exact screenshot state must never offer manual clearance."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=403,
        url=(
            "https://www.ebay.com/sch/i.html"
            "?_nkw=teresa+teng"
            "&_ssn=facerecords"
            "&LH_Complete=1"
            "&LH_Sold=1"
            "&_sop=13"
        ),
        title="Error Page | eBay",
        body=(
            "SORRY Something went wrong on our end. "
            "Please go back and try again."
        ),
        item_link_count=0,
        visible_challenge=False,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.ACCESS_BLOCKED
    )


def test_http_200_generic_error_is_terminal_block() -> None:
    """An HTTP-200 eBay Error Page must also fail closed."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=200,
        url="https://www.ebay.com/sch/i.html",
        title="Error Page | eBay",
        body=(
            "Something went wrong on our end. "
            "Please go back and try again."
        ),
        item_link_count=0,
        visible_challenge=False,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.ACCESS_BLOCKED
    )


def test_error_page_precedes_signin_url() -> None:
    """A broken sign-in endpoint is an access error, not actionable auth."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=403,
        url="https://signin.ebay.com/signin/s",
        title="Error Page | eBay",
        body=(
            "SORRY Something went wrong on our end. "
            "Please go back and try again."
        ),
        item_link_count=0,
        visible_challenge=False,
        visible_signin=True,
    )

    assert (
        state
        is module.BootstrapState.ACCESS_BLOCKED
    )


def test_real_signin_page_allows_one_human_action() -> None:
    """A visible normal sign-in form may be completed by the operator."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=200,
        url="https://signin.ebay.com/signin/s",
        title="Sign in or Register | eBay",
        body="Sign in Email or username Continue",
        item_link_count=0,
        visible_challenge=False,
        visible_signin=True,
    )

    assert (
        state
        is module.BootstrapState.HUMAN_AUTH_REQUIRED
    )


def test_real_visible_challenge_allows_human_action_only() -> None:
    """A visible verification control may be handled only by the human."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=403,
        url="https://www.ebay.com/sch/i.html",
        title="Security check | eBay",
        body="Please verify you are human.",
        item_link_count=0,
        visible_challenge=True,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.HUMAN_CHALLENGE_REQUIRED
    )


def test_normal_results_require_item_links() -> None:
    """A successful page must contain actual eBay item identities."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=200,
        url="https://www.ebay.com/sch/i.html",
        title="Teresa Teng products for sale | eBay",
        body="Search for anything Shop by category",
        item_link_count=53,
        visible_challenge=False,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.AVAILABLE
    )


def test_unknown_zero_result_page_is_not_success() -> None:
    """An unexplained zero-link page must not be called cleared."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=200,
        url="https://www.ebay.com/sch/i.html",
        title="eBay",
        body="Welcome",
        item_link_count=0,
        visible_challenge=False,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.UNKNOWN_ERROR
    )


def test_bootstrap_does_not_create_replacement_profile() -> None:
    """Missing profile state must fail instead of silently starting over."""

    source = BOOTSTRAP.read_text(
        encoding="utf-8"
    )

    assert (
        ".mkdir("
        not in source
    )

    assert (
        "EBAY_PROFILE_REPLACEMENT_AUTOMATIC=false"
        in source
    )


def test_success_requires_available_state() -> None:
    """The old unconditional persistent-profile success text is gone."""

    source = BOOTSTRAP.read_text(
        encoding="utf-8"
    )

    assert (
        "The persistent profile has been saved."
        not in source
    )

    assert (
        "EBAY_PROFILE_ACCESS_VALIDATED=PASS"
        in source
    )

    assert (
        "if initial.state is BootstrapState.AVAILABLE:"
        in source
    )

    assert (
        "if final.state is BootstrapState.AVAILABLE:"
        in source
    )

def test_missing_named_profile_is_not_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolving a missing profile must not create the named directory."""

    module = load_bootstrap()

    profile_root = (
        tmp_path
        / "profiles"
    )

    monkeypatch.setenv(
        "AUCTION_BROWSER_PROFILE_ROOT",
        str(profile_root),
    )

    resolved = module.existing_profile_directory(
        "facerecords-missing"
    )

    assert resolved == (
        profile_root
        / "facerecords-missing"
    )

    assert (
        profile_root.is_dir()
        is True
    )

    assert (
        resolved.exists()
        is False
    )


def test_bootstrap_does_not_call_mutating_profile_path() -> None:
    """Bootstrap must not resolve profiles through profile_path()."""

    source = BOOTSTRAP.read_text(
        encoding="utf-8"
    )

    assert (
        "profile_path("
        not in source
    )

    assert (
        "existing_profile_directory("
        in source
    )


def test_off_domain_signin_url_is_not_actionable_auth() -> None:
    """An off-domain redirect must never be presented as eBay authentication."""

    module = load_bootstrap()

    assert (
        module.is_signin_url(
            "https://signin.example.com/signin"
        )
        is False
    )

    assert (
        module.is_signin_url(
            "https://example.com/signin"
        )
        is False
    )

    assert (
        module.is_signin_url(
            "https://signin.ebay.com/signin/s"
        )
        is True
    )


def test_off_domain_signin_page_is_unknown_not_human_auth() -> None:
    """Human credential action is offered only for an eBay sign-in endpoint."""

    module = load_bootstrap()

    state = module.classify_snapshot(
        http_status=200,
        url="https://signin.example.com/signin",
        title="Sign in",
        body="Email Password",
        item_link_count=0,
        visible_challenge=False,
        visible_signin=False,
    )

    assert (
        state
        is module.BootstrapState.UNKNOWN_ERROR
    )
