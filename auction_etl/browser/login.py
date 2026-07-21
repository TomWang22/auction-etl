from __future__ import annotations

import typer
from playwright.sync_api import TimeoutError

from auction_etl.browser.manager import browser


def login(profile: str, url: str) -> None:
    context = browser.context(profile)

    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()

    try:
        page.goto(url, wait_until="load", timeout=60_000)
    except TimeoutError:
        typer.secho(
            "Navigation timed out. The browser is still open; continue manually.",
            fg=typer.colors.YELLOW,
        )

    typer.secho(
        f"Browser opened with profile '{profile}'.",
        fg=typer.colors.GREEN,
    )

    typer.echo("Log in manually if needed.")
    typer.prompt("Press ENTER to save the session", default="", show_default=False)

    browser.close()

    typer.secho("✓ Session saved.", fg=typer.colors.GREEN)
