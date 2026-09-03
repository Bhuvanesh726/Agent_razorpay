# Layer 4.6b — Browse abandonment segment

An addition to Layer 4.6's campaign orchestrator, not a new subsystem. It
reuses `CampaignPolicyEngine`, the existing audit path (`campaign_id` as
`session_id`, same `audit_events` table), the existing control-group split,
and the existing `measure_campaign()` unchanged. The only genuinely new
pieces are one table (`product_views`), one segment function, and a
per-customer personalization of *which product* an offer targets.

## Why this one is different

The other five segments are historical — they look at what a customer
already bought. This one is behavioral: it catches intent *in progress*.
Someone who opened the same product page four times this week and never
bought it is closer to a purchase than any lapsed buyer, and no order
history would ever surface that.

## Part 1 — Tracking views

`product_views` (`sku`, `user_id`, `session_id`, `viewed_at`, `request_id`)
has two producers sharing one table:

- **The real frontend** — `POST /api/products/{sku}/view`, fired from a new
  `ProductDetailModal` (there was no product-detail view in this app before
  this layer; clicking a product card in the grid now opens one) whenever a
  detail is opened. `user_id` here is always the single hardcoded demo
  shopper (`settings.default_user_id`).
- **The synthetic generator** — `app/campaigns/generator.py` layers
  realistic view patterns on top of the purchase history it already builds,
  covering every case segmentation needs to distinguish: genuinely
  abandoned (repeated, recent, never bought), viewed-then-bought-anyway
  (must be excluded), too few views (below threshold), and stale views
  (right count, wrong window). `user_id` here is a synthetic
  `Customer.customer_key` (e.g. `"CUST-007"`).

Since `browse_abandonment` segmentation only ever matches a `user_id`
against a synthetic `Customer.customer_key`, the real shop's views (always
`"user_demo"`) are harmlessly ignored by the campaign math while still
proving the logging path itself works, live.

**Cheap and non-blocking, by construction, not just by intent.**
`campaign_service.log_product_view()` wraps its write in a bare
`try`/`except`, rolls back and logs on failure, and never raises — the
router endpoint always returns `204` regardless. No catalog lookup happens
before the write either (that read would cost more than the write); an
invalid SKU is just inert data, never an error. `test_a_failed_write_does_not_raise`
proves this by making the commit itself throw and asserting nothing
propagates.

## Part 2 — The segment (deterministic, as always)

`compute_browse_abandonment_segment(db, as_of, min_views=3, window_days=7)`:
same SKU viewed 3+ times in the last 7 days (both configurable), and no
purchase of that SKU, ever. A customer can qualify with **zero lifetime
orders** — pure browsing is the entire signal — which the other five
segments' `build_customer_profiles()` doesn't handle (it only builds a
profile from order history), so this segment uses a small variant,
`build_customer_profiles_including_zero_orders()`, that fills in a
zero-valued profile for a browse-only customer instead of silently
dropping them.

A customer with multiple qualifying SKUs is assigned only the most-viewed
one — one row per customer, same shape as every other segment, rather than
creating parallel campaign entries for the same person.

## Part 3 — The offer: small, fixed, and personalized

Discount is `campaign_browse_abandonment_discount_pct` (default **2%**) —
config, never LLM-proposed. **The offer skips the LLM call entirely**,
honestly: `CampaignProposal.model_used` literally reads `"none
(deterministic browse-abandonment offer)"` and every token/cost/latency
field is `0`, rather than faking a model call that didn't happen. There's
no judgment to exercise here that an LLM call would add: the *product* is
whatever this specific customer already told us they're circling (their
own repeated views picked it, not a segment-wide choice), and the
*discount* is deliberately small — a nudge for someone already close to
buying, not persuasion for someone who needs convincing. A bigger discount
here would give away margin on a sale that was likely to happen anyway.

**Personalization without a parallel pipeline.** The other five segments
share one featured-product list for the whole campaign; this one needs a
different product per customer. `service.py` handles both with a single
`_member_featured_products()` helper: if a segment member carries a
`target_sku` (only ever true for `browse_abandonment` — see
`CustomerProfile.target_sku` in `segmentation.py`), that customer's own
product is used; otherwise the campaign's shared list is used, unchanged
from Layer 4.6. One `run_campaign()` body, one policy loop, one
measurement call — not two pipelines. `CampaignOffer` gained one nullable
column, `sku`, to record which product each row was actually about (always
populated now, for every segment, not just this one).

Runs through the unmodified `CampaignPolicyEngine` — `DiscountCapRule`,
`MarginFloorRule`, `CampaignBudgetRule`, `OfferFrequencyRule`,
`SegmentSizeRule` — no special path. `test_default_2pct_discount_clears_policy`
and `test_configuring_a_larger_discount_is_blocked_by_discount_cap_rule`
prove both directions: the real default sails through, and a
config-inflated discount (tested at 50% against a 30% cap) is denied by
name like any other offer.

## Part 4 — Being honest about causality

**Repeated views without a purchase has at least two plausible causes, and
view counts alone cannot distinguish them:** the price is above what this
customer will pay, or the product's description doesn't answer a question
they actually have. This system does not claim to know which. It measures
instead — `browse_abandonment`'s conversion rate (redemptions ÷ offers
sent) is reported *separately* from the other five segments, in
`campaigns/run.py`'s console output and markdown report, and in the
`/campaigns` merchant view (an amber callout on this segment's detail
panel specifically), always with the caveat spelled out rather than
implied. A low conversion rate here is evidence worth investigating — not
proof of either cause on its own. Nothing in the code, the CLI output, or
the UI asserts "this means price resistance" or "this means a content
gap" — that inference is left to the merchant, informed by the content-gap
data below.

## Part 5 — Content gap logging

A new tool, `report_content_gap(sku, question)` (`app/agent/tools.py`),
mirrors `decline_upsell`'s pattern exactly: not policy-gated (flagging a
documentation gap is never a risk), called by the shopping agent
*alongside* its best available answer, never instead of one. It logs an
ordinary `content_gap_reported` audit event — **no new table**. Merchant
aggregation (`AuditService.get_content_gaps()`, exposed at
`GET /api/campaigns/content-gaps`) groups the existing `audit_events` rows
by SKU in Python and returns counts plus sample questions; this needed one
new repository method, `list_by_event_type` (a cross-session read — the
first the append-only `AuditRepository` has needed since Layer 4), not a
new persistence layer. Surfaced on `/campaigns` as: *"N users asked about X
on this SKU; your description doesn't cover it."*

### Why this does not web-search to fill the gap

The decision not to reach for AI here is itself a judgment call, made
deliberately, for three reasons — not because it wasn't considered:

1. **The catalog is synthetic.** A real web search for "Pedigree Adult Dry
   Dog Food Chicken 3kg" would return results about an actual product this
   store doesn't sell under this description — a category error, not an
   answer.
2. **Pulling unverified external text into a system whose entire thesis is
   bounded, auditable behavior would undercut that thesis.** Every other
   piece of information this system acts on — catalog data, policy
   decisions, segment membership — is either generated with a known seed or
   computed by code a reader can step through. An unreviewed paragraph
   scraped from the open web has neither property, and stitching it into a
   product description would quietly reintroduce exactly the kind of
   unaudited external input Layer 3's prompt-injection defense exists to
   keep out of the system in the first place.
3. **The merchant fixing their own description is the actual fix.** A
   patched-over answer generated on the fly hides the underlying problem
   (an incomplete listing) instead of surfacing it — the system's job here
   is to make the gap visible and countable, not to paper over it.

## A live finding: this segment is the most exposed to its own cap

`campaigns/run.py` runs all six segments in one pass, and segment
membership overlaps — a customer can be `repeat` *and* mid-abandonment on
an unrelated product. Since `browse_abandonment` is proposed last, a live
run showed all of it blocked: every one of its treatment members had
already been ALLOWed by `lapsed`, `repeat`, `high_value`, or
`category_loyal` earlier in the same pass, and `OfferFrequencyRule`'s
default (one offer per customer per 30-day window) correctly refused to
target them again. This is the identical, correct cross-campaign
protection Layer 4.6's own docs already found for `high_value` and
`category_loyal` — `browse_abandonment` is simply the segment most exposed
to it, being last in line. The ALLOW-and-redeem path itself is separately
verified end to end (`test_browse_abandonment_offer_is_personalized_and_deterministic`,
plus a standalone clean-database run during development that showed 5 of 7
personalized offers ALLOWed with 2 redemptions and a real net margin
figure) — a live run where it happens to be entirely capped by an earlier
campaign in the same pass is a real, honestly-reported outcome of running
it after five others already claimed most of the window, not evidence the
mechanism doesn't work.

## Config (`backend/app/core/config.py`)

`campaign_browse_min_views` (3), `campaign_browse_window_days` (7),
`campaign_browse_abandonment_discount_pct` (0.02) — same override-via-env,
never-touchable-by-a-proposal discipline as every other campaign setting.

## Running it

`python campaigns/run.py` now proposes and gates six campaigns, not five —
no flag needed. `browse_abandonment`'s console output and the saved
markdown report both call out its conversion rate in its own section, with
the causality caveat inline rather than left for a reader to infer.
