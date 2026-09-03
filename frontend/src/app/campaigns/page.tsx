"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchCampaign, fetchCampaigns, fetchSegments } from "@/lib/api";
import type { CampaignDetail, CampaignSummary, Segment } from "@/lib/types";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

function MarginImpact({ paise: p }: { paise: number }) {
  const cls = p < 0 ? "text-red-600" : p > 0 ? "text-green-600" : "text-gray-500";
  return <span className={`font-medium ${cls}`}>{paise(p)}</span>;
}

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="text-gray-300">—</span>;
  const style = decision === "DENY" ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${style}`}>{decision}</span>;
}

export default function CampaignsPage() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [selected, setSelected] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSegments(), fetchCampaigns()])
      .then(([segs, camps]) => {
        setSegments(segs);
        setCampaigns(camps);
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Campaigns</h1>
          <p className="text-sm text-gray-500">
            Every number here is either a real deterministic computation (segments, policy decisions) or an
            explicitly simulated one (redemption, revenue) — see docs/046-campaigns.md. Run{" "}
            <code className="rounded bg-gray-100 px-1">python campaigns/run.py</code> to generate history and
            campaigns.
          </p>
        </div>
        <Link href="/" className="text-sm text-gray-500 underline hover:text-gray-800">
          ← Shop
        </Link>
      </header>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : segments.length === 0 ? (
        <p className="text-sm text-gray-400">
          No synthetic history yet. Run <code className="rounded bg-gray-100 px-1">python campaigns/run.py</code>{" "}
          from the repo root, then reload this page.
        </p>
      ) : (
        <>
          <section>
            <h2 className="mb-2 text-sm font-semibold text-gray-700">Segments (deterministic, no LLM)</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
              {segments.map((s) => (
                <div key={s.name} className="rounded-md border border-gray-200 p-2 text-xs">
                  <div className="font-medium">{s.name}</div>
                  <div className="text-gray-500">{s.size} member(s)</div>
                  <div className="mt-1 text-gray-400">{s.description}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold text-gray-700">Campaign runs</h2>
            <div className="overflow-x-auto rounded-md border border-gray-200">
              <table className="w-full min-w-[900px] border-collapse text-sm">
                <thead className="bg-gray-50 text-left text-gray-500">
                  <tr>
                    <th className="p-2">Segment</th>
                    <th className="p-2">Status</th>
                    <th className="p-2">Discount</th>
                    <th className="p-2">Sent</th>
                    <th className="p-2">Blocked</th>
                    <th className="p-2">Control</th>
                    <th className="p-2">Redemptions</th>
                    <th className="p-2">Incremental revenue</th>
                    <th className="p-2">Net margin impact</th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((c) => (
                    <tr
                      key={c.campaign_id}
                      onClick={() => openCampaign(c.campaign_id)}
                      className="cursor-pointer border-t border-gray-100 hover:bg-gray-50"
                    >
                      <td className="p-2 font-medium">{c.segment_name}</td>
                      <td className="p-2">{c.status}</td>
                      {c.status === "completed" && c.measurement && c.proposal ? (
                        <>
                          <td className="p-2">{(c.proposal.discount_pct * 100).toFixed(0)}%</td>
                          <td className="p-2">{c.measurement.offers_sent}</td>
                          <td className="p-2">{c.measurement.offers_blocked}</td>
                          <td className="p-2">{c.measurement.control_size}</td>
                          <td className="p-2">{c.measurement.redemptions}</td>
                          <td className="p-2">{paise(c.measurement.incremental_revenue_paise)}</td>
                          <td className="p-2">
                            <MarginImpact paise={c.measurement.net_margin_impact_paise} />
                          </td>
                        </>
                      ) : (
                        <td className="p-2 text-gray-400" colSpan={6}>
                          refused before any customer was targeted — segment too small
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {detailLoading && <p className="text-sm text-gray-400">Loading campaign…</p>}

          {selected && (
            <section className="flex flex-col gap-3 rounded-md border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">{selected.segment_name}</h2>
                <a
                  href={`/audit?session=${selected.campaign_id}`}
                  className="text-xs text-gray-400 underline hover:text-gray-700"
                >
                  Full audit trail →
                </a>
              </div>

              {selected.proposal && (
                <div className="rounded-md bg-gray-50 p-3 text-sm">
                  <p>
                    <strong>{(selected.proposal.discount_pct * 100).toFixed(0)}% off</strong> {selected.proposal.skus.join(", ")}
                  </p>
                  <p className="mt-1 text-gray-700">&ldquo;{selected.proposal.message}&rdquo;</p>
                  <p className="mt-1 text-xs text-gray-400">{selected.proposal.rationale}</p>
                </div>
              )}

              {selected.measurement && (
                <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                  <span>Treatment revenue: <strong>{paise(selected.measurement.treatment_revenue_paise)}</strong></span>
                  <span>Control revenue: <strong>{paise(selected.measurement.control_revenue_paise)}</strong></span>
                  <span>Control conv. rate: <strong>{(selected.measurement.control_conversion_rate * 100).toFixed(1)}%</strong></span>
                  <span>Discount cost: <strong>{paise(selected.measurement.discount_cost_paise)}</strong></span>
                  <span>Expected baseline revenue: <strong>{paise(selected.measurement.expected_baseline_revenue_paise)}</strong></span>
                  <span>Incremental revenue: <strong>{paise(selected.measurement.incremental_revenue_paise)}</strong></span>
                  <span>Treatment COGS: <strong>{paise(selected.measurement.treatment_cogs_paise)}</strong></span>
                  <span>
                    Net margin impact: <MarginImpact paise={selected.measurement.net_margin_impact_paise} />
                  </span>
                </div>
              )}

              <div className="overflow-x-auto rounded-md border border-gray-200">
                <table className="w-full min-w-[700px] border-collapse text-xs">
                  <thead className="bg-gray-50 text-left text-gray-500">
                    <tr>
                      <th className="p-1.5">Customer</th>
                      <th className="p-1.5">Group</th>
                      <th className="p-1.5">Decision</th>
                      <th className="p-1.5">Rule</th>
                      <th className="p-1.5">Redeemed</th>
                      <th className="p-1.5">Revenue</th>
                      <th className="p-1.5">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.offers.map((o, i) => (
                      <tr key={i} className="border-t border-gray-100 align-top">
                        <td className="p-1.5 whitespace-nowrap">{o.customer_key}</td>
                        <td className="p-1.5 whitespace-nowrap">{o.group}</td>
                        <td className="p-1.5"><DecisionBadge decision={o.decision} /></td>
                        <td className="p-1.5 whitespace-nowrap">{o.rule_name ?? "—"}</td>
                        <td className="p-1.5">{o.redeemed ? "yes" : "no"}</td>
                        <td className="p-1.5 whitespace-nowrap">{paise(o.revenue_paise)}</td>
                        <td className="p-1.5">{o.reason ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
