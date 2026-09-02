"""Unit tests for every policy rule and the engine's decision priority.

No DB, no network, no LLM — everything here runs on plain dataclasses. This
is the point: the policy engine must be provably correct without a running
server or a model in the loop.
"""

import pytest

from app.policy.engine import PolicyEngine, default_policy_engine
from app.policy.rules import (
    ConfirmationThresholdRule,
    PerItemPriceRule,
    QuantityRule,
    SpendCapRule,
    StockRule,
    UnknownSkuRule,
)
from app.policy.types import CatalogProductSnapshot, Decision, ProposedCartState

PEDIGREE = CatalogProductSnapshot(sku="PET-001", price_paise=74000, stock=25)


def make_action(**overrides) -> ProposedCartState:
    defaults = dict(
        session_id="sess-1",
        user_id="user_demo",
        tool_name="add_to_cart",
        budget_paise=100_000,
        current_cart_total_paise=0,
        sku=PEDIGREE.sku,
        quantity=1,
        product=PEDIGREE,
    )
    defaults.update(overrides)
    return ProposedCartState(**defaults)


# --- UnknownSkuRule ---------------------------------------------------


def test_unknown_sku_denied():
    rule = UnknownSkuRule()
    action = make_action(sku="GHOST-999", product=None)
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "UnknownSkuRule"
    assert "GHOST-999" in result.reason


def test_known_sku_not_flagged_by_unknown_sku_rule():
    rule = UnknownSkuRule()
    assert rule.evaluate(make_action()) is None


def test_unknown_sku_rule_ignores_non_cart_tools():
    rule = UnknownSkuRule()
    action = make_action(tool_name="search_products", sku="GHOST-999", product=None)
    assert rule.evaluate(action) is None


# --- StockRule ----------------------------------------------------------


def test_stock_rule_denies_over_stock():
    rule = StockRule()
    action = make_action(quantity=PEDIGREE.stock + 1)
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "StockRule"


def test_stock_rule_allows_within_stock():
    rule = StockRule()
    action = make_action(quantity=PEDIGREE.stock)
    assert rule.evaluate(action) is None


# --- PerItemPriceRule -----------------------------------------------------


def test_per_item_price_rule_denies_over_limit():
    rule = PerItemPriceRule(max_price_paise=50_000)
    result = rule.evaluate(make_action())
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "PerItemPriceRule"


def test_per_item_price_rule_allows_under_limit():
    rule = PerItemPriceRule(max_price_paise=100_000)
    assert rule.evaluate(make_action()) is None


# --- QuantityRule ---------------------------------------------------------


def test_quantity_rule_denies_over_max():
    rule = QuantityRule(max_quantity=5)
    result = rule.evaluate(make_action(quantity=6))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "QuantityRule"


def test_quantity_rule_allows_at_max():
    rule = QuantityRule(max_quantity=5)
    assert rule.evaluate(make_action(quantity=5)) is None


# --- SpendCapRule -----------------------------------------------------------


def test_spend_cap_denies_when_over_budget():
    rule = SpendCapRule(default_cap_paise=1_000_000)
    action = make_action(budget_paise=80_000, current_cart_total_paise=0, quantity=1)
    # PEDIGREE is 74000 paise, within an 80000 budget - should allow
    assert rule.evaluate(action) is None

    over_budget_action = make_action(budget_paise=80_000, quantity=2)  # 2 * 74000 = 148000
    result = rule.evaluate(over_budget_action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "SpendCapRule"
    assert "80.00" in result.reason


def test_spend_cap_uses_default_when_session_has_no_budget():
    rule = SpendCapRule(default_cap_paise=50_000)
    action = make_action(budget_paise=None)  # PEDIGREE is 74000, over the 50000 default
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY


def test_spend_cap_holds_when_model_tries_to_exceed_it():
    """The model proposes a cart-exceeding action; the rule must deny it
    regardless of what the model 'thinks' the budget allows."""
    rule = SpendCapRule(default_cap_paise=1_000_000)
    action = make_action(budget_paise=80_000, current_cart_total_paise=74_000, quantity=1)
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "SpendCapRule"


# --- ConfirmationThresholdRule ----------------------------------------------


def test_confirmation_threshold_triggers_above_limit():
    rule = ConfirmationThresholdRule(threshold_paise=50_000)
    result = rule.evaluate(make_action())
    assert result is not None
    assert result.decision == Decision.REQUIRE_CONFIRMATION
    assert result.rule_name == "ConfirmationThresholdRule"


def test_confirmation_threshold_silent_below_limit():
    rule = ConfirmationThresholdRule(threshold_paise=1_000_000)
    assert rule.evaluate(make_action()) is None


# --- Engine: priority and default ------------------------------------------


def test_engine_deny_beats_require_confirmation():
    engine = PolicyEngine(
        rules=[
            ConfirmationThresholdRule(threshold_paise=1),  # would fire REQUIRE_CONFIRMATION
            StockRule(),  # will fire DENY
        ]
    )
    action = make_action(quantity=PEDIGREE.stock + 1)
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY
    assert result.rule_name == "StockRule"


def test_engine_allows_when_nothing_objects():
    engine = PolicyEngine(rules=[StockRule(), QuantityRule(max_quantity=10)])
    result = engine.evaluate(make_action())
    assert result.decision == Decision.ALLOW


def test_engine_first_registered_deny_wins():
    engine = PolicyEngine(rules=[UnknownSkuRule(), StockRule()])
    action = make_action(sku="GHOST", product=None, quantity=999)
    result = engine.evaluate(action)
    assert result.rule_name == "UnknownSkuRule"


# --- Definition-of-done scenarios, via the real default engine -------------


def test_default_engine_denies_hallucinated_sku():
    engine = default_policy_engine()
    action = make_action(sku="FAKE-SKU-123", product=None)
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY
    assert result.rule_name == "UnknownSkuRule"


def test_default_engine_denies_over_budget_add():
    engine = default_policy_engine()
    oneplus = CatalogProductSnapshot(sku="ELE-002", price_paise=199_900, stock=15)
    action = ProposedCartState(
        session_id="sess-1",
        user_id="user_demo",
        tool_name="add_to_cart",
        budget_paise=80_000,
        current_cart_total_paise=74_000,  # Pedigree already in cart
        sku=oneplus.sku,
        quantity=1,
        product=oneplus,
    )
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY
    assert result.rule_name == "SpendCapRule"


def test_non_cart_tools_always_allowed_by_default_engine():
    engine = default_policy_engine()
    for tool_name in ("search_products", "get_product", "view_cart", "remove_from_cart"):
        action = ProposedCartState(
            session_id="sess-1",
            user_id="user_demo",
            tool_name=tool_name,
            budget_paise=1,
            current_cart_total_paise=0,
            sku="ANYTHING",
            quantity=999,
            product=None,
        )
        result = engine.evaluate(action)
        assert result.decision == Decision.ALLOW, f"{tool_name} should never be gated"


@pytest.mark.parametrize("tool_name", ["add_to_cart"])
def test_line_total_and_proposed_total_computed_correctly(tool_name):
    action = ProposedCartState(
        session_id="s",
        user_id="u",
        tool_name=tool_name,
        budget_paise=None,
        current_cart_total_paise=10_000,
        sku=PEDIGREE.sku,
        quantity=3,
        product=PEDIGREE,
    )
    assert action.line_total_paise == 74000 * 3
    assert action.proposed_cart_total_paise == 10_000 + 74000 * 3
