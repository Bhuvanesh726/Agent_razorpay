"""Password-less sign-in as a pre-seeded buyer or merchant, so a reviewer can
get into the app without registering their own Google OAuth client.

OFF by default. The safety gate is `demo_login_available()`: these principals
are only ever reachable when `APP_ENV=development`. Nothing else can turn it
on — no env var, no header, no request body — exactly the construction
app/testing/chaos.py uses for fault injection, and for the same reason: a
demo affordance that could be flipped on in production by editing config is
a backdoor, not a demo affordance. See tests/test_demo_login_gate.py for the
property this file exists to guarantee.

Production posture is unchanged and Google-only: app/auth/oauth_router.py is
still the only way a human authenticates, and these two rows are inert
outside development because the endpoint that mints tokens for them
(app/auth/demo_login_router.py) 404s.

The seeded buyer is deliberately given *state* — an agent credential, two
past orders in different terminal statuses, and browsing history — because a
reviewer landing on an empty dashboard learns nothing about a system whose
entire subject is what happens after an agent has been spending money for a
while.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger

DEMO_MERCHANT_ID = "user_demo_merchant"


@dataclass(frozen=True)
class DemoPrincipal:
    user_id: str
    email: str
    name: str
    role: str


def demo_buyer() -> DemoPrincipal:
    """id is settings.default_user_id ("user_demo") — the same literal every
    Layer 0-4.6 Cart/Order/AgentSession row already carries, so the demo
    buyer owns that history instead of being a second, parallel user. See
    scripts/seed.py::_seed_demo_user."""
    return DemoPrincipal(
        user_id=settings.default_user_id,
        email="demo-buyer@example.test",
        name="Demo Buyer",
        role="BUYER",
    )


def demo_merchant() -> DemoPrincipal:
    return DemoPrincipal(
        user_id=DEMO_MERCHANT_ID,
        email="demo-merchant@example.test",
        name="Demo Merchant",
        role="MERCHANT",
    )


def demo_principals() -> dict[str, DemoPrincipal]:
    return {"BUYER": demo_buyer(), "MERCHANT": demo_merchant()}


def demo_login_available() -> bool:
    """The whole gate. Deliberately a function of app_env alone."""
    return settings.app_env == "development"


def ensure_demo_environment(db: Session) -> None:
    """Idempotent: safe to call on every seed run and every demo login.

    Callers MUST check `demo_login_available()` first — this function does
    not re-check, so that the gate lives at the two entry points rather than
    being spread across every helper below.
    """
    _ensure_principals(db)
    _ensure_agent_credential(db)
    _ensure_past_orders(db)
    _ensure_browsing_history(db)
    db.commit()


def _ensure_principals(db: Session) -> None:
    from app.models.user import User

    for principal in demo_principals().values():
        existing = db.get(User, principal.user_id)
        if existing is not None:
            # Reset the role rather than leaving it alone. The dev role switch
            # (/api/dev/switch-role) writes a new role straight onto the user
            # row, so a reviewer who clicks "Switch to buyer view" while signed
            # in as the demo merchant would otherwise leave that principal
            # stuck as a BUYER — and "Continue as Demo Merchant" would silently
            # stop reaching the merchant dashboards. These two rows have one
            # canonical role each by definition, so signing in restores it.
            if existing.role != principal.role:
                existing.role = principal.role
            continue
        db.add(
            User(
                id=principal.user_id,
                email=principal.email,
                name=principal.name,
                # Never authenticated with Google, and never will — that is
                # the entire point of this row.
                google_sub=None,
                role=principal.role,
            )
        )
    db.flush()


# Everything the in-app chat agent needs to shop and pay. Excludes
# report_content_gap, which the demand loop writes on its own.
_DEMO_AGENT_SCOPES = [
    "search_products",
    "get_product",
    "present_product",
    "add_to_cart",
    "view_cart",
    "remove_from_cart",
    "initiate_payment",
    "decline_upsell",
]
_DEMO_AGENT_NAME = "Grocery Bot"


def _ensure_agent_credential(db: Session) -> None:
    """EMBEDDED, so the in-app chat can act as it with no raw key anywhere —
    the buyer's own JWT authorizes /api/agents/{id}/chat. An EXTERNAL
    credential would have to hand back a plaintext key, which this function
    has no way to show anyone."""
    from app.auth.security import generate_agent_key, hash_agent_key
    from app.models.agent_credential import AgentCredential

    buyer = demo_buyer()
    existing = (
        db.query(AgentCredential)
        .filter(AgentCredential.owner_user_id == buyer.user_id, AgentCredential.name == _DEMO_AGENT_NAME)
        .first()
    )
    if existing is not None:
        return

    db.add(
        AgentCredential(
            owner_user_id=buyer.user_id,
            name=_DEMO_AGENT_NAME,
            # Generated and immediately discarded: EMBEDDED never returns a
            # plaintext key, so nothing is lost by not keeping it.
            key_hash=hash_agent_key(generate_agent_key()),
            delivery_mode="EMBEDDED",
            scopes=list(_DEMO_AGENT_SCOPES),
            spend_limit_paise=500_000,  # ₹5,000
            status="ACTIVE",
            standing_instruction="Keep the kitchen stocked with staples under ₹500 a week.",
        )
    )
    db.flush()


# (sku, quantity) per seeded order. Two different baskets on purpose: the
# idempotency key is derived from the line items, so identical baskets would
# collide on the UNIQUE constraint and produce one order, not two.
_PAID_BASKET = [("GRO-001", 1), ("GRO-004", 2)]
_FAILED_BASKET = [("GRO-002", 1)]


def _ensure_past_orders(db: Session) -> None:
    """Built through app/orders/service.py rather than by writing rows with
    a final status, so these two orders take the same transitions a real
    purchase takes. If someone breaks the state machine, seeding fails loudly
    here instead of quietly producing history that the machine says is
    impossible.
    """
    from app.models.order import Order
    from app.orders import repository as order_repo
    from app.orders import service as order_service

    buyer = demo_buyer()
    if db.query(Order).filter(Order.user_id == buyer.user_id).first() is not None:
        return

    paid = _build_order(db, basket=_PAID_BASKET, session_id="demo-seed-paid")
    if paid is not None:
        _advance_to_awaiting(db, paid, razorpay_order_id="order_demo_seed_paid")
        order_service.mark_paid(
            db,
            paid,
            # `pay_demo` prefix on purpose: the frontend labels this an
            # unverifiable local capture (see OrderDetailModal.tsx and
            # docs/PAYMENT-REALITY.md). Seeded history must not imply money
            # moved through Razorpay, because none did.
            razorpay_payment_id="pay_demo_seed_captured",
            method="upi",
            raw_response={"seeded": True, "note": "Locally seeded demo order — not a real Razorpay payment."},
        )

    failed = _build_order(db, basket=_FAILED_BASKET, session_id="demo-seed-failed")
    if failed is not None:
        _advance_to_awaiting(db, failed, razorpay_order_id="order_demo_seed_failed")
        order_service.mark_failed(
            db,
            failed,
            error_code="BAD_REQUEST_ERROR",
            error_description="Payment failed because the UPI PIN was entered incorrectly three times.",
            raw_response={"seeded": True},
        )

    # Backdate so the list doesn't read as "everything happened this second".
    now = datetime.now(timezone.utc)
    for order, days in ((paid, 6), (failed, 2)):
        if order is not None:
            order.created_at = now - timedelta(days=days)
            order.updated_at = now - timedelta(days=days)
            order_repo.save(db, order)


def _build_order(db: Session, *, basket: list[tuple[str, int]], session_id: str):
    """Returns None when the catalog hasn't been seeded yet (a bare DB), so
    demo seeding degrades to "no orders" rather than raising."""
    from app.models.cart import Cart, CartItem
    from app.orders import service as order_service
    from app.repositories import product_repo

    buyer = demo_buyer()
    cart = Cart(user_id=buyer.user_id, status="active")
    db.add(cart)
    db.flush()

    for sku, quantity in basket:
        product = product_repo.get_by_sku(db, sku)
        if product is None:
            return None
        db.add(
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=quantity,
                unit_price_paise=product.price_paise,
                user_id=buyer.user_id,
            )
        )
    db.flush()
    db.refresh(cart)

    return order_service.create_or_get_order(
        db, user_id=buyer.user_id, session_id=session_id, cart=cart
    ).order


def _advance_to_awaiting(db: Session, order, *, razorpay_order_id: str) -> None:
    """What order_service.ensure_razorpay_order does, minus the live API call
    — the transition is still asserted by the state machine."""
    from app.orders import repository as order_repo
    from app.orders.state_machine import OrderStatus, require_transition

    require_transition(OrderStatus(order.status), OrderStatus.AWAITING_CONFIRMATION)
    order.status = OrderStatus.AWAITING_CONFIRMATION.value
    order.razorpay_order_id = razorpay_order_id
    order_repo.save(db, order)


# Enough repeat views of one SKU to clear settings.campaign_browse_min_views.
_DEMO_BUYER_VIEWS = [("GRO-003", 4), ("DAI-001", 2)]


def _ensure_browsing_history(db: Session) -> None:
    """Two different producers, because the browse-abandonment segment reads
    only one of them:

    1. Views for the live demo buyer. These prove the real logging path runs,
       but segmentation deliberately ignores them — compute_browse_abandonment_segment
       skips any user_id that isn't a synthetic customer_key (see the comment
       on ProductView in app/campaigns/models.py).
    2. The synthetic customer base, which is what the segment actually
       aggregates. Without it the merchant's browse-abandonment campaign has
       nothing to target and the page reads as broken rather than empty.
    """
    from app.campaigns import generator
    from app.campaigns.models import ProductView
    from app.repositories import product_repo

    buyer = demo_buyer()
    now = datetime.now(timezone.utc)

    if db.query(ProductView).filter(ProductView.user_id == buyer.user_id).first() is None:
        hours = 1
        for sku, count in _DEMO_BUYER_VIEWS:
            if product_repo.get_by_sku(db, sku) is None:
                continue
            for _ in range(count):
                db.add(
                    ProductView(
                        user_id=buyer.user_id,
                        sku=sku,
                        session_id="demo-seed-browse",
                        viewed_at=now - timedelta(hours=hours),
                    )
                )
                hours += 7
        db.flush()

    # generate_history() wipes and rebuilds the whole synthetic customer base,
    # so only run it when there isn't one — re-running would delete customers
    # that existing CampaignOffer rows point at.
    if generator.get_generation_meta(db) is None:
        try:
            generator.generate_history(db, seed=42)
        except Exception as e:  # pragma: no cover - a bare catalog, mainly
            logger.warning("demo seed: synthetic history generation skipped", extra={"error": str(e)})
