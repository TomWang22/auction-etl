from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.export import (
    ensure_output_dir,
    export_csv,
    export_docx,
    export_json,
    export_markdown,
    export_xlsx,
    load_rows,
)

app = typer.Typer(
    help="Export warehouse auction records."
)


def _load(
    marketplace: str | None,
    live_fx: bool,
    jpy_usd_rate: float | None,
) -> list[dict]:
    manual_rate = (
        Decimal(str(jpy_usd_rate))
        if jpy_usd_rate is not None
        else None
    )

    with Session(engine) as session:
        return load_rows(
            session,
            marketplace=marketplace,
            live_fx=live_fx,
            jpy_usd_rate=manual_rate,
        )


def _finish(
    path: Path,
    count: int,
) -> None:
    typer.secho(
        f"✓ Exported {count} warehouse auctions",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"File: {path}")


def _suffix(
    marketplace: str | None,
) -> str:
    return (
        f"_{marketplace}"
        if marketplace
        else ""
    )


@app.command("csv")
def csv_export(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
        help="Override the JPY to USD rate.",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )
    directory = ensure_output_dir(
        output_dir
    )
    path = export_csv(
        rows,
        directory
        / f"auctions{_suffix(marketplace)}.csv",
    )
    _finish(path, len(rows))


@app.command("json")
def json_export(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )
    directory = ensure_output_dir(
        output_dir
    )
    path = export_json(
        rows,
        directory
        / f"auctions{_suffix(marketplace)}.json",
    )
    _finish(path, len(rows))


@app.command("markdown")
def markdown_export(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    title: str = typer.Option(
        "Auction Warehouse",
        "--title",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )
    directory = ensure_output_dir(
        output_dir
    )
    path = export_markdown(
        rows,
        directory
        / f"auctions{_suffix(marketplace)}.md",
        title=title,
    )
    _finish(path, len(rows))


@app.command("xlsx")
def xlsx_export(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )
    directory = ensure_output_dir(
        output_dir
    )
    path = export_xlsx(
        rows,
        directory
        / f"auctions{_suffix(marketplace)}.xlsx",
    )
    _finish(path, len(rows))


@app.command("docx")
def docx_export(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    title: str = typer.Option(
        "Auction Warehouse",
        "--title",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )
    directory = ensure_output_dir(
        output_dir
    )
    path = export_docx(
        rows,
        directory
        / f"auctions{_suffix(marketplace)}.docx",
        title=title,
    )
    _finish(path, len(rows))


@app.command("all")
def export_all(
    output_dir: str = typer.Option(
        "exports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    title: str = typer.Option(
        "Auction Warehouse",
        "--title",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
        help="Override the JPY to USD rate.",
    ),
) -> None:
    rows = _load(
        marketplace,
        live_fx,
        jpy_usd_rate,
    )

    directory = ensure_output_dir(
        output_dir
    )

    suffix = _suffix(marketplace)

    paths = [
        export_csv(
            rows,
            directory
            / f"auctions{suffix}.csv",
        ),
        export_json(
            rows,
            directory
            / f"auctions{suffix}.json",
        ),
        export_markdown(
            rows,
            directory
            / f"auctions{suffix}.md",
            title=title,
        ),
        export_xlsx(
            rows,
            directory
            / f"auctions{suffix}.xlsx",
        ),
        export_docx(
            rows,
            directory
            / f"auctions{suffix}.docx",
            title=title,
        ),
    ]

    typer.secho(
        f"✓ Exported {len(rows)} warehouse auctions",
        fg=typer.colors.GREEN,
    )

    for path in paths:
        typer.echo(path)
