from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.export import (
    export_csv,
    export_docx,
    export_xlsx,
)
from auction_etl.services.report import (
    EBAY_TAX_RATE,
    load_report_rows,
)


app = typer.Typer(
    help="Generate filtered CSV, XLSX, and DOCX reports."
)


def _safe_suffix(value: str) -> str:
    cleaned = value.strip().casefold()

    for character in (
        " ",
        "/",
        "\\",
        ":",
        "*",
        "?",
        '"',
        "<",
        ">",
        "|",
    ):
        cleaned = cleaned.replace(
            character,
            "_",
        )

    return cleaned.strip("_")


@app.command("all")
def export_all(
    output_dir: str = typer.Option(
        "reports",
        "--output-dir",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    seller: str | None = typer.Option(
        None,
        "--seller",
    ),
    exclude_bulk: bool = typer.Option(
        False,
        "--exclude-bulk/--include-bulk",
    ),
    completed_only: bool = typer.Option(
        False,
        "--completed-only/--all-statuses",
    ),
    apply_ebay_tax: bool = typer.Option(
        True,
        "--apply-ebay-tax/--no-ebay-tax",
        help="Apply US/eBay sales tax.",
    ),
    ebay_tax_rate: float = typer.Option(
        0.0625,
        "--ebay-tax-rate",
        help="Default: 6.25%.",
    ),
    include_shipping: bool = typer.Option(
        False,
        "--include-shipping/--exclude-shipping",
        help="Shipping is excluded unless manually populated.",
    ),
    live_fx: bool = typer.Option(
        True,
        "--live-fx/--no-live-fx",
    ),
    jpy_usd_rate: float | None = typer.Option(
        None,
        "--jpy-usd-rate",
    ),
    title: str = typer.Option(
        "Auction Report",
        "--title",
    ),
) -> None:
    if marketplace not in {
        None,
        "ebay",
        "buyee",
    }:
        raise typer.BadParameter(
            "Marketplace must be ebay or buyee."
        )

    if ebay_tax_rate < 0:
        raise typer.BadParameter(
            "eBay tax rate cannot be negative."
        )

    manual_jpy_rate = (
        Decimal(str(jpy_usd_rate))
        if jpy_usd_rate is not None
        else None
    )

    with Session(engine) as session:
        rows = load_report_rows(
            session,
            marketplace=marketplace,
            seller=seller,
            exclude_bulk=exclude_bulk,
            completed_only=completed_only,
            apply_ebay_tax=apply_ebay_tax,
            ebay_tax_rate=Decimal(
                str(ebay_tax_rate)
            ),
            include_shipping=include_shipping,
            live_fx=live_fx,
            jpy_usd_rate=manual_jpy_rate,
        )

    output_path = Path(output_dir)
    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    suffix_parts = []

    if marketplace:
        suffix_parts.append(
            marketplace
        )

    if seller:
        suffix_parts.append(
            _safe_suffix(seller)
        )

    if exclude_bulk:
        suffix_parts.append(
            "no_bulk"
        )

    if completed_only:
        suffix_parts.append(
            "completed"
        )

    suffix = (
        "_" + "_".join(suffix_parts)
        if suffix_parts
        else ""
    )

    csv_path = export_csv(
        rows,
        output_path
        / f"auction_report{suffix}.csv",
    )

    xlsx_path = export_xlsx(
        rows,
        output_path
        / f"auction_report{suffix}.xlsx",
    )

    docx_path = export_docx(
        rows,
        output_path
        / f"auction_report{suffix}.docx",
        title=title,
    )

    typer.echo()
    typer.echo(f"Rows exported : {len(rows)}")
    typer.echo(f"CSV           : {csv_path}")
    typer.echo(f"XLSX          : {xlsx_path}")
    typer.echo(f"DOCX          : {docx_path}")

    typer.echo()
    typer.echo("Tax policy")
    typer.echo("----------")
    typer.echo("Buyee : stored 10% tax data")
    typer.echo(
        "eBay  : "
        + (
            f"{Decimal(str(ebay_tax_rate)) * 100}%"
            if apply_ebay_tax
            else "not applied"
        )
    )
    typer.echo(
        "Shipping: "
        + (
            "included when populated"
            if include_shipping
            else "excluded"
        )
    )

    typer.secho(
        "\n✓ Report generation complete.",
        fg=typer.colors.GREEN,
    )
