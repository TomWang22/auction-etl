"""Evidence-backed collector analytics proposals."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from auction_etl.services.collector_curation import (
    PRICE_BASES,
    required_text,
    validated_choice,
)


MINIMUM_ASSIGNMENT_CONFIDENCE = Decimal("0.80")
DEFAULT_MINIMUM_COMPARABLES = 3
DEFAULT_CLOSING_WINDOW_MINUTES = 360


@dataclass(frozen=True)
class ConditionSuggestion:
    """An exact-token condition normalization proposal."""

    media_grade_code: str | None
    cover_grade_code: str | None
    source_media_condition: str | None
    source_cover_condition: str | None
    confidence: Decimal
    rationale: str


@dataclass(frozen=True)
class HistoricalAnchorSuggestion:
    """A median exact-pressing historical anchor."""

    price_basis: str
    anchor_usd: Decimal
    sample_count: int
    comparable_listings: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ClosingWindowSuggestion:
    """A timestamped closing-window escalation proposal."""

    snapshot_id: int
    captured_at: datetime
    minutes_before_close: int
    start_price: Decimal
    final_price: Decimal
    currency: str
    escalation_ratio: Decimal
    source: str
    rationale: str


@dataclass(frozen=True)
class EvidenceReport:
    """All conservative proposals for one listing."""

    marketplace: str
    listing_id: str
    condition: ConditionSuggestion | None
    historical_anchor: HistoricalAnchorSuggestion | None
    closing_window: ClosingWindowSuggestion | None
    comparable_count: int
    snapshot_count: int
    blockers: tuple[str, ...]
    normalized_comparable_count: int = 0
    normalization_ready: bool = False

    @property
    def ready_actions(self) -> tuple[str, ...]:
        """Return actions that have sufficient evidence."""
        actions: list[str] = []

        if self.condition is not None:
            actions.append("condition")

        if self.historical_anchor is not None:
            actions.append("historical_anchor")

        if self.closing_window is not None:
            actions.append("closing_window")

        return tuple(actions)

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly mapping."""
        payload = asdict(self)
        payload["ready_actions"] = list(
            self.ready_actions
        )
        return payload


def _decimal(value: Any) -> Decimal | None:
    """Return a finite Decimal when possible."""
    if value is None or value == "":
        return None

    try:
        result = Decimal(str(value))
    except Exception:
        return None

    if not result.is_finite():
        return None

    return result


def _text(value: Any) -> str | None:
    """Normalize optional source text."""
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _append_note(
    existing: Any,
    addition: str,
) -> str:
    """Append provenance without duplicating it."""
    existing_text = _text(existing)

    if existing_text is None:
        return addition

    if addition in existing_text:
        return existing_text

    return f"{existing_text}\n{addition}"


def extract_exact_condition_grade(
    source_text: Any,
    allowed_codes: Iterable[str],
) -> str | None:
    """Extract only an explicit canonical grade token."""
    normalized_source = _text(source_text)

    if normalized_source is None:
        return None

    normalized_source = unicodedata.normalize(
        "NFKC",
        normalized_source,
    ).upper()

    codes = {
        str(code).strip().upper()
        for code in allowed_codes
        if str(code).strip()
    }

    aliases = (
        ("NEAR MINT", "NM"),
        ("MINT", "M"),
        ("EXCELLENT", "EX"),
    )

    for phrase, code in aliases:
        if (
            code in codes
            and re.search(
                rf"(?<![A-Z0-9])"
                rf"{re.escape(phrase)}"
                rf"(?![A-Z0-9])",
                normalized_source,
            )
        ):
            return code

    for code in sorted(
        codes,
        key=lambda value: (
            -len(value),
            value,
        ),
    ):
        if re.search(
            rf"(?<![A-Z0-9])"
            rf"{re.escape(code)}"
            rf"(?![A-Z0-9])",
            normalized_source,
        ):
            return code

    return None


def median_decimal(
    values: Sequence[Decimal],
) -> Decimal:
    """Calculate a deterministic four-decimal median."""
    if not values:
        raise ValueError(
            "At least one value is required."
        )

    ordered = sorted(values)
    midpoint = len(ordered) // 2

    if len(ordered) % 2:
        result = ordered[midpoint]
    else:
        result = (
            ordered[midpoint - 1]
            + ordered[midpoint]
        ) / Decimal("2")

    return result.quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def select_closing_window(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    closing_at: datetime | None,
    final_price: Decimal | None,
    currency: str | None,
    maximum_minutes: int,
) -> ClosingWindowSuggestion | None:
    """Select the latest compatible timestamped price snapshot."""
    if (
        closing_at is None
        or final_price is None
        or final_price <= 0
        or not currency
        or maximum_minutes < 0
    ):
        return None

    candidates: list[
        tuple[datetime, Mapping[str, Any]]
    ] = []

    for snapshot in snapshots:
        captured_at = snapshot.get(
            "captured_at"
        )
        price = _decimal(
            snapshot.get("price_local")
        )
        snapshot_currency = (
            _text(snapshot.get("currency"))
            or ""
        ).upper()

        if not isinstance(
            captured_at,
            datetime,
        ):
            continue

        if price is None or price <= 0:
            continue

        if snapshot_currency != currency.upper():
            continue

        seconds_before = (
            closing_at - captured_at
        ).total_seconds()

        if seconds_before < 0:
            continue

        if seconds_before > maximum_minutes * 60:
            continue

        candidates.append(
            (
                captured_at,
                snapshot,
            )
        )

    if not candidates:
        return None

    _, selected = max(
        candidates,
        key=lambda item: item[0],
    )

    captured_at = selected["captured_at"]
    start_price = _decimal(
        selected.get("price_local")
    )

    if start_price is None or start_price <= 0:
        return None

    minutes_before_close = int(
        round(
            (
                closing_at
                - captured_at
            ).total_seconds()
            / 60
        )
    )

    ratio = (
        final_price
        / start_price
        - Decimal("1")
    ).quantize(
        Decimal("0.00000001"),
        rounding=ROUND_HALF_UP,
    )

    return ClosingWindowSuggestion(
        snapshot_id=int(
            selected["id"]
        ),
        captured_at=captured_at,
        minutes_before_close=(
            minutes_before_close
        ),
        start_price=start_price,
        final_price=final_price,
        currency=currency.upper(),
        escalation_ratio=ratio,
        source=(
            _text(selected.get("source"))
            or "UNKNOWN"
        ),
        rationale=(
            "Latest timestamped price snapshot within "
            f"{maximum_minutes} minutes of closing."
        ),
    )


def build_evidence_report(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    *,
    price_basis: str = "GROSS",
    minimum_comparables: int = (
        DEFAULT_MINIMUM_COMPARABLES
    ),
    closing_window_minutes: int = (
        DEFAULT_CLOSING_WINDOW_MINUTES
    ),
) -> EvidenceReport:
    """Build proposals without writing database rows."""
    marketplace_value = required_text(
        marketplace,
        "Marketplace",
    )
    listing_id_value = required_text(
        listing_id,
        "Listing ID",
    )
    price_basis_value = validated_choice(
        price_basis,
        PRICE_BASES,
        "Price basis",
        "GROSS",
    )

    if minimum_comparables < 1:
        raise ValueError(
            "Minimum comparables must be at least 1."
        )

    if closing_window_minutes < 0:
        raise ValueError(
            "Closing-window minutes cannot be negative."
        )

    price_columns = {
        "HAMMER": "final_price_usd",
        "GROSS": "gross_price_usd",
        "LANDED": "landed_price_usd",
    }

    price_column = price_columns[
        price_basis_value
    ]

    with engine.connect() as connection:
        listing = connection.execute(
            text(
                """
                SELECT
                    auction.marketplace,
                    auction.listing_id,
                    auction.title,
                    auction.condition_media,
                    auction.condition_cover,
                    auction.currency,
                    auction.final_price,
                    COALESCE(
                        auction.closing_at,
                        auction.ended_at
                    ) AS closing_at,
                    assignment.pressing_id
                FROM warehouse.auction AS auction
                LEFT JOIN warehouse
                    .auction_pressing_assignment
                    AS assignment
                  ON assignment.marketplace =
                        auction.marketplace
                 AND assignment.listing_id =
                        auction.listing_id
                WHERE auction.marketplace =
                        :marketplace
                  AND auction.listing_id =
                        :listing_id
                """
            ),
            {
                "marketplace":
                    marketplace_value,
                "listing_id":
                    listing_id_value,
            },
        ).mappings().one_or_none()

        if listing is None:
            raise ValueError(
                "The requested auction listing "
                "does not exist."
            )

        condition_codes = tuple(
            connection.execute(
                text(
                    """
                    SELECT code
                    FROM system.condition_grade
                    ORDER BY sort_rank, code
                    """
                )
            ).scalars()
        )

        existing_condition = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM warehouse
                        .auction_condition_normalization
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                },
            ).mappings().one_or_none()
        )

        existing_analysis = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM warehouse.auction_analysis_input
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                },
            ).mappings().one_or_none()
        )

        existing_behavior = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM warehouse
                        .auction_behavior_observation
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                },
            ).mappings().one_or_none()
        )

        blockers: list[str] = []
        condition: ConditionSuggestion | None = None

        if (
            existing_condition is not None
            and existing_condition[
                "is_manual_override"
            ]
        ):
            blockers.append(
                "Condition already has a manual override; "
                "automatic evidence will not replace it."
            )
        else:
            media_grade = (
                extract_exact_condition_grade(
                    listing[
                        "condition_media"
                    ],
                    condition_codes,
                )
            )
            cover_grade = (
                extract_exact_condition_grade(
                    listing[
                        "condition_cover"
                    ],
                    condition_codes,
                )
            )

            if (
                media_grade is not None
                or cover_grade is not None
            ):
                condition = ConditionSuggestion(
                    media_grade_code=media_grade,
                    cover_grade_code=cover_grade,
                    source_media_condition=_text(
                        listing[
                            "condition_media"
                        ]
                    ),
                    source_cover_condition=_text(
                        listing[
                            "condition_cover"
                        ]
                    ),
                    confidence=Decimal("0.9500"),
                    rationale=(
                        "Canonical grade appears as an exact "
                        "token in the source condition text."
                    ),
                )
            else:
                blockers.append(
                    "No exact canonical condition grade token "
                    "is present in the source condition fields."
                )

        comparable_rows: list[
            Mapping[str, Any]
        ] = []

        normalized_comparable_rows: list[
            Mapping[str, Any]
        ] = []

        target_normalization_ready = False

        normalized_price_columns = {
            "HAMMER": "price_hammer_usd",
            "GROSS": "price_gross_usd",
            "LANDED": "price_landed_usd",
        }

        normalized_price_column = (
            normalized_price_columns[
                price_basis_value
            ]
        )

        pressing_id = listing[
            "pressing_id"
        ]

        if pressing_id is None:
            blockers.append(
                "No exact pressing is assigned, so historical "
                "comparables cannot be selected."
            )
        else:
            comparable_rows = list(
                connection.execute(
                    text(
                        f"""
                        SELECT
                            auction.marketplace,
                            auction.listing_id,
                            auction.{price_column}
                                AS price_usd
                        FROM warehouse
                            .auction_pressing_assignment
                            AS assignment
                        JOIN warehouse.auction
                            AS auction
                          ON auction.marketplace =
                                assignment.marketplace
                         AND auction.listing_id =
                                assignment.listing_id
                        WHERE assignment.pressing_id =
                                :pressing_id
                          AND NOT (
                              assignment.marketplace =
                                  :marketplace
                              AND assignment.listing_id =
                                  :listing_id
                          )
                          AND COALESCE(
                              auction.bulk_lot,
                              false
                          ) = false
                          AND auction.{price_column} > 0
                          AND COALESCE(
                              assignment.match_confidence,
                              0
                          ) >= :minimum_confidence
                        ORDER BY
                            auction.marketplace,
                            auction.listing_id
                        """
                    ),
                    {
                        "pressing_id":
                            pressing_id,
                        "marketplace":
                            marketplace_value,
                        "listing_id":
                            listing_id_value,
                        "minimum_confidence":
                            MINIMUM_ASSIGNMENT_CONFIDENCE,
                    },
                ).mappings()
            )

            target_normalization_ready = bool(
                connection.execute(
                    text(
                        f"""
                        SELECT COALESCE(
                            (
                                base.{normalized_price_column}
                                    > 0
                                AND base.condition_market_factor
                                    > 0
                                AND base
                                    .completeness_market_factor
                                    > 0
                            ),
                            false
                        )
                        FROM analytics
                            .auction_collector_base
                            AS base
                        WHERE base.marketplace =
                                :marketplace
                          AND base.listing_id =
                                :listing_id
                        """
                    ),
                    {
                        "marketplace":
                            marketplace_value,
                        "listing_id":
                            listing_id_value,
                    },
                ).scalar_one()
            )

            normalized_comparable_rows = list(
                connection.execute(
                    text(
                        f"""
                        SELECT
                            base.marketplace,
                            base.listing_id,
                            (
                                base.{normalized_price_column}
                                / NULLIF(
                                    base.condition_market_factor,
                                    0
                                )
                                / NULLIF(
                                    base
                                        .completeness_market_factor,
                                    0
                                )
                            ) AS price_usd
                        FROM analytics
                            .auction_collector_base
                            AS base
                        WHERE base.pressing_id =
                                :pressing_id
                          AND NOT (
                              base.marketplace =
                                  :marketplace
                              AND base.listing_id =
                                  :listing_id
                          )
                          AND COALESCE(
                              base.bulk_lot,
                              false
                          ) = false
                          AND base.{normalized_price_column} > 0
                          AND base.condition_market_factor > 0
                          AND base.completeness_market_factor > 0
                          AND COALESCE(
                              base.pressing_match_confidence,
                              0
                          ) >= :minimum_confidence
                        ORDER BY
                            base.marketplace,
                            base.listing_id
                        """
                    ),
                    {
                        "pressing_id":
                            pressing_id,
                        "marketplace":
                            marketplace_value,
                        "listing_id":
                            listing_id_value,
                        "minimum_confidence":
                            MINIMUM_ASSIGNMENT_CONFIDENCE,
                    },
                ).mappings()
            )

        historical_anchor: (
            HistoricalAnchorSuggestion
            | None
        ) = None

        existing_anchor = (
            existing_analysis[
                "historical_anchor_usd"
            ]
            if existing_analysis is not None
            else None
        )

        if existing_anchor is not None:
            blockers.append(
                "A historical anchor already exists and will "
                "not be replaced automatically."
            )
        elif not target_normalization_ready:
            blockers.append(
                "Historical anchor is blocked because the "
                "target listing is not normalization-ready."
            )
        elif (
            len(normalized_comparable_rows)
            >= minimum_comparables
        ):
            prices = [
                Decimal(
                    str(row["price_usd"])
                )
                for row
                in normalized_comparable_rows
            ]

            historical_anchor = (
                HistoricalAnchorSuggestion(
                    price_basis=price_basis_value,
                    anchor_usd=median_decimal(
                        prices
                    ),
                    sample_count=len(
                        normalized_comparable_rows
                    ),
                    comparable_listings=tuple(
                        (
                            f"{row['marketplace']}/"
                            f"{row['listing_id']}"
                        )
                        for row
                        in normalized_comparable_rows
                    ),
                    rationale=(
                        "Median condition- and completeness-"
                        "adjusted price from normalization-ready, "
                        "high-confidence listings assigned to "
                        "the same exact pressing, excluding "
                        "bulk lots."
                    ),
                )
            )
        else:
            blockers.append(
                "Historical anchor requires at least "
                f"{minimum_comparables} normalization-ready "
                "exact-pressing comparables; found "
                f"{len(normalized_comparable_rows)} of "
                f"{len(comparable_rows)} high-confidence "
                "comparables."
            )

        snapshots = list(
            connection.execute(
                text(
                    """
                    SELECT
                        id,
                        captured_at,
                        price_local,
                        currency,
                        source
                    FROM warehouse.auction_price_snapshot
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    ORDER BY captured_at
                    """
                ),
                {
                    "marketplace":
                        marketplace_value,
                    "listing_id":
                        listing_id_value,
                },
            ).mappings()
        )

        closing_window: (
            ClosingWindowSuggestion
            | None
        ) = None

        existing_closing_evidence = (
            existing_behavior is not None
            and (
                existing_behavior[
                    "closing_window_start_price"
                ]
                is not None
                or existing_behavior[
                    "closing_window_final_price"
                ]
                is not None
            )
        )

        if existing_closing_evidence:
            blockers.append(
                "Closing-window evidence already exists and "
                "will not be replaced automatically."
            )
        else:
            closing_window = select_closing_window(
                snapshots,
                closing_at=listing[
                    "closing_at"
                ],
                final_price=_decimal(
                    listing["final_price"]
                ),
                currency=_text(
                    listing["currency"]
                ),
                maximum_minutes=(
                    closing_window_minutes
                ),
            )

            if closing_window is None:
                blockers.append(
                    "No compatible timestamped price snapshot "
                    "exists inside the requested closing window."
                )

    return EvidenceReport(
        marketplace=marketplace_value,
        listing_id=listing_id_value,
        condition=condition,
        historical_anchor=historical_anchor,
        closing_window=closing_window,
        comparable_count=len(
            comparable_rows
        ),
        snapshot_count=len(snapshots),
        blockers=tuple(blockers),
        normalized_comparable_count=len(
            normalized_comparable_rows
        ),
        normalization_ready=(
            target_normalization_ready
        ),
    )


# historical-anchor-normalization-guard:start
def _historical_anchor_is_still_valid(
    connection: Connection,
    report: EvidenceReport,
) -> bool:
    """Revalidate normalized identities and adjusted median."""
    anchor = report.historical_anchor

    if anchor is None:
        return False

    price_columns = {
        "HAMMER": "price_hammer_usd",
        "GROSS": "price_gross_usd",
        "LANDED": "price_landed_usd",
    }

    price_column = price_columns.get(
        anchor.price_basis
    )

    if price_column is None:
        return False

    target = connection.execute(
        text(
            f"""
            SELECT
                base.pressing_id,
                COALESCE(
                    (
                        base.{price_column} > 0
                        AND base.condition_market_factor > 0
                        AND base.completeness_market_factor > 0
                    ),
                    false
                ) AS normalization_ready
            FROM analytics.auction_collector_base
                AS base
            WHERE base.marketplace = :marketplace
              AND base.listing_id = :listing_id
            """
        ),
        {
            "marketplace":
                report.marketplace,
            "listing_id":
                report.listing_id,
        },
    ).mappings().one_or_none()

    if (
        target is None
        or target["pressing_id"] is None
        or not bool(
            target["normalization_ready"]
        )
    ):
        return False

    rows = list(
        connection.execute(
            text(
                f"""
                SELECT
                    base.marketplace,
                    base.listing_id,
                    (
                        base.{price_column}
                        / NULLIF(
                            base.condition_market_factor,
                            0
                        )
                        / NULLIF(
                            base.completeness_market_factor,
                            0
                        )
                    ) AS price_usd
                FROM analytics.auction_collector_base
                    AS base
                WHERE base.pressing_id = :pressing_id
                  AND NOT (
                      base.marketplace = :marketplace
                      AND base.listing_id = :listing_id
                  )
                  AND COALESCE(
                      base.bulk_lot,
                      false
                  ) = false
                  AND base.{price_column} > 0
                  AND base.condition_market_factor > 0
                  AND base.completeness_market_factor > 0
                  AND COALESCE(
                      base.pressing_match_confidence,
                      0
                  ) >= :minimum_confidence
                ORDER BY
                    base.marketplace,
                    base.listing_id
                """
            ),
            {
                "pressing_id":
                    target["pressing_id"],
                "marketplace":
                    report.marketplace,
                "listing_id":
                    report.listing_id,
                "minimum_confidence":
                    MINIMUM_ASSIGNMENT_CONFIDENCE,
            },
        ).mappings()
    )

    current_identities = {
        (
            f"{row['marketplace']}/"
            f"{row['listing_id']}"
        )
        for row in rows
    }

    expected_identities = set(
        anchor.comparable_listings
    )

    if current_identities != expected_identities:
        return False

    if len(rows) != anchor.sample_count:
        return False

    if not rows:
        return False

    current_median = median_decimal(
        [
            Decimal(
                str(row["price_usd"])
            )
            for row in rows
        ]
    )

    return current_median == anchor.anchor_usd


# historical-anchor-normalization-guard:end


def apply_evidence_report(
    engine: Engine,
    report: EvidenceReport,
) -> tuple[str, ...]:
    """Atomically apply proposals that remain unclaimed."""
    actions: list[str] = []

    if not report.ready_actions:
        return tuple()

    with engine.begin() as connection:
        identity = {
            "marketplace":
                report.marketplace,
            "listing_id":
                report.listing_id,
        }

        if report.condition is not None:
            existing = connection.execute(
                text(
                    """
                    SELECT is_manual_override
                    FROM warehouse
                        .auction_condition_normalization
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    FOR UPDATE
                    """
                ),
                identity,
            ).mappings().one_or_none()

            if not (
                existing is not None
                and existing[
                    "is_manual_override"
                ]
            ):
                condition = report.condition

                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse
                            .auction_condition_normalization (
                                marketplace,
                                listing_id,
                                media_grade_code,
                                cover_grade_code,
                                source_media_condition,
                                source_cover_condition,
                                confidence,
                                is_manual_override,
                                notes,
                                updated_at
                            )
                        VALUES (
                            :marketplace,
                            :listing_id,
                            :media_grade_code,
                            :cover_grade_code,
                            :source_media_condition,
                            :source_cover_condition,
                            :confidence,
                            false,
                            :notes,
                            now()
                        )
                        ON CONFLICT (
                            marketplace,
                            listing_id
                        )
                        DO UPDATE SET
                            media_grade_code =
                                EXCLUDED.media_grade_code,
                            cover_grade_code =
                                EXCLUDED.cover_grade_code,
                            source_media_condition =
                                EXCLUDED
                                    .source_media_condition,
                            source_cover_condition =
                                EXCLUDED
                                    .source_cover_condition,
                            confidence =
                                EXCLUDED.confidence,
                            is_manual_override = false,
                            notes = EXCLUDED.notes,
                            updated_at = now()
                        """
                    ),
                    {
                        **identity,
                        "media_grade_code":
                            condition
                                .media_grade_code,
                        "cover_grade_code":
                            condition
                                .cover_grade_code,
                        "source_media_condition":
                            condition
                                .source_media_condition,
                        "source_cover_condition":
                            condition
                                .source_cover_condition,
                        "confidence":
                            condition.confidence,
                        "notes":
                            (
                                "Evidence assistant: "
                                + condition.rationale
                            ),
                    },
                )

                actions.append("condition")

        if report.closing_window is not None:
            current = connection.execute(
                text(
                    """
                    SELECT *
                    FROM warehouse
                        .auction_behavior_observation
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    FOR UPDATE
                    """
                ),
                identity,
            ).mappings().one_or_none()

            already_present = (
                current is not None
                and (
                    current[
                        "closing_window_start_price"
                    ]
                    is not None
                    or current[
                        "closing_window_final_price"
                    ]
                    is not None
                )
            )

            if not already_present:
                closing = report.closing_window

                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse
                            .auction_behavior_observation (
                                marketplace,
                                listing_id,
                                distinct_bidder_count,
                                distinct_bidder_state,
                                distinct_bidder_source,
                                closing_window_minutes,
                                closing_window_start_price,
                                closing_window_final_price,
                                closing_window_currency,
                                reserve_status,
                                notes,
                                updated_at
                            )
                        VALUES (
                            :marketplace,
                            :listing_id,
                            :distinct_bidder_count,
                            :distinct_bidder_state,
                            :distinct_bidder_source,
                            :closing_window_minutes,
                            :closing_window_start_price,
                            :closing_window_final_price,
                            :closing_window_currency,
                            :reserve_status,
                            :notes,
                            now()
                        )
                        ON CONFLICT (
                            marketplace,
                            listing_id
                        )
                        DO UPDATE SET
                            closing_window_minutes =
                                EXCLUDED
                                    .closing_window_minutes,
                            closing_window_start_price =
                                EXCLUDED
                                    .closing_window_start_price,
                            closing_window_final_price =
                                EXCLUDED
                                    .closing_window_final_price,
                            closing_window_currency =
                                EXCLUDED
                                    .closing_window_currency,
                            notes = EXCLUDED.notes,
                            updated_at = now()
                        """
                    ),
                    {
                        **identity,
                        "distinct_bidder_count":
                            (
                                current[
                                    "distinct_bidder_count"
                                ]
                                if current is not None
                                else None
                            ),
                        "distinct_bidder_state":
                            (
                                current[
                                    "distinct_bidder_state"
                                ]
                                if current is not None
                                else "UNAVAILABLE"
                            ),
                        "distinct_bidder_source":
                            (
                                current[
                                    "distinct_bidder_source"
                                ]
                                if current is not None
                                else None
                            ),
                        "closing_window_minutes":
                            closing
                                .minutes_before_close,
                        "closing_window_start_price":
                            closing.start_price,
                        "closing_window_final_price":
                            closing.final_price,
                        "closing_window_currency":
                            closing.currency,
                        "reserve_status":
                            (
                                current[
                                    "reserve_status"
                                ]
                                if current is not None
                                else None
                            ),
                        "notes":
                            _append_note(
                                (
                                    current["notes"]
                                    if current is not None
                                    else None
                                ),
                                (
                                    "Evidence assistant: "
                                    f"snapshot {closing.snapshot_id}, "
                                    f"source {closing.source}, "
                                    f"captured "
                                    f"{closing.minutes_before_close} "
                                    "minutes before close."
                                ),
                            ),
                    },
                )

                actions.append(
                    "closing_window"
                )

        if report.historical_anchor is not None:
            current = connection.execute(
                text(
                    """
                    SELECT *
                    FROM warehouse.auction_analysis_input
                    WHERE marketplace = :marketplace
                      AND listing_id = :listing_id
                    FOR UPDATE
                    """
                ),
                identity,
            ).mappings().one_or_none()

            existing_anchor = (
                current[
                    "historical_anchor_usd"
                ]
                if current is not None
                else None
            )

            if (
                existing_anchor is None
                and _historical_anchor_is_still_valid(
                    connection,
                    report,
                )
            ):
                anchor = (
                    report.historical_anchor
                )

                connection.execute(
                    text(
                        """
                        INSERT INTO warehouse
                            .auction_analysis_input (
                                marketplace,
                                listing_id,
                                price_basis,
                                completeness_market_factor,
                                condition_factor_override,
                                title_strength_score,
                                market_context_score,
                                manual_auction_behavior_score,
                                expectation_price_usd,
                                historical_anchor_usd,
                                notes,
                                updated_at
                            )
                        VALUES (
                            :marketplace,
                            :listing_id,
                            :price_basis,
                            :completeness_market_factor,
                            :condition_factor_override,
                            :title_strength_score,
                            :market_context_score,
                            :manual_auction_behavior_score,
                            :expectation_price_usd,
                            :historical_anchor_usd,
                            :notes,
                            now()
                        )
                        ON CONFLICT (
                            marketplace,
                            listing_id
                        )
                        DO UPDATE SET
                            historical_anchor_usd =
                                EXCLUDED
                                    .historical_anchor_usd,
                            notes = EXCLUDED.notes,
                            updated_at = now()
                        """
                    ),
                    {
                        **identity,
                        "price_basis":
                            (
                                current["price_basis"]
                                if current is not None
                                else anchor.price_basis
                            ),
                        "completeness_market_factor":
                            (
                                current[
                                    "completeness_market_factor"
                                ]
                                if current is not None
                                else None
                            ),
                        "condition_factor_override":
                            (
                                current[
                                    "condition_factor_override"
                                ]
                                if current is not None
                                else None
                            ),
                        "title_strength_score":
                            (
                                current[
                                    "title_strength_score"
                                ]
                                if current is not None
                                else None
                            ),
                        "market_context_score":
                            (
                                current[
                                    "market_context_score"
                                ]
                                if current is not None
                                else None
                            ),
                        "manual_auction_behavior_score":
                            (
                                current[
                                    "manual_auction_behavior_score"
                                ]
                                if current is not None
                                else None
                            ),
                        "expectation_price_usd":
                            (
                                current[
                                    "expectation_price_usd"
                                ]
                                if current is not None
                                else None
                            ),
                        "historical_anchor_usd":
                            anchor.anchor_usd,
                        "notes":
                            _append_note(
                                (
                                    current["notes"]
                                    if current is not None
                                    else None
                                ),
                                (
                                    "Evidence assistant: "
                                    f"{anchor.sample_count} "
                                    "exact-pressing comparables; "
                                    f"{anchor.price_basis} median "
                                    f"${anchor.anchor_usd}."
                                ),
                            ),
                    },
                )

                actions.append(
                    "historical_anchor"
                )

    return tuple(actions)
