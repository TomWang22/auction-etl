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

CONFIG = (
    REPOSITORY_ROOT
    / ".streamlit"
    / "config.toml"
)

EXPECTED_PATHS = {
    "collector_review.py",
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


def navigation_items():
    """Return all configured navigation items."""

    return [
        item
        for section in NAVIGATION_SECTIONS
        for item in section.items
    ]


def test_navigation_covers_every_application_page_once() -> None:
    """Expose every existing page exactly once."""

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


def test_navigation_labels_are_user_facing() -> None:
    """Keep internal implementation terminology out of primary labels."""

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


def test_navigation_has_clear_sections() -> None:
    """Keep the sidebar organized by user intent."""

    titles = [
        section.title
        for section
        in NAVIGATION_SECTIONS
    ]

    assert titles == [
        "Daily work",
        "Insights",
        "Pressing library",
        "Advanced setup",
    ]

    for section in NAVIGATION_SECTIONS:
        assert section.description.strip()
        assert section.items


def test_default_streamlit_page_list_is_hidden() -> None:
    """Prevent the developer-oriented filename list from appearing."""

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
    """Render the same navigation before page-specific sidebar controls."""

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
            "import render_navigation"
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
