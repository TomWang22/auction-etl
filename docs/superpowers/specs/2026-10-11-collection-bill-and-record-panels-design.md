# Collection bill backfill and record anatomy

Date: 2026-10-11

This spec extends `2026-10-11-buyee-pdf-billing-design.md`. Where they disagree on multi-copy packages, **this spec wins**.

## Problem

Copies on My collection often have an item price from a stored sale (eBay, Gripsweat, or Buyee) and empty Shipping / Tax / Fees. The collector already paid those extras. The bills live in different shapes:

- **Buyee:** shipping invoice PDF. One file can be one auction or one package of several auctions.
- **eBay:** View order details text. One order can be one item or combined shipping for several item numbers. Gripsweat rows are the same eBay `{id}`.
- **Discogs:** marketplace order text (Subtotal, Shipping, Tax, Total).

Bring-in today treats “this catalog is already on the shelf” as done, so a real order never backfills the Gripsweat or eBay copy. Fill in the breakdown attaches **one** parsed bill to **one** selected row. Multi-auction Buyee PDFs park international shipping and customs as `Package …` lines that never land on any copy.

The same copies also need the ingest checklist: condition, obi (Japan only), insert, poster, sealed, rental. Billing completeness and record completeness are both missing on the shelf, and they are mixed into one table.

## Goal

A collector can drop or paste **one** bill, see every copy that bill covers, save shipping/tax/fees onto those rows without changing item price, and inspect **two panels** on a copy:

1. **Billing** — item, shipping, tax, fees, landed, source document.
2. **Record anatomy** — the same pressing / condition / edition fields Collector Review already stores for that listing.

Screenshots are not bills. No OCR. Catalog-only matching is forbidden.

## Two panels

Selecting a shelf row (whole row, one checkbox) opens two sibling panels, not one mixed card.

### Billing panel

Shows money only:

- Item (shelf amount, unchanged by a bill save)
- Shipping, Tax, Fees (from the billing note)
- Landed (item + converted charges)
- Source (eBay / Gripsweat / Buyee / Discogs), seller, paid-on
- Open listing
- Bill note (expander)
- Gaps: missing shipping/tax/fees, or “confirmed no extra charges”
- Fulfillment: **in process** or **delivered** is enough. Paid already means the copy is theirs. Do not block billing complete on Buyee’s later stages (seller → Buyee warehouse → package → international → customs).

This panel is the only place My collection **writes** a billing note. It may store `fulfillment_status` (`in_process` | `delivered`) on `collection_bill` as information, not as a gate.

### Record anatomy panel

MVC around the existing collector record. Not a second schema.

- **Model:** `auction_collector` fields Collector Review already edits (pressing identity, condition, edition completeness).
- **View:** the same groups as ingest — Pressing identification; Condition and assessment; Edition and completeness.
- **Controller:** save writes those columns. My collection and Collector Review are two doors to one record.

Fields (same labels as ingest):

| Group | Fields |
| --- | --- |
| Pressing identification | Catalog / matrix, region, disc count, pressing type |
| Condition and assessment | Record, Jacket, verdict, completeness/pressing notes, collector notes |
| Edition and completeness | Obi (Japan only), Insert, Poster / pin-up, Rental, rental sticker, Sealed, observed condition |

Obi is required only when `obi_for_region(region)` is true **and** the media profile shows obi. Hong Kong / Taiwan / other non-Japan pressings never ask for obi. `Automatic / unset` is a gap.

Sale type, “in my collection”, purchase date, purchase price, and purchase currency stay on the shelf / billing side. They are not duplicated in anatomy.

A logged `owned_copy` with no purchased listing has no collector record. Anatomy shows “not linked to a listing” and does not invent columns on `owned_copy` in this spec.

## Matching a bill to copies

Identity is listing id, not catalog, not title, not seller.

| Bill contains | Matches shelf row |
| --- | --- |
| eBay item number (`ebay.com/itm/{id}`, `Item number: {id}`, Gripsweat `item/{id}`) | `listing_id = {id}` and marketplace is **ebay or gripsweat** |
| Buyee `JDirectItems Auction({id})` | `listing_id = {id}` and marketplace is **buyee** |
| Discogs order id (long number on the order page) | Discogs / `owned_copy` with that external id |
| No id (totals card only: `1 item` / `Shipping` / `Tax*` / `Order total`) | The **selected** shelf row only |

If seller, date, or item amount on the bill disagree with the shelf, **still match on id**. Show the disagreement in the billing preview. Do **not** overwrite item price unless the collector confirms that replacement. Default: item stays; shipping/tax/fees write.

Buyee exception: a **one-auction** invoice whose auction id is not any shelf `listing_id` (this happened with `m1233352030` vs seller id `F8AAhZCgFb9EQhLhr`) applies to the **selected** row, same as today’s Fill in the breakdown. A **multi-auction** PDF never dumps the whole package onto the selected row; unmatched auction ids are listed and skipped.

Catalog-only matching is out. Greatest Hits on Gripsweat (`teresa-teng`, $179.99, Oct 5) must not receive a different eBay order (`professorsells`, $196.46, Feb 14).

Bring-in: a paste that is a **bill** for a copy already on the shelf is a backfill, not “already”. Do not skip it because the catalog is owned.

## Input formats

| Source | Accept | Refuse |
| --- | --- | --- |
| Buyee | Invoice PDF; pasted invoice text | PNG/JPG |
| eBay | Pasted View order details text (full page or totals card) | PNG/JPG; OCR |
| Discogs | Pasted order page text (`Subtotal`, `Shipping`, `Tax`, `Total`) | PNG/JPG; OCR |

Refusing an image: “Paste the order text, or type shipping and tax.” Typed Shipping / Tax / Fees on the selected copy remain valid.

eBay details labels that must parse:

```
1 item        $160.00
Shipping      $6.50
Tax*          $10.00
Order total   $176.50
```

Item stays $160.00. Shipping $6.50. Tax $10.00. Landed $176.50.

When the full eBay details page includes `Item number:` lines, those ids drive matching (combined shipping below).

Discogs keeps the existing Subtotal / Shipping / Tax / Total reader. Currency stays the order currency.

## One order, several copies

Shared postage is split. It is never copied in full onto every line. Per-item lines stay on that copy. Shared lines are divided **pro-rata by item price**. USD rounds to cents, JPY to whole yen. Remainder goes on the last matched copy so the pieces **sum back to the order**.

### eBay combined shipping

Proven shape: three item numbers, one shipping, one tax.

| Item number | Item | Share of $332.00 |
| --- | ---: | ---: |
| 236601326474 | $120.50 | 120.50/332 |
| 236601327666 | $120.50 | 120.50/332 |
| 366150834599 | $91.00 | 91.00/332 |

Order: items $332.00, shipping $54.00, tax $20.75, total $406.75.

Each matched copy keeps its item. Shipping and tax are that share of $54.00 and $20.75. The three landed amounts plus items equal $406.75.

### Buyee package PDF

This **replaces** the earlier rule that package international shipping and customs stay out of shelf columns.

Per auction, already printed on the PDF, stay on that copy:

- Item price (note only; shelf item unchanged)
- Plan fee
- Buyee service fee
- Domestic shipping (seller → Buyee)

Printed once for the package, split pro-rata by item price onto each auction in the file:

- International shipping
- Customs duty
- Customs clearance when it is a single package total

Shelf columns after the split:

| Column | Lines |
| --- | --- |
| Shipping | That copy’s domestic shipping + its share of international shipping |
| Tax | That copy’s share of customs duty |
| Fees | Plan fee + service fee + that copy’s share of clearance |
| Landed | Shelf item dollars + those yen lines converted |

The note still keeps the labeled yen lines and the package totals so the split can be audited. Yen stays yen. Landed uses the printed USD pair when present, else the existing rate path.

One-auction Buyee invoices are unchanged from `2026-10-11-buyee-pdf-billing-design.md`: every charge line belongs to that copy; nothing is prefixed `Package`.

## Save

1. Drop or paste one bill.
2. Resolve copies by id, or the selected row if there is no id.
3. Preview **every matched copy**: item unchanged, split charges, landed, billing gaps, anatomy gaps.
4. Ids in the bill that are not on the shelf are listed and skipped. No new copies.
5. Confirm writes all matched billing notes in one go.
6. Anatomy gaps are not auto-filled from the bill. Item Name on a Buyee PDF is not identity and not completeness.

## Completeness of both sides

A copy is incomplete until both tracks are done.

**Billing complete:** the copy is purchased (paid is set) **and** shipping/tax/fees are present from a bill or typed amounts, or the collector confirmed there were no extra charges. **In process** and **delivered** both count. Buyee has many moving parts after payment; waiting for the box is not required.

**Record complete:** pressing identification, record and jacket condition, verdict, and the edition fields the media profile + region require are set (not `Automatic / unset`).

The shelf marks billing-only gaps, anatomy-only gaps, and both. “Catalog already on the shelf” is not complete.

## Schema

Separate tables. Billing is not a column on the listing, and anatomy is not a billing row. Listing postage (`warehouse.auction.shipping_price`, `tax_amount`, `landed_price_usd`) is what the **sale** advertised. Collection postage is what **this account paid**. Those must not share columns.

### Record anatomy — existing table

`warehouse.auction_collector` keyed by `(account_id, marketplace, listing_id)` when `account_id` is set.

Obi, insert, poster, rental, sealed, Record/Jacket (`manual_condition_media` / `manual_condition_cover`), verdict, region, disc count, pressing type, completeness notes, collector notes stay here. Collector Review and the anatomy panel both read and write these columns. No second completeness table.

`warehouse.owned_copy` stays for Discogs / logged copies with no scraped listing. Unique `(account_id, source, external_id)`. Anatomy does not invent completeness columns on this table in this spec.

### Billing — two new tables

`warehouse.collection_bill` — one eBay order, one Buyee PDF, one Discogs order, or one typed sheet.

| Column | Role |
| --- | --- |
| `id` | bigserial PK |
| `account_id` | uuid, not null |
| `source` | `ebay` / `buyee` / `discogs` / `typed` |
| `external_order_id` | eBay order number, Buyee order id, Discogs order id; null for typed |
| `currency` | ISO code of the bill |
| `item_total`, `shipping_total`, `tax_total`, `fee_total`, `grand_total` | numeric(18,2); package totals before split |
| `raw_note` | labeled mechanical lines for the whole document |
| `billed_on` | date, nullable |
| `fulfillment_status` | `in_process` / `delivered` / null; not a completeness gate |
| `created_at`, `updated_at` | timestamptz |

Unique `(account_id, source, external_order_id)` where `external_order_id` is not null. Re-saving the same order upserts this row and replaces its lines.

`warehouse.collection_bill_line` — one shelf copy in that bill.

| Column | Role |
| --- | --- |
| `id` | bigserial PK |
| `bill_id` | FK → `collection_bill` ON DELETE CASCADE |
| `account_id` | uuid, not null (denormalized for shelf lookups) |
| `marketplace` | shelf marketplace (`ebay`, `gripsweat`, `buyee`, `discogs`, …) |
| `listing_id` | shelf listing / `owned_copy.external_id` |
| `printed_id` | auction or item id as printed on the bill |
| `item_amount` | amount on the bill for this line; does not overwrite shelf paid |
| `shipping_amount`, `tax_amount`, `fee_amount` | **allocated** share |
| `line_note` | per-copy labeled lines after split |
| `created_at` | timestamptz |

Allocated shipping/tax/fees for one `bill_id` **sum to** that bill’s totals (cents/yen remainder on the last line).

`manual_purchase_notes` / `owned_copy.billing_note` remain an audit copy of `line_note` so today’s `copy_costs` readers still work. The shelf **prefers** the line table when a row exists.

Do not add shipping/tax/fee columns onto `auction_collector`. That table already mixes listing economics and collector fields; billing stays out.

### Retrieval as the shelf grows

Hot path: My collection for one account, purchased copies only, newest paid-on first, plus the latest bill line per copy, plus anatomy fields already on `auction_collector`.

Indexes (all btree, additive, `IF NOT EXISTS`):

| Table | Index | Why |
| --- | --- | --- |
| `auction_collector` | `(account_id, manual_purchased, manual_purchase_date DESC)` | shelf list; today’s `ix_auction_collector_purchased` is purchased-only and will not stay selective |
| `auction_collector` | `(account_id, listing_id)` | eBay item number → Gripsweat or eBay row without scanning marketplace |
| `owned_copy` | `(account_id, paid_on DESC)` | logged-copy shelf; unique `(account_id, source, external_id)` already covers id lookup |
| `collection_bill` | `(account_id, billed_on DESC)` | account order history |
| `collection_bill` | unique `(account_id, source, external_order_id)` | upsert the same eBay/Buyee/Discogs order |
| `collection_bill_line` | `(account_id, marketplace, listing_id, created_at DESC)` | latest bill for one copy (`LATERAL … LIMIT 1`) |
| `collection_bill_line` | `(bill_id)` | load every line when previewing/saving a package |
| `collection_bill_line` | `(account_id, printed_id)` | match a pasted auction/item id to a line already stored |

Shelf query: filter `auction_collector` by `account_id` and `manual_purchased`, join identity views on `(marketplace, listing_id)`, `LEFT JOIN LATERAL` the latest `collection_bill_line` for that account + marketplace + listing_id. Do not parse `manual_purchase_notes` on every grid load once a line exists. Do not scan `warehouse.auction` to render the collection grid.

Matching a pasted eBay item id: `WHERE account_id = :account AND listing_id = :id AND marketplace IN ('ebay', 'gripsweat') AND manual_purchased IS TRUE` uses `(account_id, listing_id)`.

Never `SELECT *` the bill `raw_note` for the grid. Notes load when the billing panel opens.

FK `collection_bill.account_id` and `collection_bill_line.account_id` follow the same account uuid pattern as `owned_copy`. Line `account_id` must equal the parent bill’s `account_id` (check or write-path invariant).

Local schema change is additive (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`) in the existing collector schema upgrade path. Do not point hosted deploys at the local warehouse.

### Live warehouse coverage (2026-10-11)

52 base tables in `identity`, `account`, `ops`, `system`, `warehouse`. This feature **writes** only the two new billing tables and the existing collector/owned purchase notes. Everything else is read-only or untouched.

**Write**

| Relation | Role |
| --- | --- |
| `warehouse.collection_bill` | new; one order/PDF |
| `warehouse.collection_bill_line` | new; one copy in that order |
| `warehouse.auction_collector` | anatomy fields; `manual_purchased` / paid already set; audit `manual_purchase_notes` |
| `warehouse.owned_copy` | Discogs/logged copies; audit `billing_note` |

**Read / join (do not scan the full auction table for the grid)**

| Relation | Role |
| --- | --- |
| `warehouse.auction_collector_effective` | view: title, catalog, cover, listing url |
| `warehouse.auction_collector_review` | view: same collector fields the anatomy panel shows |
| `warehouse.pressing_identity` | catalog, region, discogs ids |
| `warehouse.release_family` | artist/album display |
| `warehouse.label` | label display |
| `warehouse.gripsweat_sale` | confirm Gripsweat `{id}` is the same eBay item id; do not store bills here |
| `account.auction_listing` | account may see the listing |
| `identity.account` | `account_id` on bills |
| `system.media_profile_component` | which edition fields the media kind requires |
| `system.condition_grade` | Record/Jacket grade vocabulary |

**Do not write (easy to grab by mistake)**

| Relation | Why not |
| --- | --- |
| `warehouse.auction` | listing economics (`shipping_price`, `tax_amount`, `landed_price_usd`) are the sale, not this purchase |
| `warehouse.auction_detail` | listing HTML/detail crawl |
| `warehouse.auction_purchase_review` | old global purchase table, no `account_id`; leave it |
| `warehouse.gripsweat_source` | probe metadata |
| `warehouse.pressing_component_expectation` | pressing-master “what the factory included”; anatomy uses collector fields |
| `warehouse.auction_component_observation` | listing observations |
| `warehouse.auction_pressing_assignment` | ingest assignment |
| `system.listing_completeness_snapshot` | listing completeness history (~13 MB); not the collection bill |
| `ops.*` | refresh jobs |
| `account.tracked_artist` / `artist_marketplace` / `marketplace_connection` | tracking, not bills |
| Analytics / evidence / normalization / verdict / crawl tables | unrelated |

Buyee moving parts (win → domestic to Buyee → package → international → customs → delivered) all live **in the invoice PDF and `collection_bill`**, not as extra warehouse tables.

## Discogs complete-run (follow-on, not this spec)

Discogs API is already the **catalog** for pressing identity (`2026-09-22-discogs-pressing-fill-design.md`). It is not a structured obi/insert/poster record. A later “complete run fill” may show Discogs notes and `pressing_component_expectation` as **hints** of what this copy might still lack. It must not auto-write collector obi/insert/poster/condition from Discogs. Out of this billing/anatomy spec.

## Architecture

Keep parsers in `auction_etl.services.collection_import`. Keep shelf writes in `auction_etl.services.collection_shelf`. Bill insert/upsert lives next to `save_billing_note` and is what `save_billing_note` calls.

New helpers (names can vary, one job each):

- Match a parsed purchase to shelf rows by listing id, treating eBay and Gripsweat as the same id space.
- Split package / combined-shipping charges pro-rata so allocated lines sum to the source total.
- Billing completeness for one copy.
- Record anatomy completeness for one purchased listing, reusing `obi_for_region` and the existing media profile (`show_obi`, insert, poster).

My collection renders the grid, then the two panels, then Fill in the breakdown (drop/paste/type) which feeds the billing panel preview. Record anatomy reads and writes collector columns already used by Collector Review. No `st.dialog`.

## Error handling

- Image upload: refuse, tell them to paste text or type amounts.
- Paste with no charge lines: existing empty-bill message.
- Item amount on the bill ≠ shelf item: preview both; default keep shelf item.
- Partial match (three item numbers, one on the shelf): save the one, list the two skipped.
- Unlinked `owned_copy`: billing can still save on that row when it was selected or matched by Discogs id; anatomy stays unlinked.
- Do not match eBay orders to Buyee rows or the reverse.

## Out of scope

- OCR of screenshots
- Overwriting album title, artist, or catalog from a bill
- Auto-creating shelf rows for unmatched item numbers
- Equal-split of shared postage
- Putting the full package postage on every copy
- A second condition schema on `owned_copy`
- Shipping/tax/fee columns on `auction_collector` or `warehouse.auction`
- Full pressing-master component audit (insert quantity vs master) — anatomy uses the ingest collector fields only
- Auto-filling obi/insert/poster from the Discogs API
- Writing `warehouse.auction_purchase_review` or listing `shipping_price`
- Changing Vercel, Railway, Neon, or `DATABASE_URL`

## Tests

- eBay details paste: item / shipping / tax / total as in the $160.00 / $6.50 / $10.00 / $176.50 card; `copy_costs` shipping and tax match; paid_amount is the item, not the order total.
- eBay combined shipping: three item numbers + $54.00 shipping + $20.75 tax allocate pro-rata to the cent and sum to the order.
- eBay item number matches a Gripsweat shelf row with the same id; does not match a different catalog.
- Totals-only paste (no item number) applies only when a row is selected.
- PNG/JPG is not parsed as a bill.
- Buyee multi-auction PDF: per-auction plan/service/domestic stay on that id; international and customs duty allocate pro-rata; allocated yen sums to the package totals.
- One-auction Buyee invoice still has no `Package` prefix (existing tests stay green).
- Discogs order paste still splits subtotal / shipping / tax.
- Bring-in of a bill for an owned catalog is a backfill, not `already`, when the note has charge lines.
- Saving a bill does not change shelf title, catalog, or item price.
- `collection_bill` + `collection_bill_line` persist a three-item eBay order; allocated shipping and tax sum to the bill totals; shelf prefers the line over the text blob.
- Re-saving the same `(account, source, external_order_id)` upserts the bill and replaces its lines.
- Anatomy completeness: Japan region with unset obi is incomplete; Hong Kong with unset obi is not blocked on obi.
- Page contract: no `st.dialog`; billing panel and record anatomy panel both present; still no `LinkColumn` on the shelf grid.

## Implementation notes

Do not point hosted deploys at the local warehouse. Unrelated dirty files stay unstaged.
