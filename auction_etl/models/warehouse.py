from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from auction_etl.database.base import Base


class Auction(Base):
    __tablename__ = "auction"
    __table_args__ = {"schema": "warehouse"}

    id: Mapped[int] = mapped_column(primary_key=True)

    marketplace: Mapped[str] = mapped_column(String(32))

    listing_id: Mapped[str] = mapped_column(String(128))

    auction_url: Mapped[str] = mapped_column(Text)

    seller: Mapped[str | None] = mapped_column(String(128))

    artist: Mapped[str | None] = mapped_column(String(255))

    title: Mapped[str] = mapped_column(Text)

    media_type: Mapped[str | None] = mapped_column(String(64))

    edition: Mapped[str | None] = mapped_column(String(64))

    catalog_number: Mapped[str | None] = mapped_column(String(128))

    condition_media: Mapped[str | None] = mapped_column(String(64))

    condition_cover: Mapped[str | None] = mapped_column(String(64))

    bulk_lot: Mapped[bool] = mapped_column(Boolean, default=False)

    bid_count: Mapped[int | None]

    watch_count: Mapped[int | None]

    start_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    final_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    shipping_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    currency: Mapped[str | None] = mapped_column(String(8))

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
