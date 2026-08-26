"""Classify marketplace browser responses using explicit response evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MarketplaceAccessState(StrEnum):
    """Canonical marketplace browser-access classifications."""

    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    ACCESS_BLOCKED = "access_blocked"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class MarketplacePageResult:
    """One deterministic marketplace response classification."""

    state: MarketplaceAccessState
    message: str


def normalize_page_text(value: str) -> str:
    """Normalize rendered text for deterministic matching."""
    return " ".join(value.casefold().split())


def classify_buyee_page(
    *,
    status_code: int | None,
    title: str,
    body: str,
) -> MarketplacePageResult:
    """Classify a Buyee response without confusing maintenance and blocking."""
    normalized_title = normalize_page_text(title)
    normalized_body = normalize_page_text(body)

    if status_code in {401, 403, 429}:
        return MarketplacePageResult(
            state=MarketplaceAccessState.ACCESS_BLOCKED,
            message=(
                "Buyee rejected the deployed worker's request "
                f"with HTTP {status_code}."
            ),
        )

    maintenance_markers = (
        "site maintenance",
        "currently unavailable due to maintenance",
        "please checkback later",
    )

    if any(
        marker in normalized_body
        for marker in maintenance_markers
    ):
        return MarketplacePageResult(
            state=MarketplaceAccessState.MAINTENANCE,
            message="Buyee is currently undergoing site maintenance.",
        )

    blocked_markers = (
        "403 forbidden",
        "access denied",
        "temporarily blocked",
        "unusual traffic",
    )

    if any(
        marker in normalized_body
        or marker in normalized_title
        for marker in blocked_markers
    ):
        return MarketplacePageResult(
            state=MarketplaceAccessState.ACCESS_BLOCKED,
            message="Buyee rejected access from the deployed worker.",
        )

    if (
        status_code is not None
        and 200 <= status_code < 400
    ):
        return MarketplacePageResult(
            state=MarketplaceAccessState.AVAILABLE,
            message="Buyee responded successfully.",
        )

    return MarketplacePageResult(
        state=MarketplaceAccessState.UNKNOWN_ERROR,
        message="Buyee returned an unrecognized response.",
    )


def classify_ebay_page(
    *,
    status_code: int | None,
    title: str,
    body: str,
) -> MarketplacePageResult:
    """Classify eBay using response status and positive page evidence."""
    normalized_title = normalize_page_text(title)
    normalized_body = normalize_page_text(body)

    if status_code in {401, 403, 429}:
        return MarketplacePageResult(
            state=MarketplaceAccessState.ACCESS_BLOCKED,
            message=(
                "eBay rejected the deployed worker's request "
                f"with HTTP {status_code}."
            ),
        )

    error_markers = (
        "error page | ebay",
        "something went wrong on our end",
        "access denied",
        "temporarily blocked",
        "verify you are human",
        "captcha",
        "unusual traffic",
    )

    if any(
        marker in normalized_title
        or marker in normalized_body
        for marker in error_markers
    ):
        return MarketplacePageResult(
            state=MarketplaceAccessState.ACCESS_BLOCKED,
            message=(
                "eBay returned an access/error page "
                "to the deployed worker."
            ),
        )

    required_normal_markers = (
        "search for anything",
        "shop by category",
    )

    normal_page = (
        status_code is not None
        and 200 <= status_code < 400
        and all(
            marker in normalized_body
            for marker in required_normal_markers
        )
    )

    if normal_page:
        return MarketplacePageResult(
            state=MarketplaceAccessState.AVAILABLE,
            message="eBay responded with its normal marketplace page.",
        )

    return MarketplacePageResult(
        state=MarketplaceAccessState.UNKNOWN_ERROR,
        message="eBay returned an unrecognized response.",
    )
