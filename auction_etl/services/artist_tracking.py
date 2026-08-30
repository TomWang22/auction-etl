"""Runtime-backed configuration for artist marketplace tracking."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import quote_plus
from urllib.parse import unquote_plus
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from auction_etl.services.account_scope import account_transaction


STATE_SCHEMA = "auction-etl-artist-tracking/v1"

STATE_ENV = "AUCTION_ARTIST_TRACKING_STATE"
RUNTIME_DIR_ENV = "AUCTION_ETL_RUNTIME_DIR"

EBAY_CONFIG_ENV = "AUCTION_EBAY_SOURCES_CONFIG"
GRIPSWEAT_CONFIG_ENV = "AUCTION_GRIPSWEAT_SOURCES_CONFIG"

SUPPORTED_MARKETPLACES = (
    "ebay",
    "gripsweat",
)

MARKETPLACE_LABELS = {
    "ebay": "eBay",
    "gripsweat": "Gripsweat",
}

REPOSITORY_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

DEFAULT_EBAY_CONFIG = (
    REPOSITORY_ROOT
    / "config"
    / "ebay_sources.json"
)

DEFAULT_GRIPSWEAT_CONFIG = (
    REPOSITORY_ROOT
    / "config"
    / "gripsweat_sources.json"
)


def runtime_root() -> Path:
    """Return the writable application runtime directory."""

    configured = os.environ.get(
        RUNTIME_DIR_ENV,
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser()

    return (
        Path.home()
        / ".auction-etl"
        / "runtime"
    )


def default_state_path() -> Path:
    """Return the persistent runtime artist state file."""

    configured = os.environ.get(
        STATE_ENV,
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser()

    return (
        runtime_root()
        / "artist-tracking"
        / "tracked-artists.json"
    )


def effective_config_directory() -> Path:
    """Return the generated marketplace configuration directory."""

    return (
        runtime_root()
        / "artist-tracking"
        / "effective"
    )


def normalize_query(value: str) -> str:
    """Normalize a human-entered artist/search value."""

    return " ".join(
        value.strip().split()
    )


def normalized_key(value: str) -> str:
    """Return a stable comparison key."""

    return normalize_query(
        value
    ).casefold()


def slugify(value: str) -> str:
    """Return a filesystem- and configuration-safe identifier."""

    normalized = normalize_query(
        value
    ).casefold()

    slug = re.sub(
        r"[^\w]+",
        "-",
        normalized,
        flags=re.UNICODE,
    ).strip("-_")

    if not slug:
        raise ValueError(
            "Artist name must contain at least one usable character."
        )

    return slug


def marketplace_label(
    marketplace: str,
) -> str:
    """Return a product-facing marketplace name."""

    return MARKETPLACE_LABELS.get(
        marketplace,
        marketplace,
    )


def build_ebay_search_url(
    query: str,
) -> str:
    """Generate an eBay completed/sold search URL."""

    encoded = quote_plus(
        normalize_query(query)
    )

    return (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={encoded}"
        "&_sacat=176985"
        "&_from=R40"
        "&rt=nc"
        "&LH_Complete=1"
        "&LH_Sold=1"
        "&_sop=13"
        "&_ipg=240"
    )


def build_gripsweat_search_url(
    query: str,
    *,
    page: int = 1,
    sort_by: str = "date",
) -> str:
    """Generate a Gripsweat search URL."""

    encoded_query = quote_plus(
        normalize_query(query)
    )

    encoded_sort = quote_plus(
        sort_by
    )

    return (
        "https://gripsweat.com/search/"
        f"?query={encoded_query}"
        f"&page={page}"
        f"&sort_by={encoded_sort}"
    )


def _load_json(
    path: Path,
) -> Any:
    """Load JSON from disk."""

    return json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )


def _atomic_write_json(
    path: Path,
    payload: Any,
) -> None:
    """Write JSON atomically."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )

    temporary = Path(
        handle.name
    )

    try:
        with handle:
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )

            handle.write(
                "\n"
            )

        os.replace(
            temporary,
            path,
        )

    finally:
        if temporary.exists():
            temporary.unlink()


def _source_values(
    payload: Any,
) -> list[tuple[str, dict[str, Any]]]:
    """Normalize supported marketplace config collection shapes."""

    if isinstance(
        payload,
        list,
    ):
        return [
            (
                str(index + 1),
                value,
            )
            for index, value
            in enumerate(
                payload
            )
            if isinstance(
                value,
                dict,
            )
        ]

    if not isinstance(
        payload,
        dict,
    ):
        return []

    for key in (
        "sources",
        "artists",
        "searches",
        "profiles",
    ):
        nested = payload.get(
            key
        )

        if isinstance(
            nested,
            list,
        ):
            return [
                (
                    str(index + 1),
                    value,
                )
                for index, value
                in enumerate(
                    nested
                )
                if isinstance(
                    value,
                    dict,
                )
            ]

        if isinstance(
            nested,
            dict,
        ):
            return [
                (
                    str(name),
                    value,
                )
                for name, value
                in nested.items()
                if isinstance(
                    value,
                    dict,
                )
            ]

    dictionary_entries = [
        (
            str(name),
            value,
        )
        for name, value
        in payload.items()
        if isinstance(
            value,
            dict,
        )
    ]

    return dictionary_entries


def _replace_source_values(
    payload: Any,
    sources: list[dict[str, Any]],
) -> Any:
    """Replace source entries while preserving the config envelope."""

    if isinstance(
        payload,
        list,
    ):
        return sources

    if not isinstance(
        payload,
        dict,
    ):
        return sources

    for key in (
        "sources",
        "artists",
        "searches",
        "profiles",
    ):
        nested = payload.get(
            key
        )

        if isinstance(
            nested,
            list,
        ):
            updated = deepcopy(
                payload
            )

            updated[
                key
            ] = sources

            return updated

        if isinstance(
            nested,
            dict,
        ):
            updated = deepcopy(
                payload
            )

            updated[
                key
            ] = {
                str(
                    source.get(
                        "name",
                        index + 1,
                    )
                ): source
                for index, source
                in enumerate(
                    sources
                )
            }

            return updated

    if all(
        isinstance(
            value,
            dict,
        )
        for value
        in payload.values()
    ):
        return {
            str(
                source.get(
                    "name",
                    index + 1,
                )
            ): source
            for index, source
            in enumerate(
                sources
            )
        }

    return sources


def _first_text(
    value: dict[str, Any],
    *keys: str,
) -> str:
    """Return the first non-empty string field."""

    for key in keys:
        candidate = value.get(
            key
        )

        if candidate is None:
            continue

        text = str(
            candidate
        ).strip()

        if text:
            return text

    return ""


def _query_from_url(
    url: str,
) -> str:
    """Extract a search term from a marketplace URL."""

    if not url:
        return ""

    try:
        parameters = parse_qs(
            urlsplit(
                url
            ).query
        )

    except ValueError:
        return ""

    for key in (
        "_nkw",
        "query",
        "q",
        "search",
        "keyword",
    ):
        values = parameters.get(
            key
        )

        if values:
            return normalize_query(
                unquote_plus(
                    str(
                        values[0]
                    )
                )
            )

    return ""


def _display_name_from_query(
    query: str,
) -> str:
    """Produce a readable initial display name from a search term."""

    normalized = normalize_query(
        query
    )

    if normalized == normalized.casefold():
        return " ".join(
            word.capitalize()
            for word
            in normalized.split()
        )

    return normalized


def _new_artist(
    name: str,
    query: str,
) -> dict[str, Any]:
    """Create one normalized artist record."""

    return {
        "id": slugify(
            query
        ),
        "name": normalize_query(
            name
        ),
        "query": normalize_query(
            query
        ),
        "enabled": True,
        "targets": {},
    }


def _target_from_legacy_source(
    marketplace: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    """Preserve a production source as a legacy marketplace target."""

    metadata: dict[str, str] = {}

    if marketplace == "ebay":
        seller = _first_text(
            source,
            "seller",
            "seller_name",
            "store",
        )

        profile = _first_text(
            source,
            "profile",
            "browser_profile",
        )

        if seller:
            metadata[
                "seller"
            ] = seller

        if profile:
            metadata[
                "profile"
            ] = profile

    return {
        "enabled": bool(
            source.get(
                "enabled",
                True,
            )
        ),
        "mode": "legacy",
        "source": deepcopy(
            source
        ),
        "metadata": metadata,
    }


def seed_from_legacy_configs(
    *,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> dict[str, Any]:
    """Build the initial runtime model from existing production configs."""

    artists: dict[
        str,
        dict[str, Any],
    ] = {}

    if ebay_config.exists():
        payload = _load_json(
            ebay_config
        )

        for _fallback, source in _source_values(
            payload
        ):
            configured_url = _first_text(
                source,
                "search_url",
                "url",
                "url_template",
            )

            query = _first_text(
                source,
                "search_query",
                "query",
                "keyword",
                "search",
            )

            if not query:
                query = _query_from_url(
                    configured_url
                )

            if not query:
                continue

            key = normalized_key(
                query
            )

            artist = artists.get(
                key
            )

            if artist is None:
                artist = _new_artist(
                    _display_name_from_query(
                        query
                    ),
                    query,
                )

                artists[
                    key
                ] = artist

            artist[
                "targets"
            ][
                "ebay"
            ] = _target_from_legacy_source(
                "ebay",
                source,
            )

    if gripsweat_config.exists():
        payload = _load_json(
            gripsweat_config
        )

        for _fallback, source in _source_values(
            payload
        ):
            query = _first_text(
                source,
                "query",
                "search_query",
                "keyword",
                "search",
            )

            artist_name = _first_text(
                source,
                "artist",
                "artist_name",
            )

            if not query:
                configured_url = _first_text(
                    source,
                    "url",
                    "search_url",
                )

                query = _query_from_url(
                    configured_url
                )

            if not query:
                continue

            if not artist_name:
                artist_name = _display_name_from_query(
                    query
                )

            key = normalized_key(
                query
            )

            artist = artists.get(
                key
            )

            if artist is None:
                artist = _new_artist(
                    artist_name,
                    query,
                )

                artists[
                    key
                ] = artist

            elif (
                artist_name
                and len(
                    artist_name
                )
                > len(
                    artist[
                        "name"
                    ]
                )
            ):
                artist[
                    "name"
                ] = artist_name

            artist[
                "targets"
            ][
                "gripsweat"
            ] = _target_from_legacy_source(
                "gripsweat",
                source,
            )

    return {
        "schema": STATE_SCHEMA,
        "artists": sorted(
            artists.values(),
            key=lambda value: str(
                value[
                    "name"
                ]
            ).casefold(),
        ),
    }


def _validate_state(
    payload: Any,
) -> dict[str, Any]:
    """Validate the persisted runtime state."""

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Artist tracking state must be a JSON object."
        )

    schema = payload.get(
        "schema"
    )

    if schema != STATE_SCHEMA:
        raise ValueError(
            "Unsupported artist tracking state schema: "
            f"{schema!r}"
        )

    artists = payload.get(
        "artists"
    )

    if not isinstance(
        artists,
        list,
    ):
        raise ValueError(
            "Artist tracking state must contain an artists list."
        )

    return payload


def load_tracking_state(
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> dict[str, Any]:
    """Load runtime state, falling back to current production config."""

    path = (
        state_path
        or default_state_path()
    )

    if path.exists():
        return _validate_state(
            _load_json(
                path
            )
        )

    return seed_from_legacy_configs(
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )


def ensure_tracking_state(
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> dict[str, Any]:
    """Persist the legacy seed the first time the user changes tracking."""

    path = (
        state_path
        or default_state_path()
    )

    state = load_tracking_state(
        state_path=path,
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )

    if not path.exists():
        _atomic_write_json(
            path,
            state,
        )

    return state



def _account_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Return a validated account/user UUID."""
    if isinstance(value, uuid.UUID):
        return value

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid UUID: {value!r}") from exc


def _sqlalchemy_database_url(value: str) -> str:
    """Normalize a PostgreSQL URL for SQLAlchemy + Psycopg 3."""
    database_url = value.strip()
    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )
    return database_url


def _runtime_account_engine() -> Engine:
    """Build the account-aware runtime engine from DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required when AUCTION_ACCOUNT_ID is set."
        )

    return create_engine(
        _sqlalchemy_database_url(database_url),
        pool_pre_ping=True,
        future=True,
    )


def list_account_tracked_artists(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
) -> list[dict[str, Any]]:
    """Return tracked artists owned by exactly one account."""
    validated_account_id = _account_uuid(account_id)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    artist.id,
                    artist.name,
                    artist.normalized_name,
                    artist.enabled,
                    artist.legacy_payload,
                    marketplace.marketplace,
                    marketplace.enabled AS marketplace_enabled,
                    marketplace.search_query,
                    marketplace.search_url,
                    marketplace.config_json
                FROM account.tracked_artist AS artist
                LEFT JOIN account.artist_marketplace AS marketplace
                  ON marketplace.tracked_artist_id = artist.id
                WHERE artist.account_id = :account_id
                ORDER BY
                    lower(artist.name),
                    artist.id,
                    marketplace.marketplace
                """
            ),
            {"account_id": validated_account_id},
        ).mappings().all()

    artists: dict[str, dict[str, Any]] = {}

    for row in rows:
        artist_id = str(row["id"])
        artist = artists.get(artist_id)

        if artist is None:
            legacy_payload = row.get("legacy_payload")
            if not isinstance(legacy_payload, dict):
                legacy_payload = {}

            query = normalize_query(
                str(legacy_payload.get("query") or row["name"])
            )

            artist = {
                "id": artist_id,
                "name": str(row["name"]),
                "query": query,
                "enabled": bool(row["enabled"]),
                "targets": {},
            }
            artists[artist_id] = artist

        marketplace = row.get("marketplace")
        if marketplace is None:
            continue

        marketplace_key = str(marketplace).casefold()
        if marketplace_key not in SUPPORTED_MARKETPLACES:
            continue

        config_json = row.get("config_json")
        metadata = (
            dict(config_json)
            if isinstance(config_json, dict)
            else {}
        )

        artist["targets"][marketplace_key] = {
            "enabled": bool(row["marketplace_enabled"]),
            "mode": "database",
            "source": None,
            "metadata": metadata,
            "search_query": str(row.get("search_query") or ""),
            "search_url": str(row.get("search_url") or ""),
        }

    return sorted(
        artists.values(),
        key=lambda value: str(value["name"]).casefold(),
    )


def upsert_account_artist(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    name: str,
    marketplaces: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Create/update one account-owned artist and marketplace targets."""
    validated_account_id = _account_uuid(account_id)
    validated_user_id = _account_uuid(user_id)
    artist_name = normalize_query(name)

    if not artist_name:
        raise ValueError("Artist name is required.")

    selected = {
        str(marketplace).strip().casefold()
        for marketplace in marketplaces
    }
    unsupported = selected - set(SUPPORTED_MARKETPLACES)

    if unsupported:
        raise ValueError(
            "Unsupported marketplaces: "
            + ", ".join(sorted(unsupported))
        )

    if not selected:
        raise ValueError("Choose at least one marketplace.")

    normalized_name = normalized_key(artist_name)
    generated_id = uuid.uuid5(
        validated_account_id,
        f"tracked-artist:{normalized_name}",
    )

    legacy_payload = json.dumps(
        {
            "query": artist_name,
            "source": "phase-d4-account-runtime",
        },
        sort_keys=True,
    )

    with account_transaction(
        engine,
        account_id=validated_account_id,
        user_id=validated_user_id,
    ) as connection:
        artist_id = connection.execute(
            text(
                """
                INSERT INTO account.tracked_artist (
                    id,
                    account_id,
                    name,
                    normalized_name,
                    enabled,
                    legacy_payload
                )
                VALUES (
                    :id,
                    :account_id,
                    :name,
                    :normalized_name,
                    TRUE,
                    CAST(:legacy_payload AS jsonb)
                )
                ON CONFLICT (account_id, normalized_name)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    enabled = TRUE,
                    legacy_payload = EXCLUDED.legacy_payload,
                    updated_at = now()
                RETURNING id
                """
            ),
            {
                "id": generated_id,
                "account_id": validated_account_id,
                "name": artist_name,
                "normalized_name": normalized_name,
                "legacy_payload": legacy_payload,
            },
        ).scalar_one()

        for marketplace in SUPPORTED_MARKETPLACES:
            enabled = marketplace in selected
            search_url = (
                build_ebay_search_url(artist_name)
                if marketplace == "ebay"
                else build_gripsweat_search_url(artist_name)
            )

            connection.execute(
                text(
                    """
                    INSERT INTO account.artist_marketplace (
                        tracked_artist_id,
                        marketplace,
                        enabled,
                        search_query,
                        search_url,
                        config_json
                    )
                    VALUES (
                        :tracked_artist_id,
                        :marketplace,
                        :enabled,
                        :search_query,
                        :search_url,
                        '{}'::jsonb
                    )
                    ON CONFLICT (tracked_artist_id, marketplace)
                    DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        search_query = EXCLUDED.search_query,
                        search_url = EXCLUDED.search_url,
                        updated_at = now()
                    """
                ),
                {
                    "tracked_artist_id": artist_id,
                    "marketplace": marketplace,
                    "enabled": enabled,
                    "search_query": artist_name,
                    "search_url": search_url,
                },
            )

    artists = list_account_tracked_artists(
        engine,
        account_id=validated_account_id,
    )

    for artist in artists:
        if str(artist["id"]) == str(artist_id):
            return artist

    raise RuntimeError(
        f"Account artist {artist_id} disappeared after upsert."
    )


def set_account_artist_enabled(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    artist_id: uuid.UUID | str,
    enabled: bool,
) -> None:
    """Pause/resume one artist only within the owning account."""
    validated_account_id = _account_uuid(account_id)
    validated_user_id = _account_uuid(user_id)
    validated_artist_id = _account_uuid(artist_id)

    with account_transaction(
        engine,
        account_id=validated_account_id,
        user_id=validated_user_id,
    ) as connection:
        result = connection.execute(
            text(
                """
                UPDATE account.tracked_artist
                SET
                    enabled = :enabled,
                    updated_at = now()
                WHERE id = :artist_id
                  AND account_id = :account_id
                """
            ),
            {
                "enabled": bool(enabled),
                "artist_id": validated_artist_id,
                "account_id": validated_account_id,
            },
        )

        if result.rowcount != 1:
            raise KeyError(
                f"Unknown account artist: {validated_artist_id}"
            )


def remove_account_artist(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    artist_id: uuid.UUID | str,
) -> None:
    """Delete one artist only from the owning account."""
    validated_account_id = _account_uuid(account_id)
    validated_user_id = _account_uuid(user_id)
    validated_artist_id = _account_uuid(artist_id)

    with account_transaction(
        engine,
        account_id=validated_account_id,
        user_id=validated_user_id,
    ) as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM account.tracked_artist
                WHERE id = :artist_id
                  AND account_id = :account_id
                """
            ),
            {
                "artist_id": validated_artist_id,
                "account_id": validated_account_id,
            },
        )

        if result.rowcount != 1:
            raise KeyError(
                f"Unknown account artist: {validated_artist_id}"
            )


def account_tracking_state(
    engine: Engine,
    *,
    account_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Return the product state shape backed by account-owned PostgreSQL."""
    return {
        "schema": STATE_SCHEMA,
        "artists": list_account_tracked_artists(
            engine,
            account_id=account_id,
        ),
    }


def list_tracked_artists(
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> list[dict[str, Any]]:
    """Return product-facing artist tracking records."""

    state = load_tracking_state(
        state_path=state_path,
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )

    return sorted(
        deepcopy(
            state[
                "artists"
            ]
        ),
        key=lambda value: str(
            value[
                "name"
            ]
        ).casefold(),
    )


def upsert_artist(
    name: str,
    marketplaces: list[str] | tuple[str, ...],
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> dict[str, Any]:
    """Add an artist or update which marketplaces track it."""

    artist_name = normalize_query(
        name
    )

    if not artist_name:
        raise ValueError(
            "Artist name is required."
        )

    selected = {
        str(
            marketplace
        ).strip().casefold()
        for marketplace
        in marketplaces
    }

    unsupported = (
        selected
        - set(
            SUPPORTED_MARKETPLACES
        )
    )

    if unsupported:
        raise ValueError(
            "Unsupported marketplaces: "
            + ", ".join(
                sorted(
                    unsupported
                )
            )
        )

    if not selected:
        raise ValueError(
            "Choose at least one marketplace."
        )

    path = (
        state_path
        or default_state_path()
    )

    state = ensure_tracking_state(
        state_path=path,
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )

    key = normalized_key(
        artist_name
    )

    artist: dict[str, Any] | None = None

    for candidate in state[
        "artists"
    ]:
        if normalized_key(
            str(
                candidate.get(
                    "query",
                    "",
                )
            )
        ) == key:
            artist = candidate
            break

        if normalized_key(
            str(
                candidate.get(
                    "name",
                    "",
                )
            )
        ) == key:
            artist = candidate
            break

    if artist is None:
        artist = _new_artist(
            artist_name,
            artist_name,
        )

        state[
            "artists"
        ].append(
            artist
        )

    artist[
        "name"
    ] = artist_name

    artist[
        "query"
    ] = artist_name

    artist[
        "enabled"
    ] = True

    targets = artist.setdefault(
        "targets",
        {},
    )

    for marketplace in SUPPORTED_MARKETPLACES:
        target = targets.get(
            marketplace
        )

        if target is None:
            if marketplace in selected:
                targets[
                    marketplace
                ] = {
                    "enabled": True,
                    "mode": "generated",
                    "source": None,
                    "metadata": {},
                }

            continue

        target[
            "enabled"
        ] = marketplace in selected

    state[
        "artists"
    ] = sorted(
        state[
            "artists"
        ],
        key=lambda value: str(
            value[
                "name"
            ]
        ).casefold(),
    )

    _atomic_write_json(
        path,
        state,
    )

    return deepcopy(
        artist
    )


def set_artist_enabled(
    artist_id: str,
    enabled: bool,
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> None:
    """Pause or resume one tracked artist."""

    path = (
        state_path
        or default_state_path()
    )

    state = ensure_tracking_state(
        state_path=path,
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )

    for artist in state[
        "artists"
    ]:
        if artist.get(
            "id"
        ) == artist_id:
            artist[
                "enabled"
            ] = bool(
                enabled
            )

            _atomic_write_json(
                path,
                state,
            )

            return

    raise KeyError(
        f"Unknown artist: {artist_id}"
    )


def remove_artist(
    artist_id: str,
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
) -> None:
    """Remove an artist from future marketplace refreshes."""

    path = (
        state_path
        or default_state_path()
    )

    state = ensure_tracking_state(
        state_path=path,
        ebay_config=ebay_config,
        gripsweat_config=gripsweat_config,
    )

    original_count = len(
        state[
            "artists"
        ]
    )

    state[
        "artists"
    ] = [
        artist
        for artist
        in state[
            "artists"
        ]
        if artist.get(
            "id"
        ) != artist_id
    ]

    if len(
        state[
            "artists"
        ]
    ) == original_count:
        raise KeyError(
            f"Unknown artist: {artist_id}"
        )

    _atomic_write_json(
        path,
        state,
    )


def target_preview_url(
    artist: dict[str, Any],
    marketplace: str,
) -> str:
    """Return the search URL shown to the user."""

    target = (
        artist.get(
            "targets",
            {}
        ).get(
            marketplace,
            {}
        )
    )

    source = target.get(
        "source"
    )

    if isinstance(
        source,
        dict,
    ):
        configured = _first_text(
            source,
            "search_url",
            "url",
        )

        if configured:
            return configured

        template = _first_text(
            source,
            "url_template",
        )

        if template:
            try:
                return template.format(
                    query=quote_plus(
                        str(
                            artist[
                                "query"
                            ]
                        )
                    ),
                    page=1,
                    sort_by="date",
                )

            except (
                KeyError,
                IndexError,
                ValueError,
            ):
                return template

    query = str(
        artist[
            "query"
        ]
    )

    if marketplace == "ebay":
        return build_ebay_search_url(
            query
        )

    if marketplace == "gripsweat":
        return build_gripsweat_search_url(
            query
        )

    return ""


def _first_source_template(
    payload: Any,
) -> dict[str, Any]:
    """Return a copy of the first configured marketplace source."""

    values = _source_values(
        payload
    )

    if not values:
        return {}

    return deepcopy(
        values[0][1]
    )


def _generated_ebay_source(
    artist: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    """Generate one eBay crawler source without seller restriction."""

    source = deepcopy(
        template
    )

    slug = str(
        artist[
            "id"
        ]
    )

    query = str(
        artist[
            "query"
        ]
    )

    source[
        "name"
    ] = slug

    source[
        "url"
    ] = build_ebay_search_url(
        query
    )

    source[
        "enabled"
    ] = True

    if "profile" in source:
        source[
            "profile"
        ] = slug

    if "seller" in source:
        source[
            "seller"
        ] = ""

    if "artist" in source:
        source[
            "artist"
        ] = str(
            artist[
                "name"
            ]
        )

    if "query" in source:
        source[
            "query"
        ] = query

    return source


def _generated_gripsweat_source(
    artist: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    """Generate one Gripsweat crawler source."""

    source = deepcopy(
        template
    )

    source[
        "name"
    ] = str(
        artist[
            "id"
        ]
    )

    source[
        "artist"
    ] = str(
        artist[
            "name"
        ]
    )

    source[
        "query"
    ] = str(
        artist[
            "query"
        ]
    )

    source[
        "enabled"
    ] = True

    if not source.get(
        "url_template"
    ):
        source[
            "url_template"
        ] = (
            "https://gripsweat.com/search/"
            "?query={query}&page={page}&sort_by={sort_by}"
        )

    if not source.get(
        "sort_by"
    ):
        source[
            "sort_by"
        ] = "date"

    return source


def _materialize_marketplace_sources(
    marketplace: str,
    *,
    state: dict[str, Any],
    legacy_payload: Any,
) -> Any:
    """Create one effective crawler config from the runtime artist model."""

    template = _first_source_template(
        legacy_payload
    )

    effective: list[
        dict[str, Any]
    ] = []

    for artist in state[
        "artists"
    ]:
        if not bool(
            artist.get(
                "enabled",
                True,
            )
        ):
            continue

        target = (
            artist.get(
                "targets",
                {}
            ).get(
                marketplace
            )
        )

        if not isinstance(
            target,
            dict,
        ):
            continue

        if not bool(
            target.get(
                "enabled",
                False,
            )
        ):
            continue

        if (
            target.get(
                "mode"
            )
            == "legacy"
            and isinstance(
                target.get(
                    "source"
                ),
                dict,
            )
        ):
            source = deepcopy(
                target[
                    "source"
                ]
            )

            source[
                "enabled"
            ] = True

            effective.append(
                source
            )

            continue

        if marketplace == "ebay":
            effective.append(
                _generated_ebay_source(
                    artist,
                    template,
                )
            )

        elif marketplace == "gripsweat":
            effective.append(
                _generated_gripsweat_source(
                    artist,
                    template,
                )
            )

    return _replace_source_values(
        legacy_payload,
        effective,
    )


def prepare_runtime_marketplace_configs(
    *,
    state_path: Path | None = None,
    ebay_config: Path = DEFAULT_EBAY_CONFIG,
    gripsweat_config: Path = DEFAULT_GRIPSWEAT_CONFIG,
    output_directory: Path | None = None,
    engine: Engine | None = None,
    account_id: uuid.UUID | str | None = None,
) -> dict[str, Path]:
    """Materialize enabled sources from account PostgreSQL or legacy input."""
    runtime_account_id = (
        account_id
        or os.environ.get("AUCTION_ACCOUNT_ID", "").strip()
        or None
    )

    owned_engine = False
    effective_engine = engine

    if runtime_account_id is not None:
        if effective_engine is None:
            effective_engine = _runtime_account_engine()
            owned_engine = True

        try:
            state = account_tracking_state(
                effective_engine,
                account_id=runtime_account_id,
            )
        finally:
            if owned_engine:
                effective_engine.dispose()
    else:
        state = load_tracking_state(
            state_path=state_path,
            ebay_config=ebay_config,
            gripsweat_config=gripsweat_config,
        )

    output = (
        output_directory
        or effective_config_directory()
    )

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    ebay_payload = _load_json(
        ebay_config
    )

    gripsweat_payload = _load_json(
        gripsweat_config
    )

    effective_ebay = _materialize_marketplace_sources(
        "ebay",
        state=state,
        legacy_payload=ebay_payload,
    )

    effective_gripsweat = _materialize_marketplace_sources(
        "gripsweat",
        state=state,
        legacy_payload=gripsweat_payload,
    )

    ebay_output = (
        output
        / "ebay_sources.json"
    )

    gripsweat_output = (
        output
        / "gripsweat_sources.json"
    )

    _atomic_write_json(
        ebay_output,
        effective_ebay,
    )

    _atomic_write_json(
        gripsweat_output,
        effective_gripsweat,
    )

    os.environ[
        EBAY_CONFIG_ENV
    ] = str(
        ebay_output
    )

    os.environ[
        GRIPSWEAT_CONFIG_ENV
    ] = str(
        gripsweat_output
    )

    return {
        "ebay": ebay_output,
        "gripsweat": gripsweat_output,
    }
