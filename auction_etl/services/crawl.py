from sqlalchemy.orm import Session

from auction_etl.browser.fetch import fetch
from auction_etl.models.crawl import CrawlJob
from auction_etl.models.raw import RawPage
from auction_etl.crawlers import next_page
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

    pages: list[RawPage] = []
    visited: set[str] = set()

    marketplace = route_url(url)

    current_url = url

    while current_url and current_url not in visited:
        visited.add(current_url)

        print(f"Fetching: {current_url}")

        page = fetch(
            url=current_url,
            profile=profile,
        )

        raw = ingest_raw_page(
            session=session,
            job=job,
            page=page,
            source=profile,
        )

        session.flush()

        pages.append(raw)

        print(
            f"Stored page {raw.id}: "
            f"{raw.url}"
        )

        current_url = next_page(
            marketplace,
            raw.html,
        )

    job.status = "finished"

    session.commit()

    return job, pages
