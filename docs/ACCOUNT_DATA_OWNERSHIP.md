# Account Data Ownership

## Purpose

This is the Phase-D row-ownership contract.

## Ownership classes

### Shared source/reference facts

Stored once and reusable:

```text
raw marketplace observations
warehouse.auction
source-derived normalized values
exchange/reference facts
shared pressing/reference definitions
```

Shared storage does not mean universal user visibility.

### Account visibility

`account.auction_listing` defines which listing identities belong in one
workspace:

```text
(account_id, marketplace, listing_id)
```

### Account curation

Private:

```text
collector notes / verdicts
collection status
manual pressing decisions
matching state
completeness state
saved preferences
```

### Account configuration

Private:

```text
tracked artists
eBay searches
Gripsweat searches
marketplace enablement
Buyee connection/profile reference
```

### Durable execution

Private:

```text
ops.refresh_job.account_id
ops.refresh_job.requested_by_user_id
```

Marketplace job rows inherit ownership through the parent refresh job.

## Initial relation decisions

| Relation / surface | Ownership | Phase-D action |
| --- | --- | --- |
| `warehouse.auction` | shared fact | keep one canonical copy |
| native Review relation | shared facts | filter by account visibility |
| Gripsweat Review integration | shared facts | filter by account visibility |
| `warehouse.auction_collector` | private | backfill/add account ownership |
| `warehouse.auction_pressing_assignment` | private curation | backfill/add account ownership |
| `ops.refresh_job` | private | add account/user ownership |
| `ops.refresh_marketplace` | private through job | verify parent job account |
| `ops.refresh_event` | private through job | verify parent job account |
| runtime artist JSON | private legacy config | migrate to `account.*` |
| new-auction queue | private workflow | account scope |
| completeness snapshot/timeline/alerts | private workflow | account scope |
| shared reference library | shared | normal read; system-admin writes |
| Buyee browser profile | private execution secret state | separate per account |

## Gripsweat constraint

The current Review page combines a native DB relation with Gripsweat reporting
rows. Therefore Phase D uses marketplace/listing identity as the first account
bridge rather than assuming every visible result has a `warehouse.auction` FK.

## Existing owner

The current single-user state is assigned to the owner only after the dry-run
proves the expected 1,441 / 3 / 5 counts.

## New account

Default deny:

```text
no account.auction_listing rows
no tracked artists
no collector decisions
no Buyee connection
```

Missing account scope must never mean “show all shared rows.”
