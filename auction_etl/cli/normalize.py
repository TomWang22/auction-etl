from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.normalize import normalize_staging

app = typer.Typer(help="Normalize parsed listing metadata.")


@app.command("staging")
def staging(
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
        help="Limit normalization to ebay or buyee.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace existing normalized values.",
    ),
) -> None:
    if marketplace not in {None, "ebay", "buyee"}:
        raise typer.BadParameter(
            "Marketplace must be ebay or buyee."
        )

    with Session(engine) as session:
        stats = normalize_staging(
            session,
            marketplace=marketplace,
            force=force,
        )

    typer.echo()
    typer.echo(f"Scanned          : {stats.scanned}")
    typer.echo(f"Changed          : {stats.changed}")
    typer.echo(f"Media classified : {stats.media_classified}")
    typer.echo(f"Catalog numbers  : {stats.catalog_numbers}")
    typer.echo(f"Labels           : {stats.labels}")
    typer.echo(f"Years            : {stats.years}")
    typer.echo(f"Countries        : {stats.countries}")
    typer.echo(f"Media grades     : {stats.media_grades}")
    typer.echo(f"Sleeve grades    : {stats.sleeve_grades}")
    typer.echo(f"Obi values       : {stats.obi_values}")

    typer.secho(
        "\n✓ Staging normalization complete.",
        fg=typer.colors.GREEN,
    )
