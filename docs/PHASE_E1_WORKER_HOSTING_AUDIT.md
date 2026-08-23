# Phase E1 permanent refresh-worker hosting audit

## Status

This document records the source-derived hosting requirements before selecting or deploying a permanent refresh-worker host.

- Phase-E source commit: `890444e162ec62952ae86e138894b652d34ce297`
- Phase-D release commit: `2b36e208ac2bb42460a2c2a464b09a4c03b523c5`
- Database mutation performed by this audit: **no**
- Marketplace refresh performed by this audit: **no**
- Docker mutation performed by this audit: **no**
- Vercel deployment performed by this audit: **no**

## Existing execution boundary

- Vercel remains the lightweight HTTP control plane.
- Neon PostgreSQL remains authoritative staging data and durable refresh coordination.
- `scripts/run_cloud_refresh_worker.py` remains the long-running marketplace execution role.
- Permanent worker hosting and permanent Buyee profile storage were explicitly deferred before Phase E.

## Hard hosting requirements

1. **Persistent process** — the worker continuously polls durable PostgreSQL refresh jobs and cannot be hosted as a request-scoped serverless function.
2. **Python 3.11 runtime** — the refresh image currently derives from `python:3.11-slim-bookworm`.
3. **Playwright + Chromium** — the image installs Chromium with Playwright system dependencies.
4. **Outbound marketplace access** — the worker executes Buyee, eBay, and Gripsweat collection.
5. **Neon PostgreSQL access** — the worker claims jobs, heartbeats leases, records progress, and writes ingestion results.
6. **Secret injection** — database and marketplace/runtime secrets must come from the hosting platform, never source control.
7. **Persistent writable volume** — `AUCTION_BUYEE_PROFILE_DIR` must point to an absolute durable directory for the browser/session profile.
8. **Graceful shutdown** — the platform must deliver `SIGTERM`; the worker handles `SIGTERM`/`SIGINT`, stops the child process, and releases or loses its durable lease safely.
9. **Restart policy** — the platform must restart the persistent worker after host/process failure.
10. **Stable logs/evidence** — stdout/stderr must be retained; optional worker output/evidence should use durable storage if enabled.

## Worker timing defaults

- Poll interval: `source-defined` seconds
- Lease interval: `source-defined` seconds
- Heartbeat interval: `source-defined` seconds

The worker validates that heartbeat is less than half the lease duration. Hosting health/restart behavior must not violate that durable-ownership assumption.

## Container execution gap

- Current refresh Dockerfile terminal command: `CMD ["bash"]`.
- Therefore a permanent host must configure the actual worker start command explicitly, rather than relying on the image default.
- Candidate command must be verified from the worker CLI before deployment.

## Environment-variable surface discovered statically

- `AUCTION_BUYEE_PROFILE`
- `AUCTION_BUYEE_PROFILE_DIR`
- `AUCTION_WORKER_HEARTBEAT_SECONDS`
- `AUCTION_WORKER_ID`
- `AUCTION_WORKER_LEASE_SECONDS`
- `AUCTION_WORKER_OUTPUT_DIR`
- `AUCTION_WORKER_POLL_SECONDS`
- `DATABASE_URL`
- `DATABASE_URL_WORKER`
- `RAILWAY_DEPLOYMENT_ID`
- `RAILWAY_SERVICE_ID`

## Worker CLI surface discovered statically

- `--buyee-profile`
- `--buyee-profile-dir`
- `--database-url`
- `--heartbeat-seconds`
- `--lease-seconds`
- `--output-dir`
- `--poll-seconds`
- `--worker-id`

## E1 acceptance gates

A permanent host is acceptable only if all of these are proven:

- [ ] Persistent worker process survives normal idle periods.
- [ ] `SIGTERM` causes graceful shutdown.
- [ ] Worker restarts automatically after an intentional process termination.
- [ ] Neon TLS/database connectivity works using staging-only worker credentials.
- [ ] Durable refresh-job claim and heartbeat work without duplicate ownership.
- [ ] A persistent volume survives redeploy/restart.
- [ ] The Buyee profile is stored on that persistent volume.
- [ ] One profile is not concurrently shared by multiple workers unless explicit profile isolation is implemented and tested.
- [ ] Chromium launches successfully in the deployed runtime.
- [ ] Logs are retained and identify the worker instance.
- [ ] No secrets appear in Git, image layers, or command output.
- [ ] Staging deployment is isolated from production.

## Provider decision

**Not selected by this audit.** Railway was previously investigated but explicitly deferred. Phase E1 should compare candidate hosts against the hard requirements above before any deployment.

## Next action

Build a provider comparison using these requirements, choose one staging worker host, then perform a deployment plan with an explicit no-production-cutover guard.
