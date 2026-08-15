"""Professional deterministic verdict-rule manager."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.services.deterministic_verdicts import (
    OPERATORS,
    SEVERITIES,
    evaluate_listing,
    list_rule_audit,
    list_rules,
    metric_catalog,
    save_rule,
    set_rule_active,
)
from auction_etl.services.normalization_readiness import (
    list_readiness,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Deterministic Verdict Rules",
    page_icon="⚖️",
    layout="wide",
)
render_navigation(expand_advanced=True)


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


def _rerun(message: str) -> None:
    """Rerun with one success message."""
    st.session_state[
        "verdict_rule_message"
    ] = message

    st.rerun()


def _rule_label(
    rule: dict[str, Any],
) -> str:
    """Build one readable rule label."""
    return (
        f"{rule['rule_code']} · "
        f"{rule['display_name']}"
    )


def _listing_label(
    row: dict[str, Any],
) -> str:
    """Build one readable listing label."""
    return (
        f"{row['marketplace']}/"
        f"{row['listing_id']} · "
        f"{row.get('title') or 'Untitled listing'}"
    )


def _render_rule_library(
    engine: Engine,
) -> None:
    """Display active and inactive rules."""
    st.subheader(
        "Professional rule library"
    )

    rules = list_rules(
        engine,
        include_inactive=True,
    )

    st.dataframe(
        pd.DataFrame(rules),
        width="stretch",
        hide_index=True,
    )

    st.markdown(
        "#### Professional terminology"
    )

    st.write(
        {
            "Reissue Price Convergence":
                "An adjusted reissue price approaching the adjusted first-press level.",
            "First-Press Price Parity":
                "An adjusted reissue result between 1.00 and 1.19 of the first-press level.",
            "Reissue Price Crossover":
                "An adjusted reissue result at or above 1.20.",
            "Persistent Reissue Displacement":
                "At least three qualified crossover results.",
            "Market Noise":
                "A cohort too small or incomplete for structural interpretation.",
            "Auction Impact":
                "The formal presentation of the legacy auction-impact score.",
            "Collector Significance Index":
                "The formal presentation of the legacy composite collector score.",
        }
    )


def _render_rule_editor(
    engine: Engine,
) -> None:
    """Create or update audited deterministic rules."""
    st.subheader(
        "Create or update a rule"
    )

    rules = list_rules(
        engine,
        include_inactive=True,
    )

    rule_by_code = {
        rule["rule_code"]: rule
        for rule in rules
    }

    selection = st.selectbox(
        "Rule",
        options=[
            "CREATE_NEW",
            *rule_by_code,
        ],
        format_func=lambda value: (
            "Create a new rule"
            if value == "CREATE_NEW"
            else _rule_label(
                rule_by_code[value]
            )
        ),
    )

    defaults = (
        {}
        if selection == "CREATE_NEW"
        else rule_by_code[
            selection
        ]
    )

    catalog = metric_catalog()
    metric_options = list(catalog)

    default_metric = (
        defaults.get("metric_code")
        or metric_options[0]
    )

    default_operator = (
        defaults.get(
            "comparison_operator"
        )
        or "GTE"
    )

    default_severity = (
        defaults.get("severity")
        or "INFO"
    )

    with st.form(
        "deterministic-rule-editor",
        clear_on_submit=False,
    ):
        rule_code = st.text_input(
            "Rule code",
            value=str(
                defaults.get(
                    "rule_code"
                )
                or ""
            ),
            placeholder="NEW_PROFESSIONAL_RULE",
        )

        display_name = st.text_input(
            "Display name",
            value=str(
                defaults.get(
                    "display_name"
                )
                or ""
            ),
        )

        category = st.text_input(
            "Category",
            value=str(
                defaults.get(
                    "category"
                )
                or "PRICE_ANOMALY"
            ),
        )

        metric_code = st.selectbox(
            "Metric",
            options=metric_options,
            index=metric_options.index(
                default_metric
            ),
            format_func=lambda value: (
                f"{value} — "
                f"{catalog[value]}"
            ),
        )

        comparison_operator = st.selectbox(
            "Comparison operator",
            options=list(OPERATORS),
            index=list(OPERATORS).index(
                default_operator
            ),
        )

        threshold_low = st.number_input(
            "Lower threshold",
            value=float(
                defaults.get(
                    "threshold_low"
                )
                or 0
            ),
            step=0.01,
        )

        threshold_high = st.text_input(
            "Upper threshold",
            value=(
                ""
                if defaults.get(
                    "threshold_high"
                ) is None
                else str(
                    defaults[
                        "threshold_high"
                    ]
                )
            ),
            help=(
                "Required only for BETWEEN."
            ),
        )

        minimum_sample_size = st.number_input(
            "Minimum comparable sample size",
            min_value=0,
            value=int(
                defaults.get(
                    "minimum_sample_size"
                )
                or 0
            ),
            step=1,
        )

        minimum_evidence_coverage = (
            st.number_input(
                "Minimum evidence coverage",
                min_value=0.0,
                max_value=1.0,
                value=float(
                    defaults.get(
                        "minimum_evidence_coverage"
                    )
                    or 0
                ),
                step=0.05,
                format="%.2f",
            )
        )

        severity = st.selectbox(
            "Severity",
            options=list(SEVERITIES),
            index=list(SEVERITIES).index(
                default_severity
            ),
        )

        priority = st.number_input(
            "Priority",
            min_value=0,
            value=int(
                defaults.get(
                    "priority"
                )
                or 100
            ),
            step=1,
        )

        verdict_label = st.text_input(
            "Verdict label",
            value=str(
                defaults.get(
                    "verdict_label"
                )
                or ""
            ),
        )

        verdict_message = st.text_area(
            "Verdict explanation",
            value=str(
                defaults.get(
                    "verdict_message"
                )
                or ""
            ),
        )

        active = st.checkbox(
            "Active",
            value=bool(
                defaults.get(
                    "active",
                    True,
                )
            ),
        )

        effective_from = st.text_input(
            "Effective from (ISO 8601)",
            value=(
                ""
                if defaults.get(
                    "effective_from"
                ) is None
                else str(
                    defaults[
                        "effective_from"
                    ]
                )
            ),
        )

        effective_to = st.text_input(
            "Effective to (ISO 8601)",
            value=(
                ""
                if defaults.get(
                    "effective_to"
                ) is None
                else str(
                    defaults[
                        "effective_to"
                    ]
                )
            ),
        )

        notes = st.text_area(
            "Rule notes",
            value=str(
                defaults.get(
                    "notes"
                )
                or ""
            ),
        )

        actor = st.text_input(
            "Actor or workflow",
            value="STREAMLIT_VERDICT_RULE_MANAGER",
        )

        reason = st.text_area(
            "Reason for this change",
        )

        submitted = st.form_submit_button(
            "Save deterministic rule",
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            saved = save_rule(
                engine,
                {
                    "rule_code":
                        rule_code,
                    "display_name":
                        display_name,
                    "category":
                        category,
                    "metric_code":
                        metric_code,
                    "comparison_operator":
                        comparison_operator,
                    "threshold_low":
                        threshold_low,
                    "threshold_high":
                        threshold_high,
                    "minimum_sample_size":
                        minimum_sample_size,
                    "minimum_evidence_coverage":
                        minimum_evidence_coverage,
                    "severity":
                        severity,
                    "priority":
                        priority,
                    "verdict_label":
                        verdict_label,
                    "verdict_message":
                        verdict_message,
                    "active":
                        active,
                    "effective_from":
                        effective_from,
                    "effective_to":
                        effective_to,
                    "notes":
                        notes,
                },
                actor=actor,
                reason=reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                "Deterministic rule saved: "
                f"{saved['rule_code']}."
            )

    if selection == "CREATE_NEW":
        return

    st.markdown(
        "#### Activation state"
    )

    activation_reason = st.text_area(
        "Activation-state reason",
        key=(
            "activation-reason:"
            f"{selection}"
        ),
    )

    desired_state = not bool(
        defaults["active"]
    )

    if st.button(
        (
            "Activate rule"
            if desired_state
            else "Deactivate rule"
        ),
        width="stretch",
    ):
        try:
            updated = set_rule_active(
                engine,
                selection,
                desired_state,
                actor=(
                    "STREAMLIT_VERDICT_RULE_MANAGER"
                ),
                reason=activation_reason,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _rerun(
                f"{updated['rule_code']} "
                f"active={updated['active']}."
            )


def _render_evaluation(
    engine: Engine,
) -> None:
    """Evaluate one listing using current active rules."""
    st.subheader(
        "Listing verdict evaluation"
    )

    rows = list_readiness(
        engine,
        limit=2000,
    )

    if not rows:
        st.info(
            "No warehouse listings are available."
        )
        return

    selection = st.selectbox(
        "Listing",
        options=[
            (
                row["marketplace"],
                row["listing_id"],
            )
            for row in rows
        ],
        format_func=lambda value: (
            _listing_label(
                next(
                    row
                    for row in rows
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

    result = evaluate_listing(
        engine,
        selection[0],
        selection[1],
    )

    triggered = result[
        "triggered"
    ]

    metrics = st.columns(3)

    metrics[0].metric(
        "Active evaluations",
        len(
            result["evaluations"]
        ),
    )
    metrics[1].metric(
        "Triggered verdicts",
        len(triggered),
    )
    metrics[2].metric(
        "Suppressed or unavailable",
        sum(
            evaluation[
                "status"
            ] in {
                "METRIC_UNAVAILABLE",
                "SUPPRESSED_SAMPLE",
                "SUPPRESSED_EVIDENCE",
            }
            for evaluation in result[
                "evaluations"
            ]
        ),
    )

    if triggered:
        for verdict in triggered:
            st.warning(
                f"**{verdict['verdict_label']}** "
                f"({verdict['severity']}): "
                f"{verdict['verdict_message']}"
            )
    else:
        st.success(
            "No active deterministic verdict rule was triggered."
        )

    st.markdown(
        "#### Metric bundle"
    )

    metric_rows = [
        {
            "metric_code":
                code,
            "value":
                value,
        }
        for code, value in sorted(
            result["metrics"].items()
        )
    ]

    st.dataframe(
        pd.DataFrame(metric_rows),
        width="stretch",
        hide_index=True,
    )

    st.markdown(
        "#### Rule-by-rule explanation"
    )

    st.dataframe(
        pd.DataFrame(
            result["evaluations"]
        ),
        width="stretch",
        hide_index=True,
    )


def _render_audit(
    engine: Engine,
) -> None:
    """Display immutable rule history."""
    st.subheader(
        "Immutable rule history"
    )

    rules = list_rules(
        engine,
        include_inactive=True,
    )

    filter_code = st.selectbox(
        "Rule history filter",
        options=[
            "ALL",
            *[
                rule["rule_code"]
                for rule in rules
            ],
        ],
    )

    events = list_rule_audit(
        engine,
        rule_code=(
            None
            if filter_code == "ALL"
            else filter_code
        ),
        limit=500,
    )

    display_rows = []

    for event in events:
        display_rows.append(
            {
                **event,
                "before_state":
                    json.dumps(
                        event[
                            "before_state"
                        ],
                        ensure_ascii=False,
                        default=str,
                    )
                    if event[
                        "before_state"
                    ] is not None
                    else None,
                "after_state":
                    json.dumps(
                        event[
                            "after_state"
                        ],
                        ensure_ascii=False,
                        default=str,
                    )
                    if event[
                        "after_state"
                    ] is not None
                    else None,
            }
        )

    st.dataframe(
        pd.DataFrame(display_rows),
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    """Render the professional verdict-rule manager."""
    st.title(
        "⚖️ Deterministic Verdict Rules"
    )

    st.caption(
        "Audited, explainable market and collector verdicts. "
        "Every result is calculated from stored metrics, explicit "
        "thresholds, evidence coverage, and sample-size requirements."
    )

    st.info(
        "No language model assigns these verdicts. "
        "Unavailable metrics and weak evidence produce explicit "
        "suppression states rather than inferred conclusions."
    )

    message = st.session_state.pop(
        "verdict_rule_message",
        None,
    )

    if message:
        st.success(message)

    engine = _engine()

    tabs = st.tabs(
        [
            "Rule library",
            "Rule editor",
            "Listing evaluation",
            "Audit history",
        ]
    )

    with tabs[0]:
        _render_rule_library(
            engine
        )

    with tabs[1]:
        _render_rule_editor(
            engine
        )

    with tabs[2]:
        _render_evaluation(
            engine
        )

    with tabs[3]:
        _render_audit(
            engine
        )


main()
