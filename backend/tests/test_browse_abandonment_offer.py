"""Integration tests for the browse_abandonment offer path. No LLM stub
needed — this segment's offer is deterministic config, not a model call
(see app/campaigns/service.py), so run_campaign() can be called directly.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.campaigns.generator import generate_history
from app.campaigns.models import CampaignOffer
from app.campaigns.service import run_campaign
from app.repositories import product_repo

_AS_OF = datetime(2026, 9, 3, tzinfo=timezone.utc)
_PRODUCTS_JSON = Path(__file__).resolve().parents[1] / "data" / "products.json"


def _seed_catalog(db) -> None:
    catalog = json.loads(_PRODUCTS_JSON.read_text(encoding="utf-8"))
    for entry in catalog["products"]:
        product_repo.upsert(
            db,
            {
                "sku": entry["sku"],
                "name": entry["name"],
                "brand": entry["brand"],
                "category": entry["category"],
                "price_paise": entry["price_paise"],
                "cost_paise": entry["cost_paise"],
                "unit": entry["unit"],
                "stock": entry["stock"],
                "description": entry["description"],
                "tags": entry["tags"],
            },
        )
    db.commit()


@pytest.fixture()
def history(db_session):
    _seed_catalog(db_session)
    generate_history(db_session, seed=42, as_of=_AS_OF)
    return db_session


def test_browse_abandonment_offer_is_personalized_and_deterministic(history):
    result = run_campaign(history, "browse_abandonment", seed=7)

    assert result.status == "completed"
    assert result.proposal.model_used.startswith("none")  # honestly labeled as not an LLM call
    assert result.proposal.total_tokens == 0
    assert result.proposal.discount_pct == pytest.approx(0.02)

    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id, CampaignOffer.group == "treatment").all()
    assert offers, "expected at least one treatment offer"
    allowed = [o for o in offers if o.decision == "ALLOW"]
    for o in allowed:
        assert o.discount_pct == pytest.approx(0.02)
        assert o.sku is not None  # each offer carries its own personalized SKU

    # Not every allowed offer shares the same SKU — proof this isn't a
    # single segment-wide featured product like the other five segments.
    skus = {o.sku for o in allowed}
    assert len(skus) >= 1
    if len(allowed) > 1:
        assert len(skus) > 1, "expected different customers to have different personalized SKUs"


def test_default_2pct_discount_clears_policy(history):
    result = run_campaign(history, "browse_abandonment", seed=7)
    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id, CampaignOffer.group == "treatment").all()
    cap_denials = [o for o in offers if o.rule_name == "DiscountCapRule"]
    assert not cap_denials, "the default 2% nudge should never itself trip DiscountCapRule"


def test_configuring_a_larger_discount_is_blocked_by_discount_cap_rule(history):
    with patch("app.core.config.settings.campaign_browse_abandonment_discount_pct", 0.50):
        with patch("app.core.config.settings.campaign_max_discount_pct", 0.30):
            result = run_campaign(history, "browse_abandonment", seed=7)

    assert result.status == "completed"
    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id, CampaignOffer.group == "treatment").all()
    denied = [o for o in offers if o.decision == "DENY"]
    assert denied, "a 50% discount should be blocked given a 30% cap"
    assert all(o.rule_name == "DiscountCapRule" for o in denied)
