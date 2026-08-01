"""Source contracts for live AG Grid browser acceptance."""

from __future__ import annotations

from pathlib import Path


ACCEPTANCE_PATH = Path(
    "scripts/accept_collector_hover_click.py"
)


def test_acceptance_ignores_hidden_tab_grids() -> None:
    """Only a visible component iframe may be selected."""
    source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "frame.frame_element()",
        "frame_element.is_visible()",
        "frame_element.bounding_box()",
        "visible_row_in_frame(",
        "find_visible_grid(",
        ".ag-center-cols-container",
        ".ag-row",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_acceptance_exercises_hover_and_editor() -> None:
    """Acceptance must test the intended interaction."""
    source = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "first_row.hover()",
        '"ag-row-hover"',
        '"pointer"',
        "click_target.click()",
        "Save collector record",
        ".ag-selection-checkbox:",
        "visible_application_errors(",
        "hover-click-",
        "editor-open.png",
    )

    for fragment in required_fragments:
        assert fragment in source
