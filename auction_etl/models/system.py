from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from auction_etl.database.base import Base


class Source(Base):
    __tablename__ = "source"
    __table_args__ = {"schema": "system"}

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(String(255))
