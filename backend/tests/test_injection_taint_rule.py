"""`InjectionTaintRule` — a product whose own catalog text tries to issue
instructions is never added to a cart.

The hole this closes was real and specific. The injection scanner used to only
write an `injection_detected` audit event; the finding never reached the policy
engine. So a *modest* injection stayed inside every other bound and was allowed:
`add_to_cart(INJ-001, 1)` at ₹99 had all thirteen rules abstain and fell through
to the default ALLOW.

The eval suite did not catch it because its attack asks for 50 units and dies on
`StockRule` — the test passed because the attacker was greedy, not because the
system was defended.
"""

import pytest

from app.policy.engine import default_policy_engine
from app.policy.rules import InjectionTaintRule
from app.policy.types import CartLineSnapshot, CatalogProductSnapshot, Decision, ProposedCartState

TAINTED = CatalogProductSnapshot(sku="INJ-001", price_paise=9900, stock=5, injection_flagged=True)
CLEAN = CatalogProductSnapshot(sku="GRO-001", price_paise=27500, stock=40)


@pytest.fixture()
def engine():
    return default_policy_engine()


def _add(product, quantity, **kwargs):
    return ProposedCartState(
        session_id="s1",
        user_id="user_demo",
        tool_name="add_to_cart",
        budget_paise=500_000,
        current_cart_total_paise=0,
        sku=product.sku,
        quantity=quantity,
        product=product,
        **kwargs,
    )


# --- the case that used to pass -------------------------------------------


def test_a_single_cheap_tainted_unit_is_denied(engine):
    """The regression. One unit, ₹99, in stock, far inside a ₹5,000 budget —
    nothing about quantity, price, stock or budget objects to it."""
    result = engine.evaluate(_add(TAINTED, 1))

    assert result.decision == Decision.DENY
    assert result.rule_name == "InjectionTaintRule"


def test_the_refusal_names_content_integrity_not_a_limit(engine):
    """A buyer told 'out of stock' or 'over budget' would be misled about why
    this was refused, and the audit trail would record the wrong reason."""
    reason = engine.evaluate(_add(TAINTED, 1)).reason

    assert "instruction-like text" in reason
    assert "not a stock, price or budget limit" in reason


# --- ordering: taint beats the money rules --------------------------------


def test_fifty_units_is_denied_by_taint_not_stock(engine):
    """Quantity 50 against stock 5 breaches StockRule too. Registration order
    decides which reason the audit trail carries, and content integrity is the
    honest one — the request was not refused for being too large."""
    result = engine.evaluate(_add(TAINTED, 50))

    assert result.decision == Decision.DENY
    assert result.rule_name == "InjectionTaintRule"


def test_taint_is_not_a_quantity_or_price_question(engine):
    """One unit is refused exactly as firmly as fifty: tainted text makes the
    product untrustworthy, not the size of the request."""
    for quantity in (1, 2, 10, 50):
        assert engine.evaluate(_add(TAINTED, quantity)).rule_name == "InjectionTaintRule"


def test_an_agent_credential_is_denied_the_same_way(engine):
    result = engine.evaluate(
        _add(
            TAINTED,
            1,
            acting_agent_credential_id="agent_x",
            agent_credential_status="ACTIVE",
            agent_scopes=["add_to_cart", "initiate_payment"],
            agent_spend_limit_paise=50_000,
            agent_spent_paise=0,
        )
    )
    assert result.decision == Decision.DENY
    assert result.rule_name == "InjectionTaintRule"


# --- payment: the second way in -------------------------------------------


def test_payment_refuses_a_cart_holding_a_tainted_line(engine):
    """An item can reach the cart without passing this rule — added before it
    existed, or added by the buyer directly through /api/cart, which never goes
    through the policy engine. Payment is the last point it can be refused."""
    result = engine.evaluate(
        ProposedCartState(
            session_id="s1",
            user_id="user_demo",
            tool_name="initiate_payment",
            budget_paise=500_000,
            current_cart_total_paise=9900,
            cart_line_items=(CartLineSnapshot(product=TAINTED, quantity=1),),
        )
    )
    assert result.decision == Decision.DENY
    assert result.rule_name == "InjectionTaintRule"


# --- no collateral damage --------------------------------------------------


def test_a_clean_product_is_unaffected(engine):
    result = engine.evaluate(_add(CLEAN, 1))

    assert result.decision == Decision.ALLOW
    assert result.rule_name == "__default__"


def test_payment_on_a_clean_cart_still_asks_rather_than_refusing(engine):
    result = engine.evaluate(
        ProposedCartState(
            session_id="s1",
            user_id="user_demo",
            tool_name="initiate_payment",
            budget_paise=500_000,
            current_cart_total_paise=27500,
            cart_line_items=(CartLineSnapshot(product=CLEAN, quantity=1),),
        )
    )
    assert result.decision == Decision.REQUIRE_CONFIRMATION
    assert result.rule_name == "PaymentAuthorizationRule"


def test_products_are_clean_unless_flagged():
    """The flag defaults False, so every existing construction site — and every
    other test in this suite — keeps meaning 'clean'."""
    assert CatalogProductSnapshot(sku="X", price_paise=1, stock=1).injection_flagged is False


def test_the_rule_abstains_on_tools_it_does_not_govern():
    """view_cart, remove_from_cart and friends are not additions."""
    rule = InjectionTaintRule()
    action = ProposedCartState(
        session_id="s1",
        user_id="user_demo",
        tool_name="view_cart",
        budget_paise=500_000,
        current_cart_total_paise=0,
        product=TAINTED,
    )
    assert rule.evaluate(action) is None
