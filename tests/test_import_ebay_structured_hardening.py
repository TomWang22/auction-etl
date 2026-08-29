"""Hardening tests for the operator-mediated structured eBay importer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.import_ebay_structured as importer
from auction_etl.collectors.ebay_compat import EbayListing


def write_json(
    path: Path,
    payload: object,
) -> None:
    """Write one test JSON document."""

    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def listing_record(
    *,
    item_id: str = "188586715117",
    title: str = "Teresa Teng LP",
) -> dict[str, Any]:
    """Return one valid structured listing record."""

    return {
        "item_id": item_id,
        "url": (
            "https://www.ebay.com/itm/"
            f"{item_id}"
        ),
        "title": title,
        "price": "$42.00",
        "seller": "facerecords",
    }


def test_exact_duplicate_item_ids_are_collapsed(
    tmp_path: Path,
) -> None:
    """Treat repeated identical collector records as one identity."""

    path = tmp_path / "input.json"
    record = listing_record()

    write_json(
        path,
        [
            record,
            dict(record),
        ],
    )

    listings = importer.load_listings(
        path
    )

    assert len(listings) == 1
    assert (
        listings[0].item_id
        == "188586715117"
    )


def test_conflicting_duplicate_item_ids_are_rejected(
    tmp_path: Path,
) -> None:
    """Reject two payloads that disagree for the same eBay identity."""

    path = tmp_path / "input.json"

    write_json(
        path,
        [
            listing_record(
                title="First title",
            ),
            listing_record(
                title="Different title",
            ),
        ],
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="Conflicting duplicate eBay item_id",
    ):
        importer.load_listings(
            path
        )


@pytest.mark.parametrize(
    "item_id",
    [
        "123",
        "abc188586715117",
        "188586715117x",
    ],
)
def test_invalid_item_ids_are_rejected(
    tmp_path: Path,
    item_id: str,
) -> None:
    """Require the same numeric identity shape used by acquisition."""

    path = tmp_path / "input.json"

    write_json(
        path,
        [
            {
                "item_id": item_id,
                "url": (
                    "https://www.ebay.com/itm/"
                    "188586715117"
                ),
                "title": "Teresa Teng LP",
            }
        ],
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="9 to 15 decimal digits",
    ):
        importer.load_listings(
            path
        )


def test_non_ebay_item_url_is_rejected(
    tmp_path: Path,
) -> None:
    """Do not accept an arbitrary URL under an eBay identity."""

    path = tmp_path / "input.json"

    record = listing_record()
    record["url"] = (
        "https://example.com/itm/"
        "188586715117"
    )

    write_json(
        path,
        [record],
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="HTTPS ebay.com URL",
    ):
        importer.load_listings(
            path
        )


def test_item_url_identity_must_match_item_id(
    tmp_path: Path,
) -> None:
    """Reject mismatched eBay URL and structured item identities."""

    path = tmp_path / "input.json"

    record = listing_record()
    record["url"] = (
        "https://www.ebay.com/itm/"
        "188586715118"
    )

    write_json(
        path,
        [record],
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="differs from field 'item_id'",
    ):
        importer.load_listings(
            path
        )


def test_wrapper_listing_count_must_match(
    tmp_path: Path,
) -> None:
    """Reject acquisition metadata inconsistent with its payload."""

    path = tmp_path / "input.json"

    write_json(
        path,
        {
            "schema": "example-schema",
            "source_name": "facerecords",
            "collector_url": (
                "collector://ebay/facerecords"
            ),
            "listing_count": 2,
            "listings": [
                listing_record(),
            ],
        },
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="listing_count.*does not match",
    ):
        importer.load_document(
            path
        )


def test_acquisition_metadata_resolves_collector_provenance(
    tmp_path: Path,
) -> None:
    """Use structured acquisition metadata when CLI overrides are absent."""

    path = tmp_path / "input.json"

    write_json(
        path,
        {
            "schema": "example-schema",
            "source_name": "facerecords",
            "collector_url": (
                "collector://ebay/facerecords"
            ),
            "listing_count": 1,
            "listings": [
                listing_record(),
            ],
        },
    )

    document = importer.load_document(
        path
    )

    source_name = importer.resolve_source_name(
        None,
        document.source_name,
    )

    source_url = importer.resolve_collector_url(
        source_name=source_name,
        cli_value=None,
        metadata_value=document.collector_url,
    )

    assert source_name == "facerecords"
    assert (
        source_url
        == "collector://ebay/facerecords"
    )


def test_source_name_and_collector_url_must_agree() -> None:
    """Prevent provenance labels from diverging from raw-page handoff URLs."""

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="conflicts with resolved source name",
    ):
        importer.resolve_collector_url(
            source_name="facerecords",
            cli_value=(
                "collector://ebay/another-seller"
            ),
            metadata_value=None,
        )


def test_main_is_dry_run_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default CLI validation must not even open a database session."""

    path = tmp_path / "input.json"

    write_json(
        path,
        [
            listing_record(),
        ],
    )

    def forbidden_session() -> object:
        raise AssertionError(
            "Dry-run unexpectedly opened a database session."
        )

    monkeypatch.setattr(
        importer,
        "SessionLocal",
        forbidden_session,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_ebay_structured.py",
            str(path),
            "--source-name",
            "facerecords",
        ],
    )

    assert importer.main() == 0

    output = capsys.readouterr().out

    assert "MODE=DRY_RUN" in output
    assert (
        "DATABASE_SESSION_OPENED=false"
        in output
    )
    assert (
        "DATABASE_WRITE_EXECUTED=false"
        in output
    )
    assert (
        "STRUCTURED_EBAY_IMPORT_DRY_RUN=PASS"
        in output
    )


class ExistingImportSession:
    """Minimal session fake for the idempotent reuse path."""

    def __init__(
        self,
        *,
        raw_page: object,
        job: object,
    ) -> None:
        self.raw_page = raw_page
        self.job = job
        self.add_count = 0
        self.flush_count = 0
        self.commit_count = 0

    def scalar(
        self,
        _statement: object,
    ) -> object:
        return self.raw_page

    def get(
        self,
        _model: object,
        _identity: object,
    ) -> object:
        return self.job

    def add(
        self,
        _value: object,
    ) -> None:
        self.add_count += 1

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


def test_identical_existing_raw_page_is_reused_without_write() -> None:
    """A repeated artifact must not create another raw-page ingestion."""

    listing = EbayListing(
        item_id="188586715117",
        url=(
            "https://www.ebay.com/itm/"
            "188586715117"
        ),
        title="Teresa Teng LP",
        price="$42.00",
        seller="facerecords",
    )

    document = importer.StructuredDocument(
        listings=(listing,),
    )

    plan = importer.build_import_plan(
        document=document,
        source_url=(
            "collector://ebay/facerecords"
        ),
    )

    existing_page = SimpleNamespace(
        id=42,
        crawl_job_id=41,
        source="ebay",
        url=plan.source_url,
        sha256=plan.sha256,
        listing_count=1,
    )

    existing_job = SimpleNamespace(
        id=41,
        source="manual",
        status="finished",
    )

    session = ExistingImportSession(
        raw_page=existing_page,
        job=existing_job,
    )

    result = importer.apply_import_plan(
        session=session,  # type: ignore[arg-type]
        plan=plan,
    )

    assert result.created is False
    assert result.job is existing_job
    assert result.raw_page is existing_page
    assert session.add_count == 0
    assert session.flush_count == 0
    assert session.commit_count == 0


def test_non_item_ebay_url_is_rejected(
    tmp_path: Path,
) -> None:
    """Require the eBay item identity in the actual URL path."""

    path = tmp_path / "input.json"

    record = listing_record()
    record["url"] = (
        "https://www.ebay.com/sch/i.html"
        "?next=/itm/188586715117"
    )

    write_json(
        path,
        [record],
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match=r"/itm/<item_id>",
    ):
        importer.load_listings(
            path
        )


def test_public_import_rejects_source_name_provenance_conflict(
    tmp_path: Path,
) -> None:
    """Require wrapper source_name provenance on the public helper path."""

    path = tmp_path / "input.json"

    write_json(
        path,
        {
            "source_name": "facerecords",
            "collector_url": (
                "collector://ebay/facerecords"
            ),
            "listing_count": 1,
            "listings": [
                listing_record(),
            ],
        },
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="source_name metadata",
    ):
        importer.import_structured_ebay(
            session=object(),  # type: ignore[arg-type]
            input_path=path,
            source_url=(
                "collector://ebay/another-seller"
            ),
        )


def test_public_import_rejects_collector_url_provenance_conflict(
    tmp_path: Path,
) -> None:
    """Require wrapper collector_url provenance on the public helper path."""

    path = tmp_path / "input.json"

    write_json(
        path,
        {
            "collector_url": (
                "collector://ebay/facerecords"
            ),
            "listing_count": 1,
            "listings": [
                listing_record(),
            ],
        },
    )

    with pytest.raises(
        importer.StructuredEbayImportError,
        match="collector_url metadata",
    ):
        importer.import_structured_ebay(
            session=object(),  # type: ignore[arg-type]
            input_path=path,
            source_url=(
                "collector://ebay/another-seller"
            ),
        )
