from __future__ import annotations

import typer

from auction_etl.database.session import engine
from auction_etl.services.discogs_fill import (
    fill_unmatched_identities,
    identity_counts,
)


app = typer.Typer(help="Discogs pressing identity fill")


@app.command("fill")
def fill(
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
        help="Limit identity fill to one marketplace.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        help="Fill at most this many unmatched warehouse rows.",
    ),
) -> None:
    """Search Discogs and auto-fill dead-on catalog matches."""
    stats = fill_unmatched_identities(
        engine,
        marketplace=marketplace,
        limit=limit,
    )
    typer.echo(f"Scanned          : {stats.scanned}")
    typer.echo(f"Discogs searches : {stats.searched}")
    typer.echo(f"Filled auto      : {stats.filled_auto}")
    typer.echo(f"Reused           : {stats.reused}")
    typer.echo(f"Need review      : {stats.needs_review}")
    typer.echo(f"Unmatched        : {stats.unmatched}")
    typer.echo(f"Images copied    : {stats.images_copied}")
    typer.echo(stats.caption())
    if stats.stopped_reason:
        typer.secho(
            "Stopped early after a Discogs HTTP or rate-limit error.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)
    typer.secho("✓ Identity fill complete.", fg=typer.colors.GREEN)


@app.command("stats")
def stats() -> None:
    """Show warehouse identity_status totals."""
    counts = identity_counts(engine)
    typer.echo(f"Filled     : {counts['filled']}")
    typer.echo(f"  auto     : {counts['filled_auto']}")
    typer.echo(f"  manual   : {counts['filled_manual']}")
    typer.echo(f"Need review: {counts['needs_review']}")
    typer.echo(f"Unmatched  : {counts['unmatched']}")
