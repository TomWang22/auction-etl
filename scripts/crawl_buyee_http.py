"""Persist the authenticated Buyee closed watchlist as one raw crawl page."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from auction_etl.database.session import SessionLocal
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage
from scripts.buyee_http_session import (
    BuyeeHttpState,
    fetch_closed_watchlist,
)


DEFAULT_STATE_FILE = Path(
    '/data/buyee-profile/.auction-etl/private/buyee-storage-state.json'
)

DEFAULT_WATCHLIST_URL = (
    "https://buyee.jp/myorders/watchlist/closed"
)


class BuyeeHttpCrawlError(RuntimeError):
    """Raised when the authenticated HTTPS crawl cannot be persisted."""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the authenticated Buyee closed watchlist over HTTPS "
            "and persist it to raw.page."
        )
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Playwright storage-state JSON containing Buyee authentication.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_WATCHLIST_URL,
        help="Authenticated Buyee watchlist URL.",
    )

    return parser.parse_args()


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def persist_raw_page(
    *,
    session: Session,
    url: str,
    status_code: int,
    html: str,
) -> tuple[CrawlJob, RawPage]:
    """Persist one Buyee crawl job and its raw page."""
    job = CrawlJob(
        source="manual",
        status="running",
    )

    session.add(job)
    session.flush()

    raw_page = RawPage(
        crawl_job_id=job.id,
        source="buyee",
        url=url,
        sha256=sha256_text(html),
        http_status=status_code,
        html=html,
    )

    session.add(raw_page)
    session.flush()

    job.status = "finished"
    session.commit()

    return job, raw_page


def crawl_closed_watchlist(
    *,
    session: Session,
    state_file: Path,
    url: str = DEFAULT_WATCHLIST_URL,
) -> tuple[CrawlJob, RawPage]:
    """Fetch and persist the authenticated Buyee closed watchlist."""
    result = fetch_closed_watchlist(
        storage_state_path=state_file,
        url=url,
    )

    if result.state is not BuyeeHttpState.AUTHENTICATED:
        raise BuyeeHttpCrawlError(
            "Buyee HTTPS session is not authenticated: "
            f"{result.state.value}"
        )

    if result.status_code is None:
        raise BuyeeHttpCrawlError(
            "Buyee HTTPS response did not include an HTTP status."
        )

    if not result.body.strip():
        raise BuyeeHttpCrawlError(
            "Buyee HTTPS response body is empty."
        )

    if not result.auction_links:
        raise BuyeeHttpCrawlError(
            "Buyee authenticated watchlist contained zero auction links."
        )

    return persist_raw_page(
        session=session,
        url=result.final_url,
        status_code=result.status_code,
        html=result.body,
    )


def main() -> int:
    """Run one authenticated Buyee HTTPS raw-page crawl."""
    arguments = parse_arguments()

    with SessionLocal() as session:
        job, raw_page = crawl_closed_watchlist(
            session=session,
            state_file=arguments.state_file.expanduser(),
            url=arguments.url,
        )

    print(f"✓ Crawl Job : {job.id}")
    print()
    print(f"Page ID : {raw_page.id}")
    print(f"URL     : {raw_page.url}")
    print(f"HTTP    : {raw_page.http_status}")
    print(f"SHA256  : {raw_page.sha256}")
    print()
    print("Fetched 1 page(s)")
    print()
    print("BUYEE_HTTP_RAW_CRAWL=PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
