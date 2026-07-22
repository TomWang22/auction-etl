from __future__ import annotations

import typer

from auction_etl.browser.login import login

app = typer.Typer(help="Browser utilities")


@app.command("login")
def browser_login(
    url: str,
    profile: str = typer.Option(
        "anonymous",
        "--profile",
        "-p",
        help="Browser profile",
    ),
) -> None:
    login(
        profile=profile,
        url=url,
    )


if __name__ == "__main__":
    app()
