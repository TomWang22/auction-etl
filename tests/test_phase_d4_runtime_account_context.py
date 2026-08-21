"""Phase D4 source-cutover contracts for account-owned runtime paths."""

from __future__ import annotations

import ast
import hashlib
import hmac
import importlib.util
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    """Read one repository source file."""
    return (ROOT / relative).read_text(encoding="utf-8")


def function_keywords(relative: str, function_name: str) -> set[str]:
    """Return keyword-only and positional argument names for a function."""
    tree = ast.parse(read(relative))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return {
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            }
    raise AssertionError(f"function not found: {relative}:{function_name}")


def test_all_eight_runtime_targets_are_account_aware() -> None:
    """The eight strict runtime paths must carry real account boundaries."""
    expectations = {
        "app/collector_review.py": (
            "AccountContext",
            "account.auction_listing",
            "warehouse.auction_collector",
            "account_id",
        ),
        "app/pages/16_Artists_to_Track.py": (
            "AccountContext",
            "list_account_tracked_artists",
            "upsert_account_artist",
        ),
        "auction_etl/services/artist_tracking.py": (
            "account.tracked_artist",
            "account.artist_marketplace",
            "account_transaction",
        ),
        "auction_etl/services/refresh_jobs.py": (
            "account_id",
            "requested_by_user_id",
            "identity.account_member",
        ),
        "auction_etl/cloud_api.py": (
            "x-auction-account-id",
            "x-auction-user-id",
            "identity.account_member",
        ),
        "scripts/run_cloud_refresh_worker.py": (
            "AUCTION_ACCOUNT_ID",
            "requested_by_user_id",
        ),
        "auction_etl/services/auction_intake.py": (
            "account.auction_listing",
            "set_transaction_account_context",
            "account_id",
        ),
        "app/pages/3_Latest_Auction_Refresh.py": (
            "AccountContext",
            "require_authenticated_account",
            "account_id",
        ),
    }

    for relative, markers in expectations.items():
        source = read(relative)
        for marker in markers:
            assert marker in source, f"{relative} missing {marker!r}"


def test_refresh_public_reads_require_account_id() -> None:
    """Durable refresh reads cannot be called without account ownership."""
    relative = "auction_etl/services/refresh_jobs.py"
    for function_name in (
        "get_refresh_job",
        "get_latest_refresh_job",
        "list_refresh_jobs",
    ):
        assert "account_id" in function_keywords(relative, function_name)


def test_refresh_creation_requires_account_and_requesting_user() -> None:
    """Refresh creation binds owner and authenticated requesting user."""
    keywords = function_keywords(
        "auction_etl/services/refresh_jobs.py",
        "create_refresh_job",
    )
    assert {"account_id", "requested_by_user_id"} <= keywords


def test_artist_mutations_require_account_and_user() -> None:
    """Tracked-artist writes carry both tenancy and audit identity."""
    relative = "auction_etl/services/artist_tracking.py"
    for function_name in (
        "upsert_account_artist",
        "set_account_artist_enabled",
        "remove_account_artist",
    ):
        keywords = function_keywords(relative, function_name)
        assert {"account_id", "user_id"} <= keywords


def test_collector_review_cache_and_write_are_account_keyed() -> None:
    """Collector Review reads and private writes are account keyed."""
    assert "account_id" in function_keywords(
        "app/collector_review.py",
        "load_records",
    )
    write_args = function_keywords(
        "app/collector_review.py",
        "save_collector_record",
    )
    assert {"account_id", "user_id"} <= write_args


def test_intake_mutation_requires_account_and_user() -> None:
    """Assignment mutation carries explicit account and user ownership."""
    args = function_keywords(
        "auction_etl/services/auction_intake.py",
        "apply_assignment",
    )
    assert {"account_id", "user_id", "confirmation_token"} <= args


def test_cloud_control_plane_rejects_body_selected_tenancy() -> None:
    """The cloud endpoint derives tenancy from signed server headers."""
    source = read("auction_etl/cloud_api.py")
    assert '"account_id" in body or "user_id" in body' in source
    assert "derived from signed server context" in source
    assert "x-auction-request-id" in source
    assert "identity.account_member" in source


def test_internal_request_signature_contract() -> None:
    """The shared signing helper produces a deterministic v1 signature."""
    path = ROOT / "auction_etl/auth/internal_request.py"
    spec = importlib.util.spec_from_file_location(
        "phase_d4_internal_request",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    account_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    user_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    timestamp = 1_786_000_000
    request_id = "phase-d4-test-request"
    method = "post"
    path_value = "/api/refresh-jobs/"
    secret = "test-only-not-a-real-secret"

    canonical = "\n".join(
        (
            "collector-ledger-account-request/v1",
            str(timestamp),
            request_id,
            "POST",
            "/api/refresh-jobs",
            str(account_id),
            str(user_id),
        )
    ).encode("utf-8")
    expected = "v1=" + hmac.new(
        secret.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()

    actual = module.sign_account_request(
        secret,
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path=path_value,
        account_id=account_id,
        user_id=user_id,
    )
    assert actual == expected
    assert module.verify_account_request_signature(
        secret,
        actual,
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path=path_value,
        account_id=account_id,
        user_id=user_id,
    )
    assert not module.verify_account_request_signature(
        secret,
        actual,
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path="/api/other",
        account_id=account_id,
        user_id=user_id,
    )


def test_non_admin_report_browser_fails_closed() -> None:
    """Global reporting remains unavailable to ordinary accounts in D4."""
    source = read("app/pages/3_Latest_Auction_Refresh.py")
    assert "if not ACCOUNT_CONTEXT.is_system_admin:" in source
    assert "reporting query itself is account-scoped" in source


def test_worker_refuses_unowned_durable_jobs() -> None:
    """The persistent worker never executes legacy unowned jobs."""
    source = read("scripts/run_cloud_refresh_worker.py")
    assert "Legacy unowned jobs must not execute in Phase D." in source
