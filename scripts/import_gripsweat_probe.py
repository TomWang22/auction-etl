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


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    probe = load_json(args.probe)

    if int(probe.get("database_writes", -1)) != 0:
        raise SystemExit(
            "Probe metadata does not confirm zero database writes."
        )

    source_by_name = {
        str(source["name"]): source
        for source in config
        if source.get("enabled", True)
    }

    pages = probe.get("pages", [])

    if not isinstance(pages, list):
        raise SystemExit("Probe pages must be a list.")

    inserted_or_updated = 0
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

    sale_upsert = text(
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
        ON CONFLICT (source_name, gripsweat_item_key)
        DO UPDATE SET
            configured_artist = EXCLUDED.configured_artist,
            source_query = EXCLUDED.source_query,
            page_number = EXCLUDED.page_number,
            source_position = EXCLUDED.source_position,
            gripsweat_url = EXCLUDED.gripsweat_url,
            title = COALESCE(
                EXCLUDED.title,
                warehouse.gripsweat_sale.title
            ),
            sold_price = COALESCE(
                EXCLUDED.sold_price,
                warehouse.gripsweat_sale.sold_price
            ),
            currency = COALESCE(
                EXCLUDED.currency,
                warehouse.gripsweat_sale.currency
            ),
            sold_at = COALESCE(
                EXCLUDED.sold_at,
                warehouse.gripsweat_sale.sold_at
            ),
            sold_at_text = COALESCE(
                EXCLUDED.sold_at_text,
                warehouse.gripsweat_sale.sold_at_text
            ),
            image_url = COALESCE(
                EXCLUDED.image_url,
                warehouse.gripsweat_sale.image_url
            ),
            original_marketplace = COALESCE(
                EXCLUDED.original_marketplace,
                warehouse.gripsweat_sale.original_marketplace
            ),
            original_listing_id = COALESCE(
                EXCLUDED.original_listing_id,
                warehouse.gripsweat_sale.original_listing_id
            ),
            raw_text = COALESCE(
                EXCLUDED.raw_text,
                warehouse.gripsweat_sale.raw_text
            ),
            last_seen_at = now(),
            updated_at = now()
        """
    )

    with engine.begin() as connection:
        source_ids: dict[str, int] = {}

        for name, source in source_by_name.items():
            source_id = connection.execute(
                source_upsert,
                {
                    "source_name": name,
                    "configured_artist": str(
                        source["artist"]
                    ),
                    "search_query": str(source["query"]),
                    "url_template": str(
                        source["url_template"]
                    ),
                    "sort_by": str(
                        source.get("sort_by", "date")
                    ),
                    "enabled": bool(
                        source.get("enabled", True)
                    ),
                    "max_pages": int(
                        source.get("max_pages", 1)
                    ),
                    "delay_seconds": decimal_or_none(
                        source.get("delay_seconds", 3.0)
                    ),
                },
            ).scalar_one()

            source_ids[name] = int(source_id)

        for page in pages:
            if page.get("error"):
                continue

            source_name = str(
                page.get("source_name", "")
            )

            if source_name not in source_ids:
                continue

            for item in page.get("items", []):
                item_key = str(
                    item.get("gripsweat_item_key", "")
                ).strip()
                item_url = str(
                    item.get("gripsweat_url", "")
                ).strip()

                if not item_key or not item_url:
                    skipped += 1
                    continue

                try:
                    connection.execute(
                        sale_upsert,
                        {
                            "source_id": source_ids[
                                source_name
                            ],
                            "source_name": source_name,
                            "configured_artist": item.get(
                                "configured_artist"
                            ),
                            "source_query": item.get(
                                "source_query"
                            ),
                            "page_number": int(
                                item.get("page_number", 1)
                            ),
                            "source_position": item.get(
                                "position"
                            ),
                            "gripsweat_item_key": item_key,
                            "gripsweat_url": item_url,
                            "title": item.get("title"),
                            "sold_price": decimal_or_none(
                                item.get("sold_price")
                            ),
                            "currency": item.get("currency"),
                            "sold_at": item.get("sold_at"),
                            "sold_at_text": item.get(
                                "sold_at_text"
                            ),
                            "image_url": item.get(
                                "image_url"
                            ),
                            "original_marketplace": item.get(
                                "original_marketplace"
                            ),
                            "original_listing_id": item.get(
                                "original_listing_id"
                            ),
                            "raw_text": item.get("raw_text"),
                        },
                    )
                    inserted_or_updated += 1
                except Exception as exc:
                    skipped += 1
                    print(
                        f"Skipped {source_name}/{item_key}: "
                        f"{exc}"
                    )

    print()
    print("Gripsweat probe import")
    print("----------------------")
    print(f"Inserted/updated: {inserted_or_updated}")
    print(f"Skipped         : {skipped}")

    return 0 if inserted_or_updated > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
