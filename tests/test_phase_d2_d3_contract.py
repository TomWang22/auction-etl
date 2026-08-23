"""Static contract tests for the Phase-D2/D3 local acceptance package."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    """Read one repository source file."""
    return (ROOT / relative).read_text(encoding="utf-8")


def test_d2_revision_chain() -> None:
    """D2 must extend the installed D1 identity foundation."""
    source = read(
        "alembic/versions/"
        "c7f6b1d9e204_account_runtime_scoping.py"
    )
    assert 'revision = "c7f6b1d9e204"' in source
    assert 'down_revision = "a4d9c2e7f105"' in source


def test_d2_preserves_nullable_staged_ownership() -> None:
    """D2 must not prematurely make owner columns non-null."""
    source = read(
        "alembic/versions/"
        "c7f6b1d9e204_account_runtime_scoping_up.sql"
    )
    assert "SET NOT NULL" not in source
    assert "ENABLE ROW LEVEL SECURITY" not in source


def test_refresh_compatibility_indexes_are_account_aware() -> None:
    """Active refresh uniqueness is per account plus one legacy lane."""
    source = read(
        "alembic/versions/"
        "c7f6b1d9e204_account_runtime_scoping_up.sql"
    )
    assert "refresh_job_one_active_per_account_idx" in source
    assert "refresh_job_one_legacy_active_idx" in source
    assert "account_id IS NOT NULL" in source
    assert "account_id IS NULL" in source


def test_collector_metadata_unique_identity_includes_account() -> None:
    """Collector-private metadata supports two accounts on one listing."""
    source = read(
        "alembic/versions/"
        "c7f6b1d9e204_account_runtime_scoping_up.sql"
    )
    assert "auction_collector_account_listing_uidx" in source
    assert "account_id," in source
    assert "marketplace," in source
    assert "listing_id" in source


def test_cross_account_acceptance_is_transactional() -> None:
    """Synthetic A/B acceptance data must be rolled back."""
    source = read(
        "scripts/phase_d_cross_account_acceptance.py"
    )
    assert "transaction.rollback()" in source
    assert '"transaction_committed": False' in source


def test_cross_account_acceptance_rejects_remote_by_default() -> None:
    """The local acceptance tool must refuse managed DB hosts."""
    source = read(
        "scripts/phase_d_cross_account_acceptance.py"
    )
    assert "Refusing non-loopback database host" in source
    assert "--allow-remote" in source


def test_runtime_gate_is_fail_closed() -> None:
    """The runtime source gate must signal a nonzero result on gaps."""
    source = read("scripts/phase_d_runtime_scope_gate.py")
    assert "MIGRATION_GATE_PASS=" in source
    assert "return 0 if not failed else 3" in source

# phase-d2-psycopg-percent-regression:start
def test_d2_sql_uses_sqlalchemy_compilation_for_percent_literals() -> None:
    """Keep PostgreSQL format tokens out of Psycopg placeholder parsing."""
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.dialects import postgresql

    repository = Path(__file__).resolve().parents[1]

    migration_path = (
        repository
        / "alembic"
        / "versions"
        / "c7f6b1d9e204_account_runtime_scoping.py"
    )
    upgrade_path = (
        repository
        / "alembic"
        / "versions"
        / "c7f6b1d9e204_account_runtime_scoping_up.sql"
    )
    downgrade_path = (
        repository
        / "alembic"
        / "versions"
        / "c7f6b1d9e204_account_runtime_scoping_down.sql"
    )

    migration_source = migration_path.read_text(
        encoding="utf-8",
    )

    assert "from sqlalchemy import text" in migration_source
    assert "exec_driver_sql" not in migration_source
    assert migration_source.count(
        "op.get_bind().execute("
    ) == 2

    dialect = postgresql.dialect(
        paramstyle="pyformat",
    )

    saw_postgresql_identifier_format = False

    for sql_path in (
        upgrade_path,
        downgrade_path,
    ):
        sql_source = sql_path.read_text(
            encoding="utf-8",
        )

        if "%I" in sql_source:
            saw_postgresql_identifier_format = True

        compiled = text(sql_source).compile(
            dialect=dialect,
        )

        assert compiled.params == {}

        rendered = str(compiled)

        assert rendered.count("%") == (
            sql_source.count("%") * 2
        )

        if "%I" in sql_source:
            assert "%%I" in rendered

    assert saw_postgresql_identifier_format
# phase-d2-psycopg-percent-regression:end
