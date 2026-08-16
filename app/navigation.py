"""Shared product-facing navigation for the auction workspace."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """Describe one user-facing application destination."""

    label: str
    path: str
    icon: str
    help_text: str


@dataclass(frozen=True, slots=True)
class NavigationSection:
    """Group related destinations by user intent."""

    title: str
    description: str
    items: tuple[NavigationItem, ...]
    collapsed: bool = True


NAVIGATION_SECTIONS = (
    NavigationSection(
        title="Everyday work",
        description=(
            "The normal workflow for reviewing sales, refreshing data, "
            "and handling newly collected listings."
        ),
        collapsed=False,
        items=(
            NavigationItem(
                label="Home",
                path="pages/1_Home.py",
                icon="🏠",
                help_text="Start here and choose the job you want to do.",
            ),
            NavigationItem(
                label="Review marketplace sales",
                path="collector_review.py",
                icon="🔎",
                help_text=(
                    "Search eBay, Buyee, and Gripsweat sales and inspect "
                    "listing and pressing details."
                ),
            ),
            NavigationItem(
                label="Refresh marketplace sales",
                path="pages/15_Ingest_New_Auctions.py",
                icon="🔄",
                help_text=(
                    "Check configured marketplaces for the latest available "
                    "sales and process the refreshed data."
                ),
            ),
            NavigationItem(
                label="Artists to track",
                path="pages/16_Artists_to_Track.py",
                icon="🎵",
                help_text=(
                    "See which artists marketplace refreshes "
                    "currently search for and open those searches."
                ),
            ),
            NavigationItem(
                label="Match new listings",
                path="pages/13_New_Auction_Intake.py",
                icon="📥",
                help_text=(
                    "Review newly collected listings and connect each one "
                    "to the correct physical pressing."
                ),
            ),
            NavigationItem(
                label="Check listing completeness",
                path="pages/10_Listing_Completeness_Review.py",
                icon="✅",
                help_text=(
                    "Compare one auction copy with the expected contents "
                    "of its assigned pressing."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Analysis & reports",
        description=(
            "Sale history, pricing, data quality, and previous refresh results."
        ),
        items=(
            NavigationItem(
                label="Sales by pressing",
                path="pages/2_Pressing_Analytics.py",
                icon="📈",
                help_text=(
                    "Analyze completed sales for exact catalog numbers "
                    "and physical pressings."
                ),
            ),
            NavigationItem(
                label="Data quality & readiness",
                path="pages/5_Normalization_Readiness.py",
                icon="📊",
                help_text=(
                    "See which listings contain enough reviewed data "
                    "for reliable comparisons."
                ),
            ),
            NavigationItem(
                label="Completeness history",
                path="pages/12_Completeness_History.py",
                icon="🕘",
                help_text=(
                    "Review historical completeness snapshots and how "
                    "pressing assessments changed over time."
                ),
            ),
            NavigationItem(
                label="Refresh history & exports",
                path="pages/3_Latest_Auction_Refresh.py",
                icon="📄",
                help_text=(
                    "Inspect previous refresh results and create reports "
                    "or exports."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Pressing library",
        description=(
            "Physical pressing identities, expected contents, "
            "and supporting evidence."
        ),
        items=(
            NavigationItem(
                label="Manage pressings",
                path="pages/14_Pressing_Reference_Catalog.py",
                icon="💿",
                help_text=(
                    "Create or update pressing identities, catalog numbers, "
                    "labels, matrices, countries, and years."
                ),
            ),
            NavigationItem(
                label="Edit pressing contents",
                path="pages/2_Completeness_Reference.py",
                icon="📦",
                help_text=(
                    "Define the components and quantities expected for "
                    "an exact physical pressing."
                ),
            ),
            NavigationItem(
                label="Add pressing evidence",
                path="pages/9_Evidence_Intake.py",
                icon="📚",
                help_text=(
                    "Add reviewed evidence supporting pressing identity "
                    "or completeness claims."
                ),
            ),
            NavigationItem(
                label="Review evidence in bulk",
                path="pages/3_Evidence_and_Bulk_Observations.py",
                icon="🧾",
                help_text=(
                    "Manage evidence sources and review multiple listing "
                    "observations together."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Advanced tools",
        description=(
            "Less frequently used configuration, cleanup, and audited "
            "reference-maintenance tools."
        ),
        items=(
            NavigationItem(
                label="Guided pressing workflow",
                path="pages/8_Cohort_Curation_Wizard.py",
                icon="🧭",
                help_text=(
                    "Work through pressing identity, evidence, completeness, "
                    "condition, comparables, and readiness."
                ),
            ),
            NavigationItem(
                label="Normalize & clean data",
                path="pages/7_Normalization_Workbench.py",
                icon="🧹",
                help_text=(
                    "Resolve structured cleanup, normalization, "
                    "and comparable-data decisions."
                ),
            ),
            NavigationItem(
                label="Scoring rules",
                path="pages/6_Deterministic_Verdict_Rules.py",
                icon="⚖️",
                help_text=(
                    "Review the explicit rules used to calculate listing "
                    "and market verdicts."
                ),
            ),
            NavigationItem(
                label="Media rules & defaults",
                path="pages/11_Media_Profile_Admin.py",
                icon="🧩",
                help_text=(
                    "Configure expected component behavior for LPs, CDs, "
                    "cassettes, DVDs, and other media."
                ),
            ),
            NavigationItem(
                label="Advanced record maintenance",
                path="pages/4_Reference_Record_Admin.py",
                icon="🗃️",
                help_text=(
                    "Maintain low-level reference records, revision history, "
                    "restores, and audited bulk imports."
                ),
            ),
        ),
    ),
)


def _section_contains(
    section: NavigationSection,
    current_page: str,
) -> bool:
    """Return whether a navigation section contains the current page."""

    return any(
        item.path == current_page
        for item in section.items
    )


def _render_items(
    items: tuple[NavigationItem, ...],
) -> None:
    """Render one group of page destinations."""

    for item in items:
        st.page_link(
            item.path,
            label=item.label,
            icon=item.icon,
            help=item.help_text,
            width="stretch",
        )


def render_navigation(
    *,
    current_page: str,
) -> None:
    """Render compact navigation with progressive disclosure."""

    with st.sidebar:
        st.markdown("## 💿 Auction workspace")
        st.caption(
            "Review sales, refresh data, and manage pressings."
        )

        everyday = NAVIGATION_SECTIONS[0]

        st.markdown(
            f"#### {everyday.title}"
        )
        _render_items(
            everyday.items
        )

        for section in NAVIGATION_SECTIONS[1:]:
            expanded = _section_contains(
                section,
                current_page,
            )

            with st.expander(
                section.title,
                expanded=expanded,
            ):
                _render_items(
                    section.items
                )
