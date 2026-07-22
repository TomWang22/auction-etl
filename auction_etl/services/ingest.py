from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage


def ingest_raw_page(
    session: Session,
    *,
    job: CrawlJob,
    page: dict,
    source: str,
) -> RawPage:
    existing = session.scalar(
        select(RawPage).where(
            RawPage.sha256 == page["sha256"]
        )
    )

    if existing is not None:
        print(f"SKIP duplicate page: {existing.id}")
        return existing

    raw = RawPage(
        crawl_job_id=job.id,
        source=source,
        url=page["url"],
        sha256=page["sha256"],
        http_status=page["status"],
        html=page["html"],
    )

    session.add(raw)
    session.flush()

    print(f"NEW  page: {raw.id}")

    return raw
