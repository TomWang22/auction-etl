# eBay sold search without authentication — investigation

Date: 2026-11-19  
Status: findings only (no product cutover)

## Question

Can Auction ETL pull **completed/sold** eBay comps without an authenticated eBay login, since sold results are public search?

## Short answer

**Data is public; automated access is not anonymous-friendly.**

- The sold URL (`LH_Complete=1&LH_Sold=1`) does **not** require an eBay member session for a normal human browser.
- From this machine, **unauthenticated automation cannot reliably load those results**. eBay/Akamai returns **403 Error Page**, captcha (`/splashui/captcha`), or a bounce into **signin** — that sign-in redirect is a **bot/security interstitial**, not “sold history is private.”
- Today’s `storage_state` path also got **403** in the same probes (stale cookies and/or IP reputation), so “have cookies” ≠ guaranteed access.

## Evidence (live probes)

Artifacts:

- `ebay-anonymous-sold-probe.json` — plain HTTPS
- `ebay-anonymous-browser-probe.json` — system Chrome, no cookies
- `ebay-anonymous-vs-storage-probe.json` — empty profile vs existing storage-state

| Mode | Auth cookies | Result |
|---|---|---|
| `urllib` HTTPS (any UA) | none | **403** AkamaiGHost Error Page |
| Headless system Chrome | none | **403** Error Page |
| Headed system Chrome | none | **200** but lands on **captcha → signin** (no `/itm/` cards) |
| Headed + empty persistent profile | none | ends on **signin.ebay.com** Error Page |
| Headed + existing `ebay-storage-state.json` | yes | **403** Error Page (session not enough right now) |

No probe returned a usable sold-results DOM without a cleared/trusted browser session.

## What this means for the product

1. **Do not treat eBay like Yahoo JP.** Yahoo closedsearch/フリマ sold work over public HTTPS. eBay sold needs a **real Chrome path** (headed owner / warm profile) because of bot defense.
2. **Login is not the comps model** — we are not scraping “My eBay.” Storage-state exists to survive Akamai, not because sold listings are account-private.
3. **Refresh already models this:** `unavailable` / `ACCESS_BLOCKED` / `authentication_required` are soft marketplace outcomes. Yahoo + Gripsweat can finish while eBay is blocked.
4. **Next recovery step (ops, not code):** open the headed eBay owner, pass captcha/sign-in if prompted, refresh `ebay-storage-state.json`, re-run a 2-page acquire. That validates the existing path; it does **not** prove a permanent no-auth HTTPS scraper.

## Non-goals from this investigation

- Building a captcha bypass
- Claiming raw HTTPS eBay sold ingest is viable
- Changing Yahoo JP integration (unaffected)

## Implication for “all 4 as a whole”

Four-source refresh is correctly designed as **independent per marketplace**. eBay can be `unavailable` while Yahoo Auctions, Yahoo フリマ, and Gripsweat stay `done`. Fixing eBay is a **session/WAF recovery** problem, not a missing Yahoo-style anonymous HTTPS adapter.
