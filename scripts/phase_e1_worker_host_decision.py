#!/usr/bin/env python3
"""Record the Phase E1 permanent worker-host decision without deploying infrastructure."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs" / "PHASE_E1_WORKER_HOSTING_AUDIT.md"
DECISION_PATH = ROOT / "docs" / "PHASE_E1_WORKER_HOST_DECISION.md"

PRIMARY_PROVIDER = "railway"
FALLBACK_PROVIDER = "render"

REQUIRED_AUDIT_MARKERS = (
    "Persistent process",
    "Python 3.11 runtime",
    "Playwright + Chromium",
    "Outbound marketplace access",
    "Neon PostgreSQL access",
    "Secret injection",
    "Persistent writable volume",
    "Graceful shutdown",
    "Restart policy",
    "Stable logs/evidence",
    "AUCTION_BUYEE_PROFILE_DIR",
    "DATABASE_URL",
)


def parse_args() -> argparse.Namespace:
    """Parse the decision-script command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate the Phase E1 worker-hosting audit and optionally write "
            "the provider decision document. This script never deploys."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write docs/PHASE_E1_WORKER_HOST_DECISION.md.",
    )
    return parser.parse_args()


def git_head() -> str:
    """Return the current repository HEAD."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_and_validate_audit() -> str:
    """Load the committed source audit and enforce its hard requirements."""
    if not AUDIT_PATH.is_file():
        raise SystemExit(f"ERROR: Missing source audit: {AUDIT_PATH}")

    text = AUDIT_PATH.read_text(encoding="utf-8")
    missing = [
        marker
        for marker in REQUIRED_AUDIT_MARKERS
        if marker not in text
    ]

    if missing:
        formatted = ", ".join(missing)
        raise SystemExit(
            "ERROR: Phase E1 source audit is missing required markers: "
            f"{formatted}"
        )

    return text


def build_decision_document(head: str) -> str:
    """Build the reviewed provider-decision record."""
    return f"""# Phase E1 permanent refresh-worker host decision

## Status

Phase E1 selects **Railway** as the primary permanent refresh-worker host and
keeps **Render** as the documented fallback.

This document records a hosting decision only. It does not deploy a service,
mutate PostgreSQL, run a marketplace refresh, rerun the owner backfill, modify
Docker infrastructure, or deploy Vercel.

- Decision source commit: `{head}`
- Source audit: `docs/PHASE_E1_WORKER_HOSTING_AUDIT.md`
- Primary provider: **Railway**
- Fallback provider: **Render**
- Deployment executed by this decision: **no**

## Decision rationale

Railway is the primary choice because the Phase-E1 worker requires a persistent
long-running process, a Docker-capable Python/Playwright runtime, durable writable
storage for the Buyee browser profile, secret injection, outbound network access,
restart behavior, retained logs, and access to Neon PostgreSQL.

Railway's deployment model also exposes explicit restart and graceful-draining
controls. The deployment preflight must set a nonzero graceful-draining window so
the worker's SIGTERM handling has time to stop child work and relinquish its
durable refresh-job lease safely.

Render remains the fallback because its background-worker service model also
supports continuously running workers, Docker execution, secret injection, logs,
and an attachable persistent disk.

## Required Railway deployment shape

The next step is a **no-deploy preflight**. No Railway service should be created
or deployed until every item below is proven.

1. Use the existing repository/Docker build surface.
2. Override the image's current `CMD ["bash"]` with the worker start command:
   `python scripts/run_cloud_refresh_worker.py`.
3. Attach one durable volume for the Buyee browser/session profile.
4. Set `AUCTION_BUYEE_PROFILE_DIR` to an absolute path on that volume.
5. If durable worker evidence is enabled, place `AUCTION_WORKER_OUTPUT_DIR` on
   the durable volume as well.
6. Inject the worker database credential through the hosting platform; do not
   commit database credentials to Git.
7. Configure a persistent-worker restart policy.
8. Configure a nonzero Railway deployment draining interval so SIGTERM handling
   has time to complete.
9. Keep the service private unless an explicit inbound endpoint is later proven
   necessary; the worker itself polls PostgreSQL and does not require HTTP
   ingress.
10. Verify the deployed runtime can reach Neon and the required marketplaces
    before permitting a real refresh job to be claimed.

## Render fallback

If Railway fails a preflight or acceptance gate, stop before any production or
staging refresh is claimed. Render is the fallback candidate using:

- a background worker service;
- the same repository/Docker build;
- the same explicit worker start command;
- a persistent disk mounted at an absolute profile path;
- platform-managed secrets; and
- the same Neon job-lease and graceful-shutdown acceptance checks.

Switching to Render is a separate reviewed decision. This document does not
authorize an automatic provider switch or deployment.

## Deployment acceptance gates

A later deployment step must prove all of the following before the worker is
allowed to process a real durable refresh job:

- worker process starts and remains healthy;
- durable profile directory survives a restart/redeploy test;
- SIGTERM reaches the worker with enough drain time for graceful shutdown;
- restart policy recovers the process after an intentional nonzero exit;
- Neon connectivity succeeds with the worker credential;
- secrets are absent from Git and command output;
- logs identify the worker without exposing credentials;
- no duplicate durable-job ownership is created;
- no marketplace refresh is started during infrastructure-only validation; and
- rollback to the previous no-worker state is documented and tested.

## Current gate

`PHASE_E1_PROVIDER_DECISION=PASS`

`PHASE_E1_PROVIDER_SELECTED=railway`

`PHASE_E1_FALLBACK_PROVIDER=render`

`PHASE_E1_DEPLOYMENT_EXECUTED=false`

`RAILWAY_DEPLOY_EXECUTED=false`

`RENDER_DEPLOY_EXECUTED=false`
"""


def main() -> int:
    """Validate the audit and optionally persist the provider decision."""
    args = parse_args()
    load_and_validate_audit()
    head = git_head()

    print("================ PHASE-E1 WORKER HOST DECISION ================")
    print(f"PHASE_E1_RECOMMENDED_PROVIDER={PRIMARY_PROVIDER}")
    print(f"PHASE_E1_FALLBACK_PROVIDER={FALLBACK_PROVIDER}")
    print("DATABASE_MUTATION_EXECUTED=false")
    print("OWNER_BACKFILL_RERUN=false")
    print("DATA_RESTORE_RERUN=false")
    print("REFRESH_EXECUTED=false")
    print("DOCKER_MUTATION_EXECUTED=false")
    print("VERCEL_DEPLOY_EXECUTED=false")
    print("RAILWAY_DEPLOY_EXECUTED=false")
    print("RENDER_DEPLOY_EXECUTED=false")

    if not args.write:
        print("PHASE_E1_PROVIDER_SELECTED=false")
        print("PHASE_E1_PROVIDER_DECISION=PLAN")
        print("PHASE_E1_DEPLOYMENT_EXECUTED=false")
        print("NEXT=RUN_WITH_--write_AFTER_REVIEW")
        return 0

    document = build_decision_document(head)
    DECISION_PATH.write_text(document, encoding="utf-8")

    print(f"PHASE_E1_PROVIDER_SELECTED={PRIMARY_PROVIDER}")
    print(f"PHASE_E1_FALLBACK_PROVIDER={FALLBACK_PROVIDER}")
    print("PHASE_E1_PROVIDER_DECISION=PASS")
    print(f"PHASE_E1_DECISION_DOCUMENT={DECISION_PATH.relative_to(ROOT)}")
    print("PHASE_E1_DEPLOYMENT_EXECUTED=false")
    print("NEXT=RAILWAY_NO_DEPLOY_PREFLIGHT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
