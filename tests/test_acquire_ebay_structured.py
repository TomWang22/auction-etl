"""Tests for the DB-free structured eBay acquisition producer."""

from __future__ import annotations

import json
from pathlib import Path

from urllib.parse import parse_qs, urlsplit

import pytest

from auction_etl.collectors.ebay_compat import (
    EbayListing,
    render_search_page,
)
from scripts.acquire_ebay_structured import (
    AcquiredPage,
    EbayAcquisitionError,
    assemble_search_window,
    atomic_write_json,
    build_payload_from_html,
    canonical_listings,
    collector_url_for_source,
    has_next_page,
    is_access_block_status,
    is_ebay_url,
    is_signin_url,
    merge_window_listings,
    require_max_pages,
    search_page_url,
)


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts" / "acquire_ebay_structured.py"
SOLD_SEARCH_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw=teresa+teng"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"
)


def item_id_at(index: int) -> str:
    """Return one 11-digit synthetic eBay item ID."""

    return f"{10_000_000_000 + index}"


def listing_for(item_id: str) -> EbayListing:
    """Return one parser-compatible listing."""

    return EbayListing(
        item_id=item_id,
        url=f"https://www.ebay.com/itm/{item_id}",
        title=f"Teresa Teng listing {item_id}",
    )


def page_html(
    item_ids: list[str],
    *,
    next_page: bool,
) -> str:
    """Render one results page with an optional next-page link."""

    html = render_search_page(
        [
            listing_for(item_id)
            for item_id in item_ids
        ]
    )

    if not next_page:
        return html

    return html.replace(
        "</body>",
        (
            '<a class="pagination__next" '
            'href="/sch/i.html?_pgn=2"></a></body>'
        ),
        1,
    )


@pytest.mark.parametrize(
    "status",
    [
        401,
        403,
        429,
    ],
)
def test_access_block_statuses_fail_closed(
    status: int,
) -> None:
    """Recognize explicit eBay HTTP access blocks."""

    assert is_access_block_status(
        status
    ) is True


@pytest.mark.parametrize(
    "status",
    [
        None,
        200,
        301,
        404,
        500,
    ],
)
def test_other_statuses_are_not_access_block_classification(
    status: int | None,
) -> None:
    """Do not misclassify unrelated HTTP outcomes."""

    assert is_access_block_status(
        status
    ) is False


def test_ebay_url_validation() -> None:
    """Accept eBay HTTPS URLs and reject unrelated hosts."""

    assert is_ebay_url(
        "https://www.ebay.com/sch/i.html"
    )
    assert is_ebay_url(
        "https://www.ebay.co.uk/sch/i.html"
    )
    assert not is_ebay_url(
        "http://www.ebay.com/sch/i.html"
    )
    assert not is_ebay_url(
        "https://example.com/ebay"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://signin.ebay.com/ws/eBayISAPI.dll",
        "https://www.ebay.com/signin/",
        "https://www.ebay.co.uk/signin",
    ],
)
def test_signin_urls_are_detected(
    url: str,
) -> None:
    """Classify eBay authentication redirects before parsing."""

    assert is_signin_url(
        url
    ) is True


def test_collector_url_encodes_source_name() -> None:
    """Build the raw-page namespace expected by the refresh handoff."""

    assert (
        collector_url_for_source(
            "face records"
        )
        == "collector://ebay/face%20records"
    )


def test_canonical_listings_deduplicate_identical_records() -> None:
    """Collapse identical duplicate item identities deterministically."""

    records = [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        },
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        },
    ]

    assert canonical_listings(
        records
    ) == [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        }
    ]


def test_canonical_listings_reject_conflicting_identity() -> None:
    """Never silently merge contradictory records for one item ID."""

    records = [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "First title",
        },
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Different title",
        },
    ]

    with pytest.raises(
        EbayAcquisitionError,
        match="Conflicting duplicate",
    ):
        canonical_listings(
            records
        )


def test_canonical_listings_preserve_first_seen_order() -> None:
    """Newest-first page order must not be rewritten by item-ID sort."""

    records = [
        {
            "item_id": "188586715118",
            "url": "https://www.ebay.com/itm/188586715118",
            "title": "Second",
        },
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "First",
        },
    ]

    assert [
        record["item_id"]
        for record in canonical_listings(records)
    ] == [
        "188586715118",
        "188586715117",
    ]


def test_search_page_url_keeps_sold_filters_and_omits_ipg() -> None:
    """Pagination may add _pgn only; sold/newest filters stay intact."""

    first = search_page_url(SOLD_SEARCH_URL, 1)
    second = search_page_url(SOLD_SEARCH_URL, 2)
    first_query = parse_qs(urlsplit(first).query)
    second_query = parse_qs(urlsplit(second).query)

    assert first == SOLD_SEARCH_URL
    assert "_pgn" not in first_query
    assert "_ipg" not in first_query
    assert first_query["LH_Sold"] == ["1"]
    assert first_query["LH_Complete"] == ["1"]
    assert first_query["_sop"] == ["13"]
    assert second_query["_pgn"] == ["2"]
    assert "_ipg" not in second_query
    assert second_query["LH_Sold"] == ["1"]
    assert second_query["LH_Complete"] == ["1"]
    assert second_query["_sop"] == ["13"]


def test_search_page_url_rejects_ipg() -> None:
    """Never widen the result window with _ipg."""

    with pytest.raises(
        EbayAcquisitionError,
        match="_ipg",
    ):
        search_page_url(
            SOLD_SEARCH_URL + "&_ipg=240",
            1,
        )


def test_require_max_pages_production_minimum_is_two() -> None:
    """Page-1-only acquisition is not a supported operator window."""

    assert require_max_pages(2, configured_max_pages=25) == 2
    assert require_max_pages(25, configured_max_pages=25) == 25

    with pytest.raises(
        EbayAcquisitionError,
        match="Configured max_pages must be at least 2",
    ):
        require_max_pages(2, configured_max_pages=1)

    with pytest.raises(
        EbayAcquisitionError,
        match="at least 2",
    ):
        require_max_pages(1, configured_max_pages=25)

    with pytest.raises(
        EbayAcquisitionError,
        match="configured max_pages",
    ):
        require_max_pages(26, configured_max_pages=25)


def test_merge_window_listings_deduplicate_first_seen() -> None:
    """Cross-page overlap keeps the earlier newest-first identity."""

    merged: dict[str, dict[str, str]] = {}
    first = canonical_listings(
        [
            {
                "item_id": "100000000001",
                "url": "https://www.ebay.com/itm/100000000001",
                "title": "Page one",
            }
        ]
    )
    second = canonical_listings(
        [
            {
                "item_id": "100000000001",
                "url": "https://www.ebay.com/itm/100000000001",
                "title": "Page one",
            },
            {
                "item_id": "100000000002",
                "url": "https://www.ebay.com/itm/100000000002",
                "title": "Page two",
            },
        ]
    )

    assert merge_window_listings(merged, first) == 1
    assert merge_window_listings(merged, second) == 1
    assert list(merged) == [
        "100000000001",
        "100000000002",
    ]


def test_two_sixty_item_pages_with_one_overlap_yield_119_identities() -> None:
    """Diagnostic contract for the observed page-1/page-2 sold window."""

    page_one_ids = [item_id_at(index) for index in range(60)]
    page_two_ids = [item_id_at(59)] + [
        item_id_at(index)
        for index in range(60, 119)
    ]
    pages = {
        1: AcquiredPage(
            requested_url=search_page_url(SOLD_SEARCH_URL, 1),
            final_url=search_page_url(SOLD_SEARCH_URL, 1),
            http_status=200,
            item_link_count=60,
            html=page_html(page_one_ids, next_page=True),
        ),
        2: AcquiredPage(
            requested_url=search_page_url(SOLD_SEARCH_URL, 2),
            final_url=search_page_url(SOLD_SEARCH_URL, 2),
            http_status=200,
            item_link_count=60,
            html=page_html(page_two_ids, next_page=True),
        ),
    }

    def fetch_page(
        url: str,
        **kwargs: object,
    ) -> AcquiredPage:
        del kwargs
        page_number = int(
            parse_qs(urlsplit(url).query).get("_pgn", ["1"])[0]
        )
        return pages[page_number]

    window = assemble_search_window(
        source_url=SOLD_SEARCH_URL,
        source_name="facerecords",
        max_pages=2,
        configured_max_pages=25,
        fetch_page=fetch_page,
    )

    assert window.page_count == 2
    assert window.stop_reason == "max_pages"
    assert window.unique_identity_count == 119
    assert [
        listing["item_id"]
        for listing in window.listings
    ] == page_one_ids + page_two_ids[1:]
    assert "_ipg" not in window.source_url
    assert has_next_page(pages[1].html) is True


def test_search_window_stops_when_there_is_no_next_page() -> None:
    """A missing next-page link stops before applying or fetching further."""

    only_ids = [item_id_at(index) for index in range(3)]
    fetched: list[str] = []

    def fetch_page(
        url: str,
        **kwargs: object,
    ) -> AcquiredPage:
        del kwargs
        fetched.append(url)
        return AcquiredPage(
            requested_url=url,
            final_url=url,
            http_status=200,
            item_link_count=3,
            html=page_html(only_ids, next_page=False),
        )

    window = assemble_search_window(
        source_url=SOLD_SEARCH_URL,
        source_name="facerecords",
        max_pages=2,
        configured_max_pages=25,
        fetch_page=fetch_page,
    )

    assert window.page_count == 1
    assert window.stop_reason == "no_next_page"
    assert window.unique_identity_count == 3
    assert len(fetched) == 1


def test_search_window_stops_on_repeated_page_identities() -> None:
    """A repeated identity set is a safe stop, not a write."""

    ids = [item_id_at(index) for index in range(3)]
    fetched: list[int] = []

    def fetch_page(
        url: str,
        **kwargs: object,
    ) -> AcquiredPage:
        del kwargs
        page_number = int(
            parse_qs(urlsplit(url).query).get("_pgn", ["1"])[0]
        )
        fetched.append(page_number)
        return AcquiredPage(
            requested_url=url,
            final_url=url,
            http_status=200,
            item_link_count=3,
            html=page_html(ids, next_page=True),
        )

    window = assemble_search_window(
        source_url=SOLD_SEARCH_URL,
        source_name="facerecords",
        max_pages=2,
        configured_max_pages=25,
        fetch_page=fetch_page,
    )

    assert fetched == [1, 2]
    assert window.page_count == 2
    assert window.stop_reason == "repeated_page"
    assert window.unique_identity_count == 3


def test_search_window_fetches_exactly_two_pages_when_bounded() -> None:
    """max_pages=2 must request _pgn=1 and _pgn=2, never page 3."""

    fetched: list[str] = []

    def fetch_page(
        url: str,
        **kwargs: object,
    ) -> AcquiredPage:
        del kwargs
        fetched.append(url)
        page_number = int(
            parse_qs(urlsplit(url).query).get("_pgn", ["1"])[0]
        )
        ids = [item_id_at(page_number * 10 + index) for index in range(2)]
        return AcquiredPage(
            requested_url=url,
            final_url=url,
            http_status=200,
            item_link_count=2,
            html=page_html(ids, next_page=True),
        )

    window = assemble_search_window(
        source_url=SOLD_SEARCH_URL,
        source_name="facerecords",
        max_pages=2,
        configured_max_pages=25,
        fetch_page=fetch_page,
    )

    assert [parse_qs(urlsplit(url).query).get("_pgn", ["1"])[0] for url in fetched] == [
        "1",
        "2",
    ]
    assert window.page_count == 2
    assert window.stop_reason == "max_pages"
    assert window.unique_identity_count == 4


def test_empty_first_page_fails_closed() -> None:
    """A zero-listing first page must not produce an applyable window."""

    def fetch_page(
        url: str,
        **kwargs: object,
    ) -> AcquiredPage:
        del kwargs
        return AcquiredPage(
            requested_url=url,
            final_url=url,
            http_status=200,
            item_link_count=0,
            html=page_html([], next_page=True),
        )

    with pytest.raises(
        EbayAcquisitionError,
        match="zero parser-compatible",
    ):
        assemble_search_window(
            source_url=SOLD_SEARCH_URL,
            source_name="facerecords",
            max_pages=2,
            configured_max_pages=25,
            fetch_page=fetch_page,
        )


def test_compatibility_parser_roundtrip() -> None:
    """Reuse the established parser contract for producer output."""

    html = render_search_page(
        [
            EbayListing(
                item_id="188586715117",
                url=(
                    "https://www.ebay.com/"
                    "itm/188586715117"
                ),
                title="Teresa Teng LP",
                price="$42.00",
                shipping="$5.00 shipping",
                bids="3 bids",
                location="Japan",
                seller="facerecords",
                seller_feedback="99.8% positive",
                subtitle="Used",
                ended="Sold Aug 26, 2026",
                image_url="https://example.com/item.jpg",
            )
        ]
    )

    payload = build_payload_from_html(
        html=html,
        source_name="facerecords",
        requested_url=(
            "https://www.ebay.com/"
            "sch/i.html?_ssn=facerecords"
        ),
        final_url=(
            "https://www.ebay.com/"
            "sch/i.html?_ssn=facerecords"
        ),
        http_status=200,
        item_link_count=1,
        collected_at_utc="2026-08-27T22:30:00Z",
    )

    assert payload["schema"] == (
        "auction-etl/ebay-structured-acquisition/v1"
    )
    assert payload["collector_url"] == (
        "collector://ebay/facerecords"
    )
    assert payload["listing_count"] == 1

    listings = payload["listings"]

    assert isinstance(
        listings,
        list,
    )

    listing = listings[0]

    assert listing["item_id"] == "188586715117"
    assert listing["title"] == "Teresa Teng LP"
    assert listing["seller"] == "facerecords"


def test_atomic_write_json(
    tmp_path: Path,
) -> None:
    """Write one deterministic JSON artifact without partial output."""

    output = (
        tmp_path
        / "facerecords.json"
    )

    payload = {
        "schema": "test/v1",
        "listings": [
            {
                "item_id": "188586715117",
                "url": "https://www.ebay.com/itm/188586715117",
                "title": "Example",
            }
        ],
    }

    atomic_write_json(
        output,
        payload,
    )

    assert json.loads(
        output.read_text(
            encoding="utf-8"
        )
    ) == payload

    assert list(
        tmp_path.glob(
            ".*.tmp"
        )
    ) == []


def test_producer_has_no_database_or_scroll_path() -> None:
    """Keep acquisition isolated from DB writes and scrolling behavior."""

    source = PRODUCER.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "SessionLocal",
        "DATABASE_URL",
        "warehouse.auction",
        "staging.listing",
        "mouse.wheel",
        "scrollBy",
        "scrollTo",
        "--disable-dev-shm-usage",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_producer_checks_http_block_before_result_wait() -> None:
    """Explicit HTTP blocking must precede item-link waiting."""

    source = PRODUCER.read_text(
        encoding="utf-8"
    )

    block_index = source.index(
        "is_access_block_status("
    )
    wait_index = source.index(
        ").first.wait_for(",
        block_index,
    )

    assert block_index < wait_index
