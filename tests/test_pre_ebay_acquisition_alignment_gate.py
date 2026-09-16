"""The pre-acquisition alignment gate must live in-repo and stay HEAD-default."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = (
    ROOT
    / "scripts"
    / "pre_ebay_acquisition_alignment_gate.sh"
)
PINNED_RELEASE = (
    "91f2a37eaa56a2d59a1ab3c791e922e172062ed9"
)


def test_pre_acquisition_gate_is_versioned_in_the_repository() -> None:
    """The gate cannot live only in /tmp."""

    assert GATE.is_file()
    assert GATE.read_text(
        encoding="utf-8"
    ).startswith(
        "#!/usr/bin/env bash"
    )


def test_pre_acquisition_gate_defaults_expected_sha_to_head() -> None:
    """A committed gate cannot freeze the previous release SHA as current."""

    source = GATE.read_text(
        encoding="utf-8"
    )

    assert "git rev-parse HEAD" in source
    assert "scripts/verify_release_alignment.py" in source
    assert "--expected-sha" in source
    assert PINNED_RELEASE not in source


def test_pre_acquisition_gate_runs_operator_only_when_requested() -> None:
    """RUN_OPERATOR=1 is the only path that opens headed Chromium."""

    source = GATE.read_text(
        encoding="utf-8"
    )

    assert 'RUN_OPERATOR="${RUN_OPERATOR:-0}"' in source
    assert 'if [[ "${RUN_OPERATOR}" != "1" ]]; then' in source
    assert "scripts/run_ebay_external_handoff.py" in source
    assert "--apply" in source
    assert "--confirm-write" in source
    assert "--max-pages 2" in source
    assert "NEW_IDENTITY_COUNT>0" in source
    assert "unset RAILWAY_ENVIRONMENT" in source
    assert "railway up" not in source
    assert "vercel deploy" not in source
    assert "DATABASE_URL must be explicitly exported" in source
