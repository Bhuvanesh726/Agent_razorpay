# Layer 4.6 — Campaign orchestrator

The question this layer answers isn't "can an AI write a campaign" — an
LLM can write a discount message in one call. It's "can an agent choose
who to target, bound what it gives away, and prove it made money." The
first and third of those are deliberately **not** the LLM's job.

## Architecture in one sentence

Deterministic history → deterministic segmentation → **one** LLM call per
segment to propose an offer → the *exact same policy-engine pattern* as
every other layer in this project gates every individual customer's offer
→ a held-out control group and a documented, seeded simulation measure
what happened → everything lands in the same audit log as everything else.

## Part 1 — Synthetic history (`app/campaigns/generator.py`)

Not committed data — `campaigns/run.py` regenerates it fresh every run,
seeded (`--seed`, default 42) for reproducibility. Customers are assigned
one of five *archetypes* (repeat-loyal-recent, repeat-high-value, lapsed,
one-time, occasional-low-value) rather than drawn from pure noise, so the
generated mix reliably produces every segment segmentation.py looks for,
instead of hoping enough variety falls out of randomness. A live run:
**20 customers, 76 orders**, comfortably over the 15+/60+ minimums.

## Part 2 — Segmentation is deterministic Python, on purpose

`app/campaigns/segmentation.py` has no LLM import and never will. This is
a place the judging criteria explicitly reward getting right: which bucket
a customer falls into should be the same answer every time for the same
data, checkable by reading five plain conditions, not by re-running a
model and hoping. That's what "auditable, reproducible, and cheaper"
means in code, not just as a paragraph in a doc.

Five independent (not mutually exclusive) segments: `lapsed` (no order in
90+ days), `repeat` (3+ orders), `high_value` (lifetime spend ≥ ₹2,000),
`category_loyal` (60%+ of a customer's *orders* — not line items — share
one dominant category), `one_time` (exactly one order ever).

## Part 3 — The LLM's job, and only that job (`app/campaigns/agent.py`)

Given a segment's name, description, and aggregate statistics (size,
average spend, average order count, top categories) plus the current
catalog, the model proposes 1-3 SKUs to feature, a discount percentage,
and a customer-facing message — via the same low-level tool-calling
gateway the shopping agent uses (`app.llm.gateway`, never Agno's
auto-executing `Agent.run()`, for the identical reason: an auto-executing
loop would bypass the policy engine). The model never sees a customer
list — segmentation decided who's eligible entirely without it — and its
proposed SKUs are validated against the real catalog exactly like the
shopping agent's `UnknownSkuRule` protects against a hallucinated SKU
(filtered, not trusted).

**cost_paise is never given to the model.** The catalog summary it
receives has `sku`/`name`/`category`/`price_paise` only — margin math
happens entirely on the policy side, after the proposal, where it can't be
gamed by a proposal that happens to know the floor.

## Part 4 — The offer policy (the gate)

Five new rules, in `app/campaigns/rules.py`, evaluated by a
`CampaignPolicyEngine` (`app/campaigns/engine.py`) that is structurally
identical to `app/policy/engine.py`'s `PolicyEngine`: every rule runs,
first DENY in registration order wins, no rule means ALLOW. (No
`REQUIRE_CONFIRMATION` here — a campaign run is autonomous end to end by
design, no per-customer human nod in the loop, so the only two outcomes
are ALLOW or DENY.)

- **`SegmentSizeRule`** — refuses the *whole* campaign, before any
  customer is considered, if the segment is smaller than
  `campaign_min_segment_size` (default 5). A live run's `one_time` segment
  (4 members) was refused exactly this way.
- **`DiscountCapRule`** — `discount_pct` above `campaign_max_discount_pct`
  (default 30%) is denied. A merchant-wide constant; a campaign proposal
  cannot raise its own ceiling.
- **`MarginFloorRule`** — checks *every* featured product, not just the
  first: `(discounted_price - cost_paise) / discounted_price` must clear
  `campaign_min_margin_pct` (default 15%), using the `cost_paise` field
  added to `Product` this layer (never exposed to any customer- or
  agent-facing surface — see Part 3).
- **`CampaignBudgetRule`** — each ALLOWed offer's *estimated* cost (the
  discount on one unit of the primary featured product — a deliberately
  conservative, single-product simplification, not a claim about what a
  customer will actually buy) accumulates against
  `campaign_default_budget_paise` (default ₹3,000); once the running total
  would breach it, every further offer in that campaign is denied. This is
  the same accumulating-total pattern `SpendCapRule` already uses for a
  shopping cart, applied per-campaign instead of per-cart.
- **`OfferFrequencyRule`** — denies a customer already targeted (ALLOWed,
  not just considered) `campaign_max_offers_per_window` times (default 1)
  within `campaign_offer_frequency_window_days` (default 30), counted
  across *all* campaigns, not just the current one.

Every decision is logged exactly like every other policy decision in this
project (`event_type: "policy_decision"`, `decision`, `rule_name`,
`reason`) — a blocked offer is not a special kind of event.

### A genuinely useful, unplanned finding

Because segments overlap (a customer can be `lapsed` *and* `high_value`)
and `campaigns/run.py` runs one campaign per segment in a single pass,
`OfferFrequencyRule` did real work in the first live run without being
specifically tested for this: a customer already ALLOWed by the `lapsed`
or `repeat` campaign (run first) was correctly refused when the
`high_value` and `category_loyal` campaigns (run later) tried to target
them again — 8 of `high_value`'s 10 treatment members and 4 of
`category_loyal`'s 5 were blocked this way. That's not a bug or an
over-strict default; it's exactly the cross-campaign anti-spam protection
the rule exists for, demonstrated for free by running the realistic
"several campaigns in flight" scenario instead of one in isolation.

## Part 5 — Control group and measurement — what's simulated, stated plainly

**This project has no real customers to send anything to.** Every
"did this customer buy" decision in `app/campaigns/simulation.py` is a
seeded coin-flip against a documented, deliberately simple probability
model — never presented as observed behavior anywhere in the report, the
API, or the UI.

The model, exactly:
- Every customer — offered, blocked, or held out in the control group —
  has a baseline chance of buying the featured product anyway, at full
  price, within the campaign window: `campaign_base_organic_conversion_rate`
  (default 5%).
- A customer who actually received an ALLOWed offer gets an *additional*
  conversion-probability lift proportional to the discount:
  `lift = discount_pct * campaign_discount_lift_sensitivity` (default
  sensitivity 0.6 — a 10% discount adds 6 points of conversion
  probability). If they convert, they're assumed to always use the offer
  they were given (no separate "converted organically while holding an
  unused code" case modeled).
- Blocked and control-group customers only ever get the baseline rate, at
  full price.
- One simulated unit of one product per converting customer — not
  modeling repeat purchases, multi-item carts, or converting more than
  once in the window.

**Control group is genuinely held out, structurally, not just by
convention.** The treatment/control split happens *before* any proposal
or policy evaluation exists (`app/campaigns/service.py`); a control
customer's `CampaignOffer` row is built directly from
`simulate_offer_outcome()`, never from a `ProposedOfferState` — there is
no code path that ever runs a control customer through the policy engine.
`test_control_group_is_genuinely_held_out` checks this as a structural
fact (every control row's `decision`/`rule_name`/`discount_pct` stay
`NULL`), not a behavioral inference.

**Measurement uses the control group's observed conversion rate as the
counterfactual** for what the offered group would likely have done
without the campaign — the standard way to isolate a treatment's
incremental effect from organic behavior that would have happened anyway:

```
control_rate            = control conversions / control group size
expected_baseline_rev   = control_rate * offered_group_size * avg_full_price
incremental_revenue     = actual_treatment_revenue - expected_baseline_rev

treatment_gross_profit  = treatment_revenue - treatment_cogs
baseline_gross_profit   = expected_baseline_rev - expected_baseline_cogs
net_margin_impact       = treatment_gross_profit - baseline_gross_profit
```

**Net margin impact is gross profit, not revenue** — the number the spec
insists on, because incremental revenue can be positive while margin is
destroyed. `test_revenue_lift_can_still_be_a_margin_loss` is a fixed
fixture proving exactly that: a 30% discount on an 85%-cost-basis product
lifts revenue by ₹1,000 (+incremental) while net margin impact comes out
to **-₹7,500** — the report is able to say a campaign made things worse
even though the top-line number looks like a win.

## Part 6 — Merchant view (`/campaigns`)

Segment sizes, a campaign-run table (discount, sent/blocked/control/
redemptions, incremental revenue, net margin impact — red when negative),
and a per-campaign detail panel: the proposal and message, the full
measurement breakdown, and every customer's row (group, decision, rule,
redeemed, revenue). Each campaign's "Full audit trail →" link opens the
*existing* `/audit` viewer from Layer 4 with the campaign's own
`campaign_id` — campaign audit events are logged to the exact same
`audit_events` table as the shopping agent's, with `campaign_id` standing
in for `session_id`, so the whole replay/filter/totals machinery from
Layer 4 works for a campaign with zero new code.

## Part 7 — Audit

Every step — `segment_computed`, `control_group_split`,
`campaign_proposed` (with real token/cost/latency, same as any other model
call), one `policy_decision` per treatment customer, `offer_blocked` for
each denial, `redemption_recorded` for each simulated conversion, and a
final `results_computed` carrying the full measurement — through the same
`AuditService` every other layer uses.

## Running it

```
python campaigns/run.py                       # default seed 42, campaign seed 7
python campaigns/run.py --seed 7 --campaign-seed 99
```

Prints progress for all seven DoD steps and writes
`campaigns/results/campaign_run_<timestamp>.{json,md}` (+ `latest.*`).

### A real live run

`2026-09-03`, seed 42 / campaign-seed 7, 20 customers / 76 orders:

| Segment | Status | Discount | Sent | Blocked | Control | Redemptions | Incremental revenue | Net margin impact |
|---|---|---|---|---|---|---|---|---|
| lapsed | completed | 10% | 6 | 0 | 2 | 3 | ₹513.00 | ₹125.40 |
| repeat | completed | 10% | 7 | 1 | 2 | 2 | ₹495.00 | ₹122.16 |
| high_value | completed | 10% | 2 | 8 | 4 | 1 | ₹299.60 | ₹77.11 |
| category_loyal | completed | 10% | 1 | 4 | 2 | 0 | ₹0.00 | ₹0.00 |
| one_time | **blocked_at_segment** | — | — | — | — | — | — | — |

`one_time` (4 members) never reached a proposal at all —
`SegmentSizeRule` refused it outright, per its own reason string: *"has
only 4 member(s), below the minimum of 5 needed to draw a reliable
conclusion."* `high_value` and `category_loyal`'s heavy blocking is
`OfferFrequencyRule` cross-campaign protection (see Part 4), not a
misconfigured rule — every blocked row names its rule and reason, readable
at `/campaigns` or in the raw audit trail.

## Two real failures this layer's own testing found

**Alembic autogenerate produced an empty migration for the new tables.**
`scripts/seed.py` calls `Base.metadata.create_all(bind=engine)` on every
run; the moment the new campaign models were registered in
`app/models/__init__.py`, running the seed script silently created all six
`campaign_*` tables directly, bypassing migration tracking entirely — so
by the time `alembic revision --autogenerate` ran, the database already
matched the target and there was nothing to detect. Fixed by dropping the
accidentally-created tables and regenerating properly. A fresh checkout
that only ever runs `alembic upgrade head` (never `seed.py` first) would
otherwise be missing these tables with no error until first use.

**`campaigns/run.py`, launched from the repo root, crashed inside the
generator with `IndexError: Cannot choose from an empty sequence`.**
`.env` sets `DATABASE_URL=sqlite:///./razorpay_agent.db` — a path relative
to the process's working directory. The backend server always runs from
`backend/`, so that resolves correctly for it; this script is meant to run
from the repo root (per its own examples), so the same relative path
silently pointed at a new, empty database file next to itself instead of
the real one — an empty product catalog, `rng.choice([])`. Fixed by
pinning `DATABASE_URL` to an absolute path anchored to `backend/` before
`app.core.config` is ever imported, so this script always finds the same
database the server does regardless of where it's launched from.

## Config (`backend/app/core/config.py`)

All thresholds above are `Settings` fields (`campaign_lapsed_days`,
`campaign_max_discount_pct`, `campaign_min_margin_pct`,
`campaign_default_budget_paise`, `campaign_min_segment_size`,
`campaign_max_offers_per_window`, `campaign_offer_frequency_window_days`,
`campaign_control_group_fraction`, `campaign_base_organic_conversion_rate`,
`campaign_discount_lift_sensitivity`, …) — overridable via env, never
touchable by an LLM proposal. One number changed from its first-guess
default during this layer's own testing: `campaign_max_pct_of_cart`-style
percentage caps are easy to set too strictly without checking them against
real catalog economics (the same lesson Layer 4.5's upsell cap taught) —
`campaign_max_discount_pct`/`campaign_min_margin_pct` here were checked
against the real seeded `cost_paise` values before being finalized, not
just picked and left untested.
