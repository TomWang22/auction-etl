"""Regression coverage for Gripsweat detail reimport identity."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from types import FunctionType

import pytest


ROOT = Path(__file__).resolve().parents[1]

ENRICH = (
    ROOT
    / "scripts"
    / "enrich_gripsweat_details.py"
)

IMPORTER = (
    ROOT
    / "scripts"
    / "import_gripsweat_probe.py"
)


def function_source(
    path: Path,
    name: str,
) -> str:
    """Return one top-level function source segment."""

    source = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    matches = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == name
        )
    ]

    assert len(matches) == 1

    segment = ast.get_source_segment(
        source,
        matches[0],
    )

    assert segment is not None

    return segment


def load_unique_probe_sale_id() -> FunctionType:
    """Compile the pure uniqueness guard without importing runtime services."""

    source = ENRICH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(ENRICH),
    )

    matches = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "unique_probe_sale_id"
        )
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

    namespace: dict[str, object] = {
        "Iterable": Iterable,
    }

    exec(
        compile(
            module,
            str(ENRICH),
            "exec",
        ),
        namespace,
    )

    function = namespace[
        "unique_probe_sale_id"
    ]

    assert isinstance(
        function,
        FunctionType,
    )

    return function


def test_one_identity_resolves_existing_sale() -> None:
    """One database identity is the only automatic update target."""

    resolve = load_unique_probe_sale_id()

    assert (
        resolve(
            [42],
            source_name="source-a",
            item_id="366019024552",
        )
        == 42
    )


def test_duplicate_identity_hits_collapse_to_one_sale() -> None:
    """Several matching identity paths may point to the same row."""

    resolve = load_unique_probe_sale_id()

    assert (
        resolve(
            [
                42,
                42,
                42,
            ],
            source_name="source-a",
            item_id="366019024552",
        )
        == 42
    )


def test_zero_identity_hits_fail_closed() -> None:
    """A missing stored sale cannot be silently inserted by enrichment."""

    resolve = load_unique_probe_sale_id()

    with pytest.raises(
        RuntimeError,
        match="No existing Gripsweat sale row resolved",
    ):
        resolve(
            [],
            source_name="source-a",
            item_id="366019024552",
        )


def test_conflicting_identity_hits_fail_closed() -> None:
    """Distinct rows must never be automatically merged."""

    resolve = load_unique_probe_sale_id()

    with pytest.raises(
        RuntimeError,
        match="different existing sale rows",
    ):
        resolve(
            [
                42,
                84,
            ],
            source_name="source-a",
            item_id="366019024552",
        )


def test_reimport_uses_canonical_importer_identity_paths() -> None:
    """Detail reimport must resolve the same stable identities as import."""

    reimport = function_source(
        ENRICH,
        "reimport_probe_rows",
    )

    importer = IMPORTER.read_text(
        encoding="utf-8"
    )

    required = (
        "gripsweat_url = :gripsweat_url",
        "source_name = :source_name",
        "gripsweat_item_key = :gripsweat_item_key",
        "original_marketplace = :original_marketplace",
        "original_listing_id = :original_listing_id",
        "FOR UPDATE",
    )

    for fragment in required:
        assert fragment in importer
        assert fragment in reimport


def test_reimport_updates_resolved_database_id() -> None:
    """The final write must use resolved row identity, not source/key only."""

    reimport = function_source(
        ENRICH,
        "reimport_probe_rows",
    )

    update_start = reimport.index(
        "update_statement = text("
    )

    update_end = reimport.index(
        "with engine.begin()",
        update_start,
    )

    update_sql = reimport[
        update_start:update_end
    ]

    assert "WHERE id = :sale_id" in update_sql

    assert (
        "WHERE source_name = :source_name"
        not in update_sql
    )

    assert (
        "gripsweat_item_key = :gripsweat_item_key"
        in update_sql
    )

    assert (
        "gripsweat_item_id = :gripsweat_item_id"
        in update_sql
    )


def test_reimport_remains_update_only() -> None:
    """Detail enrichment must never create a missing sale."""

    reimport = function_source(
        ENRICH,
        "reimport_probe_rows",
    )

    normalized = reimport.casefold()

    assert "insert into" not in normalized
    assert "unique_probe_sale_id(" in reimport

    assert (
        "GRIPSWEAT_UPDATE_ONLY_DETAIL_REIMPORT_V2"
        in reimport
    )


def test_old_updated_zero_locator_is_removed() -> None:
    """The production failure must not retain its narrow write locator."""

    reimport = function_source(
        ENRICH,
        "reimport_probe_rows",
    )

    assert (
        "Expected exactly one existing Gripsweat "
        "sale row for"
        not in reimport
    )

    assert (
        "Resolved Gripsweat sale row "
        in reimport
    )
