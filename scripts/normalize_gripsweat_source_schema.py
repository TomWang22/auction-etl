#!/usr/bin/env python3
"""Normalize configured Gripsweat source metadata before imports."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, text


@dataclass(frozen=True, slots=True)
class Source:
    source_name: str
    configured_artist: str
    search_query: str
    search_url: str
    sort_by: str
    enabled: bool


def sqlalchemy_url(database_url: str) -> str:
    """Use the installed Psycopg 3 driver explicitly."""
    if database_url.startswith("postgresql+psycopg://"):
        return database_url

    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return database_url


def source_values(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return source identifiers and mappings from supported config layouts."""
    root = payload.get("sources", payload) if isinstance(payload, dict) else payload

    if isinstance(root, dict):
        return [
            (str(key), value)
            for key, value in root.items()
            if isinstance(value, dict)
        ]

    if isinstance(root, list):
        values: list[tuple[str, dict[str, Any]]] = []

        for value in root:
            if not isinstance(value, dict):
                continue

            identifier = (
                value.get("slug")
                or value.get("source")
                or value.get("id")
                or value.get("name")
            )

            if identifier:
                values.append((str(identifier), value))

        return values

    return []


def query_from_url(search_url: str) -> str:
    """Extract a configured search query from a Gripsweat URL."""
    if not search_url:
        return ""

    parameters = parse_qs(urlparse(search_url).query)

    for key in ("query", "q", "search"):
        values = parameters.get(key)

        if values:
            return str(values[0])

    return ""


def load_sources(config_path: Path) -> list[Source]:
    """Load enabled and disabled configured sources."""
    payload: Any = json.loads(config_path.read_text(encoding="utf-8"))
    sources: list[Source] = []

    for fallback_name, value in source_values(payload):
        source_name = str(
            value.get("slug")
            or value.get("source")
            or value.get("id")
            or fallback_name
        ).strip()

        configured_artist = str(
            value.get("configured_artist")
            or value.get("artist")
            or value.get("name")
            or source_name.replace("-", " ").title()
        ).strip()

        search_url = str(
            value.get("search_url")
            or value.get("url")
            or ""
        ).strip()

        search_query = str(
            value.get("search_query")
            or value.get("query")
            or query_from_url(search_url)
            or configured_artist
        ).strip()

        sort_by = str(
            value.get("sort_by")
            or value.get("sort")
            or "date"
        ).strip()

        sources.append(
            Source(
                source_name=source_name,
                configured_artist=configured_artist,
                search_query=search_query,
                search_url=search_url,
                sort_by=sort_by,
                enabled=bool(value.get("enabled", True)),
            )
        )

    return sources


def main() -> int:
    """Normalize defaults and upsert complete configured source rows."""
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://auction:auction@db:5432/auction_warehouse",
    )
    config_path = Path(
        os.environ.get(
            "GRIPSWEAT_CONFIG",
            "config/gripsweat_sources.json",
        )
    )

    if not config_path.is_file():
        raise SystemExit(f"Missing Gripsweat configuration: {config_path}")

    sources = load_sources(config_path)

    if not sources:
        raise SystemExit("No configured Gripsweat sources were found.")

    engine = create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.gripsweat_source
                    ALTER COLUMN search_query SET DEFAULT '',
                    ALTER COLUMN search_url SET DEFAULT '',
                    ALTER COLUMN sort_by SET DEFAULT 'date';

                UPDATE warehouse.gripsweat_source
                SET
                    search_query = COALESCE(search_query, ''),
                    search_url = COALESCE(search_url, ''),
                    sort_by = COALESCE(sort_by, 'date'),
                    updated_at = NOW()
                WHERE search_query IS NULL
                   OR search_url IS NULL
                   OR sort_by IS NULL;
                """
            )
        )

        statement = text(
            """
            INSERT INTO warehouse.gripsweat_source (
                source_name,
                configured_artist,
                search_query,
                search_url,
                sort_by,
                enabled
            )
            VALUES (
                :source_name,
                :configured_artist,
                :search_query,
                :search_url,
                :sort_by,
                :enabled
            )
            ON CONFLICT (source_name)
            DO UPDATE SET
                configured_artist = EXCLUDED.configured_artist,
                search_query = EXCLUDED.search_query,
                search_url = EXCLUDED.search_url,
                sort_by = EXCLUDED.sort_by,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """
        )

        for source in sources:
            connection.execute(
                statement,
                {
                    "source_name": source.source_name,
                    "configured_artist": source.configured_artist,
                    "search_query": source.search_query,
                    "search_url": source.search_url,
                    "sort_by": source.sort_by,
                    "enabled": source.enabled,
                },
            )

    print("Normalized Gripsweat sources")
    print("============================")

    for source in sources:
        print(
            f"{source.source_name}: "
            f"{source.configured_artist} | "
            f"{source.search_query} | "
            f"enabled={source.enabled}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
