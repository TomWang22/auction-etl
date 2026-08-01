"""Regression contracts for Collector Review save SQL."""

from __future__ import annotations

import ast
from pathlib import Path


APP_PATH = Path(
    "app/collector_review.py"
)
ACCEPTANCE_PATH = Path(
    "scripts/accept_collector_hover_click.py"
)


def save_insert_sql() -> str:
    """Return the collector INSERT SQL constant."""
    source = APP_PATH.read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    function = next(
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name
        == "save_collector_record"
    )

    statements = [
        node.value
        for node in ast.walk(function)
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
        and (
            "INSERT INTO "
            "warehouse.auction_collector"
        )
        in node.value
    ]

    assert len(statements) == 1
    return statements[0]


def test_save_insert_has_explicit_types() -> None:
    """Psycopg parameters must have one unambiguous type."""
    statement = save_insert_sql()

    assert (
        "CAST(:marketplace AS "
        "character varying)"
        in statement
    )
    assert (
        "CAST(:listing_id AS "
        "character varying)"
        in statement
    )


def test_save_insert_is_conflict_safe() -> None:
    """Ensuring a collector row must be atomic."""
    statement = save_insert_sql()

    assert "VALUES" in statement
    assert "ON CONFLICT" in statement
    assert "DO NOTHING" in statement
    assert "WHERE NOT EXISTS" not in statement


def test_closed_browser_diagnostics_are_safe() -> None:
    """A closed Chrome window must not mask an error."""
    source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    assert "if page.is_closed():" in source
    assert '"page_closed": True' in source
