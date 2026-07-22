from __future__ import annotations

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

    return raw
