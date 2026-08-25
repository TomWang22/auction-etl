# Phase E1 permanent refresh-worker host decision

## Status

Phase E1 selects **Railway** as the primary permanent refresh-worker host and
keeps **Render** as the documented fallback.

This document records a hosting decision only. It does not deploy a service,
mutate PostgreSQL, run a marketplace refresh, rerun the owner backfill, modify
Docker infrastructure, or deploy Vercel.

- Decision source commit: `b54674a276a29ac16be15ca1b2889c9c24961927`
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
