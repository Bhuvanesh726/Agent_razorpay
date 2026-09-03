from pydantic import BaseModel


class CatalogFeedItemOut(BaseModel):
    """Field names chosen to align with the closest real convention for each
    concern — see docs/045-catalog.md for the full rationale:
      - id/title/description/category/availability: ACP's product-feed spec
        (OpenAI/Stripe), the field names most likely to be already familiar
        to a consuming agent.
      - price_paise as an integer minor unit, not ACP's decimal string:
        matches UCP's convention and this API's own existing price_paise
        field everywhere else — an agent should never have to parse a
        currency string to get an exact amount.
      - sku, stock, unit: no equivalent in any of ACP/AP2/x402; kept because
        they're genuinely useful to a budget-constrained buyer and this
        store already has them. sku is the actual database key; id is set
        equal to it for a consumer expecting the ACP field name.
    """

    id: str
    sku: str
    title: str
    description: str
    brand: str
    category: str
    # What a buyer actually pays right now — already reflects any active
    # discount (see app/services/pricing.py). original_price_paise/
    # discount_pct are only present when a discount is active, so an
    # external agent has the numbers to display "was/now" without having
    # to compute anything itself.
    price_paise: int
    original_price_paise: int | None = None
    discount_pct: float | None = None
    currency: str
    unit: str
    availability: str  # "in_stock" | "out_of_stock" — the two ACP values that actually apply to this catalog
    stock: int
    tags: list[str]
    updated_at: str


class CatalogFeedOut(BaseModel):
    merchant: str
    currency: str
    page: int
    page_size: int
    total: int
    items: list[CatalogFeedItemOut]
