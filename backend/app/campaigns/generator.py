"""Deterministic synthetic order history generator.

Not committed data — every campaign run (or test) calls this fresh, seeded
for reproducibility. Nothing here is real customer data; customer_key/
name/email are deliberately synthetic-looking ("Customer 007",
customer007@example.test), never invented-but-plausible real identities.

Customers are assigned one of five *archetypes* rather than drawn from pure
noise, so the resulting mix reliably produces every segment
segmentation.py looks for (lapsed, repeat, high-value, category-loyal,
one-time) instead of hoping enough variety falls out of randomness:

  - repeat_loyal_recent   : 5-8 orders, mostly one category, recent activity
  - repeat_high_value     : 4-7 orders, biased toward pricier products
  - lapsed                : 2-4 orders, all clustered in the *oldest* part
                            of the window — nothing recent, by construction
  - one_time              : exactly 1 order
  - occasional_low_value  : exactly 2 orders, cheap items — deliberately
                            NOT a repeat customer (repeat needs 3+), a
                            realistic "doesn't fit any interesting segment"
                            control mass
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.campaigns.models import Customer, GenerationMeta, HistoricalOrder, HistoricalOrderItem, ProductView
from app.repositories import product_repo

_WINDOW_DAYS = 180
_INJECTION_SKU = "INJ-001"
# Mirrors settings.campaign_browse_window_days' default (7). Kept as a literal
# rather than imported from settings so this module stays a pure function of
# its own seed + as_of, not of whatever the policy config happens to be today.
_BROWSE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class Archetype:
    name: str
    count: int
    order_count_range: tuple[int, int]
    recent_only: bool = False  # confine every order to the last 30 days
    lapsed_only: bool = False  # confine every order to the oldest 30 days
    category_biased: bool = False  # ~80% of items from one favorite category
    price_biased: bool = False  # prefer pricier products


ARCHETYPES = [
    Archetype("repeat_loyal_recent", count=5, order_count_range=(5, 9), category_biased=True),
    Archetype("repeat_high_value", count=4, order_count_range=(4, 8), price_biased=True),
    Archetype("lapsed", count=4, order_count_range=(2, 4), lapsed_only=True),
    Archetype("one_time", count=4, order_count_range=(1, 1)),
    Archetype("occasional_low_value", count=3, order_count_range=(2, 2)),
]


def _random_order_date(rng: random.Random, as_of: datetime, archetype: Archetype) -> datetime:
    if archetype.lapsed_only:
        days_ago = rng.uniform(_WINDOW_DAYS - 30, _WINDOW_DAYS)
    elif archetype.recent_only:
        days_ago = rng.uniform(0, 30)
    else:
        days_ago = rng.uniform(0, _WINDOW_DAYS)
    return as_of - timedelta(days=days_ago)


def _pick_products(rng: random.Random, catalog: list, archetype: Archetype, favorite_category: str | None) -> list:
    sellable = [p for p in catalog if p.sku != _INJECTION_SKU and p.stock > 0]
    if archetype.price_biased:
        sellable = sorted(sellable, key=lambda p: p.price_paise, reverse=True)[: max(10, len(sellable) // 3)]

    n_items = rng.randint(1, 3)
    chosen = []
    for _ in range(n_items):
        if archetype.category_biased and favorite_category and rng.random() < 0.8:
            pool = [p for p in sellable if p.category == favorite_category] or sellable
        else:
            pool = sellable
        chosen.append(rng.choice(pool))
    return chosen


def _log_views(db: Session, rng: random.Random, customer: Customer, sku: str, *, count: int, as_of: datetime, min_days_ago: float, max_days_ago: float) -> None:
    for _ in range(count):
        days_ago = rng.uniform(min_days_ago, max_days_ago)
        db.add(ProductView(user_id=customer.customer_key, sku=sku, session_id=None, viewed_at=as_of - timedelta(days=days_ago), request_id=None))


def _generate_product_views(
    db: Session, rng: random.Random, customers: list[Customer], catalog: list, as_of: datetime, purchased_by_customer: dict[int, set[str]]
) -> None:
    """Layers realistic browsing behavior on top of the purchase history
    already generated above — deliberately covering every edge case
    segmentation.py needs to distinguish, not just the "obviously qualifies"
    case:

      - genuinely abandoned (3-6 recent views, never bought)   -> qualifies
      - viewed then bought anyway (3+ views, but on a purchased SKU) -> excluded
      - too few views (1-2, below the default threshold of 3)  -> excluded
      - qualifying view *count*, but outside the recency window -> excluded
    """
    all_skus = [p.sku for p in catalog if p.sku != _INJECTION_SKU]
    pool = list(customers)
    rng.shuffle(pool)

    def _unpurchased_sku(customer: Customer) -> str | None:
        purchased = purchased_by_customer.get(customer.id, set())
        candidates = [s for s in all_skus if s not in purchased]
        return rng.choice(candidates) if candidates else None

    idx = 0
    # Genuinely abandoned: recent, repeated, never purchased. More than the
    # minimum needed to clear campaign_min_segment_size's default (5), with
    # margin — a segment that only just clears the floor is a fragile demo.
    for _ in range(7):
        if idx >= len(pool):
            break
        customer = pool[idx]
        idx += 1
        sku = _unpurchased_sku(customer)
        if sku is None:
            continue
        _log_views(db, rng, customer, sku, count=rng.randint(3, 6), as_of=as_of, min_days_ago=0.1, max_days_ago=_BROWSE_WINDOW_DAYS - 0.5)

    # Viewed repeatedly, but bought it anyway — must NOT count as abandoned.
    if idx < len(pool):
        customer = pool[idx]
        idx += 1
        purchased = purchased_by_customer.get(customer.id, set())
        if purchased:
            sku = rng.choice(sorted(purchased))
            _log_views(db, rng, customer, sku, count=rng.randint(3, 5), as_of=as_of, min_days_ago=0.1, max_days_ago=_BROWSE_WINDOW_DAYS - 0.5)

    # Below the view-count threshold — a passing glance, not real intent.
    if idx < len(pool):
        customer = pool[idx]
        idx += 1
        sku = _unpurchased_sku(customer)
        if sku is not None:
            _log_views(db, rng, customer, sku, count=1, as_of=as_of, min_days_ago=0.1, max_days_ago=_BROWSE_WINDOW_DAYS - 0.5)

    # Enough views, but stale — outside the recency window entirely.
    if idx < len(pool):
        customer = pool[idx]
        idx += 1
        sku = _unpurchased_sku(customer)
        if sku is not None:
            _log_views(
                db, rng, customer, sku, count=rng.randint(3, 5), as_of=as_of,
                min_days_ago=_BROWSE_WINDOW_DAYS + 5, max_days_ago=_BROWSE_WINDOW_DAYS + 20,
            )


def generate_history(
    db: Session,
    *,
    seed: int = 42,
    as_of: datetime | None = None,
) -> GenerationMeta:
    """Wipes and regenerates every campaign_* table (except CampaignRun/
    CampaignOffer, which belong to specific past runs, not the customer
    base) — deterministic and idempotent: the same seed always produces the
    same customers, orders, and product views."""
    as_of = (as_of or datetime.now(timezone.utc)).replace(microsecond=0)
    rng = random.Random(seed)

    db.query(ProductView).delete()
    db.query(HistoricalOrderItem).delete()
    db.query(HistoricalOrder).delete()
    db.query(Customer).delete()
    db.query(GenerationMeta).delete()
    db.commit()

    catalog, _ = product_repo.list_products(db, page=1, page_size=1000)
    categories = sorted({p.category for p in catalog if p.sku != _INJECTION_SKU})

    all_customers: list[Customer] = []
    purchased_by_customer: dict[int, set[str]] = {}

    customer_index = 1
    for archetype in ARCHETYPES:
        for _ in range(archetype.count):
            key = f"CUST-{customer_index:03d}"
            customer = Customer(customer_key=key, name=f"Customer {customer_index:03d}", email=f"customer{customer_index:03d}@example.test")
            db.add(customer)
            db.flush()  # need customer.id for the orders below
            all_customers.append(customer)
            purchased_by_customer[customer.id] = set()

            favorite_category = rng.choice(categories) if archetype.category_biased else None
            n_orders = rng.randint(*archetype.order_count_range)
            for _ in range(n_orders):
                placed_at = _random_order_date(rng, as_of, archetype)
                items = _pick_products(rng, catalog, archetype, favorite_category)
                order = HistoricalOrder(customer_id=customer.id, placed_at=placed_at, total_paise=0)
                db.add(order)
                db.flush()

                total = 0
                for product in items:
                    qty = rng.randint(1, 2)
                    db.add(
                        HistoricalOrderItem(
                            order_id=order.id,
                            sku=product.sku,
                            category=product.category,
                            quantity=qty,
                            unit_price_paise=product.price_paise,
                        )
                    )
                    total += product.price_paise * qty
                    purchased_by_customer[customer.id].add(product.sku)
                order.total_paise = total

            customer_index += 1

    _generate_product_views(db, rng, all_customers, catalog, as_of, purchased_by_customer)

    meta = GenerationMeta(seed=seed, as_of=as_of)
    db.add(meta)
    db.commit()
    return meta


def get_generation_meta(db: Session) -> GenerationMeta | None:
    return db.query(GenerationMeta).order_by(GenerationMeta.id.desc()).first()
