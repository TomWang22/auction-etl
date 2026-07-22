import typer

from auction_etl.config.settings import settings
from auction_etl.database.session import SessionLocal
from auction_etl.services.crawl import crawl_url

app = typer.Typer(help="Raw page ingestion")


@app.command("url")
def ingest_url():
    if not settings.auction_url:
        raise typer.BadParameter("AUCTION_URL is not configured.")

    with SessionLocal() as session:
        job, pages = crawl_url(
            session=session,
            url=settings.auction_url,
        )

    typer.secho("✓ Stored raw page", fg=typer.colors.GREEN)
    typer.echo(f"Job ID     : {job.id}")
    typer.echo(f"Page ID    : {pages[-1].id}")
    typer.echo(f"HTTP       : {pages[-1].http_status}")
    typer.echo(f"SHA256     : {pages[-1].sha256}")
