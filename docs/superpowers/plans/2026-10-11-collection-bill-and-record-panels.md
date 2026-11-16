# Collection bill and record anatomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill one eBay/Discogs/Buyee bill onto every matching shelf copy (Gripsweat shares the eBay item id), split package postage so the pieces sum to the order, persist bills in dedicated tables, and show Billing vs Record anatomy as two panels.

**Architecture:** Parsers stay in `collection_import`. Matching, pro-rata split, and `collection_bill` / `collection_bill_line` live in a new `collection_billing` module. `save_billing_note` writes the audit blob and upserts those tables. My collection reads the latest line for the grid, then two sibling panels. Anatomy reads/writes existing `auction_collector` columns. Paid + in-process or delivered is enough for billing; do not wait for Buyee delivery.

**Tech Stack:** Python 3.11, pytest, Streamlit, PostgreSQL (`warehouse`), existing collection import/shelf code.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-11-collection-bill-and-record-panels-design.md`
- Item price, title, catalog, seller, paid-on do not change on bill save unless the collector confirms an item-price replacement (default: keep).
- No OCR. PNG/JPG refused.
- No catalog-only matching. eBay `{id}` matches marketplace `ebay` or `gripsweat`.
- Do not write `warehouse.auction.shipping_price` or `warehouse.auction_purchase_review`.
- Do not auto-fill obi/insert/poster from Discogs.
- Do not point hosted deploys at the local warehouse. Do not commit unless asked.
- Local schema only: additive `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`.

---

### Task 1: Pro-rata package split

**Files:**
- Create: `auction_etl/services/collection_billing.py`
- Test: `tests/test_collection_billing.py`

**Interfaces:**
- Consumes: `decimal.Decimal`
- Produces: `allocate_package_charges(item_amounts: list[Decimal], shipping: Decimal, tax: Decimal, fees: Decimal = Decimal("0")) -> list[tuple[Decimal, Decimal, Decimal]]` — one `(shipping, tax, fees)` per item. Sums equal the inputs. USD-style cents (2 dp). Remainder on the last row.

- [ ] **Step 1: Write the failing test**

```python
from decimal import Decimal
from auction_etl.services.collection_billing import allocate_package_charges

def test_ebay_three_item_combined_shipping_sums_to_the_order() -> None:
    shares = allocate_package_charges(
        [Decimal("120.50"), Decimal("120.50"), Decimal("91.00")],
        shipping=Decimal("54.00"),
        tax=Decimal("20.75"),
    )
    assert len(shares) == 3
    ship = sum((row[0] for row in shares), Decimal("0"))
    tax = sum((row[1] for row in shares), Decimal("0"))
    assert ship == Decimal("54.00")
    assert tax == Decimal("20.75")
    assert shares[0][0] == shares[1][0]
    assert shares[2][0] == Decimal("54.00") - shares[0][0] - shares[1][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_collection_billing.py::test_ebay_three_item_combined_shipping_sums_to_the_order -q`

Expected: FAIL (`collection_billing` not found or function missing)

- [ ] **Step 3: Write minimal implementation**

In `auction_etl/services/collection_billing.py`: weight each item by `item / sum(items)`. Round each shipping/tax/fee share to 2 dp except the last row, which is `total - sum(prior)` so the package adds back. Empty item list returns `[]`. Zero item total: equal split (last row takes remainder). Yen callers pass whole-yen Decimals; still 2 dp is fine if amounts are integers.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_collection_billing.py -q`

Expected: PASS

- [ ] **Step 5: Commit only if asked**

---

### Task 2: Match bill ids to shelf rows (eBay = Gripsweat)

**Files:**
- Modify: `auction_etl/services/collection_billing.py`
- Test: `tests/test_collection_billing.py`

**Interfaces:**
- Consumes: shelf rows as `list[dict]` with `marketplace`, `listing_id`
- Produces: `match_bill_to_shelf(*, printed_id: str, source: str, selected: dict | None, rows: list[dict]) -> dict | None`

Rules from the spec:

- `source == "ebay"`: row where `listing_id == printed_id` and `marketplace` in `{ebay, gripsweat}`
- `source == "buyee"`: `marketplace == buyee` and `listing_id == printed_id`
- `source == "discogs"`: `marketplace` in `{discogs}` or owned_copy source, `listing_id == printed_id`
- If `printed_id` is empty and `selected` is set, return `selected`
- Buyee one-auction with no listing_id hit: return `selected` if set
- Buyee multi-auction with no hit: return `None` (never dump the package on the selected row)
- No catalog fallback

- [ ] **Step 1: Write the failing tests**

```python
from auction_etl.services.collection_billing import match_bill_to_shelf

SHELF = [
    {"marketplace": "gripsweat", "listing_id": "236601326474", "catalog_number": "2427329"},
    {"marketplace": "ebay", "listing_id": "999", "catalog_number": "2427329"},
    {"marketplace": "buyee", "listing_id": "f1204890335", "catalog_number": "SOLL170"},
]

def test_ebay_item_number_matches_gripsweat_not_another_catalog() -> None:
    hit = match_bill_to_shelf(
        printed_id="236601326474",
        source="ebay",
        selected=None,
        rows=SHELF,
    )
    assert hit is not None
    assert hit["marketplace"] == "gripsweat"

def test_buyee_unmatched_package_line_does_not_use_selected_row() -> None:
    selected = SHELF[2]
    hit = match_bill_to_shelf(
        printed_id="missing-auction",
        source="buyee",
        selected=selected,
        rows=SHELF,
        package=True,
    )
    assert hit is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_collection_billing.py -q`

Expected: FAIL on missing `match_bill_to_shelf`

- [ ] **Step 3: Implement `match_bill_to_shelf`**

Normalize ids with `str(...).strip()`. Compare listing_id as text. `package: bool = False` for the Buyee dump-guard.

- [ ] **Step 4: Run tests**

Expected: PASS

- [ ] **Step 5: Commit only if asked**

---

### Task 3: Create `collection_bill` and `collection_bill_line` plus indexes

**Files:**
- Modify: `auction_etl/services/collection_billing.py`
- Modify: `scripts/upgrade_collector_review_schema.py` (append the same DDL)
- Test: `tests/test_collection_billing.py` (SQL contract on source) and a live helper `ensure_collection_bill_tables(engine)`

**Interfaces:**
- Produces: `COLLECTION_BILL_DDL: str`, `ensure_collection_bill_tables(engine) -> None`

DDL must include:

- `warehouse.collection_bill` columns from the spec (`fulfillment_status` varchar nullable)
- `warehouse.collection_bill_line` with FK `bill_id` ON DELETE CASCADE
- Unique index on `(account_id, source, external_order_id)` WHERE `external_order_id IS NOT NULL`
- Indexes listed in the spec

- [ ] **Step 1: Write the failing source contract**

```python
from pathlib import Path
from auction_etl.services.collection_billing import COLLECTION_BILL_DDL

def test_collection_bill_ddl_has_separate_line_table_and_lookup_indexes() -> None:
    sql = COLLECTION_BILL_DDL
    assert "warehouse.collection_bill" in sql
    assert "warehouse.collection_bill_line" in sql
    assert "fulfillment_status" in sql
    assert "account_id, listing_id" in sql
    assert "ON DELETE CASCADE" in sql
```

- [ ] **Step 2: Run it (expect fail until DDL exists)**

- [ ] **Step 3: Add `COLLECTION_BILL_DDL` and `ensure_collection_bill_tables` using `engine.begin()` / `text()`**

Call `ensure_collection_bill_tables` from `app/pages/17_My_Collection.py` `main()` next to `ensure_owned_copy_table`. Duplicate the DDL string into `scripts/upgrade_collector_review_schema.py` statements tuple.

- [ ] **Step 4: Run tests**

Also run `test_collection_page_is_an_intake` after the page import of `ensure_collection_bill_tables`.

- [ ] **Step 5: Commit only if asked**

Do not run hosted deploys. Local `upgrade_schema` / page load creates tables on 127.0.0.1:5544.

---

### Task 4: Persist a bill and prefer lines on the shelf

**Files:**
- Modify: `auction_etl/services/collection_billing.py`
- Modify: `auction_etl/services/collection_shelf.py` (`save_billing_note` calls persist)
- Test: `tests/test_collection_billing.py` with a transaction against local Postgres **only if** `AUCTION_ETL_LIVE_DB=1`; otherwise unit-test upsert SQL assembly / a fake connection. Prefer a focused function that returns the row dicts to insert so it can be tested without the warehouse:

`plan_collection_bill(*, account_id, source, external_order_id, currency, totals, raw_note, fulfillment_status, lines: list[BillLine]) -> tuple[dict, list[dict]]`

`BillLine` dataclass: marketplace, listing_id, printed_id, item_amount, shipping_amount, tax_amount, fee_amount, line_note.

- [ ] **Step 1: Test allocated lines sum to totals**

```python
def test_planned_bill_lines_sum_to_package_totals() -> None:
    from auction_etl.services.collection_billing import plan_collection_bill, BillLine
    from decimal import Decimal
    shares = [
        BillLine("ebay", "1", "1", Decimal("120.50"), Decimal("19.61"), Decimal("7.53"), Decimal("0"), "n"),
        BillLine("ebay", "2", "2", Decimal("120.50"), Decimal("19.61"), Decimal("7.53"), Decimal("0"), "n"),
        BillLine("ebay", "3", "3", Decimal("91.00"), Decimal("14.78"), Decimal("5.69"), Decimal("0"), "n"),
    ]
    bill, lines = plan_collection_bill(
        account_id="acct",
        source="ebay",
        external_order_id="08-14198-02534",
        currency="USD",
        item_total=Decimal("332.00"),
        shipping_total=Decimal("54.00"),
        tax_total=Decimal("20.75"),
        fee_total=Decimal("0"),
        grand_total=Decimal("406.75"),
        raw_note="...",
        fulfillment_status="delivered",
        lines=shares,
    )
    assert sum(line.shipping_amount for line in lines) == Decimal("54.00")
    assert bill["grand_total"] == Decimal("406.75")
```

Adjust `plan_collection_bill` to validate sums (raise `ValueError` if off by more than one cent).

- [ ] **Step 2–4:** Implement persist: `INSERT ... ON CONFLICT (account_id, source, external_order_id) DO UPDATE`, delete old lines for that `bill_id`, insert new lines, then existing `save_billing_note` UPDATE of `manual_purchase_notes` / `owned_copy.billing_note` with each `line_note`.

`save_billing_note` keeps its current return count. After a successful copy UPDATE, call persist when `user_id`/account is present. Typed single-copy saves create `source='typed'`, `external_order_id` null (no unique conflict; insert new bill).

- [ ] **Step 5: Commit only if asked**

---

### Task 5: Buyee package lines include allocated international and customs

**Files:**
- Modify: `auction_etl/services/collection_import.py` (`_buyee_shipping_pdf` / package note builder)
- Test: `tests/test_collection_import.py::test_buyee_shipping_pdf_keeps_each_records_fees_and_the_package_totals`

**Interfaces:**
- After per-auction plan/service/domestic, call `allocate_package_charges` on item prices for international and customs. Append `International shipping {n} JPY` and `Customs {n} JPY` **without** the `Package` prefix so `copy_costs` includes them. Keep a `Package international shipping` / `Package customs` audit line as well **or** store package totals only on `collection_bill.shipping_total` — spec: note keeps package totals for audit **and** per-copy allocated lines for columns.

Change the existing test:

- `copy_costs(quiet.billing_note)["shipping"]` is no longer None (domestic 880 + share of 13818)
- `copy_costs(...)["customs"]` is the allocated duty share
- Sum of per-copy international shares == 13818
- Sum of customs shares == 1395
- One-auction invoice test still has no `Package` prefix on international

- [ ] **Step 1: Extend the shipping-PDF test with sum assertions**
- [ ] **Step 2: Fail**
- [ ] **Step 3: Allocate in the package parser; keep one-auction path unchanged**
- [ ] **Step 4: Pass both Buyee invoice tests**
- [ ] **Step 5: Commit only if asked**

---

### Task 6: eBay details paste keeps item vs shipping vs tax; extract item numbers

**Files:**
- Modify: `auction_etl/services/collection_import.py` (`_ebay_detail_rows`, history parser)
- Test: `tests/test_collection_import.py`

**Interfaces:**
- Totals card (`1 item $160.00` / `Shipping $6.50` / `Tax* $10.00` / `Order total $176.50`): `paid_amount` is item 160, note has shipping/tax/order total. `external_id` may stay synthetic if no item number.
- Full details page with `Item number: 236601326474` (repeatable): one `ParsedPurchase` **per item number**, shared shipping/tax allocated by item prices on that page (`3 items $332.00` / `Shipping $54.00` / `Tax* $20.75`).

- [ ] **Step 1: Add tests for the $160 card and the three-item combined page (item numbers + $54 / $20.75)**
- [ ] **Step 2–4: Parse `Item number:` lines; if count >= 2 and a shared shipping line exists, allocate; if count == 1, attach all shipping/tax to that id**
- [ ] **Step 5: Commit only if asked**

PNG/JPG: `detect_purchase_source` / file uploader already limits types. Add `jpg`/`png` to a refuse message in Fill in the breakdown if they appear; do not add them to `type=`.

---

### Task 7: Bring-in backfill instead of `already` when the paste is a bill

**Files:**
- Modify: `auction_etl/services/collection_shelf.py` `_classify_one`
- Test: `tests/test_collection_import.py` or `tests/test_collection_shelf.py` if present; otherwise add `tests/test_collection_shelf.py`

When `purchase.billing_note` has charge lines and the catalog/key is already owned, status is `backfill` (or keep `already` but the page saves bills — spec says backfill not skip). Simplest: if `billing_note` strip and costs exist, return status `"backfill"` with marketplace/listing_id of the owned row when known.

Page: treat `backfill` like Fill in the breakdown save, not “already on the shelf” with no write.

- [ ] **Step 1: Test `_classify_one` with an eBay bill note and owned catalog → `backfill`**
- [ ] **Step 2–4: Implement; leave `already` when there is no billing note**
- [ ] **Step 5: Commit only if asked**

---

### Task 8: Two panels on My collection + shelf reads latest bill line

**Files:**
- Modify: `app/pages/17_My_Collection.py`
- Test: `tests/test_collection_import.py::test_collection_page_is_an_intake`

**Interfaces:**
- Selected row → two `st.container(border=True)`: heading **Billing**, heading **Record anatomy**
- Billing: existing money metrics + fulfillment caption (in process / delivered is fine)
- Anatomy: pressing identity + condition + edition fields already on the selected listing dict if present; gaps listed; Japan-only obi. Writes go through the same collector UPDATE Collector Review uses **only if** a small existing helper can be imported without pulling `collector_review.py`. If that import is heavy, anatomy panel is **read-only gaps + Open listing** in this task, write in Task 9.

Grid: `LEFT JOIN LATERAL` latest `collection_bill_line` for shipping/tax/fees display columns instead of parsing notes when a line exists.

Page contract strings to add: `"Record anatomy"`, `"Billing"`, `"collection_bill"`, keep `"st.dialog" not in source`, `"LinkColumn" not in source`.

- [ ] **Step 1: Extend `test_collection_page_is_an_intake`**
- [ ] **Step 2–4: Split `_show_selected_copy` into billing container + anatomy container; load bill lines in `load_collected`**
- [ ] **Step 5: Commit only if asked**

Fill in the breakdown: after parse, call `match_bill_to_shelf` for each purchase; preview all matched rows with split amounts; one Save writes all. Unmatched ids listed. Image files: error string paste-or-type.

---

### Task 9: Anatomy completeness helper (Japan obi vs Hong Kong)

**Files:**
- Modify: `auction_etl/services/collection_billing.py` or a tiny `collection_anatomy.py`
- Test: `tests/test_collection_billing.py`

```python
def anatomy_gaps(row: dict) -> list[str]:
    ...

def test_japan_unset_obi_is_a_gap_hong_kong_is_not() -> None:
    japan = {"manual_region": "Japan", "manual_media_type": "LP", "manual_obi": None, ...}
    hk = {"manual_region": "Hong Kong", "manual_media_type": "LP", "manual_obi": None, ...}
    assert "Obi" in anatomy_gaps(japan)
    assert "Obi" not in anatomy_gaps(hk)
```

Reuse `obi_for_region` from media classification / collector support. Do not import `app.collector_review`.

Billing gaps: paid set + (shipping/tax/fees or confirmed none). `fulfillment_status in {in_process, delivered, None}` does not create a gap.

- [ ] **Step 1–4: Helper + panel uses it**
- [ ] **Step 5: Commit only if asked**

---

### Task 10: Wire Fill in the breakdown to multi-copy save

**Files:**
- Modify: `app/pages/17_My_Collection.py` `_render_shelf_fill`
- Test: page contract + a pure function `preview_shelf_bills(purchases, shelf_rows, selected) -> list[dict]` in `collection_billing.py`

One primary button **Save this bill on these copies**. Loop `save_billing_note` + persist lines. Typed amounts: `source=typed`, single selected row.

Refuse `image/*` in the uploader help text. Keep Buyee PDF types.

- [ ] **Step 1: Test `preview_shelf_bills` with three eBay purchases and one gripsweat shelf hit + two misses**
- [ ] **Step 2–4: Implement preview + save loop**
- [ ] **Step 5: Commit only if asked**

---

## Spec coverage

| Spec section | Task |
| --- | --- |
| Two panels | 8 |
| Matching eBay/Gripsweat/Buyee/Discogs/selected | 2, 10 |
| Pro-rata split | 1, 5, 6 |
| Input formats / no OCR | 6, 10 |
| Buyee package vs one-auction | 5 |
| `collection_bill` / `_line` + indexes | 3, 4 |
| Table coverage / do not write auction postage | 3, 4 (constraints) |
| Billing complete in-process/delivered | 8, 9 |
| Anatomy Japan obi | 9 |
| Bring-in backfill | 7 |
| Discogs complete-run | out of scope (spec follow-on) |
