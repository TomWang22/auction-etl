"""Regression coverage for collector refresh round-trip suppression."""

from __future__ import annotations

import ast
from pathlib import Path
from types import FunctionType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

COLLECTOR = (
    ROOT
    / "scripts"
    / "collector_features.py"
)

RECLASSIFY = (
    ROOT
    / "scripts"
    / "reclassify_collector.py"
)

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)


def source_text(
    path: Path,
) -> str:
    """Return validated Python source."""

    source = path.read_text(
        encoding="utf-8"
    )

    ast.parse(
        source,
        filename=str(path),
    )

    return source


def function_source(
    path: Path,
    name: str,
) -> str:
    """Return one top-level function's source."""

    source = source_text(
        path
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


def load_change_detector() -> tuple[
    tuple[str, ...],
    FunctionType,
]:
    """Compile the pure stored-value comparison contract."""

    source = source_text(
        RECLASSIFY
    )

    tree = ast.parse(
        source,
        filename=str(RECLASSIFY),
    )

    field_nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.Assign,
            )
            and any(
                isinstance(
                    target,
                    ast.Name,
                )
                and target.id
                == "RECLASSIFICATION_FIELDS"
                for target in node.targets
            )
        )
    ]

    function_nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "automatic_classification_changed"
        )
    ]

    assert len(field_nodes) == 1
    assert len(function_nodes) == 1

    module = ast.Module(
        body=[
            field_nodes[0],
            function_nodes[0],
        ],
        type_ignores=[],
    )

    ast.fix_missing_locations(
        module
    )

    namespace: dict[str, object] = {
        "Any": Any,
    }

    exec(
        compile(
            module,
            str(RECLASSIFY),
            "exec",
        ),
        namespace,
    )

    fields = namespace[
        "RECLASSIFICATION_FIELDS"
    ]

    detector = namespace[
        "automatic_classification_changed"
    ]

    assert isinstance(
        fields,
        tuple,
    )

    assert all(
        isinstance(
            value,
            str,
        )
        for value in fields
    )

    assert isinstance(
        detector,
        FunctionType,
    )

    return fields, detector


def test_collector_loads_existing_fingerprint_with_auction_query() -> None:
    """Existing fingerprints must arrive in the bulk auction result."""

    source = function_source(
        COLLECTOR,
        "load_auctions",
    )

    assert (
        "c.source_fingerprint "
        "AS collector_source_fingerprint"
        in source
    )

    assert (
        "LEFT JOIN warehouse.auction_collector AS c"
        in source
    )

    assert (
        "c.marketplace = a.marketplace"
        in source
    )

    assert (
        "c.listing_id = a.listing_id"
        in source
    )


def test_collector_build_has_no_per_row_fingerprint_query() -> None:
    """Scanning one auction must not require another fingerprint SELECT."""

    source = function_source(
        COLLECTOR,
        "build_features",
    )

    assert (
        'row.get(\n'
        '                "collector_source_fingerprint"\n'
        "            )"
        in source
    )

    assert (
        "existing_statement"
        not in source
    )

    assert (
        "SELECT source_fingerprint"
        not in source
    )


def test_equal_reclassification_is_not_a_database_change() -> None:
    """An identical deterministic classification must be a no-op."""

    fields, changed = load_change_detector()

    payload = {
        field: (
            False
            if field == "auto_bulk_lot"
            else None
        )
        for field in fields
    }

    payload[
        "auto_importance_score"
    ] = 0

    payload[
        "auto_verdict"
    ] = "PASS"

    row = {
        f"stored_{field}": value
        for field, value in payload.items()
    }

    assert (
        changed(
            row,
            payload,
        )
        is False
    )


def test_one_changed_auto_value_requires_update() -> None:
    """A real automatic-classification difference must still update."""

    fields, changed = load_change_detector()

    payload = {
        field: None
        for field in fields
    }

    payload[
        "auto_bulk_lot"
    ] = False

    payload[
        "auto_importance_score"
    ] = 10

    payload[
        "auto_verdict"
    ] = "PASS"

    row = {
        f"stored_{field}": value
        for field, value in payload.items()
    }

    row[
        "stored_auto_verdict"
    ] = "WATCH"

    assert (
        changed(
            row,
            payload,
        )
        is True
    )


def test_reclassification_selects_stored_auto_values_once() -> None:
    """The source scan must include the current automatic classification."""

    source = function_source(
        RECLASSIFY,
        "main",
    )

    fields, _ = load_change_detector()

    assert (
        "LEFT JOIN warehouse.auction_collector AS c"
        in source
    )

    for field in fields:
        assert (
            f"c.{field} AS stored_{field}"
            in source
        )

    assert (
        ").mappings().all()"
        in source
    )


def test_reclassification_skips_unchanged_rows_before_update() -> None:
    """No-op classifications must never reach the SQL UPDATE."""

    source = function_source(
        RECLASSIFY,
        "main",
    )

    payload_position = source.index(
        "payload = {"
    )

    comparison_position = source.index(
        "if not automatic_classification_changed(",
        payload_position,
    )

    dry_run_position = source.index(
        "if args.dry_run:",
        comparison_position,
    )

    update_position = source.index(
        "connection.execute(\n"
        "                update_sql,",
        dry_run_position,
    )

    assert (
        payload_position
        < comparison_position
        < dry_run_position
        < update_position
    )


def test_reclassification_update_preserves_manual_columns() -> None:
    """The optimized write remains automatic-fields-only."""

    source = function_source(
        RECLASSIFY,
        "main",
    )

    start = source.index(
        "update_sql = text("
    )

    end = source.index(
        "scanned = 0",
        start,
    )

    update_sql = source[
        start:end
    ]

    assert (
        "WHERE marketplace = :marketplace"
        in update_sql
    )

    assert (
        "AND listing_id = :listing_id"
        in update_sql
    )

    assert (
        "updated_at = NOW()"
        in update_sql
    )

    assert (
        "manual_"
        not in update_sql
    )


def test_refresh_order_remains_collector_then_reclassification() -> None:
    """The performance patch must not reorder refresh semantics."""

    source = function_source(
        RUNNER,
        "main",
    )

    collector_position = source.index(
        '"scripts/collector_features.py"'
    )

    reclassify_position = source.index(
        '"scripts/reclassify_collector.py"'
    )

    export_position = source.index(
        '"scripts/inspect_recent_ingestion.py"'
    )

    assert (
        collector_position
        < reclassify_position
        < export_position
    )
