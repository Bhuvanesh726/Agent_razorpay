"""Merchant-facing campaign endpoints — read-only. Running a campaign is
deliberately not an HTTP action (see campaigns/run.py): it makes a real,
possibly-slow LLM call and mutates a fair amount of state in one go, which
fits a batch script's "one command" framing better than a web request. This
router only ever reads what a run already produced.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.campaigns import segmentation, service
from app.campaigns.generator import get_generation_meta
from app.core.config import settings
from app.database import get_db
from app.schemas.campaigns import (
    CampaignDetailOut,
    CampaignMeasurementOut,
    CampaignOfferOut,
    CampaignProposalOut,
    CampaignSummaryOut,
    ContentGapOut,
    SegmentOut,
)

_audit = AuditService()

router = APIRouter(tags=["campaigns"])


def _to_summary(run) -> CampaignSummaryOut:
    return CampaignSummaryOut(
        campaign_id=run.campaign_id,
        segment_name=run.segment_name,
        status=run.status,
        created_at=run.created_at,
        proposal=CampaignProposalOut(**run.proposal) if run.proposal else None,
        measurement=CampaignMeasurementOut(**run.result_summary) if run.result_summary else None,
    )


@router.get("/api/campaigns/segments", response_model=list[SegmentOut])
def list_segments(db: Session = Depends(get_db)) -> list[SegmentOut]:
    meta = get_generation_meta(db)
    if meta is None:
        return []
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
    return [SegmentOut(name=s.name, description=s.description, size=s.size) for s in segments.values()]


@router.get("/api/campaigns", response_model=list[CampaignSummaryOut])
def list_campaigns(db: Session = Depends(get_db)) -> list[CampaignSummaryOut]:
    return [_to_summary(run) for run in service.list_campaign_runs(db)]


@router.get("/api/campaigns/content-gaps", response_model=list[ContentGapOut])
def list_content_gaps(db: Session = Depends(get_db)) -> list[ContentGapOut]:
    """Registered before /api/campaigns/{campaign_id} on purpose — a
    static path must be matched before a path parameter can shadow it."""
    return [ContentGapOut(**gap) for gap in _audit.get_content_gaps(db)]


@router.get("/api/campaigns/{campaign_id}", response_model=CampaignDetailOut)
def get_campaign(campaign_id: str, db: Session = Depends(get_db)) -> CampaignDetailOut:
    run = service.get_campaign_run(db, campaign_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No campaign '{campaign_id}'.")
    offers = service.get_campaign_offers(db, campaign_id)
    summary = _to_summary(run)
    return CampaignDetailOut(
        **summary.model_dump(),
        offers=[
            CampaignOfferOut(
                customer_key=key,
                group=offer.group,
                decision=offer.decision,
                rule_name=offer.rule_name,
                reason=offer.reason,
                discount_pct=offer.discount_pct,
                sku=offer.sku,
                redeemed=offer.redeemed,
                revenue_paise=offer.revenue_paise,
                cogs_paise=offer.cogs_paise,
            )
            for offer, key in offers
        ],
    )
