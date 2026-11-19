# Refresh latency investigation (job `3aa61319…`)

Date: 2026-11-19  
Run: `logs/ingestion-round/multisource-20261119-055810/…/20261119-005813`  
Wall clock: **00:58:10 → 01:21:03 (~23 min)** for **27 new** UI-visible rows (Buyee 23 + eBay 4; Gripsweat 0).  
Yahoo Auctions + フリマ **did run** in this job (novelty-fast) but the Refresh cards UI still only surfaced Buyee/eBay/Gripsweat.

## Where the time went (from artifact mtimes + log sections)

| Window | ~Duration | What |
|---|---|---|
| 00:58:13–00:58:20 | **~7s** | `Verify reusable Buyee HTTPS authentication` — **not** the bottleneck |
| 00:58:20–01:01:33 | **~3 min** | Buyee watchlist crawl + **HTTPS detail** — all **23** new ids hit `AWS_WAF_CHALLENGE` (“JavaScript verification page”) |
| 01:02:01–01:08:35 | **~6.5 min** | **WAF → headed browser detail fallback** for those 23 listings (serial owner crawls + screenshots) |
| 01:08:35–01:11:41 | **~3 min** | Buyee wrap-up + eBay tracked-artist crawl (4 new) |
| 01:11:41–01:14:22 | **~2.5–3 min** | Gripsweat probe + **pagination audit ~10 pages × 3 artists** (0 new) |
| 01:14:22–01:20:51 | **~6.5 min** | Yahoo novelty (seconds) + Discogs fill + **`collector_features` (872 changed)** + **`reclassify` (9600 row updates)** + FX + **doctor** + export |

## What “verification” actually is

The slow “verification” feeling is **not** the 7s Buyee session check. It is:

1. **Buyee AWS WAF JavaScript verification** on every new HTTPS detail URL, then  
2. **Mandatory headed browser fallback** for each challenged listing (`Apply WAF-only Buyee browser detail fallback`, `--authentication-timeout-minutes 8`).

That path turns “23 new Buyee cards” into ~6–10 minutes of browser work before eBay even starts.

## Yahoo impact (already in this run)

```
yahoo_auction   new=1  pages=4  reason=novelty  → done
yahoo_fleamarket new=0 pages=2  reason=novelty  → done
```

Yahoo is **not** the latency problem. Adding it formally is cheap next to Buyee WAF fallback + post-processing.

## Recommendations before “formal” Yahoo cutover

1. **Default refresh: `--skip-buyee`** (or skip Buyee **detail/WAF fallback**). Watchlist comps overlap Yahoo Auctions; this removes the dominant 6–10 min block.  
2. **Cap / novelty-stop Gripsweat pagination audit** (10×3 pages with 0 new is pure cost).  
3. **Defer or lighten post steps on routine refresh**: `collector_features` + `reclassify` + full `doctor` (~6 min) — run on a slower cadence or when new_count > 0 past a threshold.  
4. **Fix Refresh UI progress** so Yahoo cards appear (job already emits `AUCTION_SOURCE_STATE` for them).

## Decision gate

Do **not** block Yahoo formal integrate on eBay auth research. Block it only until Buyee WAF-detail (or Buyee entirely) is optional, otherwise every refresh stays ~20+ minutes whenever Buyee finds new watchlist rows.
