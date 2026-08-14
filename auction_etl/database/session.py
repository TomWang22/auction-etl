"""Shared SQLAlchemy engine and session factory."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_database_url() -> str:
    """Return the explicit runtime URL or the project-settings fallback."""
    configured_url = os.getenv("DATABASE_URL", "").strip()

    if configured_url:
        if configured_url.startswith("postgresql://"):
            return configured_url.replace(
                "postgresql://",
                "postgresql+psycopg://",
                1,
            )

        return configured_url

    from auction_etl.config.settings import settings

    return (
        "postgresql+psycopg://"
        f"{settings.postgres_user}:"
        f"{settings.postgres_password}@"
        f"{settings.postgres_host}:"
        f"{settings.postgres_port}/"
        f"{settings.postgres_db}"
    )


DATABASE_URL = build_database_url()




def _normalize_database_url(
    value: str,
) -> str:
    """Normalize PostgreSQL URLs for the Psycopg 3 dialect."""
    if value.startswith(
        "postgresql://"
    ):
        return value.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return value


_environment_database_url = os.getenv(
    "DATABASE_URL",
    "",
).strip()

if _environment_database_url:
    DATABASE_URL = _normalize_database_url(
        _environment_database_url
    )


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
