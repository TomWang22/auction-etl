"""Local opt-in eBay auto-handoff stays off cloud and off the crawler."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Iterable

import scripts.run_latest_auction_refresh as refresh


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"
CRAWLER = "scripts/crawl_ebay_sources.py"


def string_constants(
    nodes: Iterable[ast.AST],
) -> set[str]:
    values: set[str] = set()

    for node in nodes:
        for descendant in ast.walk(node):
            if (
                isinstance(descendant, ast.Constant)
                and isinstance(descendant.value, str)
            ):
                values.add(descendant.value)

    return values


def function_named(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node

    raise AssertionError(f"Function not found: {name}")


def test_local_auto_handoff_is_opt_in_and_rejected_on_cloud() -> None:
    assert refresh.ebay_local_auto_handoff_allowed({}) is False
    assert refresh.ebay_local_auto_handoff_allowed(
        {"AUCTION_EBAY_LOCAL_AUTO_HANDOFF": "1"}
    ) is True
    assert refresh.ebay_local_auto_handoff_allowed(
        {
            "AUCTION_EBAY_LOCAL_AUTO_HANDOFF": "1",
            "VERCEL": "1",
        }
    ) is False
    assert refresh.ebay_local_auto_handoff_allowed(
        {
            "AUCTION_EBAY_LOCAL_AUTO_HANDOFF": "1",
            "RAILWAY_DEPLOYMENT_ID": "x",
        }
    ) is False


def test_auto_handoff_uses_owner_acquire_import_and_exact_raw_page() -> None:
    source = inspect.getsource(
        refresh.run_ebay_local_auto_handoff
    )

    assert "scripts/ensure_ebay_owner.py" in source
    assert "scripts/acquire_ebay_structured.py" in source
    assert "--owner-socket" in source
    assert "scripts/import_ebay_structured.py" in source
    assert "--apply" in source
    assert "process_ebay_raw_pages(" in source
    assert "raw_page_id=" in source
    assert CRAWLER not in source
    assert "--headless" not in source
    assert "stealth" not in source.casefold()
    assert "retry" not in source.casefold()


def test_auto_handoff_is_nested_inside_external_idle_not_crawler_fallback() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RUNNER))
    main_function = function_named(tree, "main")
    idle_function = function_named(
        tree,
        "emit_ebay_external_handoff_idle",
    )
    auto_function = function_named(
        tree,
        "run_ebay_local_auto_handoff",
    )

    main_source = inspect.getsource(refresh.main)
    pending_position = main_source.index(
        "if pending_ebay_raw_pages > 0:"
    )
    auto_position = main_source.index(
        "ebay_local_auto_handoff_allowed("
    )
    external_position = main_source.index(
        "elif ebay_external_handoff_only("
    )
    browser_position = main_source.index(
        '"scripts/crawl_ebay_sources.py"'
    )

    assert pending_position < external_position < browser_position
    assert external_position < auto_position < browser_position

    assert CRAWLER not in string_constants([idle_function, auto_function])
    assert CRAWLER in string_constants([main_function])
    assert "EBAY_EXTERNAL_HANDOFF_IDLE" in string_constants(
        [idle_function]
    )
    assert "scripts/acquire_ebay_structured.py" in string_constants(
        [auto_function]
    )
    assert "scripts/import_ebay_structured.py" in string_constants(
        [auto_function]
    )
