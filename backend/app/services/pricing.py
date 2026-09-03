"""Single place "what a buyer actually pays" is computed from a product's
list price and its optional merchant-set discount (Product.discount_pct —
see app/routers/merchant.py's discount-setting endpoint). Every price a
buyer sees or is charged — the catalog feed, the shop UI, an agent tool
result, cart snapshot pricing, policy evaluation — goes through this
function, so a discount is never cosmetic in only one of those places.
"""

from app.models.product import Product


def effective_price_paise(product: Product) -> int:
    if not product.discount_pct:
        return product.price_paise
    return round(product.price_paise * (1 - product.discount_pct / 100))
