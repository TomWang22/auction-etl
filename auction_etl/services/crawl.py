from sqlalchemy.orm import Session

from auction_etl.crawlers import crawl
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage
from auction_etl.services.ingest import ingest_raw_page
from auction_etl.urls.router import route_url


def crawl_url(
    session: Session,
    url: str,
    profile: str = "anonymous",
) -> tuple[CrawlJob, list[RawPage]]:
    job = CrawlJob(
        source="manual",
        status="running",
    )

    session.add(job)
    session.flush()

    marketplace = route_url(url)

    pages: list[RawPage] = []

    for page in crawl(
        marketplace=marketplace,
        url=url,
        profile=profile,
    ):
        print(f"Fetching: {page['url']}")

        raw = ingest_raw_page(
            session=session,
            job=job,
            page=page,
            source=marketplace,
        )

        session.flush()

        pages.append(raw)

        print(
            f"Stored page {raw.id}: {raw.url}"
        )

    job.status = "finished"

    session.commit()

    return job, pages
