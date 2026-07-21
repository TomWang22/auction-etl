import typer
from rich import print

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
    print("Database module coming soon.")


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
