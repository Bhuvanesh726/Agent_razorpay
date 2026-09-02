# Layer 2 — Razorpay test-mode payment + idempotency

Test mode only. No real money moves. The one thing this layer is graded on:
double-charging must be structurally impossible, not merely unlikely.

## The idempotency guarantee

The idempotency key is `sha256(user_id, sorted cart line items, amount_paise)`
— deterministic, not a random UUID (`app/orders/idempotency.py`). Same intent
always produces the same key.

The guarantee itself lives in the database, not in application logic:
`orders.idempotency_key` has a real `UNIQUE` index (verified in the generated
migration — `unique=True`, not just an index). `app/orders/repository.py`'s
`get_or_create` never does "check if it exists, then insert" — that pattern
has a race window between the check and the insert where two concurrent
requests can both pass the check. Instead it **inserts first**, and if the
UNIQUE constraint rejects it as a duplicate, catches that `IntegrityError`,
rolls back, and re-selects whichever row actually won. The DB decides who
won, not application logic.

This is proven with a real concurrency test, not a simulated one —
`tests/test_order_repository_concurrency.py` spins up two actual threads,
each with its own SQLAlchemy session against a shared **file-based** SQLite
DB (an in-memory `:memory:` DB is isolated per-connection, so it can't
demonstrate a genuine cross-connection race), synchronized with a
`threading.Barrier` so both attempt the insert at the same instant. Asserts
exactly one row exists afterward, and that exactly one thread got
`created=True`. Ran it 5x in a row with no flakes.

## Order state machine

`app/orders/state_machine.py` — `OrderStatus` enum + an explicit
`ALLOWED_TRANSITIONS` map, never a bare string:

```
PENDING → AWAITING_CONFIRMATION → PAID (terminal)
                                → FAILED → AWAITING_CONFIRMATION (retry)
                                        → CANCELLED (terminal)
PENDING → FAILED | CANCELLED
```

`require_transition()` raises `InvalidTransitionError` on anything not in the
map — e.g. `PENDING → PAID` (skipping confirmation) or any transition out of
`PAID` are rejected in code, not just by convention. `FAILED →
AWAITING_CONFIRMATION` is deliberately allowed: a declined card should let
the user retry against the *same* order (same idempotency key, same Razorpay
order), not start over.

**A real bug this caught during live testing**: `ensure_razorpay_order`
originally short-circuited on "already has a `razorpay_order_id`" without
checking status, so retrying after a `FAILED` attempt reused the Razorpay
order (correct) but left the DB status stuck on `FAILED` while a payment was
actually back in progress (wrong). Fixed to transition `FAILED →
AWAITING_CONFIRMATION` on that path, with a regression test
(`test_retry_after_failure_reuses_razorpay_order_and_leaves_failed_state`).

## Razorpay integration (`app/payments/gateway.py`)

Same single-choke-point pattern as the LLM gateway in Layer 1 — nothing else
imports the `razorpay` SDK. Two operations:

- `create_order(amount_paise, currency, receipt)` — wraps
  `client.order.create()`, maps SDK errors to a `PaymentGatewayError` with a
  `category` (`client_error` vs `server_error`) so the caller knows whether
  retrying makes sense.
- `verify_signature(order_id, payment_id, signature)` — wraps
  `client.utility.verify_payment_signature()`, which is pure local HMAC-SHA256
  (`hmac.compare_digest`, constant-time) — **no network call**, so
  `tests/test_signature_verification.py` runs fully offline and still
  exercises the real cryptographic check, including a wrong-secret and a
  wrong-payment-id case (replay protection).

**The frontend's claim of payment success is never trusted.** Razorpay
Checkout's success callback is just a suggestion to the browser to *ask* the
backend to verify — `POST /api/payments/verify` independently recomputes the
HMAC server-side with the real key secret and only *that* decides whether the
order becomes `PAID`.

The key secret never leaves `app/payments/gateway.py` — not returned to the
frontend (only `razorpay_key_id`, the publishable id, is), not logged, not in
any audit row.

## Policy: two new rules, same pattern as Layer 1

- **`DuplicatePaymentRule`** — DENY if the order for this idempotency key has
  already reached `PAID`. The harness resolves `existing_order_status` by a
  read-only lookup before policy evaluation; the rule itself does no I/O.
- **`PaymentAuthorizationRule`** — re-validates the *entire current cart*
  through the same item-level rules (`UnknownSkuRule`, `StockRule`,
  `PerItemPriceRule`, `QuantityRule`, `SpendCapRule`) by replaying each line
  as a synthetic `add_to_cart` check against a running total — composing the
  existing rules rather than re-implementing their thresholds. This is what
  "a cart approved five minutes ago is not automatically approved now" means
  concretely: if stock dropped to zero on an item since it was added, this
  catches it using the *live* catalog, while the *charged* amount still uses
  the cart's price snapshot (never re-priced from a live catalog change).
  **Never returns ALLOW** — a clean cart gets `REQUIRE_CONFIRMATION`, never a
  straight pass. This is what makes "the agent can never complete a payment
  on its own" true at the policy layer, not just by convention in the
  harness. When a sub-rule denies, its *own* name (e.g. `SpendCapRule`) is
  surfaced as the decision's `rule_name`, not the wrapper's — a more
  actionable audit trail than "PaymentAuthorizationRule, see reason text."

Both registered in `default_policy_engine()` alongside the Layer 1 rules —
adding them was one class each, zero changes to existing rules.

## The agent tool (`initiate_payment`)

Takes no arguments — always acts on the current cart. Because
`PaymentAuthorizationRule` never returns ALLOW, every proposal lands on the
harness's existing `REQUIRE_CONFIRMATION` path from Layer 1 — no new
confirmation mechanism was needed. The tool itself (only ever reached after
the user confirms) is idempotent at two levels:

1. `order_service.create_or_get_order` — same cart ⇒ same order row, never a
   second one (the DB-level guarantee above).
2. `order_service.ensure_razorpay_order` — if the order already has a
   `razorpay_order_id`, it's reused, never re-created. This is what makes a
   rapid double-click on "Confirm" safe even before the DB race matters: the
   second call just finds the same order and the same Razorpay order.

## Why payment needed its own endpoints, outside the chat loop

Card entry happens inside Razorpay's own hosted Checkout UI (a `<script>`-
injected modal, not something a Python function call can wait on) — there's
no single synchronous call that "returns" a payment result the way other
tools do. So the flow splits:

1. Chat: propose → confirm → `initiate_payment` creates the order and
   returns Razorpay checkout params (order id, amount, the *public* key id).
2. Frontend opens Razorpay Checkout with those params.
3. Razorpay's browser SDK calls back with `{order_id, payment_id, signature}`
   on success, or a `payment.failed` event on decline — the frontend posts
   whichever happened to `POST /api/payments/verify` or
   `POST /api/payments/failed`, **outside** the agent harness.

`/api/payments/verify` is itself idempotent: a duplicate call for an
already-`PAID` order (a rapid double-click, a retried network request)
returns the existing success without creating a second `Payment` row or
re-running the state transition — logged as `duplicate_payment_prevented`.

## Cart reset on payment success

Chosen deliberately over leaving paid items sitting in the cart: on `PAID`,
the cart that produced the order is marked `checked_out` and a fresh active
cart is created (`order_service._reset_cart_after_payment`). This also
resolves an edge case in the idempotency key design — since the key is pure
content-plus-amount with no cart id or timestamp in it, buying the exact same
combination of items twice would otherwise hash identically. Because a
completed purchase always leaves the next cart empty, a genuinely new
purchase never collides with a past paid one.

## What's proven live (not just in tests)

Ran the actual flow through real Razorpay test-mode infrastructure, not
mocks, via a real browser:

- Real `order.create()` API call succeeded (confirmed by the Checkout iframe
  loading with the correct order id and price).
- A real domestic test card (`5267 3181 8797 5449`) went through Razorpay's
  full hosted flow — mobile number, card entry, name/email, the bank's OTP
  simulation (`1221`) — and **Razorpay's own signature** was verified
  server-side and accepted.
- A real decline: `4111 1111 1111 1111` was rejected by Razorpay as an
  unsupported international card. The `payment.failed` browser event fired,
  hit `/api/payments/failed`, and was logged correctly — this accidentally
  gave a real (not simulated) proof of the failure path along the way.
- The retry: after that decline, the *same* order was reused for a second
  attempt (confirmed via `ensure_razorpay_order`'s `mock_create.assert_not_called()`
  check at the test level, and the DB showing the same `razorpay_order_id`
  across both attempts) — and this attempt succeeded, taking the order to
  `PAID`.
- Final DB state matched exactly: `Order.status = PAID`, one `captured`
  `Payment` row with the real `razorpay_payment_id`, one earlier `failed`
  row with Razorpay's real decline message, old cart `checked_out`, new cart
  `active` and empty.
- The full audit trail for that session, in order: `user_message` →
  `model_call` → `tool_call_proposed` → `policy_decision
  (REQUIRE_CONFIRMATION, PaymentAuthorizationRule)` → `confirmation_approved`
  → `order_created` → `razorpay_order_created` → `tool_executed` →
  `payment_failed` (the decline) → `signature_verified` → `payment_succeeded`
  (the real payment id).

## Tests

`backend/tests/`: `test_idempotency_key.py`, `test_order_state_machine.py`,
`test_order_repository_concurrency.py` (real threads),
`test_signature_verification.py` (real HMAC, no network),
`test_payment_policy_rules.py`, `test_payment_flow_integration.py` (LLM
stubbed, Razorpay order-creation mocked, everything else — signatures, DB,
state machine, idempotency, cart reset — real). 30 new tests, all passing,
none requiring network access. Full suite: 84 passing.

## Config additions (`.env`)

```
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
```

`RAZORPAY_CURRENCY` defaults to `INR` in `app/core/config.py`, overridable
like every other threshold in this project.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/agent/chat` / `/api/agent/confirm` | unchanged from Layer 1 — `initiate_payment` is just another tool; a successful confirm now also returns a `payment` object with Checkout params |
| POST | `/api/payments/verify` | `{razorpay_order_id, razorpay_payment_id, razorpay_signature}` → verifies HMAC, marks the order PAID/FAILED |
| POST | `/api/payments/failed` | `{razorpay_order_id, error_code?, error_description?}` — records a client-reported decline, no signature to check |

## Frontend

Razorpay Checkout.js is loaded globally (`layout.tsx`). `ChatPanel` opens it
automatically the moment a confirm response carries `payment` params — no
second "pay" button of our own; Razorpay's own modal button is that step.
Success and `payment.failed` both route through the same
verify/failed endpoints and post the result back into the chat as a message.

## Known limitations (by design, for this layer)

- No webhook handling — verification is purely the browser-callback path
  (Checkout's `handler` + `payment.failed`). A user closing the tab mid-
  payment before the callback fires would leave the order in
  `AWAITING_CONFIRMATION` indefinitely; a webhook listener would close that
  gap but is out of scope here.
- Razorpay test-mode UI quirks discovered live, worth knowing if you retest
  this by hand: the contact-details step rejects obviously-fake numbers like
  `9999999999`/`9876543210` (use something like `8123456790`); `4111 1111
  1111 1111` is flagged as an unsupported international card on this
  account — use a domestic test card instead (e.g. the Mastercard number
  above); the bank OTP simulation accepts `1221`.
