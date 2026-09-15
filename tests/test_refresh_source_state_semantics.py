"""Protocol and UI contracts for eBay idle and Buyee authentication_required."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import scripts.run_latest_auction_refresh as refresh
from auction_etl.services.refresh_jobs import (
    refresh_job_to_ui_status,
)
from tests.test_cloud_refresh_worker import load_worker
from tests.test_refresh_job_ui_status_contract import job


INGEST_PAGE = Path(
    "app/pages/15_Ingest_New_Auctions.py"
)
RUNNER = Path(
    "scripts/run_latest_auction_refresh.py"
)
WORKER = Path(
    "scripts/run_cloud_refresh_worker.py"
)


def ebay_idle_branch() -> str:
    """Return the preserved external-only idle helper."""
    return inspect.getsource(
        refresh.emit_ebay_external_handoff_idle
    )


def buyee_auth_required_branch() -> str:
    """Return the verifier exit-2 handling branch."""
    source = inspect.getsource(
        refresh.main
    )
    start = source.index(
        "== BUYEE_AUTHENTICATION_REQUIRED_EXIT_CODE"
    )
    end = source.index(
        "== BUYEE_VERIFICATION_TIMEOUT_EXIT_CODE",
        start,
    )

    return source[
        start:end
    ]


def test_ebay_external_idle_emits_awaiting_handoff() -> None:
    """Idle external-only eBay is not a failed or unavailable request."""
    branch = ebay_idle_branch()

    assert '"awaiting_handoff",' in branch
    assert '"unavailable",' not in branch
    assert '"failed",' not in branch
    assert '"done",' not in branch
    assert "EBAY_EXTERNAL_HANDOFF_IDLE" in branch
    assert "browser_acquisition_executed=False" in branch
    assert "ebay_request_executed=False" in branch
    assert "eBay was not checked." in branch
    assert "Existing eBay warehouse rows are preserved." in inspect.getsource(
        refresh.emit_ebay_external_handoff_idle
    )


def test_buyee_exit_2_emits_authentication_required_with_message() -> None:
    """Verifier exit 2 must remain authentication_required, not generic failed."""
    branch = buyee_auth_required_branch()

    assert '"authentication_required",' in branch
    assert '"failed",' not in branch
    assert "set_marketplace_diagnostic(" in branch
    assert "BUYEE_AUTHENTICATION_REQUIRED" in branch
    assert "Buyee authentication is required" in branch


def test_worker_preserves_awaiting_handoff_and_authentication_required() -> None:
    """Durable worker rows must not collapse the new protocol states."""
    worker = load_worker()

    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=eBay state=awaiting_handoff"
    ) == (
        "ebay",
        "awaiting_handoff",
    )
    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=Buyee state=authentication_required"
    ) == (
        "buyee",
        "authentication_required",
    )
    assert worker.parse_source_state(
        "AUCTION_SOURCE_STATE source=Gripsweat state=unavailable"
    ) == (
        "gripsweat",
        "skipped",
    )

    source = WORKER.read_text(
        encoding="utf-8"
    )

    assert '"awaiting_handoff"' in source
    assert '"authentication_required"' in source


def test_worker_persists_buyee_authentication_required_diagnostic() -> None:
    """Exit-2 diagnostics must keep a non-empty authentication message."""
    worker = load_worker()
    calls: list[dict[str, object]] = []

    def record_update(
        _engine,
        **kwargs: object,
    ) -> None:
        calls.append(
            dict(
                kwargs
            )
        )

    worker.update_marketplace_state = record_update
    progress = worker.DurableProgress(
        engine=object(),
        job_id="00000000-0000-0000-0000-000000000001",
        worker_id_value="test-worker",
    )

    progress.consume(
        "AUCTION_SOURCE_STATE "
        "source=Buyee state=authentication_required"
    )
    progress.consume(
        'AUCTION_SOURCE_DIAGNOSTIC source=Buyee '
        'payload={"message":"Buyee authentication is required; '
        'continuing eBay and Gripsweat.",'
        '"runtime_semantics":"BUYEE_AUTHENTICATION_REQUIRED",'
        '"source_state":"authentication_required",'
        '"verifier_exit_code":2}'
    )

    assert calls[0]["state"] == "authentication_required"
    assert calls[0]["message"] != "Marketplace failed."
    assert calls[1]["state"] == "authentication_required"
    assert "Buyee authentication is required" in str(
        calls[1]["message"]
    )
    assert "Marketplace failed." not in str(
        calls[1]["message"]
    )

    error = json.loads(
        str(
            calls[1]["error"]
        )
    )
    assert error["source_state"] == "authentication_required"
    assert error["runtime_semantics"] == (
        "BUYEE_AUTHENTICATION_REQUIRED"
    )
    assert error["verifier_exit_code"] == 2
    assert error["message"]


def test_ui_status_preserves_idle_and_authentication_required() -> None:
    """Control-plane UI mapping must not recode the new states as unavailable."""
    status = refresh_job_to_ui_status(
        job(
            marketplace_states=(
                "authentication_required",
                "awaiting_handoff",
                "running",
            )
        )
    )

    assert status["source_states"] == {
        "buyee": "authentication_required",
        "ebay": "awaiting_handoff",
        "gripsweat": "running",
    }
    assert status["marketplace_states"] == status["source_states"]


def test_ingest_ui_labels_idle_and_authentication_required() -> None:
    """Refresh cards must show truthful copy for idle and auth-required."""
    source = INGEST_PAGE.read_text(
        encoding="utf-8"
    )

    assert '"awaiting_handoff"' in source
    assert '"authentication_required"' in source
    assert 'return "Awaiting external handoff"' in source
    assert 'return "Authentication required"' in source
    assert 'return "Unavailable"' in source
    assert 'return "Failed"' in source
