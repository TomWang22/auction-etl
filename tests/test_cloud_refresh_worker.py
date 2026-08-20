"""Persistent cloud refresh worker contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_railway_config_runs_persistent_worker() -> None:
    """Railway service uses the browser-capable worker image and entrypoint."""
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
