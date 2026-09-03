#!/usr/bin/env python
"""Batch evaluation harness for the policy engine + agent.

    python eval/run.py                 # against the real LLM (see .env)
    python eval/run.py --stub          # deterministic, no network - for CI
    python eval/run.py --scenarios eval/scenarios.yaml --output-dir eval/results

Each scenario runs in an isolated in-memory DB (seeded from the real
catalog), with its own session_id, so scenarios never see each other's cart
state. In --stub mode, the LLM gateway is replaced with a scripted response
built from the scenario's `stub_tool_call` — same harness, same policy
engine, same code path as live mode, just without depending on how a
specific model interprets natural language that day.

The *actual* outcome of a scenario is read back out of the audit log, not
out of the HarnessResult — the same audit trail a person would inspect,
which is the point: this is proof the system is explainable, not just proof
the runner happened to get the right answer.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import yaml  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.agent import harness  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.llm.gateway import GatewayResult  # noqa: E402
from app.llm.gateway import ToolCall as GatewayToolCall  # noqa: E402
from app.repositories import cart_repo, product_repo  # noqa: E402
from app.schemas.cart import CartItemCreate  # noqa: E402
from app.services import cart_service  # noqa: E402

_PRODUCTS_JSON = _BACKEND_DIR / "data" / "products.json"

MUTATING_TOOLS = {"add_to_cart", "initiate_payment"}
REJECTION_EVENTS = {"malformed_tool_call", "unknown_tool"}


@dataclass
class ScenarioResult:
    id: str
    category: str
    message: str
    expected_outcome: str
    expected_rule: str | None
    actual_outcome: str
    actual_rule: str | None
    passed: bool
    model_calls: int
    total_tokens: int
    total_latency_ms: int
    fallback_used: bool
    reply: str
    session_id: str
    # Independent of the base outcome above — a scenario's add_to_cart can
    # be ALLOW while its automatically-triggered upsell offer is separately
    # PROPOSED, BLOCKED, or (no relevant candidate / cap already hit) NONE.
    expected_upsell: dict | None = None
    actual_upsell_outcome: str | None = None
    actual_upsell_sku: str | None = None
    actual_upsell_rule: str | None = None


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    catalog = json.loads(_PRODUCTS_JSON.read_text(encoding="utf-8"))
    for entry in catalog["products"]:
        product_repo.upsert(
            db,
            {
                "sku": entry["sku"],
                "name": entry["name"],
                "brand": entry["brand"],
                "category": entry["category"],
                "price_paise": entry["price_paise"],
                "unit": entry["unit"],
                "stock": entry["stock"],
                "description": entry["description"],
                "tags": entry["tags"],
            },
        )
    db.commit()
    return db


def _reset_cart(db, user_id: str) -> None:
    cart = cart_repo.get_active_cart(db, user_id)
    if cart is not None:
        cart_repo.mark_checked_out(db, cart)
        db.commit()
    cart_repo.get_or_create_active_cart(db, user_id)
    db.commit()


def _apply_setup(db, user_id: str, items: list[dict]) -> None:
    for item in items:
        cart_service.add_item(db, user_id, CartItemCreate(sku=item["sku"], quantity=item["quantity"]))


def _tool_call_response(name: str, arguments: dict) -> GatewayResult:
    return GatewayResult(
        content=None,
        tool_calls=[GatewayToolCall(id="eval-call", name=name, arguments_raw=json.dumps(arguments))],
        model_used="stub-model",
        fallback_used=False,
        latency_ms=1,
    )


def _final_response(content: str) -> GatewayResult:
    return GatewayResult(content=content, tool_calls=[], model_used="stub-model", fallback_used=False, latency_ms=1)


def _run_stub(db, session_id: str, user_id: str, scenario: dict):
    responses = []
    if scenario.get("stub_tool_call"):
        call = scenario["stub_tool_call"]
        responses.append(_tool_call_response(call["name"], call.get("arguments", {})))
    responses.append(_final_response("(stub) done."))
    it = iter(responses)
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(it)):
        return harness.handle_chat(db, session_id, user_id, scenario["message"], scenario.get("budget_paise"), f"eval-{scenario['id']}")


def _run_live(db, session_id: str, user_id: str, scenario: dict):
    return harness.handle_chat(db, session_id, user_id, scenario["message"], scenario.get("budget_paise"), f"eval-{scenario['id']}")


def _extract_outcome(events) -> tuple[str, str | None]:
    for e in reversed(events):
        if e.event_type == "policy_decision" and e.tool_name in MUTATING_TOOLS:
            return e.decision, e.rule_name
        if e.event_type in REJECTION_EVENTS and e.tool_name in MUTATING_TOOLS:
            return "REJECTED", None
    return "ASK", None


def _extract_upsell_outcome(events) -> tuple[str, str | None, str | None]:
    """The upsell offer (if any) that resulted from this scenario's action —
    proposed automatically by the harness after a successful add_to_cart,
    never something the model calls directly. Independent of _extract_outcome:
    a scenario's base action can be ALLOW while its upsell is separately
    PROPOSED, BLOCKED, or NONE (no candidate, or the session cap already hit)."""
    for e in reversed(events):
        if e.event_type == "upsell_proposed":
            return "PROPOSED", (e.tool_args or {}).get("sku"), None
        if e.event_type == "upsell_blocked":
            return "BLOCKED", (e.tool_args or {}).get("sku"), e.rule_name
    return "NONE", None, None


def run_scenario(db, scenario: dict, *, stub: bool) -> ScenarioResult:
    user_id = "eval_user"
    session_id = f"eval-{scenario['id']}-{int(time.time() * 1000)}"

    _reset_cart(db, user_id)
    _apply_setup(db, user_id, scenario.get("setup_cart_items") or [])

    runner = _run_stub if stub else _run_live
    try:
        result = runner(db, session_id, user_id, scenario)
        reply = result.reply
    except Exception as e:  # a scenario blowing up is itself a result worth recording, not a crash
        reply = f"[runner error] {e}"

    events = harness._audit.get_trail(db, session_id)
    actual_outcome, actual_rule = _extract_outcome(events)
    totals = harness._audit.compute_totals(events)

    passed = actual_outcome == scenario["expected_outcome"]
    if passed and scenario.get("expected_rule"):
        passed = actual_rule == scenario["expected_rule"]

    actual_upsell_outcome, actual_upsell_sku, actual_upsell_rule = _extract_upsell_outcome(events)
    expected_upsell = scenario.get("expected_upsell")
    if expected_upsell:
        passed = passed and actual_upsell_outcome == expected_upsell["outcome"]
        if passed and expected_upsell.get("sku"):
            passed = passed and actual_upsell_sku == expected_upsell["sku"]
        if passed and expected_upsell.get("rule"):
            passed = passed and actual_upsell_rule == expected_upsell["rule"]

    return ScenarioResult(
        id=scenario["id"],
        category=scenario["category"],
        message=scenario["message"],
        expected_outcome=scenario["expected_outcome"],
        expected_rule=scenario.get("expected_rule"),
        actual_outcome=actual_outcome,
        actual_rule=actual_rule,
        passed=passed,
        model_calls=totals["total_model_calls"],
        total_tokens=totals["total_tokens"],
        total_latency_ms=sum(e.latency_ms or 0 for e in events if e.event_type == "model_call"),
        fallback_used=totals["fallback_used_count"] > 0,
        reply=reply,
        session_id=session_id,
        expected_upsell=expected_upsell,
        actual_upsell_outcome=actual_upsell_outcome,
        actual_upsell_sku=actual_upsell_sku,
        actual_upsell_rule=actual_upsell_rule,
    )


def _render_markdown(results: list[ScenarioResult], meta: dict) -> str:
    lines = [
        f"# Evaluation run — {meta['timestamp']}",
        "",
        f"Mode: **{meta['mode']}**  |  Model: `{meta['model']}`  |  Scenarios: {meta['total']}",
        "",
        "## Summary",
        "",
        f"- Total: {meta['total']}",
        f"- Passed: {meta['passed']}",
        f"- Failed: {meta['failed']}",
        f"- **False positives (legitimate action wrongly blocked/asked/rejected): {meta['false_positives']}**",
        f"- False negatives (violation wrongly allowed through): {meta['false_negatives']}",
        "",
        "### Outcome breakdown (actual)",
        "",
        "| Outcome | Count |",
        "|---|---|",
    ]
    for outcome, count in meta["outcome_breakdown"].items():
        lines.append(f"| {outcome} | {count} |")

    lines += [
        "",
        "## Results",
        "",
        "| Scenario | Category | Expected | Actual | Rule (exp/act) | Upsell (exp/act) | Pass | Model calls | Tokens | Latency (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rule_pair = f"{r.expected_rule or '—'} / {r.actual_rule or '—'}"
        if r.expected_upsell:
            upsell_pair = f"{r.expected_upsell['outcome']} / {r.actual_upsell_outcome}"
        else:
            upsell_pair = "—"
        mark = "✅" if r.passed else "❌"
        lines.append(
            f"| {r.id} | {r.category} | {r.expected_outcome} | {r.actual_outcome} | {rule_pair} | {upsell_pair} | {mark} | "
            f"{r.model_calls} | {r.total_tokens} | {r.total_latency_ms} |"
        )

    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "## Failed scenarios (detail)", ""]
        for r in failed:
            detail = (
                f"- **{r.id}**: expected `{r.expected_outcome}`"
                + (f" ({r.expected_rule})" if r.expected_rule else "")
                + f", got `{r.actual_outcome}`"
                + (f" ({r.actual_rule})" if r.actual_rule else "")
            )
            if r.expected_upsell:
                detail += (
                    f"; upsell expected `{r.expected_upsell['outcome']}`"
                    + (f" sku={r.expected_upsell['sku']}" if r.expected_upsell.get("sku") else "")
                    + (f" rule={r.expected_upsell['rule']}" if r.expected_upsell.get("rule") else "")
                    + f", got `{r.actual_upsell_outcome}` sku={r.actual_upsell_sku} rule={r.actual_upsell_rule}"
                )
            detail += f" — reply: {r.reply[:200]!r}"
            lines.append(detail)

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-evaluate the policy engine + agent against scenarios.")
    parser.add_argument("--stub", action="store_true", help="Deterministic mode: no LLM network calls.")
    parser.add_argument("--scenarios", default=str(Path(__file__).parent / "scenarios.yaml"))
    parser.add_argument("--output-dir", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()

    scenarios = yaml.safe_load(Path(args.scenarios).read_text(encoding="utf-8"))
    db = _make_db()

    print(f"Running {len(scenarios)} scenarios in {'STUB' if args.stub else 'LIVE'} mode...\n")

    results: list[ScenarioResult] = []
    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {scenario['id']} ... ", end="", flush=True)
        r = run_scenario(db, scenario, stub=args.stub)
        results.append(r)
        print("PASS" if r.passed else f"FAIL (expected {r.expected_outcome}/{r.expected_rule}, got {r.actual_outcome}/{r.actual_rule})")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    false_positives = [r for r in results if r.expected_outcome == "ALLOW" and r.actual_outcome != "ALLOW"]
    false_negatives = [
        r for r in results if r.expected_outcome in ("DENY", "REJECTED") and r.actual_outcome == "ALLOW"
    ]
    outcome_breakdown: dict[str, int] = {}
    for r in results:
        outcome_breakdown[r.actual_outcome] = outcome_breakdown.get(r.actual_outcome, 0) + 1

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "stub" if args.stub else "live",
        "model": "stub-model" if args.stub else settings.llm_model,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "false_positives": len(false_positives),
        "false_negatives": len(false_negatives),
        "outcome_breakdown": outcome_breakdown,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    payload = {"meta": meta, "results": [asdict(r) for r in results]}
    json_path = output_dir / f"results_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = _render_markdown(results, meta)
    md_path = output_dir / f"results_{stamp}.md"
    md_path.write_text(md, encoding="utf-8")
    (output_dir / "latest.md").write_text(md, encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Total: {meta['total']}  Passed: {meta['passed']}  Failed: {meta['failed']}")
    print(f"False positives (legit blocked): {meta['false_positives']}")
    print(f"False negatives (violation allowed): {meta['false_negatives']}")
    print(f"\nSaved: {json_path}\n        {md_path}")
    print("=" * 60)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
