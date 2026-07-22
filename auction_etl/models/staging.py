from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from auction_etl.database.base import Base


class Listing(Base):
    __tablename__ = "listing"
    __table_args__ = {"schema": "staging"}

    id: Mapped[int] = mapped_column(primary_key=True)

    raw_page_id: Mapped[int] = mapped_column(
        ForeignKey("raw.page.id", ondelete="CASCADE"),
        nullable=False,
    )

    marketplace: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    listing_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    auction_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(Text)

    subtitle: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)

    sold_text: Mapped[str | None] = mapped_column(Text)

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    sale_type: Mapped[str | None] = mapped_column(
        String(32)
    )

    price_text: Mapped[str | None] = mapped_column(Text)

    final_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )

    currency: Mapped[str | None] = mapped_column(
        String(8)
    )

    bid_text: Mapped[str | None] = mapped_column(Text)

    bid_count: Mapped[int | None] = mapped_column(
        Integer
    )

    shipping_text: Mapped[str | None] = mapped_column(Text)

    shipping_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )

    location: Mapped[str | None] = mapped_column(Text)

    seller: Mapped[str | None] = mapped_column(
        String(128)
    )

    seller_feedback: Mapped[str | None] = mapped_column(
        String(64)
    )

    image_url: Mapped[str | None] = mapped_column(Text)

    condition_text: Mapped[str | None] = mapped_column(
        String(128)
    )

    media_condition: Mapped[str | None] = mapped_column(
        String(64)
    )

    sleeve_condition: Mapped[str | None] = mapped_column(
        String(64)
    )

    obi: Mapped[bool | None] = mapped_column(
        Boolean
    )

    label: Mapped[str | None] = mapped_column(
        String(255)
    )

    catalog_number: Mapped[str | None] = mapped_column(
        String(128)
    )

    country: Mapped[str | None] = mapped_column(
        String(128)
    )

    format: Mapped[str | None] = mapped_column(
        String(128)
    )

    edition: Mapped[str | None] = mapped_column(
        String(128)
    )

    year: Mapped[int | None] = mapped_column(
        Integer
    )

    payload: Mapped[dict | None] = mapped_column(
        JSON
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
