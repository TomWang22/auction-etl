import typer
from rich import print

from auction_etl.database.health import database_health

app = typer.Typer(
    name="auction",
    help="Terminal-first Auction ETL",
    no_args_is_help=True,
)


@app.command()
def version():
    print("[green]Auction ETL[/green]")
    print("Version: 0.1.0")


@app.command()
def db():
    """Verify database connectivity."""
    try:
        database_health()
        print("[green]✓ PostgreSQL connection successful[/green]")
    except Exception as exc:
        print(f"[red]Database error:[/red] {exc}")


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
