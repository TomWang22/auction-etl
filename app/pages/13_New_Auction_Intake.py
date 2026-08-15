"""New-auction assignment queue and completeness alerts."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from auction_etl.services.auction_intake import (
    apply_assignment,
    engine_from_environment,
    list_alert_history,
    list_assignment_audit,
    list_cohort_summary,
    list_current_alerts,
    list_exact_pressings,
    list_match_basis_options,
    list_queue_marketplaces,
    list_unassigned_auctions,
    preview_assignment,
    queue_count,
)
from app.navigation import render_navigation


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Return a display-safe dataframe."""
    return pd.DataFrame(
        rows
    )


def _auction_label(row: dict[str, object]) -> str:
    """Return one queue selector label."""
    catalog = str(
        row.get(
            "catalog_hint"
        )
        or "no catalog hint"
    )

    return (
        f"{row['marketplace']}/"
        f"{row['listing_id']} · "
        f"{row['display_title']} · "
        f"{catalog}"
    )


def _pressing_label(row: dict[str, object]) -> str:
    """Return one exact-pressing selector label."""
    return (
        f"Pressing #{row['pressing_id']} · "
        f"{row['display_artist']} · "
        f"{row['display_title']} · "
        f"{row['catalog_number']} · "
        f"{row['media_type']}"
    )


def main() -> None:
    """Render the complete new-auction intake workflow."""
    st.set_page_config(
        page_title="New Auction Intake",
        layout="wide",
    )
    render_navigation()

    st.title("New Auction Intake")

    st.write(
        "Newly ingested auctions remain unassigned until a reviewer "
        "selects an exact pressing. Ingestion never guesses or rewrites "
        "the master pressing reference."
    )

    st.warning(
        "An auction listing is one physical copy. Its observations and "
        "condition never redefine what a complete pressing should contain."
    )

    engine = engine_from_environment()

    queue_tab, alerts_tab, cohorts_tab, audit_tab = st.tabs(
        (
            "Assignment Queue",
            "Completeness Alerts",
            "Cohort Reporting",
            "Assignment Audit",
        )
    )

    with queue_tab:
        total_queue = queue_count(
            engine
        )

        st.metric(
            "Unassigned auctions",
            total_queue,
        )

        marketplace_options = [
            "ALL",
            *list_queue_marketplaces(
                engine
            ),
        ]

        filter_left, filter_right = st.columns(
            2
        )

        with filter_left:
            marketplace = st.selectbox(
                "Marketplace",
                marketplace_options,
            )

        with filter_right:
            search = st.text_input(
                "Search title, catalog hint, or listing ID"
            )

        queue_rows = list_unassigned_auctions(
            engine,
            limit=1000,
            marketplace=(
                None
                if marketplace == "ALL"
                else marketplace
            ),
            search=search,
        )

        if not queue_rows:
            st.info(
                "No unassigned auction matches the current filters."
            )

        else:
            st.dataframe(
                _frame(
                    queue_rows
                ).drop(
                    columns=[
                        "auction_payload",
                    ],
                    errors="ignore",
                ),
                use_container_width=True,
                hide_index=True,
            )

            auction_options = {
                _auction_label(
                    row
                ):
                    row
                for row in queue_rows
            }

            selected_auction_label = st.selectbox(
                "Auction waiting for assignment",
                tuple(
                    auction_options
                ),
            )

            selected_auction = auction_options[
                selected_auction_label
            ]

            st.json(
                selected_auction[
                    "auction_payload"
                ],
                expanded=False,
            )

            pressings = list_exact_pressings(
                engine
            )

            pressing_options = {
                _pressing_label(
                    row
                ):
                    row
                for row in pressings
            }

            selected_pressing_label = st.selectbox(
                "Reviewed exact pressing",
                tuple(
                    pressing_options
                ),
            )

            selected_pressing = pressing_options[
                selected_pressing_label
            ]

            basis_options = list_match_basis_options(
                engine
            )

            basis = st.selectbox(
                "Match basis",
                basis_options,
            )

            confidence = st.number_input(
                "Match confidence",
                min_value=0.0,
                max_value=1.0,
                value=0.95,
                step=0.01,
                format="%.4f",
            )

            reviewer = st.text_input(
                "Reviewer"
            )

            reason = st.text_area(
                "Reviewed assignment reason"
            )

            scope_confirmed = st.checkbox(
                "I confirm this assignment identifies the exact pressing "
                "only; it does not infer component completeness, condition, "
                "or physical-copy lineage."
            )

            preview_key = (
                "new_auction_assignment_preview"
            )

            if st.button(
                "Preview reviewed assignment",
                type="secondary",
            ):
                try:
                    st.session_state[
                        preview_key
                    ] = preview_assignment(
                        engine,
                        marketplace=
                            selected_auction[
                                "marketplace"
                            ],
                        listing_id=
                            selected_auction[
                                "listing_id"
                            ],
                        pressing_id=
                            selected_pressing[
                                "pressing_id"
                            ],
                        match_basis=basis,
                        match_confidence=
                            confidence,
                        reviewer=reviewer,
                        reason=reason,
                        scope_confirmed=
                            scope_confirmed,
                    )
                except Exception as error:
                    st.error(
                        str(
                            error
                        )
                    )

            preview = st.session_state.get(
                preview_key
            )

            if preview:
                st.subheader(
                    "Deterministic assignment preview"
                )

                st.json(
                    preview,
                    expanded=False,
                )

                confirmation_token = st.text_input(
                    "Confirmation token",
                    help=(
                        "Copy the exact token from the recomputed preview."
                    ),
                )

                if st.button(
                    "Apply reviewed assignment",
                    type="primary",
                ):
                    try:
                        result = apply_assignment(
                            engine,
                            marketplace=
                                preview[
                                    "mutation"
                                ][
                                    "marketplace"
                                ],
                            listing_id=
                                preview[
                                    "mutation"
                                ][
                                    "listing_id"
                                ],
                            pressing_id=
                                preview[
                                    "mutation"
                                ][
                                    "pressing_id"
                                ],
                            match_basis=
                                preview[
                                    "mutation"
                                ][
                                    "match_basis"
                                ],
                            match_confidence=
                                preview[
                                    "mutation"
                                ][
                                    "match_confidence"
                                ],
                            reviewer=
                                preview[
                                    "mutation"
                                ][
                                    "reviewer"
                                ],
                            reason=
                                preview[
                                    "mutation"
                                ][
                                    "reason"
                                ],
                            scope_confirmed=True,
                            confirmation_token=
                                confirmation_token,
                        )

                        st.success(
                            "Reviewed assignment completed."
                        )

                        st.json(
                            result,
                            expanded=False,
                        )

                        st.session_state.pop(
                            preview_key,
                            None,
                        )

                        st.rerun()
                    except Exception as error:
                        st.error(
                            str(
                                error
                            )
                        )

        st.divider()

        st.subheader(
            "Safe ingestion command"
        )

        st.code(
            (
                "python scripts/run_ingest_with_assignment_queue.py "
                "--execute -- "
                "python scripts/sync_warehouse_incremental.py"
            ),
            language="bash",
        )

        st.caption(
            "The wrapper snapshots auction identities before and after "
            "ingestion, reports inserted and updated auctions, forbids "
            "automatic assignment writes, and leaves every new auction in "
            "this review queue."
        )

    with alerts_tab:
        alerts = list_current_alerts(
            engine
        )

        critical_count = sum(
            1
            for row in alerts
            if row.get(
                "severity"
            ) == "CRITICAL"
        )

        warning_count = sum(
            1
            for row in alerts
            if row.get(
                "severity"
            ) == "WARNING"
        )

        metric_left, metric_middle, metric_right = st.columns(
            3
        )

        metric_left.metric(
            "Current alerts",
            len(
                alerts
            ),
        )

        metric_middle.metric(
            "Critical",
            critical_count,
        )

        metric_right.metric(
            "Warnings",
            warning_count,
        )

        st.dataframe(
            _frame(
                alerts
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader(
            "Immutable alert history"
        )

        st.dataframe(
            _frame(
                list_alert_history(
                    engine
                )
            ),
            use_container_width=True,
            hide_index=True,
        )

    with cohorts_tab:
        st.write(
            "Cohort totals use the latest immutable snapshot for each "
            "listing and remain grouped by exact pressing and media type."
        )

        st.dataframe(
            _frame(
                list_cohort_summary(
                    engine
                )
            ),
            use_container_width=True,
            hide_index=True,
        )

    with audit_tab:
        st.write(
            "Assignment audit history is immutable. Migration baseline "
            "events and every reviewed write remain chronologically visible."
        )

        st.dataframe(
            _frame(
                list_assignment_audit(
                    engine
                )
            ),
            use_container_width=True,
            hide_index=True,
        )


main()
