# Buyee PDF billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse a Buyee shipping invoice (PDF drop or pasted text) into a noise-free charge note, save it onto an existing shelf copy without touching album title, and show the recommended Shipping / Tax / Fees split.

**Architecture:** One text pipeline. PDF bytes become plain text, then the existing Buyee reader maps English labels to amounts. `copy_costs` grows a clearance line. The shelf maps customs duty to Tax and plan + service + clearance to Fees. The Fill in the breakdown UI previews those lines and never uses Item Name as identity.

**Tech Stack:** Python 3.11, pytest, Streamlit, pypdf, existing `auction_etl.services.collection_import` / `app/pages/17_My_Collection.py`.

## Global Constraints

- Item price, seller, paid-on, artist, album, and catalog on the shelf do not change when a bill is saved.
- Billing note is labeled charge lines only (no Item Name, no 国内盤, no yen/PayPal footnotes).
- Recommended split: Shipping = domestic + international; Tax = customs duty; Fees = plan + service + customs clearance.
- One-auction invoices assign every line to that copy (no `Package` prefix). Two-or-more auction PDFs keep today’s package split.
- No OCR. No Gripsweat parser. Do not commit unless the operator asks.

---

### Task 1: Noise-free one-auction invoice lines and cost keys

**Files:**
- Modify: `auction_etl/services/collection_import.py`
- Test: `tests/test_collection_import.py`

**Interfaces:**
- Consumes: `parse_purchase_export(raw: str) -> ParseResult`, `copy_costs(note: str) -> dict[str, Decimal | None]`
- Produces: `copy_costs` keys include `clearance`. One-auction Buyee invoice notes contain only labeled amounts. `Customs clearance` is a per-copy cost. `Customs` remains customs duty.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_collection_import.py`:

```python
ONE_AUCTION_INVOICE = """
Item Price
Shopping Site(ID) JDirectItems Auction(m1233352030)
Item Name テレサ・テン（鄧麗君） / 演歌のメッセージ 国内盤(帯付)
Quantity 1
Item Price 16,335
Coupon discount -1,960
Total Amount 14,375
Other Service Fees
Plan Fee 500
Buyee Service Fee 500
Domestic Shipping Fee(From seller to Buyee) 770
Customs Clearance Fee 1,200
Total Amount 2,970
Shipping Expenses
International Shipping Fee 3,860
Total Amount 3,860
Customs Duties and Value-Added Tax
Customs Duty 1,852
Total Amount 1,852
Grand Total Payment Amount 23,057YEN
* Breakdown of Payment amount
2026/09/30 15,375
2026/10/02 6,482
Breakdown of Expenses are shown in Japanese Yen.
Actual billing amount is the currency of your payments, please check credit card/PayPal/Alipay billing for details.
"""


def test_buyee_one_auction_invoice_keeps_labeled_charges_only() -> None:
    parsed = parse_purchase_export(ONE_AUCTION_INVOICE)
    assert parsed.source == "buyee"
    row = parsed.purchases[0]
    assert row.external_id == "m1233352030"
    note = row.billing_note
    assert "国内盤" not in note
    assert "Item Name" not in note
    assert "Japanese Yen" not in note
    assert "PayPal" not in note
    assert "Item price 16,335 JPY" in note
    assert "Coupon -1,960 JPY" in note
    assert "Plan fee 500 JPY" in note
    assert "Service fee 500 JPY" in note
    assert "Domestic shipping 770 JPY" in note
    assert "Customs clearance 1,200 JPY" in note
    assert "International shipping 3,860 JPY" in note
    assert "Customs 1,852 JPY" in note
    assert "Grand total 23,057 JPY" in note
    assert "Payment 2026/09/30 15,375 JPY" in note
    assert "Payment 2026/10/02 6,482 JPY" in note
    assert "Package" not in note
    costs = copy_costs(note)
    assert costs["shipping"] == Decimal("3860")
    assert costs["domestic_shipping"] == Decimal("770")
    assert costs["customs"] == Decimal("1852")
    assert costs["plan_fee"] == Decimal("500")
    assert costs["service_fee"] == Decimal("500")
    assert costs["clearance"] == Decimal("1200")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_collection_import.py::test_buyee_one_auction_invoice_keeps_labeled_charges_only`

Expected: FAIL (`clearance` missing and/or note contains Item Name / missing payment lines).

- [ ] **Step 3: Write minimal implementation**

In `collection_import.py`:

1. Add `"clearance"` to `_COPY_COST`. Put `Customs clearance` before `Customs` in `_COST_LINE` and `_COST_KEYS`.
2. In `_buyee_bill_note`, add `("Customs clearance", r"Customs Clearance Fee\s*[:：]?\s*(-?[0-9][0-9,]*)")` before Customs Duty. Append payment rows from `r"(20\d{2}/\d{2}/\d{2})\s+([0-9][0-9,]*)"` as `Payment {date} {amount} JPY`.
3. After building the charge lines, if an auction id is in the chunk, prefix `Auction {id}` when it is not already in the note. Do not copy Item Name into the note.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_collection_import.py`

Expected: PASS, including the existing two-auction PDF test.

Do not commit.

---

### Task 2: Shelf columns use the recommended split

**Files:**
- Modify: `app/pages/17_My_Collection.py` (`_shelf_costs`, `_breakdown_summary`)
- Test: `tests/test_collection_import.py` (page contract plus a small mapping assertion in the same invoice test)

**Interfaces:**
- Consumes: `copy_costs` keys `shipping`, `domestic_shipping`, `tax`, `customs`, `plan_fee`, `service_fee`, `clearance`
- Produces: Shipping = domestic + international; Tax = eBay/Discogs tax + customs duty; Fees = plan + service + clearance (not customs duty)

- [ ] **Step 1: Extend the invoice test**

```python
    shipping = (costs["shipping"] or 0) + (costs["domestic_shipping"] or 0)
    tax = costs["customs"]
    fees = (costs["plan_fee"] or 0) + (costs["service_fee"] or 0) + (costs["clearance"] or 0)
    assert shipping == Decimal("4630")
    assert tax == Decimal("1852")
    assert fees == Decimal("2200")
```

- [ ] **Step 2: Point `_shelf_costs` and `_breakdown_summary` at that split**

```python
"tax": _sum_amounts(costs["tax"], costs["customs"]),
"fees": _sum_amounts(costs["plan_fee"], costs["service_fee"], costs["clearance"]),
```

`_breakdown_summary` must use the same tax/fees pairing so the bill picker caption matches the table.

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest -q tests/test_collection_import.py`

Expected: PASS.

Do not commit.

---

### Task 3: PDF bytes to the same reader

**Files:**
- Modify: `pyproject.toml`, `app/requirements.txt` (add `pypdf`)
- Modify: `auction_etl/services/collection_import.py` (top-level `from pypdf import PdfReader`)
- Modify: `app/pages/17_My_Collection.py` (`_read_dropped_page` and Fill in the breakdown)
- Test: `tests/test_collection_import.py`

**Interfaces:**
- Consumes: PDF bytes starting with `%PDF`
- Produces: `extract_pdf_text(data: bytes) -> str` then `parse_purchase_export`

- [ ] **Step 1: Failing test with a tiny generated PDF**

```python
from auction_etl.services.collection_import import extract_pdf_text


def test_extract_pdf_text_keeps_invoice_labels() -> None:
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, TextStringObject

    # Prefer a writer that embeds the invoice fixture as page text.
    # If constructing content streams is too heavy, write a one-page PDF
    # whose extract_text() includes "JDirectItems Auction(m1233352030)"
    # and "Customs Clearance Fee 1,200".
```

Simpler path that still fails closed: unit-test `extract_pdf_text` on bytes built with `pypdf.PdfWriter` adding a page via a known helper, **or** skip writer gymnastics and test that `parse_purchase_export(extract_pdf_text(pdf_bytes))` works when `extract_pdf_text` is fed bytes produced by:

```python
def _pdf_with_text(text: str) -> bytes:
    from reportlab...  # do not add reportlab
```

Use pypdf only. A sufficient test: `extract_pdf_text` raises a clear error on non-PDF, and `parse_purchase_export` still accepts the plain-text fixture. Add:

```python
def test_extract_pdf_text_rejects_non_pdf() -> None:
    import pytest
    with pytest.raises(ValueError, match="PDF"):
        extract_pdf_text(b"not a pdf")
```

And wire the uploader to call `extract_pdf_text` when `data.startswith(b"%PDF")`.

- [ ] **Step 2: Implement**

```python
def extract_pdf_text(data: bytes) -> str:
    if not data.startswith(b"%PDF"):
        raise ValueError("Not a PDF bill.")
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
```

`_read_dropped_page` reads `uploaded.getvalue()` as bytes. If PDF, extract; else decode UTF-8.

Fill in the breakdown: same bytes/paste merge so a collector can drop the invoice on the copy they already picked.

- [ ] **Step 3: `uv add pypdf` and run tests**

Expected: PASS.

Do not commit.

---

### Task 4: UX — record title stays, bill is charge lines

**Files:**
- Modify: `app/pages/17_My_Collection.py`
- Test: `tests/test_collection_import.py::test_collection_page_is_an_intake`

**Interfaces:**
- Consumes: parsed `billing_note`, shelf `_record_label`
- Produces: picker labeled by auction id + cost summary; preview of the note; captions that the record title does not change; file types include `pdf`

- [ ] **Step 1: Fail the page contract**

Add required strings:

```python
"Drop the Buyee invoice PDF",
"Charge lines only",
"The record title stays as it is",
"pdf",
```

Bill selectbox label uses `purchase.external_id` and `_breakdown_summary`, not `purchase.title`.

Show `st.text(purchase.billing_note)` after a successful parse.

Placeholder mentions the Buyee invoice.

- [ ] **Step 2: Implement those copy/control changes**

- [ ] **Step 3: Run**

`.venv/bin/python -m pytest -q tests/test_collection_import.py`

Expected: PASS.

- [ ] **Step 4: Look at the Collected tab in the running Streamlit app**

Confirm: copy dropdown still shows テレサ・テン · 演歌のメッセージ · 28MX 1004; after paste/drop the bill preview is the labeled lines; Shipping/Tax/Fees fill without renaming the record.

Do not commit unless asked.
