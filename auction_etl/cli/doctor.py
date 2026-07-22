import typer

app = typer.Typer(help="Project health checks")


@app.command()
def run() -> None:
    typer.echo("Doctor coming soon")
