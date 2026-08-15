"""Regression tests for user-facing application navigation."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from app.navigation import NAVIGATION_SECTIONS


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[
    1
]

ENTRYPOINT = (
    REPOSITORY_ROOT
    / "app"
    / "collector_review.py"
)

PAGES_DIRECTORY = (
    REPOSITORY_ROOT
    / "app"
    / "pages"
)

NAVIGATION_MODULE = (
    REPOSITORY_ROOT
    / "app"
    / "navigation.py"
)

HOME_PAGE = (
    PAGES_DIRECTORY
    / "1_Home.py"
)

CONFIG = (
    REPOSITORY_ROOT
    / ".streamlit"
    / "config.toml"
)

EXPECTED_PATHS = {
    "collector_review.py",
    "pages/1_Home.py",
    "pages/2_Completeness_Reference.py",
    "pages/2_Pressing_Analytics.py",
    "pages/3_Evidence_and_Bulk_Observations.py",
    "pages/3_Latest_Auction_Refresh.py",
    "pages/4_Reference_Record_Admin.py",
    "pages/5_Normalization_Readiness.py",
    "pages/6_Deterministic_Verdict_Rules.py",
    "pages/7_Normalization_Workbench.py",
    "pages/8_Cohort_Curation_Wizard.py",
    "pages/9_Evidence_Intake.py",
    "pages/10_Listing_Completeness_Review.py",
    "pages/11_Media_Profile_Admin.py",
    "pages/12_Completeness_History.py",
    "pages/13_New_Auction_Intake.py",
    "pages/14_Pressing_Reference_Catalog.py",
    "pages/15_Ingest_New_Auctions.py",
}

ADVANCED_PAGE_NAMES = {
    "4_Reference_Record_Admin.py",
    "6_Deterministic_Verdict_Rules.py",
    "7_Normalization_Workbench.py",
    "8_Cohort_Curation_Wizard.py",
    "11_Media_Profile_Admin.py",
}


def navigation_items():
    """Return all configured navigation items."""

    return [
        item
        for section in NAVIGATION_SECTIONS
        for item in section.items
    ]


def test_navigation_covers_every_application_page_once() -> None:
    """Expose every application destination exactly once."""

    items = navigation_items()

    paths = [
        item.path
        for item in items
    ]

    assert len(
        paths
    ) == len(
        set(
            paths
        )
    )

    assert set(
        paths
    ) == EXPECTED_PATHS


def test_navigation_labels_are_plain_language() -> None:
    """Keep developer terminology out of primary navigation labels."""

    labels = {
        item.path:
            item.label
        for item in navigation_items()
    }

    assert labels[
        "pages/1_Home.py"
    ] == "Home"

    assert labels[
        "collector_review.py"
    ] == "Review Marketplace Sales"

    assert labels[
        "pages/5_Normalization_Readiness.py"
    ] == "Data Quality & Readiness"

    assert labels[
        "pages/3_Latest_Auction_Refresh.py"
    ] == "Refresh History & Exports"

    assert labels[
        "pages/14_Pressing_Reference_Catalog.py"
    ] == "Manage Pressings"

    assert labels[
        "pages/3_Evidence_and_Bulk_Observations.py"
    ] == "Review Evidence in Bulk"

    assert labels[
        "pages/11_Media_Profile_Admin.py"
    ] == "Media Rules & Defaults"

    assert labels[
        "pages/4_Reference_Record_Admin.py"
    ] == "Advanced Record Maintenance"

    forbidden_terms = (
        "Admin",
        "Workbench",
        "Deterministic",
        "Intake",
        "Curation Wizard",
    )

    for item in navigation_items():
        assert item.label.strip()
        assert item.help_text.strip()
        assert "_" not in item.label

        for forbidden in forbidden_terms:
            assert (
                forbidden
                not in item.label
            )


def test_navigation_has_clear_user_intent_sections() -> None:
    """Group destinations by what the user is trying to do."""

    titles = [
        section.title
        for section
        in NAVIGATION_SECTIONS
    ]

    assert titles == [
        "Everyday work",
        "Analysis & reports",
        "Pressing library",
        "Advanced tools",
    ]

    for section in NAVIGATION_SECTIONS:
        assert section.description.strip()
        assert section.items


def test_sidebar_is_compact_and_advanced_tools_are_secondary() -> None:
    """Keep explanatory prose on Home rather than filling the sidebar."""

    source = NAVIGATION_MODULE.read_text(
        encoding="utf-8",
    )

    assert (
        "section.description"
        not in source
    )

    assert (
        '"Advanced tools"'
        in source
    )

    assert (
        "expanded=expand_advanced"
        in source
    )

    assert (
        "Review sales, refresh data, and manage pressings."
        in source
    )


def test_advanced_pages_expand_the_advanced_navigation_group() -> None:
    """Keep the current advanced destination visible when it is active."""

    for page_name in ADVANCED_PAGE_NAMES:
        source = (
            PAGES_DIRECTORY
            / page_name
        ).read_text(
            encoding="utf-8",
        )

        assert (
            "render_navigation("
            "expand_advanced=True"
            ")"
            in source
        )


def test_home_page_explains_the_workspace_and_primary_workflow() -> None:
    """Give new users a clear start-here destination."""

    source = HOME_PAGE.read_text(
        encoding="utf-8",
    )

    required = (
        "What would you like to do?",
        "What this workspace does",
        "Recommended workflow",
        "Browse every tool",
        "Review marketplace sales",
        "Refresh marketplace sales",
        "Review new auctions",
        "Manage pressings",
        "Collect",
        "Review",
        "Organize",
        "Analyze",
    )

    missing = [
        value
        for value in required
        if value not in source
    ]

    assert not missing, (
        "Missing Home-page UX contracts: "
        + ", ".join(
            missing
        )
    )


def test_primary_review_page_matches_navigation_wording() -> None:
    """Keep the main review page title aligned with the sidebar."""

    source = ENTRYPOINT.read_text(
        encoding="utf-8",
    )

    assert (
        'page_title="Review Marketplace Sales"'
        in source
    )

    assert (
        '"🔎 Review Marketplace Sales"'
        in source
    )


def test_default_streamlit_page_list_is_hidden() -> None:
    """Prevent developer-oriented filenames from appearing."""

    configuration = tomllib.loads(
        CONFIG.read_text(
            encoding="utf-8",
        )
    )

    assert (
        configuration[
            "client"
        ][
            "showSidebarNavigation"
        ]
        is False
    )


def test_every_page_renders_shared_navigation() -> None:
    """Render the same shared navigation across the application."""

    scripts = [
        ENTRYPOINT,
        *sorted(
            PAGES_DIRECTORY.glob(
                "*.py"
            )
        ),
    ]

    assert len(
        scripts
    ) == len(
        EXPECTED_PATHS
    )

    for path in scripts:
        source = path.read_text(
            encoding="utf-8",
        )

        assert (
            "from app.navigation "
            "import "
            in source
        )

        assert (
            "render_navigation"
            in source
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
