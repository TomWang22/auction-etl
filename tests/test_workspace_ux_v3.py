"""Regression tests for the low-friction workspace UX."""

from __future__ import annotations

import ast
from pathlib import Path

from app.navigation import NAVIGATION_SECTIONS


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[
    1
]

HOME_PAGE = (
    REPOSITORY_ROOT
    / "app"
    / "pages"
    / "1_Home.py"
)

NAVIGATION = (
    REPOSITORY_ROOT
    / "app"
    / "navigation.py"
)


def navigation_items():
    """Return every configured navigation item."""

    return [
        item
        for section in NAVIGATION_SECTIONS
        for item in section.items
    ]


def test_home_is_a_direct_task_launcher() -> None:
    """Keep primary jobs immediately executable from Home."""

    source = HOME_PAGE.read_text(
        encoding="utf-8",
    )

    required = (
        "🏠 Auction workspace",
        "What do you want to do?",
        "Review sales",
        "Update marketplace data",
        "Match new listings",
        "Manage pressings",
        "collector_review.py",
        "pages/15_Ingest_New_Auctions.py",
        "pages/13_New_Auction_Intake.py",
        "pages/14_Pressing_Reference_Catalog.py",
        "home-task-card-review-sales",
        "home-task-card-refresh-marketplace-sales",
        "home-task-card-match-new-listings",
        "home-task-card-manage-pressings",
        "st.button(",
        "st.switch_page(",
        "Typical workflow",
    )

    missing = [
        value
        for value in required
        if value not in source
    ]

    assert not missing, (
        "Missing Home task-launcher contracts: "
        + ", ".join(
            missing
        )
    )



def test_home_does_not_duplicate_the_full_navigation() -> None:
    """Use the sidebar, not Home, as the complete tool directory."""

    source = HOME_PAGE.read_text(
        encoding="utf-8",
    )

    forbidden = (
        "Browse every tool",
        "What this workspace does",
        "Recommended workflow",
    )

    remaining = [
        value
        for value in forbidden
        if value in source
    ]

    assert not remaining


def test_sidebar_uses_progressive_disclosure() -> None:
    """Keep everyday work visible and secondary groups collapsible."""

    source = NAVIGATION.read_text(
        encoding="utf-8",
    )

    required = (
        "everyday = NAVIGATION_SECTIONS[0]",
        "with st.expander(",
        "expanded=expanded",
        "_section_contains(",
    )

    missing = [
        value
        for value in required
        if value not in source
    ]

    assert not missing, (
        "Missing progressive-disclosure contracts: "
        + ", ".join(
            missing
        )
    )


def test_navigation_uses_outcome_oriented_labels() -> None:
    """Keep primary labels task-oriented and sentence-cased."""

    labels = {
        item.label
        for item in navigation_items()
    }

    required = {
        "Home",
        "Review marketplace sales",
        "Refresh marketplace sales",
        "Match new listings",
        "Check listing completeness",
        "Manage pressings",
    }

    assert required <= labels

    forbidden = {
        "Review Marketplace Sales",
        "Refresh Marketplace Sales",
        "Review New Auctions",
    }

    assert labels.isdisjoint(
        forbidden
    )


def test_navigation_routes_are_unique() -> None:
    """Expose every destination once."""

    paths = [
        item.path
        for item in navigation_items()
    ]

    assert len(
        paths
    ) == len(
        set(
            paths
        )
    )

    assert len(
        paths
    ) == 19


def test_every_page_identifies_current_route() -> None:
    """Allow the containing secondary navigation group to auto-expand."""

    scripts = [
        REPOSITORY_ROOT
        / "app"
        / "collector_review.py",
        *sorted(
            (
                REPOSITORY_ROOT
                / "app"
                / "pages"
            ).glob(
                "*.py"
            )
        ),
    ]

    assert len(
        scripts
    ) == 19

    for path in scripts:
        source = path.read_text(
            encoding="utf-8",
        )

        tree = ast.parse(
            source,
            filename=str(
                path
            ),
        )

        calls = [
            node
            for node in ast.walk(
                tree
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "render_navigation"
            )
        ]

        assert len(
            calls
        ) == 1

        call = calls[
            0
        ]

        assert any(
            keyword.arg
            == "current_page"
            for keyword in call.keywords
        )
