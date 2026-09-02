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
    assert {name for name in dir(service) if not name.startswith("_")} == {"log_event", "get_trail"}


def test_sessions_are_isolated_in_the_trail(db_session):
    audit = AuditService()
    audit.log_event(db_session, session_id="s1", user_id="u1", event_type="user_message", actor="user")
    audit.log_event(db_session, session_id="s2", user_id="u1", event_type="user_message", actor="user")

    assert len(audit.get_trail(db_session, "s1")) == 1
    assert len(audit.get_trail(db_session, "s2")) == 1
