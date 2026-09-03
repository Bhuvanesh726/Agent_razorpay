# Layer 4.5 — Agent-readable catalog + bounded upsell

The buildathon track's bar has two clauses — "grows revenue for a merchant"
or "makes a merchant transactable by an AI buyer end to end." Layers 0-4
built the second in isolation (one browser, one human, one chat session).
This layer makes it reachable by a *different company's* agent with zero
integration help from us, and adds the first without weakening anything the
policy engine already guarantees.

## Part A — Agent-readable catalog

### What's actually out there

Researched before writing any schema, per the brief. Short version: none of
ACP, AP2, or x402 is a catalog standard you can copy wholesale.

- **ACP** (Agentic Commerce Protocol — OpenAI, Stripe, Meta) does define a
  product feed, but it's a delimited file (TSV/CSV) pushed to an OpenAI
  ingestion endpoint, not a JSON document a merchant serves. Its field
  names — `item_id`, `title`, `description`, `price` (decimal + ISO 4217,
  e.g. `"79.99 USD"`), `availability` (`in_stock`/`out_of_stock`/
  `pre_order`/`backorder`), `product_category` — are still the closest
  thing to a shared vocabulary for *what a product listing looks like*.
  Checkout is a separate REST API; there's no `.well-known` discovery
  convention anywhere in ACP.
- **AP2** (Agent Payments Protocol — Google, now with FIDO Alliance) has no
  catalog shape at all. It's a payment-*authorization* layer: three signed
  Mandates (Intent/Cart/Payment) exchanged as verifiable credentials inside
  an A2A conversation. It assumes the catalog comes from somewhere else
  (a merchant site, ACP, UCP). The one discovery convention in that
  ecosystem — `/.well-known/agent.json` — belongs to A2A, not AP2 itself.
- **x402** (Coinbase, HTTP 402) is pay-per-request, not catalog-oriented at
  all — a protected resource returns a `PaymentRequired` body describing
  *how to pay for this one resource* (`scheme`, `network`, `amount`,
  `asset`, `payTo`), with an optional discovery index of resources and
  their prices, no product fields.
- **UCP** (Universal Commerce Protocol, `ucp.dev`) is newer and does define
  a catalog capability with `id`, `sku`, `title`, and — notably —
  `price: {amount, currency}` where `amount` is the ISO 4217 **minor unit**
  (paise/cents as an integer), plus a `/.well-known/ucp` discovery
  convention. Structurally the closest match to a paise-based backend.
- **schema.org Product/Offer** (JSON-LD) is the oldest, most universally
  parsed of the bunch, but has no discovery convention of its own — it's
  embedded per-page, not fetched as a feed.

### What this catalog aligns to, and where it deviates

- **Field names** (`id`, `title`, `description`, `category`,
  `availability`): ACP's product-feed spec — the vocabulary most likely to
  already be familiar to a consuming agent, even though ACP itself doesn't
  serve this as fetchable JSON.
- **Price representation**: UCP's convention (integer minor units), not
  ACP's decimal string. `price_paise` is an int; `currency` is a separate,
  always-present field (`GET /api/catalog/feed`, `CatalogFeedItemOut` in
  `backend/app/schemas/catalog.py`). This also matches `price_paise`
  everywhere else in this API — an agent should never have to parse a
  currency string to know an exact amount, and this store already had that
  discipline from Layer 0.
- **Discovery URI**: `/.well-known/catalog.json` borrows the *pattern* from
  UCP (`/.well-known/ucp`) and A2A (`/.well-known/agent.json`) — not a
  requirement of ACP/AP2/x402, none of which specify one, but the emerging
  norm one layer up from all three.
- **`availability`**: only two of ACP's four enum values apply
  (`in_stock`/`out_of_stock` — this catalog has no pre-order/backorder
  concept), so only those two are ever emitted; documented rather than
  padding the enum with values that would never fire.
- **`sku`, `stock`, `unit`**: no equivalent in any of the three protocols.
  Kept anyway — a budget-constrained buyer genuinely needs to know "how
  many are actually left," and this store already tracks it. `id` is set
  equal to `sku` for a consumer expecting ACP's field name; `sku` stays
  present as the real database key.
- **Checkout**: none of ACP's structured `checkout_sessions` API, AP2's
  Mandates, or x402's payment-required flow is implemented. `how_to_transact`
  in the discovery document says exactly what this merchant actually
  offers instead: a conversational endpoint (`POST /api/agent/chat`) where
  every proposed action is policy-gated and audited. This is a deliberate
  choice, not a shortcut — see "Why conversational, not a structured
  checkout API" below.

### Endpoints

- `GET /.well-known/catalog.json` — merchant name, currency, environment
  (`"test"` — this is Razorpay test mode, said plainly rather than left
  ambiguous), capabilities, endpoint URLs, `how_to_transact` prose, and an
  `aligned_to` block naming exactly what's borrowed from where (the
  paragraphs above, machine-readable).
- `GET /api/catalog/feed?page=&page_size=` — paginated, `ETag` (a SHA-256
  of the page's own serialized content — identical output always hashes
  the same, so `If-None-Match` round-trips correctly with zero extra state
  tracked server-side) and `Last-Modified` (the max `updated_at` across
  that page's products — a real column added this layer specifically so
  freshness could be answered honestly rather than approximated from
  something else).

### Why conversational, not a structured checkout API

An external agent integrating with a real ACP-style structured checkout API
has to learn *this store's* request/response shapes before it can buy
anything. A conversational endpoint needs no bespoke integration — any
agent capable of holding a conversation, including a plain LLM with no
special-cased connector for this merchant, can complete a purchase, because
the interface is language, the same interface a human already uses. That's
arguably more agent-native than a rigid REST checkout, not less — and it's
what `buyer_agent/` actually proves, live: it never learned a merchant-
specific request shape, only "send natural language to `chat`, watch for
`status: awaiting_confirmation`, `confirm`."

### Proof: `buyer_agent/`

A standalone script, zero imports from `backend/app`, no shared DB session,
no filesystem access into this project beyond its own file — everything it
knows comes from HTTP responses, the same as a genuinely different
company's agent would see. It:

1. Discovers the merchant from `/.well-known/catalog.json`.
2. Reads the full paginated feed.
3. Builds a small basket deterministically (cheapest in-stock item per
   category, greedy under budget) — deliberately not LLM-driven on the
   buyer side; the point of this script is proving the *transaction path*,
   which the merchant side already exercises with a real model.
4. Buys it through the real conversational flow (`chat` → `confirm`), the
   exact same policy-gated path a human user's session goes through — see
   "Why buyer_agent's purchase is policy-gated, not a special path" below.
5. Reports the session's audit trail — including upsell outcomes — read
   from the same public `/api/audit/{session_id}` endpoint anything else
   uses.

Run two scenarios by default: a generously-budgeted purchase (discovers,
buys, accepts a fitting upsell if one is offered) and a tightly-budgeted one
(sized so any upsell offered would breach the cap — proving it back via the
same public audit endpoint, not by peeking at internal state).

#### What actually happened, live, and two bugs it found

First basket strategy tried — cheapest in-stock item per category — reliably
built carts of a few tens of rupees, too small for any real pairing to clear
`UpsellPolicyRule`'s percentage cap; switched to *priciest* in-stock item
per category instead (`build_basket` in `buyer_agent/buyer.py`), which is
also more representative of what a budget-holder would actually buy.

That surfaced a real bug: some of those pricier picks (an item over ₹1,000,
or a cart that crosses the ₹1,000 confirmation threshold) come back
`awaiting_confirmation` from `ConfirmationThresholdRule` — exactly the same
gate a human session hits — and the original add-loop didn't handle it,
silently dropping the rest of the basket. Fixed with a small `_send()`
helper that approves any non-payment confirmation immediately (a real buyer
saying "yes, go ahead" to one add is the ordinary case), while the payment
confirmation itself stays handled explicitly by the caller.

Second bug, the same one `demo.py` already hit in Layer 4: a basket chosen
the same way every run collides with its own prior purchase forever, since
the idempotency key is a permanent hash of (user, cart contents, amount).
Fixed by shuffling *within* a pool of the priciest candidates rather than a
strict sort, so repeat runs land on a different basket. The tight-budget
scenario deliberately keeps a fully deterministic single-item pick instead
(`build_tightest_single_item_basket`) — it needs minimal leftover budget to
reliably force the block it's demonstrating, and shuffled variety would
sometimes leave just enough headroom for a cheap upsell to fit, silently
turning the "blocked" scenario into an "accepted" one on a lucky shuffle.
That determinism does mean a same-session rerun can hit its own earlier
purchase of that exact item — observed once, and left as-is: a correct
duplicate-payment refusal is a fine thing to demonstrate too, just not
what that particular rerun was trying to show.

A clean run, live, `2026-09-02`:

```
Scenario 1 (₹3,000 budget): India Gate Rice + Red Bull + Amul Ghee = ₹1,149
  -> offered Thums Up (complementary category 'cool_drinks', ₹45) -> accepted
  -> order paid, ₹1,194 total
  audit: upsell proposed=1 accepted=1 declined=0 blocked=0, revenue=₹45.00

Scenario 2 (₹780 budget): Ferrero Rocher alone = ₹749
  -> candidate upsell (₹45) would bring the cart to ₹794, over the ₹780 cap
  -> blocked by SpendCapRule, rule named, never surfaced to the buyer
  audit: upsell proposed=0 accepted=0 declined=0 blocked=1
```

Both DoD #2 (a relevant upsell offered and accepted within budget) and DoD
#3 (an upsell that would breach the cap denied, with the rule named) are
satisfied inside this single script, live, with no internal access.

#### Why buyer_agent's purchase is policy-gated, not a special path

The raw REST cart endpoints (`POST /api/cart/items`, from Layer 0) mutate
the cart directly with **no policy engine in front of them** — they were
built for the human-browsing UI, before Layer 1 introduced policy gating at
all. Had `buyer_agent` used those, "subject to the same policy engine"
would be false. It only ever calls the conversational endpoints
(`/api/agent/chat`, `/api/agent/confirm`) discovered from the catalog.json
document — the same `handle_chat`/`handle_confirm` code path, same
`PolicyEngine.evaluate()` call, same audit log, that a human's browser
session goes through. Nothing in the harness distinguishes "a person typed
this" from "an external agent posted this JSON" — which is exactly the
point.

#### Why payment completion uses a dev-only endpoint, not the real secret

Razorpay Checkout normally needs either a browser (to enter a test card and
complete OTP — the same friction Layer 2 already documented) or the
merchant's `razorpay_key_secret` to sign a callback locally (what `demo.py`
does, correctly, since `demo.py` *is* the merchant testing its own system).
`buyer_agent` is deliberately **not** given that secret — a real external
buyer never would be, and pretending otherwise would misrepresent a
constraint that's actually load-bearing for the "different company's agent"
framing. Instead, `POST /api/payments/test-complete` (gated to
`app_env == "development"`, identical gating to the `X-Chaos-Fault` header
from Layer 3) signs a synthetic callback **server-side** — the secret never
leaves the merchant's process — and then runs it through the exact same
`verify_payment()` code a real Checkout callback would hit. Only the
*signing* is a shortcut; the *verification* is not. This endpoint is
deliberately **absent** from `/.well-known/catalog.json`'s advertised
endpoints — it's this project's own headless-testing convenience, not a
capability a real external integrator should build against.

## Part B — Bounded upsell

### The mechanism, in one sentence

A candidate upsell is evaluated by the identical `PolicyEngine.evaluate()`
call every other action goes through — the same `StockRule`,
`PerItemPriceRule`, `QuantityRule`, `SpendCapRule` instances, plus one new
rule (`UpsellPolicyRule`) for the upsell-specific constraints. There is no
separate "upsell approval" code path to audit independently, which is the
literal meaning of "no special path, no exemption."

### Why the offer isn't a model-callable tool

An earlier design had the LLM call a `propose_upsell(sku)` tool. Rejected:
letting the model choose the SKU is one more hallucination surface (Layer
3's whole prompt-injection defense exists because model output about
products can't be trusted blindly), and it makes the offer's *appearance*
dependent on the model remembering to call something — unreliable for
eval/CI determinism, as this project's own Layer 4 eval run already showed
live models being unpredictably conservative.

Instead: **the harness itself** runs a deterministic recommender
(`backend/app/upsell/recommender.py` — a small `SKU -> SKU` "frequently
paired" table, falling back to "cheapest in-stock item in a complementary
category") immediately after any successful `add_to_cart`, evaluates the
candidate through the policy engine, and — only on ALLOW — attaches a
`suggested_upsell` field to that tool's result (so the model sees it and
can mention it naturally) and a structured `upsell` field on the public
chat response (so a caller with no chat history, like `buyer_agent`, can
act on it without parsing prose). The *what* is never the model's call; the
*whether to mention it, and what the user said back* still is — the system
prompt tells it to call `add_to_cart` again to accept, or `decline_upsell`
to record a no, never to invent a different SKU.

### `UpsellPolicyRule` (`backend/app/policy/rules.py`)

Three constraints, on top of the item-level rules everything else already
enforces:

1. **Session cap** (`policy_upsell_max_per_session`, default `1`) — how
   many offers this session will ever see, period, regardless of outcome.
2. **Percentage-of-cart cap** (`policy_upsell_max_pct_of_cart`, default
   `0.50`) — an offer priced above this fraction of the cart's value *at
   the moment of the first offer* is blocked, so a ₹50,000 add-on can never
   attach itself to a ₹100 cart. First discovered *empirically*: an initial
   default of 30% blocked nearly every real pairing in this catalog once
   actually tested end to end (₹249 Dentastix treats are 33.6% of a ₹740
   dog-food cart) — raised to 50% after checking it against real catalog
   economics rather than shipping an untested number.
3. **No re-offering a declined SKU** — enforced via `upsell_declined_skus`
   on the synthesized `ProposedCartState`.

### Where the session's upsell state actually lives

Nowhere new. `backend/app/upsell/state.py` derives everything — how many
offers have been proposed, which SKUs were declined, what's currently
outstanding, accepted revenue — by replaying the session's audit trail,
the same "the log is the only source of truth" discipline `app/audit/replay.py`
established in Layer 4. No new table, nothing that can drift from what
actually happened.

### Accept, decline, and the auto-decline at payment time

- **Accept**: the model calls `add_to_cart` again with the offered SKU —
  the harness recognizes it matches the outstanding offer and logs
  `upsell_accepted` with the price actually charged (not the price at
  offer time, in case the catalog changed in between).
- **Decline**: a new `decline_upsell` tool (no arguments — there's only
  ever one outstanding offer) records it explicitly.
- **Implicit decline**: if the user proceeds all the way to a *confirmed*
  payment with an offer still outstanding, `initiate_payment` records an
  implicit decline before doing anything else — a real user who never
  responded and then paid has, in every practical sense, said no.

### Measuring it

`GET /api/audit/{session_id}` now returns, alongside the existing token/cost
totals: `upsell_proposed_count`, `upsell_accepted_count`,
`upsell_declined_count`, `upsell_blocked_count`, and
`upsell_incremental_revenue_paise` — all aggregated the same way the
existing totals are, a pure fold over the trail, no new query.

### Eval coverage

`eval/scenarios.yaml` gained upsell scenarios covering: an offer appearing
after a relevant add, an offer blocked by the session's own spend cap (rule
named — `SpendCapRule`, since the item-level rules apply to a candidate
upsell too), and an offer blocked by `UpsellPolicyRule`'s own percentage
cap specifically. `backend/tests/test_upsell.py` and the `UpsellPolicyRule`
unit tests in `backend/tests/test_policy_rules.py` cover the rest
end-to-end without depending on a live model.
