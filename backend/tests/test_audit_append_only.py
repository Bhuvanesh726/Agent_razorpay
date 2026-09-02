from app.audit.repository import AuditRepository
from app.audit.service import AuditService


def test_audit_log_grows_and_never_mutates_prior_rows(db_session):
    audit = AuditService()

    first = audit.log_event(
        db_session, session_id="s1", user_id="u1", event_type="user_message", actor="user", reason="hello"
    )
    second = audit.log_event(
        db_session,
        session_id="s1",
        user_id="u1",
        event_type="policy_decision",
        actor="policy",
        decision="ALLOW",
        rule_name="__default__",
        reason="ok",
    )

    trail = audit.get_trail(db_session, "s1")
    assert [e.id for e in trail] == [first.id, second.id]
    assert trail[0].event_type == "user_message"
    assert trail[1].decision == "ALLOW"

    third = audit.log_event(db_session, session_id="s1", user_id="u1", event_type="tool_executed", actor="agent")

    trail_after = audit.get_trail(db_session, "s1")
    assert [e.id for e in trail_after] == [first.id, second.id, third.id]
    # earlier rows are byte-for-byte unchanged by the later write
    assert trail_after[0].reason == "hello"
    assert trail_after[1].decision == "ALLOW"
    assert trail_after[1].rule_name == "__default__"


def test_audit_repository_has_no_update_or_delete():
    repo = AuditRepository()
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")
    assert {name for name in dir(repo) if not name.startswith("_")} == {"create", "list_for_session"}


def test_audit_service_has_no_update_or_delete():
    service = AuditService()
    assert not hasattr(service, "update")
    assert not hasattr(service, "delete")
    assert {name for name in dir(service) if not name.startswith("_")} == {
        "log_event",
        "get_trail",
        "compute_totals",
    }


def test_sessions_are_isolated_in_the_trail(db_session):
    audit = AuditService()
    audit.log_event(db_session, session_id="s1", user_id="u1", event_type="user_message", actor="user")
    audit.log_event(db_session, session_id="s2", user_id="u1", event_type="user_message", actor="user")

    assert len(audit.get_trail(db_session, "s1")) == 1
    assert len(audit.get_trail(db_session, "s2")) == 1


def test_model_call_event_stores_token_usage_and_cost(db_session):
    audit = AuditService()
    event = audit.log_event(
        db_session,
        session_id="s1",
        user_id="u1",
        event_type="model_call",
        actor="agent",
        model_used="nvidia/nemotron-3.5-lightning-30b-a3b",
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        cost_paise=0,
        fallback_used=False,
    )
    assert event.prompt_tokens == 100
    assert event.completion_tokens == 40
    assert event.total_tokens == 140
    assert event.cost_paise == 0
    assert event.fallback_used is False


def test_compute_totals_aggregates_only_model_call_events(db_session):
    audit = AuditService()
    audit.log_event(db_session, session_id="s1", user_id="u1", event_type="user_message", actor="user")
    audit.log_event(
        db_session,
        session_id="s1",
        user_id="u1",
        event_type="model_call",
        actor="agent",
        model_used="primary-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_paise=15,
        fallback_used=False,
    )
    audit.log_event(
        db_session,
        session_id="s1",
        user_id="u1",
        event_type="model_call",
        actor="agent",
        model_used="fallback-model",
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
        cost_paise=28,
        fallback_used=True,
    )
    # non-model-call events must not pollute the totals
    audit.log_event(
        db_session, session_id="s1", user_id="u1", event_type="policy_decision", actor="policy", decision="ALLOW"
    )

    totals = audit.compute_totals(audit.get_trail(db_session, "s1"))
    assert totals == {
        "total_model_calls": 2,
        "total_prompt_tokens": 300,
        "total_completion_tokens": 130,
        "total_tokens": 430,
        "total_cost_paise": 43,
        "fallback_used_count": 1,
    }


def test_compute_totals_on_empty_trail():
    audit = AuditService()
    totals = audit.compute_totals([])
    assert totals == {
        "total_model_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "total_cost_paise": 0,
        "fallback_used_count": 0,
    }
