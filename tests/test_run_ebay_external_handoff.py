"""Tests for the reusable external eBay operator workflow."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_ebay_external_handoff import (
    ARTIFACT_SCHEMA,
    BROWSER_SKIP_SENTINEL,
    EbaySource,
    OperatorError,
    artifact_listing_ids,
    build_acquisition_command,
    build_refresh_command,
    load_external_source,
    new_identity_count,
    parse_import_plan_summary,
    parse_raw_page_id,
    reject_railway_operator_environment,
    run_child,
    run_operator,
    validate_artifact,
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
        max_pages=2,
    )

    assert "--headless" not in command
    assert "_ipg" not in command
    assert (
        command[
            command.index(
                "--max-pages"
            )
            + 1
        ]
        == "2"
    )

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


def test_acquisition_command_rejects_page_one_only_window(
    tmp_path: Path,
) -> None:
    """The operator must not recreate the shallow page-1 acquisition."""

    source = EbaySource(
        name="facerecords",
        url=SOURCE_URL,
        wait_seconds=4.0,
    )

    with pytest.raises(
        OperatorError,
        match="at least 2",
    ):
        build_acquisition_command(
            source=source,
            storage_state=tmp_path / "state.json",
            artifact=tmp_path / "artifact.json",
            timeout_seconds=45.0,
            settle_seconds=4.0,
            max_pages=1,
        )


def test_public_source_rejects_ipg(
    tmp_path: Path,
) -> None:
    """Configured sold search must not set an _ipg result-size override."""

    config = tmp_path / "ebay.json"
    write_source_config(
        config,
        mode="external",
    )
    payload = json.loads(
        config.read_text(encoding="utf-8")
    )
    payload[0]["url"] += "&_ipg=240"
    config.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        OperatorError,
        match="_ipg",
    ):
        load_external_source(
            config
        )


def test_configured_max_pages_one_is_rejected(
    tmp_path: Path,
) -> None:
    """A configured cap of 1 must not silently override the minimum-2 window."""

    config = tmp_path / "ebay.json"
    write_source_config(
        config,
        mode="external",
    )
    payload = json.loads(
        config.read_text(encoding="utf-8")
    )
    payload[0]["max_pages"] = 1
    config.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        OperatorError,
        match="Configured max_pages must be at least 2",
    ):
        load_external_source(
            config
        )


def test_acquisition_command_rejects_configured_cap_below_minimum(
    tmp_path: Path,
) -> None:
    """Do not treat max_pages=1 as a cap that wins over minimum 2."""

    source = EbaySource(
        name="facerecords",
        url=SOURCE_URL,
        wait_seconds=4.0,
        max_pages=1,
    )

    with pytest.raises(
        OperatorError,
        match="Configured max_pages must be at least 2",
    ):
        build_acquisition_command(
            source=source,
            storage_state=tmp_path / "state.json",
            artifact=tmp_path / "artifact.json",
            timeout_seconds=45.0,
            settle_seconds=4.0,
            max_pages=2,
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


SOURCE_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw=teresa+teng"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"
)


def sample_source() -> EbaySource:
    """Return the production-shaped public eBay source."""

    return EbaySource(
        name="facerecords",
        url=SOURCE_URL,
        wait_seconds=4.0,
    )


def write_valid_artifact(
    path: Path,
    *,
    listings: list[dict[str, object]] | None = None,
    http_status: int = 200,
    final_url: str = SOURCE_URL,
    schema: str = ARTIFACT_SCHEMA,
    source_name: str = "facerecords",
    source_url: str = SOURCE_URL,
) -> str:
    """Write one structured artifact and return its SHA-256."""

    if listings is None:
        listings = [
            {
                "item_id": "123456789012",
                "title": "Teresa Teng LP",
                "url": (
                    "https://www.ebay.com/itm/123456789012"
                ),
            },
            {
                "item_id": "123456789013",
                "title": "Teresa Teng CD",
                "url": (
                    "https://www.ebay.com/itm/123456789013"
                ),
            },
        ]

    payload = {
        "schema": schema,
        "source_name": source_name,
        "source_url": source_url,
        "listing_count": len(listings),
        "listings": listings,
        "page": {
            "http_status": http_status,
            "final_url": final_url,
        },
    }

    path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def operator_args(
    tmp_path: Path,
    *,
    apply: bool = False,
    confirm_write: bool = False,
    database_url: str | None = None,
) -> argparse.Namespace:
    """Build one operator argument namespace."""

    config = tmp_path / "ebay.json"
    write_source_config(
        config,
        mode="external",
    )

    storage_state = tmp_path / "state.json"
    storage_state.write_text(
        '{"cookies":[]}\n',
        encoding="utf-8",
    )

    return argparse.Namespace(
        config=config,
        storage_state=storage_state,
        artifact=tmp_path / "artifact.json",
        timeout_seconds=45.0,
        settle_seconds=None,
        database_url=database_url,
        expected_database_name="auction_warehouse",
        expected_database_user="auction",
        apply=apply,
        confirm_write=confirm_write,
        max_pages=2,
    )


def dry_run_output(
    listing_count: int,
    plan_sha: str,
) -> str:
    """Return importer dry-run stdout."""

    return (
        f"✓ Listings       : {listing_count}\n"
        f"✓ SHA-256        : {plan_sha}\n"
        "MODE=DRY_RUN\n"
        "DATABASE_SESSION_OPENED=false\n"
        "DATABASE_WRITE_EXECUTED=false\n"
        "STRUCTURED_EBAY_IMPORT_DRY_RUN=PASS\n"
    )


def test_artifact_requires_unique_valid_item_ids(
    tmp_path: Path,
) -> None:
    """Reject empty, duplicate, or malformed listing identities."""

    source = sample_source()
    artifact = tmp_path / "artifact.json"

    write_valid_artifact(
        artifact,
        listings=[],
    )

    with pytest.raises(
        OperatorError,
        match="invalid listing count",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )

    write_valid_artifact(
        artifact,
        listings=[
            {
                "item_id": "123456789012",
                "title": "A",
                "url": "https://www.ebay.com/itm/123456789012",
            },
            {
                "item_id": "123456789012",
                "title": "B",
                "url": "https://www.ebay.com/itm/123456789012",
            },
        ],
    )

    with pytest.raises(
        OperatorError,
        match="duplicate",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )

    write_valid_artifact(
        artifact,
        listings=[
            {
                "item_id": "abc",
                "title": "A",
                "url": "https://www.ebay.com/itm/abc",
            }
        ],
    )

    with pytest.raises(
        OperatorError,
        match="item ID",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )


def test_artifact_listing_ids_preserve_validated_order(
    tmp_path: Path,
) -> None:
    """Novelty comparison uses the artifact's listing IDs, not warehouse rows."""

    artifact = tmp_path / "artifact.json"
    write_valid_artifact(
        artifact
    )

    assert artifact_listing_ids(
        artifact
    ) == [
        "123456789012",
        "123456789013",
    ]


def test_new_identity_count_is_zero_when_all_ids_exist() -> None:
    """Known marketplace/listing keys must not arm apply/refresh."""

    assert new_identity_count(
        ["123456789012", "123456789013"],
        ["123456789012", "123456789013"],
    ) == 0


def test_new_identity_count_counts_only_unseen_ids() -> None:
    """Only listing IDs absent from the warehouse are novel."""

    assert new_identity_count(
        ["123456789012"],
        ["123456789012", "123456789013"],
    ) == 1


def test_valid_artifact_returns_listing_count_and_sha(
    tmp_path: Path,
) -> None:
    """Accept a schema-correct non-empty unique-ID artifact."""

    artifact = tmp_path / "artifact.json"
    expected_sha = write_valid_artifact(
        artifact
    )

    count, digest = validate_artifact(
        artifact=artifact,
        source=sample_source(),
    )

    assert count == 2
    assert digest == expected_sha


def test_malformed_artifact_is_rejected(
    tmp_path: Path,
) -> None:
    """Fail closed on schema, host, HTTP, and sign-in failures."""

    source = sample_source()
    artifact = tmp_path / "artifact.json"

    write_valid_artifact(
        artifact,
        schema="wrong-schema",
    )

    with pytest.raises(
        OperatorError,
        match="schema",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )

    write_valid_artifact(
        artifact,
        http_status=403,
    )

    with pytest.raises(
        OperatorError,
        match="HTTP 200",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )

    write_valid_artifact(
        artifact,
        final_url="https://signin.ebay.com/",
    )

    with pytest.raises(
        OperatorError,
        match="sign-in",
    ):
        validate_artifact(
            artifact=artifact,
            source=source,
        )


def test_railway_operator_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never run headed eBay acquisition on Railway."""

    monkeypatch.setenv(
        "RAILWAY_ENVIRONMENT",
        "production",
    )

    with pytest.raises(
        OperatorError,
        match="Railway",
    ):
        reject_railway_operator_environment()


def test_operator_dry_run_stops_before_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --apply the operator validates and stops with no DB write."""

    args = operator_args(
        tmp_path
    )
    plan_sha = "a" * 64
    calls: list[str] = []

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del environment
        calls.append(
            label
        )

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        if label == "STRUCTURED IMPORTER DRY RUN":
            return dry_run_output(
                2,
                plan_sha,
            )

        raise AssertionError(
            f"unexpected child: {label} {command}"
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )

    assert run_operator(
        args
    ) == 0

    output = capsys.readouterr().out

    assert calls == [
        "HEADED STRUCTURED EBAY ACQUISITION",
        "STRUCTURED IMPORTER DRY RUN",
    ]
    assert "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS" in output
    assert "ACQUISITION_MODE=external" in output
    assert "ACQUISITION_HEADLESS=false" in output
    assert "STRUCTURED_ARTIFACT_VALIDATION=PASS" in output
    assert "STRUCTURED_IMPORT_PLAN=PASS" in output
    assert "STRUCTURED_EBAY_APPLY_RUN=false" in output
    assert "DATABASE_WRITE=false" in output
    assert "REAL_REFRESH_RUN=false" in output
    assert "EBAY_BROWSER_ACQUISITION_EXECUTED=false" in output
    assert "EBAY_BROWSER_FALLBACK_PROHIBITED=true" in output


def test_operator_skips_apply_when_artifact_has_no_new_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Zero-novelty artifacts must not backup, import, or refresh."""

    args = operator_args(
        tmp_path,
        apply=True,
        confirm_write=True,
        database_url=(
            "postgresql://auction@127.0.0.1:5544/"
            "auction_warehouse"
        ),
    )
    calls: list[str] = []
    backup_calls = 0

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment
        calls.append(
            label
        )

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        if label == "STRUCTURED IMPORTER DRY RUN":
            return dry_run_output(
                2,
                "e" * 64,
            )

        raise AssertionError(
            f"zero-novelty apply started a write child: {label}"
        )

    def fake_backup(
        **kwargs: object,
    ) -> Path:
        del kwargs
        nonlocal backup_calls
        backup_calls += 1
        raise AssertionError(
            "zero-novelty apply created a database backup."
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.load_ebay_warehouse_identities",
        lambda **kwargs: frozenset(
            {
                "123456789012",
                "123456789013",
            }
        ),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.backup_database",
        fake_backup,
    )

    assert run_operator(
        args
    ) == 0

    output = capsys.readouterr().out

    assert calls == [
        "HEADED STRUCTURED EBAY ACQUISITION",
        "STRUCTURED IMPORTER DRY RUN",
    ]
    assert backup_calls == 0
    assert "NEW_IDENTITY_COUNT=0" in output
    assert "READY_FOR_STRUCTURED_EBAY_APPLY=false" in output
    assert (
        "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true"
        in output
    )
    assert "STRUCTURED_EBAY_APPLY_RUN=false" in output
    assert "DATABASE_WRITE=false" in output
    assert "REAL_REFRESH_RUN=false" in output
    assert "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS" in output


def test_second_identical_headed_apply_is_zero_novelty_and_does_not_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A replay of the same headed window must not backup, import, or refresh."""

    listings = [
        {
            "item_id": "177308895133",
            "title": "Teresa Teng LP",
            "url": "https://www.ebay.com/itm/177308895133",
        },
        {
            "item_id": "297503882046",
            "title": "Teresa Teng CD",
            "url": "https://www.ebay.com/itm/297503882046",
        },
    ]
    warehouse_ids: set[str] = set()
    backup_calls = 0
    write_labels: list[str] = []

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment
        write_labels.append(
            label
        )

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                current_artifact,
                listings=listings,
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        if label == "STRUCTURED IMPORTER DRY RUN":
            return dry_run_output(
                len(listings),
                "a" * 64,
            )

        if label == "APPLY EXACT STRUCTURED ARTIFACT":
            warehouse_ids.update(
                listing["item_id"]
                for listing in listings
                if isinstance(listing["item_id"], str)
            )
            return (
                "✓ Raw Page       : 180\n"
                "IDEMPOTENT_REUSE=false\n"
                "STRUCTURED_EBAY_RAWPAGE_IMPORT=PASS\n"
            )

        if label == "EXACT-ID REAL REFRESH":
            return (
                "Using 1 "
                + BROWSER_SKIP_SENTINEL
                + "\n"
            )

        raise AssertionError(
            f"unexpected child: {label}"
        )

    current_artifact = tmp_path / "unused.json"

    def fake_backup(
        **kwargs: object,
    ) -> Path:
        del kwargs
        nonlocal backup_calls
        backup_calls += 1
        return tmp_path / "backup.sql"

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.load_ebay_warehouse_identities",
        lambda **kwargs: frozenset(warehouse_ids),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.database_snapshot",
        lambda **kwargs: SimpleNamespace(
            database_name="auction_warehouse",
            database_user="auction",
            ebay_rows=881,
            raw_page_parsed=True,
        ),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.backup_database",
        fake_backup,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.resolve_status_file",
        lambda: tmp_path / "status.json",
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.verify_refresh_status",
        lambda status_file: 881,
    )

    first = tmp_path / "first"
    first.mkdir()
    current_artifact = first / "artifact.json"
    first_args = operator_args(
        first,
        apply=True,
        confirm_write=True,
        database_url=(
            "postgresql://auction@127.0.0.1:5544/"
            "auction_warehouse"
        ),
    )
    first_args.artifact = current_artifact

    assert run_operator(
        first_args
    ) == 0
    first_output = capsys.readouterr().out

    assert "NEW_IDENTITY_COUNT=2" in first_output
    assert "DATABASE_WRITE=true" in first_output
    assert warehouse_ids == {
        "177308895133",
        "297503882046",
    }
    assert backup_calls == 1
    assert "APPLY EXACT STRUCTURED ARTIFACT" in write_labels
    assert "EXACT-ID REAL REFRESH" in write_labels

    second = tmp_path / "second"
    second.mkdir()
    current_artifact = second / "artifact.json"
    write_labels.clear()
    second_args = operator_args(
        second,
        apply=True,
        confirm_write=True,
        database_url=(
            "postgresql://auction@127.0.0.1:5544/"
            "auction_warehouse"
        ),
    )
    second_args.artifact = current_artifact

    assert run_operator(
        second_args
    ) == 0
    second_output = capsys.readouterr().out

    assert write_labels == [
        "HEADED STRUCTURED EBAY ACQUISITION",
        "STRUCTURED IMPORTER DRY RUN",
    ]
    assert backup_calls == 1
    assert "NEW_IDENTITY_COUNT=0" in second_output
    assert "READY_FOR_STRUCTURED_EBAY_APPLY=false" in second_output
    assert (
        "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true"
        in second_output
    )
    assert "STRUCTURED_EBAY_APPLY_RUN=false" in second_output
    assert "DATABASE_WRITE=false" in second_output
    assert "REAL_REFRESH_RUN=false" in second_output
    assert "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS" in second_output


def test_operator_rejects_confirmation_failure(
    tmp_path: Path,
) -> None:
    """--apply without --confirm-write must not start acquisition."""

    args = operator_args(
        tmp_path,
        apply=True,
        confirm_write=False,
        database_url="postgresql://auction@127.0.0.1/auction_warehouse",
    )

    with pytest.raises(
        OperatorError,
        match="requires --confirm-write",
    ):
        run_operator(
            args
        )


def test_operator_fails_closed_on_acquisition_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not retry or fall back when headed acquisition fails."""

    args = operator_args(
        tmp_path
    )
    calls = 0

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment
        nonlocal calls
        calls += 1

        raise OperatorError(
            f"{label} failed with exit code 2."
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )

    with pytest.raises(
        OperatorError,
        match="HEADED STRUCTURED EBAY ACQUISITION",
    ):
        run_operator(
            args
        )

    assert calls == 1
    assert not args.artifact.exists()


def test_operator_fails_closed_on_importer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dry-run importer failure must not apply or refresh."""

    args = operator_args(
        tmp_path
    )

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        raise OperatorError(
            f"{label} failed with exit code 3."
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )

    with pytest.raises(
        OperatorError,
        match="STRUCTURED IMPORTER DRY RUN",
    ):
        run_operator(
            args
        )


def test_operator_fails_closed_on_artifact_mutation_after_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-check the immutable artifact SHA after importer dry-run."""

    args = operator_args(
        tmp_path
    )

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        args.artifact.write_text(
            args.artifact.read_text(
                encoding="utf-8"
            )
            + " \n",
            encoding="utf-8",
        )

        return dry_run_output(
            2,
            "b" * 64,
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )

    with pytest.raises(
        OperatorError,
        match="artifact changed",
    ):
        run_operator(
            args
        )


def test_operator_fails_closed_on_database_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply mode must verify the explicit database identity first."""

    args = operator_args(
        tmp_path,
        apply=True,
        confirm_write=True,
        database_url=(
            "postgresql://auction@127.0.0.1:5544/"
            "auction_warehouse"
        ),
    )

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        if label == "STRUCTURED IMPORTER DRY RUN":
            return dry_run_output(
                2,
                "c" * 64,
            )

        raise AssertionError(
            f"refresh/apply started after DB mismatch: {label}"
        )

    def fake_snapshot(
        **kwargs: object,
    ) -> object:
        del kwargs
        raise OperatorError(
            "Database name mismatch: "
            "expected 'auction_warehouse', found 'other'."
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.load_ebay_warehouse_identities",
        lambda **kwargs: frozenset(),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.database_snapshot",
        fake_snapshot,
    )

    with pytest.raises(
        OperatorError,
        match="Database name mismatch",
    ):
        run_operator(
            args
        )


def test_operator_apply_uses_exact_raw_page_and_emits_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply once, refresh by exact raw-page ID, and emit final sentinels."""

    args = operator_args(
        tmp_path,
        apply=True,
        confirm_write=True,
        database_url=(
            "postgresql://auction@127.0.0.1:5544/"
            "auction_warehouse"
        ),
    )
    refresh_commands: list[list[str]] = []

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del environment

        if label == "HEADED STRUCTURED EBAY ACQUISITION":
            write_valid_artifact(
                args.artifact
            )
            return (
                "EBAY_STRUCTURED_ACQUISITION=PASS\n"
                "DATABASE_REQUEST_EXECUTED=false\n"
            )

        if label == "STRUCTURED IMPORTER DRY RUN":
            return dry_run_output(
                2,
                "d" * 64,
            )

        if label == "APPLY EXACT STRUCTURED ARTIFACT":
            return (
                "✓ Raw Page       : 74\n"
                "IDEMPOTENT_REUSE=false\n"
                "STRUCTURED_EBAY_RAWPAGE_IMPORT=PASS\n"
            )

        if label == "EXACT-ID REAL REFRESH":
            refresh_commands.append(
                command
            )
            return (
                "Using 1 "
                + BROWSER_SKIP_SENTINEL
                + "\n"
            )

        raise AssertionError(
            f"unexpected child: {label}"
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_child",
        fake_run_child,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.load_ebay_warehouse_identities",
        lambda **kwargs: frozenset(),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.database_snapshot",
        lambda **kwargs: SimpleNamespace(
            database_name="auction_warehouse",
            database_user="auction",
            ebay_rows=820,
            raw_page_parsed=True,
        ),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.backup_database",
        lambda **kwargs: tmp_path / "backup.sql",
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.resolve_status_file",
        lambda: tmp_path / "status.json",
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.verify_refresh_status",
        lambda status_file: 820,
    )

    assert run_operator(
        args
    ) == 0

    output = capsys.readouterr().out
    refresh_command = refresh_commands[0]
    marker = refresh_command.index(
        "--ebay-structured-raw-page-id"
    )

    assert refresh_command[marker + 1] == "74"
    assert "scripts/crawl_ebay_sources.py" not in refresh_command
    assert "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS" in output
    assert "STRUCTURED_EBAY_APPLY_RUN=true" in output
    assert "STRUCTURED_EBAY_RAW_PAGE_ID=74" in output
    assert "EXACT_STRUCTURED_RAW_PAGE_PARSED=true" in output
    assert "EBAY_BROWSER_ACQUISITION_EXECUTED=false" in output
    assert "EBAY_BROWSER_FALLBACK_PROHIBITED=true" in output
    assert "REFRESH_EBAY_MARKETPLACE_STATE=done" in output
    assert (
        "REFRESH_EBAY_RUNTIME_SEMANTICS=EBAY_SOURCE_AVAILABLE"
        in output
    )
    assert "DATABASE_WRITE=true" in output
    assert "REAL_REFRESH_RUN=true" in output
    assert output.count("DATABASE_WRITE=") == 1
    assert output.count("REAL_REFRESH_RUN=") == 1
    assert "NEW_IDENTITY_COUNT=2" in output
    assert "READY_FOR_STRUCTURED_EBAY_APPLY=true" in output
    assert (
        "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=false"
        in output
    )


def test_operator_source_never_retries_or_enables_headless() -> None:
    """AST/source invariant: one headed acquisition, no crawler fallback."""

    source = inspect.getsource(
        run_operator
    )

    assert "build_acquisition_command(" in source
    assert source.count(
        "HEADED STRUCTURED EBAY ACQUISITION"
    ) == 1
    assert "for attempt" not in source
    assert "retry" not in source.casefold()
    assert "--headless" not in source
    assert "crawl_ebay_sources.py" not in source
    assert "--ebay-structured-raw-page-id" in source
    assert "NEW_IDENTITY_COUNT" in source
    assert "load_ebay_warehouse_identities(" in source
    assert "new_identity_count(" in source
    assert "max_pages" in source
    assert "backup_database(" in source
    novelty = source.index("new_identity_count(")
    backup = source.index("backup_database(")
    assert novelty < backup


def test_run_child_hides_nested_refresh_write_sentinels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Operator logs keep one terminal DATABASE_WRITE and REAL_REFRESH_RUN."""

    class Result:
        stdout = (
            "BUYEE_PUBLIC_SKIPPED=true\n"
            "BUYEE_PUBLIC_SOURCES=PASS\n"
            "DATABASE_WRITE=false\n"
            "REAL_REFRESH_RUN=false\n"
            "Using 1 pending external eBay raw page(s); "
            "browser crawl skipped.\n"
        )
        returncode = 0

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    returned = run_child(
        label="EXACT-ID REAL REFRESH",
        command=["true"],
        environment={},
    )
    printed = capsys.readouterr().out

    assert "BUYEE_PUBLIC_SKIPPED=true" in printed
    assert "DATABASE_WRITE=" not in printed
    assert "REAL_REFRESH_RUN=" not in printed
    assert "DATABASE_WRITE=" not in returned
    assert "REAL_REFRESH_RUN=" not in returned
    assert BROWSER_SKIP_SENTINEL in returned
    assert "public_child_output(" in inspect.getsource(
        run_child
    )
