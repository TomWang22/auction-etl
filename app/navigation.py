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
        title="Daily work",
        description=(
            "Review sales, update marketplace data, "
            "and handle newly collected listings."
        ),
        items=(
            NavigationItem(
                label="Auction Review",
                path="collector_review.py",
                icon="🔎",
                help_text=(
                    "Browse marketplace sales, filter listings, "
                    "and review collector details."
                ),
            ),
            NavigationItem(
                label="Refresh Marketplace Sales",
                path="pages/15_Ingest_New_Auctions.py",
                icon="🔄",
                help_text=(
                    "Bring in the latest available eBay, Buyee, "
                    "and Gripsweat sales and process them."
                ),
            ),
            NavigationItem(
                label="Review New Auctions",
                path="pages/13_New_Auction_Intake.py",
                icon="📥",
                help_text=(
                    "Review newly collected auction listings and "
                    "assign them to the correct physical pressing."
                ),
            ),
            NavigationItem(
                label="Check Listing Completeness",
                path="pages/10_Listing_Completeness_Review.py",
                icon="✅",
                help_text=(
                    "Compare one auction copy with the expected "
                    "contents of its assigned pressing."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Insights",
        description=(
            "Understand prices, data quality, history, "
            "and recent refresh results."
        ),
        items=(
            NavigationItem(
                label="Sales by Pressing",
                path="pages/2_Pressing_Analytics.py",
                icon="📈",
                help_text=(
                    "Analyze completed sales for exact catalog "
                    "numbers and physical pressings."
                ),
            ),
            NavigationItem(
                label="Data Readiness",
                path="pages/5_Normalization_Readiness.py",
                icon="📊",
                help_text=(
                    "See which listings have enough reviewed data "
                    "for reliable comparison and analysis."
                ),
            ),
            NavigationItem(
                label="Completeness History",
                path="pages/12_Completeness_History.py",
                icon="🕘",
                help_text=(
                    "Review historical completeness snapshots and "
                    "how a pressing assessment changed over time."
                ),
            ),
            NavigationItem(
                label="Refresh Reports & Exports",
                path="pages/3_Latest_Auction_Refresh.py",
                icon="📄",
                help_text=(
                    "Inspect recent ingestion results and create "
                    "formatted reports or exports. Use Refresh "
                    "Marketplace Sales for the normal refresh flow."
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
                label="Pressing Catalog",
                path="pages/14_Pressing_Reference_Catalog.py",
                icon="💿",
                help_text=(
                    "Create or edit physical pressing identities such "
                    "as catalog number, label, matrix, country, and year."
                ),
            ),
            NavigationItem(
                label="Edit Pressing Contents",
                path="pages/2_Completeness_Reference.py",
                icon="📦",
                help_text=(
                    "Define the expected components and quantities "
                    "for an exact physical pressing."
                ),
            ),
            NavigationItem(
                label="Add Pressing Evidence",
                path="pages/9_Evidence_Intake.py",
                icon="📚",
                help_text=(
                    "Stage reviewed source evidence supporting "
                    "pressing identity and completeness claims."
                ),
            ),
            NavigationItem(
                label="Evidence Sources & Bulk Review",
                path="pages/3_Evidence_and_Bulk_Observations.py",
                icon="🧾",
                help_text=(
                    "Manage evidence sources and review multiple "
                    "listing observations together."
                ),
            ),
        ),
    ),
    NavigationSection(
        title="Advanced setup",
        description=(
            "Less frequent tools for structured cleanup, rules, "
            "profiles, and audited reference maintenance."
        ),
        items=(
            NavigationItem(
                label="Guided Pressing Workflow",
                path="pages/8_Cohort_Curation_Wizard.py",
                icon="🧭",
                help_text=(
                    "Work through pressing identity, evidence, "
                    "completeness, condition, comparables, and "
                    "readiness in one guided workflow."
                ),
            ),
            NavigationItem(
                label="Normalize & Clean Data",
                path="pages/7_Normalization_Workbench.py",
                icon="🧹",
                help_text=(
                    "Resolve prioritized data-cleanup tasks, "
                    "normalization values, and comparable decisions."
                ),
            ),
            NavigationItem(
                label="Scoring Rules",
                path="pages/6_Deterministic_Verdict_Rules.py",
                icon="⚖️",
                help_text=(
                    "Review and maintain the explicit rules used "
                    "to calculate listing and market verdicts."
                ),
            ),
            NavigationItem(
                label="Media Type Setup",
                path="pages/11_Media_Profile_Admin.py",
                icon="🧩",
                help_text=(
                    "Configure expected component behavior for "
                    "LPs, CDs, cassettes, DVDs, and other media."
                ),
            ),
            NavigationItem(
                label="Reference Record Audit",
                path="pages/4_Reference_Record_Admin.py",
                icon="🗃️",
                help_text=(
                    "Maintain low-level reference records, evidence "
                    "attachments, revision history, restores, and "
                    "audited bulk imports."
                ),
            ),
        ),
    ),
)


def render_navigation() -> None:
    """Render the shared user-facing sidebar navigation."""

    with st.sidebar:
        st.markdown(
            "## 💿 Auction workspace"
        )
        st.caption(
            "Choose what you want to do. "
            "Hover over any item for a short explanation."
        )

        for section_index, section in enumerate(
            NAVIGATION_SECTIONS
        ):
            if section_index:
                st.divider()

            st.markdown(
                f"#### {section.title}"
            )
            st.caption(
                section.description
            )

            for item in section.items:
                st.page_link(
                    item.path,
                    label=item.label,
                    icon=item.icon,
                    help=item.help_text,
                    width="stretch",
                )

        st.divider()
