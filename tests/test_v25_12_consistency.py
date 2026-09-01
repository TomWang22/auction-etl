
"""V25.12 consistency regressions for marketplace UI and repeat refreshes."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PAGE = (
    ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)

PROBE = (
    ROOT
    / "scripts"
    / "probe_gripsweat.py"
)

REFRESH_JOBS = (
    ROOT
    / "auction_etl"
    / "services"
    / "refresh_jobs.py"
)


def source(path: Path) -> str:
    """Return UTF-8 source."""

    return path.read_text(
        encoding="utf-8"
    )


def function_source(
    path: Path,
    function_name: str,
) -> str:
    """Return one top-level function source block."""

    value = source(path)

    tree = ast.parse(
        value,
        filename=str(path),
    )

    matches = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == function_name
        )
    ]

    assert len(matches) == 1

    block = ast.get_source_segment(
        value,
        matches[0],
    )

    assert block is not None

    return block


def test_completed_with_unavailable_marketplace_is_explicitly_partial() -> None:
    """Two successful sources plus unavailable eBay must render as 67%."""

    durable = function_source(
        PAGE,
        "durable_source_states",
    )

    render = function_source(
        PAGE,
        "render_status",
    )

    service = function_source(
        REFRESH_JOBS,
        "refresh_job_to_ui_status",
    )

    assert '"source_states"' in durable
    assert '"marketplace_states"' in durable
    assert 'state = "unavailable"' in durable

    assert "Completed with issues" in render
    assert "stage_percent" in render
    assert 'f"({stage_percent}%)"' in render

    assert 'marketplace_state = (' in service
    assert '"unavailable"' in service


def test_ebay_access_block_remains_nonfatal_unavailable_semantics() -> None:
    """Anonymous eBay sign-in blocking is not a successful marketplace."""

    runner = source(
        ROOT
        / "scripts"
        / "run_latest_auction_refresh.py"
    )

    assert "EBAY_SOURCE_UNAVAILABLE_ACCESS_BLOCKED" in runner
    assert "eBay programmatic access is blocked" in runner
    assert "Continuing Gripsweat refresh." in runner


def test_gripsweat_known_page_predicate() -> None:
    """The early-stop predicate requires a nonempty fully-known page."""

    probe = source(PROBE)

    tree = ast.parse(
        probe,
        filename=str(PROBE),
    )

    target = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "page_is_fully_known"
        )
    )

    block = ast.get_source_segment(
        probe,
        target,
    )

    assert block is not None

    namespace: dict[str, object] = {}

    exec(
        compile(
            "from __future__ import annotations\n"
            + block
            + "\n",
            str(PROBE),
            "exec",
        ),
        namespace,
    )

    predicate = namespace[
        "page_is_fully_known"
    ]

    assert callable(predicate)

    assert predicate(
        {"a", "b"},
        {"a", "b", "c"},
    )

    assert not predicate(
        {"a", "new"},
        {"a", "b", "c"},
    )

    assert not predicate(
        set(),
        {"a", "b", "c"},
    )


def test_gripsweat_probe_stops_before_older_pages_when_page_is_known() -> None:
    """Repeat refreshes must not crawl older pages after a fully-known page."""

    probe_source = function_source(
        PROBE,
        "probe_source",
    )

    main = function_source(
        PROBE,
        "main",
    )

    assert "known_item_keys" in probe_source
    assert "page_fully_known" in probe_source
    assert "page_is_fully_known(" in probe_source
    assert "newest remaining page" in probe_source
    assert "is fully known" in probe_source

    known_stop = probe_source.index(
        "if page_fully_known:"
    )

    next_page_stop = probe_source.index(
        "if not next_detected:"
    )

    assert known_stop < next_page_stop

    assert "known_gripsweat_item_keys(" in main
    assert "known_item_keys=known_item_keys" in main
