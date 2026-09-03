"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { History, RefreshCw, ScrollText, Search } from "lucide-react";
import { fetchAuditTrail, fetchRecentAuditSessions, fetchSessionReplay } from "@/lib/api";
import type { AuditSessionSummary, AuditTrail, SessionReplay } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import { useAuth } from "@/lib/auth";
import Button from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import MetricCard from "@/components/ui/MetricCard";
import { Skeleton, SkeletonCards, SkeletonRows } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

const CHAT_SESSION_STORAGE_KEY = "razorpay-agent-session-id";

const SELECT_CLASS =
  "rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-accent";

function AuditViewerInner() {
  const { user } = useAuth();
  const isMerchant = user?.type === "merchant";
  const searchParams = useSearchParams();
  const [sessions, setSessions] = useState<AuditSessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
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

  function loadSessions() {
    setSessionsLoading(true);
    fetchRecentAuditSessions()
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setSessionsLoading(false));
  }

  function selectSession(sessionId: string) {
    setSessionIdInput(sessionId);
    load(sessionId);
  }

  useEffect(() => {
    const fromQuery = searchParams.get("session");
    if (fromQuery) {
      // Deferred to a microtask so the fetch's setState calls don't run
      // synchronously inside the effect body itself.
      Promise.resolve().then(() => load(fromQuery));
    }
    if (isMerchant) Promise.resolve().then(() => loadSessions());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMerchant]);

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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Audit trail viewer</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Every event is read straight from the audit log — nothing here comes from any other table.
        </p>
      </header>

      {isMerchant && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Recent sessions</CardTitle>
              <p className="mt-1 text-xs text-ink-soft">
                Every buyer session with at least one logged event — click one to load its trail below.
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={loadSessions} disabled={sessionsLoading}>
              <RefreshCw size={13} className={sessionsLoading ? "animate-spin" : ""} />
              Refresh
            </Button>
          </CardHeader>
          {sessionsLoading && sessions.length === 0 ? (
            <CardBody>
              <SkeletonRows count={4} />
            </CardBody>
          ) : sessions.length === 0 ? (
            <CardBody>
              <EmptyState
                icon={History}
                title="No sessions yet"
                description="Once a buyer chats with the shopping assistant, their session will show up here."
                className="border-0 p-0 py-4"
              />
            </CardBody>
          ) : (
            <TableWrap className="rounded-none border-0 border-t border-line">
              <Table>
                <THead>
                  <tr>
                    <Th>Session</Th>
                    <Th>Buyer</Th>
                    <Th>Status</Th>
                    <Th align="right">Events</Th>
                    <Th align="right">Last activity</Th>
                  </tr>
                </THead>
                <tbody>
                  {sessions.map((s) => (
                    <Tr
                      key={s.session_id}
                      onClick={() => selectSession(s.session_id)}
                      className={s.session_id === loadedSessionId ? "bg-accent-soft/50" : ""}
                    >
                      <Td className="whitespace-nowrap font-mono text-xs">{s.session_id}</Td>
                      <Td className="whitespace-nowrap">{s.user_email}</Td>
                      <Td className="whitespace-nowrap">
                        <StatusBadge status={s.status} />
                      </Td>
                      <Td align="right" numeric>
                        {s.event_count}
                      </Td>
                      <Td align="right" className="whitespace-nowrap text-ink-faint">
                        {new Date(s.updated_at + "Z").toLocaleString()}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          )}
        </Card>
      )}

      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <Input
            value={sessionIdInput}
            onChange={(e) => setSessionIdInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load(sessionIdInput)}
            placeholder="Or paste a session_id directly…"
            className="pl-9"
          />
        </div>
        <Button variant="primary" onClick={() => load(sessionIdInput)} disabled={loading || !sessionIdInput.trim()}>
          {loading ? "Loading…" : "Load"}
        </Button>
      </div>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loading && !trail && <SkeletonCards count={4} className="sm:grid-cols-4" />}

      {trail && (
        <>
          <p className="text-xs text-ink-faint">
            Session <span className="font-mono text-ink-soft">{loadedSessionId}</span>
          </p>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <MetricCard label="Model calls" value={String(trail.totals.total_model_calls)} meta={trail.totals.fallback_used_count > 0 ? `${trail.totals.fallback_used_count} used fallback` : "no fallback used"} />
            <MetricCard
              label="Tokens"
              value={String(trail.totals.total_tokens)}
              meta={`${trail.totals.total_prompt_tokens} prompt / ${trail.totals.total_completion_tokens} completion`}
            />
            <MetricCard label="Cost" value={`₹${(trail.totals.total_cost_paise / 100).toFixed(2)}`} />
            <MetricCard
              label="Upsells"
              value={String(trail.totals.upsell_proposed_count)}
              meta={`${trail.totals.upsell_accepted_count} accepted · ${trail.totals.upsell_declined_count} declined · ${trail.totals.upsell_blocked_count} blocked`}
            />
            <MetricCard
              label="Upsell revenue"
              value={`₹${(trail.totals.upsell_incremental_revenue_paise / 100).toFixed(2)}`}
              tone={trail.totals.upsell_incremental_revenue_paise > 0 ? "success" : "default"}
            />
          </div>

          {replay && (
            <Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-ink">Reconstructed from the audit log alone</p>
                <Button variant="ghost" size="sm" onClick={() => setShowNarrative((v) => !v)}>
                  {showNarrative ? "Hide" : "Show"} narrative ({replay.event_count} events)
                </Button>
              </div>
              <p className="mt-1.5 text-sm text-ink-soft">
                Final cart total:{" "}
                <span className="font-mono tabular-nums text-ink">
                  {replay.final_cart ? replay.final_cart.total_display : "— (empty)"}
                </span>
                {replay.final_order_status && (
                  <>
                    {" · "}Final order status: <StatusBadge status={replay.final_order_status} />
                  </>
                )}
              </p>
              {showNarrative && (
                <ol className="mt-3 max-h-64 list-decimal overflow-y-auto rounded-md bg-black/[0.02] py-2 pl-8 pr-3 text-xs text-ink-soft">
                  {replay.narrative.map((line, i) => (
                    <li key={i} className="py-0.5">
                      {line}
                    </li>
                  ))}
                </ol>
              )}
            </Card>
          )}

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5 text-ink-soft">
              Event type
              <select value={eventTypeFilter} onChange={(e) => setEventTypeFilter(e.target.value)} className={SELECT_CLASS}>
                <option value="all">All ({trail.events.length})</option>
                {eventTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-ink-soft">
              Decision
              <select value={decisionFilter} onChange={(e) => setDecisionFilter(e.target.value)} className={SELECT_CLASS}>
                <option value="all">All</option>
                <option value="ALLOW">Allow</option>
                <option value="DENY">Deny</option>
                <option value="REQUIRE_CONFIRMATION">Requires confirmation</option>
              </select>
            </label>
            <span className="font-mono text-xs tabular-nums text-ink-faint">
              Showing {filteredEvents.length} of {trail.events.length}
            </span>
          </div>

          <TableWrap>
            <Table className="min-w-[900px]">
              <THead>
                <tr>
                  <Th>Time</Th>
                  <Th>Event</Th>
                  <Th>Actor</Th>
                  <Th>Tool</Th>
                  <Th>Decision</Th>
                  <Th>Rule</Th>
                  <Th>Tokens / cost</Th>
                  <Th>Reason</Th>
                </tr>
              </THead>
              <tbody>
                {filteredEvents.map((e) => (
                  <Tr key={e.id} className="align-top">
                    <Td className="whitespace-nowrap text-ink-faint">{new Date(e.timestamp + "Z").toLocaleTimeString()}</Td>
                    <Td className="whitespace-nowrap font-mono text-xs">{e.event_type}</Td>
                    <Td className="whitespace-nowrap">{e.actor}</Td>
                    <Td className="whitespace-nowrap">{e.tool_name ?? "—"}</Td>
                    <Td className="whitespace-nowrap">
                      <StatusBadge status={e.decision} />
                    </Td>
                    <Td className="whitespace-nowrap text-ink-soft">{e.rule_name ?? "—"}</Td>
                    <Td className="whitespace-nowrap font-mono tabular-nums text-xs">
                      {e.total_tokens != null
                        ? `${e.total_tokens} tok · ₹${((e.cost_paise ?? 0) / 100).toFixed(2)}${e.fallback_used ? " (fallback)" : ""}`
                        : "—"}
                    </Td>
                    <Td className="max-w-md text-ink-soft">{e.reason ?? "—"}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        </>
      )}

      {!trail && !loading && !error && (
        <EmptyState
          icon={ScrollText}
          title="No session loaded"
          description={
            isMerchant ? (
              <>Pick a session from the list above, or paste a session_id directly, to view its full timeline.</>
            ) : (
              <>
                Paste a session_id above — the shopping assistant panel shows the current one under &ldquo;Show audit
                trail&rdquo; — to view its full timeline.
              </>
            )
          }
        />
      )}
    </div>
  );
}

export default function AuditViewerPage() {
  return (
    <RequireAuth>
      <Suspense
        fallback={
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-8">
            <Skeleton className="h-7 w-48" />
            <Skeleton className="h-10 w-full" />
          </div>
        }
      >
        <AuditViewerInner />
      </Suspense>
    </RequireAuth>
  );
}
