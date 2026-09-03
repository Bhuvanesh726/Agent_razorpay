from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    user_id: str
    timestamp: datetime
    event_type: str
    actor: str
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None
    decision: str | None = None
    rule_name: str | None = None
    reason: str | None = None
    model_used: str | None = None
    latency_ms: int | None = None
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_paise: int | None = None
    fallback_used: bool | None = None


class AuditTotalsOut(BaseModel):
    total_model_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_paise: int
    fallback_used_count: int
    upsell_proposed_count: int
    upsell_accepted_count: int
    upsell_declined_count: int
    upsell_blocked_count: int
    upsell_incremental_revenue_paise: int


class AuditTrailOut(BaseModel):
    session_id: str
    events: list[AuditEventOut]
    totals: AuditTotalsOut


class SessionReplayOut(BaseModel):
    session_id: str
    event_count: int
    narrative: list[str]
    final_cart: dict | None
    final_order_status: str | None
