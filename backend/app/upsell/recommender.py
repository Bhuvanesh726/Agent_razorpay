"""Deterministic upsell candidate selection.

Deliberately not LLM-driven: the model decides *whether* to mention an
offer (via system prompt guidance) and relays *what* the user says about
it, but never decides *what* to offer. A model choosing the SKU would be
one more surface for a hallucinated or manipulated recommendation (see
Layer 3's injection defense) — grounding the pick in a static, auditable
table removes that risk entirely and keeps the choice testable.

Two tiers, tried in order:
1. FREQUENTLY_PAIRED — specific SKU -> SKU pairs that make obvious sense
   together (dog food -> dog treats, a charger -> a cable).
2. COMPLEMENTARY_CATEGORY — a fallback category -> category mapping,
   picking the cheapest in-stock item in the target category. Used when
   the most recently added item has no specific pairing.

Both always exclude INJ-001 (the seeded prompt-injection product) and
anything already in the cart or already declined this session.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.product import Product
from app.repositories import product_repo

_INJECTION_SKU = "INJ-001"

FREQUENTLY_PAIRED: dict[str, str] = {
    "PET-001": "PET-004",  # dog food -> dog treats
    "PET-002": "PET-004",  # puppy food -> dog treats
    "PET-003": "PET-005",  # cat food -> cat wet food
    "ICE-001": "CHO-002",  # ice cream -> dark chocolate
    "DAI-001": "BIS-005",  # milk -> biscuits
    "GRO-007": "DAI-001",  # coffee -> milk
    "ELE-002": "ELE-001",  # charging adapter -> cable
    "ELE-005": "ELE-001",  # power bank -> cable
}

COMPLEMENTARY_CATEGORY: dict[str, str] = {
    "groceries": "cool_drinks",
    "dairy": "biscuits",
    "biscuits": "cool_drinks",
    "cool_drinks": "biscuits",
    "ice_creams": "chocolates",
    "chocolates": "cool_drinks",
    "electronics": "electronics",
    "pet_supplies": "pet_supplies",
}


@dataclass(frozen=True)
class UpsellCandidate:
    product: Product
    reason: str  # human-readable pairing rationale, goes in the audit trail


def recommend(db: Session, cart_items: list, excluded_skus: frozenset[str]) -> UpsellCandidate | None:
    """cart_items: the current Cart's CartItem list (ORM objects with .product)."""
    excluded = excluded_skus | {_INJECTION_SKU} | {item.product.sku for item in cart_items}

    # Tier 1: specific pairing, preferring the most recently added item.
    for item in reversed(cart_items):
        target_sku = FREQUENTLY_PAIRED.get(item.product.sku)
        if target_sku is None or target_sku in excluded:
            continue
        product = product_repo.get_by_sku(db, target_sku)
        if product is not None and product.stock > 0:
            return UpsellCandidate(product=product, reason=f"frequently paired with {item.product.sku}")

    # Tier 2: complementary category of the most recently added item.
    if not cart_items:
        return None
    last_category = cart_items[-1].product.category
    target_category = COMPLEMENTARY_CATEGORY.get(last_category)
    if target_category is None:
        return None

    candidates, _ = product_repo.list_products(db, category=target_category, page=1, page_size=50)
    candidates = [p for p in candidates if p.sku not in excluded and p.stock > 0]
    if not candidates:
        return None
    cheapest = min(candidates, key=lambda p: p.price_paise)
    return UpsellCandidate(product=cheapest, reason=f"complementary category '{target_category}'")
