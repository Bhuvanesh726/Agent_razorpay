from pydantic import BaseModel, ConfigDict, computed_field

from app.core.money import paise_to_display


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    brand: str
    category: str
    price_paise: int
    unit: str
    stock: int
    description: str
    tags: list[str]

    @computed_field
    @property
    def price_display(self) -> str:
        return paise_to_display(self.price_paise)


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
