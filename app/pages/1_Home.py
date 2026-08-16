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


TASK_CARD_KEY_PREFIX = "home-task-card-"

TASK_CARD_STYLES = """
<style>
[class*="st-key-home-task-card-"] button {
    position: relative;
    width: 100%;
    min-height: 10.75rem;
    padding: 1.25rem 3.5rem 1.25rem 1.25rem;
    justify-content: flex-start;
    align-items: flex-start;
    text-align: left;
    border-radius: 0.85rem;
    transition:
        transform 120ms ease,
        box-shadow 120ms ease,
        border-color 120ms ease,
        background-color 120ms ease;
}

[class*="st-key-home-task-card-"] button [data-testid="stMarkdownContainer"] {
    width: 100%;
    text-align: left;
}

[class*="st-key-home-task-card-"] button p {
    margin: 0;
    text-align: left;
    white-space: normal;
    font-size: 1rem;
    line-height: 1.5;
    font-weight: 400;
}

[class*="st-key-home-task-card-"] button p strong {
    display: inline-block;
    margin-bottom: 0.7rem;
    font-size: 1.45rem;
    line-height: 1.25;
    font-weight: 700;
}

[class*="st-key-home-task-card-"] button::after {
    content: "→";
    position: absolute;
    top: 1.15rem;
    right: 1.25rem;
    font-size: 1.45rem;
    line-height: 1;
    transition: transform 120ms ease;
}

[class*="st-key-home-task-card-"] button:hover {
    transform: translateY(-2px);
    border-color: currentColor;
    box-shadow: 0 0.5rem 1.25rem rgba(0, 0, 0, 0.08);
}

[class*="st-key-home-task-card-"] button:hover::after {
    transform: translateX(3px);
}

[class*="st-key-home-task-card-"] button:focus-visible {
    outline: 3px solid currentColor;
    outline-offset: 2px;
}

[class*="st-key-home-task-card-"] button:active {
    transform: translateY(0);
    box-shadow: none;
}

@media (prefers-reduced-motion: reduce) {
    [class*="st-key-home-task-card-"] button,
    [class*="st-key-home-task-card-"] button::after {
        transition: none;
    }

    [class*="st-key-home-task-card-"] button:hover,
    [class*="st-key-home-task-card-"] button:hover::after {
        transform: none;
    }
}
</style>
"""


def render_task_card_styles() -> None:
    """Apply the Home task-card interaction treatment."""

    st.markdown(
        TASK_CARD_STYLES,
        unsafe_allow_html=True,
    )


def task_card(
    *,
    icon: str,
    title: str,
    description: str,
    destination: str,
    key: str,
) -> None:
    """Render one primary task as a single clickable surface."""

    if not key.startswith(
        TASK_CARD_KEY_PREFIX
    ):
        raise ValueError(
            "Home task-card keys must start with "
            f"{TASK_CARD_KEY_PREFIX!r}."
        )

    label = (
        f"{icon} **{title}**  \\n"
        f"{description}"
    )

    if st.button(
        label,
        key=key,
        help=f"Open {title}",
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


render_task_card_styles()

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
        destination="collector_review.py",
        key="home-task-card-review-sales",
    )

with right_top:
    task_card(
        icon="🔄",
        title="Update marketplace data",
        description=(
            "Check all configured marketplaces for the latest available "
            "sales and process the refreshed data."
        ),
        destination="pages/15_Ingest_New_Auctions.py",
        key="home-task-card-refresh-marketplace-sales",
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
        destination="pages/13_New_Auction_Intake.py",
        key="home-task-card-match-new-listings",
    )

with right_bottom:
    task_card(
        icon="💿",
        title="Manage pressings",
        description=(
            "Create or update physical pressing identities, catalog "
            "numbers, labels, matrices, countries, and release years."
        ),
        destination="pages/14_Pressing_Reference_Catalog.py",
        key="home-task-card-manage-pressings",
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
