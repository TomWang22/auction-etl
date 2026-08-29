"""Regression contract for Buyee owner runtime-profile isolation."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OWNER = (
    REPOSITORY_ROOT
    / "scripts"
    / "run_buyee_owner.py"
)


def owner_tree() -> ast.Module:
    """Parse the production owner source."""

    return ast.parse(
        OWNER.read_text(
            encoding="utf-8",
        ),
        filename=str(OWNER),
    )


def calls_named(
    tree: ast.AST,
    name: str,
) -> list[ast.Call]:
    """Return calls whose function name matches exactly."""

    return [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
        and node.func.id == name
    ]


def attribute_calls_named(
    tree: ast.AST,
    name: str,
) -> list[ast.Call]:
    """Return method calls whose attribute matches exactly."""

    return [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and node.func.attr == name
    ]


def references_name(
    node: ast.AST,
    name: str,
) -> bool:
    """Return whether an expression references a named variable."""

    return any(
        isinstance(
            child,
            ast.Name,
        )
        and child.id == name
        for child in ast.walk(node)
    )


def test_owner_uses_fresh_runtime_chromium_profile() -> None:
    """Never launch Chromium against the durable authentication profile."""

    tree = owner_tree()

    launch_calls = attribute_calls_named(
        tree,
        "launch_persistent_context",
    )

    assert len(launch_calls) == 1

    launch = launch_calls[0]

    user_data_keywords = [
        keyword
        for keyword in launch.keywords
        if keyword.arg == "user_data_dir"
    ]

    assert len(user_data_keywords) == 1

    user_data_value = user_data_keywords[0].value

    assert references_name(
        user_data_value,
        "runtime_profile_dir",
    )

    assert not references_name(
        user_data_value,
        "profile_dir",
    )

    runtime_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.Assign,
        )
        and any(
            isinstance(
                target,
                ast.Name,
            )
            and target.id == "runtime_profile_dir"
            for target in node.targets
        )
    ]

    assert len(runtime_assignments) == 1

    runtime_assignment = runtime_assignments[0]

    assert any(
        isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and isinstance(
            node.func.value,
            ast.Name,
        )
        and node.func.value.id == "tempfile"
        and node.func.attr == "mkdtemp"
        for node in ast.walk(
            runtime_assignment.value
        )
    )


def test_owner_still_seeds_from_durable_auth_profile() -> None:
    """Keep the saved Playwright state anchored to the durable profile."""

    tree = owner_tree()

    seed_calls = calls_named(
        tree,
        "seed_authenticated_storage_state",
    )

    runtime_calls = [
        call
        for call in seed_calls
        if len(call.args) >= 2
        and isinstance(
            call.args[0],
            ast.Name,
        )
        and call.args[0].id == "context"
    ]

    assert len(runtime_calls) == 1

    call = runtime_calls[0]

    assert isinstance(
        call.args[1],
        ast.Name,
    )

    assert (
        call.args[1].id
        == "profile_dir"
    )

    source = OWNER.read_text(
        encoding="utf-8",
    )

    assert (
        "BUYEE_OWNER_RUNTIME_PROFILE="
        in source
    )

def test_owner_uses_proven_authenticated_user_agent() -> None:
    """Use the browser fingerprint proven to authenticate Buyee."""

    tree = owner_tree()

    launch_calls = attribute_calls_named(
        tree,
        "launch_persistent_context",
    )

    assert len(launch_calls) == 1

    launch = launch_calls[0]

    user_agent_keywords = [
        keyword
        for keyword in launch.keywords
        if keyword.arg == "user_agent"
    ]

    assert len(user_agent_keywords) == 1

    value = user_agent_keywords[0].value

    assert isinstance(
        value,
        ast.Constant,
    )

    assert isinstance(
        value.value,
        str,
    )

    assert value.value == 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
