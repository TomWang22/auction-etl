# Collector Ledger

> **Compatibility name:** the repository, Python package, and existing infrastructure still use `auction-etl` / `auction_etl`.
>
> **Current runtime authority:** local PostgreSQL at 127.0.0.1:5544/auction_warehouse. Vercel and Railway are non-data cloud shells and must not be pointed at the local database. Neon is retained only until a separate deletion gate. See [docs/LOCAL_AUTHORITY_CUTOVER.md](docs/LOCAL_AUTHORITY_CUTOVER.md).

Collector Ledger is a collector-focused auction intelligence and ETL system for discovering marketplace sales, preserving source evidence, normalizing auction records, identifying pressings and completeness, reviewing uncertain records, coordinating durable refresh jobs, and exporting collector-ready research.

The local loop integrates **Buyee, eBay, and Gripsweat** with PostgreSQL at `127.0.0.1:5544/auction_warehouse`, Streamlit Collector Review on HTTPS `localhost:8501`, headed eBay acquisition from a persistent browser profile, a headed Buyee owner, and Gripsweat probe/import. GitHub is the source/promotion boundary. Vercel and Railway are deferred non-data shells and must not point at the local database.

## Requirements

- Python **3.11+** and this repository's `.venv` (install with `uv sync` or `pip install -e ".[dev]"`).
- Local PostgreSQL **`127.0.0.1:5544/auction_warehouse`**, user `auction`.
- `DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse'`
- Collector Review: `AUCTION_ENV=development` on **HTTPS** `localhost:8501` with local TLS certs. Yahoo redirect URI is `https://localhost:8501/oauth2callback`.
- Playwright persistent profiles: `profiles/facerecords` for eBay; the headed Buyee owner for Buyee.
- Do not attach Vercel, Railway, or Neon to this loopback database.

## How it is designed

One warehouse, three ingest paths, one review UI:

| Source | How it is acquired | Local money | Warehouse table |
| --- | --- | --- | --- |
| Buyee | Headed owner + closed watchlist | **JPY** | `warehouse.auction` `marketplace=buyee` |
| eBay | Headed completed/sold search from `profiles/facerecords`, exact raw-page import | **Listing display currency** (not automatically USD) | `warehouse.auction` `marketplace=ebay` |
| Gripsweat | Artist probe/import | **Official USD** on eBay duplicates (`sold_at`) | `warehouse.gripsweat_sale` |

Identity is `(marketplace, listing_id)`. eBay sold URLs are `https://www.ebay.com/itm/{id}`. Gripsweat archives the same sale as `https://gripsweat.com/item/{id}/...`.

**Currency:** eBay completed/sold cards can be `US $`, `GBP`/`£`, `EUR`/`€`, `AU $`, `C $`, or a bare `$`. Bare `$` is a display amount on ebay.com, **not** official USD.

**Duplicates:** if the same `{id}` exists on eBay and Gripsweat, Collector Review keeps the native eBay row. **Gripsweat's sold amount on `sold_at` is the official transaction-day USD** for that duplicate, even if the eBay card shows `$` / GBP / EUR. The eBay local display amount stays on the eBay row.

**Buyee completeness:** every closed-watchlist identity must be in the warehouse with a listing ID, title, and JPY sold price. Live item-detail pages are extra enrichment, not the identity itself.

## Architecture overview

```mermaid
flowchart LR
    Operator["Collector / operator"]

    subgraph Review["Collector Review"]
        UI["Streamlit HTTPS localhost:8501<br/>app/collector_review.py"]
    end

    subgraph Local["Authoritative local runtime"]
        DB[("PostgreSQL 127.0.0.1:5544<br/>auction_warehouse")]
        Refresh["scripts/run_latest_auction_refresh.py"]
        EbayOp["Headed eBay operator<br/>persistent facerecords profile"]
        BuyeeOwner["Headed Buyee owner"]
        Gripsweat["Gripsweat probe / import"]
    end

    subgraph Sources["Marketplace sources"]
        Buyee["Buyee completed watchlist"]
        Ebay["eBay completed/sold search<br/>LH_Sold=1 LH_Complete=1 _sop=13"]
        Grip["Gripsweat artist search"]
    end

    subgraph Promotion["Promotion boundary"]
        Git["GitHub main"]
        Cloud["Vercel / Railway / Neon<br/>deferred non-data shells"]
    end

    Operator --> UI
    UI --> DB
    Operator --> EbayOp
    EbayOp --> Ebay
    EbayOp --> DB
    Operator --> Refresh
    Refresh --> BuyeeOwner
    Refresh --> Gripsweat
    BuyeeOwner --> Buyee
    Gripsweat --> Grip
    Refresh --> DB
    Git -.-> Cloud
```

The key architectural boundary is deliberate:

- **Local PostgreSQL on 5544** is the authoritative warehouse.
- **Collector Review on HTTPS localhost:8501** is the review UI against that warehouse. Yahoo login needs that TLS certificate.
- **eBay** is a generalized local sold/completed crawl from tracked-artist
  searches, using hidden headed Google Chrome. It is not a FaceRecords
  seller handoff.
- **Buyee** uses the headed owner plus authenticated HTTPS watchlist crawl.
- **Gripsweat** uses probe/import against configured artist searches.
- **Git/GitHub** is the source and promotion boundary.
- **Vercel, Railway, and Neon** are out of the local data plane.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full system architecture, including historical Vercel + Neon staging topology that no longer defines data authority.

## Goals

- Preserve marketplace source provenance and deterministic auction identity.
- Incrementally ingest Buyee, eBay, and Gripsweat auction data.
- Maintain a canonical PostgreSQL warehouse.
- Normalize media, pressing, completeness, condition, price, and collector metadata.
- Support collector review, evidence intake, curation, analytics, and reporting.
- Coordinate refreshes with durable PostgreSQL job state.
- Keep long-running browser/marketplace execution outside HTTP request lifecycles.
- Preserve explicit staging and production promotion boundaries.

## How it works

1. Point every command at local `DATABASE_URL` on port **5544**.
2. Open Collector Review at `https://localhost:8501` with `AUCTION_ENV=development` and local TLS certs.
3. Ingest **eBay** through the local hidden-Chrome sold/completed crawl driven
   by tracked artists (`LH_Sold=1`, `LH_Complete=1`, `_sop=13`).
4. Ingest **Buyee** through the headed owner (closed watchlist) and **Gripsweat** through probe/import via `scripts/run_latest_auction_refresh.py`.
5. Review and export from the warehouse. eBay+Gripsweat duplicates keep the eBay row and use the Gripsweat sold amount as the official transaction-day USD.

Commands are in **Start the application** and **Local marketplace ingest** below.

## Collector Review web UI

`app/collector_review.py` provides the main Streamlit interface for
searching auction history, comparing pressing identities, and editing
collector metadata.

### Data shown

The main result set combines:

- native Buyee warehouse auctions (JPY);
- native eBay warehouse auctions (local sold-card currency, with
  Gripsweat USD stamped on duplicates); and
- Gripsweat-only sales after exact native-eBay listing-ID
  deduplication.

Result counts are calculated from the current database and are not
hard-coded in the application.

Recent-ingestion metadata keeps the real auction closing timestamp
separate from the date on which a listing first entered the warehouse.
The table exposes `Opened`, `Closed`, `Added`, `Activity`, and
`Date basis` independently.

### Start the application

One command brings up the existing Postgres on port 5544 and Collector Review
at `https://localhost:8501`. If either one stops, the watcher starts it again.
It does not create a new database.

```bash
./scripts/start-local.sh
```

The log is `logs/collector-ui/start-local.log`. Stop the watcher with
`kill "$(cat logs/collector-ui/start-local.pid)"`.

Back up `auction_warehouse` to `output/backups/`. That folder is gitignored.

```bash
./scripts/backup-auction-warehouse.sh
```

The same app can be started by hand:

```bash
cd ~/auction-etl
source .venv/bin/activate

export DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse'
export AUCTION_ENV=development
export OIDC_ENV=development
export OIDC_REDIRECT_URI='https://localhost:8501/oauth2callback'

mkdir -p .streamlit/certs
if [ ! -f .streamlit/certs/localhost.pem ]; then
  mkcert -install
  mkcert \
    -cert-file .streamlit/certs/localhost.pem \
    -key-file .streamlit/certs/localhost-key.pem \
    localhost 127.0.0.1 ::1
fi

python -m streamlit run             app/collector_review.py             --server.address 127.0.0.1             --server.port 8501             --server.headless true             --server.sslCertFile .streamlit/certs/localhost.pem             --server.sslKeyFile .streamlit/certs/localhost-key.pem
```

Open `https://localhost:8501` for Yahoo login. Yahoo requires HTTPS, including
localhost. Keep the Yahoo Developer redirect URI as
`https://localhost:8501/oauth2callback`. Collector Review serves that callback
with a local mkcert TLS certificate. HTTP 8501 cannot complete Yahoo login.

Yahoo login only identifies the operator. It does not import Yahoo Mail or
Yahoo Auctions inventory. Local Buyee, eBay, and Gripsweat rows live in
PostgreSQL and stay invisible until they are attached to that personal
account. In development, Collector Review attaches the local warehouse to the
signed-in Yahoo account after login so Review is not an empty first-run
workspace.

Always use the project virtual environment. A system Python installation
may not include Streamlit or the repository dependencies.

### Local marketplace ingest

eBay, Buyee, and Gripsweat all write to the same warehouse. eBay is a
generalized local sold/completed crawl from tracked artists, using hidden
headed Google Chrome. It is not a FaceRecords seller handoff.

```bash
cd ~/auction-etl
source .venv/bin/activate
export DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse'
unset RAILWAY_ENVIRONMENT RAILWAY_ENVIRONMENT_ID RAILWAY_PROJECT_ID RAILWAY_SERVICE_ID RAILWAY_REPLICA_ID

# Add/enable artists in Collector Review, then start a local refresh.
# Streamlit queues the job and starts the local worker automatically.
# Direct CLI equivalent:
.venv/bin/python scripts/run_latest_auction_refresh.py \
  --database-url "${DATABASE_URL}" \
  --expected-database-name auction_warehouse \
  --expected-database-user auction
```

Teresa Teng eBay completed/sold item URLs (`itm/{id}`) are the sale
identity. Gripsweat often archives the same sale as `/item/{id}/`.
Those overlaps are expected. Native eBay still wins the visible row.
**Gripsweat's sold amount on `sold_at` is the official transaction-day USD**
for that duplicate, even when the eBay card is not USD. eBay sold cards
are local display currency; do not treat bare `$` as official USD. Sold
cards with no Gripsweat row are also expected.

```bash
.venv/bin/python scripts/compare_ebay_sold_to_gripsweat.py
```

That writes operator notes under gitignored `reports/` so the overlap
comb is kept next to the work without landing in git.

### Listing interaction

The Listings tab uses AG Grid rather than Streamlit's native
checkbox-selection dataframe.

- Hovering highlights the complete auction row.
- Clicking any normal cell opens that auction in the collector editor.
- Exactly one row is selected at a time.
- Marketplace, listing ID, and title remain pinned while scrolling.
- The `Listing` link opens the external auction page without selecting
  a different row.
- The sidebar search/jump control can locate a filtered listing by
  marketplace, listing ID, seller, or title.
- Selection is stored by the stable
  `(marketplace, listing_id)` identity rather than a row position.
- Changing filters or pages cannot silently redirect the editor to a
  different listing.

The Pressing groups tab also contains a grid. Browser tests must select
a visible AG Grid iframe because Streamlit creates component frames for
tab content that may currently be hidden.

### Search and reporting

The sidebar supports:

- marketplace filtering;
- free-text title, ID, seller, artist, matrix, and catalog search;
- recent additions;
- activity-date ranges;
- collector verdict;
- media type;
- collection status;
- auction or fixed-price sale type;
- local or normalized-USD price ranges; and
- configurable pagination.

The editor preserves automatic classification while allowing explicit
overrides for media type, catalog or matrix identity, pressing region,
pressing type, completeness, condition, verdict, collection ownership,
purchase information, and collector notes.

### What a row means

A sale is one record, a factory box, or a pile. The status mark says how far the review has gone. Lots have no Matched and All piles, so the mark is the way to see what is still open.

```mermaid
flowchart TD
    Sale["One sale"]
    Sale --> Kind{"What is in the sale?"}
    Kind -->|"One record, or a CD box such as CD BOX or 全5巻"| Search["Discogs search stays open"]
    Kind -->|"Photo, print, or a single magazine"| Paper["One condition. Discogs stays off"]
    Kind -->|"One format in the pile"| OneCount["One count, up to 20000"]
    Kind -->|"More than one format, such as LP 2 and EP 2"| Mixed["Choose each format, then a count for each"]
    Kind -->|"Magazines, or a pile counted in 冊"| Mag["Magazine bulk lot"]
    Search --> Mark["Status mark"]
    Paper --> Mark
    OneCount --> Mark
    Mixed --> Mark
    Mag --> Mark
    Mark --> Blank["Blank. Not done"]
    Mark --> Touched["● Touched. Opened or saved"]
    Mark --> Edited["✎ Adjusted. A field was edited"]
    Mark --> Done["✓ Processed. Identity is filled"]
```

● is the first mark, once the row has been opened or saved. ✎ means a grade, count, note, or other field was edited. ✓ means the Discogs identity is filled. A blank row has not been touched. On the Lots filter the pills are All lots, Not done, Touched, Adjusted, and Processed.

A mixed lot stores its counts as the first completeness-notes line, `Lot mix: LP 2, EP 2.` The disc count is the sum. A single-format lot keeps one number: records for an LP pile, CDs, EPs, cassettes, or magazines for the others.

### Pressing, completeness, and catalog search

A listing is one format. LP, EP / 7", and 12" stay vinyl. A CD has a booklet and no poster. A cassette has a lyric card and no obi or poster. A photo, print, or magazine is not a record. A CD box, including a title that says CD BOX or 全5巻, is one release and keeps the Discogs search. A lot is several copies and skips pressing identification. An LP lot counts records, a CD lot counts CDs, an EP lot counts EPs, a cassette lot counts cassettes, and a magazine lot is a Magazine bulk lot. A pile counted in 冊, or a DVDマガジン, is a magazine lot. A mixed lot is more than one of those formats: choose which formats are in the pile, then enter how many of each. The title LP 2 枚とEP 2 枚 opens as a mixed lot with 2 LPs and 2 EPs.

Obi is a Japanese pressing only. Hong Kong, Taiwan, Singapore, and any other set region save Obi as No.

An LP is complete when this copy still has the paper the factory included. The insert control names that pack, and it names a missing insert separately:

- **Yes.** The insert is here, with the obi and pin-up this pressing used.
- **Missing the insert.** The pressing included an insert. This copy does not have it, so the copy is not complete. The obi and pin-up can still be here.
- **Insert only.** That sheet is here, and it is all the factory included. Obi and pin-up lock to No.
- **Pin-up is the insert.** The pin-up is the sheet. There is no separate poster.
- **Factory no insert.** This pressing never included an insert. Pin-up is No. A Japanese pressing can still have an obi.

A sealed copy locks the record and jacket, or the disc and case, to S. LP and EP grades are Goldmine. CD and cassette grades are the shop letters S–D and Goldmine.

Disc count comes from the Discogs release. A single LP is 1. A double LP is 2. Use this keeps the grades and completeness already on the form. Save opens the next listing in the current pile.

Catalog search takes a catalog number or an album name. A catalog number is searched across Discogs, including a soundtrack filed under another artist. An album name stays on the listing artist. The listing's format is listed first. A catalog printed in the seller's description is the pressing. On a Gripsweat page that number is in the item text under the sold price, as in Cal 04-1056, and the price and feedback count are not read as a catalog. Cover comparison uses the sleeve photo's pixels and colors. The same catalog can still be a different cover.

### Safety

Loading, filtering, pagination, hovering, row selection, report
generation, and browser acceptance are read-only.

A database write occurs only after pressing
`Save collector record`. That operation updates the selected
`warehouse.auction_collector` identity and does not prune warehouse
auctions.

`Refresh database` clears Streamlit's cached query result. It does not
crawl marketplaces, synchronize staging data, prune rows, or operate
Docker or Colima.

### Focused tests

```bash
source .venv/bin/activate

python -m pytest -q             tests/test_collector_hover_click_grid.py             tests/test_collector_hover_click_acceptance_source.py             tests/test_live_collector_pagination.py             tests/test_main_review_recent_integration.py             tests/test_duplicate_dataframe_columns.py
```

### Real browser acceptance

Start Collector Review first, then run:

```bash
source .venv/bin/activate

evidence_dir="logs/manual-hover-click-$(date +%Y%m%d-%H%M%S)"

python scripts/accept_collector_hover_click.py             --evidence-dir "${evidence_dir}"             --keep-open-seconds 5
```

The acceptance test:

1. ignores AG Grid frames inside hidden tabs;
2. locates a visible listing row;
3. confirms that checkbox selection is absent;
4. confirms full-row hover and the pointer cursor;
5. clicks a non-link cell;
6. verifies that the collector editor opens; and
7. saves screenshot and JSON evidence without changing the database.

Add `--headless` for non-interactive execution.
<!-- collector-review-ui:end -->

<!-- collector-save-upsert:start -->
### Collector metadata saves

Before updating collector metadata, Collector Review ensures that the
selected `(marketplace, listing_id)` has a row in
`warehouse.auction_collector`.

The ensure-row statement uses a PostgreSQL
`INSERT ... VALUES ... ON CONFLICT DO NOTHING` operation. Both identity
parameters are explicitly cast to `character varying`, matching the
warehouse identity columns and preventing ambiguous Psycopg parameter
inference.

Clicking `Save collector record` is the only action in the review
workflow that writes collector metadata. Searching, filtering,
hovering, selecting rows, changing pages, opening external listing
links, and browser acceptance remain read-only.
<!-- collector-save-upsert:end -->

<!-- collector-filtered-export:start -->
## Filtered and recent-ingestion exports

Auction ETL automates a real collector workflow: continuously collecting
completed eBay and Buyee auction results, preserving source provenance,
normalizing marketplace-specific fields, classifying physical media and
pressings, reviewing uncertain records, and producing collector reports.

The Listings tab includes an
**Export filtered or recent ingestion listings** panel with three
independent actions:

1. **Prepare filtered export** exports every historical and recent row
   matching the current sidebar filters.
2. **Prepare recent-in-filter export** exports recent ingestion rows that
   also match the selected marketplace, search, seller, date interval,
   media, verdict, sale type, collection, and price filters.
3. **Prepare all recent ingestion** exports the established recent
   ingestion set regardless of sidebar filters.

The recent set uses the integrated `_is_recent_addition` metadata when
available. Batch and ingestion-date fields provide fallbacks for sources
that do not expose that flag.

CSV, Excel, JSON, and plain-text exports preserve every dataframe column,
including automatic classifications, collector overrides, audit fields,
recent-ingestion metadata, activity timestamps, source information, and
custom recovery columns.

Markdown and Word exports are intentionally collector-optimized and group
listings by media type while presenting title, pressing, catalog or
matrix identity, condition, seller, bids, tax, totals, dates, notes, and
auction URL.

The media selector can export all matches in one file, one selected media
type, or a ZIP containing one file per media type.

Deduplication prefers native eBay warehouse records over matching
Gripsweat archive records sharing the same listing ID. On those
duplicates, the Gripsweat USD amount on the sale date is the official
transaction-day USD. Exporting is read-only and never deletes or
modifies warehouse records.
<!-- collector-filtered-export:end -->

<!-- BEGIN AUCTION_ETL_CLOUD_ARCHITECTURE -->

## Architecture and deployment status

The authoritative architecture is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

The accepted runtime is local: Collector Review on HTTPS `localhost:8501`, PostgreSQL at `127.0.0.1:5544/auction_warehouse`, and three marketplace ingest paths that all write that warehouse. Vercel, Railway, and Neon are deferred shells, not the data plane.

```mermaid
flowchart LR
    Start["./scripts/start-local.sh"]
    Watch["Watcher. Restarts the app or the database if either stops"]
    UI["Collector Review HTTPS localhost:8501"]
    DB[("Local PostgreSQL 5544 auction_warehouse")]
    Backup["./scripts/backup-auction-warehouse.sh"]
    Out["output/backups. Gitignored"]
    EbayOp["Headed eBay operator"]
    Buyee["Headed Buyee owner"]
    Grip["Gripsweat probe / import"]
    Sources["Completed/sold marketplaces"]

    Start --> Watch
    Watch --> UI
    Watch --> DB
    UI --> DB
    DB --> Backup
    Backup --> Out
    EbayOp --> Sources
    Buyee --> Sources
    Grip --> Sources
    EbayOp --> DB
    Buyee --> DB
    Grip --> DB
```

Current architecture status:
  * Local warehouse counts after the 2026-09-19 loop: Buyee 411, eBay 899, Gripsweat 827.
  * eBay ingest is a generalized local sold/completed crawl from tracked
    artists (`LH_Sold=1`, `LH_Complete=1`, `_sop=13`) using hidden Chrome.
  * Buyee uses the headed owner; Gripsweat uses configured artist probe/import.
  * Phase-D account tenancy remains in the product, with Collector Review login on HTTPS localhost:8501.
  * Vercel/Railway/Neon must not be pointed at this loopback database.

- Durable refresh coordination lives in local PostgreSQL.
- Railway is deferred (trial expired) and is not part of the accepted local runtime.
- Compatibility identifiers such as `auction_etl`, `~/auction-etl`, and `auction-etl-staging` remain unchanged for now.

<!-- COLLECTOR_LEDGER_PHASE_D_AUTH_ACCOUNTS -->
## Phase D — authentication and private accounts

Collector Ledger's next milestone adds OIDC authentication, personal accounts,
account-scoped marketplace visibility, private collector curation,
account-owned tracked artists/refresh jobs, and isolated Buyee connection
state.

See `docs/PHASE_D_AUTH_ACCOUNT_ARCHITECTURE.md` and the generated
`docs/ACCOUNT_SCOPING_MATRIX.generated.md`.

## Phase D auth/account tenancy closeout

Phase D is merged into `main` and accepted for the current staging architecture.

- Visible listings: **1440**
- Tracked artists: **3**
- Marketplace searches: **5**
- Owner account acceptance: **PASS**
- Historical 58-identity staging restore: **complete**
- Owner backfill: **complete**
- Stale `1441` acceptance invariant: **removed**
- Phase-D post-merge smoke: **PASS**

This milestone records the completed staging/account-tenancy state. It does not represent production runtime/data cutover; refresh-worker hosting and production promotion remain separate explicit operations.
