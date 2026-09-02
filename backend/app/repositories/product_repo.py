from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.models.product import Product


def get_by_sku(db: Session, sku: str) -> Product | None:
    return db.scalar(select(Product).where(Product.sku == sku))


def get_by_id(db: Session, product_id: int) -> Product | None:
    return db.get(Product, product_id)


def list_products(
    db: Session,
    *,
    category: str | None = None,
    search: str | None = None,
    min_price_paise: int | None = None,
    max_price_paise: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Product], int]:
    stmt = select(Product)

    if category:
        stmt = stmt.where(Product.category == category)
    if min_price_paise is not None:
        stmt = stmt.where(Product.price_paise >= min_price_paise)
    if max_price_paise is not None:
        stmt = stmt.where(Product.price_paise <= max_price_paise)
    if search:
        like = f"%{search.lower()}%"
        # SQLite has no native array containment, so tags are matched by
        # casting the JSON column to text — portable across SQLite/Postgres,
        # if coarser than a real array operator.
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(like),
                func.lower(func.cast(Product.tags, String)).like(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Product.id).offset((page - 1) * page_size).limit(page_size)
    items = list(db.scalars(stmt))
    return items, total


def list_categories(db: Session) -> list[tuple[str, int]]:
    stmt = (
        select(Product.category, func.count(Product.id))
        .group_by(Product.category)
        .order_by(Product.category)
    )
    return list(db.execute(stmt).all())


def upsert(db: Session, data: dict) -> Product:
    product = get_by_sku(db, data["sku"])
    if product is None:
        product = Product(**data)
        db.add(product)
    else:
        for key, value in data.items():
            setattr(product, key, value)
    return product
