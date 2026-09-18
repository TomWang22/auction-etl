"""NEW_IDENTITY_COUNT=0 must never reach backup, apply, or refresh."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts.run_ebay_external_handoff import (
    run_operator,
)
from tests.test_run_ebay_external_handoff import (
    dry_run_output,
    operator_args,
    write_valid_artifact,
)


def test_zero_new_identity_count_cannot_reach_backup_write_or_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Zero novelty must return before backup, import/apply, or refresh."""

    source = inspect.getsource(
        run_operator
    )
    novelty_gate = source.index(
        "if novelty < 1:"
    )
    early_return = source.index(
        "return 0",
        novelty_gate,
    )
    backup = source.index(
        "backup_database("
    )
    apply_label = source.index(
        "APPLY EXACT STRUCTURED ARTIFACT"
    )
    refresh_label = source.index(
        "EXACT-ID REAL REFRESH"
    )

    assert novelty_gate < early_return
    assert early_return < backup
    assert backup < apply_label
    assert apply_label < refresh_label

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
            "NEW_IDENTITY_COUNT=0 reached write/refresh: "
            f"{label}"
        )

    def forbid_backup(
        **kwargs: object,
    ) -> Path:
        del kwargs
        raise AssertionError(
            "NEW_IDENTITY_COUNT=0 reached backup_database()."
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
        forbid_backup,
    )

    assert run_operator(
        args
    ) == 0

    output = capsys.readouterr().out

    assert calls == [
        "HEADED STRUCTURED EBAY ACQUISITION",
        "STRUCTURED IMPORTER DRY RUN",
    ]
    assert "NEW_IDENTITY_COUNT=0" in output
    assert "STRUCTURED_EBAY_APPLY_RUN=false" in output
    assert "DATABASE_WRITE=false" in output
    assert "REAL_REFRESH_RUN=false" in output
    assert "NEW_EBAY_ROWS_INSERTED=0" in output
    assert "WAREHOUSE_EBAY_ROW_DELTA=0" in output
    assert "WAREHOUSE_INCREASE_MATCHES_INSERTED_ROWS=true" in output
    assert "NEW_EBAY_LISTING_IDS=" in output
    assert "NEW_EBAY_LISTING_ID=" not in output.replace(
        "NEW_EBAY_LISTING_IDS=",
        "",
    )
    assert "POST_RUN_DB_VERIFICATION=PASS" in output
    assert "APPLY EXACT STRUCTURED ARTIFACT" not in output
    assert "EXACT-ID REAL REFRESH" not in output
    assert "Backup:" not in output
