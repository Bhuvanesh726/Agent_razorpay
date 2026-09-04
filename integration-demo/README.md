# Kirana Mart — third-party merchant integration demo

A fictional external merchant that gets a full agentic shopping assistant by
doing exactly one thing: **sending an API key we issued in an HTTP header.**

This folder is deliberately dumb. It is three static files and a ~140-line
standard-library Python server:

```
integration-demo/
  index.html    markup
  app.js        ~330 lines of vanilla JS — fetch() and DOM, nothing else
  styles.css    plain CSS
  serve.py      stdlib-only static server + /api reverse proxy
  README.md     this file
```

**There is no AI in here.** No `openai`, no `anthropic`, no `agno`, no NVIDIA
key, no model SDK, no prompt, no `requirements.txt`, no `package.json`, no
build step. Every intelligent behaviour on the page — understanding
"add 2 packs of Tata Salt", choosing the SKU, applying spend limits, deciding
that a payment needs human confirmation, generating the upsell — happens on
*our* side, behind the key. That is the entire point: **we are the service
provider, and this is what integrating with us costs a merchant.**

---

## 1. Run it

**Prerequisites:** the platform backend running at `http://127.0.0.1:8842`
(`docker compose up` at the repo root, or `uvicorn app.main:app --port 8842`
from `backend/`). Python 3.9+ for the demo server. Nothing to install.

```bash
cd integration-demo
python serve.py                  # http://127.0.0.1:3000
python serve.py --port 3100      # if the main Next.js frontend already owns 3000
```

Then open the printed URL and paste an agent key (see §2).

`serve.py` serves the three static files and reverse-proxies `/api/*`,
`/health` and `/.well-known/*` to the backend. That proxy exists only to make
CORS a non-issue — see §4. It forwards your `X-Agent-Key` header untouched and
relays the backend's status codes verbatim (a 401 for a bad key and a 403 for
a forbidden endpoint must reach the page as-is, not become a proxy error).

### Alternative: no proxy at all

If you would rather use nothing but the stock Python static server:

```bash
python -m http.server 3000 --bind 127.0.0.1     # from integration-demo/
```

`app.js` probes `/health` on its own origin at boot; when that 404s (as it does
with the stock server) it falls back to calling `http://127.0.0.1:8842`
directly. **That only works on port 3000** — see §4 — and only while the main
Next.js frontend is *not* running, since it also wants 3000. The footer of the
page always tells you which mode is active.

---

## 2. Get an EXTERNAL agent key

An agent credential belongs to a **buyer**, and its raw key is shown **exactly
once, at creation** — only the SHA hash is stored
(`backend/app/auth/credentials_router.py::create_agent`). There is no
"show key again" endpoint, by design.

**Through the product UI (the real flow):**

1. Sign in to the main frontend at `http://127.0.0.1:3000` with Google, as a BUYER.
2. Go to the agents / credentials page and create a new agent.
3. Set **delivery mode = EXTERNAL**. This matters: an `EMBEDDED` credential
   never emits a plaintext key at all — the buyer runs it from inside the app,
   so there is nothing for a third party to hold.
4. Give it scopes. For this demo you want at least
   `search_products, get_product, add_to_cart, view_cart, remove_from_cart, initiate_payment, decline_upsell`.
5. Set a spend limit (paise). It is a hard cumulative cap across every run of
   that credential, enforced by `AgentSpendLimitRule`.
6. **Copy the key now.** Paste it into this demo's key bar and press *Connect*.

**Headless shortcut (dev only), if you don't want to do the Google round-trip:**

```bash
cd backend
python scripts/create_agent_credential.py --name "Kirana Mart Demo" --spend-limit-paise 300000

# or, if the backend is the docker container (it uses its own volume DB):
docker exec razorpay-agent-backend-1 \
  python scripts/create_agent_credential.py --name "Kirana Mart Demo" --spend-limit-paise 300000
```

That script performs the identical database write the `POST /api/agents`
endpoint would, and prints the raw key once.

The key is kept in this browser's `localStorage` under `kiranamart.agentKey`.
*Delete key* removes it. Revoking the credential in the platform UI kills it
server-side regardless of what this browser still holds.

---

## 3. The entire integration surface

Four endpoints. That's it.

| What the merchant wants | Call | Auth |
|---|---|---|
| Show a product grid | `GET /api/products?page_size=5` | none — `@public` |
| Search the catalog | `GET /api/products?search=coffee` | none — `@public` |
| Verify the pasted key & show who it is | `GET /api/auth/me` | `X-Agent-Key` |
| The whole shopping agent | `POST /api/agent/chat` | `X-Agent-Key` |
| Approve / decline a gated action | `POST /api/agent/confirm` | `X-Agent-Key` |

```
X-Agent-Key: agentkey_...
```

An external agent authenticates with that raw-secret header, **not** a
`Authorization: Bearer` JWT. Humans use the JWT; software uses the key. The two
trust mechanisms are deliberately not interchangeable —
`backend/app/auth/principal.py` resolves each into a different `Principal` type,
and `backend/app/auth/routing.py` gates every route on that type, default-deny.

### What identity resolution actually returns

`GET /api/auth/me` is the **only** endpoint in the platform that both accepts
`AuthRequirement.AGENT` and answers "who am I". For an agent key it returns:

```json
{ "type": "agent", "user_id": "user_demo", "email": null,
  "role": null, "credential_id": "agent_91e2cc4935a84d59" }
```

So the demo can prove the key is live, that it resolves to a *software*
principal, and which buyer it acts for. It **cannot** read back the
credential's display name, its scope list, or its spend limit: those live on
`GET /api/agents/{credential_id}`, which is BUYER-only and answers this key
with `403 Not authorized for this endpoint.` The buyer sees them when they
create the credential and in the platform's own agent UI. A holder of the key
learns its limits the way any bearer does — by hitting them and reading the
policy denial that comes back.

### What the demo deliberately does **not** call

`/api/cart`. Those REST endpoints are BUYER-only and reject an agent key with
403, on purpose: they mutate the cart with no policy engine in front of them,
so letting an agent reach them would be a genuine bypass of
`RevokedCredentialRule` / `AgentScopeRule` / `AgentSpendLimitRule`
(`backend/app/routers/cart.py`, module docstring). The cart panel in this demo
is rendered entirely from the `cart` object that every `ChatResponse` carries.

### The confirmation handshake

`POST /api/agent/chat` can come back with `status: "awaiting_confirmation"` and
a `pending` block naming the tool, the rule that stopped it, and why:

```json
{ "status": "awaiting_confirmation",
  "pending": { "tool_name": "initiate_payment",
               "rule_name": "PaymentAuthorizationRule",
               "reason": "Cart re-validated: 2 item(s), total ₹917.00. Confirm to proceed to payment." } }
```

The merchant must then call `POST /api/agent/confirm` with
`{ "session_id": ..., "approve": true|false }`. The demo renders that as the
amber Confirm/Decline panel. The merchant does not get to skip it; the platform
will not charge anyone on an unconfirmed turn.

Responses may also carry `upsell`, `product_suggestion` and `payment` — the
demo renders all three as cards under the reply.

**Latency warning:** a chat turn is a real multi-step agent run. 30–120 seconds
is normal, and longer when the upstream model provider is slow and the platform
falls back. `serve.py` uses a 300 s proxy timeout for exactly this reason.

---

## 4. CORS — read this before changing ports

The backend allows **exactly one** browser origin:

```python
# backend/app/main.py
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], ...)
```

and `settings.frontend_url` defaults to `http://127.0.0.1:3000`. It is a single
string, not a list, deliberately — `localhost` and `127.0.0.1` are different
origins, and supporting both invites a whole class of cookie/CORS bug.

A preflight from any other origin is rejected outright:

```
$ curl -i -X OPTIONS -H "Origin: http://127.0.0.1:3100" \
    -H "Access-Control-Request-Method: POST" \
    http://127.0.0.1:8842/api/agent/chat
HTTP/1.1 400 Bad Request
Disallowed CORS origin
```

**Three ways to live with that, in order of preference:**

1. **Run `serve.py` (the default).** It proxies `/api/*`, so from the browser's
   point of view every call is same-origin and CORS never applies. Works on any
   free port, requires no backend change. This is what the demo ships with.
2. **Serve the folder on `http://127.0.0.1:3000` and call `:8842` directly.**
   That origin is already allowlisted, so it just works — but only while the
   main Next.js frontend is stopped, because it also binds 3000.
3. **Point the backend's allowlist at this demo instead.** Set
   `FRONTEND_URL=http://127.0.0.1:3100` in the repo-root `.env` and restart the
   backend (`docker compose up -d --force-recreate backend`). **This is the
   destructive option:** `frontend_url` is one value, so doing this breaks CORS
   *and* every post-login OAuth redirect for the real frontend. Don't, unless
   the main frontend is down for good.

No backend file was modified to make this demo work, and none needs to be.

---

## 5. What this demo proves

- **Our API is usable as a service by a third party.** A merchant with no ML
  team, no model budget and no vector store ships a working shopping agent by
  pasting a key into a static page.
- **The intelligence is genuinely ours.** Grep this folder: no provider SDK, no
  model name, no prompt, no key of our own. Cut the network to `:8842` and the
  page becomes a dead product list.
- **The trust boundary holds under a real client.** The same key that unlocks
  `/api/agent/chat` is refused by `/api/cart` and `/api/agents` with a 403.
  Agents don't get buyer powers just because they're authenticated.
- **Policy travels with the API, not the client.** Payment confirmation, spend
  limits and scope checks are enforced server-side. The merchant's UI can't
  opt out of them; the best it can do is render the confirmation prompt nicely.
- **Identity is honest about its own limits.** The credential can prove *that*
  it is an agent and *whose* agent it is, and cannot read its own leash.
