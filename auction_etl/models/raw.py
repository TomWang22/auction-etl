from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from auction_etl.database.base import Base


class RawPage(Base):
    __tablename__ = "page"
    __table_args__ = {"schema": "raw"}

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[str] = mapped_column(String(32))

    url: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    sha256: Mapped[str] = mapped_column(String(64))

    http_status: Mapped[int] = mapped_column(Integer)

    html: Mapped[str] = mapped_column(Text)

    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
