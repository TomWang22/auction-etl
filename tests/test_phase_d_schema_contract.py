"""Phase-D schema contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = (
    ROOT
    / "alembic"
    / "versions"
    / "a4d9c2e7f105_account_identity_foundation_up.sql"
)


def test_required_tenancy_tables_exist_in_d1() -> None:
    sql = UP.read_text(encoding="utf-8")
    for relation in (
        "identity.app_user",
        "identity.account",
        "identity.account_member",
        "account.auction_listing",
        "account.tracked_artist",
        "account.artist_marketplace",
        "account.marketplace_connection",
    ):
        assert relation in sql


def test_refresh_ownership_is_additive_nullable_in_d1() -> None:
    sql = UP.read_text(encoding="utf-8")
    assert "account_id uuid NULL" in sql
    assert "requested_by_user_id uuid NULL" in sql


def test_marketplace_connection_is_not_a_password_vault() -> None:
    sql = UP.read_text(encoding="utf-8").casefold()
    section = sql.split(
        "create table account.marketplace_connection",
        1,
    )[1].split(");", 1)[0]
    assert "password" not in section
    assert "credential_reference" in section
    assert "profile_reference" in section
