# Yahoo Japan past sales (Auctions closedsearch + フリマ sold)

Date: 2026-11-16  
Status: **design only — not scheduled for implementation**

## Problem

Today Japan JPY sales enter the warehouse mainly through **Buyee closed watchlist**. That only sees auctions the operator already watched. Artists like Teresa Teng / Momoe Yamaguchi sell heavily on Yahoo Japan **without** ever appearing on that watchlist.

Public past-sale surfaces already exist and take the same keyword pattern as eBay sold search:

| Surface | Example URL | Role |
|---|---|---|
| Yahoo!オークション 落札相場 | `https://auctions.yahoo.co.jp/closedsearch/closedsearch?p=teresa+teng&fixed=0&b=1&is_postage_mode=1&n=50` | Closed auction / fixed-price hammers |
| Yahoo!フリマ sold | `https://paypayfleamarket.yahoo.co.jp/search/teresa%20teng?page=1&sold=1` | Peer sold (SOLD) listings |

Yahoo Taiwan past sales are unavailable for this product. Yahoo!ショッピング is storefront inventory, not a comps feed — out of scope here. Discogs API does **not** expose per-release sold history (only current asks / suggestions); Discogs stays identity-only.

## Goal

When the operator enables a tracked artist, refresh can pull **recent past sales** from Yahoo Auctions closedsearch and Yahoo フリマ sold search into the same warehouse / Review pipeline used for eBay — swap the keyword the same way `build_ebay_search_url(artist_name)` does today.

Success when implemented later:

1. Add/enable artist → both Yahoo surfaces get a `search_query` / `search_url` row (or explicit disable per surface).
2. Refresh upserts new `(marketplace, listing_id)` rows with JPY hammers and end times.
3. Review shows them with source chips; Buyee duplicates of the same Yahoo auction do not invent a second unique sale.
4. No change to Buyee watchlist behavior; no Discogs sales scrape.

## Non-goals (this design)

- Implementing crawlers, parsers, or UI in this change set.
- Yahoo Taiwan, Yahoo Shopping, Mercari, Rakuten.
- Buyee artist-search / beyond-watchlist (separate design if needed).
- Discogs `/sell/history` scraping or API past-sales (API cannot do it).
- Redesigning Streamlit performance (separate track).

## Approaches considered

| | Approach | Pros | Cons |
|---|---|---|---|
| **A (recommended)** | Two warehouse marketplaces: `yahoo_auction` and `yahoo_fleamarket`, each with its own URL builder + parser + refresh step, driven by the same tracked-artist name | Clear IDs, clear dedupe, mirrors eBay vs Gripsweat split | Two adapters to maintain |
| B | One `yahoo_jp` marketplace with `channel` in `config_json` | Fewer labels in UI | Muddy identity rules; harder doctor/refresh state |
| C | Auctions only now; フリマ “later” | Smaller first slice | Leaves a real Momoe/Teresa channel on the table; URLs already proven |

**Choice: A.** Same artist keyword, two marketplace keys — like eBay + Gripsweat, not one blended feed.

## Design

### 1. Keyword → URL (same vibe as eBay)

Extend `account.artist_marketplace` (or equivalent) so a tracked artist can enable:

| marketplace | URL builder (sketch) |
|---|---|
| `yahoo_auction` | `https://auctions.yahoo.co.jp/closedsearch/closedsearch?p={query}&fixed=0&b=1&is_postage_mode=1&n=50` then page with `b=` |
| `yahoo_fleamarket` | `https://paypayfleamarket.yahoo.co.jp/search/{query}?page=1&sold=1` then `page=` |

- `search_query` defaults to the tracked artist display name (operator can override later, same as eBay).
- Normalize spaces the way Yahoo expects (closedsearch historically dislikes over-encoding; flea uses path-encoded segments — pin fixtures when building).
- Optional category filters (レコード / CD) stay **off** by default so titles that sit in odd categories still appear; tighten later if noise is high.

### 2. Identity and money

| Field | `yahoo_auction` | `yahoo_fleamarket` |
|---|---|---|
| `marketplace` | `yahoo_auction` | `yahoo_fleamarket` |
| `listing_id` | Yahoo auction id from item URL (`/jp/auction/{id}` or current equivalent) | フリマ item id from item URL (host-specific; never reuse auction id space) |
| Currency | JPY | JPY |
| Hammer | 落札 price on card | Sold price on SOLD card |
| `closing_at` / sold_at | End datetime on card | Sold / last-updated time if exposed; else crawl day as weak fallback (document weakness) |
| `auction_url` | Canonical auctions.yahoo.co.jp item URL | Canonical paypayfleamarket.yahoo.co.jp item URL |
| Title / seller / image | From search card; detail page optional enrichment | Same |

Never store Buyee’s proxy id as the Yahoo identity. If a sale is later seen on Buyee, link by **Yahoo auction id** (or title+seller+close-day heuristic only as a soft assist).

### 3. Acquire / parse / store (shared product pattern)

Follow [`ENGINEERING.md`](../../ENGINEERING.md) §4:

1. **Acquire** search HTML (and optional item HTML) → `raw.page` (or existing raw store).
2. **Parse** pure functions over fixtures (`parsers/yahoo_auction.py`, `parsers/yahoo_fleamarket.py`).
3. **Upsert** `warehouse.auction` on `(marketplace, listing_id)`.
4. **Scope** into `account.auction_listing` for the account that tracked the artist (same visibility rules as eBay).
5. **Enrich** optional: item detail for description / condition text (seller reports), FX to USD via existing FX path.

**Browser posture (to decide at implement time, default below):**

- Prefer **HTTPS first** for public closedsearch / sold search (like Gripsweat).
- If WAF / empty / challenge: fall back to **headed Chrome** owner (like Buyee/eBay), off-desktop window placement.
- Do not use true headless.

**Retention windows (product expectations, not hard deletes):**

- Auctions closedsearch: on the order of **~120 days** of public history (community scrape notes; re-verify at implement).
- フリマ SOLD search: public SOLD display on the order of **~180 days** after sale ([Yahoo!フリマ notice](https://paypayfleamarket.yahoo.co.jp/notice/function/post_1116/)).
- Warehouse rows **stay** after they fall off the public window; refresh only stops seeing new/changed cards.

### 4. Dedupe and Review

| Pair | Rule |
|---|---|
| `yahoo_auction` ↔ Buyee | Same underlying Yahoo auction id → one unique sale in Review (prefer showing Buyee if the operator’s watchlist/proxy row exists; otherwise Yahoo). Exact join key to be proven with fixtures. |
| `yahoo_auction` ↔ `yahoo_fleamarket` | Different sites; **no** automatic merge unless a future evidence link says same physical copy (do not merge on title alone). |
| `yahoo_*` ↔ eBay / Gripsweat | No merge; different market. |
| Same title, different ids | Two rows (correct market history), same as today. |

Source chips / marketplace labels: **Yahoo Auctions**, **Yahoo フリマ** (customer-facing), distinct from Buyee.

### 5. Refresh orchestration

Extend `run_latest_auction_refresh.py` state machine with two optional steps (names illustrative):

`… → buyee → ebay → gripsweat → yahoo_auction → yahoo_fleamarket → fx → doctor → …`

- Each step: per enabled tracked artist, fetch search pages until empty/max pages, upsert, emit `ops.refresh_event`.
- Failure isolation: one Yahoo surface failing must not skip the other or wipe baseline counts (same doctor invariants as eBay).
- Artists to Track UI: checkboxes for Yahoo Auctions / Yahoo フリマ next to eBay / Gripsweat.

### 6. Rate, pacing, and politeness

- Pace per host (separate budgets for `auctions.yahoo.co.jp` vs `paypayfleamarket.yahoo.co.jp`).
- Cap pages per artist per refresh (start conservative, e.g. first N pages newest-first).
- Store raw HTML so selector breakage is fixable offline (classic layout-change playbook).

### 7. Testing before any production crawl

1. Save fixture HTML from the two example URLs (Teresa Teng) plus one Momoe query.
2. Parser unit tests: listing_id, title, JPY hammer, end/sold time, url.
3. URL builder tests: artist name → exact query substitution; pagination params.
4. Dedupe tests: synthetic Buyee row sharing Yahoo auction id.
5. No live scrape required for merge of the design implementation PR until fixtures pass.

### 8. Implementation sketch (when approved later)

| Slice | Deliverable |
|---|---|
| 0 | This design approved; still no code |
| 1 | URL builders + `artist_marketplace` enablement for both keys |
| 2 | `yahoo_auction` HTTPS acquire + parser + upsert + refresh step |
| 3 | Buyee ↔ Yahoo auction dedupe in Review unique-sale logic |
| 4 | `yahoo_fleamarket` acquire + parser + upsert + refresh step |
| 5 | Artists to Track + ENGINEERING/RUNBOOK notes |

Slice 2 alone already unlocks the largest Japan past-sale gap. Slice 4 is the second adapter, not a rewrite.

## Risks

| Risk | Mitigation |
|---|---|
| WAF / bot walls on Yahoo | HTTPS first; headed owner fallback; raw capture |
| closedsearch / フリマ markup drift | Fixtures + fail-closed parsers |
| Buyee double-count | Identity join on Yahoo auction id |
| Noise (DVD, signed goods, lots) | Same media classifiers / Lots chip as today; optional category filters later |
| Public window shorter than eBay archive | Expect rolling discovery; warehouse keeps history |
| Legal / ToS | Personal single-collector use, polite pacing; no resale API; revisit if product becomes multi-tenant |

## Open questions (resolve at implement kickoff)

1. Prefer showing **Buyee** or **Yahoo Auctions** when both ids match?
2. Default-on for new tracked artists, or opt-in per Yahoo surface?
3. Japanese vs Latin search_query variants (テレサ・テン vs Teresa Teng) — one query or two rows per artist?

## References (live checks for this design)

- Auctions closedsearch (Teresa Teng): https://auctions.yahoo.co.jp/closedsearch/closedsearch?p=teresa+teng&fixed=0&b=1&is_postage_mode=1&n=50
- フリマ sold search (Teresa Teng): https://paypayfleamarket.yahoo.co.jp/search/teresa%20teng?page=1&sold=1
- フリマ SOLD display window notice: https://paypayfleamarket.yahoo.co.jp/notice/function/post_1116/
- Existing eBay URL builder: `auction_etl.services.artist_tracking.build_ebay_search_url`
- Stack map: `docs/ENGINEERING.md` §4–5
