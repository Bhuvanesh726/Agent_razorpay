#!/usr/bin/env python
"""An external AI shopping agent — a different "company's" agent, deliberately
isolated from the merchant it's buying from:

  - No import of anything under backend/app. Every fact it acts on (what's
    for sale, how to buy, what things cost) comes from the merchant's public
    HTTP surface, exactly like a real third-party integrator would see it.
  - No shared DB session, no direct SQL, no filesystem access into the
    merchant's project.
  - No login, no browser, no consent screen — this is Layer 4.7's Mode B
    (external) agent credential. It authenticates every call with
    X-Agent-Key, a bounded, revocable secret bound to a specific buyer and
    scoped to a specific set of tools, shown to a human exactly once at
    creation (see docs/047-principals.md). Get one with:
        python backend/scripts/create_agent_credential.py
    then either export AGENT_API_KEY=<key> or pass --agent-key <key>.
  - Every cart mutation goes through /api/agent/chat, never the raw
    /api/cart REST endpoints — those are deliberately BUYER-only (see
    backend/app/routers/cart.py) precisely so an agent can't bypass the
    policy engine (RevokedCredentialRule, AgentScopeRule,
    AgentSpendLimitRule) that only runs in front of the chat path. That
    includes clearing out any leftover cart from a previous run, which used
    to be a direct REST reset and is now its own chat turn.
  - No access to the merchant's Razorpay key_secret — real Checkout
    verification needs either a browser (which this headless script doesn't
    drive) or that secret, and a genuine external buyer has neither. This
    project's own dev-only /api/payments/test-complete endpoint stands in
    for completing the browser round-trip; buyer_agent calls it directly by
    URL (not because the merchant "told" it to — that endpoint is
    deliberately absent from the discovery document, since it's this
    project's own headless-testing convenience, not a real capability an
    external integrator should build against). See docs/045-catalog.md.

Two scenarios, run by default:
  1. A generously-budgeted purchase: discover the merchant, read the feed,
     build a small basket within budget, buy it, and accept an upsell offer
     if one appears and still fits.
  2. A tightly-budgeted purchase: same flow, but the budget is deliberately
     sized so any upsell offered would breach the spend cap — the offer
     must never appear, and the audit trail must show why.

    python backend/scripts/create_agent_credential.py   # once, to get a key
    export AGENT_API_KEY=agentkey_...
    python buyer_agent/buyer.py
    python buyer_agent/buyer.py --base-url http://127.0.0.1:8842 --agent-key agentkey_...
"""

import argparse
import json
import os
import random
import sys
import uuid
from urllib import error, request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def _step(text: str) -> None:
    print(f"\n--- {text} ---")


def _call(base_url: str, method: str, path_or_url: str, body: dict | None = None, headers: dict | None = None) -> dict:
    """path_or_url may be a path ('/health') or a full URL — full URLs come
    straight from the discovery document rather than being reconstructed
    from a path, so there's exactly one place that ever assembles a URL
    from a hardcoded path (this function, for the well-known/health/feed
    lookups this agent is allowed to know about in advance)."""
    url = path_or_url if path_or_url.startswith("http") else f"{base_url}{path_or_url}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        detail = e.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from e


def discover(base_url: str) -> dict:
    """The only thing hardcoded is the well-known path itself — everything
    this agent does next comes from what that document says."""
    _step(f"Discovering merchant at {base_url}/.well-known/catalog.json")
    doc = _call(base_url, "GET", "/.well-known/catalog.json")
    print(f"  merchant: {doc['merchant']['name']} (currency={doc['merchant']['currency']}, env={doc['merchant']['environment']})")
    print(f"  capabilities: {', '.join(doc['capabilities'])}")
    return doc


def fetch_full_feed(base_url: str, feed_url: str) -> list[dict]:
    _step(f"Reading the product feed at {feed_url}")
    items: list[dict] = []
    page = 1
    while True:
        body = _call(base_url, "GET", f"{feed_url}?page={page}&page_size=50")
        items.extend(body["items"])
        if len(items) >= body["total"]:
            break
        page += 1
    print(f"  {len(items)} products across {page} page(s)")
    return items


def build_basket(feed_items: list[dict], budget_paise: int, max_items: int = 3) -> list[dict]:
    """Not LLM-driven — the point of this script is proving the
    *transaction* path end to end, not simulating LLM shopping judgment
    (the merchant side already proves that). Picks from the priciest
    in-stock item per category, added while it still fits the budget: a
    basket of the *cheapest* item per category was tried first and
    reliably produced carts too small (a few tens of rupees) for any real
    upsell pairing to fit under UpsellPolicyRule's percentage-of-cart cap —
    this is a more representative "what would someone with this budget
    actually buy" basket, and leaves room to demonstrate an offer actually
    being accepted, not just blocked.

    The order among comparably-priced candidates is shuffled rather than a
    strict sort — a purely deterministic basket picks the *exact same*
    combination every run, which (like demo.py found in Layer 4) collides
    with its own prior purchase forever once paid once: the idempotency key
    is a permanent hash of (user, cart contents, amount), so a fixed basket
    burns itself out after one successful run. Variety here isn't about
    simulating judgment — it's what makes this script safely re-runnable.
    """
    in_stock = [i for i in feed_items if i["availability"] == "in_stock"]
    by_category: dict[str, dict] = {}
    for item in in_stock:
        current = by_category.get(item["category"])
        if current is None or item["price_paise"] > current["price_paise"]:
            by_category[item["category"]] = item

    candidates = sorted(by_category.values(), key=lambda i: i["price_paise"], reverse=True)

    def _fill(pool: list[dict]) -> list[dict]:
        basket: list[dict] = []
        total = 0
        for item in pool:
            if len(basket) >= max_items:
                break
            if total + item["price_paise"] > budget_paise:
                continue
            basket.append(item)
            total += item["price_paise"]
        return basket

    # Shuffle within a pool of the priciest candidates (not the whole list —
    # that would undermine "priciest first" and could produce a tiny basket
    # again) so repeated runs don't always land on the exact same basket.
    premium_pool = candidates[: max_items * 3]
    random.shuffle(premium_pool)
    basket = _fill(premium_pool)
    if basket:
        return basket
    return _fill(candidates)  # tight budget: nothing in the premium pool fit alone — try everything


def build_tightest_single_item_basket(feed_items: list[dict], budget_paise: int) -> list[dict]:
    """For the upsell-blocked scenario specifically: the single priciest
    in-stock item that still fits the budget, leaving minimal headroom.
    Deliberately not the same variety-shuffled build_basket() above — a
    shuffled multi-item basket could randomly leave enough headroom for a
    cheap upsell to fit, which would make this scenario stop demonstrating
    the thing it's named for. Unlike build_basket(), this is fully
    deterministic (same item every run), which does mean a repeat run in
    the same dev session can hit its own prior purchase via the permanent
    idempotency key (see docs/045-catalog.md) rather than paying fresh —
    itself a correct, if not this scenario's intended, demonstration."""
    in_stock = [i for i in feed_items if i["availability"] == "in_stock" and i["price_paise"] <= budget_paise]
    if not in_stock:
        return []
    return [max(in_stock, key=lambda i: i["price_paise"])]


def _send(
    base_url: str, chat_url: str, confirm_url: str, session_id: str, message: str, headers: dict, budget_paise: int | None = None
) -> dict:
    """Send a chat message and, if it comes back needing confirmation for
    anything other than payment (e.g. ConfirmationThresholdRule on a
    pricier add — very possible once a real basket includes anything over
    ₹1,000), approve it immediately. A real user saying "yes, go ahead" to
    a single pending add is the ordinary case, not a special one — payment
    confirmations are handled explicitly by the caller instead, since that
    step needs its own retry and reporting."""
    body: dict = {"session_id": session_id, "message": message}
    if budget_paise is not None:
        body["budget_paise"] = budget_paise
    res = _call(base_url, "POST", chat_url, body, headers)
    if res["status"] == "awaiting_confirmation" and (res.get("pending") or {}).get("tool_name") != "initiate_payment":
        res = _call(base_url, "POST", confirm_url, {"session_id": session_id, "approve": True}, headers)
    return res


def run_purchase(base_url: str, headers: dict, *, budget_paise: int, label: str, basket_builder=build_basket) -> dict:
    _banner(f"SCENARIO: {label} (budget ₹{budget_paise / 100:.2f})")
    doc = discover(base_url)
    feed_items = fetch_full_feed(base_url, doc["endpoints"]["catalog_feed"])

    basket = basket_builder(feed_items, budget_paise)
    if not basket:
        print("  no basket fits this budget — nothing to buy.")
        return {"session_id": None, "bought": [], "upsell_offer": None, "upsell_accepted": False, "paid": False}

    session_id = f"buyer-{uuid.uuid4().hex[:8]}"
    chat_url = doc["endpoints"]["chat"]
    confirm_url = doc["endpoints"]["confirm"]

    # /api/cart is BUYER-only (see backend/app/routers/cart.py) — an agent
    # clears out any leftover cart from a prior run the same way it does
    # everything else, through the policy-engine-fronted chat path, not a
    # raw REST call it isn't scoped for.
    _step(f"Clearing any existing cart via chat (session {session_id})")
    _send(base_url, chat_url, confirm_url, session_id, "Please remove every item currently in my cart, if any.", headers)

    _step("Building a basket within budget")
    running_total = 0
    last_upsell = None
    for item in basket:
        res = _send(
            base_url, chat_url, confirm_url, session_id, f"Add one {item['title']} to my cart.", headers, budget_paise
        )
        running_total = res["cart"]["total_paise"]
        print(f"  + {item['title']} (₹{item['price_paise'] / 100:.2f}) -> cart total ₹{running_total / 100:.2f}")
        if res.get("upsell"):
            last_upsell = res["upsell"]

    upsell_accepted = False
    if last_upsell is not None:
        _step(f"Merchant offered an upsell: {last_upsell['name']} (₹{last_upsell['price_paise'] / 100:.2f}) — {last_upsell['reason']}")
        if running_total + last_upsell["price_paise"] <= budget_paise:
            res = _send(base_url, chat_url, confirm_url, session_id, f"Yes, add the {last_upsell['name']} too.", headers)
            running_total = res["cart"]["total_paise"]
            upsell_accepted = res.get("upsell") is None and running_total > sum(i["price_paise"] for i in basket)
            print(f"  accepted -> cart total ₹{running_total / 100:.2f}")
        else:
            _send(base_url, chat_url, confirm_url, session_id, "No thanks.", headers)
            print("  declined — doesn't fit the remaining budget")
    else:
        print("\n  no upsell offered this session (none allowed by policy, or none relevant).")

    _step("Requesting payment")
    res = _call(base_url, "POST", chat_url, {"session_id": session_id, "message": "Pay for my cart now."}, headers)
    if res["status"] != "awaiting_confirmation":
        print(f"  unexpected status '{res['status']}' — not proceeding to payment.")
        return {
            "session_id": session_id, "bought": basket, "upsell_offer": last_upsell,
            "upsell_accepted": upsell_accepted, "paid": False,
        }

    res = _call(base_url, "POST", confirm_url, {"session_id": session_id, "approve": True}, headers)
    payment = res.get("payment")
    if payment is None:
        # The Razorpay test API is occasionally slow/flaky — the same class
        # of transient failure demo.py already found and retries. One retry
        # mirrors what a real (im)patient buyer would do; the harness's own
        # retry path is "ask again, then confirm again" (a failed confirm
        # clears the pending state, so re-confirming directly does nothing).
        print(f"  payment was not initiated ({res['reply'][:150]!r}) — retrying once")
        res = _call(base_url, "POST", chat_url, {"session_id": session_id, "message": "Please try paying again."}, headers)
        if res.get("status") == "awaiting_confirmation":
            res = _call(base_url, "POST", confirm_url, {"session_id": session_id, "approve": True}, headers)
            payment = res.get("payment")
    if payment is None:
        print(f"  payment was not initiated: {res['reply'][:200]}")
        return {
            "session_id": session_id, "bought": basket, "upsell_offer": last_upsell,
            "upsell_accepted": upsell_accepted, "paid": False,
        }
    print(f"  order created: razorpay_order_id={payment['razorpay_order_id']}, amount=₹{payment['amount_paise'] / 100:.2f}")

    # NOT part of the discovered contract — see the module docstring. A real
    # external buyer would complete Razorpay Checkout in a browser here.
    # AGENT-authorized (unlike /api/payments/verify and /failed, which stay
    # BUYER-only for the real browser callback) precisely so this headless
    # agent can reach it — see backend/app/routers/payments.py.
    _step("Completing payment (this project's headless test-complete endpoint — see module docstring)")
    result = _call(
        base_url, "POST", "/api/payments/test-complete", {"razorpay_order_id": payment["razorpay_order_id"]}, headers
    )
    print(f"  {result['status']}: {result['message']}")

    return {
        "session_id": session_id,
        "bought": basket,
        "upsell_offer": last_upsell,
        "upsell_accepted": upsell_accepted,
        "paid": result["status"] == "PAID",
    }


def report(base_url: str, headers: dict, session_id: str | None) -> None:
    if session_id is None:
        return
    _step(f"Audit trail totals for {session_id} (this agent's own credential may read its own runs — see backend/app/routers/audit.py)")
    trail = _call(base_url, "GET", f"/api/audit/{session_id}", headers=headers)
    totals = trail["totals"]
    print(
        f"  upsells: proposed={totals['upsell_proposed_count']} accepted={totals['upsell_accepted_count']} "
        f"declined={totals['upsell_declined_count']} blocked={totals['upsell_blocked_count']} "
        f"incremental_revenue=₹{totals['upsell_incremental_revenue_paise'] / 100:.2f}"
    )
    blocked = [e for e in trail["events"] if e["event_type"] == "upsell_blocked"]
    for e in blocked:
        print(f"  blocked: {e['rule_name']} — {e['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="External AI buyer agent — discovers and buys from the merchant over its public API only.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8842")
    parser.add_argument(
        "--agent-key",
        default=os.environ.get("AGENT_API_KEY", ""),
        help="EXTERNAL-mode agent credential key (X-Agent-Key). Defaults to $AGENT_API_KEY. "
        "Mint one with: python backend/scripts/create_agent_credential.py",
    )
    parser.add_argument("--budget-paise", type=int, default=300_000, help="Budget for the generous-scenario run (default ₹3,000).")
    parser.add_argument("--tight-budget-paise", type=int, default=78_000, help="Budget for the upsell-blocked scenario (default ₹780).")
    args = parser.parse_args()

    if not args.agent_key:
        print(
            "No agent credential provided. Set AGENT_API_KEY or pass --agent-key.\n"
            "Mint one with: python backend/scripts/create_agent_credential.py",
            file=sys.stderr,
        )
        return 1
    headers = {"X-Agent-Key": args.agent_key}

    try:
        _call(args.base_url, "GET", "/health")
    except Exception as e:
        print(f"Merchant not reachable at {args.base_url}: {e}", file=sys.stderr)
        return 1

    outcome_1 = run_purchase(
        args.base_url, headers, budget_paise=args.budget_paise, label="generous budget, accept a fitting upsell"
    )
    report(args.base_url, headers, outcome_1["session_id"])

    outcome_2 = run_purchase(
        args.base_url,
        headers,
        budget_paise=args.tight_budget_paise,
        label="tight budget — any upsell should be blocked",
        basket_builder=build_tightest_single_item_basket,
    )
    report(args.base_url, headers, outcome_2["session_id"])

    _banner("Summary")
    print(f"Scenario 1 — bought {len(outcome_1['bought'])} item(s), paid={outcome_1['paid']}, upsell_accepted={outcome_1['upsell_accepted']}")
    print(f"Scenario 2 — bought {len(outcome_2['bought'])} item(s), paid={outcome_2['paid']}, upsell_offer_shown={outcome_2['upsell_offer'] is not None}")
    ok = outcome_1["paid"] and outcome_2["upsell_offer"] is None
    print("Zero internal access used throughout — every fact came from HTTP responses.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
