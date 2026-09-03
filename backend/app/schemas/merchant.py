from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    created_at: datetime
    type: str
    evidence: dict
    suggested_action: str
    status: str
    acted_at: datetime | None
    dismissed_at: datetime | None
    # Computed at read time from DemandSignal, not stored — see
    # app/demand/aggregation.py::conversions_since. 0 for a NEW/DISMISSED
    # notification (nothing to measure yet). A search-match signal, not a
    # sale — see purchases_since_acted below for the real number.
    conversions_since_acted: int = 0
    # Computed at read time from actual PAID orders — see
    # app/demand/aggregation.py::purchases_since. This is the number that
    # answers "did this actually sell anything," in real revenue.
    purchases_since_acted: int = 0
    revenue_since_acted_paise: int = 0


class NotificationActionRequest(BaseModel):
    status: str  # "ACTED" | "DISMISSED"


class ProductRowOut(BaseModel):
    sku: str
    name: str
    category: str
    price_paise: int
    discount_pct: float | None
    effective_price_paise: int
    stock: int
    is_out_of_stock: bool


class SetPriceRequest(BaseModel):
    price_paise: int


class SetDiscountRequest(BaseModel):
    # None/0 clears the discount.
    discount_pct: float | None


class ToggleStockResult(BaseModel):
    sku: str
    stock: int
    is_out_of_stock: bool


class HeadlineNumbersOut(BaseModel):
    queries_received: int
    match_rate: float  # MATCHED / (MATCHED + NO_MATCH + OUT_OF_STOCK + BLOCKED_BY_POLICY)
    unmet_demand_count: int  # distinct NO_MATCH demand signals
    upsell_revenue_paise: int
    campaign_net_margin_impact_paise: int
