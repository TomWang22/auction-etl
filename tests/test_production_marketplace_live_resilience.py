"""Production contracts for all-source resilience and live visibility."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"
WORKER = ROOT / "scripts" / "run_cloud_refresh_worker.py"
EBAY = ROOT / "scripts" / "crawl_ebay_sources.py"
GRIPSWEAT_PROBE = ROOT / "scripts" / "probe_gripsweat.py"
GRIPSWEAT_AUDIT = ROOT / "scripts" / "audit_gripsweat_pagination.py"
GRIPSWEAT_DETAILS = ROOT / "scripts" / "enrich_gripsweat_details.py"
BROWSER_RUNTIME = (
    ROOT
    / "auction_etl"
    / "services"
    / "marketplace_browser_runtime.py"
)
REVIEW = ROOT / "app" / "collector_review.py"


def source(path: Path) -> str:
    """Read and compile one source contract."""
    value = path.read_text(encoding="utf-8")
    ast.parse(value, filename=str(path))
    return value


def function_block(
    path: Path,
    name: str,
) -> str:
    """Return one top-level function block."""
    value = source(path)
    tree = ast.parse(value, filename=str(path))

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            block = ast.get_source_segment(
                value,
                node,
            )
            assert block is not None
            return block

    raise AssertionError(
        f"Function not found: {name}"
    )


def test_cloud_marketplace_browser_is_ephemeral_on_railway() -> None:
    """Cloud collectors must not reopen the persistent profile mount."""
    runtime = source(BROWSER_RUNTIME)

    assert "AUCTION_MARKETPLACE_BROWSER_MODE" in runtime
    assert '"ephemeral"' in runtime
    assert "_railway_runtime" in runtime
    assert "chromium.launch(" in runtime
    assert "launch_persistent_context(" not in runtime
    assert "--no-sandbox" in runtime
    assert "--disable-dev-shm-usage" in runtime


def test_ebay_and_every_gripsweat_browser_stage_use_cloud_runtime() -> None:
    """All browser-backed non-Buyee sources share the Railway-safe path."""
    expected_import = (
        "from auction_etl.services.marketplace_browser_runtime "
        "import browser"
    )

    for path in (
        EBAY,
        GRIPSWEAT_PROBE,
        GRIPSWEAT_AUDIT,
        GRIPSWEAT_DETAILS,
    ):
        value = source(path)
        assert expected_import in value
        assert (
            "from auction_etl.browser.manager import browser"
            not in value
        )


def test_buyee_visibility_is_published_before_detail_enrichment() -> None:
    """New Buyee identities reach Review before slow detail fallback."""
    runner = source(RUNNER)

    sync_index = runner.index(
        '"Safely synchronize Buyee without pruning"'
    )
    publish_index = runner.index(
        'source="Buyee"',
        sync_index,
    )
    details_index = runner.index(
        '"Buyee new-only detail enrichment"',
        publish_index,
    )

    assert sync_index < publish_index < details_index


def test_ebay_visibility_is_published_after_each_safe_sync() -> None:
    """Each completed eBay sync can become account-visible immediately."""
    block = function_block(
        RUNNER,
        "process_ebay_raw_pages",
    )

    sync_index = block.index(
        '"Safely synchronize eBay without pruning"'
    )
    publish_index = block.index(
        'source="eBay"',
        sync_index,
    )

    assert sync_index < publish_index


def test_gripsweat_visibility_is_published_during_discovery() -> None:
    """Probe and pagination imports publish before detail enrichment ends."""
    runner = source(RUNNER)

    probe_import = runner.index(
        '"Import Gripsweat probe"'
    )
    probe_publish = runner.index(
        'source="Gripsweat"',
        probe_import,
    )
    pagination_import = runner.index(
        '"Import Gripsweat identities"'
    )
    pagination_publish = runner.index(
        'source="Gripsweat"',
        pagination_import,
    )
    detail_enrichment = runner.index(
        '"Apply Gripsweat detail enrichment"'
    )

    assert probe_import < probe_publish
    assert pagination_import < pagination_publish
    assert probe_publish < detail_enrichment
    assert pagination_publish < detail_enrichment


def test_unclassified_ebay_failure_does_not_block_gripsweat() -> None:
    """A failed eBay crawl is durable but the next source is still attempted."""
    runner = source(RUNNER)

    failed_state = runner.index(
        'status["ebay_source_state"] = "failed"'
    )
    failed_emit = runner.index(
        '"eBay",\n                        "failed"',
        failed_state,
    )
    gripsweat_start = runner.index(
        '"Gripsweat",\n            "running"',
        failed_emit,
    )

    assert failed_state < failed_emit < gripsweat_start
    assert (
        "Continuing Gripsweat refresh."
        in runner[
            failed_state:
            gripsweat_start
        ]
    )


def test_required_source_failure_is_decided_after_source_attempts() -> None:
    """require-all affects final acceptance instead of short-circuiting eBay."""
    runner = source(RUNNER)

    eBay_start = runner.index(
        '"eBay",\n            "running"'
    )
    gripsweat_start = runner.index(
        '"Gripsweat",\n            "running"',
        eBay_start,
    )

    eBay_block = runner[
        eBay_start:
        gripsweat_start
    ]

    assert (
        "Required source eBay is unavailable"
        not in eBay_block
    )
    assert "required_unavailable" in runner
    assert "terminal_failures" in runner


def test_worker_preserves_successful_later_marketplace_on_global_failure() -> None:
    """Job failure terminalizes only nonterminal source rows."""
    worker = source(WORKER)

    assert "self._failed_marketplaces" in worker
    assert "def finalize_runner_failure" in worker
    assert "progress.finalize_runner_failure(" in worker
    assert 'if state != "waiting":' in worker


def test_review_surface_rerenders_live_account_visibility() -> None:
    """Review marketplace sales refreshes while source publication advances."""
    review = source(REVIEW)

    assert "@st.fragment(" in review
    assert 'run_every="3s"' in review
    assert "rerun_review_while_refresh_active" in review
    assert "account_refresh_is_active" in review
    assert "FROM ops.refresh_job" in review
    assert "load_records.clear()" in review
    assert "st.rerun()" in review
    assert "account.auction_listing" in review
    assert "@st.cache_data(" in review
    assert "ttl=2" in review

def test_ebay_failure_persists_child_output_without_cross_source_leak() -> None:
    """eBay diagnostics must retain the child error and stay source-scoped."""
    runner = source(RUNNER)
    emit_block = function_block(
        RUNNER,
        "emit_source_state",
    )

    assert "marketplace_diagnostics" in emit_block
    assert 'status.get(\n                    "message"' not in emit_block
    assert "bounded_command_output" in runner
    assert "command_output_tail" in runner
    assert "eBay child output tail" in runner
    assert '"captcha"' in runner
    assert '"robot check"' in runner
    assert '"access denied"' in runner


def test_gripsweat_incomplete_details_are_nonfatal_in_production() -> None:
    """Durable identity ingestion must survive partial detail enrichment."""
    runner = source(RUNNER)
    details = source(GRIPSWEAT_DETAILS)

    assert '"--allow-incomplete"' in runner
    assert '"--allow-incomplete"' in details
    assert "GRIPSWEAT_INCOMPLETE_DETAIL_POLICY=CONTINUE" in details
    assert "_incremental_detail_result_counts" in runner
    assert "GRIPSWEAT_DETAIL_ENRICHMENT_PARTIAL" in runner


def test_worker_terminalizes_marketplaces_before_parent_failure() -> None:
    """A terminal parent job must not leave a marketplace running forever."""
    worker = source(WORKER)
    block = function_block(
        WORKER,
        "execute_claimed_job",
    )

    assert "def finalize_runner_failure" in worker
    assert "progress.finalize_runner_failure(" in block
    assert 'state="failed"' in worker
    assert 'state="skipped"' in worker
    assert "marketplace=None" in block


def test_refresh_ui_separates_marketplace_and_record_progress() -> None:
    """Marketplace success and record throughput are separate metrics."""

    page_path = (
        ROOT
        / "app"
        / "pages"
        / "15_Ingest_New_Auctions.py"
    )

    page = source(
        page_path
    )

    block = function_block(
        page_path,
        "render_status",
    )

    assert (
        "def marketplace_stage_counts"
        in page
    )

    assert (
        "Marketplaces updated:"
        in block
    )

    assert (
        "completed_stages"
        in block
    )

    assert (
        "settled"
        not in block
    )

    assert (
        "Record processing:"
        in block
    )

    assert (
        '"not_run"'
        in page
    )

def test_buyee_waf_detail_failure_does_not_stop_later_sources() -> None:
    """Secondary Buyee detail failure must not short-circuit eBay."""

    runner = source(
        RUNNER
    )

    fallback = runner.index(
        "buyee_browser_fallback_status"
    )

    ebay_start = runner.index(
        '"eBay",\n            "running"',
        fallback,
    )

    block = runner[
        fallback:
        ebay_start
    ]

    assert (
        "allow_failure=True"
        in block
    )

    assert (
        "BUYEE_DETAIL_ENRICHMENT_PARTIAL"
        in block
    )

    assert (
        "command_output_tail"
        in block
    )

    assert (
        "Continuing eBay and Gripsweat."
        in block
    )


def test_not_run_is_distinct_from_unavailable() -> None:
    """A source never attempted after parent failure must say Not run."""

    refresh_jobs_path = (
        ROOT
        / "auction_etl"
        / "services"
        / "refresh_jobs.py"
    )

    page_path = (
        ROOT
        / "app"
        / "pages"
        / "15_Ingest_New_Auctions.py"
    )

    refresh_block = function_block(
        refresh_jobs_path,
        "refresh_job_to_ui_status",
    )

    page = source(
        page_path
    )

    assert (
        "not reached because the "
        in refresh_block
    )

    assert (
        "refresh runner stopped"
        in refresh_block
    )

    assert (
        "cancelled before execution"
        in refresh_block
    )

    assert (
        '"not_run"'
        in refresh_block
    )

    assert (
        '"unavailable"'
        in refresh_block
    )

    assert (
        'return "Not run"'
        in page
    )

    assert (
        'return "Unavailable"'
        in page
    )


def test_partial_diagnostics_survive_successful_identity_ingestion() -> None:
    """Child diagnostic output remains available after identity success."""

    worker = source(
        WORKER
    )

    assert (
        '"command_output_tail"'
        in worker
    )

    assert (
        "Durable production diagnostics"
        in source(
            ROOT
            / "app"
            / "pages"
            / "15_Ingest_New_Auctions.py"
        )
    )
