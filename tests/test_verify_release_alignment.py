"""Read-only release alignment parsing stays fail-closed."""

from __future__ import annotations

import json

import pytest

from scripts.verify_release_alignment import (
    AlignmentError,
    parse_railway_payload,
    parse_vercel_list_payload,
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
