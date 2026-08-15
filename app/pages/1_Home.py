"""Home page for the auction workspace."""

from __future__ import annotations

import streamlit as st

from app.navigation import NAVIGATION_SECTIONS, render_navigation


def render_action_card(
    *,
    title: str,
    icon: str,
    description: str,
    path: str,
    action_label: str,
) -> None:
    """Render one prominent starting action."""

    with st.container(
        border=True
    ):
        st.markdown(
            f"### {icon} {title}"
        )
        st.write(
            description
        )
        st.page_link(
            path,
            label=action_label,
            width="stretch",
        )


st.set_page_config(
    page_title="Auction Workspace",
    page_icon="🏠",
    layout="wide",
)

render_navigation()

st.title(
    "🏠 Auction workspace"
)

st.write(
    "Keep marketplace sales current, review new listings, maintain "
    "physical pressing records, and analyze sale history from one place."
)

st.subheader(
    "What would you like to do?"
)

left_column, right_column = st.columns(
    2
)

with left_column:
    render_action_card(
        title="Review marketplace sales",
        icon="🔎",
        description=(
            "Search eBay, Buyee, and Gripsweat sales, inspect listing "
            "details, and review pressing information."
        ),
        path="collector_review.py",
        action_label="Open sales review",
    )

    render_action_card(
        title="Review new auctions",
        icon="📥",
        description=(
            "Work through newly collected listings and connect each one "
            "to the correct physical pressing."
        ),
        path="pages/13_New_Auction_Intake.py",
        action_label="Open new-auction review",
    )

with right_column:
    render_action_card(
        title="Refresh marketplace sales",
        icon="🔄",
        description=(
            "Check all configured marketplaces for the latest available "
            "sales and process the refreshed data."
        ),
        path="pages/15_Ingest_New_Auctions.py",
        action_label="Open marketplace refresh",
    )

    render_action_card(
        title="Manage pressings",
        icon="💿",
        description=(
            "Create or update physical pressing identities, catalog "
            "numbers, labels, matrices, countries, and release years."
        ),
        path="pages/14_Pressing_Reference_Catalog.py",
        action_label="Open pressing library",
    )

st.divider()

st.subheader(
    "What this workspace does"
)

workflow_columns = st.columns(
    4
)

with workflow_columns[0]:
    st.markdown(
        "### 1. 🔄 Collect"
    )
    st.write(
        "Refresh available marketplace sales from eBay, Buyee, "
        "and Gripsweat."
    )

with workflow_columns[1]:
    st.markdown(
        "### 2. 🔎 Review"
    )
    st.write(
        "Inspect incoming and historical listings and correct "
        "important sale details."
    )

with workflow_columns[2]:
    st.markdown(
        "### 3. 💿 Organize"
    )
    st.write(
        "Connect listings to exact physical pressings and maintain "
        "their expected contents and evidence."
    )

with workflow_columns[3]:
    st.markdown(
        "### 4. 📈 Analyze"
    )
    st.write(
        "Compare sale history, pressing performance, completeness, "
        "and data readiness."
    )

st.divider()

st.subheader(
    "Recommended workflow"
)

st.markdown(
    """
**1. Refresh marketplace sales** when you want to check for new data.

**2. Review new auctions** when newly collected listings need a pressing assignment.

**3. Manage pressings and evidence** when a physical release needs clearer identity
or completeness information.

**4. Review marketplace sales and analytics** when you want to compare prices,
condition, completeness, or pressing performance.
"""
)

with st.expander(
    "Browse every tool",
    expanded=False,
):
    st.caption(
        "Every destination is listed here with a plain-language explanation."
    )

    for section in NAVIGATION_SECTIONS:
        st.markdown(
            f"### {section.title}"
        )
        st.write(
            section.description
        )

        for item in section.items:
            if item.path == "pages/1_Home.py":
                continue

            st.page_link(
                item.path,
                label=item.label,
                icon=item.icon,
                help=item.help_text,
                width="stretch",
            )
