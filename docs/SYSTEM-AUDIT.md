# System audit

A pre-submission sweep of the whole system, asking one question of every claim the software
makes: **is this measured, derived, or invented?**

Method: read the code, then verify against the running system. Where a claim could be checked by
driving the real thing — real chat turns, a real container in production posture, a real
third-party app holding a real credential — it was, and the observed output is quoted. Nothing
below is asserted from reading alone unless it says so.

Scope: backend (`app/`), frontend, the Docker deployment, and the third-party integration demo.
Two prior audits feed into it and are not repeated here: **[PAYMENT-REALITY.md](PAYMENT-REALITY.md)**
(what is real at Razorpay) and **[../Failures.md](../Failures.md)** (what broke and what was got
wrong).

---

## Summary

| Area | Verdict |
|---|---|
| Authorization surface | **Sound** |
| Policy engine (money bounds) | **Sound** |
| Order state machine + idempotency | **Sound after three fixes** |
| Audit trail | **Sound** — append-only by construction |
| Demand-signal → notification loop | **Real** — verified with live traffic |
| Merchant growth metrics | **2 of 5 were overstated; relabelled** |
| Campaign measurement | **Simulated, and now says so everywhere** |
| Payments | **Orders real, most captures synthetic** — see PAYMENT-REALITY.md |
| Resilience | **Sound** — incl. one unscripted live failure recovered |
| Third-party integration | **Real** — verified end to end |

Five defects were found and fixed during this audit — three in the order state machine and
idempotency, one in error-response handling, one in the conversation history's message counts. Two
claims were found overstated and relabelled. Two further defects were found and fixed while
containerising the project, before this sweep began, and are recorded under Deployment. Nothing was
found that required removing a feature.

---

## Authorization

**Verdict: sound.** Enumerated every route on the running app:

```
routes with NO auth marker: none
/api routes NOT on SecureAPIRoute: none
marker counts: {public: 10, agent: 7, buyer: 28, merchant: 18, pending: 2}
```

Default-deny is structural, not conventional: `SecureAPIRoute` refuses a route with no
`@requires`/`@public` marker, so forgetting one fails closed. All 10 public endpoints are
legitimately public — health, the agent-readable catalog (public by design), the OAuth entry
points, and the code-gated demo login.

Checked for the classic escalation paths and found none:

- **Cart IDOR**: `cart_service.delete_item` verifies `item.user_id != user_id` and returns **404,
  not 403**, so it does not leak which item ids exist.
- **Cross-tenant conversation reads**: a credential belonging to another buyer 404s on ownership;
  right buyer but wrong agent also 404s.
- **Agent escalation**: an agent key presented to `/api/cart` and `/api/agents` gets `403`; a bogus
  key gets `401`. Verified live through the third-party app, not just in tests.

**Note, not a defect**: agents are authorized, never authenticated — `/api/auth/me` is the only
endpoint accepting `AuthRequirement.AGENT` that answers "who am I", and it deliberately exposes only
principal type, credential id and owning buyer. An agent cannot read its own name, scopes or spend
limit; those live on a BUYER-only endpoint.

---

## Money: what actually bounds an agent

**Verdict: sound.** The load-bearing invariant holds by construction:

`PaymentAuthorizationRule` (`app/policy/rules.py`) has **no code path returning `ALLOW`** — every
branch returns `DENY` or `REQUIRE_CONFIRMATION`. It re-validates the entire cart *at payment time*
by replaying each line through the item rules, so a cart that passed when items were added is
checked again against current price, stock and limits before money moves.

`AgentSpendLimitRule` is independent of the session budget and reserves headroom at add-to-cart
rather than at payment. `DENY` beats `REQUIRE_CONFIRMATION` beats `ALLOW` with no special-casing.

Every rule carries a human-readable `reason` built from the actual numbers, and
`PaymentAuthorizationRule` deliberately reports the *underlying* failing rule's name rather than its
own wrapper — so an audit line reads `SpendCapRule`, not a generic wrapper.

**Known limitation, documented not fixed**: removing an item from the cart does not release the
spend-limit headroom it reserved (`docs/047-principals.md`).

---

## Order state machine and idempotency

**Verdict: sound after three fixes made during this audit.**

**Fixed — `FAILED → PAID` was impossible.** Razorpay Checkout can report failure then success within
one session. Refusing the later verified success left order #23 recorded `FAILED` while Razorpay
held a real captured ₹275 payment. The transition is now permitted, because Razorpay is the
authority on whether money moved and our `FAILED` is only a local belief. `mark_paid` is still
reachable only after `gateway.verify_signature()` returns true, so reaching `PAID` still requires an
HMAC verified against the merchant secret. `PAID → FAILED` remains forbidden. The recovery writes a
`payment_recovered_after_failure` audit event rather than silently flipping a status.

**Fixed — repeat failure callbacks 500'd.** `FAILED → FAILED` raised `InvalidTransitionError` on an
ordinary duplicate callback. Now idempotent: the attempt is recorded, the redundant transition
skipped.

**Fixed — a buyer could never re-order the same basket.** The idempotency key was
`user_id + line items + amount`, justified by the reasoning that paying empties the cart so a later
purchase would differ. That reasoning was wrong: a fresh cart refilled with the same items has
identical contents. Reproduced:

```
purchase 1 -> order #1 cart=1 status=PAID  duplicate=False
purchase 2 -> order #1 cart=2 status=PAID  duplicate=True   <- merged into the paid order
```

`cart_id` is now part of the key. Paying marks the cart checked-out and opens a fresh one, so a
genuine repeat purchase gets its own order, while a retry on the *same* unpaid cart still collapses
to one — the case idempotency exists for. Both properties are pinned by tests.

**Still open**: four orders (4, 19, 23, 26) recorded `FAILED` from before these fixes. Nothing
reconciles rows already in the database, and backfilling `PAID` without provider confirmation would
be inventing a payment record. The missing `payment.captured` webhook remains the correct
architectural answer and is not implemented.

---

## Audit trail

**Verdict: sound.** `AuditEventRepository` exposes `create` plus three read methods — there is no
update or delete of an `AuditEvent` anywhere in the codebase. Append-only by construction rather
than by policy.

38 distinct event types, including several most systems never record: `injection_detected`,
`signature_rejected`, `iteration_limit_hit`, `malformed_tool_call`, `control_group_split`,
`upsell_blocked`, `duplicate_payment_prevented`, `payment_recovered_after_failure`.

Session replay distinguishes a chat confirmation from a product-card one-click confirm
(`via=chat` / `via=product_card`) — the two would otherwise be indistinguishable, which would defeat
the point of replaying the trail.

---

## Demand-signal loop and merchant notifications

**Verdict: real. Not mock data, not seeded.** This was checked specifically because seeded
"notifications" would be an easy and invisible fake.

`MerchantNotification` has exactly one producer — `app/demand/aggregation.py::run`, invoked on read
from `app/routers/merchant.py`. No seed script writes to that table.

Verified by driving live traffic rather than reading: five distinct chat sessions asking for a
product the catalog does not stock produced five genuine `DemandSignal` rows
(`category="strawberries"`, `outcome="NO_MATCH"`, the category extracted by the model), crossed the
`max(5, active_buyers × 0.20)` threshold, and raised:

```json
{"type": "UNMET_DEMAND",
 "evidence": {"category": "strawberries", "distinct_buyers": 5, "active_buyers": 1},
 "suggested_action": "5 buyer(s) asked for 'strawberries' and nothing in your catalog matched …"}
```

Two properties worth stating because they are easy to get wrong and were got right:

- **Evidence is aggregate-only** — counts, category, attributes. No `raw_query`, no `session_id`.
  The privacy boundary is enforced by the queries themselves, and asserted in
  `tests/test_demand_signals.py::test_notification_evidence_never_contains_raw_query_or_session_id`.
- **Counted by distinct session, not by signal** — one buyer asking five times raises nothing.

An empty notifications panel means the threshold has genuinely not been crossed. That is correct
behaviour, not a broken feature.

---

## Conversation history

**Verdict: sound after one fix.** Transcripts are read from `agent_messages`, which already stores
them, rather than reconstructed from the audit log — `replay_session` produces an engineering
decision trail (`[agent] tool_executed decision=ALLOW rule=…`), which is right for the merchant
audit viewer and wrong to show a buyer as their own conversation.

**Fixed — the history list lied about message counts.** It advertised "8 messages" for a
conversation that opens with two, because `message_count` counted system prompts, tool results and
tool-call-only assistant turns — rows the transcript never renders. It now uses the same filter the
transcript does, and the startup backfill recomputes unconditionally so counts written under the
older definition self-correct rather than staying wrong.

History is scoped per agent credential and filtered by owning buyer, so a credential id alone cannot
surface another buyer's conversations. Conversations are archived, never deleted: a conversation is
the readable half of a record whose other half is an immutable audit trail, and allowing one to be
erased while the other persists would let the two disagree.

---

## Merchant growth metrics

**Verdict: three of five honest; two were overstated and are now relabelled.** Full write-up in
`Failures.md` entry 4.

| Card | Backed by | Verdict |
|---|---|---|
| Queries received | `DemandSignal` rows from real chat turns | Real |
| Match rate | Derived from those | Real |
| Unmet demand | `NO_MATCH` count | Real |
| ~~Upsell revenue~~ → **Upsell value accepted** | `upsell_accepted` events | **Was overstated** |
| Campaign net margin | `simulate_offer_outcome()` | **Simulated** |

**"Upsell revenue"** summed events logged when a buyer accepts an upsell *into their cart*, not when
a payment is captured — an offer accepted and never paid for counted as revenue. Renamed, with the
sublabel *"added to carts, not captured payments."*

**"Campaign net margin"** is a random draw against a configured conversion probability. It measures
nothing. The campaigns page already said so; the dashboard card — where a merchant sees it first —
did not. Now carries *"simulated outcome."*

Neither number changed. Only the claim about it did. Both were true when written and drifted into
overstatement through naming alone, which is the same failure as `pay_auto_*` ids implying captured
payments: **a label is part of the claim, not decoration on it.**

What *is* real on the campaign side: segmentation is deterministic and LLM-free, the guardrails are
enforced by a rule engine (`DiscountCapRule`, `MarginFloorRule`), the control/treatment split is
recorded as a `control_group_split` audit event, and one campaign path honestly records
`model_used="none (deterministic browse-abandonment offer)"`.

---

## Resilience

**Verdict: sound.** Seven injectable faults (`app/testing/chaos.py`), each writing a
`chaos_fault_injected` audit event so a reviewer never has to take "trust me, I broke it" on faith.
The gate is structural — `APP_ENV=development` only, with no env var or header able to enable it
elsewhere.

Beyond injected faults, the model path has retry → fallback model → circuit breaker. This was
exercised unscripted during testing: the primary model returned 502 on its third attempt, the
fallback 502'd once, then succeeded. The request completed and the cart was still correct.

**Fixed during this audit — every server error was reported to users as a connectivity failure.**
Starlette's `ServerErrorMiddleware` sits outside all user middleware including CORS, so an unhandled
exception reached the browser without `Access-Control-Allow-Origin`; the browser then refused to
expose the response and the frontend could only report *"Could not reach the API"* — about a backend
that was running and had answered. `CORSSafeServerErrorMiddleware` now converts exceptions to
responses *inside* CORS, and logs the traceback that `ServerErrorMiddleware` no longer sees.
Registration order is the whole fix, so a test asserts it directly. Verified live:

```
status: 500   ACAO: http://127.0.0.1:3000
body:   {"detail": "...", "error_type": "RuntimeError", "request_id": "084d022e-..."}
```

---

## Prompt injection

**Verdict: sound, with honest scope.** Catalog text is scanned for instruction-like content and an
`injection_detected` event is written. The defence is not the scanner — it is that **tool results
are never spliced into the system prompt, and the policy engine re-checks any resulting action
regardless of what the model does with it.** The scanner exists to make an attempt visible in the
audit trail, not to be the control.

---

## Third-party integration

**Verdict: real, verified end to end.** `integration-demo/` is a storefront with no model SDK, no
provider key and no inference code — the agent lives entirely behind an issued API key.

The full path was driven through the UI: an EXTERNAL credential created in this project's own
interface (key shown exactly once), pasted into the third-party app, which then resolved
`type: agent, acts for buyer: user_demo_merchant, human email: n/a (software principal)`, ran a real
agent turn, added two items, generated an upsell, and had **₹211.00 of its ₹500.00 limit tracked**
against the credential — with `/api/cart` and `/api/agents` both 403 to that same key.

This is the sharpest available evidence for the "makes a merchant transactable by an AI buyer"
claim, because none of it depends on this project's own UI.

---

## Deployment

**Verdict: sound.** `docker compose up --build` works from a clean clone with no `.env` — verified
by deleting the file and the volumes and running it. The stack seeds itself (51 products, 8
categories) into a named volume.

Two defects were found and fixed getting there: `requirements.txt` was missing three packages the
code imports (`openai`, `requests`, `httpx`) — the app worked only because the developer's venv had
them transitively, and a clean install crashed on startup. And compose hard-required a gitignored
`.env`, so a fresh clone failed instantly; it is now optional.

---

## What this audit did not cover

Stated so the report is not read as broader than it is:

- **No load or concurrency testing.** SQLite with a background title-generation thread is the one
  place concurrent writes are plausible; failures there are caught and degrade to a fallback title,
  but this was not stress-tested.
- **No dependency CVE scan.**
- **No formal threat model.** The authorization checks above are targeted probes, not an exhaustive
  penetration test.
- **Frontend correctness** was verified by driving the UI and checking for console errors, not by
  automated frontend tests — there are none.

---

## Test suite

303 tests, all passing, run inside the container:

```bash
docker compose exec backend python -m pytest -q
```

Tests added during this audit cover each defect it found: repeat purchase, the two order-state
transitions, CORS headers on a 500 (including the middleware ordering that is the actual fix), and
message-count consistency.
