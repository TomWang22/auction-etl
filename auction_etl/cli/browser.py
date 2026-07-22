from __future__ import annotations

import typer

from auction_etl.browser.login import login

app = typer.Typer(help="Browser utilities")


@app.command("login")
def login_command(
    url: str,
    profile: str = typer.Option(
        ...,
        "--profile",
        "-p",
        help="Browser profile name.",
    ),
) -> None:
    login(
        profile=profile,
        url=url,
    )


if __name__ == "__main__":
    app()
