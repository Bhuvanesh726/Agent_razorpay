"""Campaign offer policy rules — same pattern as app/policy/rules.py: each
rule is a class with an evaluate() that returns a RuleResult when it
objects, or None when it doesn't apply. Pure: no DB, no network, no LLM —
unit-testable with plain dataclasses, exactly like the shopping rules.

DiscountCapRule and MarginFloorRule are genuine merchant-wide policy
constants, configured once (from settings) and never touchable by anything
downstream of the LLM's proposal. CampaignBudgetRule, OfferFrequencyRule,
and SegmentSizeRule instead read pre-resolved fields off the action itself
— campaign_budget_paise, customer_recent_offer_count, etc. are computed by
the service layer from settings and real offer history *before* the LLM's
proposal is evaluated, so the proposal has no way to influence its own
budget or frequency ceiling.
"""

from abc import ABC, abstractmethod

from app.campaigns.types import Decision, ProposedOfferState, RuleResult


class CampaignRule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, action: ProposedOfferState) -> RuleResult | None: ...


class SegmentSizeRule(CampaignRule):
    """Refuses the whole campaign, not a single offer — checked once before
    any customer is ever considered (see service.py). Kept as a normal rule
    anyway, evaluated against a placeholder per-customer action, so a
    blocked campaign is audited through the exact same
    policy_decision/DENY pipeline as everything else — no special path for
    "the campaign itself" versus "one customer's offer"."""

    name = "SegmentSizeRule"

    def evaluate(self, action: ProposedOfferState) -> RuleResult | None:
        if action.segment_size < action.min_segment_size:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Segment '{action.segment_name}' has only {action.segment_size} member(s), below the "
                f"minimum of {action.min_segment_size} needed to draw a reliable conclusion from the result.",
            )
        return None


class DiscountCapRule(CampaignRule):
    def __init__(self, max_discount_pct: float):
        self.max_discount_pct = max_discount_pct

    name = "DiscountCapRule"

    def evaluate(self, action: ProposedOfferState) -> RuleResult | None:
        if action.discount_pct > self.max_discount_pct:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Proposed discount {action.discount_pct * 100:.0f}% exceeds the maximum allowed "
                f"{self.max_discount_pct * 100:.0f}%.",
            )
        return None


class MarginFloorRule(CampaignRule):
    """Checks every featured product, not just the primary one — a
    campaign that discounts three products should never be allowed to sell
    even one of them below the floor, regardless of which one the budget
    math treats as "primary"."""

    def __init__(self, min_margin_pct: float):
        self.min_margin_pct = min_margin_pct

    name = "MarginFloorRule"

    def evaluate(self, action: ProposedOfferState) -> RuleResult | None:
        for product in action.featured_products:
            discounted = product.discounted_price_paise(action.discount_pct)
            if discounted <= 0:
                return RuleResult(
                    Decision.DENY,
                    self.name,
                    f"SKU '{product.sku}': a {action.discount_pct * 100:.0f}% discount on "
                    f"₹{product.price_paise / 100:.2f} leaves a non-positive price.",
                )
            margin = (discounted - product.cost_paise) / discounted
            if margin < self.min_margin_pct:
                return RuleResult(
                    Decision.DENY,
                    self.name,
                    f"SKU '{product.sku}': discounted price ₹{discounted / 100:.2f} (cost ₹{product.cost_paise / 100:.2f}) "
                    f"leaves a {margin * 100:.1f}% margin, below the {self.min_margin_pct * 100:.0f}% floor.",
                )
        return None


class CampaignBudgetRule(CampaignRule):
    name = "CampaignBudgetRule"

    def evaluate(self, action: ProposedOfferState) -> RuleResult | None:
        projected = action.committed_spend_paise + action.estimated_discount_cost_paise
        if projected > action.campaign_budget_paise:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"This offer's estimated cost (₹{action.estimated_discount_cost_paise / 100:.2f}) would bring "
                f"committed campaign spend to ₹{projected / 100:.2f}, exceeding the "
                f"₹{action.campaign_budget_paise / 100:.2f} campaign budget.",
            )
        return None


class OfferFrequencyRule(CampaignRule):
    name = "OfferFrequencyRule"

    def evaluate(self, action: ProposedOfferState) -> RuleResult | None:
        if action.customer_recent_offer_count >= action.max_offers_per_window:
            return RuleResult(
                Decision.DENY,
                self.name,
                f"Customer '{action.customer_key}' has already been targeted "
                f"{action.customer_recent_offer_count} time(s) within the lookback window "
                f"(max {action.max_offers_per_window}).",
            )
        return None
