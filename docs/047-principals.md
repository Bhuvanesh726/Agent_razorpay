# Layer 4.7 — Principals: buyer, merchant, agent

Every prior layer ran as a single hardcoded `user_demo`. This layer replaces
that with three real principal types — buyer, merchant, agent — sharing one
authorization mechanism, and introduces a bounded, revocable credential for
software acting on a buyer's behalf. It replaces the Google OAuth work
originally planned for Layer 5.

## Humans authenticate. Agents are authorized. These are not the same thing.

Conflating them is a design smell the spec explicitly calls out, and it's
worth saying exactly why, rather than just complying.

A buyer or merchant is a person. Proving who they are is an *identity*
problem: Google verifies "this is really this Gmail account," this backend
then vouches for that verification by issuing its own JWT
(`app/auth/security.py::create_access_token`), and every subsequent request
just needs to show that JWT hasn't expired or been tampered with. That's
**authentication** — the question is "who is this."

An agent is software. It has no identity to verify in that sense — there is
no "prove you are really this program" ceremony that means anything. What
actually matters for an agent is a completely different question:
"*is this exact request within the bounds someone explicitly granted it*" —
a specific spend limit, a specific set of tool scopes, revocable at any
moment without that software's cooperation or even its knowledge. That's
**authorization** via a bounded credential, not authentication of an
identity. `AgentCredential` has no password, no login flow, no session — it
has a `spend_limit_paise`, a `scopes` list, and a `status` that can flip to
`REVOKED` mid-conversation.

Concretely, in this codebase, the two mechanisms:

| | Human (buyer/merchant) | Agent |
|---|---|---|
| Presents | `Authorization: Bearer <jwt>` | `X-Agent-Key: <raw key>` |
| Proves | "Google verified this person, and this backend vouched for them" | "this exact secret was issued to this exact credential" |
| Resolved by | `app/auth/principal.py::_resolve_from_jwt` | `app/auth/principal.py::_resolve_from_agent_key` |
| Revocation | Wait for JWT expiry (7 days) or re-auth | Instant — `status="REVOKED"`, checked fresh every request |
| Rejected because... | signature invalid / expired | *never rejected here* — see below |

That last row is the sharpest expression of the distinction. A revoked
agent key still resolves to a valid `Principal` in `_resolve_from_agent_key`
— the secret genuinely was issued, to this exact credential, so pretending
authentication failed would be a lie. The denial happens one layer up, in
`RevokedCredentialRule` (`app/policy/rules.py`), as a normal, audited
`policy_decision` event — the same kind of event `SpendCapRule` or
`StockRule` produces — instead of a bare 401 with no trail. Whether an
agent is *allowed to proceed* is a policy question, evaluated fresh on
every call; whether a human *is who they claim* is an identity question,
settled once at login. Building one mechanism that tried to answer both
would have blurred exactly the distinction this section is arguing for.

## The agent credential, in two delivery modes

One table (`AgentCredential`), one set of policy rules
(`RevokedCredentialRule`, `AgentScopeRule`, `AgentSpendLimitRule`), one
enforcement path (`/api/agent/chat`, `/api/agent/confirm`). The only
difference between the two modes is whether the raw key is ever shown to a
human — and that difference is load-bearing enough that collapsing them
into one flow would misrepresent what each is actually for.

### Mode A — embedded agent (the product, and the primary POC)

A buyer creates this entirely from the UI:
`POST /api/agents` with `delivery_mode: "EMBEDDED"`. The raw key is
generated server-side (`generate_agent_key()`), hashed immediately
(`hash_agent_key()` — SHA-256, one-way), and the hash is the *only* thing
ever written to `AgentCredential.key_hash`. The raw value exists for the
lifetime of one local variable inside `create_agent()` and is discarded the
moment the function returns — `AgentCreateResponse.key` is `None` for this
mode, unconditionally, and no other endpoint returns it either (see
"EMBEDDED key never returned," tested explicitly).

Running it doesn't need the key at all: `POST /api/agents/{id}/run`
authenticates the *buyer* (their own JWT, proving they own this
credential), then constructs the `agent` `Principal` directly from the DB
row and pushes it into the same contextvar the HTTP `X-Agent-Key` path
would populate (`app/auth/context.py`), for one call into the harness. Same
policy evaluation, same audit tagging, as an external agent's own
authenticated HTTP call — the only thing that differs is *how* the
`Principal` got constructed, not what it's allowed to do afterward. Grant,
run, observe, revoke — all from the UI, with no human ever touching a
credential.

### Mode B — external agent (integration)

`POST /api/agents` with `delivery_mode: "EXTERNAL"` instead returns the raw
key exactly once, in that one response
(`AgentCreateResponse.key = raw_key`), so a third party can configure it in
their own system. This is what `buyer_agent/` actually uses: mint a
credential (`backend/scripts/create_agent_credential.py` — a dev-only
stand-in for "log in, click create-agent in the UI, copy the key," since
this headless script can't drive a Google OAuth browser flow itself), set
it as `AGENT_API_KEY`, and every subsequent call carries `X-Agent-Key`.

### Why both have to exist, not just one

Mode A is what makes "an AI agent shops for me" a *product feature* — a
buyer who has never heard of API keys can still get one, bounded, running
in production, because the platform holds the secret on their behalf. Mode
B is what makes this system *integrable* — a real third-party agent
(a different company's software, exactly what `buyer_agent/` simulates)
cannot function with a secret it's never shown; it needs to hold and
present that secret itself. Neither mode is a strictly-better version of
the other; they answer different questions ("can my buyer's own agent run
without them ever seeing a key" vs. "can an outside integrator configure
their own agent against my system"), and a real deployment needs to answer
both.

## The tradeoff, stated plainly

Mode A means a credential exists that its own owner cannot see. That is
**more leak-resistant** — there is no plaintext key sitting in a buyer's
clipboard history, password manager, or a support ticket they pasted it
into by accident, because it never existed outside this server's process
after the moment it was hashed. But it also means **the buyer is trusting
this platform** to hold that secret correctly and to only ever use it on
their behalf, the same trust they already extend to any password manager
or OAuth provider — they cannot independently verify what's inside
`AgentCredential.key_hash`, or audit this server's memory at the instant
`create_agent()` ran, the way they could scrutinize a key they held
themselves.

Where that boundary actually sits, concretely: this backend's own process
memory and database, between the moment `generate_agent_key()` returns and
the moment `hash_agent_key()` is called on the same line
(`app/auth/credentials_router.py::create_agent`). A compromise of *this
server* during that narrow window — not of the buyer, not of any client —
is the one scenario that could expose an embedded key's plaintext.

What a real deployment would change: this demo hashes with unsalted
SHA-256 (`hashlib.sha256`, `app/auth/security.py::hash_agent_key`) — fine
for a high-entropy 256-bit token (`secrets.token_urlsafe(32)`) where
brute-forcing the hash back to the key is infeasible regardless of salting,
but a production system would still want the generation-to-hash window to
happen inside a boundary with its own audit logging (an HSM or a secrets
manager's own generate-and-seal API, not an ordinary Python process), so
that "was this key's plaintext ever written to a log, a core dump, or swap
space" has an answer better than "we're fairly sure it wasn't." Real
deployments of comparable systems accept exactly this tradeoff already —
this is architecturally the same trust a payment processor's tokenization
vault asks for, or a password manager's zero-knowledge claim: "trust us to
have engineered the boundary correctly," not "trust us because we say so."

## Authorization: default-deny, enforced structurally

The obvious way to add auth to FastAPI is `Depends(get_principal)` sprinkled
onto the endpoints that need it. Rejected on purpose: that fails *open* — an
endpoint a developer forgot to annotate is simply unauthenticated, silently.
The spec's own requirement ("an endpoint with no declared auth requirement
must fail closed") can't be satisfied by a mechanism a missing annotation
can skip.

Instead, `SecureAPIRoute` (`app/auth/routing.py`) is a custom
`fastapi.routing.APIRoute` subclass passed as `route_class=` to every
`APIRouter(...)` in this project. It wraps every handler before it ever
runs and checks for exactly one of two markers:

```python
@public                                  # e.g. /health, the catalog feed
@requires(AuthRequirement.BUYER)
@requires(AuthRequirement.BUYER, AuthRequirement.AGENT)
@requires(AuthRequirement.MERCHANT)
```

An endpoint with neither raises 403 for every caller, always, with no
header or credential able to get past it —
`tests/test_principals_auth.py::test_endpoint_with_no_auth_marker_fails_closed`
proves this against a standalone app with a deliberately unmarked route, so
the guarantee is tested at the mechanism level, not just "every route in
this codebase happens to have a marker today."

`Principal` resolution (`app/auth/principal.py::resolve_principal`) checks
`X-Agent-Key` first, then `Authorization: Bearer`, opening its own
short-lived DB session rather than depending on FastAPI's request-scoped
one — it runs inside the routing layer, before normal dependency injection
has produced a session at all.

### Row-level scoping, endpoint by endpoint

- **Cart** (`app/routers/cart.py`) — BUYER only, deliberately excluding
  AGENT. These raw REST endpoints mutate the cart with no policy engine in
  front of them (a Layer 0 shape, predating policy gating entirely);
  letting an agent hit them would be a real bypass of "same rules, same
  enforcement," not a convenience. `buyer_agent/` was reworked this layer
  to clear a stale cart through `/api/agent/chat` instead of a direct
  `DELETE /api/cart/items/{id}` for exactly this reason.
- **Campaigns** (`app/routers/campaigns.py`) — MERCHANT only, every
  endpoint. Campaign offers carry `cogs_paise` — cost-of-goods, i.e.
  margin data — which must never reach a buyer or agent response.
- **Products / catalog** (`app/routers/products.py`,
  `app/routers/catalog.py`) — PUBLIC for browsing and the agent-readable
  feed (an external agent has no credential yet the first time it looks
  here), `@requires(BUYER, AGENT)` for view-logging.
  `ProductOut`/`CatalogFeedItemOut` never include `Product.cost_paise` —
  the buyer-facing schemas simply don't declare the field, checked directly
  in `test_cost_paise_absent_from_product_and_catalog_responses`.
- **Agent chat/confirm** (`app/routers/agent.py`) — `@requires(BUYER,
  AGENT)`. A human's own JWT and an agent's `X-Agent-Key` reach the
  identical `handle_chat`/`handle_confirm` code path.
- **Agent credentials** (`app/auth/credentials_router.py`) — BUYER only.
  List/detail/revoke are owner-scoped (`_get_owned_credential` — a
  credential that doesn't exist and one that exists but isn't yours return
  the identical 404, so probing can't distinguish the two cases).
- **Payments** (`app/routers/payments.py`) — `/verify` and `/failed` stay
  BUYER-only (the real browser-driven Checkout callback has no reason to
  ever come from an agent's own HTTP call); `/test-complete` allows AGENT
  too, specifically because that dev-only endpoint exists *for*
  `buyer_agent/` — an external agent has no browser to receive a real
  callback in. All three now verify `order.user_id == principal.user_id`
  before touching the order (`_find_owned_order`), returning the same 404
  either way.
- **Audit** (`app/routers/audit.py`) — `@requires(BUYER, MERCHANT, AGENT)`.
  Merchants read any session (campaign runs have no `AgentSession` row at
  all); buyers and agents are scoped to sessions owned by that buyer — an
  agent's `Principal.user_id` is its credential's owner, so it can read its
  own runs but never another buyer's.

### A real bug this review found: session ownership

While writing the row-level scoping above, a genuine cross-user gap
surfaced, not a hypothetical one: `agent_session_repo.get_or_create_session`
looked up an `AgentSession` by `session_id` alone, with no check that the
session's `user_id` matched the caller. A second user who reused or guessed
someone else's `session_id` string could have operated on that other user's
real cart. Fixed in `app/agent/harness.py` — both `handle_chat` and
`handle_confirm` now raise `SessionOwnershipError` the moment a resolved
session's `user_id` doesn't match the calling principal's, and
`app/routers/agent.py` translates that into a 403.

## Policy rules added this layer

Same engine, same pattern as every rule before them
(`app/policy/rules.py`), evaluated per line item alongside `StockRule`,
`PerItemPriceRule`, etc.:

- **`RevokedCredentialRule`** — denies immediately if
  `agent_credential_status == "REVOKED"`, for *any* tool, not just
  cart-mutating ones. Registered first, ahead of `UnknownSkuRule`, so a
  revoked credential is denied before anything else about the action is
  even evaluated.
- **`AgentScopeRule`** — denies a tool call outside `agent_scopes`. An
  agent created with `scopes: ["search_products", "get_product"]` cannot
  call `add_to_cart`, full stop, regardless of session budget or stock.
- **`AgentSpendLimitRule`** — denies once `agent_spent_paise +
  this_line_amount > agent_spend_limit_paise`, evaluated independently of
  `SpendCapRule`'s session budget. The stricter of the two always wins,
  because both run and either can DENY. `agent_spent_paise` itself is read
  fresh from the DB on every policy evaluation
  (`app/agent/harness.py::_agent_policy_fields`) rather than cached on the
  `Principal` — the same freshness `RevokedCredentialRule` depends on for
  "revoked mid-session," so a credential revoked or exhausted between two
  tool calls in the same multi-iteration turn is caught on the very next
  one.

`AgentCredential.spent_paise` is incremented at successful `add_to_cart`
time, using the price actually charged (not the proposal) — a documented
simplification: removing an item does not currently release the
reservation, mirroring how `SpendCapRule`'s own session budget already
works.

## Audit: principal tagging with zero call-site changes

Every `_audit.log_event(...)` call site across `harness.py`, `tools.py`,
and `campaigns/service.py` — dozens of them, none touched this layer —
needed to start recording the acting principal
(`AuditEvent.principal_type`, `AuditEvent.principal_id`). Threading a new
parameter through every one of those call sites was the obvious approach
and the one most likely to introduce a regression in what the spec itself
calls the biggest-regression-risk layer so far.

Instead, `app/audit/service.py::log_event` falls back to
`_default_principal_fields()` whenever neither field is passed explicitly,
which reads the same `contextvars.ContextVar` (`app/auth/context.py`) that
`SecureAPIRoute` populates for the duration of each request — the exact
pattern this project already used for `X-Chaos-Fault`
(`app/testing/chaos.py`) in Layer 3. Every existing call site got correct
tagging automatically; nothing needed to change except the one fallback at
the top of `log_event` itself.

## What "buyer/merchant Google OAuth, agent authorization" looks like end to end

Live-verified this layer, not just unit-tested:

```
$ python backend/scripts/create_agent_credential.py
Created EXTERNAL agent credential 'agent_c2a0085962364a0a' for owner 'user_demo'.
Scopes: search_products, get_product, add_to_cart, view_cart, remove_from_cart, initiate_payment, decline_upsell
Spend limit: 1,000,000 paise
Raw key (shown exactly once — save it now):
  agentkey_...

$ export AGENT_API_KEY=agentkey_...
$ python buyer_agent/buyer.py --base-url http://127.0.0.1:8842
SCENARIO: generous budget, accept a fitting upsell (budget ₹3000.00)
  + Baskin Robbins Belgian Chocolate Tub 500ml (₹450.00) -> cart total ₹450.00
  + India Gate Basmati Rice Classic 5kg (₹649.00) -> cart total ₹1099.00
  + Red Bull Energy Drink 4-pack (₹500.00) -> cart total ₹1599.00
  Merchant offered an upsell: Nestle KitKat 4-Finger 6-pack (₹120.00)
  accepted -> cart total ₹1719.00
  order created: razorpay_order_id=order_TXUYZd59RcveXM, amount=₹1719.00
  PAID: Payment verified and captured.

SCENARIO: tight budget — any upsell should be blocked (budget ₹780.00)
  + Ferrero Rocher 16-piece Box (₹749.00) -> cart total ₹749.00
  no upsell offered this session
  blocked: SpendCapRule — This would bring the cart total to ₹794.00, exceeding the session budget of ₹780.00.

Scenario 1 — bought 3 item(s), paid=True, upsell_accepted=True
Scenario 2 — bought 1 item(s), paid=False, upsell_offer_shown=False
```

A real `EXTERNAL` credential, authenticated with `X-Agent-Key` on every
call, went through the full policy-gated conversational flow and a real
Razorpay test-mode payment — with zero internal access, exactly as
`docs/045-catalog.md`'s original `buyer_agent/` design intended, now on top
of a bounded, revocable credential instead of the old unauthenticated
`user_demo`.

## Tests

`backend/tests/test_policy_rules.py` covers the three new rules at the
unit level (11 new tests — no-op for humans, revoked-denied-immediately
including for non-cart tools, scope allow/deny, spend allow/deny including
the literal "blocked despite higher session budget" DoD scenario, and
registration-order precedence). `backend/tests/test_principals_auth.py`
covers the eight DoD scenarios end-to-end through the real HTTP/routing
layer (`TestClient` + `SecureAPIRoute`, not direct function calls — several
of these, like default-deny and JWT/agent-key resolution, only exist at
that layer):

1. Buyer cannot reach merchant endpoints (and merchant can).
2. `cost_paise` absent from `/api/products` and `/api/catalog/feed`.
3. Agent blocked at its credential's spend limit despite a higher session
   budget.
4. Revoked credential denied immediately (auth still succeeds; the policy
   layer denies).
5. Agent blocked calling a tool outside its declared scopes.
6. User A cannot list/read user B's agents, read B's audit trail, or read
   B's order via payments.
7. EMBEDDED key never returned by `/api/agents` create, list, or detail.
8. An endpoint with no `@public`/`@requires` marker is unreachable, always.

Full suite: 192 passed, 0 regressions to Layers 0-4.6b.
