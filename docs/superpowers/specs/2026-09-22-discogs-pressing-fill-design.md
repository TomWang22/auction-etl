# Discogs pressing fill (identity only)

Date: 2026-09-22

## Problem

Marketplace refresh only ingests sales. As of this design, the warehouse had ~1439 auctions and ~1433 unassigned intake-queue rows, with 2 local pressings. Operators must type identity by hand. Titles often already carry catalog tokens (`MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP`). Completeness (obi, insert, poster) is a later, local concern.

## Goal

After ingest, New Auction Intake shows a Discogs **release shortlist**. The operator **clicks one release**. That click fills canonical pressing identity (label choice, catalog, year, country, format, matrix, Discogs ids) **and Collector Review shows those fields on that sale immediately**. Completeness (obi, insert, poster) stays on the pressing library, optional, once per pressing — not a per-sale form.

No computer vision. Listing photos sit next to Discogs cover so variants can be distinguished by eye. **Dead-on unique matches fill without review.** Ambiguous matches stay on the grid as flagged rows — never a popup.

## Discogs is the catalog, not completeness

Verified against the public page and API for a sale already in the warehouse:

- Page: https://www.discogs.com/release/10320765 (山口百恵 – 15才, CBS/Sony `SOLL-114`, Japan 1974 LP)
- API: `GET https://api.discogs.com/releases/10320765`

That release has structured identity (artist, label+catno, format, country, year, matrix, images) and a free-text `notes` sentence: “This release includes a lyric sheet and a glossy booklet…”. Notes are **not** a structured obi/insert/poster record. Do not map notes into `system.component_type` expectations.

## API usage

Authentication required for search. Identify as `auction-etl/1.0` (or similar unique User-Agent). Use the Discogs application **key + secret** (Developer Settings → VinylPriceAnalyzer consumer key/secret) or a personal token. Store in `.streamlit/secrets.toml` under `[discogs]` (`key`, `secret`) and/or `DISCOGS_TOKEN`. Header: `Authorization: Discogs key=…, secret=…` or `Authorization: Discogs token=…`. Never log credentials. Database search does **not** need the OAuth request-token dance; key+secret raises the rate limit to 60/min.

| Call | When |
|---|---|
| `GET /database/search?type=release&catno=…&artist=…&format=Vinyl` | After ingest, for each unassigned queue row that has a catalog token or artist+title. Fallback: `q=` from title when catno is missing. |
| `GET /releases/{id}` | After the operator clicks a shortlist row. |

Search `catno` on Discogs is catalog-number search (example in docs: `DGCD-24425`). Normalize hyphens and spaces so listing `SOLL114` matches Discogs `SOLL-114`.

Rate limit: 60 authenticated requests / minute / IP (`X-Discogs-Ratelimit-*`). Pace the post-ingest lookup; cache search JSON on the queue row so intake does not re-hit search on every page load. Do not retry-storm 429s.

## Fill on click (identity)

From `GET /releases/{id}`:

| Discogs | Local |
|---|---|
| `artists[].name` (display `anv` if present) | `warehouse.release_family` artist |
| `title` | `warehouse.release_family` title |
| `labels[]` where `entity_type_name=Label` | `warehouse.label` (`display_name`, unique `discogs_label_id`) and `pressing_identity.label_id` |
| `labels[].catno` | `pressing_identity.catalog_number` |
| `id` | `pressing_identity.discogs_release_id` (unique) |
| `master_id` | `pressing_identity.discogs_master_id` (nullable, not a second pressing) |
| `year` / `released` | `pressing_identity.release_year` |
| `country` | `pressing_identity.country` (Japan also sets region Japan) |
| `formats[].name` + `descriptions` + `qty` | `media_type`, `format_detail`, `disc_count` (`Vinyl`+`LP`+`qty=1` → LP / 1) |
| `formats[].descriptions` Promo / Reissue | `generation` PROMO / REISSUE only; never invent FIRST_PRESS |
| `identifiers` type `Matrix / Runout` | `matrix_number` (join distinct values; keep full list in notes if long) |
| `images` / `thumb` | shortlist + picker only; do not treat as completeness evidence |
| `uri` | store as `discogs_uri` for the operator to open |

If `labels[]` has more than one Label entity, the click target is the **release**, then a second click picks the label. One-label releases (this CBS/Sony example) skip that step.

## Do not fill from Discogs

Obi, insert, lyric sheet, poster, pin-up, booklet, inner sleeve, box, sticker, shrink, factory sealed, condition, first-press vs early-press. Completeness stays on `warehouse.pressing_component_expectation` and the existing wizard **after** assignment.

`notes` may be shown as a read-only hint on the picker. It is never parsed into component expectations.

## Schema

- `warehouse.label`: `id`, `display_name`, `discogs_label_id` unique nullable, timestamps.
- `warehouse.pressing_identity.label_id` nullable FK → `warehouse.label`. Keep `label_name` populated from the chosen label for existing views.
- `warehouse.pressing_identity.discogs_release_id` unique nullable.
- `warehouse.pressing_identity.discogs_master_id` nullable.
- `warehouse.pressing_identity.discogs_uri` nullable.
- `warehouse.auction.label` remains listing-extract **hint** for search, not the canonical choice.
- `warehouse.auction.image_url` nullable (from staging listing image). Exposed on Collector Review.
- `warehouse.auction.identity_status` — `unmatched` | `needs_review` | `filled_auto` | `filled_manual`
- `warehouse.auction.identity_source` — `listing` | `discogs`
- `warehouse.auction.identity_filled_at` timestamptz nullable
- `warehouse.auction.discogs_thumb_url` nullable (display only)
- Intake cache: persist shortlist JSON on `system.new_auction_assignment_queue` (or on the auction row) plus fetched-at, account-scoped.

Alembic follows current head (including local `auction.label` if that revision is applied).

## Operator flow

1. Refresh ingests sales (unchanged crawl).
2. Discogs identity pass runs on **new/updated** warehouse rows only.
3. Dead-on → assigned + Collector Review shows label/catalog/year/cover immediately, badge **Filled**.
4. Not dead-on → same grid, badge **Needs review**, listing photo + Discogs shortlist inline.
5. Manual click on a flagged row → **Filled** (manual), Updated marker.
6. Empty shortlist → **Unmatched**, still listed; no popup.

The 11-stage cohort wizard is not the first-identity UI.

## Ingest overhaul

Refresh stays crawl → parse → normalize → warehouse. Add a **Discogs identity pass** immediately after warehouse sync, paced at ≤60 authenticated calls/min.

For each newly inserted/updated auction in that run:

1. Build a search key: `catalog_number` if present, else catno token in the title (`SOLL114` ≡ `SOLL-114`), plus artist tokens from `artist` or title.
2. `GET /database/search?type=release&catno=…&artist=…` (add `format=Vinyl` when media looks like LP/vinyl). Cache the shortlist on the listing.
3. Classify the result (below). **Dead-on:** write pressing + assignment + show on Collector Review immediately. **Not dead-on:** do not guess; flag the row in the main grid.

Ingest UI (no modal): marketplace cards and Collector Review captions like `12 filled · 3 need review`. Rows that just changed get an inline **Updated** marker (`identity_filled_at` / `identity_status_changed_at`), sortable, not a popup.

## Dead-on vs flagged

**Dead-on (review not needed)** — all of:

- A catalog token exists (field or title).
- After hyphen/space fold, Discogs `catno` equals that token.
- Exactly **one** search hit remains after keeping vinyl/LP (or the listing’s media type) and, when the listing is JP-titled or Japan-pressed, preferring `country=Japan`.
- Artist overlap: listing artist or title contains a Discogs artist/ANV token (e.g. Yamaguchi / 山口百恵 / Momoe).

Then auto-upsert family/label/pressing, assign, set `identity_status = filled_auto`, `identity_source = discogs`.

**Flagged (review needed)** — 0 hits, 2+ plausible hits, catno mismatch, or no catalog token (title-only fuzzy). Set `identity_status = needs_review`, keep shortlist on the row. Operator clicks a candidate **on the row** (expand/inline chooser), not a popup. Choosing one sets `identity_status = filled_manual`.

Pictures: listing `image_url` must move from staging onto `warehouse.auction` and Collector Review so the sale photo shows on the main grid. After a fill, also show Discogs `thumb`. Photos are **display + flagged-row comparison**, not a vision matcher.

Second sale of the same `discogs_release_id` is dead-on by identity reuse: no extra Discogs search required if the catalog already maps to a local pressing.

## Show identity on Collector Review immediately

Collector Review (`warehouse.auction_collector_review`) is the main listing surface. Today it does **not** join `auction_pressing_assignment` / `pressing_identity`. Effective catalog/label come from listing extract and collector overrides only. A Discogs click that only writes the pressing library would stay invisible there.

After a click:

1. Assignment exists (`warehouse.auction_pressing_assignment`).
2. Collector effective view prefers **pressing identity** over listing extract:

   `effective_label` = collector manual label if any, else `warehouse.label.display_name` / `pressing.label_name`, else `auction.label` (extract hint).

   `effective_catalog_number` = collector manual, else `pressing.catalog_number`, else listing/auto catalog.

   Same pattern for media type, disc count, region/country, year (add `effective_release_year` if the review grid needs it).

3. Refresh the Collector Review query so the row shows label/catalog/year/format **on the next load** with no extra form.

Analytics pages that already filter on `effective_catalog_number` then group the same pressing without a second fill step.

## Completeness references the library, not each sale

Obi / insert / poster are **pressing-library** facts (`warehouse.pressing_component_expectation`), not ingest fields.

Wrong friction: Discogs click opens the completeness wizard, or every new sale needs obi/insert/poster checkboxes.

Correct split:

| Layer | When | Who |
|---|---|---|
| Identity | Dead-on auto-fill, or click on a flagged row | Once per *pressing* (reused for later sales with the same `discogs_release_id`) |
| Library completeness | Optional, later, on that pressing | Once per pressing: “this CBS/Sony LP is expected to include obi + insert” |
| This copy | Optional collector observation | Only if you care about this auction’s missing obi |

Until a pressing has library expectations, Collector Review shows identity and leaves obi/insert/poster as **unspecified** (`NULL`), not missing and not required. Do not treat unspecified as incomplete.

When the library *is* curated later, sales already assigned to that pressing inherit the expected-set in completeness views automatically. No re-ingest.

Do **not** seed REQUIRED expectations from Discogs `notes` (the 15才 page says “lyric sheet and booklet” in prose only). Optional: show `notes` on the picker as a hint for later library work.

A second sale of SOLL-114 hits the same `discogs_release_id`, reuses the pressing, and shows identity immediately. Completeness still follows that one library row.

## Non-goals

- Auto-assign when two Discogs releases share the same catalog (those stay flagged).
- Discogs marketplace listings / prices as warehouse facts.
- OCR or vision matching of listing photos to Discogs images.
- Creating completeness expectations from `notes`.
- Modal/popup review after ingest.
- Replacing ingest/crawl.

## Test plan

- Search key: `SOLL114` in an eBay title produces catno `SOLL114` / `SOLL-114` equivalent.
- Mapping fixture from the 10320765 payload: CBS/Sony label id 33078, catalog `SOLL-114`, Japan, 1974, LP, matrices `SOLL-114A2` / `SOLL-114B3`, generation not FIRST_PRESS, notes not creating OBI/INSERT rows.
- Unique catno+artist+vinyl hit auto-fills and sets `identity_status=filled_auto` with no operator click.
- Two vinyl hits for one catno stay `needs_review` and do not assign.
- Collector Review effective label/catalog for an auto-filled listing equal the Discogs pressing values without a manual collector override.
- A second listing assigned to the same `discogs_release_id` reuses the pressing; no second identity form.
- Unspecified library completeness does not mark the sale incomplete or create OBI/INSERT expectation rows.
- Two Label entities on one chosen release require an explicit label choice.
- Missing token → `unmatched` or `needs_review`; the grid still lists the sale.
- Credentials never appear in logs or assignment audit payloads.
- Ingest copy reports filled vs needs-review counts; no modal component.
