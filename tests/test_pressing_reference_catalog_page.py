"""Static contract tests for the pressing-reference UI."""

from pathlib import Path


PAGE = Path(
    "app/pages/14_Pressing_Reference_Catalog.py"
)


def test_page_contains_physical_identity_fields() -> None:
    source = PAGE.read_text(
        encoding="utf-8"
    )

    for required in (
        "Canonical release title",
        "Catalog number",
        "Matrix / runout",
        "Release country",
        "Release language",
        "Release year",
        "Physical format",
        "Release type",
        "Edition / pressing notes",
    ):
        assert required in source


def test_page_explicitly_separates_auction_observations() -> None:
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "Auction prices, sellers, bids, listing outcomes"
        in source
    )

    for forbidden_query_field in (
        "gross_price",
        "final_price",
        "start_price",
        "tax_amount",
        "bid_count",
        "hammer_before_tax",
    ):
        assert forbidden_query_field not in source
