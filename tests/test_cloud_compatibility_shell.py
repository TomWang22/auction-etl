"""Tests for the retired Railway compatibility shell."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts import (
    run_cloud_compatibility_shell as shell,
)


def test_check_mode_accepts_railway(
    monkeypatch,
    capsys,
) -> None:
    """Railway check mode confirms the database-free contract."""
    monkeypatch.setenv(
        "RAILWAY_DEPLOYMENT_ID",
        "test-deployment",
    )
    monkeypatch.setenv(
        "RAILWAY_SERVICE_ID",
        "test-service",
    )

    status = shell.main(
        [
            "--check",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert captured.err == ""

    assert (
        "RAILWAY_COMPATIBILITY_SHELL=true"
        in captured.out
    )
    assert (
        "DATA_AUTHORITY=local"
        in captured.out
    )
    assert (
        "CLOUD_DATABASE_ACCESS=false"
        in captured.out
    )
    assert (
        "CLOUD_REFRESH_WORKER_EXECUTED=false"
        in captured.out
    )
    assert (
        "MARKETPLACE_REQUEST_EXECUTED=false"
        in captured.out
    )
    assert (
        "RAILWAY_COMPATIBILITY_SHELL_CHECK=PASS"
        in captured.out
    )


def test_non_railway_runtime_is_rejected(
    monkeypatch,
    capsys,
) -> None:
    """The compatibility process cannot masquerade as a local service."""
    for variable in (
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
        "VERCEL",
        "VERCEL_ENV",
    ):
        monkeypatch.delenv(
            variable,
            raising=False,
        )

    status = shell.main(
        [
            "--check",
        ]
    )

    captured = capsys.readouterr()

    assert status == 2
    assert (
        "Railway deployment identity is unavailable."
        in captured.err
    )


def test_compatibility_shell_has_no_data_or_marketplace_clients() -> None:
    """The shell must remain structurally unable to perform cloud ETL."""
    path = Path(
        "scripts/run_cloud_compatibility_shell.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )

    imported_modules: set[str] = set()

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                imported_modules.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.add(
                node.module
                or ""
            )

    forbidden_roots = {
        "httpx",
        "playwright",
        "psycopg",
        "requests",
        "socket",
        "sqlalchemy",
        "subprocess",
        "urllib",
    }

    imported_roots = {
        module.split(
            ".",
            1,
        )[0]
        for module in imported_modules
        if module
    }

    assert not (
        forbidden_roots
        & imported_roots
    )

    assert (
        "auction_etl.runtime_authority"
        in imported_modules
    )


def test_railway_iac_starts_only_compatibility_shell() -> None:
    """Railway must not launch the prohibited legacy refresh worker."""
    text = Path(
        ".railway/railway.ts"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'startCommand: '
        '"python scripts/run_cloud_compatibility_shell.py"'
        in text
    )

    assert (
        'startCommand: '
        '"python scripts/run_cloud_refresh_worker.py"'
        not in text
    )
