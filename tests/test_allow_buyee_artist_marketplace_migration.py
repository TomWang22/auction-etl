"""Regression tests for the Buyee artist-marketplace migration."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


VERSIONS = Path("alembic/versions")

REVISION_ID = "6a8f4d2c9b17"

PRIOR_HEAD = "25b11c0de001"

WRAPPER = (
    VERSIONS
    / "6a8f4d2c9b17_allow_buyee_artist_marketplace.py"
)

UP_SQL = (
    VERSIONS
    / "6a8f4d2c9b17_allow_buyee_artist_marketplace_up.sql"
)

DOWN_SQL = (
    VERSIONS
    / "6a8f4d2c9b17_allow_buyee_artist_marketplace_down.sql"
)

FOUNDATION = (
    VERSIONS
    / "a4d9c2e7f105_account_identity_foundation_up.sql"
)


def _literal_assignment(
    tree: ast.Module,
    name: str,
) -> Any:
    """Return one literal top-level assignment."""

    matches: list[ast.AST] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue

            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        else:
            continue

        if not (
            isinstance(target, ast.Name)
            and target.id == name
        ):
            continue

        if value is not None:
            matches.append(value)

    assert len(matches) == 1

    return ast.literal_eval(
        matches[0]
    )


def _constraint_values(
    source: str,
) -> tuple[str, ...]:
    """Return artist_marketplace_check string values."""

    pattern = re.compile(
        r"""
        CONSTRAINT
        \s+
        artist_marketplace_check
        \s+
        CHECK
        \s*
        \(
            \s*
            marketplace
            \s+
            IN
            \s*
            \(
                (?P<values>[^)]*)
            \)
            \s*
        \)
        """,
        re.IGNORECASE
        | re.DOTALL
        | re.VERBOSE,
    )

    matches = list(
        pattern.finditer(
            source
        )
    )

    assert len(matches) == 1

    return tuple(
        re.findall(
            r"'([^']+)'",
            matches[0].group(
                "values"
            ),
        )
    )


def _revision_graph() -> dict[str, tuple[str, ...]]:
    """Return static Alembic parent relationships."""

    records: dict[
        str,
        tuple[str, ...],
    ] = {}

    for path in sorted(
        VERSIONS.glob("*.py")
    ):
        tree = ast.parse(
            path.read_text(
                encoding="utf-8"
            ),
            filename=str(path),
        )

        try:
            revision = _literal_assignment(
                tree,
                "revision",
            )
            down_revision = _literal_assignment(
                tree,
                "down_revision",
            )
        except (
            AssertionError,
            TypeError,
            ValueError,
        ):
            continue

        if not isinstance(
            revision,
            str,
        ):
            continue

        if down_revision is None:
            parents: tuple[str, ...] = ()
        elif isinstance(
            down_revision,
            str,
        ):
            parents = (
                down_revision,
            )
        elif isinstance(
            down_revision,
            (
                tuple,
                list,
            ),
        ):
            parents = tuple(
                str(value)
                for value in down_revision
            )
        else:
            raise AssertionError(
                "Unsupported down_revision: "
                + repr(
                    down_revision
                )
            )

        records[
            revision
        ] = parents

    return records


def test_revision_extends_confirmed_head() -> None:
    """The migration must follow the previously proven unique head."""

    tree = ast.parse(
        WRAPPER.read_text(
            encoding="utf-8"
        ),
        filename=str(WRAPPER),
    )

    assert (
        _literal_assignment(
            tree,
            "revision",
        )
        == REVISION_ID
    )

    assert (
        _literal_assignment(
            tree,
            "down_revision",
        )
        == PRIOR_HEAD
    )


def test_wrapper_uses_sibling_sql_files() -> None:
    """Upgrade and downgrade must follow the repository SQL-wrapper pattern."""

    source = WRAPPER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(WRAPPER),
    )

    function_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    assert "upgrade" in function_names
    assert "downgrade" in function_names
    assert "_sql" in function_names

    assert (
        "6a8f4d2c9b17_allow_buyee_artist_marketplace_up.sql"
        in source
    )

    assert (
        "6a8f4d2c9b17_allow_buyee_artist_marketplace_down.sql"
        in source
    )

    assert UP_SQL.is_file()
    assert DOWN_SQL.is_file()


def test_upgrade_expands_only_artist_marketplace_constraint() -> None:
    """Upgrade permits all three supported artist marketplaces."""

    source = UP_SQL.read_text(
        encoding="utf-8"
    )

    assert (
        "ALTER TABLE account.artist_marketplace"
        in source
    )

    assert (
        "DROP CONSTRAINT artist_marketplace_check"
        in source
    )

    assert set(
        _constraint_values(
            source
        )
    ) == {
        "ebay",
        "buyee",
        "gripsweat",
    }

    forbidden = (
        "DROP TABLE",
        "DELETE FROM",
        "TRUNCATE",
        "UPDATE account.artist_marketplace",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_downgrade_refuses_to_orphan_buyee_targets() -> None:
    """Downgrade must fail before restoring a constraint that rejects Buyee."""

    source = DOWN_SQL.read_text(
        encoding="utf-8"
    )

    required = (
        "IF EXISTS",
        "FROM account.artist_marketplace",
        "marketplace = 'buyee'",
        "RAISE EXCEPTION",
        "Cannot downgrade artist_marketplace_check",
        "DROP CONSTRAINT artist_marketplace_check",
    )

    for fragment in required:
        assert fragment in source

    assert set(
        _constraint_values(
            source
        )
    ) == {
        "ebay",
        "gripsweat",
    }

    guard_position = source.index(
        "IF EXISTS"
    )

    drop_position = source.index(
        "DROP CONSTRAINT artist_marketplace_check"
    )

    assert guard_position < drop_position


def test_historical_foundation_remains_two_marketplace_history() -> None:
    """The applied historical migration must remain immutable."""

    source = FOUNDATION.read_text(
        encoding="utf-8"
    )

    assert set(
        _constraint_values(
            source
        )
    ) == {
        "ebay",
        "gripsweat",
    }


def test_new_revision_is_unique_alembic_head() -> None:
    """Static revision topology must advance to this migration."""

    records = _revision_graph()

    assert REVISION_ID in records
    assert records[
        REVISION_ID
    ] == (
        PRIOR_HEAD,
    )

    children = {
        revision: set()
        for revision in records
    }

    for revision, parents in records.items():
        for parent in parents:
            assert parent in records

            children[
                parent
            ].add(
                revision
            )

    heads = {
        revision
        for revision, descendants
        in children.items()
        if not descendants
    }

    assert heads == {
        REVISION_ID
    }


def test_migration_triplet_is_complete() -> None:
    """The revision must retain Python, up-SQL, and down-SQL siblings."""

    assert WRAPPER.is_file()
    assert UP_SQL.is_file()
    assert DOWN_SQL.is_file()
