# Auction ETL performance percentiles (measured)

Generated: `2026-11-19T06:47:49.234325+00:00`
Source refresh job: `3aa61319-8f49-4a31-accc-62a2ae49068c`

Nearest-rank percentiles. **p100 = max observed** in each sample.

## Warehouse reality (local DB)

| Store | Count |
| --- | ---: |
| `buyee` | 1,014 |
| `ebay` | 1,601 |
| `gripsweat_sale` | 897 |
| `yahoo_auction` | 401 |
| `yahoo_fleamarket` | 391 |

### Account-visible listings

| Marketplace | Visible |
| --- | ---: |
| `buyee` | 1,014 |
| `ebay` | 1,601 |
| `gripsweat` | 749 |
| `yahoo_auction` | 401 |
| `yahoo_fleamarket` | 391 |

### Yahoo time span (`ended_at`)

| Marketplace | n | min | max |
| --- | ---: | --- | --- |
| `yahoo_fleamarket` | 391 | 2026-08-31 03:10:03+00:00 | 2026-11-19 02:04:08+00:00 |
| `yahoo_auction` | 401 | 2026-05-31 13:00:00+00:00 | 2026-11-19 06:01:48+00:00 |

## Full refresh phase wall times (one real run)

| Phase | Seconds | Minutes |
| --- | ---: | ---: |
| `buyee_session_verify` | 7 | 0.12 |
| `buyee_crawl_plus_https_detail_waf_fail` | 193 | 3.22 |
| `buyee_waf_headed_detail_fallback_23_listings` | 394 | 6.57 |
| `ebay_refresh_approx` | 100 | 1.67 |
| `gripsweat_probe_and_pagination_audit` | 161 | 2.68 |
| `yahoo_auction_plus_fleamarket_novelty` | 8 | 0.13 |
| `post_features_reclassify_fx_doctor` | 389 | 6.48 |
| `full_refresh_wall_clock` | 1372 | 22.87 |

## Latency distributions (seconds)

| Workload | n | min | p50 | p90 | p95 | p99 | p99.9 | p100 | mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `buyee_waf_headed_detail_page_to_json` | 23 | 0.624 | 1.142 | 1.878 | 2.158 | 2.282 | 2.282 | 2.282 | 1.204 |
| `buyee_waf_headed_detail_inter_arrival` | 22 | 9.843 | 15.997 | 24.92 | 25.903 | 27.258 | 27.258 | 27.258 | 17.823 |
| `yahoo_https_search_page` | 29 | 1.007 | 1.328 | 1.76 | 1.812 | 1.881 | 1.881 | 1.881 | 1.434 |
| `yahoo_auction_detail_https` | 25 | 0.943 | 1.496 | 1.707 | 1.766 | 1.779 | 1.779 | 1.779 | 1.458 |
| `yahoo_fleamarket_detail_https_all` | 40 | 0.645 | 0.767 | 2.299 | 2.53 | 2.624 | 2.624 | 2.624 | 1.195 |
| `yahoo_fleamarket_detail_https_200_only` | 9 | 2.106 | 2.266 | 2.545 | 2.624 | 2.624 | 2.624 | 2.624 | 2.345 |

## Reading

- Full refresh wall (~22m 52s) was dominated by **Buyee WAF headed detail**, not Yahoo JP.
- Yahoo HTTPS search/detail pages are typically **~1–2s** (p50–p95) in live probes.
- Flea **detail** bursts trip **429**; production Yahoo フリマ stays **search-only** with novelty stop.
- UI multisource refresh defaults **`--skip-buyee-detail`** to cut the dominant tail.

Artifacts: `2026-11-19-performance-percentiles.json`, run dir under `logs/ingestion-round/multisource-20261119-055810/`.
