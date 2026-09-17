"""Read-only release alignment parsing stays fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_release_alignment import (
    AlignmentError,
    GitIdentity,
    HISTORICAL_PRODUCTION_BASELINE_SHA,
    REJECTED_AS_CURRENT_RELEASE_SHAS,
    RailwayIdentity,
    SmokeError,
    VercelIdentity,
    main,
    parse_arguments,
    parse_railway_payload,
    parse_vercel_list_payload,
    production_smoke_command,
    vercel_github_sha,
)


def test_parse_railway_payload_reads_release_sha() -> None:
    """Railway JSON must expose the latest SUCCESS deployment SHA."""

    identity = parse_railway_payload(
        [
            {
                "id": "781f7fa0-0967-49db-9d0a-6bc08e2e14af",
                "status": "SUCCESS",
                "meta": {
                    "cliMessage": (
                        "Release "
                        "f08626ca3aab6da8f76c32692e8ff50cdd528bfd"
                    )
                },
            }
        ]
    )

    assert identity.deployment_id == (
        "781f7fa0-0967-49db-9d0a-6bc08e2e14af"
    )
    assert identity.status == "SUCCESS"
    assert identity.release_sha == (
        "f08626ca3aab6da8f76c32692e8ff50cdd528bfd"
    )


def test_parse_railway_payload_reads_github_commit_hash() -> None:
    """GitHub-triggered Railway deploys expose commitHash, not cliMessage."""

    identity = parse_railway_payload(
        [
            {
                "id": "fe0497cb-8693-4ec3-8f88-8e4c254ee44a",
                "status": "SUCCESS",
                "meta": {
                    "branch": "main",
                    "commitHash": (
                        "548f54cf100316215b9d27ea9e13daa98d33b29e"
                    ),
                    "commitMessage": (
                        "Expand headed eBay acquisition "
                        "to a bounded two-page window."
                    ),
                },
            }
        ]
    )

    assert identity.release_sha == (
        "548f54cf100316215b9d27ea9e13daa98d33b29e"
    )


def test_parse_railway_payload_rejects_empty_list() -> None:
    """No deployment is not alignment."""

    with pytest.raises(
        AlignmentError,
        match="no deployment",
    ):
        parse_railway_payload([])


def test_parse_vercel_list_payload_reads_github_sha() -> None:
    """Vercel JSON must expose production githubCommitSha."""

    payload = json.loads(
        """
        {
          "deployments": [
            {
              "url": "auction-etl-staging.vercel.app",
              "state": "READY",
              "meta": {
                "githubCommitSha":
                  "f08626ca3aab6da8f76c32692e8ff50cdd528bfd"
              }
            }
          ]
        }
        """
    )
    deployment = parse_vercel_list_payload(payload)

    assert vercel_github_sha(deployment) == (
        "f08626ca3aab6da8f76c32692e8ff50cdd528bfd"
    )


def test_vercel_github_sha_rejects_missing_metadata() -> None:
    """A READY URL without githubCommitSha is not release alignment."""

    with pytest.raises(
        AlignmentError,
        match="githubCommitSha",
    ):
        vercel_github_sha({"url": "example.vercel.app", "meta": {}})


def test_historical_baseline_is_not_current_release() -> None:
    """730f283 is historical metadata, not the current production SHA."""

    assert HISTORICAL_PRODUCTION_BASELINE_SHA == (
        "730f283356d2b1d326ec79fbadf2c2f7e73e8c4c"
    )
    arguments = parse_arguments([])

    assert arguments.expected_sha == ""
    assert arguments.expected_sha != HISTORICAL_PRODUCTION_BASELINE_SHA
    assert "6ef4c59f4144f115515a021892229890376af3c2" not in (
        arguments.expected_sha
    )
    assert arguments.smoke is True


def test_no_smoke_disables_production_pytest_gate() -> None:
    """Alignment-only checks remain available without changing the default."""

    arguments = parse_arguments(["--no-smoke"])

    assert arguments.smoke is False
    assert arguments.expected_sha == ""


def test_production_smoke_command_covers_pagination_and_novelty() -> None:
    """Smoke must re-prove bounded pages, novelty skip, and SHA parsing."""

    command = production_smoke_command(
        Path("/tmp/auction-etl")
    )
    joined = " ".join(
        command
    )

    assert command[:3] == [
        command[0],
        "-m",
        "pytest",
    ]
    assert "tests/test_verify_release_alignment.py" in joined
    assert "tests/test_run_ebay_external_handoff.py" in joined
    assert "tests/test_acquire_ebay_structured.py" in joined
    assert (
        "tests/test_existing_ebay_identities_no_new_warehouse_rows.py"
        in joined
    )
    assert (
        "tests/test_classify_ebay_external_current_release_gate.py"
        in joined
    )
    assert (
        "tests/test_pre_ebay_acquisition_alignment_gate.py"
        in joined
    )
    assert (
        "tests/test_zero_novelty_cannot_write.py"
        in joined
    )
    assert (
        "tests/test_preflight_ebay_operator.py"
        in joined
    )


def stub_aligned_release(
    monkeypatch: pytest.MonkeyPatch,
    sha: str | None = None,
) -> str:
    """Stub GitHub, Railway, and Vercel at one non-predecessor aligned SHA."""

    expected = sha or (
        "0123456789abcdef0123456789abcdef01234567"
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.git_identity",
        lambda root: GitIdentity(
            branch="main",
            local_head=expected,
            origin_main=expected,
            github_main=expected,
            worktree_clean=True,
            worktree_status="",
        ),
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.railway_identity",
        lambda **kwargs: RailwayIdentity(
            deployment_id="railway-deploy",
            status="SUCCESS",
            release_sha=expected,
        ),
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.vercel_identity",
        lambda **kwargs: VercelIdentity(
            url="https://auction-etl.vercel.app",
            deployment_id="vercel-deploy",
            state="READY",
            github_commit_sha=expected,
        ),
    )
    return expected


PREDECESSOR_CURRENT_SHA = (
    "6ef4c59f4144f115515a021892229890376af3c2"
)


def test_stub_aligned_release_does_not_enforce_predecessor_current_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit-test alignment must not treat 6ef4c59 as current production."""

    sha = stub_aligned_release(
        monkeypatch
    )

    assert sha != PREDECESSOR_CURRENT_SHA
    assert sha != HISTORICAL_PRODUCTION_BASELINE_SHA
    assert PREDECESSOR_CURRENT_SHA in REJECTED_AS_CURRENT_RELEASE_SHAS
    assert parse_arguments([]).expected_sha != PREDECESSOR_CURRENT_SHA


@pytest.mark.parametrize(
    "historical_sha",
    (
        "730f283356d2b1d326ec79fbadf2c2f7e73e8c4c",
        "6ef4c59f4144f115515a021892229890376af3c2",
        "7818f56d7b690fe1d187d61d44b6de3643ae6825",
        "0912af08c4ce0de0ff6290b28bbe8d7bddd7576d",
    ),
)
def test_rejects_historical_sha_when_head_is_current(
    historical_sha: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A current HEAD cannot accept a predecessor as the current release."""

    stub_aligned_release(
        monkeypatch
    )

    with pytest.raises(
        AlignmentError,
        match="not a current production release",
    ):
        main(
            [
                "--root",
                str(tmp_path),
                "--no-smoke",
                "--expected-sha",
                historical_sha,
            ]
        )


@pytest.mark.parametrize(
    "historical_sha",
    (
        "730f283356d2b1d326ec79fbadf2c2f7e73e8c4c",
        "6ef4c59f4144f115515a021892229890376af3c2",
        "7818f56d7b690fe1d187d61d44b6de3643ae6825",
        "0912af08c4ce0de0ff6290b28bbe8d7bddd7576d",
    ),
)
def test_aligned_historical_sha_cannot_pass_as_current(
    historical_sha: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Even a fully aligned predecessor SHA is not current production."""

    stub_aligned_release(
        monkeypatch,
        sha=historical_sha,
    )

    with pytest.raises(
        AlignmentError,
        match="not a current production release",
    ):
        main(
            [
                "--root",
                str(tmp_path),
                "--no-smoke",
                "--expected-sha",
                historical_sha,
            ]
        )


def test_rejected_current_release_shas_cover_every_predecessor() -> None:
    """The verifier must reject every retired current-release SHA."""

    assert REJECTED_AS_CURRENT_RELEASE_SHAS == frozenset(
        {
            "730f283356d2b1d326ec79fbadf2c2f7e73e8c4c",
            "6ef4c59f4144f115515a021892229890376af3c2",
            "7818f56d7b690fe1d187d61d44b6de3643ae6825",
            "0912af08c4ce0de0ff6290b28bbe8d7bddd7576d",
        }
    )
    assert (
        "0123456789abcdef0123456789abcdef01234567"
        not in REJECTED_AS_CURRENT_RELEASE_SHAS
    )


@pytest.mark.parametrize(
    "historical_sha",
    sorted(REJECTED_AS_CURRENT_RELEASE_SHAS),
)
def test_retired_sha_is_rejected_before_deployment_checks(
    historical_sha: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retired SHAs must fail before Git, Railway, or Vercel queries."""

    def fail_git(
        root: Path,
    ) -> GitIdentity:
        del root
        raise AssertionError(
            "git_identity ran"
        )

    def fail_railway(
        **kwargs: object,
    ) -> RailwayIdentity:
        del kwargs
        raise AssertionError(
            "railway_identity ran"
        )

    def fail_vercel(
        **kwargs: object,
    ) -> VercelIdentity:
        del kwargs
        raise AssertionError(
            "vercel_identity ran"
        )

    monkeypatch.setattr(
        "scripts.verify_release_alignment.git_identity",
        fail_git,
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.railway_identity",
        fail_railway,
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.vercel_identity",
        fail_vercel,
    )

    with pytest.raises(
        AlignmentError,
        match="not a current production release",
    ):
        main(
            [
                "--root",
                str(tmp_path),
                "--no-smoke",
                "--expected-sha",
                historical_sha,
            ]
        )


def test_smoke_runs_only_after_alignment_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The reusable gate is alignment, then production smoke, around HEAD."""

    expected = stub_aligned_release(
        monkeypatch
    )
    smoke_roots: list[Path] = []

    monkeypatch.setattr(
        "scripts.verify_release_alignment.run_production_smoke",
        lambda root: smoke_roots.append(root),
    )

    assert main(
        [
            "--root",
            str(tmp_path),
        ]
    ) == 0

    output = capsys.readouterr().out

    assert smoke_roots == [tmp_path.resolve()]
    assert "PROVEN_PRODUCTION_BASELINE_SHA=" not in output
    assert (
        "HISTORICAL_PRODUCTION_BASELINE_SHA="
        f"{HISTORICAL_PRODUCTION_BASELINE_SHA}"
    ) in output
    assert (
        "CURRENT_PROVEN_PRODUCTION_RELEASE_SHA="
        f"{expected}"
    ) in output
    assert f"RELEASE_HEAD={expected}" in output
    assert "RELEASE_ALIGNMENT=PASS" in output
    assert "PRODUCTION_SMOKE=PASS" in output
    assert output.index("RELEASE_ALIGNMENT=PASS") < output.index(
        "PRODUCTION_SMOKE=PASS"
    )


def test_no_smoke_skips_production_pytest_after_alignment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """--no-smoke proves alignment without running the pytest gate."""

    def fail_if_smoke_runs(
        root: Path,
    ) -> None:
        del root
        raise AssertionError(
            "smoke ran"
        )

    stub_aligned_release(
        monkeypatch
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.run_production_smoke",
        fail_if_smoke_runs,
    )

    assert main(
        [
            "--root",
            str(tmp_path),
            "--no-smoke",
        ]
    ) == 0

    output = capsys.readouterr().out

    assert "RELEASE_ALIGNMENT=PASS" in output
    assert "PRODUCTION_SMOKE=PASS" not in output


def test_smoke_failure_keeps_alignment_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Pytest smoke failure is distinct from GitHub/Railway/Vercel mismatch."""

    def fail_smoke(
        root: Path,
    ) -> None:
        del root
        raise SmokeError(
            "pytest failed"
        )

    stub_aligned_release(
        monkeypatch
    )
    monkeypatch.setattr(
        "scripts.verify_release_alignment.run_production_smoke",
        fail_smoke,
    )

    with pytest.raises(
        SmokeError,
        match="pytest failed",
    ):
        main(
            [
                "--root",
                str(tmp_path),
            ]
        )

    output = capsys.readouterr().out

    assert "RELEASE_ALIGNMENT=PASS" in output
    assert "PRODUCTION_SMOKE=PASS" not in output
