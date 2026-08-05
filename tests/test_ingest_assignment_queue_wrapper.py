"""Safety contracts for the ingestion wrapper."""

import ast
from pathlib import Path


SCRIPT = Path(
    "scripts/run_ingest_with_assignment_queue.py"
)


def test_wrapper_defaults_to_dry_run() -> None:
    """The external command cannot run without explicit execution."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert "--execute" in source
    assert "if not args.execute" in source
    assert '"DRY_RUN"' in source


def test_wrapper_never_auto_assigns() -> None:
    """The wrapper contains no assignment mutation."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    ).lower()

    assert (
        "insert into warehouse.auction_pressing_assignment"
        not in source
    )

    assert (
        "update warehouse.auction_pressing_assignment"
        not in source
    )

    assert (
        "delete from warehouse.auction_pressing_assignment"
        not in source
    )


def test_subprocess_does_not_use_shell_mode() -> None:
    """Ingest command arguments are passed without shell expansion."""
    tree = ast.parse(
        SCRIPT.read_text(
            encoding="utf-8"
        )
    )

    run_calls = [
        node
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and node.func.attr == "run"
    ]

    assert run_calls

    for call in run_calls:
        keyword_names = {
            keyword.arg
            for keyword in call.keywords
        }

        assert "shell" not in keyword_names
