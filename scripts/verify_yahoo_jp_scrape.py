#!/usr/bin/env python3
"""Live verify Yahoo Auctions + フリマ scrape/pagination — no DB, no UI.

Gate before wiring refresh / Review marketplace sales.

Example:
  .venv/bin/python scripts/verify_yahoo_jp_scrape.py \\
    --query 'teresa teng' --auction-pages 3 --flea-pages 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auction_etl.parsers.yahoo_auction import (
    parse_closedsearch_html,
    parse_item_detail_html,
)
from auction_etl.parsers.yahoo_fleamarket import (
    parse_item_detail_html as parse_flea_item_detail_html,
    parse_sold_search_html,
)
from auction_etl.services.artist_tracking import (
    build_yahoo_auction_search_url,
    build_yahoo_fleamarket_search_url,
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass
class VerifyReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(CheckResult(name=name, ok=ok, detail=detail))

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def print(self) -> None:
        for check in self.checks:
            mark = "PASS" if check.ok else "FAIL"
            print(f"[{mark}] {check.name}: {check.detail}")
        print("RESULT:", "PASS" if self.ok else "FAIL")


def _fetch(url: str, *, retries: int = 4) -> tuple[str, int]:
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", errors="replace")
                return body, int(response.status)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 503} or attempt + 1 >= retries:
                raise
            # PayPay flea rate-limits aggressively on detail bursts.
            time.sleep(min(12.0, 3.0 * (attempt + 1)))
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt + 1 >= retries:
                raise
            time.sleep(min(8.0, 2.0 * (attempt + 1)))
    assert last_error is not None
    raise last_error


def _challenge_like(html: str) -> bool:
    lowered = html.casefold()
    markers = (
        "aws_waf",
        "captcha",
        "access denied",
        "request blocked",
        "please verify",
    )
    if any(marker in lowered for marker in markers):
        return True
    if "__NEXT_DATA__" not in html:
        return True
    return False


def _auction_money_ok(row: dict[str, Any]) -> str | None:
    gross = row.get("gross_price_jpy")
    final = row.get("final_price_jpy")
    tax = row.get("tax_amount_jpy")
    includes = row.get("price_includes_tax")
    if not isinstance(gross, int) or gross <= 0:
        return "missing/invalid gross"
    if not isinstance(final, int) or final <= 0:
        return "missing/invalid final"
    if includes is True:
        if tax is None or tax < 0:
            return "taxed row missing tax_amount"
        if gross != final + tax:
            return f"gross!=final+tax ({gross}!={final}+{tax})"
        if final * 11 < gross * 9:
            # final should be ~ gross/1.1
            return f"final not ~gross/1.1 ({final} vs {gross})"
    elif includes is False:
        if tax not in (0, None):
            return f"untaxed tax_amount={tax}"
        if final != gross:
            return f"untaxed final!=gross ({final}!={gross})"
    else:
        return "price_includes_tax unset"
    if row.get("bid_count") is not None and int(row["bid_count"]) < 0:
        return "negative bid_count"
    return None


def verify_auctions(
    report: VerifyReport,
    *,
    query: str,
    pages: int,
    page_size: int,
    pause_s: float,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    all_rows: list[dict[str, Any]] = []
    totals: list[int | None] = []

    for page_index in range(pages):
        start = 1 + page_index * page_size
        url = build_yahoo_auction_search_url(
            query,
            start=start,
            page_size=page_size,
        )
        print(f"FETCH auction p{page_index + 1}: {url}")
        try:
            html, status = _fetch(url)
        except urllib.error.URLError as exc:
            report.add(
                f"auction page {page_index + 1} fetch",
                False,
                str(exc),
            )
            return all_rows

        report.add(
            f"auction page {page_index + 1} http",
            status == 200,
            f"status={status}",
        )
        if _challenge_like(html):
            report.add(
                f"auction page {page_index + 1} body",
                False,
                "challenge/empty (no usable __NEXT_DATA__)",
            )
            return all_rows

        parsed = parse_closedsearch_html(html)
        report.add(
            f"auction page {page_index + 1} parse",
            bool(parsed["parse_ok"]),
            f"rows={len(parsed['items'])} total≈{parsed['total_results_available']}",
        )
        if not parsed["parse_ok"]:
            return all_rows

        totals.append(parsed["total_results_available"])
        ids = [row["listing_id"] for row in parsed["items"]]
        overlap = sorted(seen.intersection(ids))
        report.add(
            f"auction page {page_index + 1} pagination",
            len(overlap) == 0 and len(ids) > 0,
            f"unique={len(ids)} overlap={len(overlap)}"
            + (f" sample={overlap[:3]}" if overlap else ""),
        )
        if overlap or not ids:
            return all_rows

        money_failures = []
        for row in parsed["items"]:
            problem = _auction_money_ok(row)
            if problem:
                money_failures.append(f"{row['listing_id']}:{problem}")
        report.add(
            f"auction page {page_index + 1} money",
            not money_failures,
            "ok"
            if not money_failures
            else f"{len(money_failures)} bad e.g. {money_failures[:3]}",
        )

        seen.update(ids)
        all_rows.extend(parsed["items"])
        if page_index + 1 < pages:
            time.sleep(pause_s)

    if totals and totals[0] is not None:
        report.add(
            "auction totalResultsAvailable",
            totals[0] > page_size,
            f"total={totals[0]} (need multi-page room)",
        )
    report.add(
        "auction pages collected",
        len(seen) >= pages,
        f"unique_ids={len(seen)} across {pages} page(s)",
    )
    return all_rows


def _content_ok_auction(row: dict[str, Any]) -> str | None:
    listing_id = str(row.get("listing_id") or "")
    title = str(row.get("title") or "").strip()
    url = str(row.get("auction_url") or "")
    if not listing_id or not listing_id.replace("_", "").isalnum():
        return "bad listing_id"
    if len(title) < 3:
        return "empty/short title"
    if listing_id not in url or "/jp/auction/" not in url:
        return f"url missing id ({url})"
    if not row.get("closing_at"):
        return "missing closing_at"
    if row.get("currency") != "JPY":
        return "currency!=JPY"
    money = _auction_money_ok(row)
    if money:
        return money
    return None


def _content_ok_flea(row: dict[str, Any]) -> str | None:
    listing_id = str(row.get("listing_id") or "")
    title = str(row.get("title") or "").strip()
    url = str(row.get("auction_url") or "")
    if not listing_id:
        return "bad listing_id"
    if len(title) < 3:
        return "empty/short title"
    if listing_id not in url or "/item/" not in url:
        return f"url missing id ({url})"
    if not row.get("closing_at"):
        return "missing closing_at"
    if row.get("item_status") != "SOLD":
        return f"status={row.get('item_status')}"
    if row.get("gross_price_jpy") != row.get("final_price_jpy"):
        return "gross!=final"
    if not isinstance(row.get("gross_price_jpy"), int) or row["gross_price_jpy"] <= 0:
        return "bad price"
    if row.get("tax_amount_jpy") is not None or row.get("price_includes_tax") is not None:
        return "invented tax"
    return None


def verify_listing_contents(
    report: VerifyReport,
    *,
    label: str,
    rows: list[dict[str, Any]],
    checker,
) -> None:
    failures: list[str] = []
    for row in rows:
        problem = checker(row)
        if problem:
            failures.append(f"{row.get('listing_id')}:{problem}")
    report.add(
        f"{label} per-listing content",
        not failures,
        f"checked={len(rows)}"
        if not failures
        else f"{len(failures)}/{len(rows)} bad e.g. {failures[:5]}",
    )


def verify_auction_details(
    report: VerifyReport,
    *,
    rows: list[dict[str, Any]],
    sample: int,
    pause_s: float,
) -> list[dict[str, Any]]:
    """Fetch item pages for scraped auction cards. sample<=0 means all rows."""

    proofs: list[dict[str, Any]] = []
    if not rows:
        report.add("auction detail per-listing", False, "no search rows")
        return proofs

    picks = rows if sample <= 0 else rows[:sample]
    failures: list[str] = []
    for index, row in enumerate(picks, start=1):
        url = row["auction_url"]
        print(
            f"DETAIL auction {index}/{len(picks)} {row['listing_id']}: {url}",
            flush=True,
        )
        proof: dict[str, Any] = {
            "marketplace": "yahoo_auction",
            "listing_id": row["listing_id"],
            "search": {
                "title": row.get("title"),
                "gross_price_jpy": row.get("gross_price_jpy"),
                "final_price_jpy": row.get("final_price_jpy"),
                "tax_amount_jpy": row.get("tax_amount_jpy"),
                "price_includes_tax": row.get("price_includes_tax"),
                "start_price_jpy": row.get("start_price_jpy"),
                "bid_count": row.get("bid_count"),
                "closing_at": row.get("closing_at"),
                "auction_url": url,
            },
            "ok": False,
            "error": None,
            "detail": None,
        }
        try:
            html, status = _fetch(url)
        except urllib.error.URLError as exc:
            proof["error"] = f"fetch {exc}"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        if status != 200 or _challenge_like(html):
            proof["error"] = f"detail http/challenge status={status}"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        detail = parse_item_detail_html(html)
        if detail is None:
            proof["error"] = "detail parse failed"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        proof["detail"] = {
            "listing_id": detail.get("listing_id"),
            "gross_price_jpy": detail.get("gross_price_jpy"),
            "final_price_jpy": detail.get("final_price_jpy"),
            "tax_amount_jpy": detail.get("tax_amount_jpy"),
            "price_includes_tax": detail.get("price_includes_tax"),
            "start_price_jpy": detail.get("start_price_jpy"),
            "bid_count": detail.get("bid_count"),
        }
        problems: list[str] = []
        if detail["listing_id"] != row["listing_id"]:
            problems.append(f"id mismatch detail={detail['listing_id']}")
        if detail.get("gross_price_jpy") != row.get("gross_price_jpy"):
            problems.append(
                f"gross search={row.get('gross_price_jpy')} "
                f"detail={detail.get('gross_price_jpy')}"
            )
        # Tax-inclusive cards: search uses price/1.1; detail may round ±1 yen.
        search_final = row.get("final_price_jpy")
        detail_final = detail.get("final_price_jpy")
        if isinstance(search_final, int) and isinstance(detail_final, int):
            if abs(search_final - detail_final) > 1:
                problems.append(
                    f"final search={search_final} detail={detail_final}"
                )
        elif search_final != detail_final:
            problems.append(
                f"final search={search_final} detail={detail_final}"
            )
        if detail.get("price_includes_tax") != row.get("price_includes_tax"):
            problems.append(
                f"includes_tax search={row.get('price_includes_tax')} "
                f"detail={detail.get('price_includes_tax')}"
            )
        if (
            detail.get("start_price_jpy") is not None
            and row.get("start_price_jpy") is not None
            and detail.get("start_price_jpy") != row.get("start_price_jpy")
        ):
            problems.append(
                f"start search={row.get('start_price_jpy')} "
                f"detail={detail.get('start_price_jpy')}"
            )
        if problems:
            proof["error"] = "; ".join(problems)
            failures.append(f"{row['listing_id']}:{proof['error']}")
        else:
            proof["ok"] = True
        proofs.append(proof)
        time.sleep(pause_s)

    checked_ok = sum(1 for proof in proofs if proof["ok"])
    report.add(
        "auction detail per-listing",
        not failures and checked_ok == len(picks),
        f"ok={checked_ok}/{len(picks)}"
        if not failures
        else f"ok={checked_ok}/{len(picks)} failures={failures[:8]}",
    )
    return proofs


def verify_flea_details(
    report: VerifyReport,
    *,
    rows: list[dict[str, Any]],
    sample: int,
    pause_s: float,
) -> list[dict[str, Any]]:
    """Fetch item pages for scraped flea cards. sample<=0 means all rows."""

    proofs: list[dict[str, Any]] = []
    if not rows:
        report.add("flea detail per-listing", False, "no search rows")
        return proofs

    picks = rows if sample <= 0 else rows[:sample]
    failures: list[str] = []
    for index, row in enumerate(picks, start=1):
        url = row["auction_url"]
        print(
            f"DETAIL flea {index}/{len(picks)} {row['listing_id']}: {url}",
            flush=True,
        )
        proof: dict[str, Any] = {
            "marketplace": "yahoo_fleamarket",
            "listing_id": row["listing_id"],
            "search": {
                "title": row.get("title"),
                "gross_price_jpy": row.get("gross_price_jpy"),
                "final_price_jpy": row.get("final_price_jpy"),
                "item_status": row.get("item_status"),
                "closing_at": row.get("closing_at"),
                "auction_url": url,
            },
            "ok": False,
            "error": None,
            "detail": None,
        }
        try:
            html, status = _fetch(url)
        except urllib.error.URLError as exc:
            proof["error"] = f"fetch {exc}"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        if status != 200 or _challenge_like(html):
            proof["error"] = f"detail http/challenge status={status}"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        detail = parse_flea_item_detail_html(html)
        if detail is None:
            proof["error"] = "detail parse failed"
            failures.append(f"{row['listing_id']}:{proof['error']}")
            proofs.append(proof)
            continue
        proof["detail"] = {
            "listing_id": detail.get("listing_id"),
            "gross_price_jpy": detail.get("gross_price_jpy"),
            "final_price_jpy": detail.get("final_price_jpy"),
            "item_status": detail.get("item_status"),
            "tax_amount_jpy": detail.get("tax_amount_jpy"),
            "price_includes_tax": detail.get("price_includes_tax"),
        }
        problems: list[str] = []
        if detail["listing_id"] != row["listing_id"]:
            problems.append(f"id mismatch detail={detail['listing_id']}")
        if detail.get("gross_price_jpy") != row.get("gross_price_jpy"):
            problems.append(
                f"price search={row.get('gross_price_jpy')} "
                f"detail={detail.get('gross_price_jpy')}"
            )
        if detail.get("item_status") not in (None, "SOLD"):
            problems.append(f"status={detail.get('item_status')}")
        if detail.get("tax_amount_jpy") is not None or detail.get(
            "price_includes_tax"
        ) is not None:
            problems.append("unexpected tax fields")
        if problems:
            proof["error"] = "; ".join(problems)
            failures.append(f"{row['listing_id']}:{proof['error']}")
        else:
            proof["ok"] = True
        proofs.append(proof)
        time.sleep(pause_s)

    checked_ok = sum(1 for proof in proofs if proof["ok"])
    report.add(
        "flea detail per-listing",
        not failures and checked_ok == len(picks),
        f"ok={checked_ok}/{len(picks)}"
        if not failures
        else f"ok={checked_ok}/{len(picks)} failures={failures[:8]}",
    )
    return proofs


def verify_flea(
    report: VerifyReport,
    *,
    query: str,
    pages: int,
    pause_s: float,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    all_rows: list[dict[str, Any]] = []

    for page in range(1, pages + 1):
        url = build_yahoo_fleamarket_search_url(query, page=page)
        print(f"FETCH flea p{page}: {url}")
        try:
            html, status = _fetch(url)
        except urllib.error.URLError as exc:
            report.add(f"flea page {page} fetch", False, str(exc))
            return all_rows

        report.add(f"flea page {page} http", status == 200, f"status={status}")
        if _challenge_like(html):
            report.add(
                f"flea page {page} body",
                False,
                "challenge/empty (no usable __NEXT_DATA__)",
            )
            return all_rows

        parsed = parse_sold_search_html(html)
        report.add(
            f"flea page {page} parse",
            bool(parsed["parse_ok"]),
            f"rows={len(parsed['items'])} total≈{parsed['total_results_available']} "
            f"offset={parsed['offset']}",
        )
        if not parsed["parse_ok"]:
            return all_rows

        ids = [row["listing_id"] for row in parsed["items"]]
        overlap = sorted(seen.intersection(ids))
        expected_offset = (page - 1) * 100
        offset_ok = parsed["offset"] == expected_offset
        report.add(
            f"flea page {page} pagination",
            len(overlap) == 0 and len(ids) > 0 and offset_ok,
            f"unique={len(ids)} overlap={len(overlap)} offset={parsed['offset']} "
            f"(expected {expected_offset})",
        )
        if overlap or not ids or not offset_ok:
            return all_rows

        bad_tax = [
            row["listing_id"]
            for row in parsed["items"]
            if row.get("tax_amount_jpy") is not None
            or row.get("price_includes_tax") is not None
        ]
        sold_ok = all(row.get("item_status") == "SOLD" for row in parsed["items"])
        price_ok = all(
            isinstance(row.get("gross_price_jpy"), int)
            and row["gross_price_jpy"] == row.get("final_price_jpy")
            and row["gross_price_jpy"] > 0
            for row in parsed["items"]
        )
        report.add(
            f"flea page {page} money",
            sold_ok and price_ok and not bad_tax,
            "SOLD hammers, no invented tax"
            if sold_ok and price_ok and not bad_tax
            else f"sold_ok={sold_ok} price_ok={price_ok} invented_tax={len(bad_tax)}",
        )

        seen.update(ids)
        all_rows.extend(parsed["items"])
        if page < pages:
            time.sleep(pause_s)

    report.add(
        "flea pages collected",
        len(seen) >= pages,
        f"unique_ids={len(seen)} across {pages} page(s)",
    )
    return all_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="teresa teng")
    parser.add_argument(
        "--target",
        type=int,
        default=100,
        help="Collect at least this many search listings per marketplace",
    )
    parser.add_argument(
        "--auction-pages",
        type=int,
        default=None,
        help="Auction search pages (default: derive from --target; 0 skips)",
    )
    parser.add_argument(
        "--flea-pages",
        type=int,
        default=None,
        help="Flea search pages (default: derive from --target; 0 skips)",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--pause-s", type=float, default=0.35)
    parser.add_argument(
        "--detail-sample",
        type=int,
        default=0,
        help="Detail-check this many listings per marketplace (0 = all scraped)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write machine-readable report JSON",
    )
    parser.add_argument(
        "--listing-proof-out",
        type=Path,
        default=None,
        help="Per-listing search↔detail proof JSON",
    )
    parser.add_argument(
        "--flea-search-html",
        type=Path,
        default=None,
        help="Optional saved flea search HTML when live search is rate-limited",
    )
    parser.add_argument(
        "--auction-search-html",
        type=Path,
        default=None,
        help="Optional saved auction search HTML (single page) for offline search parse",
    )
    args = parser.parse_args()

    if args.auction_pages is None:
        auction_pages = max(
            1, (args.target + args.page_size - 1) // args.page_size + 1
        )
    else:
        auction_pages = args.auction_pages
    if args.flea_pages is None:
        flea_pages = max(1, (args.target + 99) // 100)
    else:
        flea_pages = args.flea_pages

    report = VerifyReport()
    print("Yahoo JP live scrape/pagination/content verify (no DB write)")
    print(
        f"query={args.query!r} target={args.target} page_size={args.page_size} "
        f"auction_pages={auction_pages} flea_pages={flea_pages} "
        f"detail_sample={'all' if args.detail_sample <= 0 else args.detail_sample}"
    )

    flea_rows: list[dict[str, Any]] = []
    flea_proofs: list[dict[str, Any]] = []
    auction_rows: list[dict[str, Any]] = []
    auction_proofs: list[dict[str, Any]] = []

    # Flea first: its host 429s faster if auction detail bursts run ahead.
    if flea_pages > 0 or args.flea_search_html is not None:
        print("phase: flea search + per-listing details")
        if args.flea_search_html is not None:
            html = args.flea_search_html.read_text(encoding="utf-8")
            parsed = parse_sold_search_html(html)
            report.add(
                "flea search html",
                bool(parsed["parse_ok"]) and len(parsed["items"]) > 0,
                f"file={args.flea_search_html} rows={len(parsed['items'])}",
            )
            flea_rows = parsed["items"]
        else:
            flea_rows = verify_flea(
                report,
                query=args.query,
                pages=flea_pages,
                pause_s=args.pause_s,
            )
        flea_rows = flea_rows[: args.target]
        report.add(
            "flea target count",
            len(flea_rows) >= min(args.target, 1),
            f"using={len(flea_rows)} (want {args.target})",
        )
        verify_listing_contents(
            report,
            label="flea",
            rows=flea_rows,
            checker=_content_ok_flea,
        )
        flea_proofs = verify_flea_details(
            report,
            rows=flea_rows,
            sample=args.detail_sample,
            pause_s=max(args.pause_s, 1.0),
        )
    else:
        report.add("flea skipped", True, "flea-pages=0")

    if auction_pages > 0:
        if flea_pages > 0:
            print("cooldown 8s before auction host…")
            time.sleep(8.0)
        print("phase: auction search + per-listing details")
        auction_rows = verify_auctions(
            report,
            query=args.query,
            pages=auction_pages,
            page_size=args.page_size,
            pause_s=args.pause_s,
        )
        auction_rows = auction_rows[: args.target]
        report.add(
            "auction target count",
            len(auction_rows) >= min(args.target, 1),
            f"using={len(auction_rows)} (want {args.target})",
        )
        verify_listing_contents(
            report,
            label="auction",
            rows=auction_rows,
            checker=_content_ok_auction,
        )
        auction_proofs = verify_auction_details(
            report,
            rows=auction_rows,
            sample=args.detail_sample,
            pause_s=args.pause_s,
        )
    else:
        report.add("auction skipped", True, "auction-pages=0")

    if auction_rows:
        known = next(
            (row for row in auction_rows if row["listing_id"] == "p1252469501"),
            None,
        )
        if known is not None:
            report.add(
                "known screenshot listing p1252469501",
                known.get("gross_price_jpy") == 43018
                and known.get("tax_amount_jpy") == 0
                and known.get("bid_count") == 27
                and known.get("start_price_jpy") == 15000,
                f"gross={known.get('gross_price_jpy')} tax={known.get('tax_amount_jpy')} "
                f"bids={known.get('bid_count')} start={known.get('start_price_jpy')}",
            )
        else:
            report.add(
                "known screenshot listing p1252469501",
                True,
                "not on fetched pages (ok; listing may age off page 1)",
            )

    report.print()
    if args.json_out is not None:
        payload = {
            "ok": report.ok,
            "query": args.query,
            "target": args.target,
            "page_size": args.page_size,
            "auction_rows": len(auction_rows),
            "flea_rows": len(flea_rows),
            "auction_details_ok": sum(1 for p in auction_proofs if p["ok"]),
            "flea_details_ok": sum(1 for p in flea_proofs if p["ok"]),
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail}
                for c in report.checks
            ],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")

    proof_path = args.listing_proof_out
    if proof_path is None and args.json_out is not None:
        proof_path = args.json_out.with_name(
            args.json_out.stem + "-listing-proofs.json"
        )
    if proof_path is not None:
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(
            json.dumps(
                {
                    "ok": report.ok,
                    "auction": auction_proofs,
                    "fleamarket": flea_proofs,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {proof_path}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
