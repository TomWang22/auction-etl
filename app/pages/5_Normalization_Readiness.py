"""Deterministic normalization-readiness dashboard."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.normalization_readiness import (
    get_readiness,
    list_readiness,
    readiness_summary,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Normalization Readiness",
    page_icon="📊",
    layout="wide",
)
render_navigation(current_page="pages/5_Normalization_Readiness.py")


@st.cache_resource
def _engine() -> Engine:
    """Create the shared PostgreSQL engine."""
    database_url = os.environ.get(
        "DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required."
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def _percentage(
    value: Decimal | None,
) -> str:
    """Format a deterministic ratio."""
    if value is None:
        return "Unavailable"

    return f"{value * Decimal('100'):.1f}%"


def _listing_label(
    row: dict[str, Any],
) -> str:
    """Build one listing label."""
    title = (
        row.get("title")
        or "Untitled listing"
    )

    return (
        f"{row['marketplace']}/"
        f"{row['listing_id']} · "
        f"{title}"
    )


def main() -> None:
    """Render normalization readiness for every listing."""
    st.title("📊 Normalization Readiness")

    st.caption(
        "A deterministic view of pressing assignment, "
        "shared completeness references, observed components, "
        "condition normalization, selected price basis, and "
        "eligible exact-pressing comparables."
    )

    st.info(
        "Structural completeness is calculated from required "
        "component quantities. Readiness percentages represent "
        "satisfied data gates, not subjective collector judgment."
    )

    engine = _engine()

    search = st.text_input(
        "Search title, artist, catalog number, marketplace, or listing ID",
    )

    minimum_comparables = st.number_input(
        "Minimum eligible exact-pressing comparables",
        min_value=1,
        max_value=100,
        value=3,
        step=1,
    )

    rows = list_readiness(
        engine,
        search=search,
        minimum_comparables=
            int(minimum_comparables),
        limit=2000,
    )

    summary = readiness_summary(
        rows
    )

    metrics = st.columns(7)

    metrics[0].metric(
        "Listings",
        summary["total"],
    )
    metrics[1].metric(
        "Ready",
        summary["ready"],
    )
    metrics[2].metric(
        "Blocked",
        summary["blocked"],
    )
    metrics[3].metric(
        "Pressing assigned",
        summary["pressing_assigned"],
    )
    metrics[4].metric(
        "Reference configured",
        summary["reference_configured"],
    )
    metrics[5].metric(
        "Condition normalized",
        summary["condition_normalized"],
    )
    metrics[6].metric(
        "Completeness normalized",
        summary[
            "completeness_normalized"
        ],
    )

    status_filter = st.multiselect(
        "Readiness status",
        options=[
            "READY",
            "BLOCKED",
        ],
        default=[
            "READY",
            "BLOCKED",
        ],
    )

    filtered = [
        row
        for row in rows
        if row["readiness_status"]
        in status_filter
    ]

    display_rows = []

    for row in filtered:
        display_rows.append(
            {
                "marketplace":
                    row["marketplace"],
                "listing_id":
                    row["listing_id"],
                "title":
                    row["title"],
                "catalog_number":
                    row["catalog_number"],
                "media_type":
                    row["media_type"],
                "pressing_id":
                    row["pressing_id"],
                "reference_status":
                    row["reference_status"],
                "structural_completeness":
                    row[
                        "completeness_status"
                    ],
                "completeness_ratio":
                    row[
                        "completeness_ratio"
                    ],
                "raw_comparables":
                    row[
                        "raw_comparable_count"
                    ],
                "eligible_comparables":
                    row[
                        "eligible_comparable_count"
                    ],
                "readiness_gate_ratio":
                    row[
                        "readiness_gate_ratio"
                    ],
                "readiness_status":
                    row[
                        "readiness_status"
                    ],
                "blocker_count":
                    len(
                        row["blockers"]
                    ),
            }
        )

    st.dataframe(
        pd.DataFrame(display_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "completeness_ratio":
                st.column_config.ProgressColumn(
                    "Structural completeness",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.1%%",
                ),
            "readiness_gate_ratio":
                st.column_config.ProgressColumn(
                    "Readiness gates",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.1%%",
                ),
        },
    )

    if not filtered:
        st.info(
            "No listing matches the current filters."
        )
        return

    selected_key = st.selectbox(
        "Listing detail",
        options=[
            (
                row["marketplace"],
                row["listing_id"],
            )
            for row in filtered
        ],
        format_func=lambda value: (
            _listing_label(
                next(
                    row
                    for row in filtered
                    if (
                        row[
                            "marketplace"
                        ],
                        row[
                            "listing_id"
                        ],
                    ) == value
                )
            )
        ),
    )

    detail = get_readiness(
        engine,
        selected_key[0],
        selected_key[1],
        minimum_comparables=
            int(minimum_comparables),
    )

    st.subheader(
        "Deterministic readiness detail"
    )

    detail_metrics = st.columns(6)

    detail_metrics[0].metric(
        "Readiness",
        detail[
            "readiness_status"
        ],
    )
    detail_metrics[1].metric(
        "Readiness gates",
        _percentage(
            detail[
                "readiness_gate_ratio"
            ]
        ),
    )
    detail_metrics[2].metric(
        "Reference",
        detail[
            "reference_status"
        ],
    )
    detail_metrics[3].metric(
        "Structural completeness",
        detail[
            "completeness_status"
        ]
        or "Unavailable",
    )
    detail_metrics[4].metric(
        "Raw comparables",
        detail[
            "raw_comparable_count"
        ],
    )
    detail_metrics[5].metric(
        "Eligible comparables",
        detail[
            "eligible_comparable_count"
        ],
    )

    left, right = st.columns(2)

    with left:
        st.markdown(
            "#### Component calculation"
        )

        st.write(
            {
                "required_component_count":
                    detail[
                        "required_component_count"
                    ],
                "present_required_component_count":
                    detail[
                        "present_required_component_count"
                    ],
                "missing_components":
                    detail[
                        "missing_components"
                    ],
                "unverified_components":
                    detail[
                        "unverified_components"
                    ],
                "unexpected_components":
                    detail[
                        "unexpected_components"
                    ],
                "completeness_ratio":
                    detail[
                        "completeness_ratio"
                    ],
                "complete":
                    detail["complete"],
            }
        )

    with right:
        st.markdown(
            "#### Normalization factors"
        )

        st.write(
            {
                "selected_price_usd":
                    detail[
                        "selected_price_usd"
                    ],
                "condition_market_factor":
                    detail[
                        "condition_market_factor"
                    ],
                "completeness_market_factor":
                    detail[
                        "completeness_market_factor"
                    ],
                "database_normalization_ready":
                    detail[
                        "normalization_ready"
                    ],
            }
        )

    st.markdown(
        "#### Explicit blockers"
    )

    if detail["blockers"]:
        for blocker in detail[
            "blockers"
        ]:
            st.warning(blocker)
    else:
        st.success(
            "All deterministic readiness gates are satisfied."
        )


main()
