from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories import product_repo
from app.schemas.product import CategoryOut, ProductListOut, ProductOut


def list_products(
    db: Session,
    *,
    category: str | None,
    search: str | None,
    min_price_paise: int | None,
    max_price_paise: int | None,
    page: int,
    page_size: int,
) -> ProductListOut:
    items, total = product_repo.list_products(
        db,
        category=category,
        search=search,
        min_price_paise=min_price_paise,
        max_price_paise=max_price_paise,
        page=page,
        page_size=page_size,
    )
    return ProductListOut(
        items=[ProductOut.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_product_by_sku(db: Session, sku: str) -> ProductOut:
    product = product_repo.get_by_sku(db, sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    return ProductOut.model_validate(product)


def list_categories(db: Session) -> list[CategoryOut]:
    rows = product_repo.list_categories(db)
    return [CategoryOut(category=category, product_count=count) for category, count in rows]
