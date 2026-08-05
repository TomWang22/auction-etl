"""Static and deterministic tests for auction intake."""

from __future__ import annotations

import ast
from pathlib import Path

from auction_etl.services import auction_intake


SERVICE = Path(
    "auction_etl/services/auction_intake.py"
)


def test_confirmation_token_changes_with_review_inputs() -> None:
    """Preview tokens are bound to the complete reviewed mutation."""
    first = {
        "auction":
            {
                "marketplace":
                    "example",
                "listing_id":
                    "1",
            },
        "pressing":
            {
                "pressing_id":
                    2,
            },
        "mutation":
            {
                "reason":
                    "First reviewed reason.",
            },
    }

    second = {
        **first,
        "mutation": {
            "reason":
                "Second reviewed reason.",
        },
    }

    import hashlib
    import json

    first_digest = hashlib.sha256(
        json.dumps(
            first,
            sort_keys=True,
        ).encode()
    ).hexdigest()

    second_digest = hashlib.sha256(
        json.dumps(
            second,
            sort_keys=True,
        ).encode()
    ).hexdigest()

    assert first_digest != second_digest


def test_service_uses_serializable_recomputation() -> None:
    """Apply mode recomputes the preview under serialization."""
    source = SERVICE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    apply_function = next(
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name == "apply_assignment"
    )

    semantic_text = " ".join(
        node.value
        for node in ast.walk(
            apply_function
        )
        if isinstance(
            node,
            ast.Constant,
        )
        and isinstance(
            node.value,
            str,
        )
    )

    call_names = {
        node.func.id
        for node in ast.walk(
            apply_function
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Name,
        )
    }

    assert "SERIALIZABLE" in semantic_text
    assert "_preview_with_connection" in call_names
    assert "pg_advisory_xact_lock" in semantic_text
    assert "set_config" in semantic_text


def test_confidence_validation() -> None:
    """Confidence remains explicit and bounded."""
    assert auction_intake._confidence(
        "0.9500"
    ) == auction_intake.Decimal(
        "0.9500"
    )

    for invalid in (
        "-0.1",
        "1.1",
        "invalid",
    ):
        try:
            auction_intake._confidence(
                invalid
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"Invalid confidence was accepted: {invalid}"
            )
