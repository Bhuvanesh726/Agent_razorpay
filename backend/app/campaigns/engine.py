from app.campaigns.rules import (
    CampaignBudgetRule,
    CampaignRule,
    DiscountCapRule,
    MarginFloorRule,
    OfferFrequencyRule,
    SegmentSizeRule,
)
from app.campaigns.types import Decision, ProposedOfferState, RuleResult
from app.core.config import settings

_DEFAULT_ALLOW_REASON = "No policy rule objected."


class CampaignPolicyEngine:
    """Same pattern as app/policy/engine.py's PolicyEngine: evaluate every
    rule, DENY beats ALLOW, first DENY in registration order wins. No
    REQUIRE_CONFIRMATION here — a campaign run is autonomous end to end by
    design (no per-customer human-in-the-loop step), so the only two
    outcomes for an offer are ALLOW or DENY."""

    def __init__(self, rules: list[CampaignRule]):
        self.rules = rules

    def evaluate(self, action: ProposedOfferState) -> RuleResult:
        for rule in self.rules:
            result = rule.evaluate(action)
            if result is not None and result.decision == Decision.DENY:
                return result
        return RuleResult(Decision.ALLOW, "__default__", _DEFAULT_ALLOW_REASON)


def default_campaign_policy_engine() -> CampaignPolicyEngine:
    return CampaignPolicyEngine(
        rules=[
            SegmentSizeRule(),
            DiscountCapRule(settings.campaign_max_discount_pct),
            MarginFloorRule(settings.campaign_min_margin_pct),
            CampaignBudgetRule(),
            OfferFrequencyRule(),
        ]
    )
