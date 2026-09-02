"""Unit tests for the two Layer 2 policy rules. Same discipline as the
Layer 1 rules: plain dataclasses, zero DB/network/LLM.
"""

from app.policy.engine import PolicyEngine, default_policy_engine
from app.policy.rules import (
    DuplicatePaymentRule,
    PaymentAuthorizationRule,
    PerItemPriceRule,
    QuantityRule,
    SpendCapRule,
    StockRule,
    UnknownSkuRule,
)
from app.policy.types import CartLineSnapshot, CatalogProductSnapshot, Decision, ProposedCartState

PEDIGREE = CatalogProductSnapshot(sku="PET-001", price_paise=74000, stock=25)
DROOLS = CatalogProductSnapshot(sku="PET-002", price_paise=39900, stock=30)


def make_payment_action(**overrides) -> ProposedCartState:
    defaults = dict(
        session_id="sess-1",
        user_id="user_demo",
        tool_name="initiate_payment",
        budget_paise=200_000,
        current_cart_total_paise=0,
        cart_line_items=(CartLineSnapshot(product=PEDIGREE, quantity=1),),
        existing_order_status=None,
    )
    defaults.update(overrides)
    return ProposedCartState(**defaults)


# --- DuplicatePaymentRule ---------------------------------------------------


def test_duplicate_payment_denied_when_already_paid():
    rule = DuplicatePaymentRule()
    result = rule.evaluate(make_payment_action(existing_order_status="PAID"))
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.rule_name == "DuplicatePaymentRule"


def test_duplicate_payment_silent_when_not_paid_yet():
    rule = DuplicatePaymentRule()
    for status in (None, "PENDING", "AWAITING_CONFIRMATION", "FAILED", "CANCELLED"):
        assert rule.evaluate(make_payment_action(existing_order_status=status)) is None


def test_duplicate_payment_rule_ignores_non_payment_tools():
    rule = DuplicatePaymentRule()
    action = make_payment_action(tool_name="add_to_cart", existing_order_status="PAID")
    assert rule.evaluate(action) is None


# --- PaymentAuthorizationRule ------------------------------------------------


def _item_rules(per_item_max=300_000, quantity_max=10, spend_cap_default=1_000_000):
    return [
        UnknownSkuRule(),
        StockRule(),
        PerItemPriceRule(per_item_max),
        QuantityRule(quantity_max),
        SpendCapRule(spend_cap_default),
    ]


def test_payment_authorization_requires_confirmation_when_cart_is_clean():
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    result = rule.evaluate(make_payment_action())
    assert result is not None
    assert result.decision == Decision.REQUIRE_CONFIRMATION
    assert result.rule_name == "PaymentAuthorizationRule"


def test_payment_authorization_never_returns_allow():
    """However clean the cart, payment must never be a straight ALLOW —
    a human always has to confirm it."""
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    result = rule.evaluate(make_payment_action())
    assert result is not None
    assert result.decision != Decision.ALLOW


def test_payment_authorization_denies_empty_cart():
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    result = rule.evaluate(make_payment_action(cart_line_items=()))
    assert result is not None
    assert result.decision == Decision.DENY


def test_payment_authorization_denies_when_stock_dropped_since_add_time():
    """A cart approved five minutes ago is not automatically approved now —
    if stock fell below the cart's quantity in the meantime, re-validation
    must catch it."""
    thin_stock = CatalogProductSnapshot(sku=PEDIGREE.sku, price_paise=PEDIGREE.price_paise, stock=0)
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    action = make_payment_action(cart_line_items=(CartLineSnapshot(product=thin_stock, quantity=1),))
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY
    assert "PET-001" in result.reason


def test_payment_authorization_denies_over_budget_cart():
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    action = make_payment_action(
        budget_paise=50_000,  # both items together (740 + 399) exceed this
        cart_line_items=(
            CartLineSnapshot(product=PEDIGREE, quantity=1),
            CartLineSnapshot(product=DROOLS, quantity=1),
        ),
    )
    result = rule.evaluate(action)
    assert result is not None
    assert result.decision == Decision.DENY


def test_payment_authorization_ignores_non_payment_tools():
    rule = PaymentAuthorizationRule(item_rules=_item_rules())
    action = make_payment_action(tool_name="add_to_cart")
    assert rule.evaluate(action) is None


# --- Definition-of-done scenarios, via the real default engine -------------


def test_default_engine_payment_over_spend_cap_is_denied():
    engine = default_policy_engine()
    action = make_payment_action(
        budget_paise=50_000,
        cart_line_items=(CartLineSnapshot(product=PEDIGREE, quantity=1),),
    )
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY


def test_default_engine_payment_requires_confirmation_on_clean_cart():
    engine = default_policy_engine()
    action = make_payment_action()
    result = engine.evaluate(action)
    assert result.decision == Decision.REQUIRE_CONFIRMATION
    assert result.rule_name == "PaymentAuthorizationRule"


def test_default_engine_denies_duplicate_over_authorization():
    """DENY beats REQUIRE_CONFIRMATION even though PaymentAuthorizationRule
    would otherwise confirm a perfectly clean cart."""
    engine = default_policy_engine()
    action = make_payment_action(existing_order_status="PAID")
    result = engine.evaluate(action)
    assert result.decision == Decision.DENY
    assert result.rule_name == "DuplicatePaymentRule"
