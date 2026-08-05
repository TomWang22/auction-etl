"""Tests for completeness-history browser acceptance."""

import ast

from pathlib import Path


SCRIPT = Path(
    "scripts/accept_completeness_history.py"
)


def test_acceptance_uses_proven_root_navigator() -> None:
    """The history acceptance starts from the Streamlit root."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "accept_state_safe_completeness_and_profiles.py",
        "_wait_for_root",
        "open_sidebar_page",
        "Completeness Snapshot History",
        "Assigned auction listing",
        "Chronological change timeline",
        "Immutable snapshot ledger",
        "persistence_controls_clicked",
        "database_writes",
    )

    for fragment in required:
        assert fragment in source


def test_acceptance_never_clicks_persistence_controls() -> None:
    """The browser command performs navigation only."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "Apply reviewed",
        "Save changed",
        "Register attachment",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_assigned_listing_selector_uses_streamlit_structure() -> None:
    """Acceptance recognizes Streamlit and BaseWeb selectboxes."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    helper = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_assigned_listing_selector"
        ),
        None,
    )

    assert helper is not None

    semantic_text = " ".join(
        node.value
        for node in ast.walk(
            helper
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    )

    required = (
        "Assigned",
        "auction",
        "listing",
        "stSelectbox",
        "data-baseweb",
        "aria-autocomplete",
        "Visible comboboxes:",
        "Rendered application excerpt:",
        "assigned-listing-selector-timeout.png",
    )

    for fragment in required:
        assert fragment in semantic_text

    call_names = {
        node.func.id
        for node in ast.walk(
            helper
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

    assert "RuntimeError" in call_names


def test_main_waits_for_history_heading_before_selector() -> None:
    """Page hydration precedes assignment-selector discovery."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    main_function = next(
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name == "main"
    )

    heading_wait_lines = []
    selector_call_lines = []

    for node in ast.walk(
        main_function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if (
            isinstance(
                node.func,
                ast.Attribute,
            )
            and node.func.attr == "wait_for"
        ):
            owner = node.func.value

            if (
                isinstance(
                    owner,
                    ast.Name,
                )
                and owner.id == "history_heading"
            ):
                heading_wait_lines.append(
                    node.lineno
                )

        if (
            isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "_assigned_listing_selector"
        ):
            selector_call_lines.append(
                node.lineno
            )

    assert len(
        heading_wait_lines
    ) == 1

    assert len(
        selector_call_lines
    ) == 1

    assert (
        heading_wait_lines[0]
        < selector_call_lines[0]
    )
