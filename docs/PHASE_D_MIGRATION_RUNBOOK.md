# Phase D Migration Runbook

## Rule

Do not combine schema creation, owner backfill, query conversion, RLS
enforcement, and public authentication into one operation.

## D0 — install and audit

Run the downloaded package.

Expected:

```text
RESULT=PHASE_D_AUTH_ACCOUNT_FOUNDATION_INSTALLED
NEON_MUTATION_EXECUTED=false
ACCOUNT_SCOPE_AUDIT_GENERATED=true
```

Review:

```text
docs/PHASE_D_AUTH_ACCOUNT_ARCHITECTURE.md
docs/ACCOUNT_DATA_OWNERSHIP.md
docs/ACCOUNT_SCOPING_MATRIX.generated.md
docs/PHASE_D_SECURITY_MODEL.md
docs/PHASE_D_TEST_PLAN.md
```

## D1 — additive schema review

Inspect:

```text
alembic/versions/a4d9c2e7f105_account_identity_foundation.py
alembic/versions/a4d9c2e7f105_account_identity_foundation_up.sql
alembic/versions/a4d9c2e7f105_account_identity_foundation_down.sql
```

D1 does not enable public users.

## OIDC configuration

Copy:

```text
.streamlit/secrets.toml.example
```

to:

```text
.streamlit/secrets.toml
```

and fill values locally/platform-side.

Never commit the real file.

## Owner dry run

After D1 has been applied to the intended test/staging database and the owner's
OIDC subject is known:

```bash
python scripts/phase_d_owner_backfill.py \
  --provider oidc \
  --subject '...' \
  --email '...' \
  --display-name '...' \
  --expected-visible-listings 1441 \
  --expected-tracked-artists 3 \
  --expected-marketplace-searches 5
```

Required:

```text
VISIBLE_LISTING_COUNT=1441
TRACKED_ARTIST_COUNT=3
MARKETPLACE_SEARCH_COUNT=5
OWNER_BACKFILL_ACCEPTANCE_GATE=PASS
DATABASE_MUTATION_EXECUTED=false
```

Any mismatch is a stop condition.

## D2 — account-scope application code

Convert every generated `ACCOUNT_SCOPE_REQUIRED` path.

### Review

Reads:

```text
shared Review surface
WHERE/EXISTS account.auction_listing for current account
```

Writes:

```text
account_id + marketplace + listing_id
```

### Artists

Replace runtime JSON as the active product authority with:

```text
account.tracked_artist
account.artist_marketplace
```

Keep legacy JSON only as migration evidence/input.

### Refresh

Create/read/latest/status all require account ownership.

A job UUID is not authorization.

### Matching and completeness

Scope queue, assignment, audit, snapshot, timeline, and alert operations.

### Admin/shared tools

Require `is_system_admin`.

## Apply owner backfill

Only after D2 code is ready and reviewed:

```bash
python scripts/phase_d_owner_backfill.py \
  --provider oidc \
  --subject '...' \
  --email '...' \
  --display-name '...' \
  --system-admin \
  --apply
```

Preserve the printed evidence file.

## Shadow verification

With public sign-up still disabled:

1. owner login works;
2. Review still shows 1,441;
3. Artists still shows 3 / 5;
4. collector values still exist;
5. refresh history is owner-scoped;
6. matching/completeness still work;
7. synthetic second account sees zero rows;
8. synthetic account cannot read owner job UUID;
9. synthetic account cannot see owner Buyee reference.

## D3 — enforcement

Create the enforcement revision only after D2 passes.

Required changes:

- account-aware uniqueness constraints;
- required ownership columns become non-null;
- active-refresh uniqueness updated by final concurrency design;
- PostgreSQL RLS enabled and forced where appropriate;
- account/user GUCs established for transactions;
- cross-account negative tests pass.

Run:

```bash
python scripts/phase_d_scope_gate.py
```

before D3.

## D4 — public authentication

Enable login/onboarding only after D3.

New user must start with zero private rows.

## Rollback

Dry run:

```bash
python scripts/phase_d_owner_backfill_rollback.py \
  --evidence /path/to/owner-backfill-....json
```

Apply only if the drift check passes:

```bash
python scripts/phase_d_owner_backfill_rollback.py \
  --evidence /path/to/owner-backfill-....json \
  --apply
```

Rollback never deletes canonical marketplace/source facts.

## Historical safety

```text
CONTROLLED_V3_RERUN=false
Railway remains deferred.
Production promotion remains explicit.
```
