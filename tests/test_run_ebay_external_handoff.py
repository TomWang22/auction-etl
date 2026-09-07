"""Tests for the reusable external eBay operator workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_ebay_external_handoff import (
    BROWSER_SKIP_SENTINEL,
    EbaySource,
    OperatorError,
    build_acquisition_command,
    build_refresh_command,
    load_external_source,
    parse_import_plan_summary,
    parse_raw_page_id,
    validate_write_request,
    verify_no_ebay_browser_fallback,
)


def write_source_config(
    path: Path,
    *,
    mode: str,
) -> None:
    """Write one production-shaped eBay source config."""

    path.write_text(
        json.dumps(
            [
                {
                    "name": "facerecords",
                    "enabled": True,
                    "seller": "all-sellers",
                    "profile": "ebay-public",
                    "acquisition_mode": mode,
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_nkw=teresa+teng"
                        "&LH_Complete=1"
                        "&LH_Sold=1"
                        "&_sop=13"
                    ),
                    "wait_seconds": 4,
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_external_source_is_accepted(
    tmp_path: Path,
) -> None:
    """Accept the released external-only production policy."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_source_config(
        config,
        mode="external",
    )

    source = load_external_source(
        config
    )

    assert source == EbaySource(
        name="facerecords",
        url=(
            "https://www.ebay.com/sch/i.html"
            "?_nkw=teresa+teng"
            "&LH_Complete=1"
            "&LH_Sold=1"
            "&_sop=13"
        ),
        wait_seconds=4.0,
    )


def test_browser_policy_is_rejected(
    tmp_path: Path,
) -> None:
    """Never run the operator workflow under browser-fallback policy."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_source_config(
        config,
        mode="browser",
    )

    with pytest.raises(
        OperatorError,
        match="not 'external'",
    ):
        load_external_source(
            config
        )


def test_acquisition_command_is_always_headed(
    tmp_path: Path,
) -> None:
    """The supported operator acquisition must not add --headless."""

    source = EbaySource(
        name="facerecords",
        url=(
            "https://www.ebay.com/sch/i.html"
            "?_nkw=teresa+teng"
            "&LH_Complete=1"
            "&LH_Sold=1"
            "&_sop=13"
        ),
        wait_seconds=4.0,
    )

    state = (
        tmp_path
        / "state.json"
    )

    artifact = (
        tmp_path
        / "artifact.json"
    )

    command = build_acquisition_command(
        source=source,
        storage_state=state,
        artifact=artifact,
        timeout_seconds=45.0,
        settle_seconds=4.0,
    )

    assert "--headless" not in command

    assert (
        command[
            command.index(
                "--storage-state"
            )
            + 1
        ]
        == str(
            state
        )
    )

    assert (
        command[
            command.index(
                "--output"
            )
            + 1
        ]
        == str(
            artifact
        )
    )


def test_write_mode_requires_two_explicit_gates() -> None:
    """Database writes require both apply and confirmation."""

    validate_write_request(
        apply=False,
        confirm_write=False,
        database_url=None,
    )

    with pytest.raises(
        OperatorError,
        match="requires --confirm-write",
    ):
        validate_write_request(
            apply=True,
            confirm_write=False,
            database_url="postgresql://example",
        )

    with pytest.raises(
        OperatorError,
        match="requires --apply",
    ):
        validate_write_request(
            apply=False,
            confirm_write=True,
            database_url="postgresql://example",
        )

    with pytest.raises(
        OperatorError,
        match="requires an explicit database URL",
    ):
        validate_write_request(
            apply=True,
            confirm_write=True,
            database_url=None,
        )

    validate_write_request(
        apply=True,
        confirm_write=True,
        database_url="postgresql://example",
    )


def test_importer_plan_summary_is_parsed() -> None:
    """Recover deterministic dry-run plan metadata."""

    output = (
        "✓ Source         : ebay/facerecords\n"
        "✓ Listings       : 60\n"
        "✓ SHA-256        : "
        "0947866f44e5d0e6e27903a849de9c61"
        "b21636a545837a2676a0f4ecb144c861\n"
        "MODE=DRY_RUN\n"
    )

    sha256, count = (
        parse_import_plan_summary(
            output
        )
    )

    assert sha256 == (
        "0947866f44e5d0e6e27903a849de9c61"
        "b21636a545837a2676a0f4ecb144c861"
    )

    assert count == 60


def test_exact_raw_page_id_is_parsed() -> None:
    """Use only the raw-page identity emitted by the importer."""

    output = (
        "✓ Crawl Job      : 45\n"
        "✓ Raw Page       : 74\n"
        "STRUCTURED_EBAY_RAWPAGE_IMPORT=PASS\n"
    )

    assert (
        parse_raw_page_id(
            output
        )
        == 74
    )


def test_refresh_command_uses_exact_raw_page() -> None:
    """Exact raw-page refresh must use the no-fallback CLI contract."""

    command = build_refresh_command(
        database_url=(
            "postgresql+psycopg://"
            "auction:secret@127.0.0.1:5544/"
            "auction_warehouse"
        ),
        expected_database_name="auction_warehouse",
        expected_database_user="auction",
        raw_page_id=74,
    )

    marker = (
        command.index(
            "--ebay-structured-raw-page-id"
        )
    )

    assert (
        command[
            marker
            + 1
        ]
        == "74"
    )

    assert (
        "scripts/crawl_ebay_sources.py"
        not in command
    )


def test_no_browser_fallback_accepts_exact_handoff_log() -> None:
    """Accept explicit browser-skip evidence."""

    verify_no_ebay_browser_fallback(
        "Using 1 "
        + BROWSER_SKIP_SENTINEL
        + "\n"
        + "Parse eBay source external raw-page handoff\n"
    )


@pytest.mark.parametrize(
    "marker",
    [
        "scripts/crawl_ebay_sources.py",
        "profile=ebay-public",
    ],
)
def test_no_browser_fallback_rejects_browser_evidence(
    marker: str,
) -> None:
    """Reject any eBay crawler/runtime evidence after exact-ID handoff."""

    output = (
        "Using 1 "
        + BROWSER_SKIP_SENTINEL
        + "\n"
        + marker
        + "\n"
    )

    with pytest.raises(
        OperatorError,
        match="browser fallback evidence",
    ):
        verify_no_ebay_browser_fallback(
            output
        )
