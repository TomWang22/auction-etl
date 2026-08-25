# Phase E plan

## Objective

Complete the operational work explicitly deferred by the Phase-D release: permanent refresh-worker hosting and production-promotion readiness, while preserving Phase-D account isolation and staging safety.

## E0 — Baseline and release lineage

- Keep the Phase-D release tag immutable.
- Keep Phase E based on the current `main` that contains the Phase-D release.
- Treat the Phase-D 1440/3/5 values as historical acceptance baselines, not permanent live-data caps.
- Require a clean full-test baseline before implementation.

## E1 — Permanent refresh-worker hosting

- Select and document the permanent worker host.
- Define worker process lifecycle, restart policy, health/readiness behavior, logs, and alerting.
- Define persistent Buyee browser-profile storage and recovery boundaries.
- Keep marketplace/browser execution outside Vercel request lifecycles.

## E2 — Staging worker deployment

- Deploy the worker with staging-only credentials and least privilege.
- Prove durable refresh-job claim/heartbeat/completion behavior.
- Prove restart/idempotency behavior and prevent duplicate concurrent execution.
- Capture repeatable deployment and rollback evidence.

## E3 — End-to-end account-scoped refresh acceptance

- Exercise control plane -> PostgreSQL job -> worker -> marketplace -> Neon staging.
- Prove account context survives dispatch and worker execution.
- Add cross-account negative tests for refresh visibility and mutations.
- Verify existing owner-scoped artist tracking remains isolated.

## E4 — Production-promotion readiness

- Inventory production secrets/configuration separately from staging.
- Verify migrations, backups, rollback, health checks, and operational ownership.
- Define a production acceptance matrix and explicit stop conditions.
- Do not perform production runtime/data cutover as part of readiness work.

## E5 — Promotion gate

- Require full tests plus worker-host acceptance evidence.
- Require account-isolation acceptance.
- Require an explicit production-cutover confirmation in a separate operation.
- Tag/release only after the Phase-E acceptance gate passes.

## Non-goals

- Do not rerun the Phase-D historical data restore.
- Do not rerun the Phase-D owner backfill.
- Do not change the historical Phase-D acceptance evidence.
- Do not move or rewrite the existing Phase-D release tag.
- Do not perform production cutover implicitly.
