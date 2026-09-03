from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.campaigns import service as campaign_service
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, public, requires
from app.database import get_db
from app.schemas.product import CategoryOut, ProductListOut, ProductOut, ProductViewCreate
from app.services import product_service

router = APIRouter(tags=["products"], route_class=SecureAPIRoute)


@router.get("/api/products", response_model=ProductListOut)
@public
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
@public
def get_product(sku: str, db: Session = Depends(get_db)) -> ProductOut:
    return product_service.get_product_by_sku(db, sku)


@router.get("/api/categories", response_model=list[CategoryOut])
@public
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    return product_service.list_categories(db)


@router.post("/api/products/{sku}/view", status_code=204)
@requires(AuthRequirement.BUYER, AuthRequirement.AGENT)
def log_product_view(
    sku: str,
    payload: ProductViewCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Fired by the frontend when a product detail is opened. Cheap and
    best-effort by design (see campaign_service.log_product_view) — this
    endpoint never returns an error the frontend would need to handle,
    so a logging failure can never block or break browsing."""
    request_id = getattr(request.state, "request_id", None)
    campaign_service.log_product_view(db, user_id=principal.user_id, sku=sku, session_id=payload.session_id, request_id=request_id)
    return Response(status_code=204)
