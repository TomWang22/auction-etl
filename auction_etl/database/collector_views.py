"""Own and verify Collector Review database views."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection


EFFECTIVE_VIEW = "warehouse.auction_collector_effective"
REVIEW_VIEW = "warehouse.auction_collector_review"

EFFECTIVE_VIEW_COLUMNS = (
    "id",
    "marketplace",
    "listing_id",
    "auction_url",
    "seller",
    "artist",
    "title",
    "media_type",
    "edition",
    "catalog_number",
    "condition_media",
    "condition_cover",
    "bulk_lot",
    "bid_count",
    "watch_count",
    "start_price",
    "final_price",
    "shipping_price",
    "tax_amount",
    "currency",
    "ended_at",
    "created_at",
    "gross_price",
    "tax_rate",
    "price_includes_tax",
    "disc_count",
    "opening_at",
    "closing_at",
    "current_price_gross",
    "buyout_price_gross",
    "detail_status",
    "detail_fetched_at",
    "fx_rate_to_usd",
    "fx_rate_date",
    "start_price_usd",
    "final_price_usd",
    "shipping_price_usd",
    "tax_usd",
    "gross_price_usd",
    "landed_price_usd",
    "current_price_usd",
    "buyout_price_usd",
    "auction_format",
    "manual_catalog_number",
    "manual_region",
    "manual_media_type",
    "manual_disc_count",
    "manual_bulk_lot",
    "manual_obi",
    "manual_insert_present",
    "manual_poster_present",
    "manual_rental",
    "manual_sticker",
    "manual_promo",
    "manual_sealed",
    "manual_reissue",
    "manual_first_press",
    "manual_importance_score",
    "manual_verdict",
    "manual_condition_media",
    "manual_condition_cover",
    "manual_completeness_notes",
    "manual_collector_notes",
    "effective_catalog_number",
    "effective_region",
    "effective_media_type",
    "effective_disc_count",
    "effective_bulk_lot",
    "effective_obi",
    "effective_insert_present",
    "effective_poster_present",
    "effective_rental",
    "effective_sticker",
    "effective_promo",
    "effective_sealed",
    "effective_reissue",
    "effective_first_press",
    "seller_total_sales",
    "seller_first_sale_at",
    "seller_last_sale_at",
    "seller_average_gross_price",
    "repeat_seller",
    "auction_duration_days",
    "start_to_finish_multiplier",
    "bids_per_day",
    "effective_importance_score",
    "effective_verdict",
    "effective_condition_media",
    "effective_condition_cover",
    "collector_updated_at",
)

REVIEW_VIEW_COLUMNS = (
    "id",
    "marketplace",
    "listing_id",
    "auction_url",
    "seller",
    "artist",
    "title",
    "media_type",
    "edition",
    "catalog_number",
    "condition_media",
    "condition_cover",
    "bulk_lot",
    "bid_count",
    "watch_count",
    "start_price",
    "final_price",
    "shipping_price",
    "tax_amount",
    "currency",
    "ended_at",
    "created_at",
    "gross_price",
    "tax_rate",
    "price_includes_tax",
    "disc_count",
    "opening_at",
    "closing_at",
    "current_price_gross",
    "buyout_price_gross",
    "detail_status",
    "detail_fetched_at",
    "fx_rate_to_usd",
    "fx_rate_date",
    "start_price_usd",
    "final_price_usd",
    "shipping_price_usd",
    "tax_usd",
    "gross_price_usd",
    "landed_price_usd",
    "current_price_usd",
    "buyout_price_usd",
    "auction_format",
    "manual_catalog_number",
    "manual_region",
    "manual_media_type",
    "manual_disc_count",
    "manual_bulk_lot",
    "manual_obi",
    "manual_insert_present",
    "manual_poster_present",
    "manual_rental",
    "manual_sticker",
    "manual_promo",
    "manual_sealed",
    "manual_reissue",
    "manual_first_press",
    "manual_importance_score",
    "manual_verdict",
    "manual_condition_media",
    "manual_condition_cover",
    "manual_completeness_notes",
    "manual_collector_notes",
    "effective_catalog_number",
    "effective_region",
    "effective_media_type",
    "effective_disc_count",
    "effective_bulk_lot",
    "effective_obi",
    "effective_insert_present",
    "effective_poster_present",
    "effective_rental",
    "effective_sticker",
    "effective_promo",
    "effective_sealed",
    "effective_reissue",
    "effective_first_press",
    "seller_total_sales",
    "seller_first_sale_at",
    "seller_last_sale_at",
    "seller_average_gross_price",
    "repeat_seller",
    "auction_duration_days",
    "start_to_finish_multiplier",
    "bids_per_day",
    "effective_importance_score",
    "effective_verdict",
    "effective_condition_media",
    "effective_condition_cover",
    "collector_updated_at",
    "effective_pressing_type",
    "detail_auction_status",
    "detail_condition_text",
    "live_detail_status",
    "live_detail_error_message",
    "live_detail_fetched_at",
)

EFFECTIVE_VIEW_SELECT_SQL = r"""
SELECT a.id,
    a.marketplace,
    a.listing_id,
    a.auction_url,
    a.seller,
    a.artist,
    a.title,
    a.media_type,
    a.edition,
    a.catalog_number,
    a.condition_media,
    a.condition_cover,
    a.bulk_lot,
    a.bid_count,
    a.watch_count,
    a.start_price,
    a.final_price,
    a.shipping_price,
    a.tax_amount,
    a.currency,
    a.ended_at,
    a.created_at,
    a.gross_price,
    a.tax_rate,
    a.price_includes_tax,
    a.disc_count,
    a.opening_at,
    a.closing_at,
    a.current_price_gross,
    a.buyout_price_gross,
    a.detail_status,
    a.detail_fetched_at,
    a.fx_rate_to_usd,
    a.fx_rate_date,
    a.start_price_usd,
    a.final_price_usd,
    a.shipping_price_usd,
    a.tax_usd,
    a.gross_price_usd,
    a.landed_price_usd,
    a.current_price_usd,
    a.buyout_price_usd,
    a.auction_format,
    c.manual_catalog_number,
    c.manual_region,
    c.manual_media_type,
    c.manual_disc_count,
    c.manual_bulk_lot,
    c.manual_obi,
    c.manual_insert_present,
    c.manual_poster_present,
    c.manual_rental,
    c.manual_sticker,
    c.manual_promo,
    c.manual_sealed,
    c.manual_reissue,
    c.manual_first_press,
    c.manual_importance_score,
    c.manual_verdict,
    c.manual_condition_media,
    c.manual_condition_cover,
    c.manual_completeness_notes,
    c.manual_collector_notes,
    COALESCE(c.manual_catalog_number, c.auto_catalog_number, a.catalog_number) AS effective_catalog_number,
    COALESCE(c.manual_region, c.auto_region) AS effective_region,
    COALESCE(c.manual_media_type, c.auto_media_type, a.media_type) AS effective_media_type,
    COALESCE(c.manual_disc_count, c.auto_disc_count, a.disc_count) AS effective_disc_count,
    COALESCE(c.manual_bulk_lot, c.auto_bulk_lot, a.bulk_lot) AS effective_bulk_lot,
    COALESCE(c.manual_obi, c.auto_obi) AS effective_obi,
    COALESCE(c.manual_insert_present, c.auto_insert_present) AS effective_insert_present,
    COALESCE(c.manual_poster_present, c.auto_poster_present) AS effective_poster_present,
    COALESCE(c.manual_rental, c.auto_rental) AS effective_rental,
    COALESCE(c.manual_sticker, c.auto_sticker) AS effective_sticker,
    COALESCE(c.manual_promo, c.auto_promo) AS effective_promo,
    COALESCE(c.manual_sealed, c.auto_sealed) AS effective_sealed,
    COALESCE(c.manual_reissue, c.auto_reissue) AS effective_reissue,
    COALESCE(c.manual_first_press, c.auto_first_press) AS effective_first_press,
    c.seller_total_sales,
    c.seller_first_sale_at,
    c.seller_last_sale_at,
    c.seller_average_gross_price,
    c.repeat_seller,
    c.auction_duration_days,
    c.start_to_finish_multiplier,
    c.bids_per_day,
    COALESCE(c.manual_importance_score, c.auto_importance_score) AS effective_importance_score,
    COALESCE(c.manual_verdict, c.auto_verdict) AS effective_verdict,
    COALESCE(c.manual_condition_media, a.condition_media) AS effective_condition_media,
    COALESCE(c.manual_condition_cover, a.condition_cover) AS effective_condition_cover,
    c.updated_at AS collector_updated_at
   FROM warehouse.auction a
     LEFT JOIN warehouse.auction_collector c ON c.marketplace::text = a.marketplace::text AND c.listing_id::text = a.listing_id::text;
"""

REVIEW_VIEW_SELECT_SQL = r"""
SELECT effective.id,
    effective.marketplace,
    effective.listing_id,
    effective.auction_url,
    effective.seller,
    effective.artist,
    effective.title,
    effective.media_type,
    effective.edition,
    effective.catalog_number,
    effective.condition_media,
    effective.condition_cover,
    effective.bulk_lot,
    effective.bid_count,
    effective.watch_count,
    effective.start_price,
    effective.final_price,
    effective.shipping_price,
    effective.tax_amount,
    effective.currency,
    effective.ended_at,
    effective.created_at,
    effective.gross_price,
    effective.tax_rate,
    effective.price_includes_tax,
    effective.disc_count,
    effective.opening_at,
    effective.closing_at,
    effective.current_price_gross,
    effective.buyout_price_gross,
    effective.detail_status,
    effective.detail_fetched_at,
    effective.fx_rate_to_usd,
    effective.fx_rate_date,
    effective.start_price_usd,
    effective.final_price_usd,
    effective.shipping_price_usd,
    effective.tax_usd,
    effective.gross_price_usd,
    effective.landed_price_usd,
    effective.current_price_usd,
    effective.buyout_price_usd,
    effective.auction_format,
    effective.manual_catalog_number,
    effective.manual_region,
    effective.manual_media_type,
    effective.manual_disc_count,
    effective.manual_bulk_lot,
    effective.manual_obi,
    effective.manual_insert_present,
    effective.manual_poster_present,
    effective.manual_rental,
    effective.manual_sticker,
    effective.manual_promo,
    effective.manual_sealed,
    effective.manual_reissue,
    effective.manual_first_press,
    effective.manual_importance_score,
    effective.manual_verdict,
    effective.manual_condition_media,
    effective.manual_condition_cover,
    effective.manual_completeness_notes,
    effective.manual_collector_notes,
    effective.effective_catalog_number,
    effective.effective_region,
    effective.effective_media_type,
    effective.effective_disc_count,
    effective.effective_bulk_lot,
    effective.effective_obi,
    effective.effective_insert_present,
    effective.effective_poster_present,
    effective.effective_rental,
    effective.effective_sticker,
    effective.effective_promo,
    effective.effective_sealed,
    effective.effective_reissue,
    effective.effective_first_press,
    effective.seller_total_sales,
    effective.seller_first_sale_at,
    effective.seller_last_sale_at,
    effective.seller_average_gross_price,
    effective.repeat_seller,
    effective.auction_duration_days,
    effective.start_to_finish_multiplier,
    effective.bids_per_day,
    effective.effective_importance_score,
    effective.effective_verdict,
    effective.effective_condition_media,
    effective.effective_condition_cover,
    effective.collector_updated_at,
    COALESCE(collector.manual_pressing_type, collector.auto_pressing_type,
        CASE
            WHEN effective.effective_promo IS TRUE THEN 'PROMO_SAMPLE'::text
            WHEN effective.effective_first_press IS TRUE THEN 'FIRST_PRESSING'::text
            WHEN effective.effective_reissue IS TRUE THEN 'REISSUE'::text
            ELSE 'STANDARD'::text
        END::character varying) AS effective_pressing_type,
    detail.auction_status AS detail_auction_status,
    detail.condition_text AS detail_condition_text,
    detail.detail_status AS live_detail_status,
    detail.error_message AS live_detail_error_message,
    detail.fetched_at AS live_detail_fetched_at
   FROM warehouse.auction_collector_effective effective
     LEFT JOIN warehouse.auction_collector collector ON collector.marketplace::text = effective.marketplace::text AND collector.listing_id::text = effective.listing_id::text
     LEFT JOIN warehouse.auction_detail detail ON detail.marketplace::text = effective.marketplace::text AND detail.listing_id::text = effective.listing_id::text;
"""

COLLECTOR_VIEW_DDL = (
    f"DROP VIEW IF EXISTS {REVIEW_VIEW}",
    f"DROP VIEW IF EXISTS {EFFECTIVE_VIEW}",
    f"CREATE VIEW {EFFECTIVE_VIEW} AS\n{EFFECTIVE_VIEW_SELECT_SQL}",
    f"CREATE VIEW {REVIEW_VIEW} AS\n{REVIEW_VIEW_SELECT_SQL}",
)

_REQUIRED_COLUMNS = {
    ("warehouse", "auction"): {
        "id",
        "marketplace",
        "listing_id",
        "auction_url",
        "seller",
        "artist",
        "title",
        "media_type",
        "edition",
        "catalog_number",
        "condition_media",
        "condition_cover",
        "bulk_lot",
        "bid_count",
        "watch_count",
        "start_price",
        "final_price",
        "shipping_price",
        "tax_amount",
        "currency",
        "ended_at",
        "created_at",
        "gross_price",
        "tax_rate",
        "price_includes_tax",
        "disc_count",
        "opening_at",
        "closing_at",
        "current_price_gross",
        "buyout_price_gross",
        "detail_status",
        "detail_fetched_at",
        "fx_rate_to_usd",
        "fx_rate_date",
        "start_price_usd",
        "final_price_usd",
        "shipping_price_usd",
        "tax_usd",
        "gross_price_usd",
        "landed_price_usd",
        "current_price_usd",
        "buyout_price_usd",
        "auction_format",
    },
    ("warehouse", "auction_collector"): {
        "marketplace",
        "listing_id",
        "auto_catalog_number",
        "manual_catalog_number",
        "auto_region",
        "manual_region",
        "auto_media_type",
        "manual_media_type",
        "auto_disc_count",
        "manual_disc_count",
        "auto_bulk_lot",
        "manual_bulk_lot",
        "auto_obi",
        "manual_obi",
        "auto_insert_present",
        "manual_insert_present",
        "auto_poster_present",
        "manual_poster_present",
        "auto_rental",
        "manual_rental",
        "auto_sticker",
        "manual_sticker",
        "auto_promo",
        "manual_promo",
        "auto_sealed",
        "manual_sealed",
        "auto_reissue",
        "manual_reissue",
        "auto_first_press",
        "manual_first_press",
        "seller_total_sales",
        "seller_first_sale_at",
        "seller_last_sale_at",
        "seller_average_gross_price",
        "repeat_seller",
        "auction_duration_days",
        "start_to_finish_multiplier",
        "bids_per_day",
        "auto_importance_score",
        "manual_importance_score",
        "auto_verdict",
        "manual_verdict",
        "manual_condition_media",
        "manual_condition_cover",
        "manual_completeness_notes",
        "manual_collector_notes",
        "auto_pressing_type",
        "manual_pressing_type",
        "updated_at",
    },
    ("warehouse", "auction_detail"): {
        "marketplace",
        "listing_id",
        "auction_status",
        "condition_text",
        "detail_status",
        "error_message",
        "fetched_at",
    },
}


@dataclass(frozen=True)
class CollectorViewState:
    """Verified collector-view cardinality and shape."""

    warehouse_rows: int
    warehouse_unique_rows: int
    collector_rows: int
    collector_unique_rows: int
    effective_rows: int
    effective_unique_rows: int
    review_rows: int
    review_unique_rows: int
    effective_columns: tuple[str, ...]
    review_columns: tuple[str, ...]


def _relation_columns(
    connection: Connection,
    schema_name: str,
    relation_name: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = :relation_name
            ORDER BY ordinal_position
            """
        ),
        {
            "schema_name": schema_name,
            "relation_name": relation_name,
        },
    ).scalars()

    return tuple(str(row) for row in rows)


def _validate_required_columns(connection: Connection) -> None:
    missing_messages: list[str] = []

    for (schema_name, relation_name), required in _REQUIRED_COLUMNS.items():
        available = set(
            _relation_columns(
                connection,
                schema_name,
                relation_name,
            )
        )
        missing = sorted(required - available)

        if missing:
            missing_messages.append(
                f"{schema_name}.{relation_name}: "
                + ", ".join(missing)
            )

    if missing_messages:
        raise RuntimeError(
            "Collector-view prerequisites are missing:\n"
            + "\n".join(missing_messages)
        )


def _unmanaged_dependents(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            """
            WITH managed AS (
                SELECT to_regclass(
                    'warehouse.auction_collector_effective'
                ) AS relation_oid
                UNION ALL
                SELECT to_regclass(
                    'warehouse.auction_collector_review'
                )
            ),
            dependencies AS (
                SELECT DISTINCT
                    source_relation.oid AS source_oid,
                    dependent_relation.oid AS dependent_oid,
                    dependent_namespace.nspname
                        || '.'
                        || dependent_relation.relname
                        AS dependent_name
                FROM pg_rewrite AS rewrite_record
                JOIN pg_class AS dependent_relation
                  ON dependent_relation.oid = rewrite_record.ev_class
                JOIN pg_namespace AS dependent_namespace
                  ON dependent_namespace.oid =
                        dependent_relation.relnamespace
                JOIN pg_depend AS dependency
                  ON dependency.objid = rewrite_record.oid
                JOIN pg_class AS source_relation
                  ON source_relation.oid = dependency.refobjid
                WHERE source_relation.oid IN (
                    SELECT relation_oid
                    FROM managed
                    WHERE relation_oid IS NOT NULL
                )
                  AND dependent_relation.oid <>
                        source_relation.oid
            )
            SELECT dependent_name
            FROM dependencies
            WHERE dependent_oid NOT IN (
                SELECT relation_oid
                FROM managed
                WHERE relation_oid IS NOT NULL
            )
            ORDER BY dependent_name
            """
        )
    ).scalars()

    return tuple(str(row) for row in rows)


def _external_grants(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT
                table_schema
                || '.'
                || table_name
                || ':'
                || grantee
                || ':'
                || privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = 'warehouse'
              AND table_name IN (
                  'auction_collector_effective',
                  'auction_collector_review'
              )
              AND grantee <> current_user
            ORDER BY 1
            """
        )
    ).scalars()

    return tuple(str(row) for row in rows)


def preflight_collector_views(connection: Connection) -> None:
    """Fail before DDL when prerequisites or unmanaged metadata exist."""
    _validate_required_columns(connection)

    dependents = _unmanaged_dependents(connection)

    if dependents:
        raise RuntimeError(
            "Refusing to replace collector views because unmanaged "
            "dependents exist: "
            + ", ".join(dependents)
        )

    grants = _external_grants(connection)

    if grants:
        raise RuntimeError(
            "Refusing to replace collector views because external "
            "grants would be lost: "
            + ", ".join(grants)
        )


def verify_collector_views(
    connection: Connection,
    *,
    require_collector_parity: bool = False,
) -> CollectorViewState:
    """Verify managed view shape and warehouse-key cardinality."""
    counts = connection.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM warehouse.auction),
                (
                    SELECT COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                    FROM warehouse.auction
                ),
                (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector
                ),
                (
                    SELECT COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                    FROM warehouse.auction_collector
                ),
                (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector_effective
                ),
                (
                    SELECT COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                    FROM warehouse.auction_collector_effective
                ),
                (
                    SELECT COUNT(*)
                    FROM warehouse.auction_collector_review
                ),
                (
                    SELECT COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                    FROM warehouse.auction_collector_review
                )
            """
        )
    ).one()

    state = CollectorViewState(
        warehouse_rows=int(counts[0]),
        warehouse_unique_rows=int(counts[1]),
        collector_rows=int(counts[2]),
        collector_unique_rows=int(counts[3]),
        effective_rows=int(counts[4]),
        effective_unique_rows=int(counts[5]),
        review_rows=int(counts[6]),
        review_unique_rows=int(counts[7]),
        effective_columns=_relation_columns(
            connection,
            "warehouse",
            "auction_collector_effective",
        ),
        review_columns=_relation_columns(
            connection,
            "warehouse",
            "auction_collector_review",
        ),
    )

    warehouse_cardinality = (
        state.warehouse_rows,
        state.warehouse_unique_rows,
    )

    if state.warehouse_rows != state.warehouse_unique_rows:
        raise RuntimeError(
            "Warehouse marketplace/listing keys are not unique."
        )

    if state.collector_rows != state.collector_unique_rows:
        raise RuntimeError(
            "Collector marketplace/listing keys are not unique."
        )

    for label, cardinality in (
        (
            "effective",
            (
                state.effective_rows,
                state.effective_unique_rows,
            ),
        ),
        (
            "review",
            (
                state.review_rows,
                state.review_unique_rows,
            ),
        ),
    ):
        if cardinality != warehouse_cardinality:
            raise RuntimeError(
                f"{label} cardinality {cardinality} does not "
                f"match warehouse {warehouse_cardinality}."
            )

    if require_collector_parity:
        collector_cardinality = (
            state.collector_rows,
            state.collector_unique_rows,
        )

        if collector_cardinality != warehouse_cardinality:
            raise RuntimeError(
                "Collector cardinality "
                f"{collector_cardinality} does not match warehouse "
                f"{warehouse_cardinality}."
            )

    if state.effective_columns != EFFECTIVE_VIEW_COLUMNS:
        raise RuntimeError(
            "Effective-view columns differ from the managed definition."
        )

    if state.review_columns != REVIEW_VIEW_COLUMNS:
        raise RuntimeError(
            "Review-view columns differ from the managed definition."
        )

    return state


def install_collector_views(
    connection: Connection,
    *,
    require_collector_parity: bool = False,
) -> CollectorViewState:
    """Replace both managed views atomically and verify the result."""
    preflight_collector_views(connection)

    for statement in COLLECTOR_VIEW_DDL:
        connection.execute(text(statement))

    return verify_collector_views(
        connection,
        require_collector_parity=require_collector_parity,
    )
