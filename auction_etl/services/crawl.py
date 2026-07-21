from sqlalchemy.orm import Session

from auction_etl.browser.fetch import fetch
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage


def crawl_url(session: Session, url: str) -> tuple[CrawlJob, RawPage]:
    job = CrawlJob(
        source="manual",
        status="running",
    )

    session.add(job)
    session.flush()

    page = fetch(url)

    raw = RawPage(
        crawl_job_id=job.id,
        source="manual",
        url=page["url"],
        sha256=page["sha256"],
        http_status=page["status"],
        html=page["html"],
    )

    session.add(raw)
    session.flush()

    job.status = "finished"

    session.commit()

    return job, raw
