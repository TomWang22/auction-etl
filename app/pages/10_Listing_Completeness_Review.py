"""State-safe auction listing completeness review."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from auction_etl.services.state_safe_completeness import (
    evaluate_listing,
    list_assigned_listings,
)


st.set_page_config(
    page_title="Listing Completeness Review",
    page_icon="✅",
    layout="wide",
)


def _engine():
    """Return the warehouse engine."""
    return create_engine(
        os.environ.get(
            "DATABASE_URL",
            (
                "postgresql+psycopg://auction:auction"
                "@127.0.0.1:5544/auction_warehouse"
            ),
        ),
        pool_pre_ping=True,
        future=True,
    )


def _listing_label(
    row: dict[str, object],
) -> str:
    """Return one listing selector label."""
    return (
        f"{row['marketplace']}/{row['listing_id']} · "
        f"{row['catalog_number']} · "
        f"{row['media_type']} · "
        f"{row['title']}"
    )


def _render_rows(
    title: str,
    rows: tuple[dict[str, object], ...],
) -> None:
    """Render one deterministic detail group."""
    st.subheader(
        title
    )

    if not rows:
        st.info(
            "None."
        )
        return

    st.dataframe(
        pd.DataFrame(
            list(
                rows
            )
        ),
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    """Render the listing completeness page."""
    st.title(
        "Listing Completeness Review"
    )

    st.caption(
        "Compare one auction copy with the authoritative master "
        "reference for its assigned exact pressing."
    )

    st.info(
        "Only REQUIRED master rows participate in component arithmetic. "
        "UNKNOWN and NOT_INCLUDED rows never add required units."
    )

    engine = _engine()

    search = st.text_input(
        "Search assigned listings",
        placeholder=(
            "Marketplace, listing ID, catalog, artist, title, or media type"
        ),
    )

    listings = list_assigned_listings(
        engine,
        search,
    )

    if not listings:
        st.warning(
            "No assigned listing matches the current search."
        )
        return

    listing_map = {
        (
            str(
                row[
                    "marketplace"
                ]
            ),
            str(
                row[
                    "listing_id"
                ]
            ),
        ):
            row
        for row in listings
    }

    selected_identity = st.selectbox(
        "Assigned auction listing",
        options=list(
            listing_map
        ),
        format_func=lambda value:
            _listing_label(
                listing_map[
                    value
                ]
            ),
    )

    selected = listing_map[
        selected_identity
    ]

    result = evaluate_listing(
        engine,
        selected_identity[0],
        selected_identity[1],
    )

    columns = st.columns(
        6
    )

    columns[0].metric(
        "Status",
        result.status,
    )

    columns[1].metric(
        "Pressing",
        result.pressing_id
        or "—",
    )

    columns[2].metric(
        "Media",
        result.media_type
        or "—",
    )

    columns[3].metric(
        "Required units",
        result.required_unit_count,
    )

    columns[4].metric(
        "Verified units",
        result.satisfied_unit_count,
    )

    columns[5].metric(
        "Ratio",
        result.completeness_ratio
        or "—",
    )

    st.write(
        result.explanation
    )

    st.caption(
        "Damage is reported separately from structural completeness. "
        "A structurally complete copy may still have documented damage."
    )

    tabs = st.tabs(
        [
            "Missing",
            "Quantity shortfalls",
            "Unverified",
            "Contradictions",
            "Damage",
            "Evaluation record",
        ]
    )

    with tabs[0]:
        _render_rows(
            "Explicitly missing REQUIRED components",
            result.missing_components,
        )

    with tabs[1]:
        _render_rows(
            "Required quantity shortfalls",
            result.quantity_shortfalls,
        )

    with tabs[2]:
        _render_rows(
            "REQUIRED components lacking decisive observation",
            result.unverified_components,
        )

    with tabs[3]:
        _render_rows(
            "Contradictory listing observations",
            result.contradictory_components,
        )

    with tabs[4]:
        _render_rows(
            "Explicit structured damage observations",
            result.damaged_components,
        )

    with tabs[5]:
        st.json(
            result.to_dict()
        )

    st.caption(
        "Use Collector analytics → Components to add or update "
        "listing-specific observations. Use Completeness Reference "
        "to edit the exact-pressing master."
    )


main()
