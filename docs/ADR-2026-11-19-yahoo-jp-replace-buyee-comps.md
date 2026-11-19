# ADR: Replace Buyee Japan comps with Yahoo Auctions + フリマ

- **Status:** Accepted (design locked; production wiring + live refresh gate still open)
- **Date:** 2026-11-19
- **Spec:** `docs/superpowers/specs/2026-11-16-yahoo-jp-past-sales-design.md`
- **Supersedes (comps ingest):** Buyee closed-watchlist as the Japan past-sale feed
- **Does not change:** Historical `marketplace=buyee` warehouse rows; Buyee invoice / package / collection-bill flows

## Context

Japan JPY comps today enter mainly through **Buyee closed watchlist**. That feed is:

1. **Watched-only** — Buyee sold/closed results are only auctions the operator already watched, not the public closed market.
2. **Overlapping Yahoo Auctions** — Buyee listing ids are Yahoo `auctionId`s; dual-running both double-counts the same hammer unless Review dedupes (Yahoo authoritative).
3. **Operationally heavy** — login cookies, headed Chrome owner, WAF — for a narrow slice of what public closedsearch already exposes.

Public surfaces already match the eBay “sold search by artist” model:

| Source | Role |
|---|---|
| Yahoo Auctions closedsearch | Public auction / fixed-price hammers |
| Yahoo フリマ sold search | Peer sold listings (separate host + ids) |

Parsers, URL builders, live verify (auction 100/100 detail), scoped ingest smoke, and Review/Refresh label stubs already exist. What remains is **wiring into auction-etl refresh + UI**, with rate limits and layout designed so a 429 does not fail the whole run.

## Decision

1. **Japan comps ingest = Approach A:** warehouse marketplaces `yahoo_auction` and `yahoo_fleamarket`, artist-driven like eBay/Gripsweat.
2. **Retire Buyee as a refresh Japan step** after Yahoo refresh is green (dual-run optional and short). Buyee is not a permanent third Japan card.
3. **Keep Buyee history readable**; stop crawling watchlist for comps. Invoice/PDF/shelf money paths stay until a separate decision.
4. **Layout:** Refresh / Artists / Analytics treat eBay + Gripsweat + Yahoo Auctions + Yahoo フリマ as the live set; Buyee is optional/legacy only.
5. **Rate limits are first-class:** flea search-only in refresh; novelty watermark stop; soft `rate_limited`/`skipped` marketplace state — never fail the whole job on PayPay 429.

## Consequences

### Positive

- Comps coverage expands beyond watched auctions.
- One identity story for Japan auction hammers (Yahoo id), with Buyee∩Yahoo dedupe preferring Yahoo during dual-run.
- No Buyee login required for Japan search comps.
- Artists can enable Japan auction and/or フリマ independently (フリマ opt-in by default).

### Negative / cost

- Two HTTPS adapters + per-host pacing to maintain.
- PayPay flea rate limits are sticky (≥7 min host-wide after detail bursts) — detail must stay out of steady-state refresh.
- Doctor / ENGINEERING / Home copy must move off “Buyee, eBay, Gripsweat”.
- Dual-run briefly increases Japan noise until Buyee step is off.

### Explicit non-goals

- Deleting historical Buyee rows.
- Expanding Buyee beyond watchlist.
- Yahoo Taiwan / Shopping / Mercari.
- Discogs sold history.

## Layout (product)

| Surface | Live | Buyee |
|---|---|---|
| Refresh progress | eBay → Gripsweat → Yahoo Auctions → Yahoo フリマ | Hidden, or last/dim only in dual-run |
| Artists to Track | Four toggles; Auctions default on; フリマ opt-in | Not a track platform |
| Review chips / unique sales | Yahoo Auctions, Yahoo フリマ, eBay, Gripsweat | Legacy bucket only if rows remain |
| Pressing Analytics colors | Fixed palette (§20 of spec) | Slate legacy |
| Ingestion chart | Four live columns | Drop from default after cutover |

## Rate-limit max budget (refresh)

Measured: auctions host tolerates refresh-scale bursts; flea **detail** ~15 reqs @ 50ms trips **whole flea host** for ≥7 minutes; no `Retry-After`.

| Marketplace | Max search pages / artist / run | Detail in refresh | Min pause |
|---|---|---|---|
| `yahoo_auction` | 5 (novelty may stop earlier) | Off by default | ≥ 0.35s / page |
| `yahoo_fleamarket` | 5 (novelty may stop earlier) | **Never** in production refresh | ≥ 0.8s / page |
| Account run | Cap total flea pages across artists (start: 15) | — | On 429: stop flea step; cool ≥ 15 min next attempt |

Novelty stop (known ids + `MAX(closing_at)` watermark) is the primary brake; page caps are the hard ceiling.

## Real integration test gate (auction-etl)

Not “parser green” — **refresh-shaped** proof before Buyee is turned off:

| # | Gate | Pass |
|---|---|---|
| 1 | Unit: novelty stop + page cap on fixtures | Stops on fully-known / watermark page |
| 2 | Live smoke: `yahoo_jp_ingest` for one enabled artist, search-only, budgets above | Upserts new ids; second run stops early (`already_known` / novelty) |
| 3 | Dual-host: auction + flea sequential under budget | No flea 429; auction continues if flea soft-skips |
| 4 | Refresh job contract: marketplace states include yahoo_*; 429 → completable state | Job `completed` with partial Japan OK |
| 5 | UI: Refresh progress + Artists toggles + Analytics colors | Buyee not required to run Japan comps |
| 6 | Review: Buyee∩Yahoo same id → one sale, Yahoo preferred | Metrics match |
| 7 | Cutover: Buyee step disabled; doctor baselines on Yahoo counts | No watchlist crawl started |

Until gates 1–6 pass, Buyee may remain dual-run optional. Gate 7 is the ADR cutover execution.

## Draft commit message (overhaul — when gates pass)

Use when the wiring PR ships (not for this ADR-only change):

```
Retire Buyee watchlist comps in favor of Yahoo Auctions and フリマ.

Public closedsearch and sold search cover artist-driven Japan past sales;
Buyee only mirrored watched Yahoo auctions and overlapped the same ids.
```

Optional ADR-only commit (if committed separately):

```
Record ADR replacing Buyee Japan comps with Yahoo Auctions and フリマ.

Buyee sold results are watchlist-only and duplicate Yahoo auction ids,
so refresh should move to the public Yahoo surfaces instead.
```

## References

- Design + rate probes: `docs/superpowers/specs/2026-11-16-yahoo-jp-past-sales-design.md` (§§16–22)
- Probe artifacts: `docs/superpowers/specs/yahoo-jp-rate-limit-*.json`
- Identity / Review dedupe: `drop_overlapping_buyee_for_yahoo_rows`
- Prior hosting decision style: `docs/PHASE_E1_WORKER_HOST_DECISION.md`
