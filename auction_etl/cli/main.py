import typer
from rich import print

from auction_etl.database.bootstrap import bootstrap_database
from auction_etl.database.health import database_health, list_schemas

app = typer.Typer(
    name="auction",
    help="Terminal-first Auction ETL",
    no_args_is_help=True,
)


db_app = typer.Typer(help="Database commands")
app.add_typer(db_app, name="db")


@app.command()
def version():
    print("[green]Auction ETL[/green]")
    print("Version: 0.1.0")


@db_app.command("check")
def check():
    database_health()
    print("[green]✓ PostgreSQL connection successful[/green]")


@db_app.command("init")
def init():
    bootstrap_database()
    print("[green]✓ Database initialized[/green]")


@db_app.command("schemas")
def schemas():
    for schema in list_schemas():
        print(schema)


@app.command()
def crawl():
    print("Crawler coming soon.")


@app.command()
def ingest():
    print("Ingestion coming soon.")


@app.command()
def classify():
    print("Classification coming soon.")


@app.command()
def report():
    print("Reports coming soon.")


if __name__ == "__main__":
    app()
