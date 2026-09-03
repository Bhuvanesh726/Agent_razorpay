"""Unit tests for every campaign policy rule and the engine's priority.
No DB, no network, no LLM — plain dataclasses, same discipline as
test_policy_rules.py.
"""

from app.campaigns.engine import CampaignPolicyEngine, default_campaign_policy_engine
from app.campaigns.rules import (
    CampaignBudgetRule,
    DiscountCapRule,
    MarginFloorRule,
    OfferFrequencyRule,
    SegmentSizeRule,
)
from app.campaigns.types import Decision, FeaturedProductSnapshot, ProposedOfferState

WIDGET = FeaturedProductSnapshot(sku="PET-001", price_paise=74_000, cost_paise=44_000)  # 40.5% margin at list price


def make_action(**overrides) -> ProposedOfferState:
    defaults = dict(
        campaign_id="camp-1",
        segment_name="lapsed",
        segment_size=10,
        min_segment_size=5,
        customer_id=1,
        customer_key="CUST-001",
        discount_pct=0.15,
        featured_products=(WIDGET,),
        campaign_budget_paise=300_000,
        committed_spend_paise=0,
        customer_recent_offer_count=0,
        max_offers_per_window=1,
    )
    defaults.update(overrides)
    return ProposedOfferState(**defaults)


# --- SegmentSizeRule -----------------------------------------------------


def test_segment_size_allowed_when_above_minimum():
    rule = SegmentSizeRule()
    assert rule.evaluate(make_action(segment_size=10, min_segment_size=5)) is None


def test_segment_size_denied_when_below_minimum():
    rule = SegmentSizeRule()
    result = rule.evaluate(make_action(segment_size=3, min_segment_size=5))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "SegmentSizeRule"
    assert "3" in result.reason and "5" in result.reason


# --- DiscountCapRule -------------------------------------------------------


def test_discount_within_cap_allowed():
    rule = DiscountCapRule(max_discount_pct=0.30)
    assert rule.evaluate(make_action(discount_pct=0.25)) is None


def test_discount_above_cap_denied():
    rule = DiscountCapRule(max_discount_pct=0.30)
    result = rule.evaluate(make_action(discount_pct=0.50))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "DiscountCapRule"
    assert "50%" in result.reason


# --- MarginFloorRule -------------------------------------------------------


def test_margin_floor_allowed_when_above_floor():
    # 74000 * (1-0.15) = 62900; margin = (62900-44000)/62900 = 30.0%
    rule = MarginFloorRule(min_margin_pct=0.15)
    assert rule.evaluate(make_action(discount_pct=0.15)) is None


def test_margin_floor_denied_when_discount_pushes_below_floor():
    # 74000 * (1-0.40) = 44400; margin = (44400-44000)/44400 = 0.9% < 15%
    rule = MarginFloorRule(min_margin_pct=0.15)
    result = rule.evaluate(make_action(discount_pct=0.40))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "MarginFloorRule"
    assert "PET-001" in result.reason


def test_margin_floor_checks_every_featured_product_not_just_primary():
    cheap_margin_product = FeaturedProductSnapshot(sku="GRO-004", price_paise=2_800, cost_paise=2_600)  # thin margin
    rule = MarginFloorRule(min_margin_pct=0.15)
    result = rule.evaluate(make_action(discount_pct=0.10, featured_products=(WIDGET, cheap_margin_product)))
    assert result is not None
    assert "GRO-004" in result.reason


# --- CampaignBudgetRule -----------------------------------------------------


def test_budget_allowed_when_headroom_remains():
    rule = CampaignBudgetRule()
    action = make_action(campaign_budget_paise=300_000, committed_spend_paise=100_000, discount_pct=0.15)
    assert rule.evaluate(action) is None


def test_budget_denied_when_offer_would_breach_cap():
    rule = CampaignBudgetRule()
    # estimated cost of this offer: 74000 * 0.15 = 11100
    action = make_action(campaign_budget_paise=105_000, committed_spend_paise=100_000, discount_pct=0.15)
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "CampaignBudgetRule"


def test_campaign_stops_mid_run_once_budget_is_exhausted():
    """A sequence of allowed offers accumulates committed_spend_paise; once
    the running total would breach the budget, further offers are denied —
    exactly the DoD's "a campaign that would breach the budget is stopped
    mid-run", exercised as a small integration of the rule + a manual loop."""
    engine = CampaignPolicyEngine(rules=[CampaignBudgetRule()])
    budget = 25_000  # room for roughly two 11100-paise offers, not three
    committed = 0
    allowed_count = 0
    for _ in range(5):
        action = make_action(campaign_budget_paise=budget, committed_spend_paise=committed, discount_pct=0.15)
        result = engine.evaluate(action)
        if result.decision == Decision.ALLOW:
            allowed_count += 1
            committed += action.estimated_discount_cost_paise
        else:
            assert result.rule_name == "CampaignBudgetRule"
    assert allowed_count == 2
    assert committed <= budget


# --- OfferFrequencyRule -----------------------------------------------------


def test_frequency_allowed_under_limit():
    rule = OfferFrequencyRule()
    assert rule.evaluate(make_action(customer_recent_offer_count=0, max_offers_per_window=1)) is None


def test_frequency_denied_at_limit():
    rule = OfferFrequencyRule()
    result = rule.evaluate(make_action(customer_recent_offer_count=1, max_offers_per_window=1))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "OfferFrequencyRule"
    assert "CUST-001" in result.reason


# --- Engine priority + default engine --------------------------------------


def test_first_deny_in_registration_order_wins():
    engine = CampaignPolicyEngine(
        rules=[DiscountCapRule(max_discount_pct=0.10), MarginFloorRule(min_margin_pct=0.15)]
    )
    # Both would object (60% discount breaches both the cap and the floor) -
    # DiscountCapRule is registered first, so it wins.
    result = engine.evaluate(make_action(discount_pct=0.60))
    assert result.rule_name == "DiscountCapRule"


def test_default_engine_allows_a_clean_offer():
    engine = default_campaign_policy_engine()
    result = engine.evaluate(make_action(discount_pct=0.15, campaign_budget_paise=300_000))
    assert result.decision == Decision.ALLOW
    assert result.rule_name == "__default__"


def test_default_engine_blocks_a_too_small_segment_before_anything_else():
    engine = default_campaign_policy_engine()
    result = engine.evaluate(make_action(segment_size=2, min_segment_size=5))
    assert result.decision == Decision.DENY
    assert result.rule_name == "SegmentSizeRule"
