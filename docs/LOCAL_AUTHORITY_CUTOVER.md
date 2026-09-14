# Local Authority Cutover

## Status

Collector Ledger's authoritative operational data plane is the local PostgreSQL
database:

```text
127.0.0.1:5544/auction_warehouse
```

Vercel and Railway are not database authorities and must not be configured to
reach this loopback address.

The Vercel deployment is retained only as a database-free compatibility shell.
The legacy durable cloud refresh worker is prohibited from executing in a
Railway or Vercel runtime.

Neon is retained temporarily for historical verification and rollback evidence.
Its deletion is a separate, explicit operation and is not authorized by this
cutover.

## Accepted cutover baseline

The read-only local cutover preflight established:

Git release:

```text
bf3c1b1c8aeb7234e9591d8117dce527fe593151
```

PostgreSQL:

```text
127.0.0.1:5544/auction_warehouse
```

Alembic:

```text
6a8f4d2c9b17
```

`warehouse.auction`:

```text
total = 1205
ebay  = 875
buyee = 330
```

Structured eBay raw page:

```text
id            = 166
listing_count = 60
parsed        = true
```

Gripsweat:

```text
sales   = 817
sources = 3
```

Local durable cloud coordination:

```text
ops.refresh_job         = 0
ops.refresh_marketplace = 0
```

The latest accepted local refresh evidence was:

```text
state                  = success
phase                  = completed
ebay marketplace state = done
ebay runtime semantics = EBAY_SOURCE_AVAILABLE
final eBay rows        = 875
```

## Cloud boundary

The cutover rules are:

- Local PostgreSQL owns canonical operational data.
- Local execution owns marketplace refresh operations.
- GitHub remains the source and promotion boundary.
- Vercel must not open a PostgreSQL connection.
- Railway must not run the legacy cloud refresh worker or database-backed
  Collector Review process.
- No cloud runtime may be pointed at `127.0.0.1:5544`.
- Historical cloud implementation remains in source until a separate cleanup
  change removes it.
- Neon remains untouched until an explicit deletion gate is approved.
