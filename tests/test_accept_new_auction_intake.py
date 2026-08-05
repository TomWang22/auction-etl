"""Browser-acceptance contracts for New Auction Intake."""

import ast
from pathlib import Path


SCRIPT = Path(
    "scripts/accept_new_auction_intake.py"
)


def test_acceptance_uses_root_first_sidebar_navigation() -> None:
    """Acceptance uses visible, route-deduplicated sidebar links."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    navigation = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_open_sidebar_page"
        ),
        None,
    )

    assert navigation is not None

    string_literals = {
        node.value
        for node in ast.walk(
            navigation
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

    assert (
        '[data-testid="stSidebar"]'
        in string_literals
    )

    assert "a[href]" in string_literals

    assigned_names: set[str] = set()

    for node in ast.walk(
        navigation
    ):
        targets = []

        if isinstance(
            node,
            ast.Assign,
        ):
            targets = list(
                node.targets
            )
        elif isinstance(
            node,
            ast.AnnAssign,
        ):
            targets = [
                node.target
            ]

        for target in targets:
            if isinstance(
                target,
                ast.Name,
            ):
                assigned_names.add(
                    target.id
                )

    assert {
        "page_slug",
        "candidate_by_route",
        "route_diagnostics",
        "ranked_candidates",
        "selected_candidate",
    } <= assigned_names

    called_attributes = {
        node.func.attr
        for node in ast.walk(
            navigation
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
    }

    assert {
        "is_visible",
        "get_attribute",
        "scroll_into_view_if_needed",
        "click",
        "wait_for",
    } <= called_attributes

    assert "_wait_for_root" in {
        node.func.id
        for node in ast.walk(
            navigation
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
    }

    assert (
        "sidebar link was not uniquely found"
        not in source
    )

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
