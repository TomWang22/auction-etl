"""Regression tests for runtime artist tracking."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from auction_etl.services.artist_tracking import (
    build_ebay_search_url,
    build_gripsweat_search_url,
    list_tracked_artists,
    prepare_runtime_marketplace_configs,
    remove_artist,
    set_artist_enabled,
    upsert_artist,
)


def write_json(
    path: Path,
    value: object,
) -> None:
    """Write deterministic JSON test data."""

    path.write_text(
        json.dumps(
            value,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def sample_configs(
    tmp_path: Path,
) -> tuple[Path, Path]:
    """Create representative legacy marketplace configs."""

    ebay = (
        tmp_path
        / "ebay.json"
    )

    gripsweat = (
        tmp_path
        / "gripsweat.json"
    )

    write_json(
        ebay,
        {
            "sources": [
                {
                    "name": "facerecords",
                    "profile": "facerecords",
                    "seller": "facerecords",
                    "enabled": True,
                    "completed_only": True,
                    "max_pages": 3,
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_nkw=teresa%20teng"
                        "&_ssn=facerecords"
                        "&LH_Complete=1"
                        "&LH_Sold=1"
                    ),
                }
            ]
        },
    )

    write_json(
        gripsweat,
        {
            "sources": [
                {
                    "name": "teresa-teng",
                    "artist": "Teresa Teng",
                    "query": "teresa teng",
                    "enabled": True,
                    "max_pages": 3,
                    "sort_by": "date",
                    "url_template": (
                        "https://gripsweat.com/search/"
                        "?query={query}"
                        "&page={page}"
                        "&sort_by={sort_by}"
                    ),
                },
                {
                    "name": "anita-mui",
                    "artist": "Anita Mui",
                    "query": "anita mui",
                    "enabled": True,
                    "max_pages": 3,
                    "sort_by": "date",
                    "url_template": (
                        "https://gripsweat.com/search/"
                        "?query={query}"
                        "&page={page}"
                        "&sort_by={sort_by}"
                    ),
                },
            ]
        },
    )

    return (
        ebay,
        gripsweat,
    )


def source_list(
    path: Path,
) -> list[dict]:
    """Return sources from a generated config."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(
        payload,
        list,
    ):
        return payload

    return payload[
        "sources"
    ]


def test_legacy_sources_group_teresa_across_marketplaces(
    tmp_path: Path,
) -> None:
    """Treat seller/profile metadata as metadata, not artist identity."""

    ebay, gripsweat = sample_configs(
        tmp_path
    )

    artists = list_tracked_artists(
        state_path=(
            tmp_path
            / "state.json"
        ),
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    names = [
        artist[
            "name"
        ]
        for artist
        in artists
    ]

    assert names == [
        "Anita Mui",
        "Teresa Teng",
    ]

    teresa = next(
        artist
        for artist
        in artists
        if artist[
            "name"
        ] == "Teresa Teng"
    )

    assert set(
        teresa[
            "targets"
        ]
    ) == {
        "ebay",
        "gripsweat",
    }

    assert (
        teresa[
            "targets"
        ][
            "ebay"
        ][
            "metadata"
        ][
            "seller"
        ]
        == "facerecords"
    )


def test_user_can_add_edit_pause_and_remove_artist(
    tmp_path: Path,
) -> None:
    """Persist the complete product editing lifecycle."""

    ebay, gripsweat = sample_configs(
        tmp_path
    )

    state = (
        tmp_path
        / "state.json"
    )

    created = upsert_artist(
        "Faye Wong",
        [
            "ebay",
            "gripsweat",
        ],
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    artist_id = created[
        "id"
    ]

    artists = list_tracked_artists(
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    faye = next(
        artist
        for artist
        in artists
        if artist[
            "id"
        ] == artist_id
    )

    assert (
        faye[
            "targets"
        ][
            "ebay"
        ][
            "enabled"
        ]
        is True
    )

    assert (
        faye[
            "targets"
        ][
            "gripsweat"
        ][
            "enabled"
        ]
        is True
    )

    upsert_artist(
        "Faye Wong",
        [
            "gripsweat",
        ],
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    artists = list_tracked_artists(
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    faye = next(
        artist
        for artist
        in artists
        if artist[
            "id"
        ] == artist_id
    )

    assert (
        faye[
            "targets"
        ][
            "ebay"
        ][
            "enabled"
        ]
        is False
    )

    set_artist_enabled(
        artist_id,
        False,
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    artists = list_tracked_artists(
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    faye = next(
        artist
        for artist
        in artists
        if artist[
            "id"
        ] == artist_id
    )

    assert (
        faye[
            "enabled"
        ]
        is False
    )

    remove_artist(
        artist_id,
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    artists = list_tracked_artists(
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    assert all(
        artist[
            "id"
        ] != artist_id
        for artist
        in artists
    )


def test_generated_marketplace_urls_encode_artist_names() -> None:
    """Generate links without user-entered marketplace URLs."""

    ebay = build_ebay_search_url(
        "Faye Wong"
    )

    gripsweat = build_gripsweat_search_url(
        "Faye Wong"
    )

    ebay_query = parse_qs(
        urlsplit(
            ebay
        ).query
    )

    gripsweat_query = parse_qs(
        urlsplit(
            gripsweat
        ).query
    )

    assert ebay_query[
        "_nkw"
    ] == [
        "Faye Wong"
    ]

    assert ebay_query[
        "LH_Complete"
    ] == [
        "1"
    ]

    assert ebay_query[
        "LH_Sold"
    ] == [
        "1"
    ]

    assert gripsweat_query[
        "query"
    ] == [
        "Faye Wong"
    ]


def test_refresh_materialization_preserves_legacy_and_adds_user_artist(
    tmp_path: Path,
) -> None:
    """Feed user artists into the real crawler configuration boundary."""

    ebay, gripsweat = sample_configs(
        tmp_path
    )

    state = (
        tmp_path
        / "state.json"
    )

    upsert_artist(
        "Faye Wong",
        [
            "ebay",
            "gripsweat",
        ],
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
    )

    output = (
        tmp_path
        / "effective"
    )

    generated = prepare_runtime_marketplace_configs(
        state_path=state,
        ebay_config=ebay,
        gripsweat_config=gripsweat,
        output_directory=output,
    )

    ebay_sources = source_list(
        generated[
            "ebay"
        ]
    )

    gripsweat_sources = source_list(
        generated[
            "gripsweat"
        ]
    )

    legacy_ebay = next(
        source
        for source
        in ebay_sources
        if source.get(
            "seller"
        ) == "facerecords"
    )

    assert (
        legacy_ebay[
            "profile"
        ]
        == "facerecords"
    )

    faye_ebay = next(
        source
        for source
        in ebay_sources
        if (
            "faye"
            in str(
                source.get(
                    "name",
                    "",
                )
            ).casefold()
        )
    )

    assert not faye_ebay.get(
        "seller"
    )

    assert "_ssn=" not in str(
        faye_ebay[
            "url"
        ]
    )

    faye_gripsweat = next(
        source
        for source
        in gripsweat_sources
        if source.get(
            "artist"
        ) == "Faye Wong"
    )

    assert (
        faye_gripsweat[
            "query"
        ]
        == "Faye Wong"
    )
