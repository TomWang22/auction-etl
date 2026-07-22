import typer
from sqlalchemy import text

from auction_etl.database.session import engine

app = typer.Typer(help="Warehouse statistics")


@app.command()
def run() -> None:
    queries = {
        "Auctions": """
            SELECT COUNT(*)
            FROM warehouse.auction
        """,
        "Artists": """
            SELECT COUNT(DISTINCT artist)
            FROM warehouse.auction
            WHERE artist IS NOT NULL
        """,
        "Bulk lots": """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE bulk_lot
        """,
        "Unknown media": """
            SELECT COUNT(*)
            FROM warehouse.auction
            WHERE media_type IS NULL
        """,
        "Latest auction": """
            SELECT MAX(ended_at)
            FROM warehouse.auction
        """,
        "Oldest auction": """
            SELECT MIN(ended_at)
            FROM warehouse.auction
        """,
    }

    typer.echo()
    typer.secho("Warehouse Statistics", bold=True)
    typer.echo("=" * 40)

    with engine.begin() as conn:
        for title, sql in queries.items():
            value = conn.execute(text(sql)).scalar()
            typer.echo(f"{title:<18} {value}")

    typer.echo()
