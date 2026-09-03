"""Deterministic — no LLM anywhere in this file (the one LLM step is
app/demand/capture.py's extraction; everything from here on is plain
Python, same discipline as app/campaigns/segmentation.py). Reads
DemandSignal rows (and, for browse abandonment, the existing ProductView
table from Layer 4.6b) and turns them into MerchantNotification rows once a
threshold is crossed — never re-raising the same one twice (dedupe_key is
UNIQUE), and never carrying a raw_query or a session/buyer identity into a
notification's evidence. See docs/048-demand-loop.md and
tests/test_demand_privacy.py, which enforces the privacy claim directly
rather than by convention.

`run()` is safe to call on every merchant dashboard load — it's cheap
(no LLM, a handful of GROUP BYs) and idempotent (an existing dedupe_key is
left untouched, not recreated), so there's no separate scheduler to run or
forget to run — the same "no scheduler needed" shape as the embedded
agent's "Run now" button in Layer 4.7.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.campaigns.models import ProductView
from app.core.config import settings
from app.models.agent_session import AgentSession
from app.models.cart import Cart, CartItem
from app.models.demand_signal import DemandSignal
from app.models.merchant_notification import MerchantNotification
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.orders.state_machine import OrderStatus


def crosses_threshold(count: int, active_buyers: int) -> bool:
    required = max(
        settings.demand_notification_threshold_floor,
        active_buyers * settings.demand_notification_threshold_pct,
    )
    return count >= required


def count_active_buyers(db: Session) -> int:
    """Real BUYER-role Users who have chatted with the agent at least once —
    the denominator every percentage threshold above is computed against."""
    stmt = (
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(AgentSession, AgentSession.user_id == User.id)
        .where(User.role == "BUYER")
    )
    return db.scalar(stmt) or 0


def _upsert(db: Session, *, type_: str, dedupe_key: str, evidence: dict, suggested_action: str) -> None:
    """Never recreates a notification that already exists for this
    dedupe_key, whatever its status — a merchant's ACTED/DISMISSED decision
    on one sticks. An existing NEW one has its evidence refreshed (counts
    move as more signals come in); an ACTED/DISMISSED one is left alone."""
    existing = db.scalar(select(MerchantNotification).where(MerchantNotification.dedupe_key == dedupe_key))
    if existing is not None:
        if existing.status == "NEW":
            existing.evidence = evidence
        return
    db.add(
        MerchantNotification(
            type=type_,
            dedupe_key=dedupe_key,
            evidence=evidence,
            suggested_action=suggested_action,
        )
    )


def _raise_unmet_demand(db: Session, active_buyers: int) -> None:
    rows = db.execute(
        select(DemandSignal.category, DemandSignal.session_id).where(
            DemandSignal.outcome == "NO_MATCH", DemandSignal.category.is_not(None)
        )
    ).all()
    sessions_by_category: dict[str, set[str]] = defaultdict(set)
    for category, session_id in rows:
        sessions_by_category[category].add(session_id)

    for category, sessions in sessions_by_category.items():
        count = len(sessions)
        if not crosses_threshold(count, active_buyers):
            continue
        _upsert(
            db,
            type_="UNMET_DEMAND",
            dedupe_key=f"UNMET_DEMAND:{category}",
            evidence={"category": category, "distinct_buyers": count, "active_buyers": active_buyers},
            suggested_action=f"{count} buyer(s) asked for '{category}' and nothing in your catalog matched — "
            "consider adding a product in this category.",
        )


def _raise_out_of_stock_demand(db: Session, active_buyers: int) -> None:
    rows = db.execute(
        select(DemandSignal.matched_sku, DemandSignal.session_id).where(
            DemandSignal.outcome == "OUT_OF_STOCK", DemandSignal.matched_sku.is_not(None)
        )
    ).all()
    sessions_by_sku: dict[str, set[str]] = defaultdict(set)
    for sku, session_id in rows:
        sessions_by_sku[sku].add(session_id)

    for sku, sessions in sessions_by_sku.items():
        count = len(sessions)
        if not crosses_threshold(count, active_buyers):
            continue
        product = db.scalar(select(Product).where(Product.sku == sku))
        name = product.name if product is not None else sku
        _upsert(
            db,
            type_="OUT_OF_STOCK_DEMAND",
            dedupe_key=f"OUT_OF_STOCK_DEMAND:{sku}",
            evidence={"sku": sku, "product_name": name, "distinct_buyers": count, "active_buyers": active_buyers},
            suggested_action=f"{count} buyer(s) tried to buy '{name}' ({sku}) while it was out of stock — "
            "consider restocking it.",
        )


def _raise_attribute_gaps(db: Session, active_buyers: int) -> None:
    """Which SPECIFIC attribute keeps blocking a match, within a category
    that already has unmet demand — derived purely from the attribute KEYS
    already collected in extracted_attributes, never a new product schema
    field. A category with 5 NO_MATCH signals where 4 of them all named
    "max_sugar_g" points at a much more actionable gap than the category
    number alone does."""
    rows = db.execute(
        select(DemandSignal.category, DemandSignal.session_id, DemandSignal.extracted_attributes).where(
            DemandSignal.outcome == "NO_MATCH", DemandSignal.category.is_not(None)
        )
    ).all()
    sessions_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    sample_values: dict[tuple[str, str], list] = defaultdict(list)
    for category, session_id, attributes in rows:
        for key, value in (attributes or {}).items():
            sessions_by_key[(category, key)].add(session_id)
            if len(sample_values[(category, key)]) < 5:
                sample_values[(category, key)].append(value)

    for (category, attribute), sessions in sessions_by_key.items():
        count = len(sessions)
        if not crosses_threshold(count, active_buyers):
            continue
        _upsert(
            db,
            type_="ATTRIBUTE_GAP",
            dedupe_key=f"ATTRIBUTE_GAP:{category}:{attribute}",
            evidence={
                "category": category,
                "attribute": attribute,
                "distinct_buyers": count,
                "active_buyers": active_buyers,
                "sample_values": sample_values[(category, attribute)],
            },
            suggested_action=f"{count} buyer(s) in '{category}' asked for a specific '{attribute}' constraint "
            "your stocked items don't meet — consider stocking something that does.",
        )


def _raise_browse_abandonment(db: Session, active_buyers: int) -> None:
    """Reuses the Layer 4.6b ProductView table (populated by real buyer
    product-detail opens, not just the campaign system's synthetic
    backtest data — see app/campaigns/models.py::ProductView's docstring),
    scoped here to real Users only. Unlike app/campaigns/segmentation.py's
    version (per-customer, feeds a campaign), this is per-SKU: how many
    *distinct real buyers* each repeatedly viewed it — a documented
    simplification skips excluding buyers who went on to purchase it,
    since correctly doing so needs a live-order join this layer's time
    budget didn't include; see docs/048-demand-loop.md."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.campaign_browse_window_days)
    real_user_ids = set(db.scalars(select(User.id)))

    rows = db.execute(
        select(ProductView.user_id, ProductView.sku).where(ProductView.viewed_at >= cutoff)
    ).all()
    view_counts: Counter[tuple[str, str]] = Counter()
    for user_id, sku in rows:
        if user_id in real_user_ids:
            view_counts[(user_id, sku)] += 1

    abandoners_by_sku: dict[str, set[str]] = defaultdict(set)
    for (user_id, sku), count in view_counts.items():
        if count >= settings.campaign_browse_min_views:
            abandoners_by_sku[sku].add(user_id)

    for sku, buyers in abandoners_by_sku.items():
        count = len(buyers)
        if not crosses_threshold(count, active_buyers):
            continue
        product = db.scalar(select(Product).where(Product.sku == sku))
        name = product.name if product is not None else sku
        _upsert(
            db,
            type_="BROWSE_ABANDONMENT",
            dedupe_key=f"BROWSE_ABANDONMENT:{sku}",
            evidence={"sku": sku, "product_name": name, "distinct_buyers": count, "active_buyers": active_buyers},
            suggested_action=f"{count} buyer(s) viewed '{name}' ({sku}) {settings.campaign_browse_min_views}+ times "
            f"in the last {settings.campaign_browse_window_days} days without buying — consider a small discount.",
        )


def run(db: Session) -> None:
    active_buyers = count_active_buyers(db)
    _raise_unmet_demand(db, active_buyers)
    _raise_out_of_stock_demand(db, active_buyers)
    _raise_attribute_gaps(db, active_buyers)
    _raise_browse_abandonment(db, active_buyers)
    db.commit()


def conversions_since(db: Session, category: str | None, sku: str | None, since: datetime) -> int:
    """For "close the loop": how many DemandSignal rows matching this
    notification's category/sku have MATCHED since the merchant acted on
    it. Computed at read time from the same DemandSignal rows everything
    else here reads — no separate tracking table."""
    stmt = select(func.count()).select_from(DemandSignal).where(
        DemandSignal.outcome == "MATCHED", DemandSignal.timestamp >= since
    )
    if sku is not None:
        stmt = stmt.where(DemandSignal.matched_sku == sku)
    elif category is not None:
        stmt = stmt.where(DemandSignal.category == category)
    else:
        return 0
    return db.scalar(stmt) or 0


def purchases_since(db: Session, category: str | None, sku: str | None, since: datetime) -> dict:
    """Same "close the loop" idea as conversions_since, but grounded in
    actual paid orders and revenue rather than a search-match signal — this
    is the number that answers "did acting on this notification actually
    sell anything," not just "did a search find something." Revenue counts
    only the matching line items within an order, never the whole order
    total, so an order that also contains unrelated products doesn't
    overstate this one notification's impact."""
    stmt = (
        select(Order.id, CartItem.quantity, CartItem.unit_price_paise)
        .select_from(Order)
        .join(Cart, Cart.id == Order.cart_id)
        .join(CartItem, CartItem.cart_id == Cart.id)
        .join(Product, Product.id == CartItem.product_id)
        .where(Order.status == OrderStatus.PAID.value, Order.updated_at >= since)
    )
    if sku is not None:
        stmt = stmt.where(Product.sku == sku)
    elif category is not None:
        stmt = stmt.where(Product.category == category)
    else:
        return {"count": 0, "revenue_paise": 0}

    rows = db.execute(stmt).all()
    order_ids = {order_id for order_id, _, _ in rows}
    revenue_paise = sum(qty * price for _, qty, price in rows)
    return {"count": len(order_ids), "revenue_paise": revenue_paise}
