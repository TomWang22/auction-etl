"""Database-identity propagation tests for the refresh runner."""

from __future__ import annotations

from scripts import run_latest_auction_refresh as refresh
from scripts import update_auction_fx as update_fx


def test_child_environment_propagates_validated_database_identity(
    monkeypatch,
) -> None:
    """Child commands receive the identity validated by the parent."""
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "stale_database",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "stale_user",
    )
    monkeypatch.setenv(
        "DOCKER_HOST",
        "unexpected-docker-host",
    )
    monkeypatch.setenv(
        "DOCKER_CONTEXT",
        "unexpected-docker-context",
    )
    monkeypatch.setenv(
        "PGOPTIONS",
        "unexpected-pg-options",
    )

    environment = refresh.build_child_environment(
        database_url=(
            "postgresql+psycopg://"
            "example@example.invalid/neondb"
        ),
        expected_database_name="neondb",
        expected_database_user="neondb_owner",
    )

    assert environment["DATABASE_URL"].endswith(
        "/neondb"
    )
    assert (
        environment["AUCTION_EXPECTED_DATABASE_NAME"]
        == "neondb"
    )
    assert (
        environment["AUCTION_EXPECTED_DATABASE_USER"]
        == "neondb_owner"
    )

    assert "DOCKER_HOST" not in environment
    assert "DOCKER_CONTEXT" not in environment
    assert "PGOPTIONS" not in environment


def test_fx_updater_consumes_propagated_database_identity(
    monkeypatch,
) -> None:
    """The FX child resolves the propagated parent identity."""
    monkeypatch.setenv(
        "DATABASE_URL",
        (
            "postgresql+psycopg://"
            "example@example.invalid/neondb"
        ),
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "neondb",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "neondb_owner",
    )

    arguments = update_fx.parse_arguments([])

    assert arguments.expected_database_name == "neondb"
    assert arguments.expected_database_user == "neondb_owner"
    assert arguments.database_url.endswith(
        "/neondb"
    )


def test_child_environment_overrides_stale_parent_identity(
    monkeypatch,
) -> None:
    """CLI-validated identity wins over inherited stale defaults."""
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "auction_warehouse",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "auction",
    )

    environment = refresh.build_child_environment(
        database_url=(
            "postgresql+psycopg://"
            "example@example.invalid/neondb"
        ),
        expected_database_name="neondb",
        expected_database_user="neondb_owner",
    )

    assert (
        environment["AUCTION_EXPECTED_DATABASE_NAME"]
        == "neondb"
    )
    assert (
        environment["AUCTION_EXPECTED_DATABASE_USER"]
        == "neondb_owner"
    )
