"""Smoke tests for user-triggered ingestion without production marketplace work."""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

INGEST_PAGE = (
    REPOSITORY_ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)

HARNESS = r"""
from __future__ import annotations

import json
import time

from auction_etl.services.auction_ingest_job import (
    RUNNING_STATES,
    get_latest_status,
    start_job,
    tail_log,
)


first = start_job()
second = start_job()

if first["job_id"] != second["job_id"]:
    raise SystemExit(
        "ERROR: duplicate start created a second active ingestion job."
    )

deadline = time.monotonic() + 15.0
history: list[dict[str, object]] = []

while True:
    status = get_latest_status()

    if status is None:
        raise SystemExit(
            "ERROR: latest ingestion status disappeared."
        )

    history.append(
        {
            "status": status.get("status"),
            "progress": status.get("progress"),
            "phase": status.get("phase"),
            "source_states": status.get("source_states"),
        }
    )

    if status.get("status") not in RUNNING_STATES:
        break

    if time.monotonic() >= deadline:
        raise SystemExit(
            "ERROR: fake ingestion timed out."
        )

    time.sleep(0.05)

log_text = tail_log(
    status.get("log_path"),
    line_count=200,
)

print(
    json.dumps(
        {
            "first_job_id": first["job_id"],
            "second_job_id": second["job_id"],
            "history": history,
            "final": status,
            "log": log_text,
        },
        sort_keys=True,
    )
)
"""


def write_fake_runner(path: Path) -> None:
    """Write a deterministic marketplace runner used only by this test."""

    path.write_text(
        textwrap.dedent(
            """\
            from __future__ import annotations

            import time


            steps = (
                ("eBay ingestion started", 0.35),
                ("eBay ingestion complete", 0.10),
                ("Buyee ingestion started", 0.10),
                ("Buyee ingestion complete", 0.10),
                ("Gripsweat ingestion started", 0.10),
                ("Gripsweat ingestion complete", 0.10),
                ("collector normalize complete", 0.05),
                ("FX exchange rate update complete", 0.05),
                ("verification complete", 0.05),
                ("RESULT=PASS", 0.00),
            )

            for message, delay in steps:
                print(
                    message,
                    flush=True,
                )

                if delay:
                    time.sleep(
                        delay
                    )
            """
        ),
        encoding="utf-8",
    )


def test_fake_runner_completes_without_production_ingestion(
    tmp_path: Path,
) -> None:
    """Run the real background controller against a harmless fake runner."""

    temporary_home = (
        tmp_path
        / "home"
    )

    temporary_home.mkdir(
        parents=True,
        exist_ok=True,
    )

    fake_runner = (
        tmp_path
        / "fake_marketplace_runner.py"
    )

    write_fake_runner(
        fake_runner
    )

    environment = os.environ.copy()

    environment["HOME"] = str(
        temporary_home
    )

    environment["AUCTION_INGEST_RUNNER"] = shlex.join(
        [
            sys.executable,
            str(
                fake_runner
            ),
        ]
    )

    existing_pythonpath = environment.get(
        "PYTHONPATH"
    )

    environment["PYTHONPATH"] = (
        str(
            REPOSITORY_ROOT
        )
        if not existing_pythonpath
        else (
            str(
                REPOSITORY_ROOT
            )
            + os.pathsep
            + existing_pythonpath
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            HARNESS,
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, (
        "Fake ingestion harness failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    payload = json.loads(
        result.stdout
    )

    assert (
        payload["first_job_id"]
        == payload["second_job_id"]
    )

    final = payload[
        "final"
    ]

    assert final[
        "status"
    ] == "completed"

    assert final[
        "progress"
    ] == 100

    assert final[
        "phase"
    ] == "Complete"

    assert final[
        "return_code"
    ] == 0

    assert final[
        "planned_sources"
    ] == [
        "eBay",
        "Buyee",
        "Gripsweat",
    ]

    assert final[
        "source_states"
    ] == {
        "eBay": "done",
        "Buyee": "done",
        "Gripsweat": "done",
    }

    runner_command = final[
        "runner_command"
    ]

    assert str(
        fake_runner
    ) in runner_command

    assert (
        "run_auction_refresh_on_demand.sh"
        not in " ".join(
            runner_command
        )
    )

    log_path = Path(
        final[
            "log_path"
        ]
    )

    assert (
        temporary_home
        in log_path.parents
    )

    log_text = payload[
        "log"
    ]

    for expected in (
        "eBay ingestion started",
        "Buyee ingestion started",
        "Gripsweat ingestion started",
        "collector normalize complete",
        "FX exchange rate update complete",
        "verification complete",
        "RESULT=PASS",
        "Runner exit status: 0",
    ):
        assert expected in log_text

    observed_states = {
        item[
            "status"
        ]
        for item in payload[
            "history"
        ]
    }

    assert (
        observed_states
        & {
            "queued",
            "running",
        }
    )


def test_ingestion_page_exposes_product_progress_contract() -> None:
    """Verify the current Marketplace Sales refresh product contract."""

    source = INGEST_PAGE.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(
            INGEST_PAGE
        ),
    )

    required_text = (
        "Refresh Marketplace Sales",
        "Refresh status",
        "Technical details",
        "eBay",
        "Buyee",
        "Gripsweat",
        "st.progress(",
        "st.toast(",
        "get_latest_status",
        "start_job",
        "tail_log",
    )

    missing = [
        value
        for value in required_text
        if value not in source
    ]

    assert not missing, (
        "Missing current refresh UI contracts: "
        + ", ".join(
            missing
        )
    )

    obsolete_product_copy = (
        "Ingest New Auctions",
        "Ingest new auctions across all sites",
        "Auction ingestion is running…",
        "Auction ingestion started.",
        "New auctions are ready.",
        "Auction ingestion failed. Open the log for details.",
        "This page refreshes automatically every 2 seconds.",
    )

    stale = [
        value
        for value in obsolete_product_copy
        if value in source
    ]

    assert not stale, (
        "Obsolete ingestion UI copy returned: "
        + ", ".join(
            stale
        )
    )

def test_queued_job_without_worker_pid_is_not_reconciled_as_failed(
    monkeypatch,
) -> None:
    """Protect the parent/worker PID-registration startup window."""

    from auction_etl.services import auction_ingest_job as ingest_job

    queued = ingest_job.new_status(
        "a" * 32
    )

    assert queued[
        "worker_pid"
    ] is None

    persisted: list[
        dict[str, object]
    ] = []

    monkeypatch.setattr(
        ingest_job,
        "ensure_runtime_directories",
        lambda: None,
    )

    monkeypatch.setattr(
        ingest_job,
        "read_json",
        lambda _path: dict(
            queued
        ),
    )

    monkeypatch.setattr(
        ingest_job,
        "persist_status",
        lambda payload: (
            persisted.append(
                dict(
                    payload
                )
            )
            or payload
        ),
    )

    result = ingest_job.get_latest_status()

    assert result is not None
    assert result[
        "status"
    ] == "queued"

    assert result[
        "worker_pid"
    ] is None

    assert persisted == []

def test_post_processing_failure_does_not_blame_last_marketplace() -> None:
    """Keep post-processing failures separate from marketplace failures."""

    from auction_etl.services import auction_ingest_job as ingest_job

    status = ingest_job.new_status(
        "b" * 32
    )

    ingest_job.interpret_output(
        status,
        "Gripsweat ingestion started",
    )

    assert status[
        "source_states"
    ][
        "Gripsweat"
    ] == "running"

    assert status[
        "stage"
    ] == "marketplace"

    ingest_job.interpret_output(
        status,
        "Update auction FX values",
    )

    assert status[
        "stage"
    ] == "post_processing"

    assert status[
        "source_states"
    ][
        "Gripsweat"
    ] == "observed"

    status[
        "failure_stage"
    ] = "post_processing"

    ingest_job.mark_active_sources_failed(
        status
    )

    assert "failed" not in set(
        status[
            "source_states"
        ].values()
    )

    assert status[
        "source_states"
    ][
        "Gripsweat"
    ] == "observed"

def test_expired_queued_job_without_worker_pid_becomes_start_failure(
    monkeypatch,
) -> None:
    """Prevent an abandoned queued job from blocking all future refreshes."""

    from auction_etl.services import auction_ingest_job as ingest_job

    queued = ingest_job.new_status(
        "c" * 32
    )

    queued[
        "worker_pid"
    ] = None

    queued[
        "worker_registration_deadline"
    ] = 0.0

    persisted: list[
        dict[str, object]
    ] = []

    monkeypatch.setattr(
        ingest_job,
        "ensure_runtime_directories",
        lambda: None,
    )

    monkeypatch.setattr(
        ingest_job,
        "read_json",
        lambda _path: dict(
            queued
        ),
    )

    monkeypatch.setattr(
        ingest_job,
        "persist_status",
        lambda payload: (
            persisted.append(
                dict(
                    payload
                )
            )
            or payload
        ),
    )

    result = ingest_job.get_latest_status()

    assert result is not None

    assert result[
        "status"
    ] == "failed"

    assert result[
        "phase"
    ] == "Worker did not start"

    assert result[
        "stage"
    ] == "starting"

    assert result[
        "failure_stage"
    ] == "starting"

    assert len(
        persisted
    ) == 1
