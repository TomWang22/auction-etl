# Buyee PDF billing breakdown

Date: 2026-10-11

## Problem

My Collection already stores an item price on a purchased copy. Shipping, tax, and fees stay empty until a billing note is saved. For eBay and Discogs that note comes from order details. For Buyee the complete bill is the shipping invoice PDF.

The 2026-10-11 Teresa Teng copy (`28MX 1004`, auction `m1233352030`) is on the shelf at **US$102.40** with blank Shipping / Tax / Fees. That dollar amount is the first Buyee card charge (15,375 YEN), not the landed cost. The invoice PDF for that same auction prints the full sheet and a grand total of **23,057 YEN**.

Today that PDF cannot fill the sheet:

- Bring in purchases accepts `html`, `htm`, `csv`, `txt` only. It does not accept `.pdf`.
- The Buyee invoice reader requires two or more `JDirectItems Auction(…)` ids. This file has one, so it is skipped.
- `Customs Clearance Fee` is not a recognized line, so 1,200 YEN would be dropped even from a good paste.

## Goal

A collector can drop the Buyee invoice PDF, or paste its text, onto a copy already on the shelf. The **item price stays as it is**. Shipping / Tax / Fees / Landed use the recommended split. The billing note is **only the mechanical charge sheet**, not a dump of the PDF.

eBay, Discogs, Record City, and Gripsweat intake stay unchanged.

## Mechanical billing vs album identity

The invoice is not a catalog source. Album title, artist, and catalog are already on the shelf (this copy is `テレサ・テン · 演歌のメッセージ · 28MX 1004`). Those fields are analyzed from the listing / Discogs, not from Buyee’s **Item Name**.

PDF Item Name is listing noise (`国内盤(帯付)`, shopping-site ids, truncated characters). Do not:

- parse catalog tokens from the invoice
- classify media from the invoice
- overwrite shelf artist, album, or catalog
- keep prose footer lines (“Breakdown of Expenses are shown in Japanese Yen”, card/PayPal/Alipay notes)
- keep section subtotals that repeat a labeled line (Other Service Fees total, Shipping Expenses total)

The reader is a label → amount map. Identity stays the shelf row the collector picked. Auction id is stored on the note only so the bill can be audited against `m1233352030`.

## Proven invoice (one auction)

Source: Buyee shipping invoice PDF for `JDirectItems Auction(m1233352030)`, item テレサ・テン / 演歌のメッセージ 国内盤(帯付).

| Line | Amount (YEN) |
|---|---:|
| Item price | 16,335 |
| Coupon discount | -1,960 |
| Item total | 14,375 |
| Plan fee | 500 |
| Buyee service fee | 500 |
| Domestic shipping (seller → Buyee) | 770 |
| Customs clearance fee | 1,200 |
| Other-service-fees total | 2,970 |
| International shipping | 3,860 |
| Customs duty | 1,852 |
| **Grand total** | **23,057** |

Payment dates on the same PDF: 2026/09/30 = 15,375 and 2026/10/02 = 6,482. Those two payments sum to 21,857. The 1,200 gap is the customs clearance fee, which is on the grand total and not in the payment-date table. Keep both payment rows in the note. Do not change `paid_on` on the shelf.

Item 16,335 − coupon 1,960 + 2,970 + 3,860 + 1,852 = 23,057.

## Intake

Bring in purchases accepts `.pdf` in addition to the existing html/txt/csv drop and paste.

Fill in the breakdown keeps paste. A PDF dropped there is not required for this spec; the same parser must accept pasted invoice text so a collector who copied the PDF can still save it on one copy.

A screenshot or other image is not a bill. No OCR.

## Text pipeline

Dropping a PDF extracts text, then both PDF and paste use one Buyee reader.

Use a small PDF text extractor (for example `pypdf`) on generated Buyee invoices. Do not parse table geometry unless text extraction loses section labels. If a `.pdf` yields no usable auction id and no charge labels, show the existing empty-bill message: that page did not include a shipping, tax, or fee line.

## One-auction invoice

When the file has exactly one `JDirectItems Auction(id)`, every charge line belongs to that copy. Do not label international shipping or customs as package totals.

The billing note is only these labeled lines (plus auction/order id):

- Item price
- Coupon (when present)
- Plan fee
- Service fee
- Domestic shipping
- Customs clearance fee
- International shipping
- Customs duty
- Grand total
- Payment-date rows when present (`2026/09/30 15375 JPY`, `2026/10/02 6482 JPY`)

No Item Name, no table headers, no currency footnotes. `ParsedPurchase.title` may stay empty when saving onto a picked shelf row. If a review picker needs a label, use Item Name only as a UI caption — never as identity.

## Two-or-more auction invoice

Keep the current split:

- Plan fee, service fee, and domestic shipping are per auction.
- International shipping and customs duty stay labeled as package totals in the note so they are not assigned to every row.
- Customs clearance fee follows the same rule as customs duty: package total when printed once for the shipment.

## Shelf columns

Item price, seller, and paid-on are not updated when a bill is saved onto an existing copy.

From the per-copy lines in the note:

| Column | Lines |
|---|---|
| Shipping | Domestic shipping + international shipping |
| Tax | Customs duty |
| Fees | Plan fee + service fee + customs clearance fee |
| Landed | Item dollars + those yen lines converted |

Package-labeled lines stay in the note and stay out of those three columns.

Yen lines stay visible in yen. Landed converts them with the printed USD rate on the bill when present, otherwise the existing ECB rate path.

Coupon is not a column. It stays in the note. The shelf item amount is whatever was already saved (for this copy, US$102.40).

## Matching an existing copy

Fill in the breakdown already lets the collector pick the shelf row, then save the parsed bill onto that listing. Keep that. Auction id `m1233352030` does not have to equal the Buyee listing id / seller id already on the shelf (`F8AAhZCgFb9EQhLhr` on this copy).

Bring in purchases may still offer “already on the shelf” / backfill when the parsed bill has a billing note. Identity matching stays as it is; this spec does not add auction-id-to-listing-id linking.

## Out of scope

- Changing the item price to 16,335 YEN or 23,057 YEN
- Analyzing or correcting album title from the PDF
- OCR of screenshots
- Gripsweat bill reading
- Extra table columns for every Buyee fee
- Pointing Vercel or Railway at the local database
- Deleting Neon

## Tests

Add a fixture that is this one-auction invoice (plain text matching the extracted PDF). Assert:

- Source is Buyee
- External id is `m1233352030`
- Billing note is the labeled charge lines only; it does not contain Item Name, `国内盤`, or the yen-footnote prose
- Note contains item, coupon, plan, service, domestic, clearance, international, customs duty, and grand total 23,057
- `copy_costs` shipping = 770 + 3,860
- `copy_costs` tax / customs duty = 1,852
- `copy_costs` fees = 500 + 500 + 1,200
- International shipping is not prefixed with `Package`
- Saving the bill does not change shelf title or catalog
- A two-auction PDF fixture still labels package international / customs as today

Bring in purchases file types include `pdf`. The existing “Fill in the breakdown” paste path still parses this text without a file.
