import typer

from auction_etl.database.session import SessionLocal
from auction_etl.services.crawl import crawl_url

app = typer.Typer(help="Crawler")


@app.command("url")
def url(
    url: str,
    profile: str = typer.Option(
        "anonymous",
        "--profile",
        "-p",
        help="Browser profile to use.",
    ),
):
    with SessionLocal() as session:
        job, pages = crawl_url(
            session=session,
            url=url,
            profile=profile,
        )

    typer.secho(
        f"✓ Crawl Job : {job.id}",
        fg=typer.colors.GREEN,
    )

    for page in pages:
        typer.echo("")
        typer.echo(f"Page ID : {page.id}")
        typer.echo(f"URL     : {page.url}")
        typer.echo(f"HTTP    : {page.http_status}")
        typer.echo(f"SHA256  : {page.sha256}")

    typer.echo("")
    typer.secho(
        f"Fetched {len(pages)} page(s)",
        fg=typer.colors.CYAN,
    )


if __name__ == "__main__":
    app()
