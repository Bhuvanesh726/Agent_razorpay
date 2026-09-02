from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.product import CategoryOut, ProductListOut, ProductOut
from app.services import product_service

router = APIRouter(tags=["products"])


@router.get("/api/products", response_model=ProductListOut)
def list_products(
    category: str | None = None,
    search: str | None = None,
    min_price_paise: int | None = Query(default=None, ge=0),
    max_price_paise: int | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProductListOut:
    return product_service.list_products(
        db,
        category=category,
        search=search,
        min_price_paise=min_price_paise,
        max_price_paise=max_price_paise,
        page=page,
        page_size=page_size,
    )


@router.get("/api/products/{sku}", response_model=ProductOut)
def get_product(sku: str, db: Session = Depends(get_db)) -> ProductOut:
    return product_service.get_product_by_sku(db, sku)


@router.get("/api/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    return product_service.list_categories(db)
