from sqlalchemy import text

from auction_etl.database.session import engine

SCHEMAS = (
    "raw",
    "staging",
    "warehouse",
    "analytics",
    "system",
)


def bootstrap_database() -> None:
    with engine.begin() as conn:
        for schema in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
