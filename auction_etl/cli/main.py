import typer

from auction_etl.cli.audit import app as audit_app
from auction_etl.cli.doctor import app as doctor_app
from auction_etl.cli.review import app as review_app
from auction_etl.cli.stats import app as stats_app
from auction_etl.cli.browser import app as browser_app
from auction_etl.cli.crawl import app as crawl_app
from auction_etl.cli.ingest import app as ingest_app
from auction_etl.cli.sync import app as sync_app
from auction_etl.database.health import database_health

app = typer.Typer(
    name="auction",
    help="Terminal-first Auction ETL",
    no_args_is_help=True,
)


@app.command()
def version():
    typer.echo("Auction ETL 0.1.0")


db_app = typer.Typer(help="Database")


@db_app.command("check")
def check():
    database_health()
    typer.secho(
        "✓ PostgreSQL connection successful",
        fg=typer.colors.GREEN,
    )


app.add_typer(db_app, name="db")
app.add_typer(browser_app, name="browser")
app.add_typer(crawl_app, name="crawl")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sync_app, name="sync")
app.add_typer(review_app, name="review")
app.add_typer(stats_app, name="stats")
app.add_typer(doctor_app, name="doctor")
app.add_typer(audit_app, name="audit")



if __name__ == "__main__":
    app()
