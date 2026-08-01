# Auction ETL

Terminal-first ETL pipeline for collecting, normalizing, classifying, and analyzing collectible auction data from multiple marketplaces.

## Goals

- PostgreSQL warehouse
- eBay & Buyee ingestion
- Classification pipeline
- Analytics
- CSV / Markdown / Chatbot exports

<!-- collector-review-ui:start -->
## Collector Review web UI

`app/collector_review.py` provides the main Streamlit interface for
searching auction history, comparing pressing identities, and editing
collector metadata.

### Data shown

The main result set combines:

- native Buyee warehouse auctions;
- native eBay warehouse auctions; and
- Gripsweat-only sales after exact native-eBay listing-ID
  deduplication.

Result counts are calculated from the current database and are not
hard-coded in the application.

Recent-ingestion metadata keeps the real auction closing timestamp
separate from the date on which a listing first entered the warehouse.
The table exposes `Opened`, `Closed`, `Added`, `Activity`, and
`Date basis` independently.

### Start the application

```bash
cd ~/auction-etl
source .venv/bin/activate

export DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse'

python -m streamlit run             app/collector_review.py             --server.address 127.0.0.1             --server.port 8501             --server.headless true
```

Open `http://127.0.0.1:8501`.

Always use the project virtual environment. A system Python installation
may not include Streamlit or the repository dependencies.

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
