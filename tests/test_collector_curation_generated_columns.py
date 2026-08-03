"""Generated-column regression tests for collector behavior."""

from __future__ import annotations

import ast
import inspect
import textwrap

from auction_etl.services.collector_curation import (
    save_behavior,
)


GENERATED_COLUMN = (
    "closing_window_escalation_ratio"
)


def behavior_write_sql() -> str:
    """Extract the behavior upsert SQL."""
    source = textwrap.dedent(
        inspect.getsource(
            save_behavior
        )
    )
    tree = ast.parse(source)

    matches = [
        node.value
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "INSERT INTO" in node.value
            and "auction_behavior_observation"
            in node.value
        )
    ]

    assert len(matches) == 1
    return matches[0]


def test_generated_ratio_is_not_a_write_target() -> None:
    """PostgreSQL must calculate the escalation ratio."""
    sql = behavior_write_sql()
    upper_sql = sql.upper()

    values_index = upper_sql.index(
        "VALUES"
    )
    conflict_index = upper_sql.index(
        "ON CONFLICT"
    )
    update_index = upper_sql.index(
        "DO UPDATE SET"
    )

    returning_index = upper_sql.find(
        "RETURNING",
        update_index,
    )

    if returning_index == -1:
        returning_index = len(sql)

    insert_columns = sql[:values_index]
    values_clause = sql[
        values_index:conflict_index
    ]
    update_clause = sql[
        update_index:returning_index
    ]

    assert (
        GENERATED_COLUMN
        not in insert_columns
    )

    assert (
        GENERATED_COLUMN
        not in values_clause
    )

    assert (
        GENERATED_COLUMN
        not in update_clause
    )

    assert "closing_window_start_price" in sql
    assert "closing_window_final_price" in sql
