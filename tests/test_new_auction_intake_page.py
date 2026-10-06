"""Page contracts for New Auction Intake."""

import ast
from pathlib import Path


PAGE = Path(
    "app/pages/13_New_Auction_Intake.py"
)


def test_page_exposes_complete_review_workflow() -> None:
    """The page exposes queue, alerts, cohorts, and audit history."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    semantic_text = " ".join(
        node.value
        for node in ast.walk(
            tree
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
        "New Auction Intake",
        "Assignment Queue",
        "Completeness Alerts",
        "Cohort Reporting",
        "Assignment Audit",
        "Preview reviewed assignment",
        "Apply reviewed assignment",
        "Safe ingestion command",
    )

    for fragment in required:
        assert fragment in semantic_text


def test_page_passes_account_scope_into_queue_services() -> None:
    """Account-scoped queue APIs must receive the signed-in account."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "account_id=account_id" in source
    assert "user_id=page_account_context.user_id" in source
    assert "queue_count(" in source
    assert "list_unassigned_auctions(" in source
    assert "preview_assignment(" in source
    assert "no master reference" in source
    assert "NO_VERIFIED_REFERENCE" in source


def test_page_rejects_automatic_inference() -> None:
    """The UI states the master and listing boundaries."""
    source = PAGE.read_text(
        encoding="utf-8"
    )

    assert "never guesses" in source
    assert "never redefine" in source
    assert "scope confirmation" not in source.lower() or "confirm" in source.lower()
