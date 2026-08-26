"""Tests for Buyee detail-crawler database identity safety."""

from __future__ import annotations

import pytest

from scripts.crawl_buyee_live_details import (
    DEFAULT_EXPECTED_DATABASE_NAME,
    DEFAULT_EXPECTED_DATABASE_USER,
    expected_database_identity,
)


def test_expected_database_identity_uses_repository_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve safe local defaults when no deployment identity is supplied."""
    monkeypatch.delenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        raising=False,
    )
    monkeypatch.delenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        raising=False,
    )

    assert expected_database_identity() == (
        DEFAULT_EXPECTED_DATABASE_NAME,
        DEFAULT_EXPECTED_DATABASE_USER,
    )


def test_expected_database_identity_accepts_railway_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the same production identity contract as the refresh runner."""
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "neondb",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "neondb_owner",
    )

    assert expected_database_identity() == (
        "neondb",
        "neondb_owner",
    )


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        (
            "AUCTION_EXPECTED_DATABASE_NAME",
            "   ",
        ),
        (
            "AUCTION_EXPECTED_DATABASE_USER",
            "",
        ),
    ),
)
def test_expected_database_identity_rejects_blank_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    """Never silently disable the database write guard."""
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_NAME",
        "neondb",
    )
    monkeypatch.setenv(
        "AUCTION_EXPECTED_DATABASE_USER",
        "neondb_owner",
    )
    monkeypatch.setenv(
        variable,
        value,
    )

    with pytest.raises(
        RuntimeError,
        match=variable,
    ):
        expected_database_identity()


def test_detail_crawler_has_no_stale_database_name_constant() -> None:
    """Prevent the retired auction_warehouse-only guard from returning."""
    import scripts.crawl_buyee_live_details as module

    assert not hasattr(
        module,
        "DATABASE_NAME",
    )
