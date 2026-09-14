"""Fail-closed tests for headed Buyee profile reauth."""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

import pytest

from scripts.run_buyee_profile_reauth import (
    REQUIRED_BUYEE_PROFILE_DIR,
    BuyeeReauthError,
    build_headed_reauth_command,
    build_read_only_verifier_command,
    classify_buyee_verifier_exit,
    raise_for_verifier_exit,
    reject_railway_reauth_environment,
    require_buyee_profile_dir,
    run_operator,
    storage_state_for_profile,
    validate_refresh_request,
)


def operator_args(
    profile_dir: Path,
    *,
    refresh: bool = False,
    confirm_write: bool = False,
    database_url: str | None = None,
) -> argparse.Namespace:
    """Build one Buyee reauth argument namespace."""

    return argparse.Namespace(
        profile_dir=profile_dir,
        timeout_minutes=30,
        refresh=refresh,
        confirm_write=confirm_write,
        database_url=database_url,
        expected_database_name="auction_warehouse",
        expected_database_user="auction",
    )


def test_profile_dir_must_be_railway_volume_mount(
    tmp_path: Path,
) -> None:
    """Persist Buyee state only under /data/buyee-profile."""

    with pytest.raises(
        BuyeeReauthError,
        match="/data/buyee-profile",
    ):
        require_buyee_profile_dir(
            tmp_path / "elsewhere"
        )

    assert (
        storage_state_for_profile(
            REQUIRED_BUYEE_PROFILE_DIR
        )
        == (
            REQUIRED_BUYEE_PROFILE_DIR
            / ".auction-etl"
            / "private"
            / "buyee-storage-state.json"
        )
    )


def test_headed_reauth_skips_http_and_stays_headed() -> None:
    """Expired cookies must not block headed login, and headless is forbidden."""

    profile = REQUIRED_BUYEE_PROFILE_DIR
    command = build_headed_reauth_command(
        profile_dir=profile,
        storage_state=storage_state_for_profile(
            profile
        ),
        timeout_minutes=30,
        evidence_dir=Path("/tmp/buyee-reauth"),
    )

    assert "--headless" not in command
    assert "--skip-http-preflight" in command
    assert str(profile) in command
    assert str(
        storage_state_for_profile(profile)
    ) in command
    assert "/data/private/" not in " ".join(command)


def test_read_only_verifier_is_headless_https() -> None:
    """After the headed browser closes, verify the saved state read-only."""

    profile = REQUIRED_BUYEE_PROFILE_DIR
    command = build_read_only_verifier_command(
        profile_dir=profile,
        storage_state=storage_state_for_profile(
            profile
        ),
        evidence_dir=Path("/tmp/buyee-verify"),
    )

    assert "--headless" in command
    assert "--skip-http-preflight" not in command
    assert "--timeout-minutes" in command
    assert command[
        command.index("--timeout-minutes") + 1
    ] == "1"


def test_verifier_exit_codes_stay_distinct() -> None:
    """Do not collapse authentication_required into blocked or failed."""

    assert classify_buyee_verifier_exit(0) == (
        "BUYEE_SOURCE_AVAILABLE"
    )
    assert classify_buyee_verifier_exit(2) == (
        "BUYEE_AUTHENTICATION_REQUIRED"
    )
    assert classify_buyee_verifier_exit(4) == (
        "BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED"
    )
    assert classify_buyee_verifier_exit(5) == (
        "BUYEE_MAINTENANCE"
    )
    assert classify_buyee_verifier_exit(3) == (
        "BUYEE_AUTHENTICATION_STATE_INDETERMINATE_TIMEOUT"
    )
    assert classify_buyee_verifier_exit(1) == (
        "BUYEE_SOURCE_FAILED"
    )


def test_refresh_requires_confirmation() -> None:
    """One refresh still needs an explicit write gate."""

    validate_refresh_request(
        refresh=False,
        confirm_write=False,
        database_url=None,
    )

    with pytest.raises(
        BuyeeReauthError,
        match="requires --confirm-write",
    ):
        validate_refresh_request(
            refresh=True,
            confirm_write=False,
            database_url="postgresql://auction@127.0.0.1/auction_warehouse",
        )

    with pytest.raises(
        BuyeeReauthError,
        match="requires --refresh",
    ):
        validate_refresh_request(
            refresh=False,
            confirm_write=True,
            database_url="postgresql://auction@127.0.0.1/auction_warehouse",
        )


def test_railway_headed_reauth_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headed Buyee login must not run on a Railway worker."""

    monkeypatch.setenv(
        "RAILWAY_ENVIRONMENT",
        "production",
    )

    with pytest.raises(
        BuyeeReauthError,
        match="Railway",
    ):
        reject_railway_reauth_environment()


def test_operator_dry_path_closes_browser_then_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Headed reauth, persist, close, then read-only verifier; no DB write."""

    profile = tmp_path / "data" / "buyee-profile"
    profile.mkdir(
        parents=True,
    )
    storage_state = storage_state_for_profile(
        profile
    )
    storage_state.parent.mkdir(
        parents=True,
    )
    storage_state.write_text(
        '{"cookies":[]}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.REQUIRED_BUYEE_PROFILE_DIR",
        profile,
    )

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

        if label == "HEADED BUYEE PROFILE REAUTH":
            assert "--headless" not in command
            assert "--skip-http-preflight" in command
            return (
                "Buyee session verified\n"
                "BUYEE_HEADED_REAUTH=PASS\n"
            )

        if label == "READ-ONLY BUYEE VERIFIER":
            assert "--headless" in command
            assert "--skip-http-preflight" not in command
            return (
                "Buyee HTTPS session verified\n"
                "Auction links: 4\n"
            )

        raise AssertionError(
            f"unexpected child: {label} {command}"
        )

    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.run_child",
        fake_run_child,
    )

    assert run_operator(
        operator_args(profile)
    ) == 0

    output = capsys.readouterr().out

    assert calls == [
        "HEADED BUYEE PROFILE REAUTH",
        "READ-ONLY BUYEE VERIFIER",
    ]
    assert "BUYEE_PROFILE_REAUTH_OPERATOR=PASS" in output
    assert "BUYEE_HEADED_BROWSER_CLOSED=true" in output
    assert "BUYEE_READ_ONLY_VERIFIER=PASS" in output
    assert (
        "BUYEE_RUNTIME_SEMANTICS=BUYEE_SOURCE_AVAILABLE"
        in output
    )
    assert "BUYEE_REFRESH_RUN=false" in output
    assert "DATABASE_WRITE=false" in output


def test_operator_maps_authentication_required_not_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier exit 2 remains authentication_required."""

    profile = tmp_path / "data" / "buyee-profile"
    profile.mkdir(
        parents=True,
    )
    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.REQUIRED_BUYEE_PROFILE_DIR",
        profile,
    )

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment

        if label == "HEADED BUYEE PROFILE REAUTH":
            raise_for_verifier_exit(
                label=label,
                code=2,
            )

        raise AssertionError(
            f"verifier started after auth-required: {label}"
        )

    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.run_child",
        fake_run_child,
    )

    with pytest.raises(
        BuyeeReauthError,
        match="authentication_required",
    ):
        run_operator(
            operator_args(profile)
        )


def test_operator_maps_access_blocked_distinctly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier exit 4 remains access-blocked, not authentication_required."""

    profile = tmp_path / "data" / "buyee-profile"
    profile.mkdir(
        parents=True,
    )
    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.REQUIRED_BUYEE_PROFILE_DIR",
        profile,
    )

    def fake_run_child(
        *,
        label: str,
        command: list[str],
        environment: object,
    ) -> str:
        del command, environment
        raise_for_verifier_exit(
            label=label,
            code=4,
        )

    monkeypatch.setattr(
        "scripts.run_buyee_profile_reauth.run_child",
        fake_run_child,
    )

    with pytest.raises(
        BuyeeReauthError,
        match="access_blocked",
    ) as excinfo:
        run_operator(
            operator_args(profile)
        )

    assert "authentication_required" not in str(
        excinfo.value
    ).casefold()


def test_operator_source_never_writes_outside_volume() -> None:
    """AST invariant: persist only under /data/buyee-profile."""

    source = inspect.getsource(
        run_operator
    )

    assert "build_headed_reauth_command(" in source
    assert "build_read_only_verifier_command(" in source
    assert "HEADED BUYEE PROFILE REAUTH" in source
    assert "READ-ONLY BUYEE VERIFIER" in source
    assert "/data/private" not in source
    assert "stealth" not in source.casefold()
    assert "captcha bypass" not in source.casefold()


def test_verifier_exposes_skip_http_preflight_flag() -> None:
    """Headed reauth needs a verifier flag that skips stale HTTPS short-circuit."""

    source = Path(
        "scripts/verify_buyee_session.py"
    ).read_text(
        encoding="utf-8"
    )

    assert '"--skip-http-preflight"' in source
    assert "skip_http_preflight" in source
