import typer

from auction_etl.cli.browser import app as browser_app
from auction_etl.cli.crawl import app as crawl_app
from auction_etl.database.health import database_health

app = typer.Typer(
    name="auction",
    help="Terminal-first Auction ETL",
    no_args_is_help=True,
)


@app.command()
def version():
    typer.echo("Auction ETL 0.1.0")


db_app = typer.Typer(help="Database commands")


@db_app.command("check")
def check():
    database_health()
    typer.secho("✓ PostgreSQL connection successful", fg=typer.colors.GREEN)


app.add_typer(db_app, name="db")
app.add_typer(browser_app, name="browser")
app.add_typer(crawl_app, name="crawl")


@app.command()
def ingest():
    typer.echo("Coming soon")


@app.command()
def classify():
    typer.echo("Coming soon")


@app.command()
def report():
    typer.echo("Coming soon")


if __name__ == "__main__":
    app()
