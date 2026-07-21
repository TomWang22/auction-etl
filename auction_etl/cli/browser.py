from __future__ import annotations

import shutil

import typer

from auction_etl.browser.login import login
from auction_etl.browser.profiles import (
    PROFILE_ROOT,
    list_profiles,
    profile_exists,
    profile_path,
)

app = typer.Typer(help="Browser profile management")


@app.command("list")
def list_command() -> None:
    profiles = list_profiles()

    if not profiles:
        typer.echo("No browser profiles.")
        return

    for profile in profiles:
        typer.echo(profile)


@app.command("create")
def create(profile: str) -> None:
    typer.secho(
        f"✓ Created {profile_path(profile)}",
        fg=typer.colors.GREEN,
    )


@app.command("remove")
def remove(profile: str) -> None:
    if not profile_exists(profile):
        typer.secho(
            "Profile does not exist.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    shutil.rmtree(PROFILE_ROOT / profile)

    typer.secho(
        f"✓ Removed {profile}",
        fg=typer.colors.GREEN,
    )


@app.command("login")
def login_command(
    profile: str,
    marketplace: str = "ebay",
) -> None:
    urls = {
        "ebay": "https://www.ebay.com/",
        "buyee": "https://buyee.jp/",
    }

    if marketplace not in urls:
        raise typer.BadParameter(f"Unknown marketplace: {marketplace}")

    login(profile, urls[marketplace])
