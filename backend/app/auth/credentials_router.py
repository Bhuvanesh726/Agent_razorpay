"""Agent credential lifecycle — BUYER-only (an agent can't mint another
agent, and this project scopes merchant tooling to campaigns/audit, not a
buyer's personal shopping agents). See docs/047-principals.md for the two
delivery modes this router implements identically except for one response
field.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent import harness
from app.audit.service import AuditService
from app.auth.context import reset_current_principal, set_current_principal
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.auth.security import generate_agent_key, hash_agent_key
from app.core.config import settings
from app.database import get_db
from app.models.agent_credential import AgentCredential
from app.schemas.agents import (
    AgentActionOut,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentDetailOut,
    AgentRunResult,
    AgentSummaryOut,
)

router = APIRouter(tags=["agents"], route_class=SecureAPIRoute)
_audit = AuditService()


def _get_owned_credential(db: Session, credential_id: str, principal: Principal) -> AgentCredential:
    cred = db.get(AgentCredential, credential_id)
    if cred is None or cred.owner_user_id != principal.user_id:
        # Same 404 either way — a buyer probing another buyer's credential
        # id learns nothing about whether it exists.
        raise HTTPException(status_code=404, detail=f"No agent credential '{credential_id}'.")
    return cred


def _to_summary(cred: AgentCredential) -> AgentSummaryOut:
    return AgentSummaryOut(
        id=cred.id,
        name=cred.name,
        delivery_mode=cred.delivery_mode,
        scopes=cred.scopes,
        spend_limit_paise=cred.spend_limit_paise,
        spent_paise=cred.spent_paise,
        status=cred.status,
        standing_instruction=cred.standing_instruction,
        created_at=cred.created_at,
        last_used_at=cred.last_used_at,
        revoked_at=cred.revoked_at,
    )


@router.post("/api/agents", response_model=AgentCreateResponse)
@requires(AuthRequirement.BUYER)
def create_agent(
    payload: AgentCreateRequest, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AgentCreateResponse:
    invalid_scopes = set(payload.scopes) - set(settings.agent_available_scope_list)
    if invalid_scopes:
        raise HTTPException(status_code=422, detail=f"Unknown scope(s): {sorted(invalid_scopes)}")
    if not payload.scopes:
        raise HTTPException(status_code=422, detail="At least one scope is required.")

    raw_key = generate_agent_key()
    cred = AgentCredential(
        owner_user_id=principal.user_id,
        name=payload.name,
        key_hash=hash_agent_key(raw_key),
        delivery_mode=payload.delivery_mode,
        scopes=payload.scopes,
        spend_limit_paise=payload.spend_limit_paise,
        standing_instruction=payload.standing_instruction,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)

    summary = _to_summary(cred)
    # The plaintext exists only in this one local variable, in this one
    # response, for EXTERNAL mode only — never stored (only key_hash is),
    # never logged, never returned by any other endpoint. EMBEDDED mode
    # never puts it in a response at all — see docs/047-principals.md.
    key = raw_key if cred.delivery_mode == "EXTERNAL" else None
    return AgentCreateResponse(**summary.model_dump(), key=key)


@router.get("/api/agents", response_model=list[AgentSummaryOut])
@requires(AuthRequirement.BUYER)
def list_agents(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> list[AgentSummaryOut]:
    creds = (
        db.query(AgentCredential)
        .filter(AgentCredential.owner_user_id == principal.user_id)
        .order_by(AgentCredential.created_at.desc())
        .all()
    )
    return [_to_summary(c) for c in creds]


@router.get("/api/agents/{credential_id}", response_model=AgentDetailOut)
@requires(AuthRequirement.BUYER)
def get_agent(
    credential_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AgentDetailOut:
    cred = _get_owned_credential(db, credential_id, principal)
    actions = _audit.get_agent_actions(db, cred.id)
    return AgentDetailOut(
        **_to_summary(cred).model_dump(),
        recent_actions=[
            AgentActionOut(
                timestamp=e.timestamp,
                session_id=e.session_id,
                event_type=e.event_type,
                tool_name=e.tool_name,
                decision=e.decision,
                rule_name=e.rule_name,
                reason=e.reason,
            )
            for e in actions
        ],
    )


@router.post("/api/agents/{credential_id}/revoke", response_model=AgentSummaryOut)
@requires(AuthRequirement.BUYER)
def revoke_agent(
    credential_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AgentSummaryOut:
    cred = _get_owned_credential(db, credential_id, principal)
    if cred.status != "REVOKED":
        cred.status = "REVOKED"
        cred.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(cred)
    return _to_summary(cred)


@router.post("/api/agents/{credential_id}/run", response_model=AgentRunResult)
@requires(AuthRequirement.BUYER)
def run_agent(
    credential_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AgentRunResult:
    """EMBEDDED mode's "grant, run, observe, revoke" loop — the buyer never
    presents a key here at all (they're already authenticated as the
    credential's owner via their own JWT), which is exactly why an
    embedded key never needs to exist in plaintext anywhere past the
    moment it was hashed at creation. This endpoint constructs the AGENT
    Principal directly from the credential row and pushes it into the same
    contextvar app/auth/routing.py uses (see app/auth/context.py) for the
    one call into the harness, then restores whatever was there —
    everything downstream (policy evaluation, audit tagging) is identical
    to an EXTERNAL agent's own authenticated HTTP call.
    """
    cred = _get_owned_credential(db, credential_id, principal)
    if cred.status == "REVOKED":
        raise HTTPException(status_code=403, detail="This credential has been revoked.")
    if not cred.standing_instruction:
        raise HTTPException(status_code=422, detail="This agent has no standing instruction to run.")

    # _resolve_from_agent_key stamps this for a real X-Agent-Key HTTP call —
    # this path never calls it (there's no key to present), so it has to be
    # set here instead, or "last active" would show "never" forever for an
    # embedded agent that's only ever run from this button.
    cred.last_used_at = datetime.now(timezone.utc)
    db.commit()

    agent_principal = Principal(
        type="agent",
        user_id=cred.owner_user_id,
        credential_id=cred.id,
        credential_status=cred.status,
        scopes=frozenset(cred.scopes or []),
        spend_limit_paise=cred.spend_limit_paise,
        spent_paise=cred.spent_paise,
    )
    token = set_current_principal(agent_principal)
    try:
        session_id = f"agent-run-{uuid.uuid4().hex[:8]}"
        result = harness.handle_chat(
            db, session_id, cred.owner_user_id, cred.standing_instruction, cred.spend_limit_paise, None
        )
    finally:
        reset_current_principal(token)

    return AgentRunResult(reply=result.reply, status=result.status, cart=result.cart)
