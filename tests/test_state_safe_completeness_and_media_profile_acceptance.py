"""Tests for state-safe browser acceptance."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(
    "scripts/accept_state_safe_completeness_and_profiles.py"
)


def _module():
    """Load the acceptance module."""
    specification = (
        importlib.util.spec_from_file_location(
            "state_safe_sidebar_acceptance",
            SCRIPT,
        )
    )

    assert specification is not None
    assert specification.loader is not None

    module = importlib.util.module_from_spec(
        specification
    )

    sys.modules[
        specification.name
    ] = module

    specification.loader.exec_module(
        module
    )

    return module


def _function(
    name: str,
) -> ast.FunctionDef:
    """Return one top-level function from the acceptance script."""
    tree = ast.parse(
        SCRIPT.read_text(
            encoding="utf-8"
        )
    )

    function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == name
        ),
        None,
    )

    assert function is not None

    return function


def test_navigation_uses_sidebar_clicks_not_deep_link_goto() -> None:
    """Page navigation uses Streamlit's SPA sidebar."""
    function = _function(
        "open_sidebar_page"
    )

    attribute_calls = {
        node.func.attr
        for node in ast.walk(
            function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
    }

    assert "click" in attribute_calls
    assert "goto" not in attribute_calls


def test_root_navigation_precedes_error_listeners() -> None:
    """Initial application hydration is outside page diagnostics."""
    function = _function(
        "main"
    )

    goto_calls = [
        node
        for node in ast.walk(
            function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and node.func.attr == "goto"
    ]

    listener_calls = [
        node
        for node in ast.walk(
            function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and node.func.attr == "on"
    ]

    assert len(
        goto_calls
    ) == 1

    assert listener_calls

    assert int(
        goto_calls[0].lineno
    ) < min(
        int(
            call.lineno
        )
        for call in listener_calls
    )


def test_route_relative_streamlit_internal_404_is_blocking() -> None:
    """Nested _stcore failures cannot be suppressed."""
    module = _module()

    event = {
        "status":
            404,
        "url":
            (
                "http://127.0.0.1:8501/"
                "Listing_Completeness_Review/"
                "_stcore/health"
            ),
        "method":
            "GET",
        "resource_type":
            "fetch",
    }

    assert not module._is_optional_http_error(
        event
    )


def test_known_optional_assets_remain_non_blocking() -> None:
    """Only optional static assets receive narrow exceptions."""
    module = _module()

    favicon = {
        "status":
            404,
        "url":
            "http://127.0.0.1:8501/favicon.ico",
        "method":
            "GET",
        "resource_type":
            "image",
    }

    source_map = {
        "status":
            404,
        "url":
            "http://127.0.0.1:8501/static/app.js.map",
        "method":
            "GET",
        "resource_type":
            "other",
    }

    script = {
        "status":
            404,
        "url":
            "http://127.0.0.1:8501/static/app.js",
        "method":
            "GET",
        "resource_type":
            "script",
    }

    assert module._is_optional_http_error(
        favicon
    )

    assert module._is_optional_http_error(
        source_map
    )

    assert not module._is_optional_http_error(
        script
    )


def test_acceptance_never_clicks_persistence_controls() -> None:
    """Navigation clicks cannot become data mutations."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "Listing Completeness Review",
        "Media Profile Administration",
        "Streamlit sidebar SPA link",
        "persistence_controls_clicked",
        "database_writes",
    )

    for fragment in required:
        assert fragment in source

    forbidden = (
        "Apply reviewed media profile",
        "Apply reviewed reference",
        "Save changed comparable decisions",
    )

    for fragment in forbidden:
        assert fragment not in source
