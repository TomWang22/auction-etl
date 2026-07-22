import typer

app = typer.Typer(help="Review auctions")


@app.command()
def run() -> None:
    typer.echo("Review subsystem coming soon")
