"""Tests for eBay cloud-access failure classification."""

from scripts.run_latest_auction_refresh import ebay_access_blocked


def test_http_403_is_access_block() -> None:
    """HTTP 403 should degrade eBay instead of failing the whole refresh."""
    assert ebay_access_blocked(
        1,
        "ERROR facerecords: Blocked HTTP status 403",
    )


def test_sign_in_redirect_is_access_block() -> None:
    """Forced anonymous-search sign-in should be treated as blocked access."""
    assert ebay_access_blocked(
        1,
        (
            "ERROR facerecords: eBay unexpectedly redirected "
            "the anonymous completed-search page to sign-in."
        ),
    )


def test_success_is_not_access_block() -> None:
    """Successful crawler execution must never be classified as blocked."""
    assert not ebay_access_blocked(
        0,
        "Blocked HTTP status 403",
    )


def test_unrelated_failure_is_not_access_block() -> None:
    """Unrelated crawler failures must remain fatal."""
    assert not ebay_access_blocked(
        1,
        "ERROR facerecords: parser exploded unexpectedly",
    )


def test_access_stop_403_is_access_block() -> None:
    """Sold-search 403 after context replace is blocked access, not a crash."""
    assert ebay_access_blocked(
        1,
        (
            "EBAY_CRAWL_PHASE=access_continue page=1 status=403\n"
            "EBAY_CRAWL_PHASE=context_replace page=1 profile=ebay-public\n"
            "EBAY_CRAWL_PHASE=access_stop page=1 status=403\n"
            "EBAY_CRAWL_PHASE=results_ready page=1 status=403 "
            "listing_count=0\n"
        ),
    )


def test_screenshot_timeout_after_403_is_access_block() -> None:
    """Diagnostic screenshot hang on a 403 stamp must not look like a crash."""
    assert ebay_access_blocked(
        1,
        (
            "EBAY_CRAWL_PHASE=results_ready page=1 status=403 "
            "listing_count=0\n"
            "ERROR b90ab4a1-7fe0-5edb-aea5-3d9b7135325b: "
            "Page.screenshot: Timeout 8000ms exceeded.\n"
            "Blocked         : 0\n"
            "Failed          : 1\n"
        ),
    )


def test_screenshot_timeout_without_http_block_is_not_access_block() -> None:
    """A screenshot hang with no HTTP-block evidence stays a crawl failure."""
    assert not ebay_access_blocked(
        1,
        "ERROR facerecords: Page.screenshot: Timeout 8000ms exceeded.",
    )
