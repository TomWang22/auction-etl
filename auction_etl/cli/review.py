from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy.orm import Session

from auction_etl.database.session import engine
from auction_etl.services.review import (
    CLEAR_VALUE,
    export_review_csv,
    export_review_xlsx,
    import_review_csv,
    import_review_xlsx,
    review_coverage,
)

app = typer.Typer(
    help=(
        "Export and import manual "
        "listing reviews."
    )
)


def _validate_marketplace(
    marketplace: str | None,
) -> None:
    if marketplace not in {
        None,
        "ebay",
        "buyee",
    }:
        raise typer.BadParameter(
            "Marketplace must be "
            "ebay or buyee."
        )


def _print_import_stats(
    stats,
) -> None:
    typer.echo()
    typer.echo(
        f"Rows scanned   : "
        f"{stats.scanned}"
    )
    typer.echo(
        f"Rows matched   : "
        f"{stats.matched}"
    )
    typer.echo(
        f"Rows updated   : "
        f"{stats.updated_rows}"
    )
    typer.echo(
        f"Fields updated : "
        f"{stats.updated_fields}"
    )
    typer.echo(
        f"Missing rows   : "
        f"{stats.missing}"
    )
    typer.echo(
        f"Invalid values : "
        f"{stats.invalid}"
    )

    if (
        stats.invalid
        or stats.missing
    ):
        typer.secho(
            "\n⚠ Import completed "
            "with warnings.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            "\n✓ Review import complete.",
            fg=typer.colors.GREEN,
        )


@app.command("export")
def export_command(
    output: str = typer.Option(
        "review/listings_review.csv",
        "--output",
        "-o",
    ),
    marketplace: str | None = typer.Option(
        None,
        "--marketplace",
        "-m",
    ),
    all_rows: bool = typer.Option(
        False,
        "--all",
        help=(
            "Export every listing, "
            "not only incomplete rows."
        ),
    ),
) -> None:
    _validate_marketplace(
        marketplace
    )

    path = Path(output)
    suffix = path.suffix.casefold()

    with Session(engine) as session:
        if suffix == ".xlsx":
            stats = export_review_xlsx(
                session,
                path,
                marketplace=marketplace,
                all_rows=all_rows,
            )
        elif suffix == ".csv":
            stats = export_review_csv(
                session,
                path,
                marketplace=marketplace,
                all_rows=all_rows,
            )
        else:
            raise typer.BadParameter(
                "Output must end in "
                ".csv or .xlsx."
            )

    typer.secho(
        f"✓ Exported {stats.rows} "
        "review rows",
        fg=typer.colors.GREEN,
    )
    typer.echo(
        f"File: {stats.path}"
    )
    typer.echo(
        f"Use {CLEAR_VALUE} to "
        "explicitly clear a field."
    )


@app.command("import")
def import_command(
    input_path: str = typer.Argument(
        ...,
        help=(
            "Edited review CSV "
            "or XLSX file."
        ),
    ),
) -> None:
    path = Path(input_path)
    suffix = path.suffix.casefold()

    with Session(engine) as session:
        if suffix == ".xlsx":
            stats = import_review_xlsx(
                session,
                path,
            )
        elif suffix == ".csv":
            stats = import_review_csv(
                session,
                path,
            )
        else:
            raise typer.BadParameter(
                "Input must end in "
                ".csv or .xlsx."
            )

    _print_import_stats(stats)


@app.command("status")
def status_command() -> None:
    with Session(engine) as session:
        coverage = review_coverage(
            session
        )

    typer.echo()
    typer.echo(
        "Manual-review field coverage"
    )
    typer.echo(
        "----------------------------"
    )

    for field, (
        populated,
        total,
        percent,
    ) in coverage.items():
        typer.echo(
            f"{field:17}: "
            f"{populated:4}/{total:4} "
            f"({percent:5.1f}%)"
        )
