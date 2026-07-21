from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from auction_etl.database.base import Base


class CrawlJob(Base):
    __tablename__ = "crawl_job"
    __table_args__ = {"schema": "system"}

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(32), default="running")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
