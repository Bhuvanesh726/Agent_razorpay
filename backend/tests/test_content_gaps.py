"""report_content_gap (app/agent/tools.py) and its merchant-side
aggregation (AuditService.get_content_gaps) — reuses the existing
audit_events table entirely, no new table."""

from app.agent.tools import report_content_gap
from app.audit.service import AuditService

_audit = AuditService()


def test_report_content_gap_logs_an_audit_event(db_session):
    result = report_content_gap(db_session, "user_demo", "sess-1", sku="PET-001", question="Is this grain-free?")
    assert result == {"logged": True}

    trail = _audit.get_trail(db_session, "sess-1")
    assert len(trail) == 1
    assert trail[0].event_type == "content_gap_reported"
    assert trail[0].tool_args == {"sku": "PET-001", "question": "Is this grain-free?"}


def test_content_gaps_are_aggregated_by_sku_across_sessions(db_session):
    report_content_gap(db_session, "user_demo", "sess-1", sku="PET-001", question="Is this grain-free?")
    report_content_gap(db_session, "user_demo", "sess-2", sku="PET-001", question="How many calories per cup?")
    report_content_gap(db_session, "user_demo", "sess-3", sku="ELE-004", question="Is it waterproof?")

    gaps = _audit.get_content_gaps(db_session)

    by_sku = {g["sku"]: g for g in gaps}
    assert by_sku["PET-001"]["count"] == 2
    assert "Is this grain-free?" in by_sku["PET-001"]["sample_questions"]
    assert by_sku["ELE-004"]["count"] == 1
    # sorted by count descending
    assert gaps[0]["sku"] == "PET-001"
