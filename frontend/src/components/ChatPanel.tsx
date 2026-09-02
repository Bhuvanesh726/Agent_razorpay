"use client";

import { useEffect, useRef, useState } from "react";
import { confirmPendingAction, fetchAuditTrail, sendAgentMessage } from "@/lib/api";
import type { AuditTrail, ChatMessage, PendingAction } from "@/lib/types";

interface Props {
  onCartChanged: () => void;
}

const SESSION_STORAGE_KEY = "razorpay-agent-session-id";

function loadOrCreateSessionId(): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.localStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

function rupeesToPaise(value: string): number | null {
  const n = Number(value);
  if (!value.trim() || Number.isNaN(n) || n < 0) return null;
  return Math.round(n * 100);
}

export default function ChatPanel({ onCartChanged }: Props) {
  const [sessionId] = useState(() => loadOrCreateSessionId());
  const [budgetInput, setBudgetInput] = useState("");
  const [budgetLocked, setBudgetLocked] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAudit, setShowAudit] = useState(false);
  const [auditTrail, setAuditTrail] = useState<AuditTrail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, pending]);

  function pushMessage(role: ChatMessage["role"], text: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text }]);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || sending || pending) return;
    setInput("");
    pushMessage("user", text);
    setSending(true);
    setError(null);
    try {
      const budgetPaise = budgetLocked ? null : rupeesToPaise(budgetInput);
      if (!budgetLocked && budgetPaise != null) setBudgetLocked(true);
      const res = await sendAgentMessage(sessionId, text, budgetLocked ? undefined : budgetPaise);
      pushMessage("assistant", res.reply);
      setPending(res.pending);
      onCartChanged();
      if (showAudit) refreshAudit();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  async function handleConfirm(approve: boolean) {
    setConfirming(true);
    setError(null);
    try {
      const res = await confirmPendingAction(sessionId, approve);
      pushMessage("assistant", res.reply);
      setPending(res.pending);
      onCartChanged();
      if (showAudit) refreshAudit();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  }

  async function refreshAudit() {
    if (!sessionId) return;
    setAuditLoading(true);
    try {
      setAuditTrail(await fetchAuditTrail(sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuditLoading(false);
    }
  }

  function toggleAudit() {
    const next = !showAudit;
    setShowAudit(next);
    if (next) refreshAudit();
  }

  return (
    <div className="flex h-fit flex-col gap-3 rounded-lg border border-gray-200 p-4 lg:sticky lg:top-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Shopping assistant</h2>
        <button onClick={toggleAudit} className="text-xs text-gray-400 underline hover:text-gray-700">
          {showAudit ? "Hide" : "Show"} audit trail
        </button>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="budget" className="text-gray-500">
          Budget ₹
        </label>
        <input
          id="budget"
          type="number"
          min={0}
          value={budgetInput}
          onChange={(e) => setBudgetInput(e.target.value)}
          disabled={budgetLocked}
          placeholder="e.g. 800"
          className="w-24 rounded-md border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400"
        />
        {budgetLocked && (
          <button
            onClick={() => setBudgetLocked(false)}
            className="text-xs text-gray-400 underline hover:text-gray-700"
          >
            change
          </button>
        )}
      </div>

      <div ref={scrollRef} className="flex max-h-80 min-h-40 flex-col gap-2 overflow-y-auto border-t border-gray-100 pt-2">
        {messages.length === 0 && (
          <p className="text-sm text-gray-400">
            Set a budget above, then ask for something — e.g. &ldquo;I need dog food under ₹800&rdquo;.
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`rounded-md px-3 py-2 text-sm whitespace-pre-wrap ${
              m.role === "user" ? "self-end bg-black text-white" : "self-start bg-gray-100 text-gray-800"
            }`}
          >
            {m.text}
          </div>
        ))}
        {sending && <p className="self-start text-xs text-gray-400">Thinking…</p>}
      </div>

      {pending && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-amber-900">Confirmation needed</p>
          <p className="mt-1 text-amber-800">{pending.reason}</p>
          {pending.rule_name && <p className="mt-1 text-xs text-amber-600">Rule: {pending.rule_name}</p>}
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => handleConfirm(true)}
              disabled={confirming}
              className="rounded-md bg-black px-3 py-1 text-xs text-white disabled:opacity-40"
            >
              Confirm
            </button>
            <button
              onClick={() => handleConfirm(false)}
              disabled={confirming}
              className="rounded-md border border-gray-300 px-3 py-1 text-xs disabled:opacity-40"
            >
              Decline
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          disabled={sending || !!pending}
          placeholder={pending ? "Resolve the pending action above first" : "Ask for something to buy..."}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-100"
        />
        <button
          onClick={handleSend}
          disabled={sending || !!pending || !input.trim()}
          className="rounded-md bg-black px-3 py-2 text-sm text-white disabled:opacity-40"
        >
          Send
        </button>
      </div>

      {showAudit && (
        <div className="mt-2 flex flex-col gap-2">
          {auditLoading ? (
            <p className="p-2 text-xs text-gray-400">Loading…</p>
          ) : !auditTrail || auditTrail.events.length === 0 ? (
            <p className="p-2 text-xs text-gray-400">No events yet for this session.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-1.5 rounded-md border border-gray-200 bg-gray-50 p-2 text-xs text-gray-600 sm:grid-cols-3">
                <span>Model calls: {auditTrail.totals.total_model_calls}</span>
                <span>Fallback used: {auditTrail.totals.fallback_used_count}</span>
                <span>Tokens: {auditTrail.totals.total_tokens}</span>
                <span>Prompt tokens: {auditTrail.totals.total_prompt_tokens}</span>
                <span>Completion tokens: {auditTrail.totals.total_completion_tokens}</span>
                <span>Cost: ₹{(auditTrail.totals.total_cost_paise / 100).toFixed(2)}</span>
              </div>

              <div className="max-h-64 overflow-y-auto rounded-md border border-gray-200 text-xs">
                <table className="w-full border-collapse">
                  <thead className="sticky top-0 bg-gray-50 text-left text-gray-500">
                    <tr>
                      <th className="p-1.5">Event</th>
                      <th className="p-1.5">Actor</th>
                      <th className="p-1.5">Tool</th>
                      <th className="p-1.5">Decision</th>
                      <th className="p-1.5">Rule</th>
                      <th className="p-1.5">Tokens / Cost</th>
                      <th className="p-1.5">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditTrail.events.map((e) => (
                      <tr key={e.id} className="border-t border-gray-100 align-top">
                        <td className="p-1.5 whitespace-nowrap">{e.event_type}</td>
                        <td className="p-1.5 whitespace-nowrap">{e.actor}</td>
                        <td className="p-1.5 whitespace-nowrap">{e.tool_name ?? "—"}</td>
                        <td className="p-1.5 whitespace-nowrap">
                          {e.decision ? (
                            <span
                              className={
                                e.decision === "DENY"
                                  ? "text-red-600"
                                  : e.decision === "REQUIRE_CONFIRMATION"
                                    ? "text-amber-600"
                                    : "text-green-600"
                              }
                            >
                              {e.decision}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="p-1.5 whitespace-nowrap">{e.rule_name ?? "—"}</td>
                        <td className="p-1.5 whitespace-nowrap">
                          {e.total_tokens != null
                            ? `${e.total_tokens} tok · ₹${((e.cost_paise ?? 0) / 100).toFixed(2)}${e.fallback_used ? " (fallback)" : ""}`
                            : "—"}
                        </td>
                        <td className="p-1.5">{e.reason ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
