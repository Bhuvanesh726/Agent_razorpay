"""Policy rules.

Each rule is a single class with an `evaluate()` method that returns a
RuleResult when it has an opinion, or None when it doesn't apply to this
action. Adding a new rule means adding one class here and registering it in
`engine.default_policy_engine()` — never editing an if-chain.

Rules are pure: no DB access, no network, no LLM. They only look at the
ProposedCartState they're handed. This is what makes them unit-testable
without a running server.
"""

from abc import ABC, abstractmethod

from app.policy.types import Decision, ProposedCartState, RuleResult

# Only these tools mutate the cart; only they carry a money decision.
CART_MUTATING_TOOLS = {"add_to_cart"}


class Rule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, action: ProposedCartState) -> RuleResult | None: ...


class UnknownSkuRule(Rule):
    """Models hallucinate SKUs. Never trust one that isn't in the catalog."""

    name = "UnknownSkuRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        if action.sku is not None and action.product is None:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"SKU '{action.sku}' does not exist in the catalog. The agent may be "
                "hallucinating a product — refusing to add it to the cart.",
            )
        return None


class StockRule(Rule):
    name = "StockRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        if action.product is None or action.quantity is None:
            return None
        if action.quantity > action.product.stock:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Requested quantity {action.quantity} exceeds available stock "
                f"({action.product.stock}) for SKU '{action.sku}'.",
            )
        return None


class PerItemPriceRule(Rule):
    def __init__(self, max_price_paise: int):
        self.max_price_paise = max_price_paise

    name = "PerItemPriceRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        if action.product is None:
            return None
        if action.product.price_paise > self.max_price_paise:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Item price ₹{action.product.price_paise / 100:.2f} exceeds the "
                f"per-item limit of ₹{self.max_price_paise / 100:.2f}.",
            )
        return None


class QuantityRule(Rule):
    def __init__(self, max_quantity: int):
        self.max_quantity = max_quantity

    name = "QuantityRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        if action.quantity is None:
            return None
        if action.quantity > self.max_quantity:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Requested quantity {action.quantity} exceeds the maximum allowed "
                f"per line item ({self.max_quantity}).",
            )
        return None


class SpendCapRule(Rule):
    """The hard budget ceiling for the session.

    Uses the budget explicitly stored on the session (never inferred from
    chat text — the harness is responsible for that separation). Falls back
    to a configured default cap when the session never set one, so a session
    is never unbounded.
    """

    def __init__(self, default_cap_paise: int):
        self.default_cap_paise = default_cap_paise

    name = "SpendCapRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        cap = action.budget_paise if action.budget_paise is not None else self.default_cap_paise
        if action.proposed_cart_total_paise > cap:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"This would bring the cart total to ₹{action.proposed_cart_total_paise / 100:.2f}, "
                f"exceeding the session budget of ₹{cap / 100:.2f}.",
            )
        return None


class ConfirmationThresholdRule(Rule):
    """A soft gate: large-but-affordable purchases still get a human nod."""

    def __init__(self, threshold_paise: int):
        self.threshold_paise = threshold_paise

    name = "ConfirmationThresholdRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        if action.proposed_cart_total_paise > self.threshold_paise:
            return RuleResult(
                Decision.REQUIRE_CONFIRMATION,
                self.name,
                f"Cart total would reach ₹{action.proposed_cart_total_paise / 100:.2f}, "
                f"above the ₹{self.threshold_paise / 100:.2f} confirmation threshold. "
                "Please confirm before this is added.",
            )
        return None
