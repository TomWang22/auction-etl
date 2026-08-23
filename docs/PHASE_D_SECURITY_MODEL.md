# Phase D Security Model

## Trust boundaries

Collector Ledger has separate boundaries:

1. browser → Streamlit;
2. Streamlit ↔ OIDC provider;
3. app servers → Neon;
4. authenticated/internal caller → Vercel control plane;
5. worker → marketplace/Buyee profile storage.

Authentication at one boundary does not automatically secure another.

## Identity

Use:

```text
(provider, OIDC subject)
```

as the stable external identity.

Email may change and is not the authorization primary key.

## Passwords

Collector Ledger does not implement a password database.

Signup, password reset, MFA, and provider credential policy belong to the OIDC
provider.

## Authorization chain

Never trust a browser-supplied `account_id`.

Resolve:

```text
OIDC principal
  -> identity.app_user
  -> identity.account_member
  -> identity.account
```

server-side.

## New-account default deny

```text
visible listings = 0
tracked artists = 0
Buyee connection = not configured
shared admin write = denied
```

## Database defense

Application queries must explicitly scope rows before RLS is enabled.

RLS is a second layer, not a substitute for correct queries.

## Buyee secrets

Never put in PostgreSQL account metadata:

```text
password
raw cookies
localStorage
browser session token
browser profile bytes
```

Store opaque protected-storage references only.

## Vercel API

Streamlit OIDC login does not automatically authorize Vercel.

Recommended internal request fields:

```text
timestamp
request/nonce ID
account_id
user_id
HTTP method/path
body digest
server signature
```

Vercel verifies the signature and database ownership.

A browser-provided account UUID alone is never sufficient.

## System admin

Personal-account owner != system admin.

Global/shared reference mutation requires:

```text
identity.app_user.is_system_admin = true
```

## Logging

Safe audit fields:

```text
user_id
account_id
action
route
job_id
timestamp
result
```

Never log OIDC client secrets, DB passwords, Buyee passwords, or raw session
material.

## Required negative tests

```text
unauthenticated page access denied
cross-account listing read denied
cross-account collector write denied
cross-account tracked-artist access denied
cross-account refresh GET denied
cross-account refresh create denied
cross-account Buyee reference read denied
normal user shared-admin mutation denied
```
