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
- **Latency:** Measured headed fallback ~16s p50 / ~27s p100 inter-arrival per listing; ~6.5 min for 23 listings. Prefer `--skip-buyee-detail` on routine multisource refresh.

### Buyee fails whole refresh under `--skip-buyee-detail` (2026-11-20)

- **Symptom:** UI shows Buyee “Marketplace execution failed”, 13 new / 0 processed; eBay/Gripsweat/Yahoo never run. Log: `AWS_WAF_CHALLENGE` × N then `Skipping Buyee WAF browser detail fallback` then `RuntimeError: Buyee HTTPS detail crawler failed without a classified WAF fallback candidate.`
- **Cause:** Watchlist identities upserted fine; HTTPS detail hit WAF; `--skip-buyee-detail` skipped headed fallback but the runner still treated detail status ≠ 0 as a hard stop.
- **Fix:** With `--skip-buyee-detail`, skip HTTPS detail + WAF fallback entirely after identity sync (degraded, not failed) so later marketplaces still run. Identities already in `warehouse.auction`; detail remains optional enrichment.

### Refresh UI shows 3 of 5 / Yahoo grey while warehouse grew (2026-11-20)

- **Symptom:** “Completed with issues”, Marketplaces updated 3 of 5; Yahoo Auctions / フリマ stay waiting with 0 new. Log still has `Yahoo JP yahoo_auction state=done new=…` and warehouse counts rise.
- **Cause:** (1) `ops.refresh_marketplace_ordinal_check` still required `ordinal BETWEEN 1 AND 3`, so job create never inserted Yahoo rows. (2) Worker `SOURCE_NAMES` / `\S+` source parser did not map `Yahoo Auctions` / `Yahoo フリマ` into durable marketplace updates.
- **Fix:** Migration `e8f3c1a0b7d2` raises ordinal ceiling to 5 and allows `rate_limited`. Worker maps Yahoo display names and accepts spaced source tokens. Restart Streamlit + local refresh worker after migrate so new jobs insert all five planned sources.

### Yahoo フリマ detail HTTP 429 / sticky rate limit

- **Symptom:** Flea item pages return 429 after a short burst; search pages still 200.
- **Cause:** Host rate limit on `paypayfleamarket.yahoo.co.jp` item URLs under parallel/paced detail.
- **Fix:** Production ingest is **search-only** for フリマ. Do not re-enable flea detail crawl. Soft-fail as `rate_limited`; keep novelty watermark. Auction detail HTTPS remains OK (~1.5s p50).

### Yahoo auction∩fleamarket duplicate listing ids

- **Symptom:** Same numeric id appears twice in Review (auction + fleamarket).
- **Cause:** Both Yahoo surfaces can share an id for the same lot.
- **Fix:** Ingest skips flea ids already on auction; Review `drop_overlapping_yahoo_jp_rows` keeps auction. One-shot cleanup: delete fleamarket warehouse rows whose `listing_id` exists on `yahoo_auction`.

### Refresh UI shows “3 of 3” / missing Yahoo progress

- **Symptom:** Latest Auction Refresh chart or progress omits Yahoo Auctions / フリマ even though the job ran them.
- **Cause:** UI planned sources lagged behind runner sources.
- **Fix:** Planned sources must include `yahoo_auction` and `yahoo_fleamarket`; chart series are built dynamically from present marketplace columns.

### Full refresh ~23 minutes / Yahoo not the culprit

- **Symptom:** Five-marketplace refresh wall clock ~20–25 minutes.
- **Cause:** Buyee WAF headed detail + post-pass features/reclassify/FX/doctor dominate; Yahoo novelty is seconds. Gripsweat pagination can also walk deep history when the newest probe page is not fully known.
- **Fix:** Default `--skip-buyee-detail` from UI multisource; keep `--lookback-days 3` (PostgreSQL `max(sold_at|ended_at) - N`) so Gripsweat/Yahoo stop at the daily floor instead of 2014. See [`superpowers/specs/2026-11-19-performance-percentiles.md`](superpowers/specs/2026-11-19-performance-percentiles.md).

### Gripsweat refresh walks back to 2014

- **Symptom:** Pagination audit keeps loading old archive pages; warehouse `sold_at` spans a decade.
- **Cause:** Newest-first crawl continues while “new” IDs still appear on older pages; no date floor.
- **Fix:** Refresh passes `--min-sold-at` from `refresh_lookback.gripsweat_sold_cutoff` (default 3 days before `max(sold_at)`). Do not disable lookback for daily runs; use a larger `--lookback-days` only for intentional backfill.

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
