# Layer 1 — Agent harness + policy engine

No payment code in this layer — that's Layer 2. This layer adds an AI agent
on top of the Layer 0 catalog/cart, wrapped in a policy engine that gates
every money-affecting action.

## The core idea

**The agent proposes; the policy engine decides.** The LLM never executes a
tool call directly — it can only *ask* for one. Every proposed action is
evaluated by a set of deterministic Python rules before anything happens to
the cart. Rules never live in the prompt, because a model can be talked out
of a prompt instruction; it cannot talk its way past code it never touches.

```
user message
    │
    ▼
harness loop (app/agent/harness.py) ── MAX_ITERATIONS bounded
    │
    ├─ LLM gateway (app/llm/gateway.py) → proposes a tool call
    │
    ├─ policy engine (app/policy/) → ALLOW / DENY / REQUIRE_CONFIRMATION
    │     evaluates the proposed CART STATE, never the chat text
    │
    ├─ DENY        → reason fed back to the model as the tool result, loop continues
    ├─ CONFIRM     → loop halts, waits for POST /api/agent/confirm
    └─ ALLOW       → tool actually executes (app/agent/tools.py, thin wrappers
                      over the Layer 0 service layer)
    │
    ▼
every step above is written to audit_events (app/audit/) — append-only
```

## Why Agno, but not `Agent.run()`

Agno's `Model.invoke()` is a single raw call: messages + tools in, one
proposed response out — nothing executes. That's exactly the primitive the
harness needs. Agno's higher-level `Agent.run()` / `Model.response()` loop
was deliberately **not** used because it auto-executes tool calls internally
— there'd be nowhere to insert the policy gate between proposal and
execution. `app/llm/gateway.py` uses `agno.models.nvidia.Nvidia` purely as a
typed HTTP transport (it wraps the `openai` SDK against NIM, with error
classes that carry a status code — what makes retry/fallback logic clean).

## The policy engine — the actual product

`app/policy/` has zero dependency on the DB, the LLM, or FastAPI. A rule is
one class with an `evaluate(ProposedCartState) -> RuleResult | None` method.
`ProposedCartState` is a plain dataclass built by the harness *before*
calling the engine (resolving the SKU against the real catalog, computing
the cart total the action would produce) — the rules themselves only ever
see that resolved state, never the model's claims about price or stock.

Six rules, in priority order (DENY beats REQUIRE_CONFIRMATION beats ALLOW;
first match wins within each):

| Rule | Checks |
|---|---|
| `UnknownSkuRule` | SKU must exist in the catalog — catches hallucinated products |
| `StockRule` | quantity ≤ available stock |
| `PerItemPriceRule` | unit price ≤ `POLICY_PER_ITEM_MAX_PAISE` |
| `QuantityRule` | quantity ≤ `POLICY_QUANTITY_MAX` |
| `SpendCapRule` | resulting cart total ≤ the session's stated `budget_paise` (falls back to `POLICY_DEFAULT_SPEND_CAP_PAISE` if the session never set one — a session is never unbounded) |
| `ConfirmationThresholdRule` | resulting cart total > `POLICY_CONFIRMATION_THRESHOLD_PAISE` → soft gate, not a denial |

Adding a rule means adding one class and one line in
`policy/engine.py::default_policy_engine()` — never touching an if-chain.
All six are unit-tested in `backend/tests/test_policy_rules.py` with plain
dataclasses, zero network/DB calls.

## Sessions, budget, and the cart

`session_id` (from the client) is a **conversation/audit thread**, separate
from the cart. The cart is still the one Layer 0 built — one active cart per
`user_id` (`user_demo`). This means chat and the manual "Add to cart" button
share the same real cart, and Layer 0's schema needed zero changes.

The budget is explicit and sticky: the frontend sends `budget_paise` once
(the "Budget ₹" field), it's stored on the `agent_sessions` row, and every
later message in that session enforces it — `SpendCapRule` never re-derives
a budget by reading the chat text.

## Confirmation flow

When `ConfirmationThresholdRule` (or any future soft-gate rule) fires, the
harness stops entirely and persists the pending tool call on the session row
(`pending_tool_call`, `pending_rule_name`, `pending_reason`). No new chat
message is accepted for that session until `POST /api/agent/confirm`
resolves it — `{"session_id", "approve": true|false}`. Approving executes
the held tool call and resumes the loop; declining feeds a "user declined"
result back to the model and resumes the loop from there.

## Handling a flaky model

Free-tier models occasionally: return malformed tool-call JSON, propose a
tool that doesn't exist, or retry a just-denied action with different
arguments. The harness assumes all of this will happen:

- Malformed/unparseable arguments → treated as a denial-shaped tool result
  (`malformed_tool_call` audit event), fed back to the model, loop continues.
- Unknown tool name → same pattern (`unknown_tool` event).
- A denied action → the reason is fed back as the tool result; the system
  prompt tells the model not to retry with different arguments, but nothing
  *enforces* that at the protocol level — the policy engine will just deny it
  again. `MAX_ITERATIONS` (default 8) is the actual backstop: if the model
  keeps trying, the loop stops and says so rather than spinning forever.
- Multiple tool calls in one model turn → only the first is evaluated/
  executed; the rest get an explicit "skipped, one call per turn" result
  (still required by the OpenAI tool-call protocol — every `tool_call_id` in
  a turn needs a matching result) and are reconsidered by the model next turn.

## LLM gateway: retry and fallback

`app/llm/gateway.py` is the only place in the codebase that talks to an LLM.
Per call: up to `LLM_MAX_RETRIES` retries with exponential backoff on 429s
and 5xx/timeouts (anything else fails immediately — no point retrying a bad
request). If the primary model (`LLM_MODEL`) exhausts its retries, the
gateway retries once against `LLM_FALLBACK` and records `fallback_used` in
the log line. This was observed live during testing: a 30s timeout on the
primary model triggered a retry, succeeded on attempt 2 — the retry path is
real, not theoretical.

Every call logs (structured JSON, via the existing Layer 0 logging
middleware): model id, attempt number, latency, tool-call count, token
counts, cost, and outcome. Token counts (`prompt_tokens`/`completion_tokens`/
`total_tokens`) come straight from the OpenAI-compatible response's `usage`
object — Agno's `MessageMetrics` parses that 1:1, so the gateway reads it
from there rather than re-parsing the raw response. `cost_paise =
total_tokens * LLM_COST_PAISE_PER_TOKEN` (default `0.0` — NVIDIA's current
tier is free); the plumbing is real today, so the number becomes real the
day the rate isn't zero, with no code changes.

## Audit log

`audit_events` is append-only **by construction**, not by convention:
`app/audit/repository.py` defines exactly two methods, `create` and
`list_for_session` — there is no `update` or `delete` anywhere in the
module, and nothing else in the codebase touches that table. Every step of
the harness loop writes a row: user message, model call, tool call proposed,
policy decision (with the rule name and reason), tool executed, final
response. `AuditService.log_event()` commits immediately, independent of
whatever happens later in the same request.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/agent/chat` | `{session_id, message, budget_paise?}` → reply, cart, policy status |
| POST | `/api/agent/confirm` | `{session_id, approve}` → resolves a pending action, resumes the loop |
| GET | `/api/audit/{session_id}` | `{session_id, events, totals}` — full event trail in order, plus session totals (model calls, prompt/completion/total tokens, cost, fallback-used count) computed from the `model_call` events |

## Frontend

`ChatPanel` sits between the product grid and the cart sidebar. `session_id`
is a client-generated UUID persisted in `localStorage` (so a page refresh
keeps the same conversation). A confirmation banner shows the rule name and
reason and blocks new messages until Confirm/Decline is resolved — matching
the harness, which also refuses new messages mid-confirmation. An "audit
trail" toggle fetches and renders the full `GET /api/audit/{session_id}`
table inline, so the policy decisions are visible without opening devtools.

## Tests

`backend/tests/`:
- `test_policy_rules.py` — every rule individually, the engine's priority
  ordering, and the two definition-of-done scenarios (hallucinated SKU,
  over-budget add), all via `default_policy_engine()` with zero network/DB.
- `test_audit_append_only.py` — appending never mutates prior rows; the
  repository/service classes expose no update/delete.
- `test_harness_integration.py` — the full loop with the LLM gateway
  stubbed (scripted responses, no network calls): hallucinated SKU denied,
  spend cap denied, an allowed add actually lands in the cart, and the full
  confirm/resume round-trip.
- `test_gateway_cost.py` — `cost_paise` arithmetic (zero by default, scales
  with the configured rate, rounds correctly, `None` when tokens unknown).
- `test_audit_append_only.py` also covers `compute_totals`: aggregates only
  `model_call` events, ignores everything else in the trail.

All 36 tests run in under 3 seconds with no network access.

## Verified live (real NVIDIA NIM calls, real browser)

- "I need dog food under ₹800" → agent searched, found two matches
  (Pedigree ₹740, Drools ₹399), asked which one (genuine ambiguity — this is
  correct caution, not a bug) → "the Pedigree one" → added.
- "Add the OnePlus earphones too" (₹1,999, cart already at ₹740, budget
  ₹800) → **denied** by `SpendCapRule`, reason and rule name shown to the
  user, cart unchanged.
- A separate confirmation-threshold scenario (in-budget but large purchase)
  correctly halted, showed the Confirm/Decline UI, and completed the add
  after confirming — full round trip through the real browser.
- A live 30-second timeout on the primary model correctly triggered the
  retry path and succeeded on the next attempt.

## Config additions (`.env`)

```
NVIDIA_API_KEY=...
LLM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
LLM_FALLBACK=openai/gpt-oss-120b
```

Everything else (timeouts, retries, policy thresholds, max iterations) has a
default in `app/core/config.py` and can be overridden via env vars — nothing
is hardcoded inline. See that file for the full list
(`LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_RETRY_BACKOFF_SECONDS`,
`LLM_COST_PAISE_PER_TOKEN`, `AGENT_MAX_ITERATIONS`,
`POLICY_DEFAULT_SPEND_CAP_PAISE`, `POLICY_PER_ITEM_MAX_PAISE`,
`POLICY_QUANTITY_MAX`, `POLICY_CONFIRMATION_THRESHOLD_PAISE`).

## How to run it (PowerShell)

**Backend** (same as Layer 0, now with the agent endpoints live):
```powershell
cd backend
..\venv\Scripts\Activate.ps1
python -m alembic upgrade head    # only needed once, for the new tables
python -m uvicorn app.main:app --host 127.0.0.1 --port 8842 --reload
```

**Run the tests:**
```powershell
cd backend
..\venv\Scripts\Activate.ps1
python -m pytest -v
```

**Frontend:** unchanged from Layer 0 — `npm run dev` in `frontend/`.

## Known limitations (by design, for this layer)

- Search is still Layer 0's plain substring match — a multi-word query like
  "OnePlus earphones" won't match "OnePlus Bullets Wireless Z2 Earphones"
  unless the words appear as one contiguous phrase. The agent handles a miss
  by asking for a more specific name rather than guessing a SKU. Better
  search is a Layer 5 concern, not a policy concern.
- The cart is shared per `user_id`, not per session — fine for a single-demo-
  user buildathon submission, would need to change alongside real auth.
- No streaming — the frontend waits for the full harness loop to finish
  (can be 10–90s with a free-tier model across several tool-call turns).
