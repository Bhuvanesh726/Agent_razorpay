from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class FeaturedProductSnapshot:
    """What a campaign rule is allowed to know about a featured product —
    deliberately not the SQLAlchemy model, same reasoning as
    policy/types.py's CatalogProductSnapshot: rules stay importable and
    testable with zero DB dependency."""

    sku: str
    price_paise: int
    cost_paise: int

    def discounted_price_paise(self, discount_pct: float) -> int:
        return round(self.price_paise * (1 - discount_pct))


@dataclass(frozen=True)
class ProposedOfferState:
    """One customer's candidate offer within a campaign — the campaign
    equivalent of ProposedCartState. Evaluated once per customer in the
    campaign's treatment group; a control-group customer never has one of
    these built at all (see app/campaigns/service.py).

    campaign_budget_paise, customer_recent_offer_count,
    max_offers_per_window, and min_segment_size are all resolved once by
    the service layer from settings/history *before* evaluation — never
    something the LLM's proposal can influence. Only discount_pct and
    featured_products come from the proposal.
    """

    campaign_id: str
    segment_name: str
    segment_size: int
    min_segment_size: int
    customer_id: int
    customer_key: str
    discount_pct: float
    featured_products: tuple[FeaturedProductSnapshot, ...]
    campaign_budget_paise: int
    committed_spend_paise: int  # sum of estimated cost of every offer ALLOWED so far this campaign
    customer_recent_offer_count: int
    max_offers_per_window: int

    @property
    def primary_product(self) -> FeaturedProductSnapshot:
        return self.featured_products[0]

    @property
    def estimated_discount_cost_paise(self) -> int:
        """Conservative, single-unit, primary-product cost used only to
        reserve budget headroom — assumes this customer redeems for one
        unit of the first featured product. Deliberately not trying to
        model "might buy several of several products"; see docs/046-campaigns.md."""
        p = self.primary_product
        return p.price_paise - p.discounted_price_paise(self.discount_pct)


@dataclass(frozen=True)
class RuleResult:
    decision: Decision
    rule_name: str
    reason: str
