from datetime import datetime

from pydantic import BaseModel


class ConversationSummaryOut(BaseModel):
    session_id: str
    # Null until the first user message has been titled. The frontend shows a
    # placeholder rather than an empty row.
    title: str | None
    message_count: int
    last_active_at: datetime | None
    created_at: datetime
    archived: bool
    status: str


class ConversationMessageOut(BaseModel):
    seq: int
    role: str
    content: str | None
    tool_name: str | None


class ConversationDetailOut(BaseModel):
    session_id: str
    title: str | None
    archived: bool
    status: str
    messages: list[ConversationMessageOut]
