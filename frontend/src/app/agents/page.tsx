"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createAgent, fetchAgent, fetchAgents, revokeAgent, runAgent } from "@/lib/api";
import type { AgentAction, AgentCreateResponse, AgentDetail, AgentSummary } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";

// Mirrors backend/app/core/config.py's agent_available_scopes default — the
// backend is the actual source of truth and rejects anything outside its
// own configured list at creation time, so a mismatch here just shows up as
// a 422 rather than silently succeeding.
const AVAILABLE_SCOPES = [
  "search_products",
  "get_product",
  "add_to_cart",
  "view_cart",
  "remove_from_cart",
  "initiate_payment",
  "decline_upsell",
  "report_content_gap",
];

function rupees(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "ACTIVE" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

function KeyRevealDialog({ agent, onClose }: { agent: AgentCreateResponse; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white p-5 shadow-xl">
        <h2 className="text-lg font-semibold">Save this key now</h2>
        <p className="mt-1 text-sm text-gray-600">
          &ldquo;{agent.name}&rdquo; is an <strong>external</strong> agent credential. This key is shown{" "}
          <strong>exactly once</strong> — it is hashed at rest and cannot be recovered after you close this dialog.
          Configure it wherever the external agent runs (e.g. <code>AGENT_API_KEY</code> for{" "}
          <code>buyer_agent/</code>).
        </p>
        <pre className="mt-3 overflow-x-auto rounded-md bg-gray-900 p-3 text-xs text-green-300">{agent.key}</pre>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded-md bg-black px-4 py-2 text-sm text-white hover:bg-gray-800"
        >
          I&rsquo;ve saved it
        </button>
      </div>
    </div>
  );
}

function CreateAgentForm({ onCreated }: { onCreated: (agent: AgentCreateResponse) => void }) {
  const [name, setName] = useState("");
  const [deliveryMode, setDeliveryMode] = useState<"EMBEDDED" | "EXTERNAL">("EMBEDDED");
  const [scopes, setScopes] = useState<Set<string>>(new Set(["search_products", "get_product", "add_to_cart", "view_cart"]));
  const [spendLimitInput, setSpendLimitInput] = useState("500");
  const [standingInstruction, setStandingInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleScope(scope: string) {
    setScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const spendLimitPaise = Math.round(Number(spendLimitInput) * 100);
    if (!name.trim() || scopes.size === 0 || !spendLimitPaise || spendLimitPaise <= 0) {
      setError("Give the agent a name, at least one scope, and a positive spend limit.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createAgent({
        name: name.trim(),
        delivery_mode: deliveryMode,
        scopes: Array.from(scopes),
        spend_limit_paise: spendLimitPaise,
        standing_instruction: standingInstruction.trim() || null,
      });
      onCreated(created);
      setName("");
      setStandingInstruction("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border border-gray-200 p-4">
      <h2 className="font-semibold">Create an agent</h2>

      <label className="flex flex-col gap-1 text-sm">
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Weekly groceries"
          className="rounded-md border border-gray-300 px-3 py-2"
        />
      </label>

      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="mb-1">Delivery mode</legend>
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name="delivery-mode"
            checked={deliveryMode === "EMBEDDED"}
            onChange={() => setDeliveryMode("EMBEDDED")}
            className="mt-0.5"
          />
          <span>
            <strong>Embedded</strong> — runs from this UI. The key is generated and hashed on the server; it is
            never shown to anyone, including you.
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name="delivery-mode"
            checked={deliveryMode === "EXTERNAL"}
            onChange={() => setDeliveryMode("EXTERNAL")}
            className="mt-0.5"
          />
          <span>
            <strong>External</strong> — for a third-party integration (e.g. <code>buyer_agent/</code>). The key is
            shown once, right after you create it, for you to configure elsewhere.
          </span>
        </label>
      </fieldset>

      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="mb-1">Scopes — which tools this agent may call</legend>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {AVAILABLE_SCOPES.map((scope) => (
            <label key={scope} className="flex items-center gap-1.5">
              <input type="checkbox" checked={scopes.has(scope)} onChange={() => toggleScope(scope)} />
              <span className="font-mono text-xs">{scope}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        Spend limit (₹) — a hard cap across every run of this credential, independent of any session budget
        <input
          type="number"
          min={1}
          value={spendLimitInput}
          onChange={(e) => setSpendLimitInput(e.target.value)}
          className="w-32 rounded-md border border-gray-300 px-3 py-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        Standing instruction (used by &ldquo;Run now&rdquo; for an embedded agent — plain language)
        <textarea
          value={standingInstruction}
          onChange={(e) => setStandingInstruction(e.target.value)}
          placeholder="e.g. Buy a 5kg bag of atta if it's under ₹300 and in stock."
          rows={2}
          className="rounded-md border border-gray-300 px-3 py-2"
        />
      </label>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded-md bg-black px-4 py-2 text-sm text-white disabled:opacity-40"
      >
        {submitting ? "Creating…" : "Create agent"}
      </button>
    </form>
  );
}

function AgentActionRow({ action }: { action: AgentAction }) {
  const decisionCls =
    action.decision === "DENY"
      ? "text-red-600"
      : action.decision === "REQUIRE_CONFIRMATION"
        ? "text-amber-600"
        : "text-green-600";
  return (
    <tr className="border-t border-gray-100 align-top">
      <td className="p-1.5 whitespace-nowrap text-xs text-gray-400">{new Date(action.timestamp + "Z").toLocaleString()}</td>
      <td className="p-1.5 whitespace-nowrap text-xs">{action.event_type}</td>
      <td className="p-1.5 whitespace-nowrap text-xs">{action.tool_name ?? "—"}</td>
      <td className="p-1.5 whitespace-nowrap text-xs">
        {action.decision ? <span className={decisionCls}>{action.decision}</span> : "—"}
      </td>
      <td className="p-1.5 whitespace-nowrap text-xs">{action.rule_name ?? "—"}</td>
      <td className="p-1.5 text-xs text-gray-600">{action.reason ?? "—"}</td>
    </tr>
  );
}

function AgentCard({ agent, onChanged }: { agent: AgentSummary; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runReply, setRunReply] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggleExpand() {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail) {
      setLoadingDetail(true);
      try {
        setDetail(await fetchAgent(agent.id));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoadingDetail(false);
      }
    }
  }

  async function handleRevoke() {
    setBusy(true);
    setError(null);
    try {
      await revokeAgent(agent.id);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    setBusy(true);
    setError(null);
    setRunReply(null);
    try {
      const res = await runAgent(agent.id);
      setRunReply(res.reply);
      setDetail(null); // stale — force a re-fetch next expand for updated spend/actions
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-medium">{agent.name}</h3>
            <StatusBadge status={agent.status} />
            <span className="text-xs text-gray-400">{agent.delivery_mode}</span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Spent {rupees(agent.spent_paise)} of {rupees(agent.spend_limit_paise)} limit · Last active{" "}
            {agent.last_used_at ? new Date(agent.last_used_at + "Z").toLocaleString() : "never"} · Created{" "}
            {new Date(agent.created_at + "Z").toLocaleDateString()}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {agent.scopes.map((s) => (
              <span key={s} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-600">
                {s}
              </span>
            ))}
          </div>
          {agent.standing_instruction && (
            <p className="mt-1.5 text-xs text-gray-500">
              Standing instruction: <span className="italic">&ldquo;{agent.standing_instruction}&rdquo;</span>
            </p>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          {agent.status === "ACTIVE" && agent.delivery_mode === "EMBEDDED" && agent.standing_instruction && (
            <button
              onClick={handleRun}
              disabled={busy}
              className="rounded-md bg-black px-3 py-1.5 text-xs text-white disabled:opacity-40"
            >
              {busy ? "Running…" : "Run now"}
            </button>
          )}
          {agent.status === "ACTIVE" && (
            <button
              onClick={handleRevoke}
              disabled={busy}
              className="rounded-md border border-red-300 px-3 py-1.5 text-xs text-red-700 disabled:opacity-40"
            >
              Revoke
            </button>
          )}
          <button onClick={toggleExpand} className="text-xs text-gray-400 underline hover:text-gray-700">
            {expanded ? "Hide" : "Show"} activity
          </button>
        </div>
      </div>

      {runReply && (
        <div className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-2 text-xs text-gray-700">{runReply}</div>
      )}
      {error && <div className="mt-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>}

      {expanded && (
        <div className="mt-3 overflow-x-auto rounded-md border border-gray-200">
          {loadingDetail ? (
            <p className="p-2 text-xs text-gray-400">Loading…</p>
          ) : !detail || detail.recent_actions.length === 0 ? (
            <p className="p-2 text-xs text-gray-400">No actions recorded for this credential yet.</p>
          ) : (
            <table className="w-full min-w-[640px] border-collapse text-xs">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  <th className="p-1.5">Time</th>
                  <th className="p-1.5">Event</th>
                  <th className="p-1.5">Tool</th>
                  <th className="p-1.5">Decision</th>
                  <th className="p-1.5">Rule</th>
                  <th className="p-1.5">Reason</th>
                </tr>
              </thead>
              <tbody>
                {detail.recent_actions.map((a, i) => (
                  <AgentActionRow key={i} action={a} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function AgentsPageInner() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revealAgent, setRevealAgent] = useState<AgentCreateResponse | null>(null);

  function refresh() {
    fetchAgents()
      .then(setAgents)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  function handleCreated(created: AgentCreateResponse) {
    refresh();
    if (created.delivery_mode === "EXTERNAL") setRevealAgent(created);
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">My agents</h1>
          <p className="text-sm text-gray-500">
            Grant, run, observe, and revoke — every agent here is bounded by its own spend limit and scopes,
            enforced the same way for every call it makes.
          </p>
        </div>
        <Link href="/" className="text-sm text-gray-500 underline hover:text-gray-800">
          ← Back to shop
        </Link>
      </header>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      <CreateAgentForm onCreated={handleCreated} />

      <div className="flex flex-col gap-3">
        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : agents.length === 0 ? (
          <p className="text-sm text-gray-400">No agents yet — create one above.</p>
        ) : (
          agents.map((a) => <AgentCard key={a.id} agent={a} onChanged={refresh} />)
        )}
      </div>

      {revealAgent && <KeyRevealDialog agent={revealAgent} onClose={() => setRevealAgent(null)} />}
    </div>
  );
}

export default function AgentsPage() {
  return (
    <RequireAuth allow={["buyer"]}>
      <AgentsPageInner />
    </RequireAuth>
  );
}
