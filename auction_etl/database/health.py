from sqlalchemy import text

from auction_etl.database.session import engine


def database_health() -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
