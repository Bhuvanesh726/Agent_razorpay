from app.core.config import settings
from app.policy.rules import (
    ConfirmationThresholdRule,
    PerItemPriceRule,
    QuantityRule,
    Rule,
    SpendCapRule,
    StockRule,
    UnknownSkuRule,
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
    return PolicyEngine(
        rules=[
            UnknownSkuRule(),
            StockRule(),
            PerItemPriceRule(settings.policy_per_item_max_paise),
            QuantityRule(settings.policy_quantity_max),
            SpendCapRule(settings.policy_default_spend_cap_paise),
            ConfirmationThresholdRule(settings.policy_confirmation_threshold_paise),
        ]
    )
