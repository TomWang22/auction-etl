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
    """Verify the Streamlit page retains its progress and notification UI."""

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
        "Ingest New Auctions",
        "Ingest new auctions across all sites",
        "Auction ingestion is running…",
        "Auction ingestion started.",
        "New auctions are ready.",
        "Auction ingestion failed. Open the log for details.",
        "Live ingestion log",
        "This page refreshes automatically every 2 seconds.",
        "scripts/run_auction_refresh_on_demand.sh",
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
        "Missing ingestion UI contracts: "
        + ", ".join(
            missing
        )
    )
