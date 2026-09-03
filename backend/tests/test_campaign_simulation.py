"""Measurement math, checked against fixed, hand-computed fixtures — no
randomness, no DB. simulate_offer_outcome (the seeded RNG path) is
exercised separately in test_campaign_integration.py; this file is purely
about whether measure_campaign()'s arithmetic is correct.
"""

from app.campaigns.simulation import OfferOutcome, measure_campaign


def _outcome(customer_id, group, price, cost, converted, paid) -> OfferOutcome:
    return OfferOutcome(
        customer_id=customer_id,
        group=group,
        product_price_paise=price,
        product_cost_paise=cost,
        converted=converted,
        paid_price_paise=paid,
    )


def test_measurement_math_on_a_balanced_fixture():
    # 4 offered (2 redeem at 8000, 20% off ₹100 list, cost ₹60), 2 blocked,
    # 4 control (1 converts organically at full price, rate=0.25).
    outcomes = [
        _outcome(1, "offered", 10_000, 6_000, True, 8_000),
        _outcome(2, "offered", 10_000, 6_000, True, 8_000),
        _outcome(3, "offered", 10_000, 6_000, False, 0),
        _outcome(4, "offered", 10_000, 6_000, False, 0),
        _outcome(5, "blocked", 10_000, 6_000, False, 0),
        _outcome(6, "blocked", 10_000, 6_000, False, 0),
        _outcome(7, "control", 10_000, 6_000, True, 10_000),
        _outcome(8, "control", 10_000, 6_000, False, 0),
        _outcome(9, "control", 10_000, 6_000, False, 0),
        _outcome(10, "control", 10_000, 6_000, False, 0),
    ]

    m = measure_campaign(outcomes, segment_size=10)

    assert m.segment_size == 10
    assert m.offers_sent == 4
    assert m.offers_blocked == 2
    assert m.control_size == 4
    assert m.redemptions == 2

    assert m.treatment_revenue_paise == 16_000  # 8000 + 8000
    assert m.control_revenue_paise == 10_000
    assert m.control_conversion_rate == 0.25

    # counterfactual: 0.25 control rate * 4 offered * ₹100 full price
    assert m.expected_baseline_revenue_paise == 10_000
    assert m.expected_baseline_cogs_paise == 6_000

    assert m.incremental_revenue_paise == 6_000  # 16000 - 10000
    assert m.discount_cost_paise == 4_000  # (10000-8000) * 2 redemptions
    assert m.treatment_cogs_paise == 12_000  # 6000 * 2 redemptions

    # treatment gross profit 16000-12000=4000; baseline gross profit 10000-6000=4000
    assert m.net_margin_impact_paise == 0


def test_revenue_lift_can_still_be_a_margin_loss():
    """The exact case the spec calls out: 'a campaign that lifts revenue
    while destroying margin is a failure and the report must be able to
    say so.' A steep discount on a thin-margin product lifts revenue but
    sells at a per-unit loss."""
    price, cost, discounted = 10_000, 8_500, 7_000  # 30% off, cost is 85% of list

    outcomes = [
        _outcome(1, "offered", price, cost, True, discounted),
        _outcome(2, "offered", price, cost, True, discounted),
        _outcome(3, "offered", price, cost, True, discounted),
        _outcome(4, "offered", price, cost, False, 0),
        _outcome(5, "control", price, cost, True, price),
        _outcome(6, "control", price, cost, True, price),
        _outcome(7, "control", price, cost, False, 0),
        _outcome(8, "control", price, cost, False, 0),
    ]

    m = measure_campaign(outcomes, segment_size=8)

    assert m.offers_sent == 4
    assert m.redemptions == 3
    assert m.control_conversion_rate == 0.5

    assert m.treatment_revenue_paise == 21_000  # 7000 * 3
    assert m.expected_baseline_revenue_paise == 20_000  # 0.5 * 4 * 10000
    assert m.incremental_revenue_paise == 1_000  # revenue DID go up...

    assert m.treatment_cogs_paise == 25_500  # 8500 * 3
    assert m.expected_baseline_cogs_paise == 17_000  # 0.5 * 4 * 8500
    # ...but margin went deeply negative: -4500 treatment profit vs +3000 baseline
    assert m.net_margin_impact_paise == -7_500


def test_measurement_with_no_control_conversions_and_no_redemptions():
    outcomes = [
        _outcome(1, "offered", 10_000, 6_000, False, 0),
        _outcome(2, "control", 10_000, 6_000, False, 0),
    ]
    m = measure_campaign(outcomes, segment_size=3)
    assert m.redemptions == 0
    assert m.control_conversion_rate == 0.0
    assert m.incremental_revenue_paise == 0
    assert m.net_margin_impact_paise == 0


def test_measurement_with_empty_control_group_does_not_divide_by_zero():
    outcomes = [_outcome(1, "offered", 10_000, 6_000, True, 8_000)]
    m = measure_campaign(outcomes, segment_size=1)
    assert m.control_size == 0
    assert m.control_conversion_rate == 0.0
    assert m.expected_baseline_revenue_paise == 0
    assert m.incremental_revenue_paise == m.treatment_revenue_paise
