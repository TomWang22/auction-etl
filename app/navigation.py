"""User-facing navigation for the auction review application."""

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
    """Group related application destinations."""

    title: str
    description: str
    items: tuple[NavigationItem, ...]


NAVIGATION_SECTIONS = (
    NavigationSection(
        title="Everyday work",
        description=(
            "Start here for the normal workflow: review sales, "
            "refresh marketplace data, and handle new listings."
        ),
        items=(
            NavigationItem(
                label="Home",
                path="pages/1_Home.py",
                icon="🏠",
                help_text=(
                    "See what the workspace does, where to start, "
                    "and how the main tools fit together."
                ),
            ),
            NavigationItem(
                label="Review Marketplace Sales",
                path="collector_review.py",
                icon="🔎",
                help_text=(
                    "Browse marketplace sales, filter listings, "
                    "and review collector and pressing details."
                ),
            ),
            NavigationItem(
                label="Refresh Marketplace Sales",
                path="pages/15_Ingest_New_Auctions.py",
                icon="🔄",
                help_text=(
                    "Check eBay, Buyee, and Gripsweat for the latest "
                    "available sales and update the local data."
                ),
            ),
            NavigationItem(
                label="Review New Auctions",
                path="pages/13_New_Auction_Intake.py",
                icon="📥",
                help_text=(
                    "Review newly collected listings and connect them "
                    "to the correct physical pressing."
                ),
            ),
            NavigationItem(
                label="Check Listing Completeness",
                path="pages/10_Listing_Completeness_Review.py",
                icon="✅",
                help_text=(
                    "Compare a sale copy with the contents expected "
                    "for its assigned pressing."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Analysis & reports",
        description=(
            "Understand sale prices, data quality, historical changes, "
            "and previous refresh results."
        ),
        items=(
            NavigationItem(
                label="Sales by Pressing",
                path="pages/2_Pressing_Analytics.py",
                icon="📈",
                help_text=(
                    "Analyze completed sales for exact catalog numbers "
                    "and physical pressings."
                ),
            ),
            NavigationItem(
                label="Data Quality & Readiness",
                path="pages/5_Normalization_Readiness.py",
                icon="📊",
                help_text=(
                    "See which listings have enough reviewed information "
                    "for reliable comparison and analysis."
                ),
            ),
            NavigationItem(
                label="Completeness History",
                path="pages/12_Completeness_History.py",
                icon="🕘",
                help_text=(
                    "Review historical completeness assessments and "
                    "see how they changed over time."
                ),
            ),
            NavigationItem(
                label="Refresh History & Exports",
                path="pages/3_Latest_Auction_Refresh.py",
                icon="📄",
                help_text=(
                    "Inspect previous refresh results and create reports "
                    "or exports. Use Refresh Marketplace Sales to run "
                    "a new refresh."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Pressing library",
        description=(
            "Maintain physical release identities, expected contents, "
            "and supporting evidence."
        ),
        items=(
            NavigationItem(
                label="Manage Pressings",
                path="pages/14_Pressing_Reference_Catalog.py",
                icon="💿",
                help_text=(
                    "Create or edit pressing identities such as catalog "
                    "number, label, matrix, country, and year."
                ),
            ),
            NavigationItem(
                label="Edit Pressing Contents",
                path="pages/2_Completeness_Reference.py",
                icon="📦",
                help_text=(
                    "Define the components and quantities expected "
                    "for an exact physical pressing."
                ),
            ),
            NavigationItem(
                label="Add Pressing Evidence",
                path="pages/9_Evidence_Intake.py",
                icon="📚",
                help_text=(
                    "Add reviewed source evidence that supports pressing "
                    "identity and completeness claims."
                ),
            ),
            NavigationItem(
                label="Review Evidence in Bulk",
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
            "Less frequently used tools for structured cleanup, rules, "
            "profiles, and audited reference maintenance."
        ),
        items=(
            NavigationItem(
                label="Guided Pressing Workflow",
                path="pages/8_Cohort_Curation_Wizard.py",
                icon="🧭",
                help_text=(
                    "Work through pressing identity, evidence, completeness, "
                    "condition, comparables, and readiness step by step."
                ),
            ),
            NavigationItem(
                label="Normalize & Clean Data",
                path="pages/7_Normalization_Workbench.py",
                icon="🧹",
                help_text=(
                    "Resolve prioritized cleanup tasks, normalized values, "
                    "and comparable decisions."
                ),
            ),
            NavigationItem(
                label="Scoring Rules",
                path="pages/6_Deterministic_Verdict_Rules.py",
                icon="⚖️",
                help_text=(
                    "Review the explicit rules used to calculate listing "
                    "and market verdicts."
                ),
            ),
            NavigationItem(
                label="Media Rules & Defaults",
                path="pages/11_Media_Profile_Admin.py",
                icon="🧩",
                help_text=(
                    "Configure expected component behavior for LPs, CDs, "
                    "cassettes, DVDs, and other media."
                ),
            ),
            NavigationItem(
                label="Advanced Record Maintenance",
                path="pages/4_Reference_Record_Admin.py",
                icon="🗃️",
                help_text=(
                    "Maintain low-level reference records, evidence links, "
                    "revision history, restores, and audited bulk imports."
                ),
            ),
        ),
    ),
)


def render_navigation_item(
    item: NavigationItem,
) -> None:
    """Render one sidebar destination."""

    st.page_link(
        item.path,
        label=item.label,
        icon=item.icon,
        help=item.help_text,
        width="stretch",
    )


def render_navigation(
    *,
    expand_advanced: bool = False,
) -> None:
    """Render compact shared user-facing sidebar navigation."""

    with st.sidebar:
        st.markdown(
            "## 💿 Auction workspace"
        )
        st.caption(
            "Review sales, refresh data, and manage pressings."
        )

        for section in NAVIGATION_SECTIONS:
            if section.title == "Advanced tools":
                with st.expander(
                    "Advanced tools",
                    expanded=expand_advanced,
                ):
                    for item in section.items:
                        render_navigation_item(
                            item
                        )

                continue

            st.markdown(
                f"**{section.title}**"
            )

            for item in section.items:
                render_navigation_item(
                    item
                )
