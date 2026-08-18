"""Tests for tracked-artist production refresh lifecycle status."""

from __future__ import annotations

import uuid
from pathlib import Path

from auction_etl.services.auction_ingest_job import (
    artist_target_statuses,
    interpret_output,
    mark_all_sources_done,
    new_status,
)


ROOT = Path(
    __file__
).resolve().parents[
    1
]

ARTIST_PAGE = (
    ROOT
    / "app"
    / "pages"
    / "16_Artists_to_Track.py"
)


def artist_snapshot() -> dict[str, dict[str, object]]:
    """Return one artist included on both searchable marketplaces."""

    return {
        "momoe-yamaguchi": {
            "name":
                "Momoe Yamaguchi",
            "query":
                "Momoe Yamaguchi",
            "targets": [
                "ebay",
                "gripsweat",
            ],
        }
    }


def current_artist() -> dict[str, object]:
    """Return the corresponding product-facing artist record."""

    return {
        "id":
            "momoe-yamaguchi",
        "name":
            "Momoe Yamaguchi",
        "query":
            "Momoe Yamaguchi",
        "enabled":
            True,
        "targets": {
            "ebay": {
                "enabled":
                    True,
            },
            "gripsweat": {
                "enabled":
                    True,
            },
        },
    }


def test_job_snapshot_starts_artist_targets_waiting() -> None:
    """A production job captures enabled artist targets at start."""

    status = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    assert (
        status[
            "artist_target_protocol"
        ]
        == "snapshot-v1"
    )

    artist = status[
        "artist_targets"
    ][
        "momoe-yamaguchi"
    ]

    assert artist[
        "target_states"
    ] == {
        "ebay":
            "waiting",
        "gripsweat":
            "waiting",
    }


def test_ebay_lifecycle_updates_only_ebay_artist_target() -> None:
    """Global eBay lifecycle is reflected on included eBay artist targets."""

    status = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=running\n",
    )

    artist = status[
        "artist_targets"
    ][
        "momoe-yamaguchi"
    ]

    assert (
        artist[
            "target_states"
        ][
            "ebay"
        ]
        == "running"
    )

    assert (
        artist[
            "target_states"
        ][
            "gripsweat"
        ]
        == "waiting"
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    assert (
        artist[
            "target_states"
        ][
            "ebay"
        ]
        == "done"
    )

    assert (
        artist[
            "target_completed_at"
        ][
            "ebay"
        ]
        is not None
    )


def test_buyee_remains_global_not_per_artist() -> None:
    """Buyee watchlist lifecycle must not become an artist target."""

    status = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    before = dict(
        status[
            "artist_targets"
        ][
            "momoe-yamaguchi"
        ][
            "target_states"
        ]
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=unavailable\n",
    )

    after = status[
        "artist_targets"
    ][
        "momoe-yamaguchi"
    ][
        "target_states"
    ]

    assert after == before


def test_last_success_survives_a_later_running_refresh() -> None:
    """Display previous successful refresh time while a new run is active."""

    completed = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    completed[
        "status"
    ] = "running"

    interpret_output(
        completed,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    completed[
        "status"
    ] = "completed"

    completed_at = completed[
        "artist_targets"
    ][
        "momoe-yamaguchi"
    ][
        "target_completed_at"
    ][
        "ebay"
    ]

    running = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    running[
        "status"
    ] = "running"

    interpret_output(
        running,
        "AUCTION_SOURCE_STATE source=eBay state=running\n",
    )

    summary = artist_target_statuses(
        [
            current_artist()
        ],
        latest_status=running,
        history=[
            running,
            completed,
        ],
    )

    ebay = summary[
        "momoe-yamaguchi"
    ][
        "ebay"
    ]

    assert (
        ebay[
            "state"
        ]
        == "running"
    )

    assert (
        ebay[
            "current_job"
        ]
        is True
    )

    assert (
        ebay[
            "last_refreshed_at"
        ]
        == completed_at
    )


def test_missing_completion_marker_is_not_green_per_artist() -> None:
    """Artist targets inherit strict Step 2C non-green finalization."""

    status = new_status(
        uuid.uuid4().hex,
        artist_targets=artist_snapshot(),
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    mark_all_sources_done(
        status
    )

    artist = status[
        "artist_targets"
    ][
        "momoe-yamaguchi"
    ]

    assert (
        artist[
            "target_states"
        ][
            "ebay"
        ]
        == "done"
    )

    assert (
        artist[
            "target_states"
        ][
            "gripsweat"
        ]
        != "done"
    )


def test_artists_page_uses_production_refresh_job() -> None:
    """Artists to track must reuse production ingestion orchestration."""

    source = ARTIST_PAGE.read_text(
        encoding="utf-8",
    )

    assert (
        "start_job"
        in source
    )

    assert (
        '"Refresh tracked artists"'
        in source
    )

    assert (
        "artist_target_statuses"
        in source
    )

    assert (
        'run_every="3s"'
        in source
    )

    assert (
        "Last refreshed:"
        in source
    )

    assert (
        "Buyee still refreshes from the authenticated watchlist"
        in source
    )
