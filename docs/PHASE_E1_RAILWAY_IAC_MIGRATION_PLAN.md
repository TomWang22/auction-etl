# Phase E1 Railway Infrastructure-as-Code migration design

## Status

The Railway no-deploy preflight passed.

This document designs the next configuration step only. It does not link this
repository to a Railway project, create or modify Railway resources, read secret
values, deploy a service, mutate PostgreSQL, or run a marketplace refresh.

## Current repository state

The repository already contains a legacy `railway.json` with these worker settings:

- builder: `DOCKERFILE`
- Dockerfile: `Dockerfile.auction-etl.refresh`
- start command: `python scripts/run_cloud_refresh_worker.py`
- restart policy: `ALWAYS`

`Dockerfile.auction-etl.refresh` currently ends with `CMD ["bash"]`, so the
explicit worker start command must remain part of the Railway configuration.

## Railway platform direction

Railway now uses Infrastructure as Code (IaC) for project-level configuration,
with `.railway/railway.ts` as the TypeScript source of truth.

Legacy `railway.json` / `railway.toml` Config as Code is deprecated, new services
cannot opt into it, and legacy files stop being read after 2026-12-01.

A service cannot be managed by both legacy Config as Code and IaC at the same
time. The current repository is not linked to a Railway project, so no
`railway config plan` is run in this design step.

## Candidate IaC shape

This is a design candidate, not an apply-ready configuration:

```ts
import {
  defineRailway,
  github,
  project,
  service,
  volume,
} from "railway/iac";

const WORKER_REGION = "REVIEW_REQUIRED";
const WORKER_VOLUME_MB = 1024;
const WORKER_MOUNT = "/data";

export default defineRailway((ctx) => {
  if (WORKER_REGION === "REVIEW_REQUIRED") {
    throw new Error(
      "Choose WORKER_REGION only after comparing Railway placement with Neon staging.",
    );
  }

  const workerData = volume("auction-refresh-worker-data", {
    region: WORKER_REGION,
    sizeMB: WORKER_VOLUME_MB,
  });

  const worker = service("auction-refresh-worker", {
    source: github("TomWang22/auction-etl", { branch: "main" }),
    start: "python scripts/run_cloud_refresh_worker.py",
    replicas: { [WORKER_REGION]: 1 },
    volumeMounts: { [WORKER_MOUNT]: workerData },
    env: {
      RAILWAY_DOCKERFILE_PATH: "Dockerfile.auction-etl.refresh",
      DATABASE_URL_WORKER: ctx.shared.DATABASE_URL_WORKER,
      AUCTION_BUYEE_PROFILE_DIR: "/data/buyee-profile",
      AUCTION_WORKER_OUTPUT_DIR: "/data/worker-output",
      AUCTION_WORKER_ID: "railway-phase-e1-worker",
      RAILWAY_DEPLOYMENT_DRAINING_SECONDS: "60",
      RAILWAY_DEPLOYMENT_OVERLAP_SECONDS: "0",
    },
  });

  return project("auction-etl", {
    resources: [worker, workerData],
  });
});
```

## Required semantics

The eventual Railway configuration must preserve:

1. GitHub source `TomWang22/auction-etl` and source branch `main`.
2. `Dockerfile.auction-etl.refresh`.
3. Start command `python scripts/run_cloud_refresh_worker.py`.
4. Exactly one worker replica for initial acceptance.
5. One persistent volume mounted at an absolute path.
6. `AUCTION_BUYEE_PROFILE_DIR` on that persistent volume.
7. Optional worker output/evidence on that persistent volume.
8. `DATABASE_URL_WORKER` supplied by Railway without committing its value.
9. A nonzero SIGTERM draining interval.
10. Failure recovery equivalent to the reviewed restart-policy requirement.
11. No public HTTP domain unless later proven necessary.
12. No real marketplace refresh during infrastructure-only acceptance.

## Blockers before any apply

### B1. Target project and environment

Select the intended Railway project/environment before planning. Do not create a
new project merely to make the plan command work.

### B2. Legacy `railway.json` ownership

Determine whether an existing Railway service is actually managed by the
repository's legacy `railway.json`.

If yes, use Railway's migration workflow and review the preview before changing
the legacy configuration source. If no Railway service exists yet, retire the
legacy file as part of the IaC transition rather than creating a second source
of truth.

### B3. Restart-policy mapping

The legacy file explicitly sets `restartPolicyType=ALWAYS`.

The current IaC reference reviewed for this design does not document a
restart-policy field on `service(...)`. Do not invent one. Before apply, prove
the supported mapping from Railway's migration output or record an explicitly
reviewed service-level setting that preserves the required failure recovery.

### B4. Region and volume size

`WORKER_REGION` intentionally remains `REVIEW_REQUIRED`. Choose it after
comparing Railway placement with the current Neon staging region.

The 1024 MB volume size is a review value, not an accepted production size.

### B5. Database secret reference

Before apply, prove that the selected environment has the intended shared
`DATABASE_URL_WORKER` key without printing, exporting, or committing its value.
If the credential is service-scoped instead, revise the IaC design.

### B6. Persistent-worker behavior

Verify Railway Serverless is disabled for the worker. The worker is a persistent
polling process and must not rely on request-triggered wakeups.

### B7. No-deploy plan gate

Only after the target project/environment and blockers above are resolved, run:

`railway config plan`

Do not use `--show-values`. Review the plan for zero unexpected destroys or
changes to unrelated resources.

`railway config apply` remains prohibited until that plan is separately reviewed.

## Current gate

`PHASE_E1_RAILWAY_NO_DEPLOY_PREFLIGHT=PASS`

`PHASE_E1_RAILWAY_IAC_MIGRATION_DESIGN=PASS`

`RAILWAY_CONFIG_PLAN_EXECUTED=false`

`RAILWAY_CONFIG_APPLY_EXECUTED=false`

`RAILWAY_PROJECT_LINK_MUTATION_EXECUTED=false`

`RAILWAY_RESOURCE_MUTATION_EXECUTED=false`

`DATABASE_MUTATION_EXECUTED=false`

`REFRESH_EXECUTED=false`
