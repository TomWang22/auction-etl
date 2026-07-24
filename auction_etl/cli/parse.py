from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.parse import (
    parse_all,
    parse_latest,
    parse_page,
    parse_source,
)

app = typer.Typer(help="Parse raw HTML into staging listings.")


def _print_stats(stats) -> None:
    typer.secho("", nl=False)
    typer.echo(f"Pages parsed : {stats.pages}")
    typer.echo(f"Listings     : {stats.listings}")


@app.command()
def latest(
    force: bool = typer.Option(
        False,
        "--force",
        help="Reparse pages that have already been parsed.",
    ),
) -> None:
    with Session(engine) as session:
        _print_stats(parse_latest(session, force=force))


@app.command("all")
def all_pages(
    force: bool = typer.Option(
        False,
        "--force",
        help="Reparse pages that have already been parsed.",
    ),
) -> None:
    with Session(engine) as session:
        _print_stats(parse_all(session, force=force))


@app.command()
def source(
    marketplace: str = typer.Argument(..., help="ebay or buyee"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reparse pages that have already been parsed.",
    ),
) -> None:
    with Session(engine) as session:
        _print_stats(parse_source(session, marketplace, force=force))


@app.command()
def page(
    page_id: int,
) -> None:
    with Session(engine) as session:
        _print_stats(parse_page(session, page_id))
