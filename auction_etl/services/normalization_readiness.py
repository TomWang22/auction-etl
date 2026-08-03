"""Deterministic normalization-readiness reporting."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


DEFAULT_MINIMUM_COMPARABLES = 3


def _decimal_or_none(
    value: Any,
) -> Decimal | None:
    """Normalize an optional numeric value."""
    if value is None:
        return None

    return Decimal(str(value))


def _reference_status(
    row: dict[str, Any],
) -> str:
    """Classify the shared pressing reference."""
    if row["pressing_id"] is None:
        return "NO_PRESSING"

    if row["expectation_count"] == 0:
        return "NOT_CONFIGURED"

    if row["unknown_reference_count"] > 0:
        return "PARTIAL"

    return "CONFIGURED"


def _blockers(
    row: dict[str, Any],
    minimum_comparables: int,
) -> list[str]:
    """Return explicit deterministic readiness blockers."""
    blockers: list[str] = []

    if row["pressing_id"] is None:
        blockers.append(
            "No exact pressing assignment exists."
        )

    if row["reference_status"] == "NOT_CONFIGURED":
        blockers.append(
            "The pressing completeness reference is not configured."
        )
    elif row["reference_status"] == "PARTIAL":
        blockers.append(
            "The pressing completeness reference contains UNKNOWN states."
        )

    if row["condition_market_factor"] is None:
        blockers.append(
            "No canonical condition market factor is available."
        )

    if row["completeness_market_factor"] is None:
        blockers.append(
            "No completeness market factor is available."
        )

    if row["selected_price_usd"] is None:
        blockers.append(
            "No selected normalized price basis is available."
        )

    if row["eligible_comparable_count"] < minimum_comparables:
        blockers.append(
            "Fewer than "
            f"{minimum_comparables} normalization-ready "
            "exact-pressing comparables are available."
        )

    return blockers


def _readiness_gate_ratio(
    row: dict[str, Any],
    minimum_comparables: int,
) -> Decimal:
    """Calculate readiness as satisfied gates over six gates."""
    gates = (
        row["pressing_id"] is not None,
        row["reference_status"] == "CONFIGURED",
        row["condition_market_factor"] is not None,
        row["completeness_market_factor"] is not None,
        row["selected_price_usd"] is not None,
        row["eligible_comparable_count"] >=
            minimum_comparables,
    )

    satisfied = sum(
        int(value)
        for value in gates
    )

    return (
        Decimal(satisfied)
        / Decimal(len(gates))
    ).quantize(
        Decimal("0.0001")
    )


def list_readiness(
    engine: Engine,
    *,
    marketplace: str | None = None,
    listing_id: str | None = None,
    search: str | None = None,
    minimum_comparables: int =
        DEFAULT_MINIMUM_COMPARABLES,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Return readiness rows for listings and exact pressings."""
    if minimum_comparables < 1:
        raise ValueError(
            "Minimum comparables must be at least one."
        )

    if limit < 1:
        raise ValueError(
            "Limit must be at least one."
        )

    normalized_search = (
        search.strip()
        if search and search.strip()
        else None
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                WITH reference_summary AS (
                    SELECT
                        pressing_id,
                        COUNT(*) AS expectation_count,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'REQUIRED'
                        ) AS required_reference_count,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'NOT_INCLUDED'
                        ) AS not_included_reference_count,
                        COUNT(*) FILTER (
                            WHERE expectation_state =
                                'UNKNOWN'
                        ) AS unknown_reference_count
                    FROM warehouse.pressing_component_expectation
                    GROUP BY pressing_id
                ),
                comparable_summary AS (
                    SELECT
                        pressing_id,
                        COUNT(*) FILTER (
                            WHERE selected_price_usd
                                IS NOT NULL
                        ) AS raw_comparable_count,
                        COUNT(*) FILTER (
                            WHERE normalization_ready IS TRUE
                              AND selected_price_usd
                                    IS NOT NULL
                        ) AS eligible_comparable_count
                    FROM analytics.auction_collector_base
                    WHERE pressing_id IS NOT NULL
                    GROUP BY pressing_id
                )
                SELECT
                    base.marketplace,
                    base.listing_id,
                    auction.title,
                    auction.artist,
                    auction.catalog_number,
                    auction.media_type,
                    base.pressing_id,
                    assignment.match_basis,
                    assignment.match_confidence,
                    base.selected_price_usd,
                    base.condition_market_factor,
                    base.completeness_market_factor,
                    base.normalization_ready,
                    completeness.required_component_count,
                    completeness.present_required_component_count,
                    completeness.missing_components,
                    completeness.unverified_components,
                    completeness.unexpected_components,
                    completeness.completeness_ratio,
                    completeness.completeness_status,
                    completeness.complete,
                    COALESCE(
                        reference.expectation_count,
                        0
                    ) AS expectation_count,
                    COALESCE(
                        reference.required_reference_count,
                        0
                    ) AS required_reference_count,
                    COALESCE(
                        reference.not_included_reference_count,
                        0
                    ) AS not_included_reference_count,
                    COALESCE(
                        reference.unknown_reference_count,
                        0
                    ) AS unknown_reference_count,
                    COALESCE(
                        comparable.raw_comparable_count,
                        0
                    ) AS raw_comparable_count,
                    COALESCE(
                        comparable.eligible_comparable_count,
                        0
                    ) AS eligible_comparable_count
                FROM analytics.auction_collector_base AS base
                JOIN warehouse.auction AS auction
                  ON auction.marketplace =
                        base.marketplace
                 AND auction.listing_id =
                        base.listing_id
                LEFT JOIN warehouse.auction_pressing_assignment
                    AS assignment
                  ON assignment.marketplace =
                        base.marketplace
                 AND assignment.listing_id =
                        base.listing_id
                LEFT JOIN warehouse.auction_completeness
                    AS completeness
                  ON completeness.marketplace =
                        base.marketplace
                 AND completeness.listing_id =
                        base.listing_id
                LEFT JOIN reference_summary AS reference
                  ON reference.pressing_id =
                        base.pressing_id
                LEFT JOIN comparable_summary AS comparable
                  ON comparable.pressing_id =
                        base.pressing_id
                WHERE (
                    CAST(:marketplace AS text) IS NULL
                    OR base.marketplace =
                        CAST(:marketplace AS text)
                )
                  AND (
                    CAST(:listing_id AS text) IS NULL
                    OR base.listing_id =
                        CAST(:listing_id AS text)
                  )
                  AND (
                    CAST(:search AS text) IS NULL
                    OR CONCAT_WS(
                        ' ',
                        auction.title,
                        auction.artist,
                        auction.catalog_number,
                        auction.media_type,
                        base.marketplace,
                        base.listing_id
                    ) ILIKE
                        '%' ||
                        CAST(:search AS text) ||
                        '%'
                  )
                ORDER BY
                    base.normalization_ready DESC NULLS LAST,
                    base.pressing_id NULLS LAST,
                    base.marketplace,
                    base.listing_id
                LIMIT :limit
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "search":
                    normalized_search,
                "limit":
                    limit,
            },
        ).mappings().all()

    results: list[dict[str, Any]] = []

    for raw_row in rows:
        row = dict(raw_row)

        row["selected_price_usd"] = (
            _decimal_or_none(
                row["selected_price_usd"]
            )
        )

        row["condition_market_factor"] = (
            _decimal_or_none(
                row["condition_market_factor"]
            )
        )

        row["completeness_market_factor"] = (
            _decimal_or_none(
                row["completeness_market_factor"]
            )
        )

        row["completeness_ratio"] = (
            _decimal_or_none(
                row["completeness_ratio"]
            )
        )

        row["reference_status"] = (
            _reference_status(row)
        )

        row["readiness_gate_ratio"] = (
            _readiness_gate_ratio(
                row,
                minimum_comparables,
            )
        )

        row["blockers"] = _blockers(
            row,
            minimum_comparables,
        )

        row["readiness_status"] = (
            "READY"
            if not row["blockers"]
            else "BLOCKED"
        )

        results.append(row)

    return results


def get_readiness(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    *,
    minimum_comparables: int =
        DEFAULT_MINIMUM_COMPARABLES,
) -> dict[str, Any]:
    """Return one listing readiness record."""
    rows = list_readiness(
        engine,
        marketplace=marketplace,
        listing_id=listing_id,
        minimum_comparables=
            minimum_comparables,
        limit=2,
    )

    if len(rows) != 1:
        raise ValueError(
            "The requested listing was not found or is not unique."
        )

    return rows[0]


def readiness_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    """Summarize deterministic readiness states."""
    return {
        "total":
            len(rows),
        "ready":
            sum(
                row["readiness_status"] == "READY"
                for row in rows
            ),
        "blocked":
            sum(
                row["readiness_status"] == "BLOCKED"
                for row in rows
            ),
        "pressing_assigned":
            sum(
                row["pressing_id"] is not None
                for row in rows
            ),
        "reference_configured":
            sum(
                row["reference_status"] == "CONFIGURED"
                for row in rows
            ),
        "condition_normalized":
            sum(
                row["condition_market_factor"] is not None
                for row in rows
            ),
        "completeness_normalized":
            sum(
                row["completeness_market_factor"] is not None
                for row in rows
            ),
    }
