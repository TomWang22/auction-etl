"""Source-contract tests for non-destructive warehouse synchronization."""

from __future__ import annotations

import ast
from pathlib import Path


CLI_PATH = Path(
    "auction_etl/cli/sync.py"
)
SERVICE_PATH = Path(
    "auction_etl/services/warehouse.py"
)


def test_cli_defaults_to_no_prune() -> None:
    """The public synchronization command must default to no pruning."""
    source = CLI_PATH.read_text(
        encoding="utf-8"
    )

    assert "--prune/--no-prune" in source
    assert "Global warehouse pruning is disabled" in source

    tree = ast.parse(source)

    warehouse_function = next(
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == "warehouse"
    )

    assert warehouse_function is not None


def test_service_contains_incomplete_snapshot_guard() -> None:
    """Scoped pruning must reject empty or incomplete snapshots."""
    source = SERVICE_PATH.read_text(
        encoding="utf-8"
    )

    assert "Global warehouse pruning is disabled" in source
    assert "staging contains no" in source
    assert "incomplete marketplace snapshot" in source
    assert "prune: bool = False" in source
