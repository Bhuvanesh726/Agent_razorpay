from sqlalchemy.orm import Session

from app.audit.repository import AuditRepository
from app.models.audit_event import AuditEvent

_repo = AuditRepository()


class AuditService:
    """Every write commits immediately, independent of whatever the caller
    does next — an audit row must survive even if the rest of the request
    later fails or rolls back."""

    def log_event(
        self,
        db: Session,
        *,
        session_id: str,
        user_id: str,
        event_type: str,
        actor: str,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_result: dict | None = None,
        decision: str | None = None,
        rule_name: str | None = None,
        reason: str | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_paise: int | None = None,
        fallback_used: bool | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            actor=actor,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            decision=decision,
            rule_name=rule_name,
            reason=reason,
            model_used=model_used,
            latency_ms=latency_ms,
            request_id=request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_paise=cost_paise,
            fallback_used=fallback_used,
        )
        _repo.create(db, event)
        db.commit()
        db.refresh(event)
        return event

    def get_trail(self, db: Session, session_id: str) -> list[AuditEvent]:
        return _repo.list_for_session(db, session_id)

    def get_content_gaps(self, db: Session, *, sample_size: int = 3) -> list[dict]:
        """Aggregates every content_gap_reported event (see
        app/agent/tools.py::report_content_gap) by SKU — "N users asked
        about X on this SKU; your description doesn't cover it," per the
        merchant view. Grouped here rather than in SQL: this table's write
        volume in a demo project never justifies a GROUP BY, and keeping
        the aggregation in Python keeps the append-only repository's read
        surface to a single, generic "everything of this event_type" query."""
        events = _repo.list_by_event_type(db, "content_gap_reported")
        by_sku: dict[str, list[str]] = {}
        for e in events:
            sku = (e.tool_args or {}).get("sku") or e.tool_name or "unknown"
            question = (e.tool_args or {}).get("question") or e.reason or ""
            by_sku.setdefault(sku, []).append(question)
        return [
            {"sku": sku, "count": len(questions), "sample_questions": questions[:sample_size]}
            for sku, questions in sorted(by_sku.items(), key=lambda kv: len(kv[1]), reverse=True)
        ]

    def compute_totals(self, events: list[AuditEvent]) -> dict:
        """Pure aggregation over an already-fetched trail — no DB access."""
        model_calls = [e for e in events if e.event_type == "model_call"]
        upsell_accepted = [e for e in events if e.event_type == "upsell_accepted"]
        incremental_revenue_paise = sum(
            (e.tool_args or {}).get("price_paise", 0) * (e.tool_args or {}).get("quantity", 1) for e in upsell_accepted
        )
        return {
            "total_model_calls": len(model_calls),
            "total_prompt_tokens": sum(e.prompt_tokens or 0 for e in model_calls),
            "total_completion_tokens": sum(e.completion_tokens or 0 for e in model_calls),
            "total_tokens": sum(e.total_tokens or 0 for e in model_calls),
            "total_cost_paise": sum(e.cost_paise or 0 for e in model_calls),
            "fallback_used_count": sum(1 for e in model_calls if e.fallback_used),
            "upsell_proposed_count": sum(1 for e in events if e.event_type == "upsell_proposed"),
            "upsell_accepted_count": len(upsell_accepted),
            "upsell_declined_count": sum(1 for e in events if e.event_type == "upsell_declined"),
            "upsell_blocked_count": sum(1 for e in events if e.event_type == "upsell_blocked"),
            "upsell_incremental_revenue_paise": incremental_revenue_paise,
        }
