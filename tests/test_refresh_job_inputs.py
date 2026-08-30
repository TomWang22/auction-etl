from __future__ import annotations

import pytest

from auction_etl.services.refresh_job_inputs import (
    MAX_EBAY_INPUT_BYTES,
    validate_structured_ebay_input,
)


def _valid() -> dict[str, object]:
    return {
        "schema": "ebay-structured/v1",
        "source_name": "facerecords",
        "collector_url": "collector://ebay/facerecords",
        "listing_count": 1,
        "listings": [
            {
                "item_id": "336705604106",
                "url": "https://www.ebay.com/itm/336705604106",
                "title": "Teresa Teng LP",
            }
        ],
    }


def test_valid_input() -> None:
    value = validate_structured_ebay_input(_valid())
    assert value.source_name == "facerecords"
    assert value.collector_url == "collector://ebay/facerecords"
    assert value.byte_length > 0
    assert len(value.sha256) == 64


def test_wrong_provenance_rejected() -> None:
    payload = _valid()
    payload["collector_url"] = "collector://ebay/other"
    with pytest.raises(ValueError, match="collector_url"):
        validate_structured_ebay_input(payload)


def test_conflicting_duplicate_rejected() -> None:
    payload = _valid()
    payload["listing_count"] = 2
    payload["listings"] = [
        {
            "item_id": "336705604106",
            "url": "https://www.ebay.com/itm/336705604106",
            "title": "A",
        },
        {
            "item_id": "336705604106",
            "url": "https://www.ebay.com/itm/336705604106",
            "title": "B",
        },
    ]
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        validate_structured_ebay_input(payload)


def test_oversized_rejected() -> None:
    payload = _valid()
    payload["padding"] = "x" * (MAX_EBAY_INPUT_BYTES + 1)
    with pytest.raises(ValueError, match="384 KiB"):
        validate_structured_ebay_input(payload)
