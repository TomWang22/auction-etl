# Auction ETL — runbook (incidents & fixes)

Operational memory for bugs we have already hit. When something fails again,
match the symptom here before inventing a new path.

See also [`ENGINEERING.md`](ENGINEERING.md).

---

## Marketplace refresh

### FX job exits status 1: expected N fx_rates; found N−2

- **Symptom:** `update_auction_fx` fails verification after refresh.
- **Cause:** Collection / stub rows with null currency skipped rate application but were still counted in the expected total.
- **Fix:** Apply rates only where currency is present; keep expected/found aligned. Do not invent FX for null currency stubs.

### Buyee “missed” recent closed auctions

- **Symptom:** Watchlist shows closed items; warehouse / completeness looks empty for them.
- **Cause:** First ingest got `detail_status=error` (WAF/HTTPS challenge); later “new-only” passes skipped them; completeness hid null `ended_at`.
- **Fix:** Confirm identities exist on `warehouse.auction`; re-run detail via headed owner for WAF ids; do not treat detail failure as “never ingested.”

### Buyee detail crawl: all AWS_WAF_CHALLENGE

- **Symptom:** HTTPS detail crawl fails every listing; refresh continues with browser fallback.
- **Cause:** Buyee returned JavaScript verification HTML instead of the item.
- **Fix:** Expected path — headed Buyee owner (`run_buyee_owner_job.py crawl_live_details`). Do not enable headless. If owner auth is stale, re-verify storage state.

### eBay later pages HTTP 403 / Akamai

- **Symptom:** Page 1 sold results OK; pagination dies.
- **Fix:** Keep page-1 results; load `ebay.com` on the same tab before sold search; headed Chrome + storage state only.

### eBay / Buyee Chrome steals focus (“orange jacket” tabs)

- **Symptom:** During refresh, Chrome jumps to the front; sold cards / jackets flash; UI feels unusable.
- **Cause:** Owners launch headed Chrome at `--window-position=80,80` (on-desktop). True headless is blocked by the sites.
- **Fix:** Default off-desktop window placement; set `AUCTION_CHROME_VISIBLE=1` only when you need to watch the scrape. Never “fix” with `headless=True`.

### Refresh lock / another refresh already running

- **Symptom:** New refresh refuses to start.
- **Fix:** Check `logs/latest-refresh/runs/*/refresh.lock` and `ops.refresh_job` state; do not start a second owner against the same profile blindly.

---

## Discogs / identity

### Fill too slow for many Momoe (same catalog) copies

- **Symptom:** Each copy pays `get_release` latency.
- **Fix:** Prefer owned unique pressing; after “Use this”, `propagate_catalog_identity_to_siblings` / **Fill same catalogs** (no HTTP when pressing known; one search per leftover catalog).

### Artist chart split: `nan`, 山口百恵, Momoe Yamaguchi, slash credits

- **Symptom:** Acquisition “By artist” looks broken.
- **Cause:** Raw `artist_name`; `str(nan)=="nan"`.
- **Fix:** `canonical_artist_display` / `collection_artist_label` folds aliases; unknown section does not override a known name.

### Theresa Teng vs Teresa Teng

- **Fix:** Add spelling to `_ARTIST_EQUIVALENCE_GROUPS`.

---

## My collection / bills

### Buyee tax / 110% hammers

- **Rule:** Item prices stay as printed 110% hammers; Japanese consumption tax is tax-inclusive (10/110). Do not invent Buyee `paid_on` without bill evidence.

### Record form “broken” / missing bulk lot

- **Fix:** Review-style media labels including bulk lots + mix counts; Discogs off for lots; disc count restored (1 = single sleeve, 2 = gatefold/double, …).

### `_single_bill_pressing() got unexpected keyword argument 'owned_choices'`

- **Fix:** Implement owned unique pressing preference in the bill matcher (TDD).

### Streamlit ImportError after editing services

- **Symptom:** `cannot import name 'canonical_artist_display'` during `importlib.reload(collection_acquisition)`.
- **Cause:** Acquisition reloaded before `discogs_identity`.
- **Fix:** Reload identity/fill before acquisition; mtime-gate reloads so everyday clicks do not reload at all.

### Save banner shows `buyee:j…` / listing id

- **Fix:** Catalog / matrix first in `_shelf_copy_label` / `_record_label`; prefer `manual_catalog_number`.

### Yellow warning / do not add until ready

- **Rule:** Do not add a lot until anatomy/billing gates clear; do not invent paid-on.

---

## Streamlit UI sluggishness

| # | Cause | Mitigation |
| --- | --- | --- |
| 1 | `importlib.reload` every run | Mtime-only reload helper |
| 2 | Fat Review query + 30s cache | Longer TTL; clear on write |
| 3 | AgGrid remount every interaction | Stable key until data write |
| 4 | Nested / reflexive `st.rerun()` | One rerun per intentional save |
| 5 | Headed Chrome on primary desktop during scrape | Off-desktop Chrome; refresh outside UI process |

---

## Same listing / OBO reminders

- Duplicate eBay+Gripsweat → show eBay row; Gripsweat USD for OBO when eBay only has the ask.
- Same album **title** ≠ same warehouse row; same **listing id** does.
- Same **catalog** on the shelf → share Discogs identity; grades stay per copy.

---

## Safe commands

```bash
# UI
./scripts/start-local.sh

# Full refresh (local only)
DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse' \
  .venv/bin/python scripts/run_latest_auction_refresh.py

# Watch scrape Chrome on-screen (debug only)
AUCTION_CHROME_VISIBLE=1  # then ensure_*_owner / refresh

# Backup
./scripts/backup-auction-warehouse.sh
```

Never point Vercel/Railway at `127.0.0.1:5544`.
