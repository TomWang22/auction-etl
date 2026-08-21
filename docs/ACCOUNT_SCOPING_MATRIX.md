# Account-Scoping Matrix — Design Baseline

The generated whole-repository inventory is:

```text
docs/ACCOUNT_SCOPING_MATRIX.generated.md
```

## User-facing surfaces

| Surface | Current risk | Required boundary |
| --- | --- | --- |
| Home | assumes one workspace | authenticated account context |
| Review marketplace sales | global review + collector join | account visibility + private collector values |
| Refresh marketplace sales | global durable job operations | account-owned job create/read/latest |
| Artists to track | single runtime JSON | account-owned DB config |
| Match new listings | global queue/assignment | account-owned workflow |
| Listing completeness | global completeness workflow | account-owned workflow |
| Analysis/reports | may aggregate global rows | account-visible aggregation |
| Pressing library | mixes reference and curation | shared reads; private curation; admin shared writes |
| Advanced tools | can mutate shared state | system-admin only |

## Known services

| Service | Required conversion |
| --- | --- |
| `artist_tracking.py` | account DB authority; runtime JSON migration source only |
| `refresh_jobs.py` | require account/user for create/read/latest |
| `auction_intake.py` | account-filter queue/assignment/audit |
| `collector_curation.py` | account-key personal writes |
| review services | filter shared facts through account visibility |
| cloud worker | claim account-owned job and attach resulting listing visibility to that account |

## Gate

Every generated `ACCOUNT_SCOPE_REQUIRED` runtime file must be converted or
explicitly justified before D3 enforcement or D4 public sign-in.
