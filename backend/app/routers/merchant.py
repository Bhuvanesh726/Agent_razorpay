"""The merchant dashboard — Layer 4.8. Notifications feed (demand-signal
aggregation output), a products table with inline price/discount/stock
actions, and headline numbers. Every endpoint here is MERCHANT-only; see
docs/048-demand-loop.md for why the demand-signal loop (not campaigns,
already merchant-only since Layer 4.6) is the actual point of this layer.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.campaigns import service as campaign_service
from app.core.config import settings
from app.database import get_db
from app.demand import aggregation as demand_aggregation
from app.models.demand_signal import DemandSignal
from app.models.merchant_notification import MerchantNotification
from app.models.product import Product
from app.repositories import product_repo
from app.schemas.merchant import (
    HeadlineNumbersOut,
    NotificationActionRequest,
    NotificationOut,
    ProductRowOut,
    SetDiscountRequest,
    SetPriceRequest,
    ToggleStockResult,
)
from app.services.pricing import effective_price_paise

router = APIRouter(tags=["merchant"], route_class=SecureAPIRoute)
_audit = AuditService()

# A restock quantity is arbitrary by design — "Toggle out-of-stock" is a
# demo-friendly on/off switch, not an inventory-management feature (out of
# this layer's explicit scope; see docs/048-demand-loop.md's "what NOT to
# build"). There's deliberately no separate is_out_of_stock column: Product.stock
# is the one existing source of truth OutOfStockRule/StockRule/the catalog
# feed's availability field all already read.
_RESTOCK_QUANTITY = 20


@router.get("/api/merchant/notifications", response_model=list[NotificationOut])
@requires(AuthRequirement.MERCHANT)
def list_notifications(db: Session = Depends(get_db)) -> list[NotificationOut]:
    demand_aggregation.run(db)  # cheap, deterministic, idempotent — see aggregation.py's module docstring
    rows = db.scalars(
        select(MerchantNotification).order_by(MerchantNotification.created_at.desc())
    ).all()
    out = []
    for n in rows:
        conversions = 0
        purchases = {"count": 0, "revenue_paise": 0}
        if n.status == "ACTED" and n.acted_at is not None:
            conversions = demand_aggregation.conversions_since(
                db, n.evidence.get("category"), n.evidence.get("sku"), n.acted_at
            )
            purchases = demand_aggregation.purchases_since(
                db, n.evidence.get("category"), n.evidence.get("sku"), n.acted_at
            )
        out.append(
            NotificationOut(
                id=n.id,
                created_at=n.created_at,
                type=n.type,
                evidence=n.evidence,
                suggested_action=n.suggested_action,
                status=n.status,
                acted_at=n.acted_at,
                dismissed_at=n.dismissed_at,
                conversions_since_acted=conversions,
                purchases_since_acted=purchases["count"],
                revenue_since_acted_paise=purchases["revenue_paise"],
            )
        )
    return out


@router.post("/api/merchant/notifications/{notification_id}/action", response_model=NotificationOut)
@requires(AuthRequirement.MERCHANT)
def act_on_notification(
    notification_id: int, payload: NotificationActionRequest, db: Session = Depends(get_db)
) -> NotificationOut:
    if payload.status not in ("ACTED", "DISMISSED"):
        raise HTTPException(status_code=422, detail="status must be ACTED or DISMISSED.")
    notification = db.get(MerchantNotification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail=f"No notification '{notification_id}'.")
    now = datetime.now(timezone.utc)
    notification.status = payload.status
    if payload.status == "ACTED":
        notification.acted_at = now
    else:
        notification.dismissed_at = now
    db.commit()
    db.refresh(notification)
    return NotificationOut(
        id=notification.id,
        created_at=notification.created_at,
        type=notification.type,
        evidence=notification.evidence,
        suggested_action=notification.suggested_action,
        status=notification.status,
        acted_at=notification.acted_at,
        dismissed_at=notification.dismissed_at,
        conversions_since_acted=0,
    )


def _product_row(p: Product) -> ProductRowOut:
    return ProductRowOut(
        sku=p.sku,
        name=p.name,
        category=p.category,
        price_paise=p.price_paise,
        discount_pct=p.discount_pct,
        effective_price_paise=effective_price_paise(p),
        stock=p.stock,
        is_out_of_stock=p.stock <= 0,
    )


@router.get("/api/merchant/products", response_model=list[ProductRowOut])
@requires(AuthRequirement.MERCHANT)
def list_products(db: Session = Depends(get_db)) -> list[ProductRowOut]:
    products, _total = product_repo.list_products(db, page=1, page_size=1000)
    return [_product_row(p) for p in products]


def _get_or_404(db: Session, sku: str) -> Product:
    product = product_repo.get_by_sku(db, sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"No product '{sku}'.")
    return product


@router.post("/api/merchant/products/{sku}/price", response_model=ProductRowOut)
@requires(AuthRequirement.MERCHANT)
def set_price(sku: str, payload: SetPriceRequest, db: Session = Depends(get_db)) -> ProductRowOut:
    if payload.price_paise <= 0:
        raise HTTPException(status_code=422, detail="price_paise must be positive.")
    product = _get_or_404(db, sku)
    product.price_paise = payload.price_paise
    db.commit()
    db.refresh(product)
    return _product_row(product)


@router.post("/api/merchant/products/{sku}/discount", response_model=ProductRowOut)
@requires(AuthRequirement.MERCHANT)
def set_discount(sku: str, payload: SetDiscountRequest, db: Session = Depends(get_db)) -> ProductRowOut:
    product = _get_or_404(db, sku)
    pct = payload.discount_pct
    if pct:
        # The same ceiling the campaign system already enforces on any
        # discount (campaign_max_discount_pct) — there is no separate
        # "DiscountCapRule" in the policy engine because setting a
        # merchant-wide markdown is a catalog edit, not a buyer/agent cart
        # action the policy engine ever evaluates. See docs/048-demand-loop.md.
        max_pct = settings.campaign_max_discount_pct * 100
        if pct <= 0 or pct > max_pct:
            raise HTTPException(status_code=422, detail=f"discount_pct must be between 0 and {max_pct:.0f}.")
        product.discount_pct = pct
    else:
        product.discount_pct = None
    db.commit()
    db.refresh(product)
    return _product_row(product)


@router.post("/api/merchant/products/{sku}/toggle-stock", response_model=ToggleStockResult)
@requires(AuthRequirement.MERCHANT)
def toggle_stock(sku: str, db: Session = Depends(get_db)) -> ToggleStockResult:
    product = _get_or_404(db, sku)
    product.stock = 0 if product.stock > 0 else _RESTOCK_QUANTITY
    db.commit()
    db.refresh(product)
    return ToggleStockResult(sku=product.sku, stock=product.stock, is_out_of_stock=product.stock <= 0)


@router.get("/api/merchant/headline", response_model=HeadlineNumbersOut)
@requires(AuthRequirement.MERCHANT)
def headline_numbers(db: Session = Depends(get_db)) -> HeadlineNumbersOut:
    signals = db.scalars(select(DemandSignal)).all()
    total = len(signals)
    matched = sum(1 for s in signals if s.outcome == "MATCHED")
    unmet = sum(1 for s in signals if s.outcome == "NO_MATCH")
    match_rate = (matched / total) if total else 0.0

    upsell_revenue = _audit.get_upsell_revenue_total_paise(db)

    net_margin_impact = 0
    for run in campaign_service.list_campaign_runs(db):
        if run.result_summary:
            net_margin_impact += run.result_summary.get("net_margin_impact_paise", 0)

    return HeadlineNumbersOut(
        queries_received=total,
        match_rate=round(match_rate, 4),
        unmet_demand_count=unmet,
        upsell_revenue_paise=upsell_revenue,
        campaign_net_margin_impact_paise=net_margin_impact,
    )
