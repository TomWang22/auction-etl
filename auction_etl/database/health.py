from sqlalchemy import text

from auction_etl.database.session import engine


def database_health() -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def list_schemas() -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT schema_name
                FROM information_schema.schemata
                ORDER BY schema_name
                """
            )
        )

        return [row[0] for row in rows]
