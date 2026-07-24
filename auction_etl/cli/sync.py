from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.warehouse import (
    sync_staging_to_warehouse,
    warehouse_counts,
)

app = typer.Typer(
    help="Synchronize generated ETL layers."
)


@app.command("warehouse")
def warehouse(
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
        help="Limit synchronization to ebay or buyee.",
    ),
    prune: bool = typer.Option(
        True,
        "--prune/--no-prune",
        help="Remove warehouse rows absent from staging.",
    ),
) -> None:
    if marketplace not in {
        None,
        "ebay",
        "buyee",
    }:
        raise typer.BadParameter(
            "Marketplace must be ebay or buyee."
        )

    with Session(engine) as session:
        stats = sync_staging_to_warehouse(
            session,
            marketplace=marketplace,
            prune=prune,
        )

        counts = warehouse_counts(session)

    typer.echo()
    typer.echo(
        f"Staging scanned   : {stats.scanned}"
    )
    typer.echo(
        "Inserted/updated  : "
        f"{stats.inserted_or_updated}"
    )
    typer.echo(
        f"Pruned            : {stats.pruned}"
    )

    typer.echo()
    typer.echo("Warehouse rows")
    typer.echo("--------------")

    total = 0

    for source, count in counts:
        typer.echo(
            f"{source:8}: {count}"
        )
        total += count

    typer.echo(
        f"{'total':8}: {total}"
    )

    typer.secho(
        "\n✓ Warehouse synchronization complete.",
        fg=typer.colors.GREEN,
    )
