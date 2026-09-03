"""Simulated redemption + control-group measurement.

Nothing in this file is observed behavior. This project has no real
customers to actually send a campaign to, so every "did this customer buy"
decision is a seeded coin-flip against a documented, deliberately simple
probability model — never presented as measured behavior anywhere in the
report or the UI. See docs/046-campaigns.md for the full writeup.

Model (two free parameters, both in Settings, both named for what they are):
  - Every customer — offered the campaign, blocked from it, or held out in
    the control group — has a baseline chance of buying the featured
    product anyway within the campaign window, at full price:
    campaign_base_organic_conversion_rate.
  - A customer who actually received an ALLOWED offer gets an ADDITIONAL
    conversion-probability lift proportional to the discount's size:
    lift = discount_pct * campaign_discount_lift_sensitivity, and if they
    convert, they pay the discounted price (assumed to always use the
    offer they were given, rather than separately modeling "converted
    organically while holding an unused offer").
  - Blocked and control-group customers only ever get the baseline rate,
    always at full price — nothing was ever extended to them.
  - One simulated unit of one product per converting customer. Not
    modeling repeat purchases, multi-item carts, or a customer converting
    more than once within the campaign window.

Measurement then uses the control group's *observed* conversion rate as
the counterfactual for what the offered group would have done without the
campaign — the standard "control rate x group size" baseline for isolating
a treatment's incremental effect from organic behavior that would have
happened anyway.
"""

import random
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class OfferOutcome:
    """One customer's simulated result. group is "offered" (received an
    ALLOWED offer), "blocked" (policy denied their offer), or "control"
    (held out — no offer was ever evaluated for them)."""

    customer_id: int
    group: str
    product_price_paise: int
    product_cost_paise: int
    converted: bool
    paid_price_paise: int  # discounted price if redeemed, full price if organic, 0 if not converted

    @property
    def redeemed(self) -> bool:
        return self.group == "offered" and self.converted

    @property
    def revenue_paise(self) -> int:
        return self.paid_price_paise if self.converted else 0

    @property
    def cogs_paise(self) -> int:
        return self.product_cost_paise if self.converted else 0

    @property
    def discount_given_paise(self) -> int:
        return (self.product_price_paise - self.paid_price_paise) if self.redeemed else 0


def simulate_offer_outcome(
    rng: random.Random, *, customer_id: int, group: str, product_price_paise: int, product_cost_paise: int, discount_pct: float
) -> OfferOutcome:
    base_rate = settings.campaign_base_organic_conversion_rate
    if group == "offered":
        conversion_prob = min(1.0, base_rate + discount_pct * settings.campaign_discount_lift_sensitivity)
        paid_price = round(product_price_paise * (1 - discount_pct))
    else:
        conversion_prob = base_rate
        paid_price = product_price_paise

    converted = rng.random() < conversion_prob
    return OfferOutcome(
        customer_id=customer_id,
        group=group,
        product_price_paise=product_price_paise,
        product_cost_paise=product_cost_paise,
        converted=converted,
        paid_price_paise=paid_price if converted else 0,
    )


@dataclass(frozen=True)
class CampaignMeasurement:
    segment_size: int
    offers_sent: int
    offers_blocked: int
    control_size: int
    redemptions: int
    treatment_revenue_paise: int
    control_revenue_paise: int
    control_conversion_rate: float
    expected_baseline_revenue_paise: int  # counterfactual: what the offered group likely would have made anyway
    incremental_revenue_paise: int
    discount_cost_paise: int
    treatment_cogs_paise: int
    expected_baseline_cogs_paise: int
    net_margin_impact_paise: int  # incremental GROSS PROFIT, not incremental revenue — see module docstring


def measure_campaign(outcomes: list[OfferOutcome], *, segment_size: int) -> CampaignMeasurement:
    offered = [o for o in outcomes if o.group == "offered"]
    blocked_count = sum(1 for o in outcomes if o.group == "blocked")
    control = [o for o in outcomes if o.group == "control"]

    redemptions = [o for o in offered if o.redeemed]
    control_conversions = [o for o in control if o.converted]

    treatment_revenue = sum(o.revenue_paise for o in offered)
    control_revenue = sum(o.revenue_paise for o in control)
    control_rate = (len(control_conversions) / len(control)) if control else 0.0

    avg_full_price_offered = (sum(o.product_price_paise for o in offered) / len(offered)) if offered else 0.0
    avg_cost_offered = (sum(o.product_cost_paise for o in offered) / len(offered)) if offered else 0.0

    expected_baseline_revenue = round(control_rate * len(offered) * avg_full_price_offered)
    expected_baseline_cogs = round(control_rate * len(offered) * avg_cost_offered)

    discount_cost = sum(o.discount_given_paise for o in offered)
    treatment_cogs = sum(o.cogs_paise for o in offered)

    incremental_revenue = treatment_revenue - expected_baseline_revenue
    treatment_gross_profit = treatment_revenue - treatment_cogs
    expected_baseline_gross_profit = expected_baseline_revenue - expected_baseline_cogs
    net_margin_impact = treatment_gross_profit - expected_baseline_gross_profit

    return CampaignMeasurement(
        segment_size=segment_size,
        offers_sent=len(offered),
        offers_blocked=blocked_count,
        control_size=len(control),
        redemptions=len(redemptions),
        treatment_revenue_paise=treatment_revenue,
        control_revenue_paise=control_revenue,
        control_conversion_rate=control_rate,
        expected_baseline_revenue_paise=expected_baseline_revenue,
        incremental_revenue_paise=incremental_revenue,
        discount_cost_paise=discount_cost,
        treatment_cogs_paise=treatment_cogs,
        expected_baseline_cogs_paise=expected_baseline_cogs,
        net_margin_impact_paise=net_margin_impact,
    )
