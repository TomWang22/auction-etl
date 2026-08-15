"""Regression tests for conflict-safe Gripsweat probe imports."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

import pytest


ROOT = Path(__file__).resolve().parents[1]
IMPORTER = (
    ROOT
    / "scripts"
    / "import_gripsweat_probe.py"
)


def load_importer() -> ModuleType:
    """Load the importer without executing its main entrypoint."""

    spec = importlib.util.spec_from_file_location(
        "gripsweat_probe_import_test_target",
        IMPORTER,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


class ScalarResult:
    """Minimal SQLAlchemy-result stand-in."""

    def __init__(
        self,
        value: int | None,
    ) -> None:
        self.value = value

    def scalar_one_or_none(
        self,
    ) -> int | None:
        return self.value


class ScalarCollection:
    """Minimal scalar collection stand-in."""

    def __init__(
        self,
        values: list[int],
    ) -> None:
        self.values = values

    def all(
        self,
    ) -> list[int]:
        return list(
            self.values
        )


class CollectionResult:
    """Minimal result exposing scalars()."""

    def __init__(
        self,
        values: list[int],
    ) -> None:
        self.values = values

    def scalars(
        self,
    ) -> ScalarCollection:
        return ScalarCollection(
            self.values
        )


class FakeConnection:
    """Execute one deterministic importer write flow."""

    def __init__(
        self,
        module: ModuleType,
        *,
        inserted_id: int | None,
        matching_ids: list[int],
    ) -> None:
        self.module = module
        self.inserted_id = inserted_id
        self.matching_ids = matching_ids
        self.updated_sale_id: int | None = None
        self.savepoint_count = 0

    @contextmanager
    def begin_nested(
        self,
    ) -> Iterator[None]:
        self.savepoint_count += 1
        yield

    def execute(
        self,
        statement: Any,
        parameters: dict[str, Any],
    ) -> Any:
        if statement is self.module.SALE_INSERT:
            return ScalarResult(
                self.inserted_id
            )

        if statement is self.module.SALE_IDENTITY_MATCH:
            return CollectionResult(
                self.matching_ids
            )

        if statement is self.module.SALE_UPDATE:
            self.updated_sale_id = int(
                parameters[
                    "sale_id"
                ]
            )

            return object()

        raise AssertionError(
            f"Unexpected statement: {statement}"
        )


@pytest.fixture
def parameters() -> dict[str, Any]:
    """Return representative sale bind values."""

    return {
        "source_id":
            1,
        "source_name":
            "teresa-teng",
        "configured_artist":
            "Teresa Teng",
        "source_query":
            "teresa teng",
        "page_number":
            1,
        "source_position":
            1,
        "gripsweat_item_key":
            "current-slug",
        "gripsweat_url":
            "https://gripsweat.com/item/123/current-slug",
        "title":
            None,
        "sold_price":
            None,
        "currency":
            "USD",
        "sold_at":
            None,
        "sold_at_text":
            None,
        "image_url":
            None,
        "original_marketplace":
            None,
        "original_listing_id":
            None,
        "raw_text":
            "example",
    }


def test_insert_path_uses_one_savepoint(
    parameters: dict[str, Any],
) -> None:
    """A new row inserts without an identity lookup."""

    module = load_importer()

    connection = FakeConnection(
        module,
        inserted_id=91,
        matching_ids=[],
    )

    result = module.write_sale(
        connection,
        parameters,
    )

    assert result == "inserted"
    assert connection.savepoint_count == 1
    assert connection.updated_sale_id is None


def test_existing_url_or_key_updates_one_row(
    parameters: dict[str, Any],
) -> None:
    """Any unique identity may resolve the existing sale."""

    module = load_importer()

    connection = FakeConnection(
        module,
        inserted_id=None,
        matching_ids=[42],
    )

    result = module.write_sale(
        connection,
        parameters,
    )

    assert result == "updated"
    assert connection.savepoint_count == 1
    assert connection.updated_sale_id == 42


def test_conflicting_identities_are_not_merged(
    parameters: dict[str, Any],
) -> None:
    """Two distinct identity rows require manual reconciliation."""

    module = load_importer()

    connection = FakeConnection(
        module,
        inserted_id=None,
        matching_ids=[
            42,
            84,
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="different existing rows",
    ):
        module.write_sale(
            connection,
            parameters,
        )

    assert connection.savepoint_count == 1
    assert connection.updated_sale_id is None


def test_importer_source_preserves_transaction_isolation() -> None:
    """The production source keeps both conflict and savepoint guards."""

    source = IMPORTER.read_text(
        encoding="utf-8",
    )

    required = (
        "ON CONFLICT DO NOTHING",
        "connection.begin_nested()",
        "gripsweat_url = :gripsweat_url",
        "source_name = :source_name",
        "gripsweat_item_key = :gripsweat_item_key",
        "original_marketplace = :original_marketplace",
        "original_listing_id = :original_listing_id",
    )

    for contract in required:
        assert contract in source

    assert (
        "ON CONFLICT (source_name, gripsweat_item_key)"
        not in source
    )

def test_identity_lookup_avoids_untyped_null_parameter_guards() -> None:
    """Prevent psycopg from inferring a type for a NULL-only bind usage."""

    source = IMPORTER.read_text(
        encoding="utf-8",
    )

    assert (
        ":original_marketplace IS NOT NULL"
        not in source
    )

    assert (
        ":original_listing_id IS NOT NULL"
        not in source
    )

    assert (
        "original_marketplace = :original_marketplace"
        in source
    )

    assert (
        "original_listing_id = :original_listing_id"
        in source
    )
