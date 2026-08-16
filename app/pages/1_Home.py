"""Product-facing start page for the auction workspace."""

from __future__ import annotations

import streamlit as st

from app.navigation import render_navigation


st.set_page_config(
    page_title="Auction workspace",
    page_icon="🏠",
    layout="wide",
)

render_navigation(
    current_page="pages/1_Home.py"
)


def task_card(
    *,
    icon: str,
    title: str,
    description: str,
    button_label: str,
    destination: str,
    key: str,
) -> None:
    """Render one immediately actionable workspace task."""

    with st.container(
        border=True
    ):
        st.subheader(
            f"{icon} {title}"
        )

        st.write(
            description
        )

        if st.button(
            button_label,
            key=key,
            width="stretch",
        ):
            st.switch_page(
                destination
            )


def workflow_step(
    *,
    number: int,
    icon: str,
    title: str,
    description: str,
) -> None:
    """Render one concise workflow step."""

    st.markdown(
        f"### {number}. {icon} {title}"
    )

    st.write(
        description
    )


st.title(
    "🏠 Auction workspace"
)

st.write(
    "Review marketplace sales, keep your data current, "
    "and connect listings to the correct physical pressings."
)

st.subheader(
    "What do you want to do?"
)

left_top, right_top = st.columns(
    2
)

with left_top:
    task_card(
        icon="🔎",
        title="Review sales",
        description=(
            "Search existing eBay, Buyee, and Gripsweat sales, "
            "inspect listing details, and review pressing information."
        ),
        button_label="Review marketplace sales →",
        destination="collector_review.py",
        key="home-review-marketplace-sales",
    )

with right_top:
    task_card(
        icon="🔄",
        title="Update marketplace data",
        description=(
            "Check all configured marketplaces for the latest available "
            "sales and process the refreshed data."
        ),
        button_label="Refresh marketplace sales →",
        destination="pages/15_Ingest_New_Auctions.py",
        key="home-refresh-marketplace-sales",
    )

left_bottom, right_bottom = st.columns(
    2
)

with left_bottom:
    task_card(
        icon="📥",
        title="Match new listings",
        description=(
            "Work through newly collected listings and connect each one "
            "to the correct physical pressing."
        ),
        button_label="Match new listings →",
        destination="pages/13_New_Auction_Intake.py",
        key="home-match-new-listings",
    )

with right_bottom:
    task_card(
        icon="💿",
        title="Manage pressings",
        description=(
            "Create or update physical pressing identities, catalog "
            "numbers, labels, matrices, countries, and release years."
        ),
        button_label="Manage pressings →",
        destination="pages/14_Pressing_Reference_Catalog.py",
        key="home-manage-pressings",
    )

st.divider()

st.subheader(
    "Typical workflow"
)

step_one, step_two, step_three, step_four = st.columns(
    4
)

with step_one:
    workflow_step(
        number=1,
        icon="🔄",
        title="Refresh",
        description=(
            "Check marketplaces when you want the latest available data."
        ),
    )

with step_two:
    workflow_step(
        number=2,
        icon="📥",
        title="Match",
        description=(
            "Connect newly collected listings to exact physical pressings."
        ),
    )

with step_three:
    workflow_step(
        number=3,
        icon="💿",
        title="Maintain",
        description=(
            "Improve pressing identity, expected contents, and evidence."
        ),
    )

with step_four:
    workflow_step(
        number=4,
        icon="🔎",
        title="Review",
        description=(
            "Compare sale history, condition, completeness, and performance."
        ),
    )

st.caption(
    "You do not need to follow every step every time. "
    "Start with the task you need."
)
