from __future__ import annotations

import logging
from datetime import datetime, timezone

import typer

from auction_etl.database.session import engine
from auction_etl.services.discogs_fill import (
    fill_unmatched_identities,
    identity_counts,
)

BACKLOG_SINCE = datetime(2000, 1, 1, tzinfo=timezone.utc)
BACKLOG_BUDGET_SECONDS = 20 * 60.0


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
    backlog: bool = typer.Option(
        False,
        "--backlog",
        help=(
            "Search the older unmatched pile without retuning fills that "
            "are already in. A clear Discogs catalog match is saved. "
            "An ambiguous one stays for review."
        ),
    ),
) -> None:
    """Search Discogs and auto-fill dead-on catalog matches."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
    )
    stats = fill_unmatched_identities(
        engine,
        marketplace=marketplace,
        limit=limit,
        retune=not backlog,
        since=BACKLOG_SINCE if backlog else None,
        budget_seconds=BACKLOG_BUDGET_SECONDS if backlog else None,
        fail_fast=False if backlog else None,
    )
    typer.echo(f"Scanned          : {stats.scanned}")
    typer.echo(f"Discogs searches : {stats.searched}")
    typer.echo(f"Filled auto      : {stats.filled_auto}")
    typer.echo(f"Reused           : {stats.reused}")
    typer.echo(f"Need review      : {stats.needs_review}")
    typer.echo(f"Unmatched        : {stats.unmatched}")
    typer.echo(f"Images copied    : {stats.images_copied}")
    typer.echo(f"Cover matched    : {stats.cover_matched}")
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
