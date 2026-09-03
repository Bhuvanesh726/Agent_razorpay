# Layer 4.8 — Onboarding, dashboards, and the demand-signal loop

Deliberately scoped: two days to submission, video/architecture-doc/README
still to write. The brief was explicit about what NOT to build (product
hero pages, image uploads, a signup form, a multi-step wizard, review
systems) and asked to be told if this grew past "one new table, one new
rule, an aggregation job, and two dashboard pages." It grew to two tables
(`demand_signals`, and `merchant_notifications` to hold the aggregation
job's own output — see below) plus a nullable column and a role-model
change; noted here rather than silently absorbed.

## Onboarding replaces the merchant-email allowlist entirely

Layer 4.7 auto-assigned `MERCHANT` to any email in `MERCHANT_EMAILS` at
first login. That's gone. `User.role` is now nullable, defaults to `None`,
and `app/auth/oauth_router.py::google_callback` no longer assigns anything
— every new Google login lands with no role at all, resolved by
`app/auth/principal.py::_resolve_from_jwt` to a fourth `PrincipalType`,
`"pending"`.

This isn't a client-side nicety. `SecureAPIRoute` (Layer 4.7's default-deny
mechanism) treats `"pending"` like any other principal type: an endpoint
has to explicitly `@requires(AuthRequirement.PENDING)` to accept one, and
exactly two do — `POST /api/onboarding/role` and `GET /api/auth/me`. Every
ordinary `BUYER`/`MERCHANT` endpoint rejects a pending principal with a
plain 403, the same as it would reject the wrong role. A pending user
literally cannot reach the shop, the cart, the agent chat, or the merchant
dashboard until they pick — onboarding is enforced at the same layer as
every other authorization boundary in this project, not by the frontend
choosing to redirect there first.

`POST /api/onboarding/role` sets the role and returns a **freshly-issued
JWT** — the old token's `role` claim is now stale (it was `null`), and the
JWT itself is otherwise stateless, so a new one is the only way the rest of
the app sees the change without a re-login. `AuthProvider`'s
`applyNewToken()` stores it and re-fetches `/api/auth/me` in place, no full
page reload needed.

### Dev-only role switch

Same gate as `X-Chaos-Fault` (Layer 3) and `/api/payments/test-complete`
(Layer 4.5): `POST /api/dev/switch-role` 404s outside `APP_ENV=development`,
checked *after* authentication so it still requires an already-onboarded
`BUYER`/`MERCHANT` principal even in dev. Exists specifically so one Google
account can demo both sides of the marketplace without a second account —
the frontend's `DevRoleSwitch` component is harmless to leave mounted
anywhere; it just stops doing anything once the backend gate closes.

## The demand-signal loop

This is the actual point of the layer — the mechanism that makes the
project two-sided instead of a shopping agent with a merchant page bolted
on.

### Capture: one LLM call, once per buyer turn

`app/demand/capture.py::maybe_capture` runs once at the end of
`harness.handle_chat` (not per tool call — per buyer *message*, which can
span several internal tool-call iterations). It does two things:

1. **Extract** (`_extract`) — the one LLM call this whole feature needs.
   A single completion, no tools, asking whether the message expressed
   product intent and what category/attributes it named. Deliberately not
   done via a second pass over historical audit-log text: real-time, at
   message-handling time, so nothing lossy gets re-parsed later.
2. **Classify the outcome from what actually happened**, never from chat
   text — `_classify_turn_outcome` reads back the audit events this exact
   turn produced (`policy_decision` events for `add_to_cart`, filtered by
   timestamp to this turn only) and derives `MATCHED` / `OUT_OF_STOCK` /
   `BLOCKED_BY_POLICY` from the real decision and rule name. If the buyer
   clearly wanted something (`has_product_intent` was true) and the turn
   never even attempted an add, that's `NO_MATCH` — read back from the
   log, not assumed, exactly the same "the log is the source of truth"
   discipline `app/audit/replay.py` established in Layer 4.

A `REQUIRE_CONFIRMATION` mid-turn is deliberately left uncaptured (`SKIP`)
— its outcome isn't known yet, and resolving it happens through a separate
`/api/agent/confirm` call this module doesn't observe. A documented
simplification, not a gap that silently miscounts: it fails to *capture*,
never to mis-classify.

Never blocks or fails the chat turn. Every failure mode — the model
timing out, returning malformed JSON, returning markdown-fenced JSON — is
caught and logged, same discipline as `app/campaigns/service.py::log_product_view`'s
"a telemetry side channel must never break the primary feature." See
**Two live-testing findings** below for what this actually caught in
practice, live, not hypothetically.

### `demand_signals`: no buyer identity column, structurally

```
id, session_id, timestamp, raw_query, category, extracted_attributes (JSON), matched_sku, outcome
```

No `user_id`. "Distinct buyers" is approximated by distinct `session_id`
(one session, one buyer, via the existing `AgentSession` table) — a
documented simplification (one buyer with two sessions asking the same
thing counts twice), but it means the privacy guarantee ("buyer identity
never exposed") isn't a query-discipline promise that a future query could
violate by accident — the column simply isn't there to select.
`raw_query` is retained for internal record-keeping only; the aggregation
layer never selects it into anything merchant-facing (enforced by what
`app/demand/aggregation.py`'s builder functions actually `SELECT`, tested
directly in `tests/test_demand_signals.py::test_notification_evidence_never_contains_raw_query_or_session_id`
rather than trusted by convention).

### Aggregation: deterministic, idempotent, cheap enough to run on every dashboard load

No LLM anywhere in `app/demand/aggregation.py` — same discipline as
`app/campaigns/segmentation.py`. `run()` is called at the top of
`GET /api/merchant/notifications` on every request, not a separate cron
job or script: it's a handful of `GROUP BY`s over a table that will never
be large in a demo's lifetime, and it's idempotent (`_upsert` never
recreates a `dedupe_key` that already exists, whatever its status), so
calling it on every page load costs nothing extra and needs nothing to
remember to run — the same "no scheduler needed" shape Layer 4.7's
embedded-agent "Run now" button already established.

One shared threshold (`crosses_threshold` — `demand_notification_threshold_pct`,
default 20%, with `demand_notification_threshold_floor`, default 5) drives
all four notification types, so there's one tested mental model instead of
four:

- **`UNMET_DEMAND`** — `NO_MATCH` signals grouped by category, distinct
  sessions counted.
- **`OUT_OF_STOCK_DEMAND`** — `OUT_OF_STOCK` signals grouped by SKU.
- **`ATTRIBUTE_GAP`** — not a new product schema field. Within a category
  that already has unmet demand, which *specific attribute key* (from
  `extracted_attributes`, already being collected) keeps recurring across
  sessions. A category with 5 `NO_MATCH` signals where 4 all named
  `max_sugar_g` is a much more actionable notification than the category
  count alone — derived entirely from data already captured, no new
  column, no numeric constraint-matching engine built against product
  attributes that don't exist in this catalog.
- **`BROWSE_ABANDONMENT`** — reuses Layer 4.6b's `ProductView` table (real
  buyer product-detail opens, not just the campaign system's synthetic
  backtest rows — see that table's own docstring), scoped to real `User`
  rows, counting distinct buyers who repeat-viewed the same SKU past
  `campaign_browse_min_views` without (a documented simplification: this
  layer's time budget didn't include re-deriving the purchase-exclusion
  join `segmentation.py`'s synthetic-customer version already does).

### Closing the loop

A `MerchantNotification` carries `status` (`NEW`/`ACTED`/`DISMISSED`) and
`acted_at`. Marking one `ACTED` doesn't just update a status — the
notification response includes `conversions_since_acted`, computed live
(`app/demand/aggregation.py::conversions_since`) as a count of `MATCHED`
demand signals for that same category/SKU with a timestamp after
`acted_at`. No separate tracking table: the same `demand_signals` rows
everything else reads, just filtered differently. This is what actually
proves the loop works — not that a notification fired, but that acting on
it visibly changed what happens next, live-verified below.

## `OutOfStockRule`

`StockRule` already denied a stock==0 SKU (`quantity(1) > stock(0)`), but
with a generic "exceeds available stock" reason. `OutOfStockRule`
(`app/policy/rules.py`, registered ahead of `StockRule`) gives the
specific case its own name and message, and — the actual point —
distinguishes `OUT_OF_STOCK` from `BLOCKED_BY_POLICY` in demand-signal
classification by rule name. "Toggle out-of-stock" on the merchant
dashboard doesn't add a new `is_out_of_stock` column (that would be a
second source of truth alongside `Product.stock`, which the catalog feed's
`availability` field and every existing stock check already reads) — it
just flips `stock` between 0 and a fixed restock quantity.

## Discount, end to end

`Product.discount_pct` (nullable float). `price_paise` stays the real list
price everywhere, always — `app/services/pricing.py::effective_price_paise`
is the one function that computes what a buyer actually pays, and it's
used consistently in the four places that matter: `ProductOut`/
`CatalogFeedItemOut` (buyer display — original + effective + pct, so the
frontend can render the strikethrough without computing anything itself),
`cart_service.add_item` (the price actually snapshotted onto the cart
line), `harness._build_proposed_state` (what the policy engine evaluates
`SpendCapRule`/`PerItemPriceRule` against), and the `search_products`/
`get_product` tool results (what the LLM itself sees, so it can mention
"on sale" honestly). A discount set on the merchant dashboard is never
cosmetic in only one of those — live-verified below, cart charged the
discounted price.

Bounded by `campaign_max_discount_pct` (30%, Layer 4.6) at the point the
merchant sets it (`app/routers/merchant.py::set_discount`) — not a new
`DiscountCapRule` in the policy engine, deliberately: setting a catalog
markdown is a merchant-side edit, not a `ProposedCartState` action the
engine ever evaluates (there is no buyer/agent turn involved), so a
formal `Rule` subclass would be reusing the wrong abstraction for a
different kind of decision. Reusing the existing constant is what "bounded
by the same cap the campaign system already enforces" means here.

## Two live-testing findings (not hypothetical)

Live-testing this layer's LLM-touching path (`demand/capture.py`) surfaced
two real bugs neither pytest's mocked-gateway tests nor a code read would
have caught. Both are in `Failures.md` with full detail; summarized here:

1. **The configured fallback model (`openai/gpt-oss-120b`) was
   decommissioned by NVIDIA the same day this layer was built** — the
   second time a model configured in this project has been retired mid-
   build. Verified the real current catalog via
   `GET https://integrate.api.nvidia.com/v1/models` rather than guessing a
   replacement, tested tool-calling specifically (not just chat) against
   five candidates using the exact `agno.models.nvidia.Nvidia` wrapper
   `app/llm/gateway.py` uses, found two of five 404 on this account despite
   being catalog-listed, and settled on `openai/gpt-oss-20b`. This is
   precisely the failure `LLMGateway`'s retry/fallback/circuit-breaker
   design (Layers 1 and 3) was built to anticipate — a config change, not
   a code change, was the fix.
2. **The model occasionally returns syntactically malformed JSON** for the
   extraction prompt despite an explicit "ONLY JSON" instruction — a
   missing closing quote, or valid JSON wrapped in a markdown fence anyway.
   `_extract()` now retries once on a fresh sample and strips a markdown
   fence before parsing; a second consecutive failure still degrades
   gracefully (turn completes normally, no signal captured, a warning
   logged) rather than being treated as fatal. Reproduced in
   `tests/test_demand_signals.py` from the actual live-observed output,
   not a synthetic example.

## Definition-of-done walkthrough, live

All six DoD items were run against the real backend/frontend, not just the
automated suite:

1. **New Google login → onboarding → pick role → correct dashboard** — a
   fresh `role=None` principal hitting `/` was redirected to `/onboarding`
   by `RequireAuth` automatically; clicking "I'm shopping" landed on
   `/dashboard` with a freshly-issued buyer JWT already applied.
2. **Buyer asks for something not stocked → honest decline, signal
   logged** — live, with a real NVIDIA call: asked for "50g chocolate
   bars with less than 3g of sugar," got a plain-language decline
   explaining no product matched (not a substitution), cart stayed empty,
   and a `NO_MATCH` `DemandSignal` was captured with
   `category="chocolate"`, `extracted_attributes={"size": "50g",
   "max_sugar_g": 3}`.
3. **Enough distinct sessions cross the threshold** — five distinct real
   buyers with matching signals; `GET /api/merchant/notifications`
   produced `UNMET_DEMAND` (category) and two `ATTRIBUTE_GAP` notifications
   (`max_sugar_g` and `size`, both named across all five buyers).
4. **Merchant sees the notification, counts and attributes only** — the
   dashboard rendered all three, each showing `distinct_buyers`,
   `active_buyers`, and (for the attribute-gap ones) `sample_values` —
   no session id, no raw query text, anywhere in the response or the UI.
5. **Act on it, reflected buyer-side** — marked the unmet-demand
   notification `ACTED` (status flipped to a green "ACTED" badge,
   `conversions_since_acted` rendered); set a 15% discount on Cadbury
   Dairy Milk Silk 150g from the merchant products table
   (`₹190.00 → ₹161.50`); confirmed via `GET /api/products/CHO-001` and
   the shop UI that the strikethrough/effective-price/percentage all
   matched, and added it to cart to confirm the line item charged
   ₹161.50, not ₹190.00.
6. **Full suite passes** — 221 passed, 0 regressions to Layers 0-4.7.
