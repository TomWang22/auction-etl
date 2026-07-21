import typer

from auction_etl.database.session import SessionLocal
from auction_etl.services.crawl import crawl_url

app = typer.Typer(help="Crawler")


@app.command("url")
def url(url: str):
    with SessionLocal() as session:
        job, page = crawl_url(session, url)

    typer.secho(f"✓ Crawl Job : {job.id}", fg=typer.colors.GREEN)
    typer.echo(f"Page ID : {page.id}")
    typer.echo(f"HTTP    : {page.http_status}")
    typer.echo(f"SHA256  : {page.sha256}")
