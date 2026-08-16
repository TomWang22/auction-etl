"""Immutable exact-pressing completeness history."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from auction_etl.services.completeness_history import (
    current_snapshot,
    engine_from_environment,
    list_assigned_listings,
    list_snapshots,
    list_timeline,
    snapshot_coverage,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Completeness History",
    layout="wide",
)
render_navigation(current_page="pages/12_Completeness_History.py")


@st.cache_resource
def _engine():
    """Return the configured PostgreSQL engine."""
    return engine_from_environment()


def _json_text(value: object) -> str:
    """Render structured fields consistently."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _listing_label(row: dict[str, object]) -> str:
    """Return one professional assignment label."""
    return (
        f"{row['marketplace']}/{row['listing_id']} · "
        f"Pressing #{row['pressing_id']} · "
        f"{row['display_artist']} · "
        f"{row['display_title']} · "
        f"{row['catalog_number']} · "
        f"{row['media_type']}"
    )


def main() -> None:
    """Render the immutable completeness timeline."""
    st.title(
        "Completeness Snapshot History"
    )

    st.caption(
        "Each auction listing is evaluated against its assigned "
        "exact-pressing master reference. Listing observations never "
        "rewrite the master reference."
    )

    st.info(
        "Only REQUIRED master-reference rows enter completeness "
        "arithmetic. UNKNOWN, NOT_INCLUDED, and media-inapplicable "
        "components remain separate states."
    )

    engine = _engine()
    coverage = snapshot_coverage(
        engine
    )

    metric_columns = st.columns(
        3
    )

    metric_columns[0].metric(
        "Assigned listings",
        coverage[
            "assigned_listings"
        ],
    )

    metric_columns[1].metric(
        "Listings with history",
        coverage[
            "listings_with_snapshots"
        ],
    )

    metric_columns[2].metric(
        "Immutable snapshots",
        coverage[
            "snapshot_rows"
        ],
    )

    assignments = list_assigned_listings(
        engine
    )

    if not assignments:
        st.warning(
            "No auction listing is assigned to an exact pressing."
        )
        return

    selected_index = st.selectbox(
        "Assigned auction listing",
        options=range(
            len(
                assignments
            )
        ),
        format_func=lambda index:
            _listing_label(
                assignments[
                    index
                ]
            ),
    )

    selected = assignments[
        int(
            selected_index
        )
    ]

    marketplace = str(
        selected[
            "marketplace"
        ]
    )

    listing_id = str(
        selected[
            "listing_id"
        ]
    )

    latest = current_snapshot(
        engine,
        marketplace,
        listing_id,
    )

    st.subheader(
        "Current derived completeness"
    )

    if latest is None:
        st.warning(
            "No derived completeness snapshot exists for this listing."
        )
    else:
        status_columns = st.columns(
            5
        )

        status_columns[0].metric(
            "Status",
            latest[
                "status"
            ],
        )

        status_columns[1].metric(
            "Required components",
            latest[
                "required_component_count"
            ],
        )

        status_columns[2].metric(
            "Required units",
            latest[
                "required_unit_count"
            ],
        )

        status_columns[3].metric(
            "Verified units",
            latest[
                "verified_present_unit_count"
            ],
        )

        status_columns[4].metric(
            "Missing units",
            latest[
                "missing_required_unit_count"
            ],
        )

        details = {
            "pressing_id":
                latest[
                    "pressing_id"
                ],
            "media_type":
                latest[
                    "media_type"
                ],
            "blocking_reasons":
                latest[
                    "blocking_reasons"
                ],
            "missing_components":
                latest[
                    "missing_components"
                ],
            "trigger_event":
                latest[
                    "trigger_event"
                ],
            "actor":
                latest[
                    "actor"
                ],
            "reason":
                latest[
                    "reason"
                ],
            "created_at":
                latest[
                    "created_at"
                ],
        }

        st.json(
            details
        )

    timeline = list_timeline(
        engine,
        marketplace,
        listing_id,
    )

    st.subheader(
        "Chronological change timeline"
    )

    if not timeline:
        st.info(
            "No timeline event exists for this listing."
        )
    else:
        timeline_rows = []

        for event in timeline:
            timeline_rows.append(
                {
                    "occurred_at":
                        event[
                            "occurred_at"
                        ],
                    "event_type":
                        event[
                            "event_type"
                        ],
                    "status_before":
                        event[
                            "status_before"
                        ],
                    "status_after":
                        event[
                            "status_after"
                        ],
                    "missing_before":
                        event[
                            "previous_missing_required_unit_count"
                        ],
                    "missing_after":
                        event[
                            "missing_required_unit_count"
                        ],
                    "actor":
                        event[
                            "actor"
                        ],
                    "reason":
                        event[
                            "reason"
                        ],
                    "source_fields":
                        _json_text(
                            event[
                                "source_changed_fields"
                            ]
                        ),
                    "completeness_fields":
                        _json_text(
                            event[
                                "completeness_changed_fields"
                            ]
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                timeline_rows
            ),
            use_container_width=True,
            hide_index=True,
        )

        with st.expander(
            "Selected timeline event details"
        ):
            event_index = st.selectbox(
                "Timeline event",
                options=range(
                    len(
                        timeline
                    )
                ),
                format_func=lambda index:
                    (
                        f"#{timeline[index]['event_id']} · "
                        f"{timeline[index]['event_type']} · "
                        f"{timeline[index]['occurred_at']}"
                    ),
            )

            st.json(
                timeline[
                    int(
                        event_index
                    )
                ]
            )

    snapshots = list_snapshots(
        engine,
        marketplace,
        listing_id,
    )

    st.subheader(
        "Immutable snapshot ledger"
    )

    st.dataframe(
        pd.DataFrame(
            snapshots
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.page_link(
        "pages/10_Listing_Completeness_Review.py",
        label="Return to Listing Completeness Review",
    )


main()
