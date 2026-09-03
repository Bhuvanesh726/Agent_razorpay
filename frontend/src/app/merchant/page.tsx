"use client";

import { useEffect, useState } from "react";
import { BellOff, Check, TrendingUp, X } from "lucide-react";
import { actOnNotification, fetchHeadlineNumbers, fetchMerchantNotifications } from "@/lib/api";
import type { HeadlineNumbers, MerchantNotification } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import DevRoleSwitch from "@/components/DevRoleSwitch";
import { useAuth } from "@/lib/auth";
import Button from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import MetricCard from "@/components/ui/MetricCard";
import { Skeleton, SkeletonCards } from "@/components/ui/Skeleton";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

const NOTIFICATION_LABELS: Record<string, string> = {
  UNMET_DEMAND: "Unmet demand",
  OUT_OF_STOCK_DEMAND: "Out-of-stock demand",
  BROWSE_ABANDONMENT: "Browse abandonment",
  ATTRIBUTE_GAP: "Attribute gap",
};

function NotificationCard({ n, onChanged }: { n: MerchantNotification; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(status: "ACTED" | "DISMISSED") {
    setBusy(true);
    setError(null);
    try {
      await actOnNotification(n.id, status);
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
        <div>
          <div className="flex items-center gap-2">
            <Badge variant="accent">{NOTIFICATION_LABELS[n.type] ?? n.type}</Badge>
            <Badge variant={n.status === "NEW" ? "warning" : n.status === "ACTED" ? "success" : "neutral"}>
              {n.status}
            </Badge>
          </div>
          <p className="mt-2 text-sm text-ink">{n.suggested_action}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(n.evidence).map(([k, v]) => (
              <span
                key={k}
                className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-soft"
              >
                {k}: {String(Array.isArray(v) ? v.join(", ") : v)}
              </span>
            ))}
          </div>
          {n.status === "ACTED" && (
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md bg-success-soft px-2.5 py-1.5">
                <TrendingUp size={13} className="text-success" />
                <span className="text-xs font-medium text-success">
                  {n.purchases_since_acted} purchase{n.purchases_since_acted === 1 ? "" : "s"} ·{" "}
                  <span className="font-mono tabular-nums">{paise(n.revenue_since_acted_paise)}</span> since you acted
                </span>
              </div>
              {n.conversions_since_acted > 0 && (
                <span className="text-xs text-ink-faint">
                  {n.conversions_since_acted} matching search{n.conversions_since_acted === 1 ? "" : "es"} also found a
                  result
                </span>
              )}
            </div>
          )}
        </div>
        {n.status === "NEW" && (
          <div className="flex shrink-0 gap-2">
            <Button variant="primary" size="sm" onClick={() => act("ACTED")} disabled={busy}>
              <Check size={13} />
              Mark acted
            </Button>
            <Button variant="secondary" size="sm" onClick={() => act("DISMISSED")} disabled={busy}>
              <X size={13} />
              Dismiss
            </Button>
          </div>
        )}
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </Card>
  );
}

function MerchantDashboardInner() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<MerchantNotification[]>([]);
  const [headline, setHeadline] = useState<HeadlineNumbers | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    Promise.all([fetchMerchantNotifications(), fetchHeadlineNumbers()])
      .then(([n, h]) => {
        setNotifications(n);
        setHeadline(h);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-8">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Merchant dashboard</h1>
          <p className="mt-1 text-sm text-ink-soft">{user?.email}</p>
        </div>
        <DevRoleSwitch />
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <SkeletonCards count={5} className="sm:grid-cols-5" />
      ) : headline ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <MetricCard label="Queries received" value={String(headline.queries_received)} />
          <MetricCard label="Match rate" value={`${(headline.match_rate * 100).toFixed(0)}%`} />
          <MetricCard label="Unmet demand" value={String(headline.unmet_demand_count)} />
          <MetricCard label="Upsell revenue" value={paise(headline.upsell_revenue_paise)} />
          <MetricCard
            label="Campaign net margin"
            value={paise(headline.campaign_net_margin_impact_paise)}
            tone={headline.campaign_net_margin_impact_paise < 0 ? "danger" : "success"}
          />
        </div>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Notifications</h2>
        {loading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : notifications.length === 0 ? (
          <EmptyState
            icon={BellOff}
            title="No notifications yet"
            description="They'll appear here once enough buyers cross a demand threshold — an unmet category, an out-of-stock SKU, or a recurring attribute gap."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {notifications.map((n) => (
              <NotificationCard key={n.id} n={n} onChanged={refresh} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default function MerchantDashboardPage() {
  return (
    <RequireAuth allow={["merchant"]}>
      <MerchantDashboardInner />
    </RequireAuth>
  );
}
