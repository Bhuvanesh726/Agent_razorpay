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
    decision: str | None = None
    rule_name: str | None = None
    reason: str | None = None
    model_used: str | None = None
    latency_ms: int | None = None
    request_id: str | None = None
