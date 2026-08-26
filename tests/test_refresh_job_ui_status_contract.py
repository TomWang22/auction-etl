"""Regression tests for durable marketplace status presented to Streamlit."""

from __future__ import annotations

from auction_etl.services.refresh_jobs import (
    refresh_job_to_ui_status,
)


def job(
    *,
    state: str = "running",
    marketplace_states: tuple[str, str, str] = (
        "waiting",
        "waiting",
        "waiting",
    ),
) -> dict[str, object]:
    """Return one durable refresh-job mapping."""
    names = (
        "buyee",
        "ebay",
        "gripsweat",
    )

    return {
        "id":
            "00000000-0000-0000-0000-000000000001",
        "state":
            state,
        "message":
            "",
        "attempt":
            1,
        "marketplaces": [
            {
                "marketplace":
                    name,
                "state":
                    marketplace_state,
                "new_count":
                    0,
                "discovered":
                    0,
                "already_known":
                    0,
                "detail_scraped":
                    0,
                "detail_skipped":
                    0,
                "discovery_pages":
                    0,
                "consecutive_known_at_stop":
                    0,
            }
            for name, marketplace_state
            in zip(
                names,
                marketplace_states,
                strict=True,
            )
        ],
    }


def test_ui_status_exposes_source_states_alias() -> None:
    """The Ingest page must receive the durable marketplace states."""
    status = refresh_job_to_ui_status(
        job(
            marketplace_states=(
                "skipped",
                "running",
                "waiting",
            )
        )
    )

    expected = {
        "buyee":
            "unavailable",
        "ebay":
            "running",
        "gripsweat":
            "waiting",
    }

    assert (
        status["marketplace_states"]
        == expected
    )
    assert (
        status["source_states"]
        == expected
    )
    assert status["phase"] == "ebay"
    assert status["progress"] == 33


def test_ui_status_shows_finalizing_after_marketplaces_finish() -> None:
    """Post-marketplace work must not look like three waiting sources."""
    status = refresh_job_to_ui_status(
        job(
            marketplace_states=(
                "skipped",
                "skipped",
                "done",
            )
        )
    )

    assert status["source_states"] == {
        "buyee":
            "unavailable",
        "ebay":
            "unavailable",
        "gripsweat":
            "done",
    }
    assert status["progress"] == 100
    assert status["phase"] == "Finalizing"


def test_failed_job_preserves_terminal_marketplace_states() -> None:
    """A later FX failure must not erase completed marketplace history."""
    status = refresh_job_to_ui_status(
        job(
            state="failed",
            marketplace_states=(
                "skipped",
                "skipped",
                "done",
            ),
        )
    )

    assert status["source_states"] == {
        "buyee":
            "unavailable",
        "ebay":
            "unavailable",
        "gripsweat":
            "done",
    }
    assert status["progress"] == 100
