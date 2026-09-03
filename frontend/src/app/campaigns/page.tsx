"use client";

import { useEffect, useState } from "react";
import { Megaphone } from "lucide-react";
import { fetchCampaign, fetchCampaigns, fetchContentGaps, fetchSegments } from "@/lib/api";
import type { CampaignDetail, CampaignSummary, ContentGap, Segment } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import { StatusBadge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import MetricCard from "@/components/ui/MetricCard";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

function MarginImpact({ paise: p }: { paise: number }) {
  const cls = p < 0 ? "text-danger" : p > 0 ? "text-success" : "text-ink-soft";
  return <span className={`font-mono tabular-nums ${cls}`}>{paise(p)}</span>;
}

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-black/[0.04] ${className}`} />;
}

function CampaignsPageInner() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [contentGaps, setContentGaps] = useState<ContentGap[]>([]);
  const [selected, setSelected] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSegments(), fetchCampaigns(), fetchContentGaps()])
      .then(([segs, camps, gaps]) => {
        setSegments(segs);
        setCampaigns(camps);
        setContentGaps(gaps);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  async function openCampaign(campaignId: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setSelected(await fetchCampaign(campaignId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Campaigns</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-soft">
          Every number here is either a real deterministic computation (segments, policy decisions) or an
          explicitly simulated one (redemption, revenue) — see docs/046-campaigns.md. Run{" "}
          <code className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[13px] text-ink">
            python campaigns/run.py
          </code>{" "}
          to generate history and campaigns.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>
      )}

      {loading ? (
        <div className="flex flex-col gap-8">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonBlock key={i} className="h-24" />
            ))}
          </div>
          <SkeletonBlock className="h-48" />
        </div>
      ) : segments.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 px-6 py-14 text-center">
          <Megaphone size={22} className="text-ink-faint" />
          <p className="text-sm font-medium text-ink">No campaign history yet</p>
          <p className="max-w-sm text-sm text-ink-soft">
            Run{" "}
            <code className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[13px] text-ink">
              python campaigns/run.py
            </code>{" "}
            from the repo root to generate synthetic history, then reload this page.
          </p>
        </Card>
      ) : (
        <>
          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Segments — deterministic, no LLM
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {segments.map((s) => (
                <MetricCard key={s.name} label={s.name.replace(/_/g, " ")} value={String(s.size)} meta={s.description} />
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Campaign runs</h2>
            <TableWrap>
              <Table className="min-w-[900px]">
                <THead>
                  <tr>
                    <Th>Segment</Th>
                    <Th>Status</Th>
                    <Th align="right">Discount</Th>
                    <Th align="right">Sent</Th>
                    <Th align="right">Blocked</Th>
                    <Th align="right">Control</Th>
                    <Th align="right">Redemptions</Th>
                    <Th align="right">Incremental revenue</Th>
                    <Th align="right">Net margin impact</Th>
                  </tr>
                </THead>
                <tbody>
                  {campaigns.map((c) => (
                    <Tr key={c.campaign_id} onClick={() => openCampaign(c.campaign_id)}>
                      <Td className="font-medium">{c.segment_name.replace(/_/g, " ")}</Td>
                      <Td>
                        <StatusBadge status={c.status} />
                      </Td>
                      {c.status === "completed" && c.measurement && c.proposal ? (
                        <>
                          <Td align="right" numeric>
                            {(c.proposal.discount_pct * 100).toFixed(0)}%
                          </Td>
                          <Td align="right" numeric>
                            {c.measurement.offers_sent}
                          </Td>
                          <Td align="right" numeric>
                            {c.measurement.offers_blocked}
                          </Td>
                          <Td align="right" numeric>
                            {c.measurement.control_size}
                          </Td>
                          <Td align="right" numeric>
                            {c.measurement.redemptions}
                          </Td>
                          <Td align="right" numeric>
                            {paise(c.measurement.incremental_revenue_paise)}
                          </Td>
                          <Td align="right" numeric>
                            <MarginImpact paise={c.measurement.net_margin_impact_paise} />
                          </Td>
                        </>
                      ) : (
                        <Td className="text-ink-faint" colSpan={7}>
                          Refused before any customer was targeted — segment too small
                        </Td>
                      )}
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          </section>

          {detailLoading && <SkeletonBlock className="h-40" />}

          {selected && (
            <Card className="flex flex-col gap-4 p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold tracking-tight text-ink">
                  {selected.segment_name.replace(/_/g, " ")}
                </h2>
                <a
                  href={`/audit?session=${selected.campaign_id}`}
                  className="text-xs font-medium text-accent hover:text-accent-hover"
                >
                  Full audit trail →
                </a>
              </div>

              {selected.proposal && (
                <div className="rounded-lg bg-black/[0.02] p-4 text-sm">
                  <p className="text-ink">
                    <span className="font-mono font-semibold tabular-nums">
                      {(selected.proposal.discount_pct * 100).toFixed(0)}%
                    </span>{" "}
                    off{" "}
                    {selected.proposal.skus.length > 0
                      ? selected.proposal.skus.join(", ")
                      : "personalized per customer (see table below)"}
                  </p>
                  <p className="mt-1.5 text-ink-soft">&ldquo;{selected.proposal.message}&rdquo;</p>
                  <p className="mt-1.5 text-xs text-ink-faint">{selected.proposal.rationale}</p>
                </div>
              )}

              {selected.segment_name === "browse_abandonment" && selected.measurement && (
                <div className="rounded-lg border border-warning/25 bg-warning-soft p-4 text-xs text-warning">
                  <p className="font-medium">
                    Conversion rate for this segment:{" "}
                    <span className="font-mono tabular-nums">
                      {selected.measurement.offers_sent > 0
                        ? `${((selected.measurement.redemptions / selected.measurement.offers_sent) * 100).toFixed(1)}%`
                        : "n/a (no offers sent)"}
                    </span>
                  </p>
                  <p className="mt-1.5 leading-relaxed">
                    Reported separately on purpose: repeated views without a purchase has at least two plausible
                    causes — the price is above what this customer will pay, or the description doesn&rsquo;t answer a
                    question they have. View counts alone can&rsquo;t tell which. A low conversion rate here is
                    evidence worth investigating (check &ldquo;Content gaps&rdquo; below), not proof of either cause.
                  </p>
                </div>
              )}

              {selected.measurement && (
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                  {[
                    ["Treatment revenue", paise(selected.measurement.treatment_revenue_paise)],
                    ["Control revenue", paise(selected.measurement.control_revenue_paise)],
                    ["Control conv. rate", `${(selected.measurement.control_conversion_rate * 100).toFixed(1)}%`],
                    ["Discount cost", paise(selected.measurement.discount_cost_paise)],
                    ["Expected baseline revenue", paise(selected.measurement.expected_baseline_revenue_paise)],
                    ["Incremental revenue", paise(selected.measurement.incremental_revenue_paise)],
                    ["Treatment COGS", paise(selected.measurement.treatment_cogs_paise)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex flex-col gap-0.5">
                      <span className="text-xs text-ink-faint">{label}</span>
                      <span className="font-mono tabular-nums text-ink">{value}</span>
                    </div>
                  ))}
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-ink-faint">Net margin impact</span>
                    <MarginImpact paise={selected.measurement.net_margin_impact_paise} />
                  </div>
                </div>
              )}

              <TableWrap>
                <Table className="min-w-[700px] text-xs">
                  <THead>
                    <tr>
                      <Th>Customer</Th>
                      <Th>Group</Th>
                      <Th>SKU</Th>
                      <Th>Decision</Th>
                      <Th>Rule</Th>
                      <Th align="right">Redeemed</Th>
                      <Th align="right">Revenue</Th>
                      <Th>Reason</Th>
                    </tr>
                  </THead>
                  <tbody>
                    {selected.offers.map((o, i) => (
                      <Tr key={i}>
                        <Td className="whitespace-nowrap">{o.customer_key}</Td>
                        <Td className="whitespace-nowrap capitalize">{o.group}</Td>
                        <Td className="whitespace-nowrap font-mono">{o.sku ?? "—"}</Td>
                        <Td>
                          <StatusBadge status={o.decision} />
                        </Td>
                        <Td className="whitespace-nowrap text-ink-soft">{o.rule_name ?? "—"}</Td>
                        <Td align="right">{o.redeemed ? "Yes" : "No"}</Td>
                        <Td align="right" numeric className="whitespace-nowrap">
                          {paise(o.revenue_paise)}
                        </Td>
                        <Td className="text-ink-soft">{o.reason ?? "—"}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              </TableWrap>
            </Card>
          )}

          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Content gaps</h2>
              <p className="mt-1 text-sm text-ink-soft">
                Questions the shopping assistant couldn&rsquo;t answer from a product&rsquo;s description. Not
                filled in automatically — see docs/046b-browse-abandonment.md for why.
              </p>
            </div>
            {contentGaps.length === 0 ? (
              <Card className="flex flex-col items-center gap-1.5 px-6 py-10 text-center">
                <p className="text-sm font-medium text-ink">Nothing to review yet</p>
                <p className="max-w-sm text-sm text-ink-soft">
                  Content gaps show up here once a buyer asks the assistant something a product&rsquo;s description
                  doesn&rsquo;t answer.
                </p>
              </Card>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {contentGaps.map((g) => (
                  <Card key={g.sku} className="p-4">
                    <p className="text-sm text-ink">
                      <span className="font-mono font-semibold tabular-nums">{g.count}</span> user(s) asked about{" "}
                      <span className="font-mono">{g.sku}</span> — your description doesn&rsquo;t cover this.
                    </p>
                    <ul className="mt-2 flex flex-col gap-1 text-xs text-ink-soft">
                      {g.sample_questions.map((q, i) => (
                        <li key={i} className="border-l-2 border-line pl-2">
                          {q}
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export default function CampaignsPage() {
  return (
    <RequireAuth allow={["merchant"]}>
      <CampaignsPageInner />
    </RequireAuth>
  );
}
