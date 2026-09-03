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

from app.policy.types import CatalogProductSnapshot, Decision, ProposedCartState, RuleResult

# Only these tools mutate the cart; only they carry a money decision.
CART_MUTATING_TOOLS = {"add_to_cart"}
PAYMENT_TOOLS = {"initiate_payment"}
# An upsell offer is never itself a mutation (nothing is added until the user
# accepts, which is a real add_to_cart call) — but a *candidate* offer must
# clear every safety check a real add would, or "no special path" is a lie.
# PRICE_CHECKED_TOOLS is what the item-level DENY rules key off of, so the
# exact same StockRule/PerItemPriceRule/QuantityRule/SpendCapRule instances
# gate a proposed upsell too. ConfirmationThresholdRule deliberately keeps
# checking CART_MUTATING_TOOLS only — a mere suggestion never demands a
# confirmation prompt; the real add (on accept) will, if it's still due one.
UPSELL_PROPOSE_TOOLS = {"propose_upsell"}
PRICE_CHECKED_TOOLS = CART_MUTATING_TOOLS | UPSELL_PROPOSE_TOOLS


class Rule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, action: ProposedCartState) -> RuleResult | None: ...


class UnknownSkuRule(Rule):
    """Models hallucinate SKUs. Never trust one that isn't in the catalog."""

    name = "UnknownSkuRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in PRICE_CHECKED_TOOLS:
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
        if action.tool_name not in PRICE_CHECKED_TOOLS:
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
        if action.tool_name not in PRICE_CHECKED_TOOLS:
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
        if action.tool_name not in PRICE_CHECKED_TOOLS:
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
        if action.tool_name not in PRICE_CHECKED_TOOLS:
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


class DuplicatePaymentRule(Rule):
    """DENY if an order for this exact idempotency key already reached PAID.

    The caller (harness) resolves `existing_order_status` by looking up the
    order for the cart's current idempotency key *before* policy evaluation
    — this rule only reads the result, never queries anything itself.
    """

    name = "DuplicatePaymentRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in PAYMENT_TOOLS:
            return None
        if action.existing_order_status == "PAID":
            return RuleResult(
                Decision.DENY,
                self.name,
                "An order for this exact cart has already been paid. "
                "This looks like a duplicate payment attempt — refusing to charge again.",
            )
        return None


class PaymentAuthorizationRule(Rule):
    """Payment is only permitted for a cart that still passes every other
    rule, checked again right now — not five minutes ago when the items were
    added. Composes the existing item-level rules rather than duplicating
    their thresholds, by replaying each cart line through them as if it were
    being freshly added.

    Never returns ALLOW: a cart that re-validates cleanly still requires a
    human's explicit confirmation before any money moves. This is what makes
    "the agent can never complete a payment on its own" true at the policy
    layer, not just by convention in the harness.
    """

    def __init__(self, item_rules: list[Rule]):
        self.item_rules = item_rules

    name = "PaymentAuthorizationRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in PAYMENT_TOOLS:
            return None

        if not action.cart_line_items:
            return RuleResult(Decision.DENY, self.name, "Cart is empty — nothing to pay for.")

        running_total = 0
        for line in action.cart_line_items:
            item_action = ProposedCartState(
                session_id=action.session_id,
                user_id=action.user_id,
                tool_name="add_to_cart",
                budget_paise=action.budget_paise,
                current_cart_total_paise=running_total,
                sku=line.product.sku,
                quantity=line.quantity,
                product=CatalogProductSnapshot(
                    sku=line.product.sku, price_paise=line.product.price_paise, stock=line.product.stock
                ),
                # Propagated from the outer initiate_payment action so an
                # agent-initiated payment re-validates revocation/scope/limit
                # too, not just price/stock/quantity/budget.
                acting_agent_credential_id=action.acting_agent_credential_id,
                agent_credential_status=action.agent_credential_status,
                agent_scopes=action.agent_scopes,
                agent_spend_limit_paise=action.agent_spend_limit_paise,
                agent_spent_paise=action.agent_spent_paise,
            )
            for rule in self.item_rules:
                result = rule.evaluate(item_action)
                if result is not None and result.decision == Decision.DENY:
                    # Surface the actual failing rule's name, not this
                    # wrapper's — "SpendCapRule" in the audit trail is more
                    # actionable than "PaymentAuthorizationRule" for every
                    # possible underlying reason.
                    return RuleResult(
                        Decision.DENY,
                        result.rule_name,
                        f"Payment re-validation failed on SKU '{line.product.sku}': {result.reason}",
                    )
            running_total += line.product.price_paise * line.quantity

        return RuleResult(
            Decision.REQUIRE_CONFIRMATION,
            self.name,
            f"Cart re-validated: {len(action.cart_line_items)} item(s), total "
            f"₹{running_total / 100:.2f}. Confirm to proceed to payment.",
        )


class UpsellPolicyRule(Rule):
    """Bounds the upsell agent specifically — separate from (and in addition
    to) the item-level rules above, which already gate a proposed upsell's
    price/stock/quantity/spend-cap exactly like a real add (see
    PRICE_CHECKED_TOOLS). This rule adds the constraints that only make sense
    for an *offer*, not a purchase: how many times this session gets asked,
    how big an ask is reasonable relative to what's already in the cart, and
    never re-asking about something already turned down.
    """

    def __init__(self, max_per_session: int, max_pct_of_original_cart: float):
        self.max_per_session = max_per_session
        self.max_pct_of_original_cart = max_pct_of_original_cart

    name = "UpsellPolicyRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.tool_name not in UPSELL_PROPOSE_TOOLS:
            return None

        if action.sku is not None and action.sku in (action.upsell_declined_skus or frozenset()):
            return RuleResult(
                Decision.DENY,
                self.name,
                f"SKU '{action.sku}' was already declined earlier this session — not proposing it again.",
            )

        if (action.upsell_proposed_count or 0) >= self.max_per_session:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Already proposed the maximum of {self.max_per_session} upsell(s) allowed this session.",
            )

        original = action.upsell_original_cart_total_paise
        if original and action.line_total_paise is not None:
            limit_paise = original * self.max_pct_of_original_cart
            if action.line_total_paise > limit_paise:
                return RuleResult(
                    Decision.DENY,
                    self.name,
                    f"Upsell price ₹{action.line_total_paise / 100:.2f} exceeds "
                    f"{self.max_pct_of_original_cart * 100:.0f}% of the original cart value "
                    f"(₹{original / 100:.2f}, limit ₹{limit_paise / 100:.2f}).",
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


# --- Layer 4.7: agent-only rules ------------------------------------------
#
# All three read only fields the harness resolves fresh every turn from the
# live AgentCredential row (never cached across turns — see
# policy/types.py's ProposedCartState docstring) and are no-ops (return
# None) whenever acting_agent_credential_id is unset, i.e. for every human
# buyer action. Registered first in default_policy_engine(), ahead of
# every item-level rule, so a revoked or out-of-scope agent is refused
# before its cart math is even considered.


class RevokedCredentialRule(Rule):
    """Applies to every tool, not just money-moving ones — a revoked agent
    can't even browse. "Denied immediately, mid-session if necessary" is
    true here specifically because credential_status is read fresh from the
    DB every turn, not from anything decided when the session started."""

    name = "RevokedCredentialRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.acting_agent_credential_id is None:
            return None
        if action.agent_credential_status == "REVOKED":
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Credential '{action.acting_agent_credential_id}' has been revoked — no further actions are permitted.",
            )
        return None


class AgentScopeRule(Rule):
    """Also applies to every tool — an agent scoped to browsing only should
    never reach add_to_cart, regardless of budget or margin."""

    name = "AgentScopeRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.acting_agent_credential_id is None or action.agent_scopes is None:
            return None
        if action.tool_name not in action.agent_scopes:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Credential '{action.acting_agent_credential_id}' is not scoped to call '{action.tool_name}' "
                f"(allowed: {sorted(action.agent_scopes)}).",
            )
        return None


class AgentSpendLimitRule(Rule):
    """Independent of — and composed with, not instead of — SpendCapRule's
    session budget: the stricter of the two wins simply because both are
    registered and DENY beats ALLOW in the same engine, no special-casing
    needed. Checked at add-to-cart time against a *projected* total
    (already-spent + this session's running cart + this proposed line),
    the same "check before it happens" shape SpendCapRule already uses —
    not against a completed payment, so an agent's limit reserves headroom
    the moment items are added, not only once they're actually paid for.
    Known simplification: removing an item does not currently release the
    reservation — see docs/047-principals.md.
    """

    name = "AgentSpendLimitRule"

    def evaluate(self, action: ProposedCartState) -> RuleResult | None:
        if action.acting_agent_credential_id is None or action.agent_spend_limit_paise is None:
            return None
        if action.tool_name not in CART_MUTATING_TOOLS:
            return None
        projected = (action.agent_spent_paise or 0) + action.proposed_cart_total_paise
        if projected > action.agent_spend_limit_paise:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"This would bring credential '{action.acting_agent_credential_id}''s total spend to "
                f"₹{projected / 100:.2f}, exceeding its ₹{action.agent_spend_limit_paise / 100:.2f} limit — "
                "independent of the session budget.",
            )
        return None
