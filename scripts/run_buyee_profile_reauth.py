"""Headed Buyee reauth into the Railway volume, then read-only verify."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

VERIFIER_SCRIPT = (
    ROOT
    / "scripts"
    / "verify_buyee_session.py"
)
REFRESH_SCRIPT = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

REQUIRED_BUYEE_PROFILE_DIR = Path(
    "/data/buyee-profile"
)
RAILWAY_REAUTH_ENVIRONMENT_KEYS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_REPLICA_ID",
)

BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE = 2
BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE = 3
BUYEE_ACCESS_BLOCKED_EXIT_CODE = 4
BUYEE_MAINTENANCE_EXIT_CODE = 5


class BuyeeReauthError(RuntimeError):
    """Raised when Buyee profile reauth cannot proceed safely."""


def reject_railway_reauth_environment() -> None:
    """Refuse headed Buyee login on Railway workers."""

    present = [
        key
        for key in RAILWAY_REAUTH_ENVIRONMENT_KEYS
        if os.environ.get(
            key,
            "",
        ).strip()
    ]

    if present:
        raise BuyeeReauthError(
            "Refusing headed Buyee reauth on Railway. "
            "Run this operator on a workstation that can write "
            f"{REQUIRED_BUYEE_PROFILE_DIR}."
        )


def require_buyee_profile_dir(
    path: Path,
) -> Path:
    """Accept only the persistent Railway Buyee volume mount."""

    resolved = (
        path
        .expanduser()
        .resolve()
    )
    required = (
        REQUIRED_BUYEE_PROFILE_DIR
        .expanduser()
        .resolve()
    )

    if resolved != required:
        raise BuyeeReauthError(
            "Buyee profile must be "
            f"{required}, not {resolved}."
        )

    return resolved


def storage_state_for_profile(
    profile_dir: Path,
) -> Path:
    """Return the only allowed Buyee storage-state path."""

    return (
        profile_dir
        / ".auction-etl"
        / "private"
        / "buyee-storage-state.json"
    )


def classify_buyee_verifier_exit(
    code: int,
) -> str:
    """Map verifier exits without collapsing distinct Buyee states."""

    if code == 0:
        return "BUYEE_SOURCE_AVAILABLE"

    if (
        code
        == BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE
    ):
        return "BUYEE_AUTHENTICATION_REQUIRED"

    if (
        code
        == BUYEE_ACCESS_BLOCKED_EXIT_CODE
    ):
        return (
            "BUYEE_SOURCE_UNAVAILABLE_ACCESS_BLOCKED"
        )

    if code == BUYEE_MAINTENANCE_EXIT_CODE:
        return "BUYEE_MAINTENANCE"

    if (
        code
        == BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE
    ):
        return (
            "BUYEE_AUTHENTICATION_STATE_"
            "INDETERMINATE_TIMEOUT"
        )

    return "BUYEE_SOURCE_FAILED"


def raise_for_verifier_exit(
    *,
    label: str,
    code: int,
) -> None:
    """Fail closed with the exact Buyee semantic, not a generic failure."""

    semantic = classify_buyee_verifier_exit(
        code
    )

    if (
        code
        == BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE
    ):
        raise BuyeeReauthError(
            f"{label} ended in authentication_required "
            f"({semantic})."
        )

    if code == BUYEE_ACCESS_BLOCKED_EXIT_CODE:
        raise BuyeeReauthError(
            f"{label} ended in access_blocked "
            f"({semantic})."
        )

    raise BuyeeReauthError(
        f"{label} failed with exit code {code} "
        f"({semantic})."
    )


def validate_refresh_request(
    *,
    refresh: bool,
    confirm_write: bool,
    database_url: str | None,
) -> None:
    """Fail closed unless an optional refresh is explicitly armed."""

    if not refresh:
        if confirm_write:
            raise BuyeeReauthError(
                "--confirm-write requires --refresh."
            )

        return

    if not confirm_write:
        raise BuyeeReauthError(
            "--refresh requires --confirm-write."
        )

    if not (
        database_url
        and database_url.strip()
    ):
        raise BuyeeReauthError(
            "--refresh requires an explicit database URL "
            "via --database-url or DATABASE_URL."
        )


def build_headed_reauth_command(
    *,
    profile_dir: Path,
    storage_state: Path,
    timeout_minutes: int,
    evidence_dir: Path,
) -> list[str]:
    """Build the headed reauth command against the volume profile."""

    if timeout_minutes < 1:
        raise BuyeeReauthError(
            "Headed reauth timeout must be at least one minute."
        )

    command = [
        sys.executable,
        str(
            VERIFIER_SCRIPT
        ),
        "--profile-dir",
        str(
            profile_dir
        ),
        "--storage-state",
        str(
            storage_state
        ),
        "--skip-http-preflight",
        "--timeout-minutes",
        str(
            timeout_minutes
        ),
        "--evidence-dir",
        str(
            evidence_dir
        ),
    ]

    if "--headless" in command:
        raise BuyeeReauthError(
            "Headed Buyee reauth unexpectedly became headless."
        )

    return command


def build_read_only_verifier_command(
    *,
    profile_dir: Path,
    storage_state: Path,
    evidence_dir: Path,
) -> list[str]:
    """Build the post-close HTTPS/headless read-only verifier."""

    command = [
        sys.executable,
        str(
            VERIFIER_SCRIPT
        ),
        "--profile-dir",
        str(
            profile_dir
        ),
        "--storage-state",
        str(
            storage_state
        ),
        "--headless",
        "--timeout-minutes",
        "1",
        "--evidence-dir",
        str(
            evidence_dir
        ),
    ]

    if "--skip-http-preflight" in command:
        raise BuyeeReauthError(
            "Read-only verifier must use the saved HTTPS session."
        )

    return command


def build_refresh_command(
    *,
    database_url: str,
    expected_database_name: str,
    expected_database_user: str,
) -> list[str]:
    """Build one real latest-refresh command after a passing verifier."""

    return [
        sys.executable,
        str(
            REFRESH_SCRIPT
        ),
        "--database-url",
        database_url,
        "--expected-database-name",
        expected_database_name,
        "--expected-database-user",
        expected_database_user,
    ]


def run_child(
    *,
    label: str,
    command: list[str],
    environment: Mapping[str, str],
) -> str:
    """Execute one repository command and return merged output."""

    print()
    print(
        f"================ {label} ================"
    )
    print()

    result = subprocess.run(
        command,
        cwd=ROOT,
        env=dict(
            environment
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    output = (
        result.stdout
        or ""
    )

    if output:
        print(
            output,
            end=(
                ""
                if output.endswith(
                    "\n"
                )
                else "\n"
            ),
        )

    if result.returncode != 0:
        raise_for_verifier_exit(
            label=label,
            code=result.returncode,
        )

    return output


def emit_operator_contract(
    *,
    profile_dir: Path,
    refresh: bool,
) -> None:
    """Emit the machine-readable Buyee reauth contract."""

    print(
        "BUYEE_PROFILE_REAUTH_OPERATOR=PASS"
    )
    print(
        f"BUYEE_PROFILE_DIR={profile_dir}"
    )
    print(
        "BUYEE_STORAGE_STATE_PATH="
        + str(
            storage_state_for_profile(
                profile_dir
            )
        )
    )
    print(
        "BUYEE_HEADED_BROWSER_CLOSED=true"
    )
    print(
        "BUYEE_READ_ONLY_VERIFIER=PASS"
    )
    print(
        "BUYEE_RUNTIME_SEMANTICS=BUYEE_SOURCE_AVAILABLE"
    )
    print(
        "BUYEE_REFRESH_RUN="
        + str(
            refresh
        ).lower()
    )
    print(
        "DATABASE_WRITE="
        + str(
            refresh
        ).lower()
    )


def parse_arguments() -> argparse.Namespace:
    """Parse Buyee reauth operator arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Reauthenticate Buyee in a headed browser, persist only "
            "into /data/buyee-profile, close the browser, then run the "
            "read-only verifier against that exact saved state."
        )
    )

    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "AUCTION_BUYEE_PROFILE_DIR",
                str(
                    REQUIRED_BUYEE_PROFILE_DIR
                ),
            )
        ),
    )

    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="After a passing verifier, run one latest refresh.",
    )

    parser.add_argument(
        "--confirm-write",
        action="store_true",
        help="Required together with --refresh to authorize database writes.",
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL"
        ),
    )

    parser.add_argument(
        "--expected-database-name",
        default=os.environ.get(
            "AUCTION_EXPECTED_DATABASE_NAME",
            "auction_warehouse",
        ),
    )

    parser.add_argument(
        "--expected-database-user",
        default=os.environ.get(
            "AUCTION_EXPECTED_DATABASE_USER",
            "auction",
        ),
    )

    return parser.parse_args()


def run_operator(
    arguments: argparse.Namespace,
) -> int:
    """Run headed Buyee reauth, then the read-only verifier."""

    reject_railway_reauth_environment()
    validate_refresh_request(
        refresh=arguments.refresh,
        confirm_write=arguments.confirm_write,
        database_url=arguments.database_url,
    )

    profile_dir = require_buyee_profile_dir(
        arguments.profile_dir
    )
    storage_state = storage_state_for_profile(
        profile_dir
    )

    if not str(
        storage_state
    ).startswith(
        str(
            profile_dir
        )
    ):
        raise BuyeeReauthError(
            "Refusing Buyee storage-state outside the profile directory."
        )

    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    storage_state.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    evidence_root = (
        ROOT
        / "logs"
        / "buyee-profile-reauth"
    )
    environment = os.environ.copy()
    environment[
        "AUCTION_BUYEE_PROFILE_DIR"
    ] = str(
        profile_dir
    )
    environment[
        "AUCTION_BUYEE_STORAGE_STATE"
    ] = str(
        storage_state
    )
    environment[
        "BUYEE_STORAGE_STATE_FILE"
    ] = str(
        storage_state
    )

    run_child(
        label="HEADED BUYEE PROFILE REAUTH",
        command=build_headed_reauth_command(
            profile_dir=profile_dir,
            storage_state=storage_state,
            timeout_minutes=arguments.timeout_minutes,
            evidence_dir=(
                evidence_root
                / "headed-reauth"
            ),
        ),
        environment=environment,
    )

    if not storage_state.is_file():
        raise BuyeeReauthError(
            "Headed reauth did not persist Buyee storage-state "
            f"under {profile_dir}."
        )

    print(
        "BUYEE_HEADED_BROWSER_CLOSED=true"
    )

    run_child(
        label="READ-ONLY BUYEE VERIFIER",
        command=build_read_only_verifier_command(
            profile_dir=profile_dir,
            storage_state=storage_state,
            evidence_dir=(
                evidence_root
                / "read-only-verifier"
            ),
        ),
        environment=environment,
    )

    if not arguments.refresh:
        emit_operator_contract(
            profile_dir=profile_dir,
            refresh=False,
        )
        return 0

    database_url = str(
        arguments.database_url
    )
    environment[
        "DATABASE_URL"
    ] = database_url

    run_child(
        label="ONE BUYEE-INCLUDED REFRESH",
        command=build_refresh_command(
            database_url=database_url,
            expected_database_name=str(
                arguments.expected_database_name
            ).strip(),
            expected_database_user=str(
                arguments.expected_database_user
            ).strip(),
        ),
        environment=environment,
    )

    emit_operator_contract(
        profile_dir=profile_dir,
        refresh=True,
    )
    return 0


def main() -> int:
    """Parse CLI arguments and run the fail-closed Buyee reauth operator."""

    arguments = parse_arguments()

    try:
        return run_operator(
            arguments
        )
    except (
        BuyeeReauthError,
        OSError,
        ValueError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        print(
            "BUYEE_PROFILE_REAUTH_OPERATOR=FAIL",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
