"""Regression tests for the product-facing on-demand ingestion runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path

from auction_etl.services import auction_ingest_job


ROOT = Path(__file__).resolve().parents[1]

RUNNER = (
    ROOT
    / "scripts"
    / "run_auction_refresh_on_demand.sh"
)

PARENT = (
    ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py"
)


def test_on_demand_runner_is_colima_only() -> None:
    """Keep the ingestion button on the established Colima runtime."""

    source = RUNNER.read_text(
        encoding="utf-8",
    )

    required = (
        "colima",
        "auction-etl-db-1",
        "127.0.0.1",
        "5544",
        "run_multisource_ingestion_round.py",
        "--execute",
    )

    forbidden = (
        "5444",
        "desktop-linux",
        "Docker Desktop",
        "auction-postgres-recovered",
        "auction-etl_recovered_postgres_data",
        "verified recovery",
        "775",
    )

    for value in required:
        assert value in source

    for value in forbidden:
        assert value not in source


def test_on_demand_runner_has_valid_bash_syntax() -> None:
    """Reject malformed shell changes before they reach the UI."""

    result = subprocess.run(
        [
            "bash",
            "-n",
            str(
                RUNNER
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        result.stdout
        + result.stderr
    )


def test_ingestion_service_still_uses_on_demand_adapter() -> None:
    """Keep the background job service connected to the guarded adapter."""

    assert (
        auction_ingest_job.DEFAULT_RUNNER.resolve()
        == RUNNER.resolve()
    )


def test_canonical_multisource_parent_exists() -> None:
    """Require the established eBay, Buyee, and Gripsweat parent."""

    assert PARENT.is_file()

    source = PARENT.read_text(
        encoding="utf-8",
    )

    assert "127.0.0.1:5544" in source
    assert "run_latest_auction_refresh.py" in source
