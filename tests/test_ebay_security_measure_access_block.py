"""Regression coverage for the exact Railway eBay security challenge."""

from __future__ import annotations

from scripts.marketplace_access import (
    MarketplaceAccessState,
    classify_ebay_page,
)
from scripts.run_latest_auction_refresh import (
    ebay_access_blocked,
)


def test_security_measure_page_is_access_blocked() -> None:
    """Railway's HTTP-200 security page is blocked access, not unknown."""

    result = classify_ebay_page(
        status_code=200,
        title="Security Measure | eBay",
        body=(
            "Skip to main content "
            "Please verify yourself to continue. "
            "To keep eBay a safe place to buy and sell, "
            "we will occasionally ask you to verify yourself."
        ),
    )

    assert (
        result.state
        is MarketplaceAccessState.ACCESS_BLOCKED
    )
    assert "access/error page" in result.message.casefold()


def test_security_measure_classifier_reaches_runner_block_semantics() -> None:
    """The canonical classifier error must degrade as blocked access."""

    result = classify_ebay_page(
        status_code=200,
        title="Security Measure | eBay",
        body="Please verify yourself to continue.",
    )

    output = (
        "ERROR facerecords: "
        f"{result.message} "
        "Screenshot: logs/ebay_block_facerecords.png"
    )

    assert ebay_access_blocked(
        1,
        output,
    ) is True


def test_press_and_hold_challenge_is_access_blocked() -> None:
    """A press-and-hold security challenge is explicit block evidence."""

    result = classify_ebay_page(
        status_code=200,
        title="eBay",
        body=(
            "Security Measure. "
            "Press and hold to verify yourself."
        ),
    )

    assert (
        result.state
        is MarketplaceAccessState.ACCESS_BLOCKED
    )


def test_unknown_success_response_remains_unknown() -> None:
    """The patch must not make arbitrary successful pages available."""

    result = classify_ebay_page(
        status_code=200,
        title="eBay",
        body="eBay",
    )

    assert (
        result.state
        is MarketplaceAccessState.UNKNOWN_ERROR
    )


def test_successful_runner_exit_is_never_access_blocked() -> None:
    """Blocked text cannot override a successful crawler return code."""

    assert ebay_access_blocked(
        0,
        "Security Measure | eBay",
    ) is False
