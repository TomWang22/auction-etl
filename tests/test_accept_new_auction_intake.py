"""Browser-acceptance contracts for New Auction Intake."""

import ast
from pathlib import Path


SCRIPT = Path(
    "scripts/accept_new_auction_intake.py"
)


def test_acceptance_uses_root_first_sidebar_navigation() -> None:
    """Deep-link internal requests cannot corrupt Streamlit startup."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert "_wait_for_root" in source
    assert "_open_sidebar_page" in source
    assert "a[href]" in source
    assert "New Auction Intake" in source


def test_acceptance_clicks_no_persistence_control() -> None:
    """Browser acceptance remains read-only."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    click_literals = []

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not isinstance(
            node.func,
            ast.Attribute,
        ):
            continue

        if node.func.attr != "click":
            continue

        click_literals.append(
            int(
                node.lineno
            )
        )

    assert click_literals
    assert "Apply reviewed assignment" not in source.split(
        "def main()",
        1,
    )[1]
