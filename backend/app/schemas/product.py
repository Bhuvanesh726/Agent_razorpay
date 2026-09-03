from pydantic import BaseModel, ConfigDict, computed_field

from app.core.money import paise_to_display


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    brand: str
    category: str
    # Always the list price — unaffected by discount_pct. What a buyer
    # actually pays is effective_price_paise below; see app/services/pricing.py.
    price_paise: int
    # None = no active discount. Set/cleared via the merchant dashboard,
    # bounded by campaign_max_discount_pct — see app/routers/merchant.py.
    discount_pct: float | None = None
    unit: str
    stock: int
    description: str
    tags: list[str]

    @computed_field
    @property
    def price_display(self) -> str:
        return paise_to_display(self.price_paise)

    @computed_field
    @property
    def effective_price_paise(self) -> int:
        if not self.discount_pct:
            return self.price_paise
        return round(self.price_paise * (1 - self.discount_pct / 100))

    @computed_field
    @property
    def effective_price_display(self) -> str:
        return paise_to_display(self.effective_price_paise)


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class CategoryOut(BaseModel):
    category: str
    product_count: int


class ProductViewCreate(BaseModel):
    session_id: str | None = None
