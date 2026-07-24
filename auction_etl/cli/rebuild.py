from __future__ import annotations

import typer
from sqlalchemy import update
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.models.raw import RawPage
from auction_etl.models.staging import Listing
from auction_etl.services.parse import parse_all

app = typer.Typer(help="Rebuild generated ETL layers.")


@app.command("staging")
def rebuild_staging(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm deletion and regeneration of staging listings.",
    ),
) -> None:
    if not yes:
        raise typer.BadParameter(
            "Pass --yes to rebuild staging.listing."
        )

    with Session(engine) as session:
        deleted = session.query(Listing).delete(
            synchronize_session=False
        )

        session.execute(
            update(RawPage).values(
                parsed_at=None,
                listing_count=None,
            )
        )

        stats = parse_all(
            session,
            force=True,
        )

    typer.echo()
    typer.echo(f"Deleted rows : {deleted}")
    typer.echo(f"Pages parsed : {stats.pages}")
    typer.echo(f"Listings     : {stats.listings}")

    typer.secho(
        "\n✓ staging.listing rebuilt.",
        fg=typer.colors.GREEN,
    )
