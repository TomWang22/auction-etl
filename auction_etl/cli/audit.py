import typer

app = typer.Typer(help="Audit warehouse")


@app.command()
def run() -> None:
    typer.echo("Audit coming soon")
