"""Regression tests for deployed marketplace response classification."""

from __future__ import annotations

from scripts.marketplace_access import (
    MarketplaceAccessState,
    classify_buyee_page,
    classify_ebay_page,
)


def test_buyee_railway_403_is_access_blocked() -> None:
    """Railway's observed Buyee 403 must not be called maintenance."""
    result = classify_buyee_page(
        status_code=403,
        title="403 Forbidden",
        body="403 Forbidden",
    )

    assert result.state is MarketplaceAccessState.ACCESS_BLOCKED
    assert "HTTP 403" in result.message


def test_buyee_real_maintenance_page_is_maintenance() -> None:
    """A genuine Buyee maintenance page remains distinguishable."""
    result = classify_buyee_page(
        status_code=200,
        title="Buyee",
        body=(
            "Site Maintenance "
            "The website is currently unavailable due to maintenance. "
            "Please checkback later."
        ),
    )

    assert result.state is MarketplaceAccessState.MAINTENANCE
    assert "maintenance" in result.message.casefold()


def test_buyee_normal_response_is_available() -> None:
    """A successful non-maintenance Buyee response is available."""
    result = classify_buyee_page(
        status_code=200,
        title="Buyee",
        body="Buyee Japanese proxy shopping service.",
    )

    assert result.state is MarketplaceAccessState.AVAILABLE


def test_ebay_railway_403_error_page_is_access_blocked() -> None:
    """The exact Railway eBay response must never look healthy."""
    result = classify_ebay_page(
        status_code=403,
        title="Error Page | eBay",
        body=(
            "SORRY Something went wrong on our end. "
            "Please go back and try again or go to eBay Homepage."
        ),
    )

    assert result.state is MarketplaceAccessState.ACCESS_BLOCKED
    assert "HTTP 403" in result.message


def test_ebay_brand_name_alone_does_not_mean_available() -> None:
    """The word eBay on an error page is not positive availability evidence."""
    result = classify_ebay_page(
        status_code=500,
        title="Error Page | eBay",
        body="Something went wrong on our end. eBay Homepage.",
    )

    assert result.state is MarketplaceAccessState.ACCESS_BLOCKED


def test_ebay_normal_homepage_is_available() -> None:
    """Normal homepage markers plus successful HTTP status indicate availability."""
    result = classify_ebay_page(
        status_code=200,
        title="Electronics, Cars, Fashion, Collectibles & More | eBay",
        body=(
            "Shop by category "
            "Search for anything "
            "Saved Motors Electronics Collectibles"
        ),
    )

    assert result.state is MarketplaceAccessState.AVAILABLE


def test_ebay_success_without_required_markers_is_unknown() -> None:
    """A generic successful response is insufficient proof of a usable page."""
    result = classify_ebay_page(
        status_code=200,
        title="eBay",
        body="eBay",
    )

    assert result.state is MarketplaceAccessState.UNKNOWN_ERROR



def test_ebay_search_results_with_listing_evidence_are_available() -> None:
    """Actual item identities prove a successful sold-search response."""

    result = classify_ebay_page(
        status_code=200,
        title="teresa teng sold items | eBay",
        body="52 results for teresa teng",
        listing_count=52,
    )

    assert result.state is MarketplaceAccessState.AVAILABLE
    assert "52 listing identity" in result.message


def test_ebay_block_status_wins_over_listing_evidence() -> None:
    """HTTP blocking cannot be hidden by stale listing markup."""

    result = classify_ebay_page(
        status_code=403,
        title="Error Page | eBay",
        body="Something went wrong on our end.",
        listing_count=52,
    )

    assert result.state is MarketplaceAccessState.ACCESS_BLOCKED
    assert "HTTP 403" in result.message
