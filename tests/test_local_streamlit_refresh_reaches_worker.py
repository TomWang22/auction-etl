"""Prove local Streamlit refresh enqueue is claimable by the local worker.

This is a queue/worker contract. It must not scrape eBay, launch Chromium,
or dispatch through Vercel/Railway.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from auction_etl.auth.context import AccountContext
from auction_etl.runtime_authority import cloud_runtime_detected
from auction_etl.services.local_refresh_dispatch import (
    LocalRefreshDispatchError,
    enqueue_refresh_via_local_worker,
)
from auction_etl.services.refresh_jobs import (
    build_refresh_engine,
    claim_next_refresh_job,
    coordination_schema_ready,
    mark_refresh_job_failed,
)


ROOT = Path(__file__).resolve().parents[1]
REFRESH_UI = (
    ROOT
    / "app"
    / "pages"
    / "3_Latest_Auction_Refresh.py"
)
INGEST_UI = (
    ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)
WORKER = (
    ROOT
    / "scripts"
    / "run_cloud_refresh_worker.py"
)
DISPATCH = (
    ROOT
    / "auction_etl"
    / "services"
    / "local_refresh_dispatch.py"
)


def test_latest_refresh_ui_enqueues_locally_not_via_vercel() -> None:
    """Collector Refresh must queue durable work in the local warehouse."""
    source = REFRESH_UI.read_text(
        encoding="utf-8"
    )

    assert "enqueue_refresh_via_local_worker" in source
    assert "create_refresh_job(" not in source
    assert "enqueue_refresh_via_control_plane" not in source
    assert "AUCTION_CONTROL_PLANE_URL" not in source
    assert "subprocess.Popen" not in source
    assert "crawl_ebay_sources.py" not in source


def test_ingest_ui_enqueues_locally_not_via_vercel() -> None:
    """Ingest New Auctions must use the same local durable queue."""
    source = INGEST_UI.read_text(
        encoding="utf-8"
    )

    assert "enqueue_refresh_via_local_worker" in source
    assert "enqueue_refresh_via_control_plane" not in source
    assert "AUCTION_CONTROL_PLANE_URL" not in source


def test_local_dispatch_rejects_cloud_runtimes() -> None:
    """Vercel and Railway must not enqueue local warehouse refresh jobs."""
    context = AccountContext(
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        account_id=UUID("22222222-2222-4222-8222-222222222222"),
        role="owner",
        email="owner@example.com",
        display_name="Owner",
        is_system_admin=False,
    )

    with pytest.raises(
        LocalRefreshDispatchError,
        match="local",
    ):
        enqueue_refresh_via_local_worker(
            database_url="postgresql://auction@127.0.0.1:5544/auction_warehouse",
            account_context=context,
            environment={
                "VERCEL": "1",
            },
        )


def test_local_dispatch_helper_is_not_a_browser_owner() -> None:
    """Queue proof must stay independent of eBay Chromium."""
    source = DISPATCH.read_text(
        encoding="utf-8"
    )

    assert "playwright" not in source.casefold()
    assert "chromium" not in source.casefold()
    assert "crawl_ebay_sources.py" not in source
    assert "cloud_runtime_detected" in source
    assert "create_refresh_job" in source
    assert "claim_next_refresh_job" not in source


def test_worker_still_claims_durable_jobs_locally() -> None:
    """The persistent worker remains the claimer of queued refresh jobs."""
    source = WORKER.read_text(
        encoding="utf-8"
    )

    assert "claim_next_refresh_job" in source
    assert "run_multisource_ingestion_round.py" in source
    assert "cloud_worker_execution_allowed_here" in source


def test_cloud_runtime_detector_still_sees_vercel_and_railway() -> None:
    """Keep the local-only enqueue boundary honest."""
    assert cloud_runtime_detected({}) is False
    assert cloud_runtime_detected({"VERCEL": "1"}) is True
    assert cloud_runtime_detected(
        {"RAILWAY_DEPLOYMENT_ID": "x"}
    ) is True


def test_local_dispatch_returns_ui_status_from_create_refresh_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Streamlit helper must create a warehouse job, not call Vercel."""
    captured: dict[str, object] = {}

    def fake_create(engine, **kwargs):
        captured.update(kwargs)
        return (
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "state": "queued",
                "message": "Waiting for the persistent marketplace worker.",
                "marketplaces": [],
            },
            True,
        )

    monkeypatch.setattr(
        "auction_etl.services.local_refresh_dispatch.build_refresh_engine",
        lambda url: object(),
    )
    monkeypatch.setattr(
        "auction_etl.services.local_refresh_dispatch.create_refresh_job",
        fake_create,
    )

    context = AccountContext(
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        account_id=UUID("22222222-2222-4222-8222-222222222222"),
        role="owner",
        email="owner@example.com",
        display_name="Owner",
        is_system_admin=False,
    )

    status, created = enqueue_refresh_via_local_worker(
        database_url="postgresql://auction@127.0.0.1:5544/auction_warehouse",
        account_context=context,
        environment={},
    )

    assert created is True
    assert status["job_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert status["state"] == "queued"
    assert captured["trigger"] == "streamlit-local"
    assert captured["account_id"] == context.account_id
    assert captured["requested_by_user_id"] == context.user_id


def test_local_enqueue_is_claimable_by_the_worker_without_scraping() -> None:
    """Create one local job and claim it. Do not run marketplace browsers."""
    if cloud_runtime_detected():
        pytest.skip("Cloud runtimes must not touch the local warehouse.")

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://auction:auction@127.0.0.1:5544/auction_warehouse",
    )

    if "127.0.0.1:5544" not in database_url:
        pytest.skip("Live queue proof requires the local warehouse.")

    engine = build_refresh_engine(database_url)
    if not coordination_schema_ready(engine):
        pytest.skip("Durable refresh tables are not present.")

    with engine.connect() as connection:
        active = connection.execute(
            text(
                """
                SELECT id
                FROM ops.refresh_job
                WHERE state IN ('queued', 'running')
                LIMIT 1
                """
            )
        ).scalar_one_or_none()

        if active is not None:
            pytest.skip(
                "An active refresh already exists; refusing to interfere."
            )

    user_id = uuid4()
    account_id = uuid4()
    email = f"queue-proof-{user_id.hex}@example.test"
    queued_job_id = ""
    claimed = None

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO identity.app_user (
                        id,
                        provider,
                        subject,
                        email,
                        display_name,
                        is_system_admin
                    )
                    VALUES (
                        :user_id,
                        'queue-proof',
                        :subject,
                        :email,
                        'Queue Proof',
                        false
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "subject": str(user_id),
                    "email": email,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO identity.account (
                        id,
                        name,
                        account_type
                    )
                    VALUES (
                        :account_id,
                        'Queue Proof',
                        'personal'
                    )
                    """
                ),
                {"account_id": account_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO identity.account_member (
                        account_id,
                        user_id,
                        role
                    )
                    VALUES (
                        :account_id,
                        :user_id,
                        'owner'
                    )
                    """
                ),
                {
                    "account_id": account_id,
                    "user_id": user_id,
                },
            )

        context = AccountContext(
            user_id=user_id,
            account_id=account_id,
            role="owner",
            email=email,
            display_name="Queue Proof",
            is_system_admin=False,
        )

        status, created = enqueue_refresh_via_local_worker(
            database_url=database_url,
            account_context=context,
            engine=engine,
            environment={},
        )

        assert created is True
        queued_job_id = str(status["job_id"])
        assert queued_job_id
        assert status["state"] == "queued"

        claimed = claim_next_refresh_job(
            engine,
            worker_id="local-queue-proof-worker",
            lease_seconds=30,
        )

        assert claimed is not None
        assert str(claimed["id"]) == queued_job_id
        assert claimed["state"] == "running"
        assert claimed["lease_owner"] == "local-queue-proof-worker"
    finally:
        if claimed is not None:
            mark_refresh_job_failed(
                engine,
                job_id=claimed["id"],
                worker_id="local-queue-proof-worker",
                error=(
                    "Queue-to-worker proof only; marketplace browsers "
                    "were not started."
                ),
                message="Local Streamlit-to-worker proof completed.",
            )
        elif queued_job_id:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE ops.refresh_job
                        SET
                            state = 'failed',
                            finished_at = now(),
                            error = :error,
                            message = :message,
                            updated_at = now()
                        WHERE id = CAST(:job_id AS uuid)
                          AND state IN ('queued', 'running')
                        """
                    ),
                    {
                        "job_id": queued_job_id,
                        "error": (
                            "Queue-to-worker proof cleanup; claim did not "
                            "succeed."
                        ),
                        "message": "Local Streamlit-to-worker proof cleanup.",
                    },
                )

        with engine.begin() as connection:
            if queued_job_id:
                connection.execute(
                    text(
                        """
                        DELETE FROM ops.refresh_job
                        WHERE id = CAST(:job_id AS uuid)
                        """
                    ),
                    {"job_id": queued_job_id},
                )
            connection.execute(
                text(
                    """
                    DELETE FROM identity.account_member
                    WHERE account_id = :account_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "account_id": account_id,
                    "user_id": user_id,
                },
            )
            connection.execute(
                text(
                    """
                    DELETE FROM identity.account
                    WHERE id = :account_id
                    """
                ),
                {"account_id": account_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM identity.app_user
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id},
            )
