"use client";

import { useEffect, useRef, useState } from "react";
import { History, ScrollText, ShieldAlert, Sparkles } from "lucide-react";
import {
  confirmAgentCredentialAction,
  fetchAgentConversation,
  fetchAuditTrail,
  sendAgentCredentialMessage,
} from "@/lib/api";
import { getOrCreateAgentSessionId, openRazorpayCheckout, setActiveAgentSessionId } from "@/lib/checkout";
import type { AgentSummary, AuditTrail, ChatMessage, PaymentInfo, PendingAction, ProductSuggestion, UpsellOffer } from "@/lib/types";
import Button from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { StatusBadge } from "@/components/ui/Badge";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";
import ProductSuggestionCard from "@/components/ProductSuggestionCard";
import ConversationHistory from "@/components/ConversationHistory";

interface Props {
  agents: AgentSummary[];
  onCartChanged: () => void;
}

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
          isUser ? "rounded-br-sm bg-ink text-white" : "rounded-bl-sm bg-black/[0.04] text-ink"
        }`}
      >
        {message.text}
      </div>
      <span className="mt-1 px-0.5 text-[11px] text-ink-faint">
        {isUser ? "You" : "Assistant"} · {formatTime(message.timestamp)}
      </span>
    </div>
  );
}

export default function ChatPanel({ agents, onCartChanged }: Props) {
  const [activeCredentialId, setActiveCredentialId] = useState(() => agents[0]?.id ?? "");
  const [sessionId, setSessionId] = useState(() => getOrCreateAgentSessionId(agents[0]?.id ?? ""));
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [upsell, setUpsell] = useState<UpsellOffer | null>(null);
  const [respondingToUpsell, setRespondingToUpsell] = useState(false);
  const [productSuggestion, setProductSuggestion] = useState<ProductSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAudit, setShowAudit] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [auditTrail, setAuditTrail] = useState<AuditTrail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [payingOrderId, setPayingOrderId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const activeAgent = agents.find((a) => a.id === activeCredentialId) ?? null;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, pending, productSuggestion]);

  function switchAgent(credentialId: string) {
    setActiveCredentialId(credentialId);
    setSessionId(getOrCreateAgentSessionId(credentialId));
    setMessages([]);
    setPending(null);
    setUpsell(null);
    setProductSuggestion(null);
    setError(null);
    setShowAudit(false);
    setAuditTrail(null);
    setShowHistory(false);
  }

  /** Load a past conversation into the panel. The transcript comes from
   *  agent_messages on the server; the session id becomes the active one so
   *  the next message continues that conversation rather than starting a new. */
  async function openConversation(nextSessionId: string) {
    if (nextSessionId === sessionId) {
      setShowHistory(false);
      return;
    }
    setLoadingConversation(true);
    setError(null);
    try {
      const detail = await fetchAgentConversation(activeCredentialId, nextSessionId);
      setSessionId(nextSessionId);
      setActiveAgentSessionId(activeCredentialId, nextSessionId);
      setMessages(
        detail.messages.map((m) => ({
          id: `${nextSessionId}-${m.seq}`,
          role: m.role === "user" ? "user" : "assistant",
          text: m.content ?? "",
          timestamp: Date.now(),
        })),
      );
      // Pending/upsell state belongs to whatever turn was in flight, not to a
      // transcript being read back.
      setPending(null);
      setUpsell(null);
      setProductSuggestion(null);
      setAuditTrail(null);
      setShowAudit(false);
      setShowHistory(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open that conversation.");
    } finally {
      setLoadingConversation(false);
    }
  }

  function pushMessage(role: ChatMessage["role"], text: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text, timestamp: Date.now() }]);
  }

  function openCheckout(payment: PaymentInfo) {
    if (payment.status === "PAID") {
      // Agent-authorized payments complete server-side, within the spend
      // limit the buyer already granted this agent — nothing to confirm again.
      onCartChanged();
      if (showAudit) refreshAudit();
      return;
    }
    setPayingOrderId(payment.order_id);
    openRazorpayCheckout(payment, `Order #${payment.order_id}`, {
      onSuccess: (result) => {
        pushMessage("assistant", `✅ ${result.message}`);
        onCartChanged();
        if (showAudit) refreshAudit();
        setPayingOrderId(null);
      },
      onFailure: (result) => {
        pushMessage("assistant", `❌ ${result.message}`);
        if (showAudit) refreshAudit();
        setPayingOrderId(null);
      },
      onDismiss: () => {
        setPayingOrderId(null);
        pushMessage("assistant", "Checkout closed without completing payment. Ask to pay again if you'd like.");
      },
      onUnavailable: () => {
        setError("Razorpay Checkout hasn't loaded yet — please try again in a moment.");
        setPayingOrderId(null);
      },
      onError: (message) => {
        setError(message);
        setPayingOrderId(null);
      },
    });
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || sending || pending || !activeCredentialId) return;
    setInput("");
    pushMessage("user", text);
    setSending(true);
    setError(null);
    setProductSuggestion(null);
    try {
      const res = await sendAgentCredentialMessage(activeCredentialId, sessionId, text);
      pushMessage("assistant", res.reply);
      setPending(res.pending);
      setUpsell(res.upsell);
      setProductSuggestion(res.product_suggestion);
      onCartChanged();
      if (showAudit) refreshAudit();
      if (res.payment) openCheckout(res.payment);
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
      const res = await confirmAgentCredentialAction(activeCredentialId, sessionId, approve);
      pushMessage("assistant", res.reply);
      setPending(res.pending);
      setUpsell(res.upsell);
      setProductSuggestion(res.product_suggestion);
      onCartChanged();
      if (showAudit) refreshAudit();
      if (res.payment) openCheckout(res.payment);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  }

  async function respondToUpsell(accept: boolean) {
    if (!upsell) return;
    const text = accept ? `Yes, add the ${upsell.name} too.` : "No thanks, I don't want that.";
    setRespondingToUpsell(true);
    setError(null);
    pushMessage("user", text);
    try {
      const res = await sendAgentCredentialMessage(activeCredentialId, sessionId, text);
      pushMessage("assistant", res.reply);
      setPending(res.pending);
      setUpsell(res.upsell);
      setProductSuggestion(res.product_suggestion);
      onCartChanged();
      if (showAudit) refreshAudit();
      if (res.payment) openCheckout(res.payment);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRespondingToUpsell(false);
    }
  }

  function handleQuickBuySuccess(message: string) {
    setProductSuggestion(null);
    pushMessage("assistant", `✅ ${message}`);
    onCartChanged();
    if (showAudit) refreshAudit();
  }

  function handleQuickBuyFailure(message: string) {
    pushMessage("assistant", `❌ ${message}`);
    if (showAudit) refreshAudit();
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
    <div className="flex h-fit flex-col gap-3 rounded-lg border border-line bg-surface p-4 lg:sticky lg:top-[4.5rem]">
      <div className="flex items-center justify-between gap-2">
        {agents.length > 1 ? (
          <select
            value={activeCredentialId}
            onChange={(e) => switchAgent(e.target.value)}
            className="min-w-0 rounded-md border-none bg-transparent text-sm font-semibold tracking-tight text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        ) : (
          <h2 className="truncate text-sm font-semibold tracking-tight text-ink">{activeAgent?.name ?? "Shopping assistant"}</h2>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            onClick={() => setShowHistory((v) => !v)}
            aria-expanded={showHistory}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-ink-soft transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
          >
            <History size={13} />
            History
          </button>
          <button
            onClick={toggleAudit}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-ink-soft transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
          >
            <ScrollText size={13} />
            {showAudit ? "Hide" : "Show"} audit trail
          </button>
        </div>
      </div>

      {showHistory && activeCredentialId && (
        <ConversationHistory
          credentialId={activeCredentialId}
          activeSessionId={sessionId}
          onOpen={openConversation}
        />
      )}

      {loadingConversation && <p className="text-xs text-ink-faint">Loading conversation…</p>}

      <div ref={scrollRef} className="flex max-h-80 min-h-40 flex-col gap-3 overflow-y-auto border-t border-line pt-3">
        {messages.length === 0 && (
          <p className="text-sm text-ink-faint">
            Ask for something to buy — e.g. &ldquo;5kg atta under ₹400&rdquo;. {activeAgent?.name ?? "This agent"} can
            only do what it&rsquo;s been scoped to do, up to its own spend limit.
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {sending && (
          <div className="flex items-center gap-1.5 self-start px-0.5 text-xs text-ink-faint">
            <span className="flex gap-0.5">
              <span className="h-1 w-1 animate-bounce rounded-full bg-ink-faint [animation-delay:-0.3s]" />
              <span className="h-1 w-1 animate-bounce rounded-full bg-ink-faint [animation-delay:-0.15s]" />
              <span className="h-1 w-1 animate-bounce rounded-full bg-ink-faint" />
            </span>
            Thinking
          </div>
        )}
      </div>

      {productSuggestion && (
        <ProductSuggestionCard
          suggestion={productSuggestion}
          credentialId={activeCredentialId}
          sessionId={sessionId}
          onSuccess={handleQuickBuySuccess}
          onFailure={handleQuickBuyFailure}
        />
      )}

      {pending && (
        <div className="rounded-lg border border-warning/25 bg-warning-soft p-3.5 text-sm">
          <div className="flex items-start gap-2">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <div>
              <p className="font-medium text-warning">Confirmation needed</p>
              <p className="mt-0.5 text-warning/90">{pending.reason}</p>
              {pending.rule_name && (
                <p className="mt-1.5 font-mono text-[11px] tracking-tight text-warning/70">{pending.rule_name}</p>
              )}
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" size="sm" onClick={() => handleConfirm(true)} disabled={confirming}>
              Confirm
            </Button>
            <Button variant="secondary" size="sm" onClick={() => handleConfirm(false)} disabled={confirming}>
              Decline
            </Button>
          </div>
        </div>
      )}

      {upsell && !pending && (
        <div className="rounded-lg border border-accent/20 bg-accent-soft p-3.5 text-sm">
          <div className="flex items-start gap-2">
            <Sparkles size={16} className="mt-0.5 shrink-0 text-accent" />
            <div>
              <p className="font-medium text-accent">Suggested add-on</p>
              <p className="mt-0.5 text-ink">
                {upsell.name} — <span className="font-mono tabular-nums">₹{(upsell.price_paise / 100).toFixed(2)}</span>
              </p>
              <p className="mt-1 text-xs text-ink-soft">{upsell.reason}</p>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" size="sm" onClick={() => respondToUpsell(true)} disabled={respondingToUpsell}>
              Add it
            </Button>
            <Button variant="secondary" size="sm" onClick={() => respondToUpsell(false)} disabled={respondingToUpsell}>
              No thanks
            </Button>
          </div>
        </div>
      )}

      {payingOrderId != null && <p className="text-xs text-ink-faint">Waiting for checkout on order #{payingOrderId}…</p>}

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">{error}</div>}

      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          disabled={sending || !!pending}
          placeholder={pending ? "Resolve the pending action above first" : "Ask for something to buy..."}
          className="flex-1"
        />
        <Button variant="primary" onClick={handleSend} disabled={sending || !!pending || !input.trim()}>
          Send
        </Button>
      </div>

      {showAudit && (
        <div className="mt-1 flex flex-col gap-2 border-t border-line pt-3">
          {auditLoading ? (
            <p className="p-2 text-xs text-ink-faint">Loading…</p>
          ) : !auditTrail || auditTrail.events.length === 0 ? (
            <p className="p-2 text-xs text-ink-faint">No events yet for this session.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-line bg-black/[0.015] p-2.5 text-xs text-ink-soft sm:grid-cols-3">
                <span>
                  Model calls: <span className="font-mono tabular-nums text-ink">{auditTrail.totals.total_model_calls}</span>
                </span>
                <span>
                  Fallback used: <span className="font-mono tabular-nums text-ink">{auditTrail.totals.fallback_used_count}</span>
                </span>
                <span>
                  Tokens: <span className="font-mono tabular-nums text-ink">{auditTrail.totals.total_tokens}</span>
                </span>
                <span>
                  Prompt tokens: <span className="font-mono tabular-nums text-ink">{auditTrail.totals.total_prompt_tokens}</span>
                </span>
                <span>
                  Completion tokens:{" "}
                  <span className="font-mono tabular-nums text-ink">{auditTrail.totals.total_completion_tokens}</span>
                </span>
                <span>
                  Cost:{" "}
                  <span className="font-mono tabular-nums text-ink">₹{(auditTrail.totals.total_cost_paise / 100).toFixed(2)}</span>
                </span>
                <span>
                  Upsells proposed:{" "}
                  <span className="font-mono tabular-nums text-ink">{auditTrail.totals.upsell_proposed_count}</span>
                </span>
                <span>
                  Upsells accepted:{" "}
                  <span className="font-mono tabular-nums text-ink">{auditTrail.totals.upsell_accepted_count}</span>
                </span>
                <span>
                  Upsell revenue:{" "}
                  <span className="font-mono tabular-nums text-ink">
                    ₹{(auditTrail.totals.upsell_incremental_revenue_paise / 100).toFixed(2)}
                  </span>
                </span>
              </div>

              <TableWrap className="max-h-64 overflow-y-auto">
                <Table className="text-xs">
                  <THead>
                    <tr>
                      <Th>Event</Th>
                      <Th>Actor</Th>
                      <Th>Tool</Th>
                      <Th>Decision</Th>
                      <Th>Rule</Th>
                      <Th align="right">Tokens / Cost</Th>
                      <Th>Reason</Th>
                    </tr>
                  </THead>
                  <tbody>
                    {auditTrail.events.map((e) => (
                      <Tr key={e.id}>
                        <Td className="whitespace-nowrap font-mono">{e.event_type}</Td>
                        <Td className="whitespace-nowrap capitalize">{e.actor}</Td>
                        <Td className="whitespace-nowrap">{e.tool_name ?? "—"}</Td>
                        <Td className="whitespace-nowrap">
                          <StatusBadge status={e.decision} />
                        </Td>
                        <Td className="whitespace-nowrap text-ink-soft">{e.rule_name ?? "—"}</Td>
                        <Td align="right" numeric className="whitespace-nowrap">
                          {e.total_tokens != null
                            ? `${e.total_tokens} · ₹${((e.cost_paise ?? 0) / 100).toFixed(2)}${e.fallback_used ? " (fb)" : ""}`
                            : "—"}
                        </Td>
                        <Td className="text-ink-soft">{e.reason ?? "—"}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              </TableWrap>
            </>
          )}
        </div>
      )}
    </div>
  );
}
