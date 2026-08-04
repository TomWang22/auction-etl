"""Structural tests for all-pressing browser acceptance."""

from __future__ import annotations

import ast
from pathlib import Path


SCRIPT = Path(
    "scripts/accept_media_aware_reference.py"
)


def test_acceptance_iterates_every_pressing() -> None:
    """Acceptance is not tied to one catalog number."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert "MR2276" not in source
    assert "list_pressings" in source
    assert "load_media_profile" in source
    assert "for pressing in pressings" in source
    assert "PROFILE_CONTRACT " in source


def test_acceptance_never_clicks_persistence_controls() -> None:
    """The live browser run remains read-only."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    main_function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "main"
        ),
        None,
    )

    assert main_function is not None

    string_literals = {
        node.value
        for node in ast.walk(
            main_function
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    }

    assert "Preview reviewed changes" in string_literals
    assert "Apply reviewed master reference" not in string_literals
    assert "persistence_controls_clicked" in string_literals
    assert "database_writes" in string_literals
