import typer

from auction_etl.database.session import SessionLocal
from auction_etl.services.parse import sync_pages

app = typer.Typer(help="Parse raw pages into the warehouse")


@app.command()
def run():
    with SessionLocal() as session:
        pages, listings = sync_pages(session)

    typer.secho("✓ Sync complete", fg=typer.colors.GREEN)
    typer.echo(f"Pages    : {pages}")
    typer.echo(f"Listings : {listings}")
