"""Tests for the guarded multi-source ingestion transition."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_multisource_ingestion_round.py"
)

SPEC = importlib.util.spec_from_file_location(
    "run_multisource_ingestion_round",
    MODULE_PATH,
)

assert SPEC is not None
assert SPEC.loader is not None

module = importlib.util.module_from_spec(
    SPEC
)

SPEC.loader.exec_module(
    module
)


def state(
    **changes: int,
) -> dict[str, int]:
    """Build an internally consistent protected-state fixture."""

    values = {
        "auctions": 853,
        "assignments": 6,
        "snapshots": 6,
        "timeline": 6,
        "queue": 847,
        "pressings": 2,
        "families": 2,
        "gripsweat_sales": 600,
        "crawl_jobs": 8,
        "raw_pages": 11,
    }

    values.update(
        changes
    )

    return values


def test_transition_accepts_new_source_rows() -> None:
    before = state()

    after = state(
        auctions=856,
        queue=850,
        gripsweat_sales=604,
        crawl_jobs=10,
        raw_pages=13,
    )

    delta = module.verify_transition(
        before,
        after,
    )

    assert delta == {
        "auction_delta": 3,
        "queue_delta": 3,
        "gripsweat_delta": 4,
        "crawl_job_delta": 2,
        "raw_page_delta": 2,
    }


def test_transition_rejects_assignment_decreases() -> None:
    before = state()

    after = state(
        assignments=5,
        queue=848,
    )

    with pytest.raises(
        module.MultiSourceIngestionError,
        match="assignments",
    ):
        module.verify_transition(
            before,
            after,
        )


def test_transition_accepts_identity_fill_assignment_increase() -> None:
    before = state()

    after = state(
        auctions=856,
        assignments=7,
        queue=849,
        pressings=3,
        families=3,
        gripsweat_sales=604,
        crawl_jobs=10,
        raw_pages=13,
    )

    delta = module.verify_transition(
        before,
        after,
    )

    assert delta["auction_delta"] == 3
    assert delta["queue_delta"] == 2


def test_transition_rejects_snapshot_decreases() -> None:
    before = state()

    after = state(
        snapshots=5,
        timeline=5,
    )

    with pytest.raises(
        module.MultiSourceIngestionError,
        match="snapshots",
    ):
        module.verify_transition(
            before,
            after,
        )


def test_transition_accepts_completeness_history_for_new_listings() -> None:
    before = state()

    after = state(
        auctions=858,
        queue=852,
        snapshots=11,
        timeline=11,
        gripsweat_sales=603,
        crawl_jobs=10,
        raw_pages=13,
    )

    delta = module.verify_transition(
        before,
        after,
    )

    assert delta["auction_delta"] == 5


def test_matrix_evidence_uses_only_matrix_keys() -> None:
    payload = {
        "matrix": "MR-2276 A",
        "details": {
            "runout": "MR-2276 B",
            "seller": "ignored",
        },
    }

    assert module.payload_matrix_strings(
        payload
    ) == [
        (
            "matrix",
            "MR-2276 A",
        ),
        (
            "runout",
            "MR-2276 B",
        ),
    ]


def test_round_drains_pending_staging_instead_of_aborting() -> None:
    """Leftover staged identities must finish ingest, not block refresh."""
    source = MODULE_PATH.read_text(
        encoding="utf-8"
    )

    assert "drain_pending_marketplace_identities" in source
    assert "Draining pending" in source
    assert "--no-prune" in source
    assert (
        "Existing Buyee/eBay staging "
        "contains pending identities:"
    ) not in source


def test_release_type_hints_are_not_title_identity() -> None:
    assert module.release_type_hint(
        "Teresa Teng Live in Concert",
        "LP",
    ) == "LIVE"

    assert module.release_type_hint(
        "Unknown album",
        "LP",
    ) is None
