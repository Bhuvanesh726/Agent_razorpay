"""Unit tests for every policy rule and the engine's decision priority.

No DB, no network, no LLM — everything here runs on plain dataclasses. This
is the point: the policy engine must be provably correct without a running
server or a model in the loop.
"""

import pytest

from app.policy.engine import PolicyEngine, default_policy_engine
from app.policy.rules import (
    AgentScopeRule,
    AgentSpendLimitRule,
    ConfirmationThresholdRule,
    PerItemPriceRule,
    QuantityRule,
    RevokedCredentialRule,
    SpendCapRule,
    StockRule,
    UnknownSkuRule,
    UpsellPolicyRule,
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


# --- UpsellPolicyRule ---------------------------------------------------

DENTASTIX = CatalogProductSnapshot(sku="PET-004", price_paise=24900, stock=40)


def make_upsell_action(**overrides) -> ProposedCartState:
    defaults = dict(
        session_id="sess-1",
        user_id="user_demo",
        tool_name="propose_upsell",
        budget_paise=500_000,
        current_cart_total_paise=74000,
        sku=DENTASTIX.sku,
        quantity=1,
        product=DENTASTIX,
        upsell_proposed_count=0,
        upsell_declined_skus=frozenset(),
        upsell_original_cart_total_paise=74000,
    )
    defaults.update(overrides)
    return ProposedCartState(**defaults)


def test_upsell_ignored_for_non_upsell_tools():
    rule = UpsellPolicyRule(max_per_session=1, max_pct_of_original_cart=0.5)
    assert rule.evaluate(make_action()) is None  # tool_name="add_to_cart" from the shared helper


def test_upsell_allowed_within_session_cap_and_pct():
    rule = UpsellPolicyRule(max_per_session=1, max_pct_of_original_cart=0.5)
    # 24900 / 74000 = 33.6%, under the 50% cap; proposed_count 0 < max 1
    assert rule.evaluate(make_upsell_action()) is None


def test_upsell_denied_once_session_cap_reached():
    rule = UpsellPolicyRule(max_per_session=1, max_pct_of_original_cart=0.5)
    result = rule.evaluate(make_upsell_action(upsell_proposed_count=1))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "UpsellPolicyRule"
    assert "maximum" in result.reason


def test_upsell_denied_above_pct_of_original_cart():
    rule = UpsellPolicyRule(max_per_session=2, max_pct_of_original_cart=0.30)
    # 24900 / 74000 = 33.6% > 30%
    result = rule.evaluate(make_upsell_action(upsell_proposed_count=0))
    assert result is not None
    assert result.decision == Decision.DENY
    assert "30%" in result.reason


def test_upsell_denied_for_a_previously_declined_sku():
    rule = UpsellPolicyRule(max_per_session=3, max_pct_of_original_cart=0.9)
    result = rule.evaluate(make_upsell_action(upsell_declined_skus=frozenset({"PET-004"})))
    assert result is not None
    assert result.decision == Decision.DENY
    assert "already declined" in result.reason


def test_upsell_item_level_rules_apply_to_propose_upsell_too():
    """No special path: the same StockRule/PerItemPriceRule/QuantityRule/
    SpendCapRule instances that gate add_to_cart also gate a candidate
    upsell — this is PRICE_CHECKED_TOOLS in policy/rules.py, not anything
    UpsellPolicyRule-specific."""
    engine = default_policy_engine()
    over_budget = make_upsell_action(current_cart_total_paise=480_000, budget_paise=500_000)
    result = engine.evaluate(over_budget)  # 480000 + 24900 > 500000
    assert result.decision == Decision.DENY
    assert result.rule_name == "SpendCapRule"


# --- Layer 4.7: agent-only rules -------------------------------------------


def make_agent_action(**overrides) -> ProposedCartState:
    defaults = dict(
        acting_agent_credential_id="agent_abc123",
        agent_credential_status="ACTIVE",
        agent_scopes=frozenset({"search_products", "get_product", "add_to_cart", "view_cart", "initiate_payment"}),
        agent_spend_limit_paise=50_000,
        agent_spent_paise=0,
    )
    defaults.update(overrides)
    return make_action(**defaults)


def test_agent_rules_are_no_ops_for_a_human_buyer_action():
    # No acting_agent_credential_id at all -> every agent rule stays silent.
    action = make_action()
    assert RevokedCredentialRule().evaluate(action) is None
    assert AgentScopeRule().evaluate(action) is None
    assert AgentSpendLimitRule().evaluate(action) is None


def test_revoked_credential_denied_immediately():
    rule = RevokedCredentialRule()
    result = rule.evaluate(make_agent_action(agent_credential_status="REVOKED"))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "RevokedCredentialRule"
    assert "agent_abc123" in result.reason


def test_revoked_credential_check_applies_to_non_cart_tools_too():
    """A revoked agent can't even browse — the rule doesn't key off
    CART_MUTATING_TOOLS at all."""
    rule = RevokedCredentialRule()
    action = make_agent_action(agent_credential_status="REVOKED", tool_name="view_cart", sku=None, product=None, quantity=None)
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY


def test_active_credential_allowed_by_revoked_rule():
    rule = RevokedCredentialRule()
    assert rule.evaluate(make_agent_action(agent_credential_status="ACTIVE")) is None


def test_agent_scope_rule_allows_a_scoped_tool():
    rule = AgentScopeRule()
    action = make_agent_action(agent_scopes=frozenset({"add_to_cart"}))
    assert rule.evaluate(action) is None


def test_agent_scope_rule_denies_an_unscoped_tool():
    rule = AgentScopeRule()
    action = make_agent_action(agent_scopes=frozenset({"search_products", "view_cart"}))  # no add_to_cart
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "AgentScopeRule"
    assert "add_to_cart" in result.reason


def test_agent_spend_limit_allows_within_limit():
    rule = AgentSpendLimitRule()
    # PET-001 costs 74000 paise, over the default 50_000 limit -> use a cheaper line
    cheap = CatalogProductSnapshot(sku="GRO-004", price_paise=2_800, stock=100)
    action = make_agent_action(product=cheap, sku=cheap.sku, agent_spend_limit_paise=50_000, agent_spent_paise=0)
    assert rule.evaluate(action) is None


def test_agent_spend_limit_denies_once_projected_total_exceeds_limit():
    rule = AgentSpendLimitRule()
    # already "spent" 480 in prior turns/sessions; this add (740) would push
    # the credential's cumulative total to 1220, over its 500-paise... use realistic units:
    action = make_agent_action(agent_spend_limit_paise=50_000, agent_spent_paise=0)  # PET-001 = 74000 > 50000
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "AgentSpendLimitRule"


def test_agent_spend_limit_blocks_even_when_session_budget_is_higher():
    """The DoD scenario itself: a ₹500 credential limit blocks an add that
    a much larger session budget would otherwise allow."""
    cheap = CatalogProductSnapshot(sku="GRO-004", price_paise=45_000, stock=100)  # ₹450, fits an unlimited session budget
    action = make_agent_action(
        product=cheap, sku=cheap.sku, quantity=1,
        budget_paise=500_000,  # generous session budget — SpendCapRule alone would allow this
        agent_spend_limit_paise=50_000, agent_spent_paise=10_000,  # already ₹100 spent; +₹450 = ₹550 > ₹500 limit
    )
    engine = default_policy_engine()
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY
    assert result.rule_name == "AgentSpendLimitRule"


def test_agent_spend_limit_ignores_non_cart_tools():
    rule = AgentSpendLimitRule()
    action = make_agent_action(tool_name="view_cart", sku=None, product=None, quantity=None, agent_spend_limit_paise=100)
    assert rule.evaluate(action) is None


def test_revoked_credential_wins_over_scope_and_spend_in_registration_order():
    engine = default_policy_engine()
    action = make_agent_action(
        agent_credential_status="REVOKED",
        agent_scopes=frozenset(),  # would also fail AgentScopeRule
        agent_spend_limit_paise=1,  # would also fail AgentSpendLimitRule
    )
    result = engine.evaluate(action)
    assert result.rule_name == "RevokedCredentialRule"
