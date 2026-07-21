from __future__ import annotations

import shutil

import typer

from auction_etl.browser.profiles import (
    PROFILE_ROOT,
    list_profiles,
    profile_exists,
    profile_path,
)

app = typer.Typer(help="Browser profile management")


@app.command("list")
def list_command() -> None:
    """
    List available browser profiles.
    """
    profiles = list_profiles()

    if not profiles:
        typer.echo("No browser profiles.")
        return

    for profile in profiles:
        typer.echo(profile)


@app.command("create")
def create(profile: str) -> None:
    """
    Create a browser profile.
    """
    path = profile_path(profile)

    typer.secho(
        f"✓ Created {path}",
        fg=typer.colors.GREEN,
    )


@app.command("remove")
def remove(profile: str) -> None:
    """
    Delete a browser profile.
    """
    if not profile_exists(profile):
        typer.secho(
            "Profile does not exist.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    shutil.rmtree(PROFILE_ROOT / profile)

    typer.secho(
        f"✓ Removed {profile}",
        fg=typer.colors.GREEN,
    )
