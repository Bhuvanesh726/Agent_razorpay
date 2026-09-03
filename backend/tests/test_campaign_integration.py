"""Integration tests for the full campaign run — the LLM gateway is
stubbed (a scripted propose_campaign tool call, same pattern as
test_harness_integration.py) but the generator, segmentation, policy
engine, simulation, DB, and audit trail are all real.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.campaigns.generator import generate_history
from app.campaigns.models import CampaignOffer
from app.campaigns.service import run_campaign
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
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


def _proposal_response(skus: list[str], discount_pct: float, message: str = "A special offer just for you.") -> GatewayResult:
    args = {"skus": skus, "discount_pct": discount_pct, "message": message, "rationale": "test rationale"}
    return GatewayResult(
        content=None,
        tool_calls=[GatewayToolCall(id="call_1", name="propose_campaign", arguments_raw=json.dumps(args))],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cost_paise=0,
    )


@pytest.fixture()
def history(db_session):
    _seed_catalog(db_session)
    generate_history(db_session, seed=42, as_of=_AS_OF)
    return db_session


def _cheapest_repeat_pairing(db_session) -> tuple[str, float]:
    """A SKU + discount that comfortably clears both DiscountCapRule and
    MarginFloorRule at their default settings, for tests that aren't
    specifically about those two rules."""
    return "GRO-004", 0.10  # Tata Salt: 2800 paise price, ~63% margin at list per the seeded cost_paise


def test_full_campaign_run_end_to_end(history):
    sku, discount = _cheapest_repeat_pairing(history)
    with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response([sku], discount)):
        result = run_campaign(history, "repeat", seed=7)

    assert result.status == "completed"
    assert result.proposal.skus == [sku]
    assert result.measurement is not None
    assert result.measurement.segment_size == result.measurement.offers_sent + result.measurement.offers_blocked + result.measurement.control_size

    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id).all()
    assert len(offers) == result.measurement.segment_size
    treatment = [o for o in offers if o.group == "treatment"]
    control = [o for o in offers if o.group == "control"]
    assert len(treatment) + len(control) == len(offers)
    assert all(o.decision in ("ALLOW", "DENY") for o in treatment)


def test_control_group_is_genuinely_held_out(history):
    sku, discount = _cheapest_repeat_pairing(history)
    with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response([sku], discount)):
        result = run_campaign(history, "repeat", seed=7)

    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id).all()
    control = [o for o in offers if o.group == "control"]
    assert len(control) > 0
    # Structural, not behavioral: a control row's decision/rule/discount
    # stay NULL because no ProposedOfferState was ever built for it.
    for o in control:
        assert o.decision is None
        assert o.rule_name is None
        assert o.discount_pct is None
        assert not o.redeemed or o.group != "treatment"  # control conversions are organic, never "redeemed"


def test_margin_floor_blocks_a_too_steep_discount(history):
    # GRO-002 (India Gate Rice): price 64900, cost roughly 56% of that per
    # the seeded margin factor — a 70% discount drives the sale price well
    # under cost, tripping MarginFloorRule regardless of DiscountCapRule.
    with patch("app.core.config.settings.campaign_max_discount_pct", 0.90):
        with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response(["GRO-002"], 0.70)):
            result = run_campaign(history, "repeat", seed=7)

    assert result.status == "completed"
    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id, CampaignOffer.group == "treatment").all()
    denied = [o for o in offers if o.decision == "DENY"]
    assert denied, "expected at least one offer denied by MarginFloorRule"
    assert all(o.rule_name == "MarginFloorRule" for o in denied)
    assert result.measurement.offers_blocked == len(denied)


def test_campaign_budget_stops_the_campaign_mid_run(history):
    sku, discount = _cheapest_repeat_pairing(history)
    # Small enough budget that only the first one or two treatment
    # customers can be allowed before CampaignBudgetRule takes over.
    with patch("app.core.config.settings.campaign_default_budget_paise", 100):
        with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response([sku], discount)):
            result = run_campaign(history, "repeat", seed=7)

    offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == result.campaign_id, CampaignOffer.group == "treatment").all()
    budget_denied = [o for o in offers if o.rule_name == "CampaignBudgetRule"]
    assert budget_denied, "expected CampaignBudgetRule to have blocked at least one offer with a near-zero budget"


def test_segment_too_small_blocks_the_whole_campaign(history):
    with patch("app.core.config.settings.campaign_min_segment_size", 999):
        with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response(["GRO-004"], 0.10)):
            result = run_campaign(history, "one_time", seed=7)

    assert result.status == "blocked_at_segment"
    assert result.measurement is None
    offers = history.query(CampaignOffer).all()
    assert len(offers) == 0  # not even a control group was built


def test_offer_frequency_rule_blocks_repeat_targeting_across_runs(history):
    sku, discount = _cheapest_repeat_pairing(history)
    with patch("app.campaigns.agent.gateway.call", return_value=_proposal_response([sku], discount)):
        first = run_campaign(history, "repeat", seed=7)
        second = run_campaign(history, "repeat", seed=11)  # different seed -> different control/treatment split

    first_allowed_ids = {
        o.customer_id
        for o in history.query(CampaignOffer).filter(CampaignOffer.campaign_id == first.campaign_id, CampaignOffer.decision == "ALLOW")
    }
    second_offers = history.query(CampaignOffer).filter(CampaignOffer.campaign_id == second.campaign_id, CampaignOffer.group == "treatment").all()
    overlap = [o for o in second_offers if o.customer_id in first_allowed_ids]
    assert overlap, "test setup needs at least one customer allowed in run 1 and re-targeted in run 2"
    for o in overlap:
        assert o.decision == "DENY"
        assert o.rule_name == "OfferFrequencyRule"
