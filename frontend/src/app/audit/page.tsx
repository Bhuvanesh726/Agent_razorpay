"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchAuditTrail, fetchSessionReplay } from "@/lib/api";
import type { AuditTrail, SessionReplay } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";

const DECISION_STYLES: Record<string, string> = {
  ALLOW: "bg-green-100 text-green-800",
  DENY: "bg-red-100 text-red-800",
  REQUIRE_CONFIRMATION: "bg-amber-100 text-amber-800",
};

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="text-gray-300">—</span>;
  const style = DECISION_STYLES[decision] ?? "bg-gray-100 text-gray-700";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${style}`}>{decision}</span>;
}

const CHAT_SESSION_STORAGE_KEY = "razorpay-agent-session-id";

function AuditViewerInner() {
  const searchParams = useSearchParams();
  const [sessionIdInput, setSessionIdInput] = useState(() => {
    const fromQuery = searchParams.get("session");
    if (fromQuery) return fromQuery;
    try {
      return window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [replay, setReplay] = useState<SessionReplay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("all");
  const [decisionFilter, setDecisionFilter] = useState<string>("all");
  const [showNarrative, setShowNarrative] = useState(false);

  async function load(sessionId: string) {
    if (!sessionId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [trailRes, replayRes] = await Promise.all([
        fetchAuditTrail(sessionId.trim()),
        fetchSessionReplay(sessionId.trim()),
      ]);
      setTrail(trailRes);
      setReplay(replayRes);
      setLoadedSessionId(sessionId.trim());
    } catch (e) {
      setTrail(null);
      setReplay(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const fromQuery = searchParams.get("session");
    if (fromQuery) {
      // Deferred to a microtask so the fetch's setState calls don't run
      // synchronously inside the effect body itself.
      Promise.resolve().then(() => load(fromQuery));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const eventTypes = useMemo(() => {
    if (!trail) return [];
    return Array.from(new Set(trail.events.map((e) => e.event_type))).sort();
  }, [trail]);

  const filteredEvents = useMemo(() => {
    if (!trail) return [];
    return trail.events.filter((e) => {
      if (eventTypeFilter !== "all" && e.event_type !== eventTypeFilter) return false;
      if (decisionFilter !== "all" && e.decision !== decisionFilter) return false;
      return true;
    });
  }, [trail, eventTypeFilter, decisionFilter]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Audit trail viewer</h1>
        <p className="text-sm text-gray-500">
          Every event is read straight from the audit log — nothing here comes from any other table.
        </p>
      </header>

      <div className="flex gap-2">
        <input
          value={sessionIdInput}
          onChange={(e) => setSessionIdInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(sessionIdInput)}
          placeholder="Paste a session_id..."
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          onClick={() => load(sessionIdInput)}
          disabled={loading || !sessionIdInput.trim()}
          className="rounded-md bg-black px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {trail && (
        <>
          <div className="grid grid-cols-2 gap-2 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 sm:grid-cols-3 md:grid-cols-6">
            <span>Session: <strong>{loadedSessionId}</strong></span>
            <span>Model calls: <strong>{trail.totals.total_model_calls}</strong></span>
            <span>Fallback used: <strong>{trail.totals.fallback_used_count}</strong></span>
            <span>Tokens: <strong>{trail.totals.total_tokens}</strong></span>
            <span>
              Prompt / completion: <strong>{trail.totals.total_prompt_tokens} / {trail.totals.total_completion_tokens}</strong>
            </span>
            <span>Cost: <strong>₹{(trail.totals.total_cost_paise / 100).toFixed(2)}</strong></span>
            <span>
              Upsells: <strong>{trail.totals.upsell_proposed_count} proposed</strong>,{" "}
              {trail.totals.upsell_accepted_count} accepted, {trail.totals.upsell_declined_count} declined,{" "}
              {trail.totals.upsell_blocked_count} blocked
            </span>
            <span>
              Upsell revenue: <strong>₹{(trail.totals.upsell_incremental_revenue_paise / 100).toFixed(2)}</strong>
            </span>
          </div>

          {replay && (
            <div className="rounded-md border border-gray-200 p-3 text-sm">
              <div className="flex items-center justify-between">
                <p className="font-medium">Reconstructed from the audit log alone</p>
                <button onClick={() => setShowNarrative((v) => !v)} className="text-xs text-gray-400 underline">
                  {showNarrative ? "Hide" : "Show"} narrative ({replay.event_count} events)
                </button>
              </div>
              <p className="mt-1 text-gray-600">
                Final cart total: <strong>{replay.final_cart ? replay.final_cart.total_display : "— (empty)"}</strong>
                {replay.final_order_status && (
                  <>
                    {" · "}Final order status: <strong>{replay.final_order_status}</strong>
                  </>
                )}
              </p>
              {showNarrative && (
                <ol className="mt-2 max-h-64 list-decimal overflow-y-auto pl-5 text-xs text-gray-600">
                  {replay.narrative.map((line, i) => (
                    <li key={i} className="py-0.5">
                      {line}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              Event type
              <select
                value={eventTypeFilter}
                onChange={(e) => setEventTypeFilter(e.target.value)}
                className="rounded-md border border-gray-300 px-2 py-1"
              >
                <option value="all">All ({trail.events.length})</option>
                {eventTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5">
              Decision
              <select
                value={decisionFilter}
                onChange={(e) => setDecisionFilter(e.target.value)}
                className="rounded-md border border-gray-300 px-2 py-1"
              >
                <option value="all">All</option>
                <option value="ALLOW">ALLOW</option>
                <option value="DENY">DENY</option>
                <option value="REQUIRE_CONFIRMATION">REQUIRE_CONFIRMATION</option>
              </select>
            </label>
            <span className="text-gray-400">
              Showing {filteredEvents.length} of {trail.events.length}
            </span>
          </div>

          <div className="overflow-x-auto rounded-md border border-gray-200">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  <th className="p-2">Time</th>
                  <th className="p-2">Event</th>
                  <th className="p-2">Actor</th>
                  <th className="p-2">Tool</th>
                  <th className="p-2">Decision</th>
                  <th className="p-2">Rule</th>
                  <th className="p-2">Tokens / Cost</th>
                  <th className="p-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((e) => (
                  <tr key={e.id} className="border-t border-gray-100 align-top hover:bg-gray-50">
                    <td className="whitespace-nowrap p-2 text-xs text-gray-400">
                      {new Date(e.timestamp + "Z").toLocaleTimeString()}
                    </td>
                    <td className="whitespace-nowrap p-2 font-mono text-xs">{e.event_type}</td>
                    <td className="whitespace-nowrap p-2 text-xs">{e.actor}</td>
                    <td className="whitespace-nowrap p-2 text-xs">{e.tool_name ?? "—"}</td>
                    <td className="whitespace-nowrap p-2">
                      <DecisionBadge decision={e.decision} />
                    </td>
                    <td className="whitespace-nowrap p-2 text-xs">{e.rule_name ?? "—"}</td>
                    <td className="whitespace-nowrap p-2 text-xs">
                      {e.total_tokens != null
                        ? `${e.total_tokens} tok · ₹${((e.cost_paise ?? 0) / 100).toFixed(2)}${e.fallback_used ? " (fallback)" : ""}`
                        : "—"}
                    </td>
                    <td className="max-w-md p-2 text-xs text-gray-700">{e.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!trail && !loading && !error && (
        <p className="text-sm text-gray-400">
          Paste a session_id above (the shopping assistant panel shows the current one under &ldquo;Show audit
          trail&rdquo;) to view its full timeline.
        </p>
      )}
    </div>
  );
}

export default function AuditViewerPage() {
  return (
    <RequireAuth>
      <Suspense fallback={<div className="p-6 text-sm text-gray-400">Loading…</div>}>
        <AuditViewerInner />
      </Suspense>
    </RequireAuth>
  );
}
