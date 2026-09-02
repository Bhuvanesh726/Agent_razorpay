from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.core.money import paise_to_display


class CartItemCreate(BaseModel):
    sku: str
    quantity: int = 1

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("quantity must be at least 1")
        return v


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price_paise: int

    @computed_field
    @property
    def unit_price_display(self) -> str:
        return paise_to_display(self.unit_price_paise)

    @computed_field
    @property
    def line_total_paise(self) -> int:
        return self.unit_price_paise * self.quantity

    @computed_field
    @property
    def line_total_display(self) -> str:
        return paise_to_display(self.line_total_paise)


class CartOut(BaseModel):
    id: int
    user_id: str
    status: str
    created_at: datetime
    items: list[CartItemOut]

    @computed_field
    @property
    def total_paise(self) -> int:
        return sum(item.unit_price_paise * item.quantity for item in self.items)

    @computed_field
    @property
    def total_display(self) -> str:
        return paise_to_display(self.total_paise)
