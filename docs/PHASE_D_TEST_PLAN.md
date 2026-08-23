# Phase D Test Plan

## Static contracts

- Streamlit OIDC login/logout source exists.
- Authlib dependency exists.
- `.streamlit/secrets.toml` is ignored.
- D1 migration is additive.
- extensive Phase-D architecture/security/runbook docs exist.
- account-scope matrix is generated.

## Owner preservation

Before apply and after conversion:

```text
visible listings:       1441
tracked artists:        3
marketplace searches:   5
```

## New account

A new principal receives:

```text
one personal account
one owner membership
zero listing bridge rows
zero tracked artists
no inherited collector decisions
no inherited Buyee state
```

## Shared fact reuse

If two accounts track the same listing:

```text
shared marketplace fact: one copy
account visibility rows: two possible
collector decisions: independently private
```

## Cross-account reads

Account A cannot read:

- B-only listing visibility;
- B collector decisions;
- B refresh jobs;
- B matching/completeness state;
- B Buyee connection/profile reference.

## Cross-account writes

A cannot:

- edit B collector values;
- edit B artists;
- enqueue/assign B workflow rows;
- create/read a refresh as B;
- attach new listing visibility to B.

## RLS

After D3:

- no account GUC -> no private rows / policy failure;
- A GUC -> A rows only;
- B GUC -> B rows only;
- `WITH CHECK` rejects forged account ownership.

## Admin

Normal account owner:

```text
own workspace administration = allowed
global shared reference mutation = denied
```

System admin:

```text
explicit global admin operation = allowed
```

## Historical invariants

```text
Controlled V3 is not rerun.
Canonical auctions are not deleted by backfill.
Railway remains outside the accepted runtime milestone.
```
