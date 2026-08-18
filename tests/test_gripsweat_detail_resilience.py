"""Regression tests for resilient Gripsweat detail enrichment."""

from __future__ import annotations

import ast
from pathlib import Path
from types import FunctionType


ROOT = Path(__file__).resolve().parents[1]

ENRICH = (
    ROOT
    / "scripts"
    / "enrich_gripsweat_details.py"
)

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)


def function_source(
    path: Path,
    name: str,
) -> str:
    """Return one top-level function source segment."""

    source = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == name
    ]

    assert len(matches) == 1

    segment = ast.get_source_segment(
        source,
        matches[0],
    )

    assert segment is not None

    return segment


def load_retry_classifier() -> FunctionType:
    """Compile the pure retry classifier."""

    source = ENRICH.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(ENRICH),
    )

    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name
        == "retryable_navigation_error"
    ]

    assert len(matches) == 1

    module = ast.Module(
        body=[
            matches[0],
        ],
        type_ignores=[],
    )

    ast.fix_missing_locations(
        module
    )

    namespace: dict[
        str,
        object,
    ] = {}

    exec(
        compile(
            module,
            str(ENRICH),
            "exec",
        ),
        namespace,
    )

    function = namespace[
        "retryable_navigation_error"
    ]

    assert isinstance(
        function,
        FunctionType,
    )

    return function


def test_retry_classifier_matches_live_failures() -> None:
    """Retry both transient production failures."""

    retryable = load_retry_classifier()

    assert retryable(
        "Page.goto: net::ERR_NETWORK_IO_SUSPENDED "
        "at https://gripsweat.com/item/133522733977/"
    )

    assert retryable(
        "Page.goto: Timeout 90000ms exceeded."
    )

    assert not retryable(
        "Missing required detail fields: sold_at"
    )

    assert not retryable(
        None
    )


def test_normal_enrichment_is_incremental() -> None:
    """Normal refreshes select only incomplete detail rows."""

    segment = function_source(
        ENRICH,
        "load_sales",
    )

    assert (
        "original_listing_id IS NULL"
        not in segment
    )

    assert (
        "detail_status IS DISTINCT FROM 'complete'"
        in segment
    )

    assert "title IS NULL" in segment
    assert "sold_at IS NULL" in segment


def test_complete_definition_does_not_require_original_id() -> None:
    """The SQL selector must match DetailResult completeness."""

    segment = function_source(
        ENRICH,
        "inspect_sale",
    )

    assert "result.title is not None" in segment
    assert "result.sold_at is not None" in segment
    assert "result.sold_price is not None" in segment

    complete_block = segment[
        segment.index(
            "result.complete ="
        ):
        segment.index(
            "if not result.complete"
        )
    ]

    assert (
        "original_listing_id"
        not in complete_block
    )


def test_production_runner_is_incremental() -> None:
    """Production must not force all complete rows to recrawl."""

    source = RUNNER.read_text(
        encoding="utf-8",
    )

    marker = (
        '"scripts/enrich_gripsweat_details.py",'
    )

    start = source.index(
        marker
    )

    end = source.index(
        'phase="Apply Gripsweat detail enrichment"',
        start,
    )

    command = source[
        start:end
    ]

    assert (
        '"--refresh-complete"'
        not in command
    )

    assert '"--attempts",' in command
    assert '"3",' in command
    assert '"--retry-delay",' in command
    assert '"10",' in command


def test_retry_uses_fresh_page_and_bounded_backoff() -> None:
    """Each retry gets a fresh page and bounded delay."""

    segment = function_source(
        ENRICH,
        "inspect_sale_with_retry",
    )

    assert "context.new_page()" in segment
    assert "page.close()" in segment
    assert "retryable_navigation_error(" in segment
    assert "attempts + 1" in segment
    assert "time.sleep(" in segment
    assert "60.0" in segment


def test_main_uses_retry_wrapper() -> None:
    """Main processing must route every sale through retries."""

    segment = function_source(
        ENRICH,
        "main",
    )

    assert "inspect_sale_with_retry(" in segment
    assert "context.new_page()" not in segment


def test_unresolved_detail_still_fails_command() -> None:
    """Retries cannot convert an unresolved row into success."""

    segment = function_source(
        ENRICH,
        "main",
    )

    assert (
        "return 0 if incomplete == 0 else 1"
        in segment
    )
