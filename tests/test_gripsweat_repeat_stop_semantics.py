from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_latest_auction_refresh.py"


def load_helper():
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RUNNER))
    names = {"_incremental_unique", "_incremental_window_is_fully_known"}
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    assert functions.keys() == names
    module = ast.Module(
        body=[
            functions["_incremental_unique"],
            functions["_incremental_window_is_fully_known"],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(RUNNER), "exec"), namespace)
    return namespace["_incremental_window_is_fully_known"]


def test_small_fully_known_window_stops() -> None:
    helper = load_helper()
    assert helper(["a", "b", "c"], {"a", "b", "c", "older"})


def test_new_identity_keeps_deeper_discovery() -> None:
    helper = load_helper()
    assert not helper(["a", "new"], {"a"})


def test_empty_window_does_not_stop() -> None:
    helper = load_helper()
    assert not helper([], {"a"})


def test_duplicates_do_not_change_result() -> None:
    helper = load_helper()
    assert helper(["a", "a", "b", "b"], {"a", "b"})


def test_threshold_scope() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "GRIPSWEAT_KNOWN_STOP_THRESHOLD" not in source
    assert "EBAY_KNOWN_STOP_THRESHOLD = 20" in source
    assert "gripsweat_probe_window_fully_known" in source
