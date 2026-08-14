"""Regression tests for auction-ingestion worker startup persistence."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from auction_etl.services import auction_ingest_job


def test_atomic_write_json_handles_concurrent_writers(
    tmp_path: Path,
) -> None:
    """Concurrent status writers must never share one temporary file."""

    status_path = (
        tmp_path
        / "status.json"
    )

    def writer(
        writer_number: int,
    ) -> None:
        for iteration in range(
            40
        ):
            auction_ingest_job.atomic_write_json(
                status_path,
                {
                    "writer":
                        writer_number,
                    "iteration":
                        iteration,
                    "payload":
                        "x"
                        * (
                            64
                            + writer_number
                        ),
                },
            )

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:
        futures = [
            executor.submit(
                writer,
                writer_number,
            )
            for writer_number
            in range(
                8
            )
        ]

        for future in futures:
            future.result()

    payload = json.loads(
        status_path.read_text(
            encoding="utf-8",
        )
    )

    assert payload[
        "writer"
    ] in range(
        8
    )

    assert payload[
        "iteration"
    ] in range(
        40
    )

    temporary_files = list(
        tmp_path.glob(
            ".status.json.*.tmp"
        )
    )

    assert temporary_files == []


def test_worker_waits_until_parent_registers_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The child must not race the parent's first worker-PID update."""

    job_id = uuid.uuid4().hex

    status_path = (
        tmp_path
        / f"{job_id}.json"
    )

    monkeypatch.setattr(
        auction_ingest_job,
        "job_path",
        lambda _job_id: status_path,
    )

    auction_ingest_job.atomic_write_json(
        status_path,
        {
            "job_id":
                job_id,
            "status":
                "queued",
            "worker_pid":
                None,
        },
    )

    current_pid = os.getpid()

    def register_worker() -> None:
        time.sleep(
            0.05
        )

        auction_ingest_job.atomic_write_json(
            status_path,
            {
                "job_id":
                    job_id,
                "status":
                    "queued",
                "worker_pid":
                    current_pid,
            },
        )

    registration_thread = threading.Thread(
        target=register_worker,
        daemon=True,
    )

    registration_thread.start()

    status = (
        auction_ingest_job
        .wait_for_worker_registration(
            job_id,
            timeout_seconds=2.0,
        )
    )

    registration_thread.join(
        timeout=2.0
    )

    assert not registration_thread.is_alive()

    assert status[
        "worker_pid"
    ] == current_pid


def test_worker_registration_times_out_for_wrong_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker must reject a job registered to another process."""

    job_id = uuid.uuid4().hex

    status_path = (
        tmp_path
        / f"{job_id}.json"
    )

    monkeypatch.setattr(
        auction_ingest_job,
        "job_path",
        lambda _job_id: status_path,
    )

    wrong_pid = (
        os.getpid()
        + 100000
    )

    auction_ingest_job.atomic_write_json(
        status_path,
        {
            "job_id":
                job_id,
            "status":
                "queued",
            "worker_pid":
                wrong_pid,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Parent did not register",
    ):
        (
            auction_ingest_job
            .wait_for_worker_registration(
                job_id,
                timeout_seconds=0.05,
            )
        )
