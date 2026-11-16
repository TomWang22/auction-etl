# Auction ETL — engineering guide

Single local product: one collector’s Buyee / eBay / Gripsweat sales in one
PostgreSQL warehouse, reviewed in Streamlit. This document is the high-level
map of stack, scrape, intake, duplicates, and how to survive site layout changes.

Companion ops history: [`RUNBOOK.md`](RUNBOOK.md). Architecture history:
[`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 1. Tech stack (what everything is made of)

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | One runtime for scrape, parse, UI, CLI |
| Package | `auction_etl` + `app/` | Library vs Streamlit pages |
| Warehouse | PostgreSQL `127.0.0.1:5544/auction_warehouse` | Sole data authority |
| ORM / SQL | SQLAlchemy 2 + Alembic | Engines, migrations, raw SQL where needed |
| UI | Streamlit + streamlit-aggrid + Altair | Operator UI on HTTPS localhost:8501 |
| Auth | Yahoo OIDC (Authlib) | Identifies the collector; does not import Yahoo inventory |
| Browser | Playwright + real Google Chrome (`channel=chrome`) | Headed only; eBay/Buyee block true headless |
| HTTP | httpx / BeautifulSoup / lxml | Gripsweat + Buyee HTTPS when WAF allows |
| Discogs | Discogs API client in `discogs_client` | Pressing identity after ingest |
| FX | `auction_etl.services.fx` + `scripts/update_auction_fx.py` | Local→USD |
| Jobs | `ops.refresh_*` tables + `run_latest_auction_refresh.py` | Durable refresh outside HTTP |

**Not in the data plane:** Vercel, Railway, Neon (shells / history only).

### How a typical function is shaped

1. **Parse / classify** — pure functions over HTML or title text (`parsers/`, `classifiers/media.py`).
2. **Service** — DB read/write with SQLAlchemy `text()` or small helpers (`services/*`).
3. **Script / owner** — long-lived process (Buyee/eBay Chrome) or one-shot CLI.
4. **Page** — Streamlit calls services; caches DataFrames; never crawls marketplaces inside a click.

Identity is always **`(marketplace, listing_id)`**. Money and media ride on that key.

---

## 2. Backend layout

```text
app/                          Streamlit pages
  collector_review.py         Review marketplace sales
  pages/17_My_Collection.py   Paid shelf + bills + acquisition charts
  pages/3_Latest_Auction_Refresh.py
auction_etl/
  browser/                    Chrome owner clients, defaults
  classifiers/                Media / lot / magazine rules
  parsers/                    Buyee, eBay HTML → structured fields
  services/
    warehouse.py              Upsert auctions
    sold_item_overlap.py      eBay ↔ Gripsweat same listing + OBO USD
    discogs_identity.py       Search keys, aliases, catalog fold
    discogs_fill.py           Assign pressings
    collection_*              My collection intake / bills / charts
  reporting/                  Review dataset integration
scripts/
  run_latest_auction_refresh.py
  run_ebay_owner.py / ensure_ebay_owner.py
  run_buyee_owner.py / ensure_buyee_owner.py
  acquire_ebay_structured.py
```

---

## 3. Functionalities (what the product does)

| Area | What the operator gets |
| --- | --- |
| **Review** | Search/filter sales; grades; Discogs fill; scenes; bulk lots |
| **My collection** | Bring in bills; shelf anatomy; speed fill; same-catalog Discogs; acquisition charts |
| **Latest refresh** | Kick / watch Buyee+eBay+Gripsweat ingest |
| **Tracked artists** | Scope which artists drive eBay/Gripsweat search |
| **Pressing library** | Reference pressings, evidence, matrices |
| **Analytics** | Sales by pressing / readiness |
| **FX / doctor** | USD values; warehouse health |

---

## 4. Marketplace scrape — high level

### Shared pattern

1. **Acquire** HTML or structured cards (browser or HTTPS).
2. **Store** raw evidence (`raw.page` and/or staging).
3. **Parse** into listing identity + money + media hints.
4. **Upsert** `warehouse.auction` (or `gripsweat_sale`) on `(marketplace, listing_id)`.
5. **Enrich** (optional detail crawl, Discogs, FX).
6. **Never delete** a baseline identity without an explicit prune path.

### Buyee

- **Owner:** long-lived headed Chrome with Buyee login cookies.
- **Primary path:** authenticated HTTPS closed-watchlist crawl.
- **Fallback:** when AWS WAF serves a challenge page, the owner browser opens the item.
- **Money:** JPY hammers; tax-inclusive 10/110 when the bill says so.
- **Identity:** Buyee item id (letter + digits or digits).

### eBay

- **Owner:** long-lived headed Google Chrome + storage-state JSON (not anonymous Chromium).
- **Acquire:** tracked-artist completed/sold search (`LH_Sold=1`, `LH_Complete=1`, `_sop=13`).
- **Import:** structured raw page → parse → warehouse.
- **Formats:** Auction, Fixed, **OBO** (`FIXED_PRICE_OBO`). On OBO, the card often shows the *ask*; accepted hammer may be missing until Gripsweat fills it.
- **Window:** headed is required. Prefer off-desktop placement so scrape does not steal the operator’s focus (`AUCTION_CHROME_VISIBLE=1` forces on-screen for debugging).

### Gripsweat

- **Path:** HTTP probe/import of artist search pages (no persistent Chrome owner).
- **Role:** archive of the same eBay sale; **official transaction-day USD** on duplicates.
- **OBO:** Gripsweat is the source of truth for the *accepted* price when eBay only stored the ask (`sold_item_overlap.gripsweat_should_stamp_obo_hammer`).

### Refresh orchestration

`scripts/run_latest_auction_refresh.py` runs Buyee → eBay → Gripsweat → FX → doctor → new-only export → backup. Progress lives in `ops.refresh_job` / `refresh_marketplace` / `refresh_event`.

---

## 5. Classic question: site layout changes

When Buyee, eBay, or Gripsweat changes markup, symptoms are empty parses, zero new rows, or WAF/challenge pages.

| Site | What usually breaks | How we counter |
| --- | --- | --- |
| **Buyee** | Watchlist card CSS / item detail DOM; WAF interstitial | Keep HTTPS selectors in `parsers/buyee.py` + crawl scripts; fail closed on challenge HTML; fall back to headed owner for those listing ids; store raw HTML so selectors can be re-tuned offline |
| **eBay** | Sold-card structure, CAPTCHA, Akamai 403 on page 2+ | Headed Chrome + storage state; load ebay.com before search; keep page-1 results if later pages 403; parse from stored raw pages; never switch to true headless |
| **Gripsweat** | Search result DOM / item URL shape | Probe scripts + `gripsweat_original_listing_id` URL parsers; compare against known eBay ids; re-run probe only after fixture HTML is updated |

**Playbook when a site moves:**

1. Capture a failing raw page into `logs/` or fixtures.
2. Write a failing parser/unit test against that HTML.
3. Adjust selectors / money regex only.
4. Re-run refresh for that marketplace; confirm new identities increase and baseline keys are not deleted.
5. Note the incident in [`RUNBOOK.md`](RUNBOOK.md).

Do **not** “fix” scrape failures by enabling headless or by pointing cloud hosts at the local DB.

---

## 6. Same listing, OBO, and same title

### Same listing (eBay ↔ Gripsweat)

- Same numeric id in `ebay.com/itm/{id}` and Gripsweat’s original listing id.
- **UI:** Review keeps the **eBay** row (`drop_overlapping_gripsweat_rows`); Gripsweat-only rows stay if there is no eBay twin.
- **Money:** For `FIXED_PRICE_OBO`, if eBay hammer ≈ ask, stamp Gripsweat sold USD as the hammer (`apply_gripsweat_official_usd` / `stamp_gripsweat_obo_hammers`). Otherwise Gripsweat is a USD *reference* only.

### OBO (best offer)

- eBay parse sets `auction_format = FIXED_PRICE_OBO` when the card is offer-based.
- Gripsweat often shows struck ask + accepted price → that accepted amount is the sale.
- Acquisition charts label this **OBO**.

### Same title already in the warehouse

- Warehouse key is **listing id**, not title. Two sales of the same album are two rows (correct for market history).
- Discogs matching folds title/artist aliases via `canonical_title_key` / `canonical_artist_key` so identity fill does not invent a second pressing for “鄧麗君” vs “Teresa Teng”.
- **My collection:** same **catalog** (folded) can inherit Discogs identity across copies without another HTTP call; condition stays per copy.
- Do not collapse two different listing ids into one auction row because titles match — that would destroy provenance.

---

## 7. My collection intake (not marketplace scrape)

1. Operator drops Buyee invoice PDF / Record City text / screenshots.
2. `collection_import` OCR/parses purchases (110% hammers, tax-inclusive yen).
3. `collection_shelf` classifies: match existing sale, new copy of known catalog, or owned_copy stub.
4. Bills → `collection_bill` / `collection_bill_line` (yen charges; landed uses FX).
5. Anatomy + optional Discogs; acquisition charts fold artists and package shapes.

---

## 8. Database map (one DB)

Schemas that matter day to day:

| Schema | Purpose |
| --- | --- |
| `raw` | Captured pages |
| `warehouse` | Auctions, Gripsweat, pressings, collector overlays, bills |
| `account` | Tracked artists, visible listing scope |
| `ops` | Refresh job state |

Important `warehouse` tables: `auction`, `auction_detail`, `gripsweat_sale`, `release_family`, `pressing_identity`, `auction_pressing_assignment`, `auction_collector`, `owned_copy`, `collection_bill`, `collection_bill_line`.

---

## 9. Frontend performance contracts

Streamlit re-runs the whole script on interaction. The browser “Running”
accessibility status stays up until that run finishes — so Review first paint
is dominated by Python over the kept pile, not by SQL (~0.5s).

1. **Reload services only when files change** (mtime gate) — not on every click.
2. **Cache warehouse loads** with a multi-minute TTL (`load_records` ttl=180);
   fold media chips, local identity, and recent-activity into that cache.
3. **Do not clear that cache on every Save** — overlay the changed row via
   session patches (`REVIEW_SAVE_PATCHES_KEY`). Clear only on Reload, refresh
   catch-up, or Discogs identity writes.
4. **Keep editor widgets in `@st.fragment`** (including media type) so filling
   grades/counts does not remount AgGrid + charts.
5. **Filter tracked artists before** pressing / prepare / title classification
   so those passes see ~2k rows, not the full join.
6. **Stable AgGrid keys** unless the underlying row set changed (never put
   selection revision in the key).
7. **One `st.rerun()` per intentional write**, not nested double-reruns.
8. **Scrape Chrome off-desktop** so refresh does not fight the UI for focus/CPU.
9. **Save toasts** name the sale for humans (`Buyee, 17 cassette lot` or
   platform + matrix/catalog/title) — never lead with the raw listing id.

---

## 10. Local authority reminder

- DB: `DATABASE_URL=postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse`
- UI: `https://localhost:8501` with mkcert TLS
- GitHub is the promotion boundary; cloud must not attach to loopback Postgres
