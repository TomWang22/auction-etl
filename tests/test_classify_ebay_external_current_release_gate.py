"""Outer current-release gate accepts applied and zero-novelty no-op terminals."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.classify_ebay_external_current_release_gate import (
    ClassificationError,
    classify_operator_log,
    emit_gate_result,
    parse_arguments,
)


NOOP_LOG = """\
EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS
NEW_IDENTITY_COUNT=0
READY_FOR_STRUCTURED_EBAY_APPLY=false
STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true
STRUCTURED_EBAY_APPLY_RUN=false
DATABASE_WRITE=false
REAL_REFRESH_RUN=false
"""

APPLIED_LOG = """\
EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS
NEW_IDENTITY_COUNT=2
READY_FOR_STRUCTURED_EBAY_APPLY=true
STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=false
STRUCTURED_EBAY_APPLY_RUN=true
DATABASE_WRITE=true
REAL_REFRESH_RUN=true
"""


def test_zero_novelty_log_is_successful_noop() -> None:
    """An identical second headed window must PASS without a write."""

    result = classify_operator_log(
        NOOP_LOG
    )

    assert result.terminal_state == "NOOP_ZERO_NOVELTY"
    assert result.operator_noop is True
    assert result.new_identity_count == 0


def test_applied_log_is_successful_write() -> None:
    """Novel identities plus apply/refresh remain the write terminal."""

    result = classify_operator_log(
        APPLIED_LOG
    )

    assert result.terminal_state == "APPLIED"
    assert result.operator_noop is False
    assert result.new_identity_count == 2


def test_apply_false_without_zero_novelty_safety_set_fails() -> None:
    """STRUCTURED_EBAY_APPLY_RUN=false alone is not a successful no-op."""

    with pytest.raises(
        ClassificationError,
        match="STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true",
    ):
        classify_operator_log(
            "\n".join(
                [
                    "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
                    "NEW_IDENTITY_COUNT=0",
                    "READY_FOR_STRUCTURED_EBAY_APPLY=false",
                    "STRUCTURED_EBAY_APPLY_RUN=false",
                    "DATABASE_WRITE=false",
                    "REAL_REFRESH_RUN=false",
                ]
            )
        )


def test_zero_novelty_with_write_sentinels_fails() -> None:
    """A no-write terminal must not claim a database write or refresh."""

    with pytest.raises(
        ClassificationError,
        match="DATABASE_WRITE=false",
    ):
        classify_operator_log(
            "\n".join(
                [
                    "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
                    "NEW_IDENTITY_COUNT=0",
                    "READY_FOR_STRUCTURED_EBAY_APPLY=false",
                    "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true",
                    "STRUCTURED_EBAY_APPLY_RUN=false",
                    "DATABASE_WRITE=true",
                    "REAL_REFRESH_RUN=false",
                ]
            )
        )


def test_positive_novelty_without_apply_fails() -> None:
    """Novel identities without apply/refresh are not a release PASS."""

    with pytest.raises(
        ClassificationError,
        match="STRUCTURED_EBAY_APPLY_RUN=true",
    ):
        classify_operator_log(
            "\n".join(
                [
                    "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
                    "NEW_IDENTITY_COUNT=2",
                    "STRUCTURED_EBAY_APPLY_RUN=false",
                    "DATABASE_WRITE=false",
                    "REAL_REFRESH_RUN=false",
                ]
            )
        )


def test_conflicting_apply_run_cannot_be_noop() -> None:
    """NOOP_ZERO_NOVELTY must not mask a log that also ran apply."""

    with pytest.raises(
        ClassificationError,
        match="STRUCTURED_EBAY_APPLY_RUN",
    ):
        classify_operator_log(
            NOOP_LOG
            + "STRUCTURED_EBAY_APPLY_RUN=true\n"
        )


def test_conflicting_database_write_cannot_be_noop() -> None:
    """A write sentinel must not hide behind a later DATABASE_WRITE=false."""

    with pytest.raises(
        ClassificationError,
        match="DATABASE_WRITE",
    ):
        classify_operator_log(
            NOOP_LOG
            + "DATABASE_WRITE=true\n"
        )


def test_operator_fail_after_pass_is_not_success() -> None:
    """A later operator FAIL is not a current-release PASS."""

    with pytest.raises(
        ClassificationError,
        match="EBAY_EXTERNAL_HANDOFF_OPERATOR",
    ):
        classify_operator_log(
            NOOP_LOG
            + "EBAY_EXTERNAL_HANDOFF_OPERATOR=FAIL\n"
        )


def test_applied_write_false_conflict_fails() -> None:
    """APPLIED cannot coexist with a no-write sentinel for the same key."""

    with pytest.raises(
        ClassificationError,
        match="DATABASE_WRITE",
    ):
        classify_operator_log(
            APPLIED_LOG
            + "DATABASE_WRITE=false\n"
        )


def test_missing_operator_pass_fails() -> None:
    """Classification requires the operator's own PASS sentinel."""

    with pytest.raises(
        ClassificationError,
        match="EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
    ):
        classify_operator_log(
            NOOP_LOG.replace(
                "EBAY_EXTERNAL_HANDOFF_OPERATOR=PASS",
                "EBAY_EXTERNAL_HANDOFF_OPERATOR=FAIL",
            )
        )


def test_emit_noop_result_matches_outer_gate_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The RESULT block must name the no-op terminal, not invent a write."""

    emit_gate_result(
        classify_operator_log(
            NOOP_LOG
        )
    )
    output = capsys.readouterr().out

    assert "EBAY_EXTERNAL_CURRENT_RELEASE_GATE=PASS" in output
    assert "OPERATOR_TERMINAL_STATE=NOOP_ZERO_NOVELTY" in output
    assert "OPERATOR_NOOP=true" in output
    assert "NEW_IDENTITY_COUNT=0" in output
    assert "STRUCTURED_EBAY_APPLY_SKIPPED_NO_NEW_IDENTITIES=true" in output
    assert "STRUCTURED_EBAY_APPLY_RUN=false" in output
    assert "DATABASE_WRITE=false" in output
    assert "REAL_REFRESH_RUN=false" in output
    assert "SOURCE_COMMIT_CREATED=false" in output
    assert "RAILWAY_CHANGE=false" in output
    assert "VERCEL_CHANGE=false" in output


def test_parse_arguments_requires_operator_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classifier reads a completed log; it does not reacquire eBay."""

    log_path = tmp_path / "operator.log"
    log_path.write_text(
        NOOP_LOG,
        encoding="utf-8",
    )
    monkeypatch.delenv(
        "OPERATOR_LOG",
        raising=False,
    )

    arguments = parse_arguments(
        [
            "--operator-log",
            str(log_path),
        ]
    )

    assert arguments.operator_log == log_path
    assert "acquire" not in str(arguments).casefold()
