#!/usr/bin/env python3
"""Read-only GitHub, Railway, Vercel, and worktree release alignment."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_PRODUCTION_BASELINE_SHA = (
    "730f283356d2b1d326ec79fbadf2c2f7e73e8c4c"
)
DEFAULT_RAILWAY_SERVICE_ID = (
    "b5346622-7343-4862-bede-edc1d53f1409"
)
DEFAULT_RAILWAY_ENVIRONMENT_ID = (
    "11c2d451-4fdb-4547-9b4d-2f57bb2902d0"
)
SHA_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")
PRODUCTION_SMOKE_TESTS = (
    "tests/test_verify_release_alignment.py",
    "tests/test_run_ebay_external_handoff.py",
    "tests/test_acquire_ebay_structured.py",
    "tests/test_existing_ebay_identities_no_new_warehouse_rows.py",
    "tests/test_classify_ebay_external_current_release_gate.py",
)


class AlignmentError(RuntimeError):
    """Raised when read-only release alignment cannot be proven."""


class SmokeError(AlignmentError):
    """Raised when the production pytest smoke gate fails after alignment."""


@dataclass(frozen=True, slots=True)
class GitIdentity:
    """Local, origin, and GitHub main commit identity."""

    branch: str
    local_head: str
    origin_main: str
    github_main: str
    worktree_clean: bool
    worktree_status: str


@dataclass(frozen=True, slots=True)
class RailwayIdentity:
    """Latest Railway deployment identity."""

    deployment_id: str
    status: str
    release_sha: str | None


@dataclass(frozen=True, slots=True)
class VercelIdentity:
    """Latest Vercel production deployment identity."""

    url: str
    deployment_id: str
    state: str
    github_commit_sha: str


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse read-only alignment arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Prove GitHub, Railway, Vercel, and worktree alignment "
            "against the current proven production release, then run "
            "the production smoke gate."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
    )
    parser.add_argument(
        "--expected-sha",
        default="",
        help=(
            "Require this 40-character commit. Defaults to local HEAD "
            "so the current commit is the enforcement SHA."
        ),
    )
    parser.set_defaults(smoke=True)
    parser.add_argument(
        "--smoke",
        dest="smoke",
        action="store_true",
        help="After alignment, run the production pytest smoke gate.",
    )
    parser.add_argument(
        "--no-smoke",
        dest="smoke",
        action="store_false",
        help="Prove alignment only; skip the production pytest smoke gate.",
    )
    parser.add_argument(
        "--railway-service-id",
        default=os.environ.get(
            "RAILWAY_SERVICE_ID",
            DEFAULT_RAILWAY_SERVICE_ID,
        ),
    )
    parser.add_argument(
        "--railway-environment-id",
        default=os.environ.get(
            "RAILWAY_ENVIRONMENT_ID",
            DEFAULT_RAILWAY_ENVIRONMENT_ID,
        ),
    )
    return parser.parse_args(argv)


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
) -> str:
    """Run one command and return stdout."""

    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit {completed.returncode}"
        )
        raise AlignmentError(
            f"{' '.join(command)} failed: {detail}"
        )
    return completed.stdout


def first_sha(
    text: str,
) -> str | None:
    """Return the first 40-character hex digest, if present."""

    match = SHA_PATTERN.search(text)
    if match is None:
        return None
    return match.group(0)


def parse_railway_payload(
    payload: object,
) -> RailwayIdentity:
    """Parse `railway deployment list --json` output."""

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("deployments", [])
    else:
        rows = []

    if not rows or not isinstance(rows[0], dict):
        raise AlignmentError(
            "Railway returned no deployment."
        )

    row = rows[0]
    deployment_id = str(
        row.get("id") or row.get("deploymentId") or ""
    ).strip()
    status = str(
        row.get("status") or row.get("state") or ""
    ).strip().upper()
    meta = row.get("meta")
    message = ""
    commit_hash = ""
    if isinstance(meta, dict):
        message = str(meta.get("cliMessage") or "")
        commit_hash = str(
            meta.get("commitHash")
            or meta.get("commitSha")
            or ""
        ).strip()

    if not deployment_id:
        raise AlignmentError(
            "Railway deployment ID is missing."
        )
    if not status:
        raise AlignmentError(
            "Railway deployment status is missing."
        )

    release_sha = None
    if SHA_PATTERN.fullmatch(commit_hash):
        release_sha = commit_hash
    else:
        release_sha = first_sha(message)

    return RailwayIdentity(
        deployment_id=deployment_id,
        status=status,
        release_sha=release_sha,
    )


def parse_vercel_list_payload(
    payload: object,
) -> dict[str, Any]:
    """Return the newest deployment object from `vercel list --json`."""

    if isinstance(payload, dict):
        rows = payload.get("deployments", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    if not rows or not isinstance(rows[0], dict):
        raise AlignmentError(
            "Vercel returned no production deployment."
        )
    return rows[0]


def vercel_github_sha(
    deployment: Mapping[str, Any],
) -> str:
    """Read githubCommitSha from one Vercel deployment object."""

    meta = deployment.get("meta")
    if not isinstance(meta, dict):
        raise AlignmentError(
            "Vercel deployment metadata is missing."
        )
    sha = str(meta.get("githubCommitSha") or "").strip()
    if not SHA_PATTERN.fullmatch(sha):
        raise AlignmentError(
            "Vercel githubCommitSha is missing."
        )
    return sha


def normalize_vercel_url(
    value: str,
) -> str:
    """Return an https Vercel deployment URL."""

    text = value.strip()
    if not text:
        raise AlignmentError(
            "Vercel production URL is missing."
        )
    if not text.startswith("https://"):
        text = "https://" + text
    return text


def git_identity(
    root: Path,
) -> GitIdentity:
    """Collect local Git and GitHub main identity."""

    branch = run_command(
        ["git", "branch", "--show-current"],
        cwd=root,
    ).strip()
    run_command(
        ["git", "fetch", "--prune", "origin", "main"],
        cwd=root,
    )
    local_head = run_command(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
    ).strip()
    origin_main = run_command(
        ["git", "rev-parse", "origin/main"],
        cwd=root,
    ).strip()
    remote = run_command(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=root,
    ).strip()
    github_main = remote.split()[0] if remote else ""
    status = run_command(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        cwd=root,
    )

    if not SHA_PATTERN.fullmatch(local_head):
        raise AlignmentError("Local HEAD is not a commit SHA.")
    if not SHA_PATTERN.fullmatch(origin_main):
        raise AlignmentError("origin/main is not a commit SHA.")
    if not SHA_PATTERN.fullmatch(github_main):
        raise AlignmentError("GitHub main is not a commit SHA.")

    return GitIdentity(
        branch=branch,
        local_head=local_head,
        origin_main=origin_main,
        github_main=github_main,
        worktree_clean=status.strip() == "",
        worktree_status=status,
    )


def railway_identity(
    *,
    root: Path,
    service_id: str,
    environment_id: str,
) -> RailwayIdentity:
    """Query the latest Railway deployment without changing it."""

    stdout = run_command(
        [
            "railway",
            "deployment",
            "list",
            "--service",
            service_id,
            "--environment",
            environment_id,
            "--limit",
            "1",
            "--json",
        ],
        cwd=root,
    )
    return parse_railway_payload(json.loads(stdout))


def vercel_identity(
    *,
    root: Path,
    expected_sha: str,
) -> VercelIdentity:
    """Query current Vercel production without deploying."""

    latest_stdout = run_command(
        [
            "vercel",
            "list",
            "--prod",
            "--json",
            "--limit",
            "1",
            "--no-color",
        ],
        cwd=root,
    )
    latest = parse_vercel_list_payload(json.loads(latest_stdout))
    latest_sha = vercel_github_sha(latest)
    latest_url = normalize_vercel_url(str(latest.get("url") or ""))
    latest_state = str(latest.get("state") or "").strip().upper()

    filtered_stdout = run_command(
        [
            "vercel",
            "list",
            "--prod",
            "--json",
            "--limit",
            "1",
            "--meta",
            f"githubCommitSha={expected_sha}",
            "--no-color",
        ],
        cwd=root,
    )
    filtered = parse_vercel_list_payload(json.loads(filtered_stdout))
    filtered_url = normalize_vercel_url(str(filtered.get("url") or ""))

    if latest_url != filtered_url:
        raise AlignmentError(
            "Newest Vercel production is not the current GitHub commit."
        )

    inspect_stdout = run_command(
        [
            "vercel",
            "inspect",
            latest_url,
            "--json",
            "--no-color",
        ],
        cwd=root,
    )
    inspected = json.loads(inspect_stdout)
    if not isinstance(inspected, dict):
        raise AlignmentError(
            "Vercel inspect payload is invalid."
        )

    deployment_id = str(inspected.get("id") or "").strip()
    ready_state = str(
        inspected.get("readyState")
        or inspected.get("state")
        or latest_state
    ).strip().upper()

    if not deployment_id:
        raise AlignmentError(
            "Vercel deployment ID is missing."
        )

    return VercelIdentity(
        url=latest_url,
        deployment_id=deployment_id,
        state=ready_state,
        github_commit_sha=latest_sha,
    )


def production_smoke_command(
    root: Path,
) -> list[str]:
    """Return the production pytest command for this repository."""

    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *[str(root / path) for path in PRODUCTION_SMOKE_TESTS],
    ]


def run_production_smoke(
    root: Path,
) -> None:
    """Run the production pytest smoke gate without deploying."""

    try:
        run_command(
            production_smoke_command(root),
            cwd=root,
        )
    except AlignmentError as exc:
        raise SmokeError(
            str(exc)
        ) from exc


def emit(
    name: str,
    value: object,
) -> None:
    """Print one alignment sentinel."""

    print(f"{name}={value}")


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Prove current release alignment and exit non-zero on mismatch."""

    arguments = parse_arguments(argv)
    root = arguments.root.expanduser().resolve()

    git = git_identity(root)
    expected_sha = (
        arguments.expected_sha.strip()
        or git.local_head
    )
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise AlignmentError(
            "--expected-sha must be a 40-character commit."
        )

    emit(
        "HISTORICAL_PRODUCTION_BASELINE_SHA",
        HISTORICAL_PRODUCTION_BASELINE_SHA,
    )
    emit(
        "CURRENT_PROVEN_PRODUCTION_RELEASE_SHA",
        expected_sha,
    )
    emit("RELEASE_HEAD", expected_sha)
    emit("LOCAL_HEAD", git.local_head)
    emit("ORIGIN_MAIN", git.origin_main)
    emit("GITHUB_MAIN", git.github_main)
    emit("GIT_BRANCH", git.branch)
    emit(
        "WORKTREE_CLEAN",
        "true" if git.worktree_clean else "false",
    )

    if git.branch != "main":
        raise AlignmentError("Expected branch main.")
    if git.local_head != expected_sha:
        raise AlignmentError(
            "Local HEAD differs from the expected release."
        )
    if git.origin_main != expected_sha:
        raise AlignmentError(
            "origin/main differs from the expected release."
        )
    if git.github_main != expected_sha:
        raise AlignmentError(
            "GitHub main differs from the expected release."
        )
    if not git.worktree_clean:
        print()
        print("Current worktree changes:")
        print(git.worktree_status, end="")
        raise AlignmentError("Worktree is not clean.")

    emit("LOCAL_GITHUB_COMMIT_ALIGNMENT", "PASS")

    railway = railway_identity(
        root=root,
        service_id=arguments.railway_service_id,
        environment_id=arguments.railway_environment_id,
    )
    emit("RAILWAY_LATEST_DEPLOYMENT_ID", railway.deployment_id)
    emit("RAILWAY_LATEST_STATUS", railway.status)
    emit(
        "RAILWAY_RELEASE_SHA",
        railway.release_sha or "unavailable",
    )
    emit("RAILWAY_CHANGE", "false")

    if railway.status != "SUCCESS":
        raise AlignmentError(
            f"Latest Railway deployment is {railway.status}, not SUCCESS."
        )
    if railway.release_sha != expected_sha:
        raise AlignmentError(
            "Railway latest deployment is not the expected release SHA."
        )
    emit("RAILWAY_ALIGNMENT", "PASS")

    vercel = vercel_identity(
        root=root,
        expected_sha=expected_sha,
    )
    emit("VERCEL_CURRENT_PRODUCTION_URL", vercel.url)
    emit("VERCEL_DEPLOYMENT_ID", vercel.deployment_id)
    emit("VERCEL_DEPLOYMENT_STATE", vercel.state)
    emit("VERCEL_GITHUB_COMMIT_SHA", vercel.github_commit_sha)
    emit("VERCEL_CHANGE", "false")

    if vercel.state != "READY":
        raise AlignmentError(
            f"Vercel production is {vercel.state}, not READY."
        )
    if vercel.github_commit_sha != expected_sha:
        raise AlignmentError(
            "Vercel production githubCommitSha is not the expected release."
        )
    emit("VERCEL_ALIGNMENT", "PASS")

    emit("SOURCE_MODIFIED", "false")
    emit("RELEASE_ALIGNMENT", "PASS")

    if arguments.smoke:
        run_production_smoke(root)
        emit("PRODUCTION_SMOKE", "PASS")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("PRODUCTION_SMOKE=FAIL")
        raise SystemExit(1) from exc
    except AlignmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("RELEASE_ALIGNMENT=FAIL")
        raise SystemExit(1) from exc
