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
