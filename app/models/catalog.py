"""`vendors` and `products` (spec section 6)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("normalized_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # `casefold()` of the trimmed display name, computed in Python (CIW-03.2).
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("vendor_id", "normalized_sku"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    # `casefold()` of the trimmed SKU; the SKU grammar is ASCII, so 64 still fits.
    normalized_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Integer cents; the grammar allows up to 9 999 999 999.99, beyond 32 bits.
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # At most 9 digits (999 999 999), which fits a 32-bit integer.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Moves on every ORM update; a Core upsert (`ON CONFLICT DO UPDATE`) must set it itself.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
