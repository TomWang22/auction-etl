"""Audited deterministic verdict-rule administration and evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.normalization_readiness import (
    get_readiness,
)


OPERATORS = (
    "GT",
    "GTE",
    "LT",
    "LTE",
    "EQ",
    "NEQ",
    "BETWEEN",
)

SEVERITIES = (
    "INFO",
    "LOW",
    "MODERATE",
    "HIGH",
    "CRITICAL",
)

RELATION_ALLOWLIST = (
    "warehouse.auction",
    "analytics.auction_collector_base",
    "warehouse.auction_completeness",
    "analytics.auction_scores",
    "analytics.emotional_damage",
    "analytics.auction_alerts",
    "analytics.midfication_detection",
)


def metric_catalog() -> dict[str, str]:
    """Return professional metric names and descriptions."""
    return {
        "NORMALIZATION_GATE_RATIO":
            "Satisfied normalization gates divided by six.",
        "COMPARABLE_SAMPLE_SIZE":
            "Normalization-ready exact-pressing comparable count.",
        "EVIDENCE_COVERAGE":
            "Available deterministic evidence coverage.",
        "COMPLETENESS_RATIO":
            "Present required quantity divided by required quantity.",
        "REISSUE_TO_FIRST_PRESS_RATIO":
            "Adjusted reissue price divided by adjusted first-press price.",
        "REISSUE_CROSSOVER_COUNT":
            "Qualified reissue crossover sales at or above 1.20.",
        "FINAL_TO_HISTORICAL_MEDIAN_RATIO":
            "Adjusted final price divided by qualified historical median.",
        "LATE_WINDOW_ESCALATION_RATIO":
            "Closing-window increase divided by closing-window start price.",
        "EMOTIONAL_DAMAGE_SCORE":
            "Legacy auction-impact score normalized to one hundred.",
        "PLUSHIE_INDEX":
            "Legacy collector-significance composite score.",
        "BID_COUNT":
            "Recorded auction bid count.",
        "WATCH_COUNT":
            "Recorded watcher count.",
    }


def _optional_text(
    value: Any,
) -> str | None:
    """Normalize optional text."""
    if value is None:
        return None

    normalized = str(value).strip()

    return normalized or None


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    """Normalize required text."""
    normalized = _optional_text(value)

    if normalized is None:
        raise ValueError(
            f"{field_name} is required."
        )

    return normalized


def _decimal(
    value: Any,
    field_name: str,
) -> Decimal:
    """Normalize a required decimal."""
    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{field_name} must be numeric."
        ) from error


def _optional_decimal(
    value: Any,
) -> Decimal | None:
    """Normalize an optional decimal."""
    if value is None:
        return None

    if isinstance(value, str) and not value.strip():
        return None

    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None


def _optional_datetime(
    value: Any,
) -> datetime | None:
    """Normalize an optional ISO-8601 timestamp."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    normalized = str(value).strip()

    if not normalized:
        return None

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1] +
            "+00:00"
        )

    try:
        return datetime.fromisoformat(
            normalized
        )
    except ValueError as error:
        raise ValueError(
            "Effective timestamps must use ISO 8601."
        ) from error


def _set_audit_context(
    connection: Connection,
    *,
    actor: str,
    reason: str,
) -> None:
    """Set transaction-local audit metadata."""
    connection.execute(
        text(
            """
            SELECT
                set_config(
                    'auction_etl.actor',
                    :actor,
                    true
                ),
                set_config(
                    'auction_etl.reason',
                    :reason,
                    true
                )
            """
        ),
        {
            "actor":
                _required_text(
                    actor,
                    "Actor",
                ),
            "reason":
                _required_text(
                    reason,
                    "Reason",
                ),
        },
    )


def list_rules(
    engine: Engine,
    *,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    """Return configured deterministic rules."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.deterministic_verdict_rule
                WHERE (
                    :include_inactive
                    OR active
                )
                ORDER BY
                    priority,
                    rule_code
                """
            ),
            {
                "include_inactive":
                    include_inactive,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def save_rule(
    engine: Engine,
    payload: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Create or update one deterministic rule."""
    rule_code = _required_text(
        payload.get("rule_code"),
        "Rule code",
    ).upper()

    display_name = _required_text(
        payload.get("display_name"),
        "Display name",
    )

    category = _required_text(
        payload.get("category"),
        "Category",
    ).upper()

    metric_code = _required_text(
        payload.get("metric_code"),
        "Metric code",
    ).upper()

    comparison_operator = _required_text(
        payload.get(
            "comparison_operator"
        ),
        "Comparison operator",
    ).upper()

    if comparison_operator not in OPERATORS:
        raise ValueError(
            "Unsupported comparison operator."
        )

    severity = _required_text(
        payload.get("severity"),
        "Severity",
    ).upper()

    if severity not in SEVERITIES:
        raise ValueError(
            "Unsupported severity."
        )

    threshold_low = _decimal(
        payload.get("threshold_low"),
        "Lower threshold",
    )

    threshold_high = _optional_decimal(
        payload.get("threshold_high")
    )

    if comparison_operator == "BETWEEN":
        if threshold_high is None:
            raise ValueError(
                "BETWEEN requires an upper threshold."
            )

        if threshold_high < threshold_low:
            raise ValueError(
                "Upper threshold must not be below the lower threshold."
            )

    minimum_sample_size = int(
        payload.get(
            "minimum_sample_size",
            0,
        )
    )

    if minimum_sample_size < 0:
        raise ValueError(
            "Minimum sample size cannot be negative."
        )

    minimum_evidence_coverage = _decimal(
        payload.get(
            "minimum_evidence_coverage",
            0,
        ),
        "Minimum evidence coverage",
    )

    if not (
        Decimal("0")
        <= minimum_evidence_coverage
        <= Decimal("1")
    ):
        raise ValueError(
            "Evidence coverage must be between zero and one."
        )

    priority = int(
        payload.get(
            "priority",
            100,
        )
    )

    effective_from = _optional_datetime(
        payload.get("effective_from")
    )

    effective_to = _optional_datetime(
        payload.get("effective_to")
    )

    if (
        effective_from is not None
        and effective_to is not None
        and effective_to <= effective_from
    ):
        raise ValueError(
            "Effective-to must be later than effective-from."
        )

    parameters = {
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
            _required_text(
                payload.get(
                    "verdict_label"
                ),
                "Verdict label",
            ),
        "verdict_message":
            _required_text(
                payload.get(
                    "verdict_message"
                ),
                "Verdict message",
            ),
        "active":
            bool(
                payload.get(
                    "active",
                    True,
                )
            ),
        "effective_from":
            effective_from,
        "effective_to":
            effective_to,
        "notes":
            _optional_text(
                payload.get("notes")
            ),
        "actor":
            _required_text(
                actor,
                "Actor",
            ),
    }

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                INSERT INTO system.deterministic_verdict_rule (
                    rule_code,
                    display_name,
                    category,
                    metric_code,
                    comparison_operator,
                    threshold_low,
                    threshold_high,
                    minimum_sample_size,
                    minimum_evidence_coverage,
                    severity,
                    priority,
                    verdict_label,
                    verdict_message,
                    active,
                    effective_from,
                    effective_to,
                    notes,
                    created_by,
                    updated_by,
                    updated_at
                )
                VALUES (
                    :rule_code,
                    :display_name,
                    :category,
                    :metric_code,
                    :comparison_operator,
                    :threshold_low,
                    :threshold_high,
                    :minimum_sample_size,
                    :minimum_evidence_coverage,
                    :severity,
                    :priority,
                    :verdict_label,
                    :verdict_message,
                    :active,
                    :effective_from,
                    :effective_to,
                    :notes,
                    :actor,
                    :actor,
                    now()
                )
                ON CONFLICT (rule_code)
                DO UPDATE SET
                    display_name =
                        EXCLUDED.display_name,
                    category =
                        EXCLUDED.category,
                    metric_code =
                        EXCLUDED.metric_code,
                    comparison_operator =
                        EXCLUDED.comparison_operator,
                    threshold_low =
                        EXCLUDED.threshold_low,
                    threshold_high =
                        EXCLUDED.threshold_high,
                    minimum_sample_size =
                        EXCLUDED.minimum_sample_size,
                    minimum_evidence_coverage =
                        EXCLUDED.minimum_evidence_coverage,
                    severity =
                        EXCLUDED.severity,
                    priority =
                        EXCLUDED.priority,
                    verdict_label =
                        EXCLUDED.verdict_label,
                    verdict_message =
                        EXCLUDED.verdict_message,
                    active =
                        EXCLUDED.active,
                    effective_from =
                        EXCLUDED.effective_from,
                    effective_to =
                        EXCLUDED.effective_to,
                    notes =
                        EXCLUDED.notes,
                    updated_by =
                        EXCLUDED.updated_by,
                    updated_at = now()
                RETURNING *
                """
            ),
            parameters,
        ).mappings().one()

    return dict(row)


def set_rule_active(
    engine: Engine,
    rule_code: str,
    active: bool,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Activate or deactivate one rule."""
    normalized_code = _required_text(
        rule_code,
        "Rule code",
    ).upper()

    with engine.begin() as connection:
        _set_audit_context(
            connection,
            actor=actor,
            reason=reason,
        )

        row = connection.execute(
            text(
                """
                UPDATE system.deterministic_verdict_rule
                SET
                    active = :active,
                    updated_by = :actor,
                    updated_at = now()
                WHERE rule_code = :rule_code
                RETURNING *
                """
            ),
            {
                "rule_code":
                    normalized_code,
                "active":
                    active,
                "actor":
                    _required_text(
                        actor,
                        "Actor",
                    ),
            },
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Rule {normalized_code} does not exist."
        )

    return dict(row)


def list_rule_audit(
    engine: Engine,
    *,
    rule_code: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return immutable verdict-rule audit events."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.deterministic_verdict_rule_audit
                WHERE (
                    CAST(:rule_code AS text) IS NULL
                    OR rule_code =
                        CAST(:rule_code AS text)
                )
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "rule_code":
                    (
                        rule_code.upper()
                        if rule_code
                        else None
                    ),
                "limit":
                    limit,
            },
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]


def _relation_json(
    connection: Connection,
    relation: str,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any]:
    """Load one relation row as JSON when compatible."""
    if relation not in RELATION_ALLOWLIST:
        raise ValueError(
            f"Relation is not allowed: {relation}"
        )

    schema_name, relation_name = (
        relation.split(".", 1)
    )

    columns = {
        row["column_name"]
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema =
                        :schema_name
                  AND table_name =
                        :relation_name
                """
            ),
            {
                "schema_name":
                    schema_name,
                "relation_name":
                    relation_name,
            },
        ).mappings()
    }

    if not {
        "marketplace",
        "listing_id",
    } <= columns:
        return {}

    row = connection.execute(
        text(
            f"""
            SELECT to_jsonb(relation_row)
            FROM {relation} AS relation_row
            WHERE marketplace =
                    :marketplace
              AND listing_id =
                    :listing_id
            LIMIT 1
            """
        ),
        {
            "marketplace":
                marketplace,
            "listing_id":
                listing_id,
        },
    ).scalar_one_or_none()

    return dict(row or {})


def _first_numeric(
    values: Mapping[str, Any],
    names: tuple[str, ...],
) -> Decimal | None:
    """Return the first available numeric alias."""
    for name in names:
        value = values.get(name)

        normalized = _optional_decimal(
            value
        )

        if normalized is not None:
            return normalized

    return None


def load_metric_bundle(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Decimal | None]:
    """Load deterministic metrics from existing analytics."""
    readiness = get_readiness(
        engine,
        marketplace,
        listing_id,
    )

    flattened: dict[str, Any] = {}

    with engine.connect() as connection:
        for relation in RELATION_ALLOWLIST:
            relation_row = _relation_json(
                connection,
                relation,
                marketplace,
                listing_id,
            )

            for key, value in (
                relation_row.items()
            ):
                flattened[
                    key.upper()
                ] = value

    metrics: dict[
        str,
        Decimal | None,
    ] = {
        "NORMALIZATION_GATE_RATIO":
            readiness[
                "readiness_gate_ratio"
            ],
        "COMPARABLE_SAMPLE_SIZE":
            Decimal(
                readiness[
                    "eligible_comparable_count"
                ]
            ),
        "COMPLETENESS_RATIO":
            readiness[
                "completeness_ratio"
            ],
        "BID_COUNT":
            _first_numeric(
                flattened,
                (
                    "BID_COUNT",
                    "BIDS",
                ),
            ),
        "WATCH_COUNT":
            _first_numeric(
                flattened,
                (
                    "WATCH_COUNT",
                    "WATCHER_COUNT",
                    "WATCHERS",
                ),
            ),
        "EVIDENCE_COVERAGE":
            _first_numeric(
                flattened,
                (
                    "EMOTIONAL_DAMAGE_COVERAGE",
                    "EVIDENCE_COVERAGE",
                ),
            ),
        "EMOTIONAL_DAMAGE_SCORE":
            _first_numeric(
                flattened,
                (
                    "EMOTIONAL_DAMAGE_SCORE",
                    "AUCTION_IMPACT_SCORE",
                ),
            ),
        "PLUSHIE_INDEX":
            _first_numeric(
                flattened,
                (
                    "PLUSHIE_INDEX",
                    "COLLECTOR_SIGNIFICANCE_INDEX",
                ),
            ),
        "REISSUE_TO_FIRST_PRESS_RATIO":
            _first_numeric(
                flattened,
                (
                    "REISSUE_TO_FIRST_PRESS_RATIO",
                    "MIDFICATION_RATIO",
                    "PRICE_RATIO",
                    "MID_RATIO",
                ),
            ),
        "REISSUE_CROSSOVER_COUNT":
            _first_numeric(
                flattened,
                (
                    "REISSUE_CROSSOVER_COUNT",
                    "STRUCTURAL_MIDFICATION_COUNT",
                    "CROSSOVER_COUNT",
                    "QUALIFYING_SALE_COUNT",
                ),
            ),
        "FINAL_TO_HISTORICAL_MEDIAN_RATIO":
            _first_numeric(
                flattened,
                (
                    "FINAL_TO_HISTORICAL_MEDIAN_RATIO",
                    "HISTORICAL_ANCHOR_DEVIATION_RATIO",
                    "HISTORICAL_DEVIATION_RATIO",
                ),
            ),
        "LATE_WINDOW_ESCALATION_RATIO":
            _first_numeric(
                flattened,
                (
                    "LATE_WINDOW_ESCALATION_RATIO",
                    "CLOSING_WINDOW_ESCALATION_RATIO",
                    "LATE_SPIKE_RATIO",
                ),
            ),
    }

    for key, value in flattened.items():
        numeric = _optional_decimal(value)

        if numeric is not None:
            metrics.setdefault(
                key,
                numeric,
            )

    return metrics


def _compare(
    value: Decimal,
    operator: str,
    threshold_low: Decimal,
    threshold_high: Decimal | None,
) -> bool:
    """Apply one deterministic comparison."""
    if operator == "GT":
        return value > threshold_low

    if operator == "GTE":
        return value >= threshold_low

    if operator == "LT":
        return value < threshold_low

    if operator == "LTE":
        return value <= threshold_low

    if operator == "EQ":
        return value == threshold_low

    if operator == "NEQ":
        return value != threshold_low

    if operator == "BETWEEN":
        if threshold_high is None:
            raise ValueError(
                "BETWEEN requires an upper threshold."
            )

        return (
            threshold_low
            <= value
            <= threshold_high
        )

    raise ValueError(
        f"Unsupported operator: {operator}"
    )


def evaluate_listing(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    *,
    at_time: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate active rules with explicit suppression reasons."""
    evaluation_time = (
        at_time
        or datetime.now(
            timezone.utc
        )
    )

    metrics = load_metric_bundle(
        engine,
        marketplace,
        listing_id,
    )

    rules = list_rules(
        engine,
        include_inactive=False,
    )

    sample_size = (
        metrics.get(
            "COMPARABLE_SAMPLE_SIZE"
        )
        or Decimal("0")
    )

    evidence_coverage = metrics.get(
        "EVIDENCE_COVERAGE"
    )

    evaluations: list[
        dict[str, Any]
    ] = []

    for rule in rules:
        effective_from = rule[
            "effective_from"
        ]

        effective_to = rule[
            "effective_to"
        ]

        if (
            effective_from is not None
            and evaluation_time <
                effective_from
        ):
            continue

        if (
            effective_to is not None
            and evaluation_time >=
                effective_to
        ):
            continue

        metric_code = rule[
            "metric_code"
        ]

        metric_value = metrics.get(
            metric_code
        )

        status = "NOT_TRIGGERED"
        reason = None
        triggered = False

        if metric_value is None:
            status = "METRIC_UNAVAILABLE"
            reason = (
                f"Metric {metric_code} "
                "is unavailable for this listing."
            )
        elif (
            sample_size
            < Decimal(
                rule[
                    "minimum_sample_size"
                ]
            )
        ):
            status = "SUPPRESSED_SAMPLE"
            reason = (
                "Comparable sample size is below "
                f"{rule['minimum_sample_size']}."
            )
        elif (
            Decimal(
                str(
                    rule[
                        "minimum_evidence_coverage"
                    ]
                )
            )
            > Decimal("0")
            and evidence_coverage is None
        ):
            status = "SUPPRESSED_EVIDENCE"
            reason = (
                "Evidence coverage is unavailable."
            )
        elif (
            evidence_coverage is not None
            and evidence_coverage
            < Decimal(
                str(
                    rule[
                        "minimum_evidence_coverage"
                    ]
                )
            )
        ):
            status = "SUPPRESSED_EVIDENCE"
            reason = (
                "Evidence coverage is below "
                f"{rule['minimum_evidence_coverage']}."
            )
        else:
            triggered = _compare(
                metric_value,
                rule[
                    "comparison_operator"
                ],
                Decimal(
                    str(
                        rule[
                            "threshold_low"
                        ]
                    )
                ),
                _optional_decimal(
                    rule[
                        "threshold_high"
                    ]
                ),
            )

            status = (
                "TRIGGERED"
                if triggered
                else "NOT_TRIGGERED"
            )

        evaluations.append(
            {
                "rule_code":
                    rule["rule_code"],
                "display_name":
                    rule["display_name"],
                "category":
                    rule["category"],
                "metric_code":
                    metric_code,
                "metric_value":
                    metric_value,
                "comparison_operator":
                    rule[
                        "comparison_operator"
                    ],
                "threshold_low":
                    rule[
                        "threshold_low"
                    ],
                "threshold_high":
                    rule[
                        "threshold_high"
                    ],
                "minimum_sample_size":
                    rule[
                        "minimum_sample_size"
                    ],
                "minimum_evidence_coverage":
                    rule[
                        "minimum_evidence_coverage"
                    ],
                "severity":
                    rule["severity"],
                "priority":
                    rule["priority"],
                "verdict_label":
                    rule[
                        "verdict_label"
                    ],
                "verdict_message":
                    rule[
                        "verdict_message"
                    ],
                "status":
                    status,
                "triggered":
                    triggered,
                "suppression_reason":
                    reason,
            }
        )

    return {
        "marketplace":
            marketplace,
        "listing_id":
            listing_id,
        "evaluated_at":
            evaluation_time,
        "metrics":
            metrics,
        "evaluations":
            evaluations,
        "triggered":
            [
                evaluation
                for evaluation in evaluations
                if evaluation["triggered"]
            ],
    }
