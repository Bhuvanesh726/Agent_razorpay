# Razorpay Agentic Commerce

An AI shopping agent that can spend a buyer's money — under a limit the buyer set,
through a policy engine that can refuse it, with every decision written to an audit
trail that can be replayed after the fact.

The interesting part is not that an agent can buy things. It's the parts that stop it:
a default-deny router, a policy engine whose payment rule *never* returns `ALLOW`,
per-agent spend limits, idempotency keys with a database-level uniqueness constraint,
and an order state machine that refuses illegal transitions even when a payment
provider says otherwise.

---

## Quick start

You need **Docker only**. No Python, Node, or database install.

```bash
git clone <this repo>
cd razorpay-agent
docker compose up --build
```

Then open **http://127.0.0.1:3000**.

First build takes a few minutes. After that, `docker compose up` starts in seconds.

| | |
|---|---|
| Storefront / dashboards | http://127.0.0.1:3000 |
| API | http://127.0.0.1:8842 |
| Health check | http://127.0.0.1:8842/health |
| Machine-readable catalog | http://127.0.0.1:8842/.well-known/catalog.json |

The backend seeds itself on first start (51 products across 8 categories) into a named
Docker volume, so your data survives `docker compose down` and restarts. To reset to a
clean slate:

```bash
docker compose down -v && docker compose up
```

**You can sign in immediately** — the login page offers a pre-seeded demo buyer and
demo merchant, so a reviewer can get in without registering their own Google OAuth
client. Production posture is Google-only: these principals are gated on
`APP_ENV=development` in code, the same way chaos injection is (`app/testing/demo_login.py`),
so the endpoint that mints their tokens simply 404s anywhere else.

### Use `127.0.0.1`, not `localhost`

They are different origins to a browser. CORS, cookies, and the OAuth redirect are all
registered against `127.0.0.1`. Using `localhost` will appear to work and then fail at
sign-in.

---

## What runs without any credentials

`docker compose up` works with no `.env` at all — every setting has a working default.
Out of the box you get the storefront, catalog, search, cart, the policy engine, the
order state machine, the audit trail, the merchant dashboards, and the full test suite.

Three things need your own keys, because they call third-party services:

| Feature | Needs | Without it |
|---|---|---|
| **Signing in as yourself** | Google OAuth client | Use the demo accounts instead — see below |
| Agent chat | `NVIDIA_API_KEY` | Chat returns an LLM error; everything else works |
| Live payments | Razorpay test keys | Checkout cannot create a Razorpay order |

### Signing in as your own Google account

Google is the only way a *real* human authenticates here — no username/password, no
guest mode. That is deliberate: the project's thesis is that **humans authenticate,
agents are authorized**. The demo principals above exist so that stance doesn't lock a
reviewer out of their own copy; they are development-only by construction, not by
convention.

If you want to sign in as yourself instead:

1. Google Cloud Console → **APIs & Services → Credentials → Create OAuth client ID**
   (type: *Web application*).
2. Under **Authorized redirect URIs**, add **both**:
   - `http://127.0.0.1:8842/api/auth/google/callback`
   - `http://localhost:8842/api/auth/google/callback`
3. `cp .env.example .env` and fill in `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   and a `JWT_SECRET_KEY` (generate with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
4. Pick buyer or merchant at `/onboarding` on first login — role is chosen there, not
   assigned from a config allowlist.
5. `docker compose up --build` (the frontend bakes its API URL at build time, so
   rebuild rather than just restarting if you change `NEXT_PUBLIC_API_URL`).

---

## Please read this before judging the payments

**Razorpay orders in this project are real. Most captured payments are not.**

24 of 25 orders were genuinely created at Razorpay and are verifiable in their
dashboard. Only **one** of them has a payment that Razorpay actually processed. Every
other "captured" payment id (`pay_auto_*`, `pay_test_*`, `pay_demo*`) was signed locally
in test mode and will not resolve in Razorpay's API.

I found this by checking my own claims against Razorpay's live API instead of trusting
my own logs. The UI now labels these simulated captures in place rather than hiding
them.

- **[docs/PAYMENT-REALITY.md](docs/PAYMENT-REALITY.md)** — exactly what is real and what
  is simulated, with specific order and payment ids.
- **[Failures.md](Failures.md)** — what broke and what I got wrong, including a real
  reconciliation gap on order #23 where Razorpay holds a captured ₹275 payment that our
  database records as `FAILED`.
- **[docs/SYSTEM-AUDIT.md](docs/SYSTEM-AUDIT.md)** — a pre-submission sweep of the whole system:
  what was verified against the running app, the four defects it found and fixed, the two metrics
  it found overstated, and what it deliberately did not cover.

To verify any of this yourself against the live API:

```bash
docker compose exec backend python scripts/verify_payments.py
```

---

## Architecture

```
frontend/   Next.js 16 (App Router, React 19), Tailwind v4 design tokens
backend/    FastAPI + SQLAlchemy, SQLite by default
docs/       Design record, one document per build layer
```

The system was built in layers; `docs/00-layer0.md` through `docs/048-demand-loop.md`
are the design record, written as each layer landed.

Load-bearing pieces:

| Concern | Where |
|---|---|
| Default-deny routing (`SecureAPIRoute`, `@requires`) | `backend/app/auth/` |
| Policy engine (scope, spend limit, duplicate, confirmation) | `backend/app/policy/` |
| Order state machine + idempotency | `backend/app/orders/` |
| Razorpay integration (the only place the SDK is touched) | `backend/app/payments/gateway.py` |
| Agent tool-calling loop | `backend/app/agent/harness.py` |
| Audit log + session replay | `backend/app/audit/` |

Two invariants worth knowing:

- `PaymentAuthorizationRule` **never** returns `ALLOW`. It returns
  `REQUIRE_CONFIRMATION` or `DENY`. An agent cannot reach a payment without a human
  confirmation or an explicit standing authorization.
- The order state machine permits `FAILED → {AWAITING_CONFIRMATION, CANCELLED}` but
  **not** `FAILED → PAID`. This is why order #23 is stuck: it is the machine refusing to
  paper over a reconciliation gap. See `Failures.md`.

Postgres is supported but off by default (SQLite keeps a fresh clone to one command):

```bash
docker compose --profile postgres up
```

---

## Tests

```bash
docker compose exec backend python -m pytest -q     # 264 tests
```

---

## Third-party integration demo

`integration-demo/` is a small storefront with **no AI in it at all**. You paste an
agent API token into it, and it drives this project's tools over HTTP. It exists to show
that the agent credential works as a service-provider key for an external app, not just
inside our own UI.
