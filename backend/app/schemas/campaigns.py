from datetime import datetime

from pydantic import BaseModel


class SegmentOut(BaseModel):
    name: str
    description: str
    size: int


class CampaignOfferOut(BaseModel):
    customer_key: str
    group: str  # "treatment" | "control"
    decision: str | None
    rule_name: str | None
    reason: str | None
    discount_pct: float | None
    sku: str | None
    redeemed: bool
    revenue_paise: int
    cogs_paise: int


class CampaignMeasurementOut(BaseModel):
    segment_size: int
    offers_sent: int
    offers_blocked: int
    control_size: int
    redemptions: int
    treatment_revenue_paise: int
    control_revenue_paise: int
    control_conversion_rate: float
    expected_baseline_revenue_paise: int
    incremental_revenue_paise: int
    discount_cost_paise: int
    treatment_cogs_paise: int
    expected_baseline_cogs_paise: int
    net_margin_impact_paise: int


class CampaignProposalOut(BaseModel):
    skus: list[str]
    discount_pct: float
    message: str
    rationale: str


class CampaignSummaryOut(BaseModel):
    campaign_id: str
    segment_name: str
    status: str
    created_at: datetime
    proposal: CampaignProposalOut | None
    measurement: CampaignMeasurementOut | None


class CampaignDetailOut(CampaignSummaryOut):
    offers: list[CampaignOfferOut]


class ContentGapOut(BaseModel):
    sku: str
    count: int
    sample_questions: list[str]
