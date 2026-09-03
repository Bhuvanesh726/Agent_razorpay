"""Orchestrates one campaign run end to end: segment -> control/treatment
split -> LLM proposal -> per-customer policy gate -> simulated redemption
-> measurement -> audit trail. This is the one place every other campaign
module meets; none of the others import each other directly.

Audit events are logged to the SAME AuditService/audit_events table the
shopping agent uses, with campaign_id standing in for session_id — the
existing GET /api/audit/{session_id} endpoint and audit viewer UI work for
a campaign's trail with zero changes, for free.
"""

import random
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.campaigns import segmentation
from app.campaigns.agent import CampaignProposal, CampaignProposalError, propose_campaign
from app.campaigns.engine import default_campaign_policy_engine
from app.campaigns.generator import get_generation_meta
from app.campaigns.models import CampaignOffer, CampaignRun, ProductView
from app.campaigns.simulation import CampaignMeasurement, measure_campaign, simulate_offer_outcome
from app.campaigns.types import Decision, FeaturedProductSnapshot, ProposedOfferState
from app.core.config import settings
from app.core.logging import logger
from app.repositories import product_repo

_audit = AuditService()
_CAMPAIGN_USER_ID = "campaign_system"
_INJECTION_SKU = "INJ-001"


def log_product_view(db: Session, *, user_id: str, sku: str, session_id: str | None, request_id: str | None) -> None:
    """Best-effort, cheap by design — called on every product-detail-open
    from the products router. Must never raise: a failed view log is not
    allowed to break browsing or block a page render, per the spec this
    endpoint exists for. No validation that sku exists in the catalog
    either — that read would cost more than the write itself; an invalid
    sku just never matches anything meaningful in segmentation later."""
    try:
        db.add(ProductView(user_id=user_id, sku=sku, session_id=session_id, request_id=request_id))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("failed to log product view", extra={"user_id": user_id, "sku": sku, "error": str(e)})


class CampaignError(Exception):
    pass


@dataclass
class CampaignResult:
    campaign_id: str
    segment_name: str
    status: str  # "completed" | "blocked_at_segment"
    proposal: CampaignProposal | None
    measurement: CampaignMeasurement | None
    reason: str | None = None


def _recent_offer_counts(db: Session, customer_ids: list[int], as_of: datetime, window_days: int) -> dict[int, int]:
    if not customer_ids:
        return {}
    cutoff = as_of - timedelta(days=window_days)
    rows = (
        db.query(CampaignOffer.customer_id)
        .join(CampaignRun, CampaignRun.campaign_id == CampaignOffer.campaign_id)
        .filter(
            CampaignOffer.customer_id.in_(customer_ids),
            CampaignOffer.decision == Decision.ALLOW.value,
            CampaignRun.created_at >= cutoff,
        )
        .all()
    )
    counts: dict[int, int] = {cid: 0 for cid in customer_ids}
    for (cid,) in rows:
        counts[cid] = counts.get(cid, 0) + 1
    return counts


def list_campaign_runs(db: Session) -> list[CampaignRun]:
    return db.query(CampaignRun).order_by(CampaignRun.created_at.desc()).all()


def get_campaign_run(db: Session, campaign_id: str) -> CampaignRun | None:
    return db.query(CampaignRun).filter(CampaignRun.campaign_id == campaign_id).first()


def get_campaign_offers(db: Session, campaign_id: str) -> list[tuple[CampaignOffer, str]]:
    """Returns (offer, customer_key) pairs — the merchant view always wants
    to show who was targeted, not just an internal customer_id."""
    from app.campaigns.models import Customer

    rows = (
        db.query(CampaignOffer, Customer.customer_key)
        .join(Customer, Customer.id == CampaignOffer.customer_id)
        .filter(CampaignOffer.campaign_id == campaign_id)
        .order_by(CampaignOffer.id)
        .all()
    )
    return [(offer, key) for offer, key in rows]


def _member_featured_products(member, shared_featured: tuple, catalog_by_sku: dict) -> tuple:
    """member.target_sku is only ever set for browse_abandonment members
    (see segmentation.py) — everyone else falls through to the campaign's
    shared featured-product list. One helper, called from both the
    treatment and control loops, is what lets a single run_campaign() body
    handle both "one offer for the whole segment" and "one personalized
    offer per customer" without a second pipeline."""
    if member.target_sku is not None:
        product = catalog_by_sku.get(member.target_sku)
        if product is not None:
            return (FeaturedProductSnapshot(sku=product.sku, price_paise=product.price_paise, cost_paise=product.cost_paise),)
    return shared_featured


def run_campaign(db: Session, segment_key: str, *, seed: int = 7, campaign_id: str | None = None) -> CampaignResult:
    meta = get_generation_meta(db)
    if meta is None:
        raise CampaignError("No synthetic history has been generated yet — call generate_history() first.")

    segments = segmentation.compute_segments(
        db,
        meta.as_of,
        lapsed_days=settings.campaign_lapsed_days,
        repeat_min_orders=settings.campaign_repeat_min_orders,
        high_value_threshold_paise=settings.campaign_high_value_threshold_paise,
        category_loyal_min_share=settings.campaign_category_loyal_min_share,
        browse_min_views=settings.campaign_browse_min_views,
        browse_window_days=settings.campaign_browse_window_days,
    )
    if segment_key not in segments:
        raise CampaignError(f"Unknown segment '{segment_key}'. Known: {sorted(segments)}")
    segment = segments[segment_key]

    campaign_id = campaign_id or f"camp-{segment_key}-{uuid.uuid4().hex[:8]}"
    rng = random.Random(seed)

    run = CampaignRun(campaign_id=campaign_id, segment_name=segment_key, status="completed")
    db.add(run)
    db.commit()

    _audit.log_event(
        db,
        session_id=campaign_id,
        user_id=_CAMPAIGN_USER_ID,
        event_type="segment_computed",
        actor="system",
        tool_args={"segment": segment_key, "size": segment.size},
        reason=f"Segment '{segment_key}' ({segment.description}) has {segment.size} member(s).",
    )

    if segment.size < settings.campaign_min_segment_size:
        reason = (
            f"Segment '{segment_key}' has only {segment.size} member(s), below the minimum of "
            f"{settings.campaign_min_segment_size} needed to draw a reliable conclusion — refusing to run."
        )
        run.status = "blocked_at_segment"
        db.commit()
        _audit.log_event(
            db,
            session_id=campaign_id,
            user_id=_CAMPAIGN_USER_ID,
            event_type="campaign_blocked",
            actor="policy",
            decision="DENY",
            rule_name="SegmentSizeRule",
            reason=reason,
        )
        return CampaignResult(campaign_id, segment_key, "blocked_at_segment", None, None, reason)

    # Control/treatment split — deterministic given the seed, computed
    # BEFORE any proposal or policy evaluation exists. "Genuinely held out"
    # is a structural fact here, not a claim: a control customer's
    # CampaignOffer row is built straight from simulate_offer_outcome, never
    # from a ProposedOfferState, so there is no code path that evaluates a
    # control customer against the policy engine at all.
    members = list(segment.members)
    rng.shuffle(members)
    n_control = max(1, round(len(members) * settings.campaign_control_group_fraction))
    control_members = members[:n_control]
    treatment_members = members[n_control:]

    _audit.log_event(
        db,
        session_id=campaign_id,
        user_id=_CAMPAIGN_USER_ID,
        event_type="control_group_split",
        actor="system",
        tool_args={"control_size": len(control_members), "treatment_size": len(treatment_members)},
        reason=f"Held out {len(control_members)} of {len(members)} segment member(s) as a control group "
        "(never targeted, never evaluated for an offer).",
    )

    catalog, _ = product_repo.list_products(db, page=1, page_size=1000)
    catalog_by_sku = {p.sku: p for p in catalog}
    is_personalized = segment_key == "browse_abandonment"

    if is_personalized:
        # Deterministic — no LLM call, and this is stated honestly in the
        # data itself (model_used, zero token/cost fields) rather than
        # faking a model call that didn't happen. There's no judgment to
        # exercise: the SKU is whatever this specific customer repeatedly
        # viewed (personalized per member — see each CampaignOffer.sku, not
        # one segment-wide choice), and the discount is fixed by config,
        # deliberately small (see docs/046b-browse-abandonment.md) rather
        # than proposed, since a bigger one would just give away margin on
        # a sale that was already likely.
        proposal = CampaignProposal(
            skus=[],
            discount_pct=settings.campaign_browse_abandonment_discount_pct,
            message="Still deciding? Here's a small thank-you for taking a close look.",
            rationale=(
                "Deterministic nudge, no LLM call — the SKU is personalized per customer "
                "(whatever they specifically viewed repeatedly, not a segment-wide pick) and the "
                "discount is a fixed, deliberately small config value, not a proposal."
            ),
            model_used="none (deterministic browse-abandonment offer)",
            fallback_used=False,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_paise=0,
            latency_ms=0,
        )
        _audit.log_event(
            db,
            session_id=campaign_id,
            user_id=_CAMPAIGN_USER_ID,
            event_type="campaign_proposed",
            actor="system",
            tool_args={"discount_pct": proposal.discount_pct, "message": proposal.message, "personalized_sku": True},
            reason=proposal.rationale,
        )
    else:
        catalog_summary = [
            {"sku": p.sku, "name": p.name, "category": p.category, "price_paise": p.price_paise}
            for p in catalog
            if p.sku != _INJECTION_SKU and p.stock > 0
        ]
        segment_stats = {
            "size": segment.size,
            "avg_lifetime_spend_paise": round(sum(m.lifetime_spend_paise for m in segment.members) / segment.size),
            "avg_order_count": round(sum(m.order_count for m in segment.members) / segment.size, 1),
            "top_categories": sorted({m.top_category for m in segment.members if m.top_category}),
        }
        try:
            proposal = propose_campaign(
                segment_name=segment_key,
                segment_description=segment.description,
                segment_stats=segment_stats,
                catalog_summary=catalog_summary,
            )
        except CampaignProposalError as e:
            run.status = "blocked_at_segment"
            db.commit()
            _audit.log_event(
                db,
                session_id=campaign_id,
                user_id=_CAMPAIGN_USER_ID,
                event_type="campaign_proposal_failed",
                actor="system",
                decision="DENY",
                reason=str(e),
            )
            return CampaignResult(campaign_id, segment_key, "blocked_at_segment", None, None, str(e))

        _audit.log_event(
            db,
            session_id=campaign_id,
            user_id=_CAMPAIGN_USER_ID,
            event_type="campaign_proposed",
            actor="agent",
            tool_args={"skus": proposal.skus, "discount_pct": proposal.discount_pct, "message": proposal.message},
            reason=proposal.rationale,
            model_used=proposal.model_used,
            prompt_tokens=proposal.prompt_tokens,
            completion_tokens=proposal.completion_tokens,
            total_tokens=proposal.total_tokens,
            cost_paise=proposal.cost_paise,
            latency_ms=proposal.latency_ms,
            fallback_used=proposal.fallback_used,
        )

    run.proposal = {
        "skus": proposal.skus,
        "discount_pct": proposal.discount_pct,
        "message": proposal.message,
        "rationale": proposal.rationale,
    }
    db.commit()

    # Shared across the whole campaign for the original five segments; for
    # browse_abandonment this stays empty and _member_featured_products()
    # resolves each customer's own target_sku instead.
    shared_featured = (
        ()
        if is_personalized
        else tuple(
            FeaturedProductSnapshot(sku=p.sku, price_paise=p.price_paise, cost_paise=p.cost_paise)
            for p in catalog
            if p.sku in proposal.skus
        )
    )

    engine = default_campaign_policy_engine()
    recent_counts = _recent_offer_counts(
        db, [m.customer_id for m in treatment_members], meta.as_of, settings.campaign_offer_frequency_window_days
    )

    budget = settings.campaign_default_budget_paise
    committed = 0
    outcomes = []

    for member in treatment_members:
        member_featured = _member_featured_products(member, shared_featured, catalog_by_sku)
        member_primary = member_featured[0]
        action = ProposedOfferState(
            campaign_id=campaign_id,
            segment_name=segment_key,
            segment_size=segment.size,
            min_segment_size=settings.campaign_min_segment_size,
            customer_id=member.customer_id,
            customer_key=member.customer_key,
            discount_pct=proposal.discount_pct,
            featured_products=member_featured,
            campaign_budget_paise=budget,
            committed_spend_paise=committed,
            customer_recent_offer_count=recent_counts.get(member.customer_id, 0),
            max_offers_per_window=settings.campaign_max_offers_per_window,
        )
        decision_result = engine.evaluate(action)
        _audit.log_event(
            db,
            session_id=campaign_id,
            user_id=_CAMPAIGN_USER_ID,
            event_type="policy_decision",
            actor="policy",
            tool_name=member.customer_key,
            decision=decision_result.decision.value,
            rule_name=decision_result.rule_name,
            reason=decision_result.reason,
        )

        allowed = decision_result.decision == Decision.ALLOW
        if allowed:
            committed += action.estimated_discount_cost_paise
            outcome = simulate_offer_outcome(
                rng,
                customer_id=member.customer_id,
                group="offered",
                product_price_paise=member_primary.price_paise,
                product_cost_paise=member_primary.cost_paise,
                discount_pct=proposal.discount_pct,
            )
        else:
            outcome = simulate_offer_outcome(
                rng,
                customer_id=member.customer_id,
                group="blocked",
                product_price_paise=member_primary.price_paise,
                product_cost_paise=member_primary.cost_paise,
                discount_pct=0.0,
            )
            _audit.log_event(
                db,
                session_id=campaign_id,
                user_id=_CAMPAIGN_USER_ID,
                event_type="offer_blocked",
                actor="policy",
                tool_name=member.customer_key,
                decision="DENY",
                rule_name=decision_result.rule_name,
                reason=decision_result.reason,
            )

        db.add(
            CampaignOffer(
                campaign_id=campaign_id,
                customer_id=member.customer_id,
                group="treatment",
                decision=decision_result.decision.value,
                rule_name=decision_result.rule_name,
                reason=decision_result.reason,
                discount_pct=proposal.discount_pct if allowed else None,
                sku=member_primary.sku,
                redeemed=outcome.redeemed,
                revenue_paise=outcome.revenue_paise,
                cogs_paise=outcome.cogs_paise,
            )
        )
        outcomes.append(outcome)
        if outcome.redeemed:
            _audit.log_event(
                db,
                session_id=campaign_id,
                user_id=_CAMPAIGN_USER_ID,
                event_type="redemption_recorded",
                actor="system",
                tool_name=member.customer_key,
                reason=f"Redeemed for ₹{outcome.revenue_paise / 100:.2f} (simulated — see docs/046-campaigns.md).",
            )

    for member in control_members:
        member_featured = _member_featured_products(member, shared_featured, catalog_by_sku)
        member_primary = member_featured[0]
        outcome = simulate_offer_outcome(
            rng,
            customer_id=member.customer_id,
            group="control",
            product_price_paise=member_primary.price_paise,
            product_cost_paise=member_primary.cost_paise,
            discount_pct=0.0,
        )
        db.add(
            CampaignOffer(
                campaign_id=campaign_id,
                customer_id=member.customer_id,
                group="control",
                decision=None,
                sku=member_primary.sku,
                redeemed=False,
                revenue_paise=outcome.revenue_paise,
                cogs_paise=outcome.cogs_paise,
            )
        )
        outcomes.append(outcome)

    db.commit()

    measurement = measure_campaign(outcomes, segment_size=segment.size)
    run.result_summary = asdict(measurement)
    db.commit()

    _audit.log_event(
        db,
        session_id=campaign_id,
        user_id=_CAMPAIGN_USER_ID,
        event_type="results_computed",
        actor="system",
        tool_args=run.result_summary,
        reason=f"Incremental revenue ₹{measurement.incremental_revenue_paise / 100:.2f}, "
        f"net margin impact ₹{measurement.net_margin_impact_paise / 100:.2f} (both simulated).",
    )

    return CampaignResult(campaign_id, segment_key, "completed", proposal, measurement)
