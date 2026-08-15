"""Import successful Gripsweat probe records idempotently."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import text

from auction_etl.database.session import engine


DEFAULT_CONFIG = Path("config/gripsweat_sources.json")
DEFAULT_PROBE = Path(
    "logs/gripsweat/probe/gripsweat_probe.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import successful Gripsweat probe records."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--probe",
        type=Path,
        default=DEFAULT_PROBE,
    )
    return parser.parse_args()


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


SALE_INSERT = text(
    """
    INSERT INTO warehouse.gripsweat_sale (
        source_id,
        source_name,
        configured_artist,
        source_query,
        page_number,
        source_position,
        gripsweat_item_key,
        gripsweat_url,
        title,
        sold_price,
        currency,
        sold_at,
        sold_at_text,
        image_url,
        original_marketplace,
        original_listing_id,
        raw_text
    )
    VALUES (
        :source_id,
        :source_name,
        :configured_artist,
        :source_query,
        :page_number,
        :source_position,
        :gripsweat_item_key,
        :gripsweat_url,
        :title,
        :sold_price,
        :currency,
        :sold_at,
        :sold_at_text,
        :image_url,
        :original_marketplace,
        :original_listing_id,
        :raw_text
    )
    ON CONFLICT DO NOTHING
    RETURNING id
    """
)


SALE_IDENTITY_MATCH = text(
    """
    SELECT id
    FROM warehouse.gripsweat_sale
    WHERE
        gripsweat_url = :gripsweat_url
        OR (
            source_name = :source_name
            AND gripsweat_item_key = :gripsweat_item_key
        )
        OR (
            original_marketplace = :original_marketplace
            AND original_listing_id = :original_listing_id
        )
    ORDER BY id
    FOR UPDATE
    """
)


SALE_UPDATE = text(
    """
    UPDATE warehouse.gripsweat_sale
    SET
        configured_artist = :configured_artist,
        source_query = :source_query,
        page_number = :page_number,
        source_position = :source_position,
        gripsweat_url = :gripsweat_url,
        title = COALESCE(
            :title,
            title
        ),
        sold_price = COALESCE(
            :sold_price,
            sold_price
        ),
        currency = COALESCE(
            :currency,
            currency
        ),
        sold_at = COALESCE(
            :sold_at,
            sold_at
        ),
        sold_at_text = COALESCE(
            :sold_at_text,
            sold_at_text
        ),
        image_url = COALESCE(
            :image_url,
            image_url
        ),
        original_marketplace = COALESCE(
            :original_marketplace,
            original_marketplace
        ),
        original_listing_id = COALESCE(
            :original_listing_id,
            original_listing_id
        ),
        raw_text = COALESCE(
            :raw_text,
            raw_text
        ),
        last_seen_at = now(),
        updated_at = now()
    WHERE id = :sale_id
    """
)


def build_sale_parameters(
    *,
    source_id: int,
    source_name: str,
    item_key: str,
    item_url: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    """Build the normalized bind parameters for one probed sale."""

    return {
        "source_id":
            source_id,
        "source_name":
            source_name,
        "configured_artist":
            item.get(
                "configured_artist"
            ),
        "source_query":
            item.get(
                "source_query"
            ),
        "page_number":
            int(
                item.get(
                    "page_number",
                    1,
                )
            ),
        "source_position":
            item.get(
                "position"
            ),
        "gripsweat_item_key":
            item_key,
        "gripsweat_url":
            item_url,
        "title":
            item.get(
                "title"
            ),
        "sold_price":
            decimal_or_none(
                item.get(
                    "sold_price"
                )
            ),
        "currency":
            item.get(
                "currency"
            ),
        "sold_at":
            item.get(
                "sold_at"
            ),
        "sold_at_text":
            item.get(
                "sold_at_text"
            ),
        "image_url":
            item.get(
                "image_url"
            ),
        "original_marketplace":
            item.get(
                "original_marketplace"
            ),
        "original_listing_id":
            item.get(
                "original_listing_id"
            ),
        "raw_text":
            item.get(
                "raw_text"
            ),
    }


def write_sale(
    connection: Any,
    parameters: dict[str, Any],
) -> str:
    """Insert or update one sale across every enforced identity."""

    with connection.begin_nested():
        inserted_id = connection.execute(
            SALE_INSERT,
            parameters,
        ).scalar_one_or_none()

        if inserted_id is not None:
            return "inserted"

        matching_ids = sorted(
            {
                int(value)
                for value in connection.execute(
                    SALE_IDENTITY_MATCH,
                    parameters,
                ).scalars().all()
            }
        )

        if not matching_ids:
            raise RuntimeError(
                "A unique constraint rejected the sale, but no "
                "known Gripsweat identity resolved the existing row."
            )

        if len(matching_ids) != 1:
            raise RuntimeError(
                "Gripsweat identities resolve to different existing "
                "rows; refusing an automatic merge: "
                + ", ".join(
                    str(value)
                    for value in matching_ids
                )
            )

        connection.execute(
            SALE_UPDATE,
            {
                **parameters,
                "sale_id":
                    matching_ids[0],
            },
        )

        return "updated"


def main() -> int:
    """Import successful probe rows idempotently."""

    args = parse_args()
    config = load_json(args.config)
    probe = load_json(args.probe)

    if int(
        probe.get(
            "database_writes",
            -1,
        )
    ) != 0:
        raise SystemExit(
            "Probe metadata does not confirm zero database writes."
        )

    source_by_name = {
        str(source["name"]):
            source
        for source in config
        if source.get(
            "enabled",
            True,
        )
    }

    pages = probe.get(
        "pages",
        [],
    )

    if not isinstance(
        pages,
        list,
    ):
        raise SystemExit(
            "Probe pages must be a list."
        )

    inserted = 0
    updated = 0
    skipped = 0

    source_upsert = text(
        """
        INSERT INTO warehouse.gripsweat_source (
            source_name,
            configured_artist,
            search_query,
            url_template,
            sort_by,
            enabled,
            max_pages,
            delay_seconds
        )
        VALUES (
            :source_name,
            :configured_artist,
            :search_query,
            :url_template,
            :sort_by,
            :enabled,
            :max_pages,
            :delay_seconds
        )
        ON CONFLICT (source_name)
        DO UPDATE SET
            configured_artist = EXCLUDED.configured_artist,
            search_query = EXCLUDED.search_query,
            url_template = EXCLUDED.url_template,
            sort_by = EXCLUDED.sort_by,
            enabled = EXCLUDED.enabled,
            max_pages = EXCLUDED.max_pages,
            delay_seconds = EXCLUDED.delay_seconds,
            updated_at = now()
        RETURNING id
        """
    )

    with engine.begin() as connection:
        source_ids: dict[str, int] = {}

        for name, source in source_by_name.items():
            source_id = connection.execute(
                source_upsert,
                {
                    "source_name":
                        name,
                    "configured_artist":
                        str(
                            source[
                                "artist"
                            ]
                        ),
                    "search_query":
                        str(
                            source[
                                "query"
                            ]
                        ),
                    "url_template":
                        str(
                            source[
                                "url_template"
                            ]
                        ),
                    "sort_by":
                        str(
                            source.get(
                                "sort_by",
                                "date",
                            )
                        ),
                    "enabled":
                        bool(
                            source.get(
                                "enabled",
                                True,
                            )
                        ),
                    "max_pages":
                        int(
                            source.get(
                                "max_pages",
                                1,
                            )
                        ),
                    "delay_seconds":
                        decimal_or_none(
                            source.get(
                                "delay_seconds",
                                3.0,
                            )
                        ),
                },
            ).scalar_one()

            source_ids[
                name
            ] = int(
                source_id
            )

        for page in pages:
            if page.get(
                "error"
            ):
                continue

            source_name = str(
                page.get(
                    "source_name",
                    "",
                )
            )

            if source_name not in source_ids:
                continue

            for item in page.get(
                "items",
                [],
            ):
                item_key = str(
                    item.get(
                        "gripsweat_item_key",
                        "",
                    )
                ).strip()

                item_url = str(
                    item.get(
                        "gripsweat_url",
                        "",
                    )
                ).strip()

                if not item_key or not item_url:
                    skipped += 1
                    continue

                parameters = build_sale_parameters(
                    source_id=source_ids[
                        source_name
                    ],
                    source_name=source_name,
                    item_key=item_key,
                    item_url=item_url,
                    item=item,
                )

                try:
                    action = write_sale(
                        connection,
                        parameters,
                    )
                except Exception as exc:
                    skipped += 1

                    print(
                        f"Skipped {source_name}/{item_key}: "
                        f"{exc}"
                    )

                    continue

                if action == "inserted":
                    inserted += 1
                elif action == "updated":
                    updated += 1
                else:
                    raise RuntimeError(
                        "Unexpected sale-write result: "
                        f"{action!r}"
                    )

    inserted_or_updated = (
        inserted
        + updated
    )

    print()
    print("Gripsweat probe import")
    print("----------------------")
    print(
        f"Inserted/updated: {inserted_or_updated}"
    )
    print(
        f"Inserted        : {inserted}"
    )
    print(
        f"Updated         : {updated}"
    )
    print(
        f"Skipped         : {skipped}"
    )

    return (
        0
        if inserted_or_updated > 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
