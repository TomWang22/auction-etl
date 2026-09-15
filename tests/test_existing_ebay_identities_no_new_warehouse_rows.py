"""60 already-known eBay IDs parse to a raw page with zero new warehouse identities."""

from __future__ import annotations

from pathlib import Path

from auction_etl.collectors.ebay_compat import EbayListing
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage
from auction_etl.parsers.ebay import parse_search
from auction_etl.services.warehouse import new_warehouse_identities
from scripts.import_ebay_structured import persist_listings

from tests.test_import_ebay_structured import FakeSession


EXISTING_COUNT = 60
EXISTING_ITEM_IDS = tuple(
    f"{10_000_000_000 + index}"
    for index in range(EXISTING_COUNT)
)
WAREHOUSE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "auction_etl"
    / "services"
    / "warehouse.py"
)


def existing_listings() -> list[EbayListing]:
    """Return 60 structured listings already represented in the warehouse."""

    return [
        EbayListing(
            item_id=item_id,
            url=f"https://www.ebay.com/itm/{item_id}",
            title=f"Existing Teresa Teng listing {item_id}",
            price="$12.00",
            seller="facerecords",
            ended="Sold Sep 8, 2026",
        )
        for item_id in EXISTING_ITEM_IDS
    ]


def persist_and_parse() -> tuple[FakeSession, CrawlJob, list[str], RawPage]:
    """Import 60 known IDs as a raw page and parse listing identities."""

    session = FakeSession()
    listings = existing_listings()
    job, raw_page = persist_listings(
        session=session,  # type: ignore[arg-type]
        listings=listings,
        source_url="collector://ebay/facerecords",
    )
    parsed_ids = [
        str(row["item_id"])
        for row in parse_search(raw_page.html)
    ]
    return session, job, parsed_ids, raw_page


def test_sixty_existing_ids_parse_to_zero_new_warehouse_identities() -> None:
    """Headed-style import of known IDs must not inflate warehouse identities."""

    session, job, parsed_ids, raw_page = persist_and_parse()

    assert job.status == "finished"
    assert raw_page.source == "ebay"
    assert raw_page.url == "collector://ebay/facerecords"
    assert raw_page.listing_count == EXISTING_COUNT
    assert raw_page.http_status == 200
    assert len(parsed_ids) == EXISTING_COUNT
    assert parsed_ids == list(EXISTING_ITEM_IDS)
    assert session.commit_count == 1

    new_ids = new_warehouse_identities(
        EXISTING_ITEM_IDS,
        parsed_ids,
    )

    assert new_ids == frozenset()


def test_one_unseen_parsed_id_is_the_only_new_warehouse_identity() -> None:
    """A parsed ID absent from the warehouse is the only new identity."""

    _, _, parsed_ids, _ = persist_and_parse()
    unseen = "199999999999"

    new_ids = new_warehouse_identities(
        EXISTING_ITEM_IDS,
        [*parsed_ids, unseen],
    )

    assert new_ids == frozenset({unseen})


def test_new_warehouse_identities_ignore_blank_ids() -> None:
    """Blank listing IDs are not warehouse identities."""

    assert new_warehouse_identities(
        [" 100 "],
        ["100", "", "  "],
    ) == frozenset()


def test_warehouse_sync_upserts_existing_marketplace_listing_keys() -> None:
    """Existing identities are updated in place, not inserted as new rows."""

    source = WAREHOUSE_SOURCE.read_text(encoding="utf-8")

    assert "on_conflict_do_update(" in source
    assert "uq_auction_marketplace_listing" in source
    assert '"marketplace"' in source
    assert '"listing_id"' in source
    assert "prune: bool = False" in source
