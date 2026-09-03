from app.core.config import settings
from app.policy.rules import (
    AgentScopeRule,
    AgentSpendLimitRule,
    ConfirmationThresholdRule,
    DuplicatePaymentRule,
    PaymentAuthorizationRule,
    PerItemPriceRule,
    QuantityRule,
    RevokedCredentialRule,
    Rule,
    SpendCapRule,
    StockRule,
    UnknownSkuRule,
    UpsellPolicyRule,
)
from app.policy.types import Decision, ProposedCartState, RuleResult

_DEFAULT_ALLOW_REASON = "No policy rule objected."


class PolicyEngine:
    """Evaluates a proposed cart state against every registered rule.

    DENY beats REQUIRE_CONFIRMATION beats ALLOW. Within DENY (or within
    REQUIRE_CONFIRMATION), the first matching rule in registration order
    wins — so rule order encodes priority (catalog/safety checks before
    softer confirmation gates).
    """

    def __init__(self, rules: list[Rule]):
        self.rules = rules

    def evaluate(self, action: ProposedCartState) -> RuleResult:
        results = [r.evaluate(action) for r in self.rules]
        results = [r for r in results if r is not None]

        for decision in (Decision.DENY, Decision.REQUIRE_CONFIRMATION):
            for result in results:
                if result.decision == decision:
                    return result

        return RuleResult(Decision.ALLOW, "__default__", _DEFAULT_ALLOW_REASON)


def default_policy_engine() -> PolicyEngine:
    unknown_sku = UnknownSkuRule()
    stock = StockRule()
    per_item_price = PerItemPriceRule(settings.policy_per_item_max_paise)
    quantity = QuantityRule(settings.policy_quantity_max)
    spend_cap = SpendCapRule(settings.policy_default_spend_cap_paise)
    agent_spend_limit = AgentSpendLimitRule()

    return PolicyEngine(
        rules=[
            # Agent-only, no-ops for a human buyer (see policy/rules.py) —
            # registered first so a revoked or out-of-scope agent is
            # refused before its cart math is ever considered.
            RevokedCredentialRule(),
            AgentScopeRule(),
            unknown_sku,
            stock,
            per_item_price,
            quantity,
            spend_cap,
            agent_spend_limit,
            # Upsell-specific constraints, evaluated only for a synthesized
            # propose_upsell action — the item-level rules above already gate
            # its price/stock/quantity/spend-cap exactly like a real add.
            UpsellPolicyRule(settings.policy_upsell_max_per_session, settings.policy_upsell_max_pct_of_cart),
            ConfirmationThresholdRule(settings.policy_confirmation_threshold_paise),
            DuplicatePaymentRule(),
            # Re-validates the whole cart through the same DENY-capable item
            # rules above — one set of thresholds, no duplicated logic. Not
            # UpsellPolicyRule: by payment time an accepted upsell is just an
            # ordinary cart line, no different from anything else in it.
            # RevokedCredentialRule/AgentScopeRule/AgentSpendLimitRule ARE
            # included — an agent revoked between adding items and
            # confirming payment must be caught here too.
            PaymentAuthorizationRule(
                item_rules=[
                    RevokedCredentialRule(),
                    AgentScopeRule(),
                    unknown_sku,
                    stock,
                    per_item_price,
                    quantity,
                    spend_cap,
                    agent_spend_limit,
                ]
            ),
        ]
    )
