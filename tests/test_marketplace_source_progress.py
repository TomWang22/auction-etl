"""Tests for explicit per-marketplace ingestion lifecycle state."""

from __future__ import annotations

import uuid
from pathlib import Path

from auction_etl.services.auction_ingest_job import (
    interpret_output,
    mark_all_sources_done,
    new_status,
)


ROOT = Path(__file__).resolve().parents[1]

REFRESH_RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

REFRESH_PAGE = (
    ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)


def status_document() -> dict[str, object]:
    """Return a fresh ingestion status document."""

    return new_status(
        uuid.uuid4().hex
    )


def test_explicit_marketplace_lifecycle() -> None:
    """Move all three marketplaces independently."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=running\n",
    )

    assert status["source_states"] == {
        "eBay": "waiting",
        "Buyee": "running",
        "Gripsweat": "waiting",
    }

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=done\n",
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=running\n",
    )

    assert status["source_states"] == {
        "eBay": "running",
        "Buyee": "done",
        "Gripsweat": "waiting",
    }

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Gripsweat state=running\n",
    )

    assert status["source_states"] == {
        "eBay": "done",
        "Buyee": "done",
        "Gripsweat": "running",
    }

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Gripsweat state=done\n",
    )

    assert status["source_states"] == {
        "eBay": "done",
        "Buyee": "done",
        "Gripsweat": "done",
    }

    assert (
        status["source_state_protocol"]
        == "explicit-v1"
    )


def test_buyee_unavailable_is_not_green() -> None:
    """Keep an unavailable Buyee source unavailable."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=unavailable\n",
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Gripsweat state=done\n",
    )

    mark_all_sources_done(
        status
    )

    assert status["source_states"] == {
        "eBay": "done",
        "Buyee": "unavailable",
        "Gripsweat": "done",
    }


def test_explicit_protocol_disables_word_guessing() -> None:
    """Ignore incidental marketplace words after explicit mode starts."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=unavailable\n",
    )

    interpret_output(
        status,
        "Continuing eBay and Gripsweat refreshes.\n",
    )

    assert status["source_states"] == {
        "eBay": "waiting",
        "Buyee": "unavailable",
        "Gripsweat": "waiting",
    }


def test_clean_exit_does_not_invent_explicit_success() -> None:
    """Missing explicit completion must never become green."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Buyee state=done\n",
    )

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=running\n",
    )

    mark_all_sources_done(
        status
    )

    assert status["source_states"] == {
        "eBay": "failed",
        "Buyee": "done",
        "Gripsweat": "failed",
    }


def test_runner_emits_marketplace_boundaries() -> None:
    """Require explicit source events in the production runner."""

    source = REFRESH_RUNNER.read_text(
        encoding="utf-8",
    )

    assert (
        "AUCTION_SOURCE_STATE source=%s state=%s"
        in source
    )

    assert source.count(
        '"Buyee",'
    ) >= 3

    assert source.count(
        '"eBay",'
    ) >= 2

    assert source.count(
        '"Gripsweat",'
    ) >= 2

    assert (
        '"unavailable",'
        in source
    )


def test_refresh_page_requires_all_sources_for_green() -> None:
    """Overall green must mean all three sources are done."""

    source = REFRESH_PAGE.read_text(
        encoding="utf-8",
    )

    assert (
        '"unavailable":'
        in source
    )

    assert (
        'return "Unavailable"'
        in source
    )

    assert (
        "def all_sources_done("
        in source
    )

    assert (
        "if all_sources_done("
        in source
    )

    assert (
        "Marketplace refresh finished with warnings."
        in source
    )

    assert (
        "not every marketplace"
        in source
    )


def test_new_explicit_jobs_start_strictly_waiting() -> None:
    """New jobs must not enter the legacy observed state."""

    status = status_document()

    assert (
        status["source_state_protocol"]
        == "explicit-v1"
    )

    assert status["source_states"] == {
        "eBay": "waiting",
        "Buyee": "waiting",
        "Gripsweat": "waiting",
    }

    assert (
        "observed"
        not in status[
            "source_states"
        ].values()
    )


def test_incidental_marketplace_text_does_not_start_a_source() -> None:
    """Explicit jobs change source state only from lifecycle markers."""

    status = status_document()

    interpret_output(
        status,
        "Preparing eBay, Buyee, and Gripsweat configuration.\n",
    )

    assert status["source_states"] == {
        "eBay": "waiting",
        "Buyee": "waiting",
        "Gripsweat": "waiting",
    }


def test_running_source_survives_post_processing_until_done_marker() -> None:
    """Post-processing text must not demote an explicitly running source."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=running\n",
    )

    interpret_output(
        status,
        "Updating normalized auction data\n",
    )

    assert status["source_states"] == {
        "eBay": "running",
        "Buyee": "waiting",
        "Gripsweat": "waiting",
    }

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    assert status["source_states"] == {
        "eBay": "done",
        "Buyee": "waiting",
        "Gripsweat": "waiting",
    }


def test_clean_exit_does_not_invent_missing_source_completion() -> None:
    """Missing explicit completion markers must remain non-green."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=eBay state=done\n",
    )

    mark_all_sources_done(
        status
    )

    assert (
        status[
            "source_states"
        ][
            "eBay"
        ]
        == "done"
    )

    for marketplace in (
        "Buyee",
        "Gripsweat",
    ):
        state = status[
            "source_states"
        ][
            marketplace
        ]

        assert state != "done"
        assert state in {
            "waiting",
            "failed",
            "unavailable",
        }

    assert (
        "observed"
        not in status[
            "source_states"
        ].values()
    )


def test_explicit_failure_does_not_create_observed_state() -> None:
    """A marketplace failure cannot demote another explicit source to observed."""

    status = status_document()

    interpret_output(
        status,
        "AUCTION_SOURCE_STATE source=Gripsweat state=running\n",
    )

    interpret_output(
        status,
        "refresh failed: eBay\n",
    )

    assert (
        "observed"
        not in status[
            "source_states"
        ].values()
    )

    assert (
        status[
            "source_states"
        ][
            "eBay"
        ]
        == "failed"
    )
