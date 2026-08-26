"""Persistent cloud refresh worker contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

WORKER_PATH = (
    ROOT
    / "scripts"
    / "run_cloud_refresh_worker.py"
)

RAILWAY = ROOT / "railway.json"


def load_worker():
    """Load the worker module without executing its main loop."""
    spec = (
        importlib.util.spec_from_file_location(
            "auction_cloud_refresh_worker",
            WORKER_PATH,
        )
    )

    assert spec is not None
    assert spec.loader is not None

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_worker_consumes_explicit_marketplace_protocol() -> None:
    """Worker state follows canonical explicit source markers."""
    worker = load_worker()

    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=Buyee state=running"
    ) == (
        "buyee",
        "running",
    )

    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=eBay state=done"
    ) == (
        "ebay",
        "done",
    )

    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=Gripsweat state=unavailable"
    ) == (
        "gripsweat",
        "skipped",
    )


def test_worker_persists_incremental_counters() -> None:
    """Known marketplace counters survive into durable progress."""
    worker = load_worker()

    counters = worker.parse_progress_counters(
        "discovered=12 already_known=9 "
        "detail_scraped=3 discovery_pages=2 "
        "consecutive_known_at_stop=7"
    )

    assert counters == {
        "discovered": 12,
        "already_known": 9,
        "detail_scraped": 3,
        "discovery_pages": 2,
        "consecutive_known_at_stop": 7,
    }

    assert worker.parse_progress_counters(
        "New detail candidates   : 4"
    )["new_count"] == 4


def test_worker_uses_existing_canonical_runner() -> None:
    """Cloud dispatch preserves the validated ingestion implementation."""
    source = WORKER_PATH.read_text(
        encoding="utf-8"
    )

    assert "run_multisource_ingestion_round.py" in source
    assert '"--execute"' in source
    assert "heartbeat_refresh_job" in source
    assert "release_refresh_job" in source
    assert "AUCTION_BUYEE_PROFILE_DIR" in source


def test_railway_config_runs_persistent_worker_when_repo_config_exists() -> None:
    """Validate Railway settings when deployment config is repository-managed."""
    if not RAILWAY.is_file():
        pytest.skip(
            "Railway deployment configuration is not repository-managed."
        )

    config = json.loads(
        RAILWAY.read_text(
            encoding="utf-8"
        )
    )

    assert (
        config["build"]["dockerfilePath"]
        == "Dockerfile.auction-etl.refresh"
    )

    assert (
        config["deploy"]["startCommand"]
        == "python scripts/run_cloud_refresh_worker.py"
    )

    assert (
        config["deploy"]["restartPolicyType"]
        == "ALWAYS"
    )

def test_worker_parses_structured_marketplace_diagnostic() -> None:
    """Canonical diagnostic payloads survive protocol parsing."""
    worker = load_worker()

    parsed = worker.parse_source_diagnostic(
        'AUCTION_SOURCE_DIAGNOSTIC source=Buyee '
        'payload={"message":"Buyee session unavailable.",'
        '"runtime_semantics":"cloud-headless",'
        '"source_state":"authentication_required",'
        '"verifier_exit_code":3}'
    )

    assert parsed == (
        "buyee",
        {
            "message":
                "Buyee session unavailable.",
            "runtime_semantics":
                "cloud-headless",
            "source_state":
                "authentication_required",
            "verifier_exit_code":
                3,
        },
    )

    assert worker.parse_source_diagnostic(
        "ordinary runner output"
    ) is None

    assert worker.parse_source_diagnostic(
        "AUCTION_SOURCE_DIAGNOSTIC "
        "source=Buyee payload=not-json"
    ) is None



def test_worker_persists_structured_marketplace_diagnostic() -> None:
    """Unavailable marketplace reasons survive into durable rows."""
    worker = load_worker()
    calls: list[dict[str, object]] = []

    original = worker.update_marketplace_state

    def record_update(
        _engine,
        **kwargs: object,
    ) -> None:
        calls.append(
            dict(
                kwargs
            )
        )

    worker.update_marketplace_state = (
        record_update
    )

    try:
        progress = worker.DurableProgress(
            engine=object(),
            job_id=(
                "00000000-0000-0000-0000-000000000001"
            ),
            worker_id_value="test-worker",
        )

        progress.consume(
            "AUCTION_SOURCE_STATE "
            "source=Buyee state=unavailable"
        )

        progress.consume(
            'AUCTION_SOURCE_DIAGNOSTIC source=Buyee '
            'payload={"message":"Buyee authentication failed.",'
            '"runtime_semantics":"cloud-headless",'
            '"source_state":"authentication_required",'
            '"verifier_exit_code":3}'
        )
    finally:
        worker.update_marketplace_state = (
            original
        )

    assert len(calls) == 2

    state_call = calls[0]

    assert state_call["marketplace"] == "buyee"
    assert state_call["state"] == "skipped"

    diagnostic_call = calls[1]

    assert diagnostic_call["marketplace"] == "buyee"
    assert diagnostic_call["state"] == "skipped"
    assert (
        diagnostic_call["message"]
        == "Buyee authentication failed."
    )

    error = diagnostic_call["error"]

    assert isinstance(
        error,
        str,
    )

    import json

    assert json.loads(
        error
    ) == {
        "message":
            "Buyee authentication failed.",
        "runtime_semantics":
            "cloud-headless",
        "source_state":
            "authentication_required",
        "verifier_exit_code":
            3,
    }



def test_worker_does_not_mark_successful_diagnostic_as_error() -> None:
    """Successful diagnostic metadata must not create a false error."""
    worker = load_worker()
    calls: list[dict[str, object]] = []

    original = worker.update_marketplace_state

    def record_update(
        _engine,
        **kwargs: object,
    ) -> None:
        calls.append(
            dict(
                kwargs
            )
        )

    worker.update_marketplace_state = (
        record_update
    )

    try:
        progress = worker.DurableProgress(
            engine=object(),
            job_id=(
                "00000000-0000-0000-0000-000000000001"
            ),
            worker_id_value="test-worker",
        )

        progress.consume(
            "AUCTION_SOURCE_STATE "
            "source=Gripsweat state=done"
        )

        progress.consume(
            'AUCTION_SOURCE_DIAGNOSTIC source=Gripsweat '
            'payload={"message":"Gripsweat completed.",'
            '"runtime_semantics":null,'
            '"source_state":null}'
        )
    finally:
        worker.update_marketplace_state = (
            original
        )

    diagnostic_call = calls[-1]

    assert diagnostic_call["state"] == "done"
    assert diagnostic_call["error"] is None
    assert (
        diagnostic_call["message"]
        == "Gripsweat completed."
    )
