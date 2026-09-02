from sqlalchemy import JSON, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.database import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (Index("ix_products_category", "category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(60), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Catalog isn't per-user yet, but every table carries user_id from day one
    # so Google OAuth (later layer) needs zero schema changes.
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default=settings.default_user_id)
