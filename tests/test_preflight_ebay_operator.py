"""Compact operator preflight must prove SHA alignment before Chromium."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.preflight_ebay_operator import (
    preflight_ebay_operator_alignment,
)
from scripts.run_ebay_external_handoff import (
    main as operator_main,
)
from scripts.verify_release_alignment import (
    AlignmentError,
)
from tests.test_verify_release_alignment import (
    stub_aligned_release,
)


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = (
    ROOT
    / "scripts"
    / "preflight_ebay_operator.py"
)
GATE = (
    ROOT
    / "scripts"
    / "pre_ebay_acquisition_alignment_gate.sh"
)
OPERATOR = (
    ROOT
    / "scripts"
    / "run_ebay_external_handoff.py"
)
RECHECK = (
    ROOT
    / "scripts"
    / "recheck_operator_alignment.sh"
)


def test_preflight_command_is_versioned_and_alignment_only() -> None:
    """The compact preflight cannot deploy, write, or open Chromium."""

    assert PREFLIGHT.is_file()
    source = PREFLIGHT.read_text(
        encoding="utf-8"
    )

    assert source.startswith(
        "#!/usr/bin/env python3"
    )
    assert "--no-smoke" in source
    assert "verify_release_alignment" in source
    assert "OPERATOR_PREFLIGHT_ALIGNMENT=PASS" in source
    assert "if result != 0:" in source
    assert "91f2a37eaa56a2d59a1ab3c791e922e172062ed9" not in source
    assert "c831252b91b76ba76b948c7e2b996deccc31ad1f" not in source
    assert "railway up" not in source
    assert "vercel deploy" not in source
    assert "acquire_ebay_structured.py" not in source
    assert "--headless" not in source
    assert "run_ebay_external_handoff.py" not in source


def test_preflight_proves_worktree_and_remote_shas_without_pytest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """GitHub, Railway, Vercel, and a clean worktree are required."""

    stub_aligned_release(
        monkeypatch
    )

    def fail_if_smoke_runs(
        root: Path,
    ) -> None:
        del root
        raise AssertionError(
            "compact preflight ran production pytest smoke."
        )

    monkeypatch.setattr(
        "scripts.verify_release_alignment.run_production_smoke",
        fail_if_smoke_runs,
    )

    assert preflight_ebay_operator_alignment(
        [
            "--root",
            str(tmp_path),
        ]
    ) == 0

    output = capsys.readouterr().out

    assert "OPERATOR_PREFLIGHT_ALIGNMENT=PASS" in output
    assert "WORKTREE_CLEAN=true" in output
    assert "RELEASE_ALIGNMENT=PASS" in output
    assert "RAILWAY_ALIGNMENT=PASS" in output
    assert "VERCEL_ALIGNMENT=PASS" in output
    assert "PRODUCTION_SMOKE=PASS" not in output


def test_preflight_does_not_emit_pass_on_nonzero_alignment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """PASS is reserved for a zero alignment status."""

    stub_aligned_release(
        monkeypatch
    )
    monkeypatch.setattr(
        "scripts.preflight_ebay_operator.verify_release_alignment_main",
        lambda argv: 1,
    )

    with pytest.raises(
        AlignmentError,
        match="non-zero",
    ):
        preflight_ebay_operator_alignment(
            [
                "--root",
                str(tmp_path),
            ]
        )

    assert "OPERATOR_PREFLIGHT_ALIGNMENT=PASS" not in (
        capsys.readouterr().out
    )


def test_preflight_runs_immediately_before_every_operator() -> None:
    """The gate and CLI must recheck alignment before headed acquisition."""

    gate = GATE.read_text(
        encoding="utf-8"
    )
    operator = OPERATOR.read_text(
        encoding="utf-8"
    )

    assert "scripts/preflight_ebay_operator.py" in gate
    assert gate.index(
        "scripts/preflight_ebay_operator.py"
    ) < gate.index(
        '"${PYTHON}" "${OPERATOR}"'
    )
    assert "preflight_ebay_operator_alignment(" in operator
    assert "preflight_ebay_operator_alignment()" in operator
    assert "--expected-sha" not in operator[
        operator.index(
            "def main("
        ):
    ]
    assert operator.index(
        "preflight_ebay_operator_alignment()"
    ) < operator.index(
        "return run_operator("
    )


def test_recheck_command_is_read_only_github_railway_vercel_alignment() -> None:
    """One command rechecks remotes and a clean worktree without Chromium."""

    assert RECHECK.is_file()
    source = RECHECK.read_text(
        encoding="utf-8"
    )

    assert source.startswith(
        "#!/usr/bin/env bash"
    )
    assert "scripts/preflight_ebay_operator.py" in source
    assert "git rev-parse HEAD" in source
    assert "--expected-sha" in source
    assert "railway up" not in source
    assert "vercel deploy" not in source
    assert "run_ebay_external_handoff.py" not in source
    assert "--apply" not in source
    assert "DATABASE_URL" not in source


def test_operator_main_skips_chromium_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Alignment failure must stop before headed acquisition."""

    operator_calls = 0

    def fail_preflight(
        argv: object = None,
    ) -> int:
        del argv
        raise AlignmentError(
            "release is not aligned."
        )

    def forbid_operator(
        arguments: object,
    ) -> int:
        del arguments
        nonlocal operator_calls
        operator_calls += 1
        raise AssertionError(
            "operator ran after preflight failure."
        )

    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.parse_arguments",
        lambda: argparse.Namespace(),
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.preflight_ebay_operator_alignment",
        fail_preflight,
    )
    monkeypatch.setattr(
        "scripts.run_ebay_external_handoff.run_operator",
        forbid_operator,
    )

    assert operator_main() == 1
    assert operator_calls == 0

    captured = capsys.readouterr()
    assert (
        "OPERATOR_PREFLIGHT_ALIGNMENT=FAIL"
        in captured.err
    )
    assert "EBAY_EXTERNAL_HEADED_ACQUISITION_EXECUTED=true" not in (
        captured.out + captured.err
    )
