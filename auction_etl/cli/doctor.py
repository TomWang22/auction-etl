from __future__ import annotations

import typer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.models.raw import RawPage
from auction_etl.models.staging import Listing

app = typer.Typer(help="Project health checks")


@app.command()
def run() -> None:
    with Session(engine) as session:

        raw_pages = session.scalar(
            select(func.count()).select_from(RawPage)
        )

        parsed_pages = session.scalar(
            select(func.count()).select_from(RawPage).where(
                RawPage.parsed_at.is_not(None)
            )
        )

        listings = session.scalar(
            select(func.count()).select_from(Listing)
        )

        orphaned = session.scalar(
            select(func.count())
            .select_from(Listing)
            .outerjoin(RawPage, Listing.raw_page_id == RawPage.id)
            .where(RawPage.id.is_(None))
        )

        duplicate_ids = session.execute(
            select(
                Listing.marketplace,
                Listing.listing_id,
                func.count(),
            )
            .group_by(
                Listing.marketplace,
                Listing.listing_id,
            )
            .having(func.count() > 1)
        ).all()

        typer.echo()
        typer.echo(f"Raw pages     : {raw_pages}")
        typer.echo(f"Parsed pages  : {parsed_pages}")
        typer.echo(f"Listings      : {listings}")
        typer.echo(f"Orphans       : {orphaned}")
        typer.echo(f"Duplicates    : {len(duplicate_ids)}")

        if duplicate_ids:
            typer.secho(
                "\nDuplicate listing ids detected:",
                fg=typer.colors.YELLOW,
            )

            for marketplace, listing_id, count in duplicate_ids[:20]:
                typer.echo(
                    f"  {marketplace:8} {listing_id} ({count})"
                )

        if orphaned == 0 and not duplicate_ids:
            typer.secho(
                "\n✓ Health check passed.",
                fg=typer.colors.GREEN,
            )
