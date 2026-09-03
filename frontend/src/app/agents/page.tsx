"use client";

import { useEffect, useState } from "react";
import { Bot, KeyRound, Play, ShieldOff } from "lucide-react";
import { createAgent, fetchAgent, fetchAgents, revokeAgent, runAgent } from "@/lib/api";
import type { AgentAction, AgentCreateResponse, AgentDetail, AgentSummary } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import FloatingChatLauncher from "@/components/FloatingChatLauncher";
import Button from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import { Input, Label, Textarea } from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

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

function KeyRevealDialog({ agent, onClose }: { agent: AgentCreateResponse; onClose: () => void }) {
  return (
    <Modal onClose={onClose}>
      <div className="flex items-center gap-2">
        <KeyRound size={17} className="text-warning" />
        <h2 className="text-lg font-semibold tracking-tight text-ink">Save this key now</h2>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-ink-soft">
        &ldquo;{agent.name}&rdquo; is an <strong className="text-ink">external</strong> agent credential. This key
        is shown <strong className="text-ink">exactly once</strong> — it is hashed at rest and cannot be recovered
        after you close this dialog. Configure it wherever the external agent runs (e.g.{" "}
        <code className="rounded bg-black/[0.04] px-1 py-0.5 font-mono text-[13px]">AGENT_API_KEY</code> for{" "}
        <code className="rounded bg-black/[0.04] px-1 py-0.5 font-mono text-[13px]">buyer_agent/</code>).
      </p>
      <pre className="mt-3 overflow-x-auto rounded-md bg-ink p-3 font-mono text-xs text-white">{agent.key}</pre>
      <Button variant="primary" onClick={onClose} className="mt-4 w-full justify-center">
        I&rsquo;ve saved it
      </Button>
    </Modal>
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
    <Card>
      <CardHeader>
        <CardTitle>Create an agent</CardTitle>
      </CardHeader>
      <form onSubmit={handleSubmit}>
        <CardBody className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Weekly groceries" />
          </label>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-0.5 text-sm font-medium text-ink">Delivery mode</legend>
            {(
              [
                {
                  value: "EMBEDDED" as const,
                  label: "Embedded",
                  desc: "Runs from this UI. The key is generated and hashed on the server; it is never shown to anyone, including you.",
                },
                {
                  value: "EXTERNAL" as const,
                  label: "External",
                  desc: (
                    <>
                      For a third-party integration (e.g. <code className="font-mono text-xs">buyer_agent/</code>).
                      The key is shown once, right after you create it, for you to configure elsewhere.
                    </>
                  ),
                },
              ] as const
            ).map((opt) => (
              <label
                key={opt.value}
                className={`flex cursor-pointer items-start gap-2.5 rounded-md border p-3 text-sm transition-colors duration-150 ${
                  deliveryMode === opt.value ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong"
                }`}
              >
                <input
                  type="radio"
                  name="delivery-mode"
                  checked={deliveryMode === opt.value}
                  onChange={() => setDeliveryMode(opt.value)}
                  className="mt-0.5 accent-accent"
                />
                <span>
                  <strong className="text-ink">{opt.label}</strong>
                  <span className="block text-ink-soft">{opt.desc}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-0.5 text-sm font-medium text-ink">Scopes — which tools this agent may call</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {AVAILABLE_SCOPES.map((scope) => (
                <label key={scope} className="flex items-center gap-1.5 text-sm text-ink-soft">
                  <input type="checkbox" checked={scopes.has(scope)} onChange={() => toggleScope(scope)} className="accent-accent" />
                  <span className="font-mono text-xs">{scope}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="flex flex-col gap-1.5">
            <Label>Spend limit (₹) — a hard cap across every run of this credential, independent of any session budget</Label>
            <Input type="number" min={1} value={spendLimitInput} onChange={(e) => setSpendLimitInput(e.target.value)} className="w-32" />
          </label>

          <label className="flex flex-col gap-1.5">
            <Label>Standing instruction (used by &ldquo;Run now&rdquo; for an embedded agent — plain language)</Label>
            <Textarea
              value={standingInstruction}
              onChange={(e) => setStandingInstruction(e.target.value)}
              placeholder="e.g. Buy a 5kg bag of atta if it's under ₹300 and in stock."
              rows={2}
            />
          </label>

          {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">{error}</div>}

          <Button type="submit" variant="primary" disabled={submitting} className="self-start">
            {submitting ? "Creating…" : "Create agent"}
          </Button>
        </CardBody>
      </form>
    </Card>
  );
}

function AgentActionRow({ action }: { action: AgentAction }) {
  return (
    <Tr>
      <Td className="whitespace-nowrap text-ink-faint">{new Date(action.timestamp + "Z").toLocaleString()}</Td>
      <Td className="whitespace-nowrap font-mono">{action.event_type}</Td>
      <Td className="whitespace-nowrap">{action.tool_name ?? "—"}</Td>
      <Td className="whitespace-nowrap">
        <StatusBadge status={action.decision} />
      </Td>
      <Td className="whitespace-nowrap text-ink-soft">{action.rule_name ?? "—"}</Td>
      <Td className="text-ink-soft">{action.reason ?? "—"}</Td>
    </Tr>
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
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Bot size={17} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-ink">{agent.name}</h3>
              <StatusBadge status={agent.status} />
              <span className="font-mono text-[11px] uppercase tracking-wide text-ink-faint">{agent.delivery_mode}</span>
            </div>
            <p className="mt-1 text-xs text-ink-soft">
              Spent <span className="font-mono tabular-nums">{rupees(agent.spent_paise)}</span> of{" "}
              <span className="font-mono tabular-nums">{rupees(agent.spend_limit_paise)}</span> limit · Last active{" "}
              {agent.last_used_at ? new Date(agent.last_used_at + "Z").toLocaleString() : "never"} · Created{" "}
              {new Date(agent.created_at + "Z").toLocaleDateString()}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {agent.scopes.map((s) => (
                <span key={s} className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-xs text-ink-soft">
                  {s}
                </span>
              ))}
            </div>
            {agent.standing_instruction && (
              <p className="mt-1.5 text-xs text-ink-soft">
                Standing instruction: <span className="italic">&ldquo;{agent.standing_instruction}&rdquo;</span>
              </p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 gap-2">
          {agent.status === "ACTIVE" && agent.delivery_mode === "EMBEDDED" && agent.standing_instruction && (
            <Button variant="primary" size="sm" onClick={handleRun} disabled={busy}>
              <Play size={13} />
              {busy ? "Running…" : "Run now"}
            </Button>
          )}
          {agent.status === "ACTIVE" && (
            <Button variant="destructive" size="sm" onClick={handleRevoke} disabled={busy}>
              <ShieldOff size={13} />
              Revoke
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={toggleExpand}>
            {expanded ? "Hide" : "Show"} activity
          </Button>
        </div>
      </div>

      {runReply && <div className="mt-3 rounded-lg border border-line bg-black/[0.02] p-3 text-xs text-ink-soft">{runReply}</div>}
      {error && <div className="mt-3 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">{error}</div>}

      {expanded && (
        <div className="mt-3">
          {loadingDetail ? (
            <Skeleton className="h-24" />
          ) : !detail || detail.recent_actions.length === 0 ? (
            <p className="rounded-lg border border-line bg-black/[0.015] p-3 text-xs text-ink-faint">
              No actions recorded for this credential yet.
            </p>
          ) : (
            <TableWrap>
              <Table className="min-w-[640px] text-xs">
                <THead>
                  <tr>
                    <Th>Time</Th>
                    <Th>Event</Th>
                    <Th>Tool</Th>
                    <Th>Decision</Th>
                    <Th>Rule</Th>
                    <Th>Reason</Th>
                  </tr>
                </THead>
                <tbody>
                  {detail.recent_actions.map((a, i) => (
                    <AgentActionRow key={i} action={a} />
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          )}
        </div>
      )}
    </Card>
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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">My agents</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          Grant, run, observe, and revoke — every agent here is bounded by its own spend limit and scopes, enforced
          the same way for every call it makes.
        </p>
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      <CreateAgentForm onCreated={handleCreated} />

      <div className="flex flex-col gap-3">
        {loading ? (
          <>
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </>
        ) : agents.length === 0 ? (
          <EmptyState icon={Bot} title="No agents yet" description="Create one above to get started." />
        ) : (
          agents.map((a) => <AgentCard key={a.id} agent={a} onChanged={refresh} />)
        )}
      </div>

      {revealAgent && <KeyRevealDialog agent={revealAgent} onClose={() => setRevealAgent(null)} />}
      <FloatingChatLauncher />
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
